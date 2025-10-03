#!/bin/bash
# Start Celery worker using Docker Compose

cd "$(dirname "$0")"

echo "🐳 Starting Celery worker with Docker Compose..."
echo ""

# Build and start the container
docker-compose up --build -d

echo ""
echo "✅ Celery worker started!"
echo ""
echo "📊 View logs:"
echo "   docker-compose logs -f celery-worker"
echo ""
echo "🛑 Stop worker:"
echo "   docker-compose down"
echo ""
echo "📈 Check worker status:"
echo "   docker-compose ps"
