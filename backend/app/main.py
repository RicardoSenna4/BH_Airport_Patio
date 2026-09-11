from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session, selectinload
from starlette.staticfiles import StaticFiles

from .config import settings
from .database import Base, SessionLocal, engine, get_db
from .models import (
    AnswerStatus, Attachment, AuditLog, ChecklistItem, ChecklistStatus, ChecklistTemplate,
    Equipment, Inspection, InspectionAnswer, InspectionStatus, Occurrence, OccurrenceStatus,
    Role, Severity, User,
)
from .schemas import (
    AttachmentOut, ChecklistCreate, ChecklistOut, ChecklistStatusChange, DashboardSummary,
    EquipmentCreate, EquipmentOut, EquipmentUpdate, GridCellOut, InspectionCreate,
    InspectionOut, OccurrenceOut, OccurrenceTransition, ReportSummary, Token, UserCreate,
    UserOut, UserUpdate,
)
from .security import allow_roles, create_token, current_user, hash_password, verify_password

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

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
    with SessionLocal() as db:
        if db.scalar(select(func.count(User.id))):
            return
        for role in Role:
            db.add(User(name=role.value.title(), email=f"{role.value.lower()}@aeroops.local", password_hash=hash_password("Aero@123"), role=role))
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    seed_users()
    yield


app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


def audit(db: Session, user: User, entity: str, entity_id: int, action: str, details: str | None = None):
    db.add(AuditLog(actor_id=user.id, entity=entity, entity_id=entity_id, action=action, details=details))


def can_view_inspection(item: Inspection, user: User) -> bool:
    return user.role != Role.FISCAL or item.inspector_id == user.id


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.2.0"}


@app.get("/checklists/{inspection_type}")
def checklist(inspection_type: str, _: User = Depends(current_user)):
    return {"type": inspection_type.upper(), "version": 1, "items": [{"item_key": key, "label": label} for key, label in CHECKLIST.get(inspection_type.upper(), CHECKLIST["PATIO"])]}


@app.get("/checklist-templates", response_model=list[ChecklistOut])
def list_checklist_templates(db: Session = Depends(get_db), _: User = Depends(allow_roles(Role.ADMINISTRADOR, Role.COORDENACAO, Role.SUPERVISOR, Role.ANALISTA))):
    return db.scalars(select(ChecklistTemplate).options(selectinload(ChecklistTemplate.items)).order_by(ChecklistTemplate.updated_at.desc())).all()


@app.post("/checklist-templates", response_model=ChecklistOut, status_code=201)
def create_checklist_template(data: ChecklistCreate, db: Session = Depends(get_db), user: User = Depends(allow_roles(Role.ADMINISTRADOR))):
    template = ChecklistTemplate(name=data.name, inspection_type=data.inspection_type.upper(), created_by=user.id, items=[ChecklistItem(**item.model_dump()) for item in data.items])
    db.add(template)
    db.flush()
    audit(db, user, "checklist_template", template.id, "CREATE", f"status={ChecklistStatus.RASCUNHO.value}")
    db.commit()
    db.refresh(template)
    return template


@app.patch("/checklist-templates/{template_id}", response_model=ChecklistOut)
def update_checklist_template(template_id: int, data: ChecklistCreate, db: Session = Depends(get_db), user: User = Depends(allow_roles(Role.ADMINISTRADOR))):
    template = db.scalar(select(ChecklistTemplate).options(selectinload(ChecklistTemplate.items)).where(ChecklistTemplate.id == template_id))
    if not template:
        raise HTTPException(status_code=404, detail="Modelo de checklist não encontrado")
    if template.status == ChecklistStatus.PUBLICADO:
        raise HTTPException(status_code=409, detail="Checklist publicado é imutável; crie uma nova versão")
    template.name, template.inspection_type = data.name, data.inspection_type.upper()
    template.items.clear()
    template.items.extend(ChecklistItem(**item.model_dump()) for item in data.items)
    audit(db, user, "checklist_template", template.id, "UPDATE")
    db.commit()
    db.refresh(template)
    return template


@app.patch("/checklist-templates/{template_id}/status", response_model=ChecklistOut)
def change_checklist_status(template_id: int, data: ChecklistStatusChange, db: Session = Depends(get_db), user: User = Depends(allow_roles(Role.ADMINISTRADOR, Role.COORDENACAO))):
    template = db.scalar(select(ChecklistTemplate).options(selectinload(ChecklistTemplate.items)).where(ChecklistTemplate.id == template_id))
    if not template:
        raise HTTPException(status_code=404, detail="Modelo de checklist não encontrado")
    allowed = {
        Role.ADMINISTRADOR: {ChecklistStatus.RASCUNHO, ChecklistStatus.EM_REVISAO, ChecklistStatus.PUBLICADO, ChecklistStatus.ARQUIVADO},
        Role.COORDENACAO: {ChecklistStatus.EM_REVISAO, ChecklistStatus.PUBLICADO, ChecklistStatus.ARQUIVADO},
    }
    if data.status not in allowed[user.role]:
        raise HTTPException(status_code=403, detail="Perfil sem permissão para este status")
    if data.status == ChecklistStatus.PUBLICADO and not template.items:
        raise HTTPException(status_code=422, detail="Checklist precisa ter ao menos um item")
    previous = template.status.value
    template.status = data.status
    audit(db, user, "checklist_template", template.id, "STATUS_CHANGE", f"from={previous};to={data.status.value}")
    db.commit()
    db.refresh(template)
    return template


@app.get("/grid", response_model=list[GridCellOut])
def operational_grid(db: Session = Depends(get_db), _: User = Depends(current_user)):
    rows = db.execute(select(Occurrence.grid_cell, func.count(Occurrence.id), func.sum(func.cast(Occurrence.severity == Severity.CRITICA, Integer))).group_by(Occurrence.grid_cell)).all()
    counts = {code: (int(total), int(critical or 0)) for code, total, critical in rows}
    return [GridCellOut(code=f"{column}{row}", row=row, column=column, occurrences=counts.get(f"{column}{row}", (0, 0))[0], critical=counts.get(f"{column}{row}", (0, 0))[1]) for row in range(7, 11) for column in "ABCDEF"]


@app.post("/auth/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == form.username, User.active.is_(True)))
    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")
    return Token(access_token=create_token(user), user=user)


@app.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


def _build_inspection(data: InspectionCreate, user: User) -> Inspection:
    return Inspection(
        protocol=f"PAT-{datetime.utcnow():%Y%m%d}-{uuid4().hex[:6].upper()}",
        inspection_type=data.inspection_type.upper(), inspector_id=user.id,
        apron=data.apron, grid_cell=data.grid_cell.upper() if data.grid_cell else None,
        location_text=data.location_text, shift=data.shift, weather=data.weather, notes=data.notes,
        answers=[InspectionAnswer(**answer.model_dump()) for answer in data.answers],
    )


@app.post("/inspections", response_model=InspectionOut, status_code=201)
def create_inspection(data: InspectionCreate, db: Session = Depends(get_db), user: User = Depends(allow_roles(Role.FISCAL, Role.SUPERVISOR))):
    inspection = _build_inspection(data, user)
    db.add(inspection)
    db.flush()
    audit(db, user, "inspection", inspection.id, "CREATE", f"type={inspection.inspection_type}")
    db.commit()
    db.refresh(inspection)
    return inspection


@app.patch("/inspections/{inspection_id}", response_model=InspectionOut)
def update_inspection(inspection_id: int, data: InspectionCreate, db: Session = Depends(get_db), user: User = Depends(allow_roles(Role.FISCAL, Role.SUPERVISOR))):
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
    if user.role == Role.FISCAL:
        query = query.where(Inspection.inspector_id == user.id)
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
def submit_inspection(inspection_id: int, db: Session = Depends(get_db), user: User = Depends(allow_roles(Role.FISCAL, Role.SUPERVISOR))):
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
    item.submitted_at = datetime.utcnow()
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
    if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail="Apenas imagens JPEG, PNG ou WebP são aceitas")
    content = file.file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Arquivo excede o limite de 10 MB")
    safe_name = f"{uuid4().hex}_{Path(file.filename or 'evidencia').name}"
    path = UPLOAD_DIR / safe_name
    path.write_bytes(content)
    attachment = Attachment(inspection_id=inspection_id, occurrence_id=occurrence_id, filename=file.filename or safe_name, content_type=file.content_type, storage_path=f"/uploads/{safe_name}", created_by=user.id)
    db.add(attachment)
    db.flush()
    audit(db, user, "attachment", attachment.id, "UPLOAD", attachment.filename)
    db.commit()
    db.refresh(attachment)
    return attachment


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
    daily = db.execute(select(func.strftime("%Y-%m-%d", Inspection.started_at), func.count(Inspection.id)).group_by(func.strftime("%Y-%m-%d", Inspection.started_at)).order_by(func.strftime("%Y-%m-%d", Inspection.started_at).desc()).limit(14)).all()
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
