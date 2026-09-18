from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
import pyotp
from cryptography.fernet import Fernet, InvalidToken as InvalidFernetToken
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from passlib.context import CryptContext
from pwdlib import PasswordHash
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import AuthSession, AuthThrottle, Role, User


password_hash = PasswordHash.recommended()
legacy_password_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)
_dummy_password_hash = password_hash.hash("dummy-password-never-used-by-a-real-user")
_fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode("utf-8")).digest()))


class LoginRateLimiter:
    """Compatibilidade dos testes; o limite real é persistido em AuthThrottle."""

    def clear(self) -> None:
        return None


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _limiter_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def login_retry_after(db: Session, key: str) -> int | None:
    item = db.get(AuthThrottle, _limiter_hash(key))
    if not item:
        return None
    now = utcnow()
    if item.blocked_until and item.blocked_until > now:
        return max(1, int((item.blocked_until - now).total_seconds()))
    if item.window_started_at < now - timedelta(seconds=settings.login_window_seconds):
        db.delete(item)
        db.flush()
    return None


def login_failure(db: Session, key: str) -> None:
    key_hash = _limiter_hash(key)
    item = db.get(AuthThrottle, key_hash)
    now = utcnow()
    if not item or item.window_started_at < now - timedelta(seconds=settings.login_window_seconds):
        if item:
            db.delete(item)
            db.flush()
        item = AuthThrottle(key_hash=key_hash, attempts=0, window_started_at=now)
        db.add(item)
    item.attempts += 1
    if item.attempts >= settings.login_max_attempts:
        excess = item.attempts - settings.login_max_attempts
        delay_minutes = min(settings.account_lock_minutes * (2**excess), 24 * 60)
        item.blocked_until = now + timedelta(minutes=delay_minutes)


def login_success(db: Session, key: str) -> None:
    db.execute(delete(AuthThrottle).where(AuthThrottle.key_hash == _limiter_hash(key)))


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_and_upgrade_password(password: str, encoded: str | None) -> tuple[bool, str | None]:
    candidate = encoded or _dummy_password_hash
    try:
        if candidate.startswith("$pbkdf2-sha256$"):
            valid = legacy_password_context.verify(password, candidate)
            return valid, hash_password(password) if valid and encoded else None
        valid, updated = password_hash.verify_and_update(password, candidate)
        return valid, updated
    except (ValueError, TypeError):
        return False, None


def verify_password(password: str, encoded: str | None) -> bool:
    return verify_and_upgrade_password(password, encoded)[0]


def generate_mfa_secret(user: User) -> tuple[str, str]:
    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=settings.app_name)
    return secret, uri


def encrypt_mfa_secret(secret: str) -> str:
    return _fernet.encrypt(secret.encode("utf-8")).decode("ascii")


def decrypt_mfa_secret(encrypted: str) -> str:
    try:
        return _fernet.decrypt(encrypted.encode("ascii")).decode("utf-8")
    except InvalidFernetToken as exc:
        raise HTTPException(status_code=500, detail="Configuração MFA inválida") from exc


def verify_mfa(user: User, code: str | None) -> bool:
    if not user.mfa_enabled or not user.mfa_secret_encrypted:
        return True
    return bool(code and pyotp.TOTP(decrypt_mfa_secret(user.mfa_secret_encrypted)).verify(code, valid_window=1))


def _encode_token(user: User, session_id: str, token_type: str, expires: datetime) -> str:
    return jwt.encode(
        {
            "sub": str(user.id),
            "role": user.role.value,
            "jti": session_id,
            "type": token_type,
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": expires.replace(tzinfo=timezone.utc),
        },
        settings.secret_key,
        algorithm="HS256",
    )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_token_pair(user: User, db: Session, request: Request | None = None) -> tuple[str, str]:
    now = utcnow()
    session_id = secrets.token_urlsafe(32)
    access_expires = now + timedelta(minutes=settings.access_token_expire_minutes)
    refresh_expires = now + timedelta(minutes=settings.refresh_token_expire_minutes)
    access_token = _encode_token(user, session_id, "access", access_expires)
    refresh_token = _encode_token(user, session_id, "refresh", refresh_expires)
    db.add(
        AuthSession(
            id=session_id,
            user_id=user.id,
            refresh_token_hash=_token_hash(refresh_token),
            expires_at=refresh_expires,
            ip_address=request.client.host if request and request.client else None,
            user_agent=(request.headers.get("user-agent") or "")[:300] if request else None,
            last_seen_at=now,
        )
    )
    return access_token, refresh_token


def _decode(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
        if payload.get("type") != expected_type or not payload.get("jti") or not payload.get("sub"):
            raise InvalidTokenError("tipo de token inválido")
        return payload
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido ou expirado") from exc


def rotate_token_pair(refresh_token: str, db: Session, request: Request | None = None) -> tuple[User, str, str]:
    payload = _decode(refresh_token, "refresh")
    session = db.get(AuthSession, payload["jti"])
    now = utcnow()
    if not session or session.revoked_at is not None or session.expires_at <= now or not secrets.compare_digest(session.refresh_token_hash, _token_hash(refresh_token)):
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada")
    user = db.scalar(select(User).where(User.id == int(payload["sub"]), User.active.is_(True)))
    if not user:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")
    session.revoked_at = now
    access_token, new_refresh_token = create_token_pair(user, db, request)
    return user, access_token, new_refresh_token


def revoke_session(token: str, db: Session) -> None:
    payload = _decode(token, "access")
    session = db.get(AuthSession, payload["jti"])
    if session and session.revoked_at is None:
        session.revoked_at = utcnow()


def token_session_id(token: str) -> str:
    return str(_decode(token, "access")["jti"])


def current_access_token(request: Request, bearer: str | None = Depends(oauth2_scheme)) -> str:
    token = bearer or request.cookies.get("aeroops_access")
    if not token:
        raise HTTPException(status_code=401, detail="Não autenticado")
    return token


def current_user(token: str = Depends(current_access_token), db: Session = Depends(get_db)) -> User:
    payload = _decode(token, "access")
    session = db.get(AuthSession, payload["jti"])
    if not session or session.revoked_at is not None or session.expires_at <= utcnow():
        raise HTTPException(status_code=401, detail="Sessão inválida ou encerrada")
    user = db.scalar(select(User).where(User.id == int(payload["sub"]), User.active.is_(True)))
    if not user:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")
    return user


def allow_roles(*roles: Role):
    def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Perfil sem permissão para esta ação")
        return user

    return dependency
