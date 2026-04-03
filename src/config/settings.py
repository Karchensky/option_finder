"""Pydantic-settings configuration loaded from .env."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings sourced from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = Field(description="PostgreSQL async connection string")

    # Polygon.io API
    polygon_api_key: str = Field(description="Polygon.io REST API key")
    polygon_s3_access_key: str = Field(default="", description="Flat-files S3 access key")
    polygon_s3_secret_key: str = Field(default="", description="Flat-files S3 secret key")
    polygon_flatfiles_endpoint: str = Field(default="https://files.polygon.io")
    polygon_flatfiles_bucket: str = Field(default="flatfiles")
    polygon_flatfiles_prefix: str = Field(default="us_options_opra/day_aggs_v1")

    # Email / Alerts
    sender_email: str = Field(default="")
    email_password: str = Field(default="")
    recipient_email: str = Field(default="")
    smtp_server: str = Field(default="smtp.gmail.com")
    smtp_port: int = Field(default=465)

    # Anomaly detection
    anomaly_alert_min_score: float = Field(default=7.5, description="Composite score threshold for alerts")
    anomaly_email_enabled: bool = Field(default=False, description="Kill-switch for email delivery")

    @property
    def async_database_url(self) -> str:
        """Return the database URL with the asyncpg driver."""
        url = self.database_url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
