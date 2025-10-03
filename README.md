# Celery Worker Service

Standalone Celery worker service for ChatLite backend. Processes background tasks like website crawling, content processing, and embeddings generation.

## Architecture

```
┌─────────────┐      ┌─────────────┐      ┌──────────────┐
│   Backend   │─────▶│    Redis    │◀─────│    Celery    │
│  (FastAPI)  │      │   (Broker)  │      │   Workers    │
└─────────────┘      └─────────────┘      └──────────────┘
     │                                            │
     └────────────────┬───────────────────────────┘
                      ▼
              ┌───────────────┐
              │   Supabase    │
              │   (Database)  │
              └───────────────┘
```

## Features

- **Separate Service**: Runs independently from the FastAPI backend
- **Docker Support**: Can run locally or in Docker container
- **Queue Management**: Listens to multiple queues (crawl, process, schedule, monitor)
- **Auto-reconnect**: Automatically reconnects to Redis on connection loss
- **Health Checks**: Built-in health check endpoints

## Queues

- `crawl_queue` - Website crawling tasks
- `process_queue` - Content processing and embeddings
- `schedule_queue` - Scheduled crawl tasks
- `monitor_queue` - System monitoring tasks
- `celery` - Default queue for misc tasks

## Setup

### Option 1: Run Locally (Development)

1. **Install dependencies:**
   ```bash
   cd celery-worker
   pip install -r requirements.txt
   playwright install chromium
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

3. **Start the worker:**
   ```bash
   ./start-local.sh
   ```

   Or manually:
   ```bash
   celery -A app.celery_app:celery_app worker \
       --loglevel=info \
       --queues=celery,crawl_queue,process_queue,schedule_queue,monitor_queue \
       --concurrency=4
   ```

### Option 2: Run with Docker (Production)

1. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

2. **Start with Docker Compose:**
   ```bash
   ./start-docker.sh
   ```

   Or manually:
   ```bash
   docker-compose up --build -d
   ```

3. **View logs:**
   ```bash
   docker-compose logs -f celery-worker
   ```

4. **Stop the worker:**
   ```bash
   docker-compose down
   ```

## Environment Variables

Required environment variables (same as backend):

```env
# Redis
REDIS_URL=redis://localhost:6379/0

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-key
SUPABASE_ANON_KEY=your-anon-key

# OpenAI
OPENAI_API_KEY=sk-your-key
OPENAI_MODEL=gpt-4o

# Environment
ENVIRONMENT=development
```

## Project Structure

```
celery-worker/
├── app/
│   ├── __init__.py
│   ├── config.py              # Configuration settings
│   ├── celery_app.py          # Celery application setup
│   ├── core/
│   │   └── supabase_client.py # Database client
│   ├── services/
│   │   ├── crawler_service.py # Crawling logic
│   │   ├── spa_crawler.py     # SPA crawling with Playwright
│   │   └── vector_search_service.py
│   ├── tasks/
│   │   ├── crawler_tasks.py   # Celery tasks
│   │   └── monitor_tasks.py
│   └── models/
├── logs/                      # Worker logs
├── Dockerfile                 # Docker image
├── docker-compose.yml         # Docker Compose config
├── requirements.txt           # Python dependencies
├── .env                       # Environment variables
├── start-local.sh            # Local startup script
└── start-docker.sh           # Docker startup script
```

## Monitoring

### Check Worker Status

**Local:**
```bash
celery -A app.celery_app:celery_app inspect active
celery -A app.celery_app:celery_app inspect registered
celery -A app.celery_app:celery_app inspect stats
```

**Docker:**
```bash
docker exec chatlite-celery-worker celery -A app.celery_app:celery_app inspect active
```

### View Logs

**Local:**
```bash
tail -f logs/celery_worker.log
```

**Docker:**
```bash
docker-compose logs -f celery-worker
```

### Health Check

**Local:**
```bash
celery -A app.celery_app:celery_app inspect ping
```

**Docker:**
```bash
docker exec chatlite-celery-worker celery -A app.celery_app:celery_app inspect ping
```

## Scaling

### Add More Workers (Local)

Run multiple instances:
```bash
# Terminal 1
celery -A app.celery_app:celery_app worker --hostname=worker1@%h

# Terminal 2
celery -A app.celery_app:celery_app worker --hostname=worker2@%h
```

### Add More Workers (Docker)

Update `docker-compose.yml`:
```yaml
services:
  celery-worker-1:
    # ... config ...

  celery-worker-2:
    # ... same config, different container name ...
```

Then:
```bash
docker-compose up --scale celery-worker=3
```

## Troubleshooting

### Worker Not Connecting to Redis

1. Check Redis is running:
   ```bash
   redis-cli ping
   ```

2. Verify REDIS_URL in .env:
   ```bash
   echo $REDIS_URL
   ```

3. Check network connectivity (Docker):
   ```bash
   docker exec chatlite-celery-worker ping host.docker.internal
   ```

### Tasks Not Being Processed

1. Check worker is running:
   ```bash
   celery -A app.celery_app:celery_app inspect active
   ```

2. Check queues are registered:
   ```bash
   celery -A app.celery_app:celery_app inspect active_queues
   ```

3. Check backend is sending tasks to correct queues:
   - Tasks must be sent to: `crawl_queue`, `process_queue`, etc.

### Import Errors

If you see module import errors:

1. Ensure PYTHONPATH is set:
   ```bash
   export PYTHONPATH=/path/to/celery-worker
   ```

2. Check all required files are copied from backend

3. Verify requirements are installed:
   ```bash
   pip install -r requirements.txt
   ```

## Deployment

### Render

Create a new **Background Worker** service:
- **Build Command:** `pip install -r requirements.txt && playwright install chromium`
- **Start Command:** `celery -A app.celery_app:celery_app worker --loglevel=info --queues=celery,crawl_queue,process_queue,schedule_queue,monitor_queue --concurrency=4`
- **Environment Variables:** Add all from .env

### AWS ECS / Kubernetes

Use the provided Dockerfile and deploy as a container service.

### Heroku

Add a `Procfile`:
```
worker: celery -A app.celery_app:celery_app worker --loglevel=info --queues=celery,crawl_queue,process_queue,schedule_queue,monitor_queue
```

## Development

### Add New Tasks

1. Create task in `app/tasks/`:
   ```python
   from app.celery_app import celery_app

   @celery_app.task(name='my.task.name')
   def my_task(arg1, arg2):
       # Task logic
       return result
   ```

2. Update imports in `app/tasks/__init__.py`

3. Call from backend:
   ```python
   from app.tasks.crawler_tasks import crawl_url
   crawl_url.delay(args...)
   ```

### Testing

Run a test task:
```python
from celery import Celery
app = Celery(broker='redis://localhost:6379/0')
app.send_task('crawler.tasks.crawl_url', args=[...])
```

## Support

For issues or questions:
1. Check logs: `tail -f logs/celery_worker.log`
2. Verify Redis connection
3. Ensure environment variables are set correctly
4. Check backend is using correct queue names
