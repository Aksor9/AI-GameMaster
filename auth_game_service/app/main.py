import logging
import pika
import json
import threading
import asyncio
import time
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .core.config import settings
from .api.endpoints import router as api_router
from .api.connection_manager import manager
from .services import database_service

logging.getLogger("pika").setLevel(logging.WARNING)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Narrador - Auth & Game Service")

origins = [
    "http://localhost",
    "http://localhost:8080",
    "https://aksor9.github.io", 
]

def setup_rabbitmq_listener(loop: asyncio.AbstractEventLoop):
    """Sets up a robust, auto-reconnecting RabbitMQ consumer in a dedicated thread."""
    def consume():
        try:
            logger.info("Listener thread: Attempting to connect to RabbitMQ...")
            connection = pika.BlockingConnection(pika.URLParameters(settings.RABBITMQ_URL))
            channel = connection.channel()
            channel.queue_declare(queue='gm_results', durable=True)
            logger.info("Listener thread: RabbitMQ connection established, waiting for results.")

            def callback(ch, method, properties, body):
                try:
                    # --- FINAL FIX: The gm_worker now publishes simple JSON via Pika. ---
                    # We can load the message body directly.
                    message = json.loads(body)

                    client_id = message.get("client_id")
                    result = message.get("result")
                    
                    if client_id and result:
                        logger.info(f"Received result for client {client_id}. Forwarding...")
                        asyncio.run_coroutine_threadsafe(
                            manager.send_personal_message(result, client_id),
                            loop
                        )
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as e:
                    logger.error(f"Error processing result message: {e}", exc_info=True)

            channel.basic_consume(queue='gm_results', on_message_callback=callback)
            channel.start_consuming()
        except pika.exceptions.AMQPConnectionError:
            logger.warning("Listener thread: RabbitMQ connection failed. Retrying in 5 seconds...")
            time.sleep(5)
        except Exception as e:
            logger.error(f"Listener thread: A critical error occurred: {e}. Retrying...", exc_info=True)
            time.sleep(5)
    
    while True:
        consume()

@app.on_event("startup")
def startup_event():
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    listener_thread = threading.Thread(target=setup_rabbitmq_listener, args=(loop,), daemon=True)
    listener_thread.start()
    
    logger.info("Initializing database...")
    database_service.init_db()
    
    logger.info("Auth & Game Service startup complete.")

@app.get("/", tags=["Health Check"])
def read_root():
    return {"message": "Auth & Game Service is running"}

app.include_router(api_router)