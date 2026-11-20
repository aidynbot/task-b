"""Application settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from environment variables."""

    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = (
        "postgresql+psycopg://crm_user:crm_password@localhost:5432/crm_db"
    )
    timezone: str = "Asia/Almaty"


settings = Settings()
