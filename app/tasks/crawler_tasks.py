"""
Celery tasks for website crawling and content processing.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List
from uuid import UUID
from celery import Task
from celery.exceptions import Retry
from datetime import datetime, timezone

from ..celery_app import celery_app
from ..services.simple_crawler import SimpleCrawler
from ..services.spa_crawler import SPACrawler
from ..services.backend_api_client import BackendAPIClient

logger = logging.getLogger(__name__)


class CrawlerTask(Task):
    """Base class for crawler tasks with error handling and retries."""

    autoretry_for = (Exception,)
    retry_kwargs = {'max_retries': 3, 'countdown': 60}
    retry_backoff = True
    retry_jitter = True

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Handle task failure."""
        logger.error(f"Task {self.name} failed: {exc}", extra={
            'task_id': task_id,
            'args': args,
            'kwargs': kwargs,
            'exception': str(exc)
        })

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Handle task retry."""
        logger.warning(f"Task {self.name} retrying: {exc}", extra={
            'task_id': task_id,
            'retry_count': self.request.retries
        })

    def on_success(self, retval, task_id, args, kwargs):
        """Handle task success."""
        logger.info(f"Task {self.name} completed successfully", extra={
            'task_id': task_id,
            'result': str(retval)[:100]  # First 100 chars of result
        })


@celery_app.task(bind=True, base=CrawlerTask, name='crawler.tasks.crawl_url')
def crawl_url(self, job_id: str = None, website_id: str = None, url: str = None, max_pages: int = 100, max_depth: int = 3) -> Dict[str, Any]:
    """
    Crawl a website starting from the given URL using API-based storage.

    Args:
        job_id: ID of the crawling job (optional for backward compatibility)
        website_id: UUID of the website to crawl
        url: Starting URL for crawling
        max_pages: Maximum number of pages to crawl
        max_depth: Maximum crawl depth

    Returns:
        Dict containing crawl results and statistics
    """
    try:
        from ..config import get_settings
        from urllib.parse import urlparse

        settings = get_settings()
        backend_url = settings.backend_url
        api_client = BackendAPIClient(backend_url)

        # Update job status to running via API
        if job_id:
            api_client.update_job_status(
                job_id=job_id,
                status='running',
                crawl_metrics={
                    'status': 'Starting crawl',
                    'progress': 0,
                    'pages_found': 0,
                    'pages_processed': 0,
                    'estimated_total': max_pages
                }
            )

        # Only update Celery state if we have a task ID
        if hasattr(self, 'request') and getattr(self.request, 'id', None):
            self.update_state(state='PROGRESS', meta={'status': 'Starting crawl', 'progress': 0})

        domain = urlparse(url).netloc

        # Initialize scraped_website record via API
        scraped_website_id = api_client.init_scraped_website(
            website_id=website_id,
            domain=domain,
            base_url=url,
            max_pages=max_pages,
            crawl_depth=max_depth
        )

        if not scraped_website_id:
            raise Exception("Failed to initialize scraped_website record")

        # Detect if website is a SPA
        is_spa = asyncio.run(SPACrawler.is_spa_website(url))
        logger.info(f"✅ SPA Detection: Website {url} detected as {'SPA' if is_spa else 'static HTML'}")

        # Use appropriate crawler based on detection
        if is_spa:
            logger.info(f"Using SPA crawler (Playwright) for {url}")
            crawler = SPACrawler(backend_url)
        else:
            logger.info(f"Using simple crawler (aiohttp) for {url}")
            crawler = SimpleCrawler(backend_url)

        result = asyncio.run(crawler.crawl_website(
            base_url=url,
            website_id=website_id,
            scraped_website_id=scraped_website_id,
            max_pages=max_pages,
            max_depth=max_depth
        ))

        # Calculate real progress based on actual results
        pages_found = result.get('pages_found', 0)
        pages_crawled = result.get('pages_crawled', 0)

        # Content is already stored via API by the crawler
        logger.info(f"✅ Crawl completed. Content stored via API for website_id: {website_id}")

        # Update job progress via API
        if job_id:
            api_client.update_job_status(
                job_id=job_id,
                status='completed',
                crawl_metrics={
                    'pages_crawled': pages_crawled,
                    'pages_processed': pages_crawled,
                    'pages_found': pages_found,
                    'crawl_time': 0
                }
            )

        # Trigger embeddings processing
        if pages_crawled > 0:
            process_crawled_content.delay(website_id, pages_crawled)

        # Only update Celery state if we have a task ID
        if hasattr(self, 'request') and getattr(self.request, 'id', None):
            self.update_state(state='PROGRESS', meta={'status': 'Content stored', 'progress': 100})

        return {
            'status': 'completed',
            'website_id': website_id,
            'pages_crawled': pages_crawled,
            'pages_processed': pages_crawled,
            'crawl_time': 0,
            'errors': result.get('errors', []),
            'storage_enabled': True
        }

    except Exception as exc:
        logger.error(f"Crawl task failed for website {website_id}: {exc}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")

        # Update job status to failed via API if job_id is provided
        if job_id:
            try:
                from ..config import get_settings
                settings = get_settings()
                api_client = BackendAPIClient(settings.backend_url)
                api_client.update_job_status(
                    job_id=job_id,
                    status='failed',
                    error_message=str(exc)
                )
                logger.info(f"Updated job {job_id} status to failed")
            except Exception as update_error:
                logger.error(f"Failed to update job status: {update_error}")

        # Only update Celery state if we have a task ID
        if hasattr(self, 'request') and getattr(self.request, 'id', None):
            self.update_state(
                state='FAILURE',
                meta={'error': str(exc), 'website_id': website_id}
            )
            raise self.retry(exc=exc)
        else:
            # When called directly (not from Celery), just re-raise
            raise


@celery_app.task(bind=True, base=CrawlerTask, name='crawler.tasks.process_data')
def process_crawled_content(self, website_id: str, pages_count: int) -> Dict[str, Any]:
    """
    Process crawled content and generate embeddings for vector search.

    This task calls the backend API to process embeddings.

    Args:
        website_id: UUID of the website
        pages_count: Number of pages that were crawled

    Returns:
        Dict containing processing results
    """
    try:
        from ..config import get_settings

        settings = get_settings()
        api_client = BackendAPIClient(settings.backend_url)

        self.update_state(state='PROGRESS', meta={'status': 'Requesting embeddings processing', 'progress': 0})

        logger.info(f"Calling backend API to process embeddings for website_id: {website_id}")

        # Call backend API to process embeddings
        result = api_client.process_embeddings(website_id, pages_count)

        if not result:
            return {
                'status': 'failed',
                'website_id': website_id,
                'error': 'API call failed'
            }

        logger.info(f"Embeddings processed successfully: {result}")

        self.update_state(state='PROGRESS', meta={'status': 'Embeddings processed', 'progress': 100})

        return result

    except Exception as exc:
        logger.error(f"Content processing failed for website {website_id}: {exc}")
        self.update_state(
            state='FAILURE',
            meta={'error': str(exc), 'website_id': website_id}
        )
        raise self.retry(exc=exc)


@celery_app.task(bind=True, base=CrawlerTask, name='crawler.tasks.schedule_crawl')
def schedule_crawl(self, website_id: str, crawl_frequency: str) -> Dict[str, Any]:
    """
    Schedule a crawl for a website based on its frequency setting.

    Args:
        website_id: UUID of the website
        crawl_frequency: Frequency setting (daily, weekly, monthly)

    Returns:
        Dict containing schedule result
    """
    try:
        # This will be expanded to handle scheduling logic
        logger.info(f"Scheduling crawl for website {website_id} with frequency {crawl_frequency}")

        return {
            'status': 'scheduled',
            'website_id': website_id,
            'frequency': crawl_frequency,
            'next_crawl': None  # Will be calculated based on frequency
        }

    except Exception as exc:
        logger.error(f"Schedule crawl failed for website {website_id}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True, base=CrawlerTask, name='crawler.tasks.generate_embeddings')
def generate_embeddings(self, page_id: str, content: str) -> Dict[str, Any]:
    """
    Generate embeddings for a specific page content.

    Args:
        page_id: UUID of the page
        content: Text content to generate embeddings for

    Returns:
        Dict containing embedding generation result
    """
    try:
        vector_service = VectorSearchService()

        # Generate embedding
        embedding = vector_service.generate_embedding(content)

        # Store embedding (this would integrate with your database)
        # For now, just return success

        return {
            'status': 'completed',
            'page_id': page_id,
            'embedding_dimensions': len(embedding),
            'content_length': len(content)
        }

    except Exception as exc:
        logger.error(f"Embedding generation failed for page {page_id}: {exc}")
        raise self.retry(exc=exc)


@celery_app.task(bind=True, base=CrawlerTask, name='crawler.tasks.update_knowledge_base')
def update_knowledge_base(self, website_id: str, updated_pages: List[str]) -> Dict[str, Any]:
    """
    Update the knowledge base with newly crawled content.

    Args:
        website_id: UUID of the website
        updated_pages: List of page IDs that were updated

    Returns:
        Dict containing knowledge base update result
    """
    try:
        # This task will handle updating the knowledge base
        # with new content and ensuring it's available for RAG

        logger.info(f"Updating knowledge base for website {website_id}")

        return {
            'status': 'completed',
            'website_id': website_id,
            'updated_pages': len(updated_pages),
            'knowledge_base_updated': True
        }

    except Exception as exc:
        logger.error(f"Knowledge base update failed for website {website_id}: {exc}")
        raise self.retry(exc=exc)


@celery_app.task(bind=True, base=CrawlerTask, name='crawler.tasks.monitor_schedule_changes')
def monitor_schedule_changes(self) -> Dict[str, Any]:
    """
    Monitor for schedule changes in the database and update Celery Beat accordingly.

    This task runs periodically to detect changes in website scheduling configurations
    and updates the automated scheduler.

    Returns:
        Dict containing monitoring result
    """
    try:
        logger.info("Monitoring schedule changes...")

        from app.services.automated_scheduler import get_automated_scheduler

        # Get the automated scheduler
        scheduler = get_automated_scheduler()

        # Trigger a manual schedule check
        result = scheduler.trigger_manual_schedule_check()

        logger.info(f"Schedule monitoring complete: {result}")
        return result

    except Exception as exc:
        logger.error(f"Schedule monitoring failed: {exc}")
        raise self.retry(exc=exc, countdown=300, max_retries=2)  # Retry after 5 minutes


@celery_app.task(bind=True, base=CrawlerTask, name='crawler.tasks.cleanup_old_crawl_data')
def cleanup_old_crawl_data(self, days_to_keep: int = 30) -> Dict[str, Any]:
    """
    Clean up old crawl data to maintain database performance.

    Args:
        days_to_keep: Number of days of data to retain

    Returns:
        Dict containing cleanup result
    """
    try:
        from datetime import datetime, timezone, timedelta
        from app.core.database import get_supabase_admin

        logger.info(f"Cleaning up crawl data older than {days_to_keep} days...")

        supabase = get_supabase_admin()
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)

        # Clean up old scraped pages (keep recent ones for reference)
        pages_result = supabase.table('scraped_pages').delete().lt(
            'scraped_at', cutoff_date.isoformat()
        ).execute()

        pages_deleted = len(pages_result.data) if pages_result.data else 0

        # Clean up old content chunks that are no longer referenced
        # This would cascade from page deletions due to foreign key constraints

        logger.info(f"Cleanup complete: {pages_deleted} old pages removed")

        return {
            'status': 'completed',
            'pages_deleted': pages_deleted,
            'cutoff_date': cutoff_date.isoformat(),
            'cleanup_completed_at': datetime.now(timezone.utc).isoformat()
        }

    except Exception as exc:
        logger.error(f"Cleanup failed: {exc}")
        raise self.retry(exc=exc, countdown=3600, max_retries=1)  # Retry after 1 hour


@celery_app.task(bind=True, base=CrawlerTask, name='crawler.tasks.health_check_websites')
def health_check_websites(self) -> Dict[str, Any]:
    """
    Perform health checks on registered websites to ensure they're accessible.

    Returns:
        Dict containing health check results
    """
    try:
        import requests
        from datetime import datetime, timezone
        from app.core.database import get_supabase_admin

        logger.info("Performing website health checks...")

        supabase = get_supabase_admin()

        # Get active websites
        websites_result = supabase.table('websites').select(
            'id, domain, url, name'
        ).eq('is_active', True).execute()

        websites = websites_result.data or []
        health_results = []

        for website in websites:
            website_id = website['id']
            domain = website['domain']
            url = website.get('url', f"https://{domain}")

            try:
                # Perform basic HTTP check
                response = requests.head(url, timeout=10, allow_redirects=True)
                status_code = response.status_code
                is_healthy = 200 <= status_code < 400

                health_results.append({
                    'website_id': website_id,
                    'domain': domain,
                    'status_code': status_code,
                    'is_healthy': is_healthy,
                    'checked_at': datetime.now(timezone.utc).isoformat()
                })

                # Update website health status in database
                supabase.table('websites').update({
                    'last_health_check': datetime.now(timezone.utc).isoformat(),
                    'is_healthy': is_healthy
                }).eq('id', website_id).execute()

            except Exception as e:
                logger.warning(f"Health check failed for {domain}: {e}")
                health_results.append({
                    'website_id': website_id,
                    'domain': domain,
                    'status_code': None,
                    'is_healthy': False,
                    'error': str(e),
                    'checked_at': datetime.now(timezone.utc).isoformat()
                })

        healthy_count = sum(1 for r in health_results if r['is_healthy'])

        logger.info(f"Health check complete: {healthy_count}/{len(health_results)} websites healthy")

        return {
            'status': 'completed',
            'total_websites': len(health_results),
            'healthy_websites': healthy_count,
            'unhealthy_websites': len(health_results) - healthy_count,
            'results': health_results,
            'checked_at': datetime.now(timezone.utc).isoformat()
        }

    except Exception as exc:
        logger.error(f"Health check failed: {exc}")
        raise self.retry(exc=exc, countdown=1800, max_retries=2)  # Retry after 30 minutes