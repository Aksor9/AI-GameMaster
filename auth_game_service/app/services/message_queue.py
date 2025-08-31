# Reemplaza el contenido de message_queue.py con esto:
import logging
from celery import Celery
from ..core.config import settings

logger = logging.getLogger(__name__)

# Define a Celery app instance configured to talk to the remote broker.
# This instance is ONLY for producing tasks.
producer_celery_app = Celery(
    'auth_service_producer',
    broker=settings.RABBITMQ_URL,
    backend=None, # No need for results
)
producer_celery_app.conf.update(
    task_ignore_result=True,
    task_track_started=False,
    broker_connection_retry_on_startup=True
)

def publish_task(queue_name: str, task_name: str, task_payload: dict):
    """Publishes a task using a Celery producer."""
    try:
        producer_celery_app.send_task(
            name=task_name,
            args=[task_payload],
            queue=queue_name
        )
        logger.info(f"Successfully published task '{task_name}' to queue '{queue_name}' via Celery.")
        return True
    except Exception as e:
        logger.error(f"Error publishing task via Celery: {e}", exc_info=True)
        return False