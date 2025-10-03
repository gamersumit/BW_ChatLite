"""
Simple web crawler that fetches HTML content without database dependencies.
All storage is handled via backend API calls.
"""
import aiohttp
import asyncio
import logging
from typing import Dict, List, Set, Tuple
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

from .backend_api_client import BackendAPIClient

logger = logging.getLogger(__name__)


class SimpleCrawler:
    """
    Simple web crawler that extracts content and returns it without storing.
    Storage is delegated to the backend API.
    """

    def __init__(self, backend_url: str):
        self.api_client = BackendAPIClient(backend_url)
        self.crawled_urls: Set[str] = set()

    async def crawl_website(
        self,
        base_url: str,
        website_id: str,
        scraped_website_id: str,
        max_pages: int = 100,
        max_depth: int = 3
    ) -> Dict:
        """
        Crawl a website and send pages to backend API for storage.

        Returns:
            Dict with crawl statistics
        """
        domain = urlparse(base_url).netloc
        urls_to_crawl: List[Tuple[str, int]] = [(base_url, 0)]
        pages_crawled = 0
        errors = []

        timeout = aiohttp.ClientTimeout(total=30)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            while urls_to_crawl and pages_crawled < max_pages:
                url, depth = urls_to_crawl.pop(0)

                if url in self.crawled_urls or depth > max_depth:
                    continue

                try:
                    logger.info(f"Crawling {url} (depth: {depth})")

                    async with session.get(url, headers={'User-Agent': 'ChatLite-Crawler/1.0'}) as response:
                        if response.status != 200:
                            logger.warning(f"HTTP {response.status} for {url}")
                            continue

                        content_type = response.headers.get('content-type', '').lower()
                        if 'text/html' not in content_type:
                            continue

                        html_content = await response.text()
                        soup = BeautifulSoup(html_content, 'html.parser')

                        # Extract content
                        title = soup.title.string if soup.title else ''
                        meta_desc = ''
                        meta_tag = soup.find('meta', attrs={'name': 'description'})
                        if meta_tag:
                            meta_desc = meta_tag.get('content', '')

                        # Extract text content
                        for script in soup(['script', 'style', 'nav', 'footer', 'header']):
                            script.decompose()

                        content_text = soup.get_text(separator=' ', strip=True)

                        # Store page via API
                        self.api_client.store_page(
                            scraped_website_id=scraped_website_id,
                            url=url,
                            title=title,
                            content_text=content_text,
                            content_html=str(soup),
                            meta_description=meta_desc,
                            status_code=response.status,
                            depth_level=depth
                        )

                        self.crawled_urls.add(url)
                        pages_crawled += 1

                        # Find links
                        if depth < max_depth:
                            for link in soup.find_all('a', href=True):
                                href = link['href']
                                full_url = urljoin(url, href)

                                # Only crawl same domain
                                if urlparse(full_url).netloc == domain:
                                    full_url_no_fragment = full_url.split('#')[0]
                                    if full_url_no_fragment not in self.crawled_urls:
                                        urls_to_crawl.append((full_url_no_fragment, depth + 1))

                except Exception as e:
                    logger.error(f"Error crawling {url}: {e}")
                    errors.append({'url': url, 'error': str(e)})
                    continue

        return {
            'pages_crawled': pages_crawled,
            'pages_found': pages_crawled + len(urls_to_crawl),
            'errors': errors
        }
