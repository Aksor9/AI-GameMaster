#!/bin/bash

# Lanza un servidor web simple en segundo plano en el puerto que Render nos asigne.
# Su única función es responder a los health checks de Render.
echo "Starting health check server..."
python3 -m http.server ${PORT:-10000} &

# Lanza el worker de Celery como el proceso principal.
echo "Starting Celery worker..."
celery -A app.worker.celery_app worker -P eventlet -Q gm_tasks --concurrency=10 --loglevel=info