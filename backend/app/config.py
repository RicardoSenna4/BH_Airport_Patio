from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AeroOps BH"
    database_url: str = "sqlite:///./aeroops.db"
    secret_key: str = "change-me-before-production"
    token_expire_minutes: int = 480
    cors_origins: str = "http://localhost:5173"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
