# File: backend/auth_game_service/app/celery_app.py

from celery import Celery
from .core.config import settings

# This file now becomes the single source of truth for the Celery application instance.

celery_app = Celery(
    'auth_game_service_worker',
    broker=settings.RABBITMQ_URL,
    backend=None
)

celery_app.conf.update(
    task_ignore_result=True,
    task_track_started=False,
    broker_connection_retry_on_startup=True
)