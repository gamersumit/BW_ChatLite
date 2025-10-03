"""
Client for making API calls to the backend.
Handles all database operations via API instead of direct DB access.
"""
import logging
import requests
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class BackendAPIClient:
    """Client for backend API operations"""

    def __init__(self, backend_url: str):
        self.backend_url = backend_url
        self.timeout = 30

    def init_scraped_website(
        self,
        website_id: str,
        domain: str,
        base_url: str,
        max_pages: int = 100,
        crawl_depth: int = 3
    ) -> Optional[str]:
        """Initialize scraped_website record and return its ID"""
        try:
            response = requests.post(
                f"{self.backend_url}/api/v1/crawl/init-scraped-website",
                json={
                    'website_id': website_id,
                    'domain': domain,
                    'base_url': base_url,
                    'max_pages': max_pages,
                    'crawl_depth': crawl_depth
                },
                timeout=self.timeout
            )

            if response.status_code == 200:
                result = response.json()
                logger.info(f"Initialized scraped_website: {result['scraped_website_id']}")
                return result['scraped_website_id']
            else:
                logger.error(f"API error initializing scraped_website: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Failed to initialize scraped_website via API: {e}")
            return None

    def store_page(
        self,
        scraped_website_id: str,
        url: str,
        title: Optional[str] = None,
        content_text: Optional[str] = None,
        content_html: Optional[str] = None,
        meta_description: Optional[str] = None,
        status_code: Optional[int] = None,
        depth_level: int = 0
    ) -> Optional[Dict]:
        """Store a crawled page"""
        try:
            response = requests.post(
                f"{self.backend_url}/api/v1/crawl/store-page",
                json={
                    'scraped_website_id': scraped_website_id,
                    'url': url,
                    'title': title,
                    'content_text': content_text,
                    'content_html': content_html,
                    'meta_description': meta_description,
                    'status_code': status_code,
                    'depth_level': depth_level
                },
                timeout=self.timeout
            )

            if response.status_code == 200:
                logger.info(f"Stored page: {url}")
                return response.json()
            else:
                logger.error(f"API error storing page: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Failed to store page via API: {e}")
            return None

    def update_job_status(
        self,
        job_id: str,
        status: str,
        crawl_metrics: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None
    ) -> bool:
        """Update crawling job status"""
        try:
            response = requests.post(
                f"{self.backend_url}/api/v1/crawl/update-job-status",
                json={
                    'job_id': job_id,
                    'status': status,
                    'crawl_metrics': crawl_metrics,
                    'error_message': error_message
                },
                timeout=self.timeout
            )

            if response.status_code == 200:
                logger.info(f"Updated job {job_id} status to {status}")
                return True
            else:
                logger.error(f"API error updating job status: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Failed to update job status via API: {e}")
            return False

    def process_embeddings(
        self,
        website_id: str,
        pages_count: int
    ) -> Optional[Dict]:
        """Process embeddings for crawled pages"""
        try:
            response = requests.post(
                f"{self.backend_url}/api/v1/crawl/process-embeddings",
                json={
                    'website_id': website_id,
                    'pages_count': pages_count
                },
                timeout=300  # 5 minute timeout for processing
            )

            if response.status_code == 200:
                result = response.json()
                logger.info(f"Embeddings processed: {result}")
                return result
            else:
                logger.error(f"API error processing embeddings: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Failed to process embeddings via API: {e}")
            return None
