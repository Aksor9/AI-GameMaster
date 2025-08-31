# File: backend/gm_worker/app/worker.py

# CRITICAL: Eventlet monkey patching must be done before any other standard libraries are imported.
import eventlet
eventlet.monkey_patch()

import logging
from celery import Celery
from .core.config import settings

# --- Logging Configuration ---
# 1. Set up a structured format for all logs from our application.
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s: %(levelname)s/%(name)s] %(message)s'
)

# 2. CRITICAL: Silence the noisy Pika library logs by setting its level to WARNING.
#    This will hide the successful connection/disconnection messages for every task.
#    We will only see logs from Pika if there is a WARNING or an ERROR.
logging.getLogger("pika").setLevel(logging.WARNING)

# 3. Get a logger for this specific module to use for our own application logs.
logger = logging.getLogger(__name__)


# --- Celery App Configuration ---
logger.info(f"GM Worker initializing with broker: {settings.RABBITMQ_URL}")

celery_app = Celery(
    'gm_worker',
    broker=settings.RABBITMQ_URL,
    include=['app.tasks.game_logic']
)

celery_app.conf.update(
    task_track_started=True,
    broker_connection_retry_on_startup=True
)

logger.info("Celery app configured. Worker is ready to receive tasks.")