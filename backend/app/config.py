from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AeroOps BH"
    environment: Literal["development", "test", "staging", "production"] = "development"
    database_url: str = "sqlite:///./aeroops.db"
    secret_key: str = "change-me-before-production"
    access_token_expire_minutes: int = 30
    refresh_token_expire_minutes: int = 480
    jwt_issuer: str = "aeroops-bh"
    jwt_audience: str = "aeroops-web"
    cors_origins: str = "http://localhost:5173"
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    login_max_attempts: int = 5
    login_window_seconds: int = 900
    account_lock_minutes: int = 15
    max_upload_bytes: int = 10 * 1024 * 1024
    clamav_host: str | None = None
    clamav_port: int = 3310
    require_malware_scan: bool = False
    seed_demo_users: bool = True
    auto_create_schema: bool = True
    docs_enabled: bool = True
    cookie_secure: bool = False
    require_privileged_mfa: bool = False
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    @model_validator(mode="after")
    def validate_production_security(self):
        if self.environment != "production":
            return self
        if len(self.secret_key) < 32 or self.secret_key == "change-me-before-production":
            raise ValueError("SECRET_KEY de produção deve ser aleatória e ter ao menos 32 caracteres")
        if self.database_url.startswith("sqlite"):
            raise ValueError("produção exige PostgreSQL")
        if self.seed_demo_users or self.auto_create_schema:
            raise ValueError("SEED_DEMO_USERS e AUTO_CREATE_SCHEMA devem ser false em produção")
        if not self.cookie_secure or not self.require_privileged_mfa or self.docs_enabled:
            raise ValueError("produção exige COOKIE_SECURE=true, REQUIRE_PRIVILEGED_MFA=true e DOCS_ENABLED=false")
        if not self.require_malware_scan or not self.clamav_host:
            raise ValueError("produção exige REQUIRE_MALWARE_SCAN=true e CLAMAV_HOST configurado")
        if any(origin.startswith("http://") or "localhost" in origin or "127.0.0.1" in origin for origin in self.cors_origin_list):
            raise ValueError("CORS_ORIGINS de produção deve conter somente origens HTTPS oficiais")
        if "sslmode=verify-full" not in self.database_url or "sslrootcert=" not in self.database_url:
            raise ValueError("produção exige PostgreSQL com sslmode=verify-full e sslrootcert")
        return self


settings = Settings()
