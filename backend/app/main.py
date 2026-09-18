from contextlib import asynccontextmanager
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
import secrets
import socket
import struct
from time import perf_counter
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
import pyotp
from fastapi import Body, Cookie, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import FileResponse, JSONResponse

from .config import settings
from .database import Base, SessionLocal, engine, get_db
from .logging_config import configure_logging
from .models import (
    AnswerStatus, Attachment, AuditLog, AuthEvent,
    Equipment, Inspection, InspectionAnswer, InspectionStatus, Occurrence, OccurrenceStatus,
    AuthSession, Role, Severity, User,
)
from .schemas import (
    AttachmentOut, AuditLogOut, AuthEventOut, DashboardSummary,
    EquipmentCreate, EquipmentOut, EquipmentUpdate, GridCellOut, InspectionCreate,
    InspectionOut, MfaCode, MfaSetupOut, OccurrenceOut, OccurrenceTransition, PasswordChange, RefreshRequest,
    ReportSummary, SessionOut, Token, UserCreate, UserOut, UserUpdate,
)
from .security import (
    LoginRateLimiter, allow_roles, create_token_pair, current_access_token, current_user, decrypt_mfa_secret,
    encrypt_mfa_secret, generate_mfa_secret, hash_password, login_failure, login_retry_after, login_success,
    revoke_session, rotate_token_pair, token_session_id, utcnow, verify_and_upgrade_password, verify_mfa,
)

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
Image.MAX_IMAGE_PIXELS = 25_000_000
logger = configure_logging()
login_limiter = LoginRateLimiter()

CHECKLIST = {
    "PATIO": [
        ("organizacao", "Organização geral do pátio"),
        ("pontes", "Pontes de embarque"),
        ("pavimento", "Pavimento e concreto"),
        ("posicoes", "Posições de aeronaves e marcações"),
        ("sinalizacao", "Sinalização horizontal e vertical"),
        ("credenciais", "Credenciais visíveis"),
        ("equipamentos_irregulares", "Equipamentos irregulares"),
        ("equipamentos_minimos", "Equipamentos mínimos na posição"),
        ("excesso_equipamentos", "Excesso de equipamentos"),
        ("fod_obstaculos", "FOD, obstáculos ou objetos soltos"),
        ("fauna", "Indícios de fauna ou risco operacional"),
    ]
}


def seed_users():
    if not settings.seed_demo_users:
        return
    with SessionLocal() as db:
        if db.scalar(select(func.count(User.id))):
            return
        for role in Role:
            db.add(User(name=role.value.title(), email=f"{role.value.lower()}@aeroops.local", password_hash=hash_password("Aero@123"), role=role))
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_create_schema:
        Base.metadata.create_all(engine)
    seed_users()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.4.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-CSRF-Token", "X-MFA-Code"],
)
if settings.environment == "production":
    app.add_middleware(HTTPSRedirectMiddleware)


@app.middleware("http")
async def request_security_and_logging(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid4().hex
    started = perf_counter()
    client_ip = request.client.host if request.client else None
    explicit_refresh = False
    if request.url.path == "/auth/refresh" and request.headers.get("content-type", "").startswith("application/json"):
        try:
            explicit_refresh = bool((await request.json()).get("refresh_token"))
        except (ValueError, AttributeError):
            pass
    cookie_authenticated = bool(
        request.cookies.get("aeroops_access") or request.cookies.get("aeroops_refresh")
    ) and not request.headers.get("Authorization") and not explicit_refresh
    if (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and cookie_authenticated
        and request.url.path != "/auth/login"
    ):
        csrf_cookie = request.cookies.get("aeroops_csrf")
        csrf_header = request.headers.get("X-CSRF-Token")
        if not csrf_cookie or not csrf_header or not secrets.compare_digest(csrf_cookie, csrf_header):
            return JSONResponse(status_code=403, content={"detail": "Validação CSRF ausente ou inválida"})
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("unhandled_request_error", extra={"request_id": request_id, "method": request.method, "path": request.url.path, "client_ip": client_ip, "event": "request_error"})
        response = JSONResponse(status_code=500, content={"detail": "Erro interno. Informe o código da requisição ao suporte."})
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
    if settings.environment == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    logger.info(
        "request_completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round((perf_counter() - started) * 1000, 2),
            "client_ip": client_ip,
            "event": "http_request",
        },
    )
    return response


def audit(db: Session, user: User, entity: str, entity_id: int, action: str, details: str | None = None):
    db.add(AuditLog(actor_id=user.id, entity=entity, entity_id=entity_id, action=action, details=details))


def auth_event(db: Session, event_type: str, outcome: str, request: Request, user: User | None = None, details: str | None = None):
    db.add(
        AuthEvent(
            actor_id=user.id if user else None,
            event_type=event_type,
            outcome=outcome,
            ip_address=request.client.host if request.client else None,
            details=details,
        )
    )


def set_session_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    common = {"secure": settings.cookie_secure, "httponly": True, "samesite": "strict"}
    response.set_cookie("aeroops_access", access_token, max_age=settings.access_token_expire_minutes * 60, path="/", **common)
    response.set_cookie("aeroops_refresh", refresh_token, max_age=settings.refresh_token_expire_minutes * 60, path="/", **common)
    response.set_cookie(
        "aeroops_csrf",
        secrets.token_urlsafe(32),
        max_age=settings.refresh_token_expire_minutes * 60,
        path="/",
        secure=settings.cookie_secure,
        httponly=False,
        samesite="strict",
    )


def clear_session_cookies(response: Response) -> None:
    for name in ("aeroops_access", "aeroops_refresh", "aeroops_csrf"):
        response.delete_cookie(name, path="/", secure=settings.cookie_secure, samesite="strict")


def can_view_inspection(item: Inspection, user: User) -> bool:
    return item.inspector_id == user.id or user.role in {Role.SUPERVISOR, Role.ANALISTA, Role.COORDENACAO, Role.ADMINISTRADOR}


def can_access_attachment(attachment: Attachment, user: User, db: Session) -> bool:
    if attachment.created_by == user.id or user.role in {Role.SUPERVISOR, Role.ANALISTA, Role.COORDENACAO, Role.ADMINISTRADOR}:
        return True
    inspection_id = attachment.inspection_id
    if not inspection_id and attachment.occurrence_id:
        occurrence = db.get(Occurrence, attachment.occurrence_id)
        inspection_id = occurrence.inspection_id if occurrence else None
    inspection = db.get(Inspection, inspection_id) if inspection_id else None
    return bool(inspection and inspection.inspector_id == user.id)


def scan_for_malware(content: bytes) -> None:
    if not settings.clamav_host:
        if settings.require_malware_scan:
            raise HTTPException(status_code=503, detail="Antivírus temporariamente indisponível")
        return
    try:
        with socket.create_connection((settings.clamav_host, settings.clamav_port), timeout=10) as scanner:
            scanner.sendall(b"zINSTREAM\0")
            for offset in range(0, len(content), 64 * 1024):
                chunk = content[offset:offset + 64 * 1024]
                scanner.sendall(struct.pack(">I", len(chunk)) + chunk)
            scanner.sendall(struct.pack(">I", 0))
            result = scanner.recv(4096).decode("utf-8", errors="replace")
        if "FOUND" in result:
            raise HTTPException(status_code=422, detail="Arquivo rejeitado pela verificação de segurança")
        if "OK" not in result:
            raise OSError(f"resposta inesperada do antivírus: {result[:120]}")
    except HTTPException:
        raise
    except OSError:
        logger.exception("malware_scanner_unavailable", extra={"event": "upload_scan_error"})
        if settings.require_malware_scan:
            raise HTTPException(status_code=503, detail="Antivírus temporariamente indisponível")


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.4.0"}


@app.get("/checklists/{inspection_type}")
def checklist(inspection_type: str, _: User = Depends(current_user)):
    return {"type": inspection_type.upper(), "version": 1, "items": [{"item_key": key, "label": label} for key, label in CHECKLIST.get(inspection_type.upper(), CHECKLIST["PATIO"])]}


@app.get("/grid", response_model=list[GridCellOut])
def operational_grid(db: Session = Depends(get_db), _: User = Depends(current_user)):
    rows = db.execute(select(Occurrence.grid_cell, func.count(Occurrence.id), func.sum(func.cast(Occurrence.severity == Severity.CRITICA, Integer))).group_by(Occurrence.grid_cell)).all()
    counts = {code: (int(total), int(critical or 0)) for code, total, critical in rows}
    return [GridCellOut(code=f"{column}{row}", row=row, column=column, occurrences=counts.get(f"{column}{row}", (0, 0))[0], critical=counts.get(f"{column}{row}", (0, 0))[1]) for row in range(7, 11) for column in "ABCDEF"]


@app.post("/auth/login", response_model=Token)
def login(response: Response, request: Request, form: OAuth2PasswordRequestForm = Depends(), mfa_code: str | None = Form(default=None), db: Session = Depends(get_db)):
    email = form.username.strip().lower()
    ip = request.client.host if request.client else "unknown"
    limiter_key = f"{ip}:{email}"
    retry_after = login_retry_after(db, limiter_key)
    if retry_after is not None:
        auth_event(db, "LOGIN", "RATE_LIMITED", request, details="limite temporário excedido")
        db.commit()
        raise HTTPException(status_code=429, detail="Muitas tentativas. Tente novamente mais tarde.", headers={"Retry-After": str(retry_after)})

    user = db.scalar(select(User).where(func.lower(User.email) == email))
    now = utcnow()
    if user and user.locked_until and user.locked_until > now:
        auth_event(db, "LOGIN", "LOCKED", request, user)
        db.commit()
        seconds = max(1, int((user.locked_until - now).total_seconds()))
        raise HTTPException(status_code=429, detail="Conta temporariamente bloqueada.", headers={"Retry-After": str(seconds)})

    valid, upgraded_hash = verify_and_upgrade_password(form.password, user.password_hash if user else None)
    if not user or not user.active or not valid:
        login_failure(db, limiter_key)
        if user:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.login_max_attempts:
                user.locked_until = now + timedelta(minutes=settings.account_lock_minutes)
                user.failed_login_attempts = 0
        auth_event(db, "LOGIN", "FAILURE", request, user, "credenciais rejeitadas")
        db.commit()
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    if settings.require_privileged_mfa and user.role in {Role.ADMINISTRADOR, Role.COORDENACAO} and not user.mfa_enabled:
        auth_event(db, "LOGIN", "MFA_ENROLLMENT_REQUIRED", request, user)
        db.commit()
        raise HTTPException(status_code=403, detail="MFA obrigatório para este perfil; solicite o processo de ativação")
    if not verify_mfa(user, mfa_code):
        auth_event(db, "LOGIN", "MFA_FAILURE", request, user)
        db.commit()
        raise HTTPException(status_code=401, detail="Código MFA obrigatório ou inválido")

    login_success(db, limiter_key)
    user.failed_login_attempts = 0
    user.locked_until = None
    if upgraded_hash:
        user.password_hash = upgraded_hash
        user.password_changed_at = now
    access_token, refresh_token = create_token_pair(user, db, request)
    auth_event(db, "LOGIN", "SUCCESS", request, user)
    db.commit()
    set_session_cookies(response, access_token, refresh_token)
    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=user,
    )


@app.post("/auth/refresh", response_model=Token)
def refresh_session(response: Response, request: Request, data: RefreshRequest | None = Body(default=None), refresh_cookie: str | None = Cookie(default=None, alias="aeroops_refresh"), db: Session = Depends(get_db)):
    supplied_token = (data.refresh_token if data else None) or refresh_cookie
    if not supplied_token:
        raise HTTPException(status_code=401, detail="Refresh token ausente")
    user, access_token, refresh_token = rotate_token_pair(supplied_token, db, request)
    auth_event(db, "TOKEN_REFRESH", "SUCCESS", request, user)
    db.commit()
    set_session_cookies(response, access_token, refresh_token)
    return Token(access_token=access_token, refresh_token=refresh_token, expires_in=settings.access_token_expire_minutes * 60, user=user)


@app.post("/auth/logout", status_code=204)
def logout(
    response: Response,
    request: Request,
    token: str = Depends(current_access_token),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    revoke_session(token, db)
    auth_event(db, "LOGOUT", "SUCCESS", request, user)
    db.commit()
    clear_session_cookies(response)
    response.status_code = 204
    return response


@app.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@app.get("/auth/sessions", response_model=list[SessionOut])
def list_sessions(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return db.scalars(select(AuthSession).where(AuthSession.user_id == user.id).order_by(AuthSession.created_at.desc())).all()


@app.delete("/auth/sessions/{session_id}", status_code=204)
def end_session(session_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    session = db.get(AuthSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    session.revoked_at = utcnow()
    db.commit()
    return Response(status_code=204)


@app.post("/auth/password", status_code=204)
def change_password(data: PasswordChange, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not verify_and_upgrade_password(data.current_password, user.password_hash)[0]:
        raise HTTPException(status_code=401, detail="Senha atual inválida")
    if verify_and_upgrade_password(data.new_password, user.password_hash)[0]:
        raise HTTPException(status_code=422, detail="A nova senha deve ser diferente da atual")
    user.password_hash = hash_password(data.new_password)
    user.password_changed_at = utcnow()
    for session in db.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))):
        session.revoked_at = utcnow()
    auth_event(db, "PASSWORD_CHANGE", "SUCCESS", request, user)
    db.commit()
    return Response(status_code=204)


@app.post("/auth/mfa/setup", response_model=MfaSetupOut)
def setup_mfa(db: Session = Depends(get_db), user: User = Depends(current_user)):
    secret, uri = generate_mfa_secret(user)
    user.mfa_secret_encrypted = encrypt_mfa_secret(secret)
    user.mfa_enabled = False
    db.commit()
    return MfaSetupOut(secret=secret, provisioning_uri=uri)


@app.post("/auth/mfa/confirm", status_code=204)
def confirm_mfa(data: MfaCode, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not user.mfa_secret_encrypted or not pyotp.TOTP(decrypt_mfa_secret(user.mfa_secret_encrypted)).verify(data.code, valid_window=1):
        raise HTTPException(status_code=422, detail="Código MFA inválido")
    user.mfa_enabled = True
    auth_event(db, "MFA_ENABLE", "SUCCESS", request, user)
    db.commit()
    return Response(status_code=204)


@app.delete("/auth/mfa", status_code=204)
def disable_mfa(data: MfaCode, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not user.mfa_enabled or not verify_mfa(user, data.code):
        raise HTTPException(status_code=422, detail="Código MFA inválido")
    user.mfa_enabled = False
    user.mfa_secret_encrypted = None
    auth_event(db, "MFA_DISABLE", "SUCCESS", request, user)
    db.commit()
    return Response(status_code=204)


def _build_inspection(data: InspectionCreate, user: User) -> Inspection:
    return Inspection(
        protocol=f"PAT-{utcnow():%Y%m%d}-{uuid4().hex[:6].upper()}",
        inspection_type=data.inspection_type.upper(), inspector_id=user.id,
        apron=data.apron, grid_cell=data.grid_cell.upper() if data.grid_cell else None,
        location_text=data.location_text, shift=data.shift, weather=data.weather, notes=data.notes,
        answers=[InspectionAnswer(**answer.model_dump()) for answer in data.answers],
    )


@app.post("/inspections", response_model=InspectionOut, status_code=201)
def create_inspection(data: InspectionCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    inspection = _build_inspection(data, user)
    db.add(inspection)
    db.flush()
    audit(db, user, "inspection", inspection.id, "CREATE", f"type={inspection.inspection_type}")
    db.commit()
    db.refresh(inspection)
    return inspection


@app.patch("/inspections/{inspection_id}", response_model=InspectionOut)
def update_inspection(inspection_id: int, data: InspectionCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = db.scalar(select(Inspection).options(selectinload(Inspection.answers)).where(Inspection.id == inspection_id))
    if not item or item.inspector_id != user.id:
        raise HTTPException(status_code=404, detail="Inspeção não encontrada")
    if item.status != InspectionStatus.RASCUNHO:
        raise HTTPException(status_code=409, detail="Inspeção enviada é imutável; use adendo ou nova versão")
    item.inspection_type, item.apron, item.grid_cell = data.inspection_type.upper(), data.apron, data.grid_cell.upper() if data.grid_cell else None
    item.location_text, item.shift, item.weather, item.notes = data.location_text, data.shift, data.weather, data.notes
    item.answers.clear()
    item.answers.extend(InspectionAnswer(**answer.model_dump()) for answer in data.answers)
    audit(db, user, "inspection", item.id, "UPDATE_DRAFT")
    db.commit()
    db.refresh(item)
    return item


@app.get("/inspections", response_model=list[InspectionOut])
def list_inspections(status_filter: InspectionStatus | None = Query(None, alias="status"), inspection_type: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    query = select(Inspection).options(selectinload(Inspection.answers)).order_by(Inspection.started_at.desc())
    if status_filter:
        query = query.where(Inspection.status == status_filter)
    if inspection_type:
        query = query.where(Inspection.inspection_type == inspection_type.upper())
    return db.scalars(query).all()


@app.get("/inspections/{inspection_id}", response_model=InspectionOut)
def get_inspection(inspection_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = db.scalar(select(Inspection).options(selectinload(Inspection.answers)).where(Inspection.id == inspection_id))
    if not item or not can_view_inspection(item, user):
        raise HTTPException(status_code=404, detail="Inspeção não encontrada")
    return item


@app.post("/inspections/{inspection_id}/submit", response_model=InspectionOut)
def submit_inspection(inspection_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = db.scalar(select(Inspection).options(selectinload(Inspection.answers)).where(Inspection.id == inspection_id, Inspection.inspector_id == user.id))
    if not item:
        raise HTTPException(status_code=404, detail="Inspeção não encontrada")
    if item.status != InspectionStatus.RASCUNHO:
        raise HTTPException(status_code=409, detail="Inspeção já enviada")
    if not item.answers or any(answer.status is None for answer in item.answers):
        raise HTTPException(status_code=422, detail="Todos os itens do checklist devem ser respondidos")
    for answer in item.answers:
        if answer.status == AnswerStatus.NAO_CONFORME:
            if not answer.observation or not answer.severity or not answer.evidence_url or not (answer.grid_cell or item.grid_cell):
                raise HTTPException(status_code=422, detail=f"Não conformidade incompleta: {answer.label}")
            db.add(Occurrence(inspection_id=item.id, answer_id=answer.id, title=answer.label, description=answer.observation, grid_cell=(answer.grid_cell or item.grid_cell).upper(), severity=answer.severity, status=OccurrenceStatus.EM_VALIDACAO))
    item.status = InspectionStatus.CONCLUIDA
    item.submitted_at = utcnow()
    audit(db, user, "inspection", item.id, "SUBMIT")
    db.commit()
    db.refresh(item)
    return item


@app.get("/occurrences", response_model=list[OccurrenceOut])
def list_occurrences(status_filter: OccurrenceStatus | None = Query(None, alias="status"), db: Session = Depends(get_db), _: User = Depends(current_user)):
    query = select(Occurrence).order_by(Occurrence.created_at.desc())
    if status_filter:
        query = query.where(Occurrence.status == status_filter)
    return db.scalars(query).all()


@app.patch("/occurrences/{occurrence_id}/status", response_model=OccurrenceOut)
def transition_occurrence(occurrence_id: int, data: OccurrenceTransition, db: Session = Depends(get_db), user: User = Depends(allow_roles(Role.SUPERVISOR, Role.ANALISTA))):
    occurrence = db.get(Occurrence, occurrence_id)
    if not occurrence:
        raise HTTPException(status_code=404, detail="Ocorrência não encontrada")
    if user.role == Role.SUPERVISOR:
        allowed = {OccurrenceStatus.VALIDADA, OccurrenceStatus.REJEITADA}
        if occurrence.status != OccurrenceStatus.EM_VALIDACAO or data.status not in allowed:
            raise HTTPException(status_code=409, detail="Supervisor só pode decidir ocorrências em validação")
    else:
        allowed = {OccurrenceStatus.EM_TRATAMENTO, OccurrenceStatus.RESOLVIDA}
        if (occurrence.status, data.status) not in {(OccurrenceStatus.VALIDADA, OccurrenceStatus.EM_TRATAMENTO), (OccurrenceStatus.EM_TRATAMENTO, OccurrenceStatus.RESOLVIDA)}:
            raise HTTPException(status_code=409, detail="Transição incompatível com o estado atual")
    previous = occurrence.status.value
    occurrence.status, occurrence.decision_note, occurrence.assigned_to = data.status, data.note, user.id
    audit(db, user, "occurrence", occurrence.id, "STATUS_CHANGE", f"from={previous};to={data.status.value};note={data.note}")
    db.commit()
    db.refresh(occurrence)
    return occurrence


@app.post("/attachments", response_model=AttachmentOut, status_code=201)
def upload_attachment(file: UploadFile = File(...), inspection_id: int | None = None, occurrence_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if (inspection_id is None) == (occurrence_id is None):
        raise HTTPException(status_code=422, detail="Informe exatamente uma inspeção ou ocorrência")
    declared_type = file.content_type or ""
    allowed_types = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
    if declared_type not in allowed_types:
        raise HTTPException(status_code=415, detail="Apenas imagens JPEG, PNG, WebP ou PDF são aceitas")
    content = file.file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail=f"Arquivo excede o limite de {settings.max_upload_bytes // (1024 * 1024)} MB")

    linked_inspection: Inspection | None = None
    if inspection_id is not None:
        linked_inspection = db.get(Inspection, inspection_id)
        if not linked_inspection:
            raise HTTPException(status_code=404, detail="Inspeção não encontrada")
    if occurrence_id is not None:
        occurrence = db.get(Occurrence, occurrence_id)
        if not occurrence:
            raise HTTPException(status_code=404, detail="Ocorrência não encontrada")
        linked_inspection = db.get(Inspection, occurrence.inspection_id)
    if not linked_inspection or not can_view_inspection(linked_inspection, user):
        raise HTTPException(status_code=403, detail="Sem permissão para anexar neste registro")

    existing = db.scalars(select(Attachment).where(Attachment.inspection_id == linked_inspection.id)).all()
    total_bytes = sum(
        (UPLOAD_DIR / item.storage_key).stat().st_size
        for item in existing
        if item.storage_key and (UPLOAD_DIR / item.storage_key).is_file()
    )
    if total_bytes + len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="A inspeção atingiu o limite total de 50 MB em anexos")

    if declared_type.startswith("image/"):
        expected_formats = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
        try:
            source = Image.open(BytesIO(content))
            source.verify()
            source = Image.open(BytesIO(content))
            if source.format != expected_formats[declared_type]:
                raise ValueError("formato divergente")
            detected_format = source.format
            source = ImageOps.exif_transpose(source)
            source.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            output = BytesIO()
            if detected_format == "JPEG":
                source.convert("RGB").save(output, format="JPEG", quality=88, optimize=True)
            elif detected_format == "PNG":
                source.save(output, format="PNG", optimize=True)
            else:
                source.save(output, format="WEBP", quality=88, method=6)
            content = output.getvalue()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            raise HTTPException(status_code=415, detail="Imagem inválida ou potencialmente maliciosa")
    else:
        tail = content[-2048:]
        active_markers = (b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile")
        if not content.startswith(b"%PDF-") or b"%%EOF" not in tail or any(marker in content for marker in active_markers):
            raise HTTPException(status_code=415, detail="PDF inválido ou com conteúdo ativo não permitido")

    scan_for_malware(content)
    extension = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf"}[declared_type]
    storage_key = f"{uuid4().hex}{extension}"
    original_name = Path(file.filename or f"evidencia{extension}").name[:255]
    path = UPLOAD_DIR / storage_key
    path.write_bytes(content)
    attachment = Attachment(
        inspection_id=inspection_id,
        occurrence_id=occurrence_id,
        filename=original_name,
        content_type=declared_type,
        storage_path="pending",
        storage_key=storage_key,
        created_by=user.id,
    )
    db.add(attachment)
    try:
        db.flush()
        attachment.storage_path = f"/attachments/{attachment.id}/content"
        audit(db, user, "attachment", attachment.id, "UPLOAD", f"type={declared_type};bytes={len(content)}")
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    db.refresh(attachment)
    return attachment


@app.get("/attachments/{attachment_id}/content")
def attachment_content(attachment_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    attachment = db.get(Attachment, attachment_id)
    if not attachment or not attachment.storage_key:
        raise HTTPException(status_code=404, detail="Anexo não encontrado")
    if not can_access_attachment(attachment, user, db):
        raise HTTPException(status_code=403, detail="Sem permissão para visualizar este anexo")
    path = UPLOAD_DIR / attachment.storage_key
    if not path.is_file() or path.parent != UPLOAD_DIR:
        raise HTTPException(status_code=404, detail="Arquivo do anexo não encontrado")
    return FileResponse(path, media_type=attachment.content_type, filename=attachment.filename)


@app.post("/equipment", response_model=EquipmentOut, status_code=201)
def create_equipment(data: EquipmentCreate, db: Session = Depends(get_db), user: User = Depends(allow_roles(Role.ANALISTA, Role.COORDENACAO, Role.ADMINISTRADOR))):
    equipment = Equipment(**data.model_dump())
    db.add(equipment)
    db.flush()
    audit(db, user, "equipment", equipment.id, "CREATE")
    db.commit()
    db.refresh(equipment)
    return equipment


@app.get("/equipment", response_model=list[EquipmentOut])
def list_equipment(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return db.scalars(select(Equipment).order_by(Equipment.next_inspection)).all()


@app.patch("/equipment/{equipment_id}", response_model=EquipmentOut)
def update_equipment(equipment_id: int, data: EquipmentUpdate, db: Session = Depends(get_db), user: User = Depends(allow_roles(Role.ANALISTA, Role.COORDENACAO, Role.ADMINISTRADOR))):
    equipment = db.get(Equipment, equipment_id)
    if not equipment:
        raise HTTPException(status_code=404, detail="Equipamento não encontrado")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(equipment, key, value)
    audit(db, user, "equipment", equipment.id, "UPDATE")
    db.commit()
    db.refresh(equipment)
    return equipment


@app.get("/equipment/alerts", response_model=list[EquipmentOut])
def equipment_alerts(days: int = Query(30, ge=0, le=365), db: Session = Depends(get_db), _: User = Depends(current_user)):
    limit = date.today() + timedelta(days=days)
    return db.scalars(select(Equipment).where(Equipment.active.is_(True), Equipment.next_inspection <= limit).order_by(Equipment.next_inspection)).all()


@app.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(allow_roles(Role.ADMINISTRADOR, Role.COORDENACAO))):
    return db.scalars(select(User).order_by(User.name)).all()


@app.get("/audit/auth-events", response_model=list[AuthEventOut])
def list_auth_events(limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db), _: User = Depends(allow_roles(Role.ADMINISTRADOR, Role.COORDENACAO))):
    return db.scalars(select(AuthEvent).order_by(AuthEvent.created_at.desc()).limit(limit)).all()


@app.get("/audit/changes", response_model=list[AuditLogOut])
def list_audit_changes(limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db), _: User = Depends(allow_roles(Role.ADMINISTRADOR, Role.COORDENACAO))):
    return db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)).all()


@app.post("/users", response_model=UserOut, status_code=201)
def create_user(data: UserCreate, db: Session = Depends(get_db), user: User = Depends(allow_roles(Role.ADMINISTRADOR))):
    if db.scalar(select(User).where(User.email == data.email)):
        raise HTTPException(status_code=409, detail="E-mail já cadastrado")
    created = User(name=data.name, email=data.email, password_hash=hash_password(data.password), role=data.role)
    db.add(created)
    db.flush()
    audit(db, user, "user", created.id, "CREATE")
    db.commit()
    db.refresh(created)
    return created


@app.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserUpdate, db: Session = Depends(get_db), user: User = Depends(allow_roles(Role.ADMINISTRADOR))):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(target, key, value)
    audit(db, user, "user", target.id, "UPDATE")
    db.commit()
    db.refresh(target)
    return target


@app.get("/reports/summary", response_model=ReportSummary)
def reports_summary(db: Session = Depends(get_db), _: User = Depends(current_user)):
    inspection_day = func.date(Inspection.started_at)
    daily = db.execute(select(inspection_day, func.count(Inspection.id)).group_by(inspection_day).order_by(inspection_day.desc()).limit(14)).all()
    areas = db.execute(select(Inspection.apron, func.count(Occurrence.id)).join(Occurrence, Occurrence.inspection_id == Inspection.id).group_by(Inspection.apron)).all()
    fiscal = db.execute(select(User.name, func.count(Inspection.id)).join(Inspection, Inspection.inspector_id == User.id).group_by(User.name)).all()
    return ReportSummary(inspections_by_day={str(day): total for day, total in daily}, occurrences_by_area={area: total for area, total in areas}, productivity_by_fiscal={name: total for name, total in fiscal})


@app.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard(db: Session = Depends(get_db), _: User = Depends(current_user)):
    inspections = db.scalar(select(func.count(Inspection.id))) or 0
    open_states = [OccurrenceStatus.ABERTA, OccurrenceStatus.EM_VALIDACAO, OccurrenceStatus.VALIDADA, OccurrenceStatus.EM_TRATAMENTO]
    open_count = db.scalar(select(func.count(Occurrence.id)).where(Occurrence.status.in_(open_states))) or 0
    critical = db.scalar(select(func.count(Occurrence.id)).where(Occurrence.status.in_(open_states), Occurrence.severity == Severity.CRITICA)) or 0
    expiring = db.scalar(select(func.count(Equipment.id)).where(Equipment.active.is_(True), Equipment.next_inspection <= date.today() + timedelta(days=30))) or 0
    by_status = db.execute(select(Occurrence.status, func.count(Occurrence.id)).group_by(Occurrence.status)).all()
    by_severity = db.execute(select(Occurrence.severity, func.count(Occurrence.id)).group_by(Occurrence.severity)).all()
    by_type = db.execute(select(Inspection.inspection_type, func.count(Inspection.id)).group_by(Inspection.inspection_type)).all()
    return DashboardSummary(inspections_total=inspections, inspections_by_type={key: count for key, count in by_type}, occurrences_open=open_count, critical_open=critical, equipment_expiring_30_days=expiring, occurrences_by_status={status.value: count for status, count in by_status}, occurrences_by_severity={severity.value: count for severity, count in by_severity})
