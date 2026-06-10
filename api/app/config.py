from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://flowwatch:pw@localhost:5432/flowwatch"
    database_url_sync: str = "postgresql+psycopg2://flowwatch:pw@localhost:5432/flowwatch"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_broker: str = "redis://localhost:6379/0"
    redis_result_backend: str = "redis://localhost:6379/1"
    redis_rate_limit_db: int = 2
    redis_pubsub_db: int = 3

    # App
    app_name: str = "FlowWatch"
    debug: bool = False
    secret_key: str = "change-me-in-production"

    # Rate limiting
    rate_limit_per_minute: int = 100

    # Slack
    slack_webhook_url: str = ""

    # Resend Email
    resend_api_key: str = ""
    alert_email_from: str = "FlowWatch <alerts@flowwatch.app>"
    alert_email_to: str = ""

    # JWT (Sprint 1 — multi-tenant auth)
    # Reuse ``secret_key`` as the JWT signing secret by default; in
    # production set ``jwt_secret`` to a dedicated value.
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 60
    jwt_refresh_ttl_minutes: int = 60 * 24 * 7  # 7 days

    class Config:
        env_file = ".env"
        extra = "allow"


@lru_cache()
def get_settings() -> Settings:
    s = Settings()
    # Default JWT secret to secret_key if not explicitly set
    if not s.jwt_secret:
        # Use object.__setattr__ because the model is frozen in spirit;
        # pydantic-settings allows this for computed defaults.
        object.__setattr__(s, "jwt_secret", s.secret_key)
    return s