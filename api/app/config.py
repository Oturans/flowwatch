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

    class Config:
        env_file = ".env"
        extra = "allow"


@lru_cache()
def get_settings() -> Settings:
    return Settings()