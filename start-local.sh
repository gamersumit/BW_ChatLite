#!/bin/bash
# Start Celery worker locally (without Docker)

cd "$(dirname "$0")"

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Set PYTHONPATH
export PYTHONPATH=$(pwd)

echo "🚀 Starting Celery worker locally..."
echo "📍 Working directory: $(pwd)"
echo "🔗 Redis URL: ${REDIS_URL}"
echo ""

# Start Celery worker
celery -A app.celery_app:celery_app worker \
    --loglevel=info \
    --queues=celery,crawl_queue,process_queue,schedule_queue,monitor_queue \
    --concurrency=4 \
    --max-tasks-per-child=100 \
    --logfile=logs/celery_worker.log \
    --pidfile=logs/celery_worker.pid
