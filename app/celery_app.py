"""
Celery Application Configuration
Standalone Celery worker that connects to Redis and processes tasks
"""

import logging
import ssl
from typing import Dict, Any
from celery import Celery

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def get_celery_config() -> Dict[str, Any]:
    """Get Celery configuration dictionary."""
    broker_url = settings.celery_broker_url
    result_backend = settings.celery_result_backend

    return {
        # Broker and Result Backend
        'broker_url': broker_url,
        'result_backend': result_backend,
        'result_backend_transport_options': {
            'master_name': 'mymaster'
        },

        # Task Routing and Queues
        'task_routes': {
            'crawler.tasks.crawl_url': {'queue': 'crawl_queue'},
            'crawler.tasks.process_data': {'queue': 'process_queue'},
            'crawler.tasks.schedule_crawl': {'queue': 'schedule_queue'},
            'crawler.tasks.generate_embeddings': {'queue': 'process_queue'},
            'crawler.tasks.update_knowledge_base': {'queue': 'process_queue'},
            'monitor.tasks.*': {'queue': 'monitor_queue'},
        },

        # Worker Configuration
        'worker_prefetch_multiplier': 1,
        'task_acks_late': True,
        'worker_disable_rate_limits': False,
        'worker_max_tasks_per_child': 1000,

        # Task Configuration
        'task_serializer': 'json',
        'result_serializer': 'json',
        'accept_content': ['json'],
        'result_expires': 1800,  # 30 minutes
        'timezone': 'UTC',
        'enable_utc': True,
        'task_ignore_result': False,
        'task_track_started': True,
        'result_compression': 'gzip',

        # Retry Configuration
        'task_default_retry_delay': 60,  # 1 minute
        'task_max_retries': 3,
        'task_soft_time_limit': 300,  # 5 minutes
        'task_time_limit': 600,  # 10 minutes

        # Redis Connection Pool
        'broker_transport_options': {
            'fanout_prefix': True,
            'fanout_patterns': True,
            'retry_on_timeout': True,
            'max_connections': 20,
        },

        # SSL Configuration for rediss:// URLs
        'broker_use_ssl': {
            'ssl_cert_reqs': ssl.CERT_NONE
        } if broker_url.startswith('rediss://') else None,
        'redis_backend_use_ssl': {
            'ssl_cert_reqs': ssl.CERT_NONE
        } if result_backend.startswith('rediss://') else None,

        # Task Discovery - Import tasks from this module
        'imports': [
            'app.tasks.crawler_tasks',
        ],
    }


# Create Celery app instance
celery_app = Celery('celery_worker')
celery_app.config_from_object(get_celery_config())


@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """Setup periodic tasks"""
    # Example: Check for schedule changes every 5 minutes
    # sender.add_periodic_task(300.0, check_schedule_changes.s(), name='check schedules')
    pass


if __name__ == '__main__':
    celery_app.start()
