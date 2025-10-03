#!/bin/bash
# Start Celery worker for Render deployment

set -e

echo "Installing Playwright browsers..."
playwright install chromium

echo "Starting Celery worker..."
celery -A app.celery_app:celery_app worker \
    --loglevel=info \
    --queues=celery,crawl_queue,process_queue,schedule_queue,monitor_queue \
    --concurrency=2 \
    --max-tasks-per-child=100 \
    --time-limit=600 \
    --soft-time-limit=300
