from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "flowwatch",
    broker=settings.redis_broker,
    backend=settings.redis_result_backend,
    include=["app.tasks.tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    result_expires=604800,  # 7 days
    task_default_retry_delay=60,
    task_default_max_retries=5,
)