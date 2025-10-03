"""
SPA (Single Page Application) crawler using Playwright for JavaScript-rendered sites.
All storage is handled via backend API calls.
"""
import asyncio
import logging
from typing import Dict, List, Set, Tuple
from playwright.async_api import async_playwright, Page
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

from .backend_api_client import BackendAPIClient

logger = logging.getLogger(__name__)


class SPACrawler:
    """
    SPA crawler that uses Playwright to render JavaScript and extract content.
    Storage is delegated to the backend API.
    """

    def __init__(self, backend_url: str):
        self.api_client = BackendAPIClient(backend_url)
        self.crawled_urls: Set[str] = set()
        self.crawled_content_hashes: Set[str] = set()  # Track content to avoid duplicates

    async def crawl_website(
        self,
        base_url: str,
        website_id: str,
        scraped_website_id: str,
        max_pages: int = 100,
        max_depth: int = 3
    ) -> Dict:
        """
        Crawl a SPA website using Playwright and send pages to backend API for storage.

        Returns:
            Dict with crawl statistics
        """
        domain = urlparse(base_url).netloc
        urls_to_crawl: List[Tuple[str, int]] = [(base_url, 0)]
        pages_crawled = 0
        errors = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent='ChatLite-SPA-Crawler/1.0'
            )

            try:
                while urls_to_crawl and pages_crawled < max_pages:
                    url, depth = urls_to_crawl.pop(0)

                    if url in self.crawled_urls or depth > max_depth:
                        continue

                    try:
                        logger.info(f"Crawling SPA {url} (depth: {depth})")

                        page = await context.new_page()

                        # Navigate and wait for page to load
                        response = await page.goto(url, wait_until='networkidle', timeout=30000)

                        if not response or response.status != 200:
                            logger.warning(f"HTTP {response.status if response else 'null'} for {url}")
                            await page.close()
                            continue

                        # Wait for common SPA content containers to load
                        try:
                            await page.wait_for_selector('main, article, [role="main"], .content, #content, #app, #root', timeout=5000)
                        except:
                            pass  # Continue if selectors not found

                        # Additional wait for dynamic content and modals
                        await page.wait_for_timeout(2000)  # Give JS time to render

                        # Extract content
                        html_content = await page.content()
                        title = await page.title()

                        soup = BeautifulSoup(html_content, 'html.parser')

                        # Extract meta description
                        meta_desc = ''
                        meta_tag = soup.find('meta', attrs={'name': 'description'})
                        if meta_tag:
                            meta_desc = meta_tag.get('content', '')

                        # Extract text content
                        for script in soup(['script', 'style', 'nav', 'footer', 'header']):
                            script.decompose()

                        content_text = soup.get_text(separator=' ', strip=True)

                        # Check for duplicate content (redirect detection)
                        import hashlib
                        content_hash = hashlib.md5(content_text[:1000].encode()).hexdigest()

                        # Check if we were redirected (URL in browser differs from requested URL)
                        actual_url = page.url
                        was_redirected = actual_url != url

                        if was_redirected:
                            logger.warning(f"🔀 Redirected from {url} to {actual_url}")
                            # If redirected to a page we already crawled, skip it
                            if actual_url in self.crawled_urls:
                                logger.info(f"⏭️  Skipping {url} - redirected to already crawled page {actual_url}")
                                continue

                        # Check if content is duplicate (same as another page)
                        if content_hash in self.crawled_content_hashes:
                            logger.info(f"⏭️  Skipping {url} - duplicate content detected")
                            continue

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
                        self.crawled_content_hashes.add(content_hash)
                        pages_crawled += 1

                        # Find links if not at max depth - Enhanced multi-method extraction
                        if depth < max_depth:
                            logger.info(f"🔍 Extracting links from {url} (depth {depth}/{max_depth})...")
                            # Enhanced link extraction with 10+ methods for SPAs
                            links = await page.evaluate('''
                                () => {
                                    const links = [];
                                    const baseUrl = window.location.origin;

                                    // Method 1: Traditional href links
                                    document.querySelectorAll('a[href]').forEach(a => {
                                        links.push(a.href);
                                    });

                                    // Method 2: React Router links (to= attribute)
                                    document.querySelectorAll('a[to], [to]').forEach(a => {
                                        const to = a.getAttribute('to');
                                        if (to) links.push(baseUrl + (to.startsWith('/') ? to : '/' + to));
                                    });

                                    // Method 3: Navigation with onclick handlers
                                    document.querySelectorAll('[onclick*="push"], [onclick*="navigate"]').forEach(el => {
                                        const onclick = el.getAttribute('onclick');
                                        const match = onclick.match(/['"]([^'"]+)['"]/);
                                        if (match) links.push(baseUrl + (match[1].startsWith('/') ? match[1] : '/' + match[1]));
                                    });

                                    // Method 4: Look for navigation menu items with data attributes
                                    document.querySelectorAll('[data-href], [data-to], [data-route]').forEach(el => {
                                        const href = el.getAttribute('data-href') || el.getAttribute('data-to') || el.getAttribute('data-route');
                                        if (href) links.push(baseUrl + (href.startsWith('/') ? href : '/' + href));
                                    });

                                    // Method 5: Look for links in buttons or clickable elements
                                    document.querySelectorAll('button, [role="button"], .btn').forEach(el => {
                                        const onclick = el.getAttribute('onclick');
                                        const dataHref = el.getAttribute('data-href') || el.getAttribute('data-url');

                                        if (dataHref) {
                                            links.push(dataHref.startsWith('http') ? dataHref : baseUrl + dataHref);
                                        }

                                        if (onclick && onclick.includes('location.href')) {
                                            const match = onclick.match(/location\\.href\\s*=\\s*['"]([^'"]+)['"]/);
                                            if (match) {
                                                links.push(match[1].startsWith('http') ? match[1] : baseUrl + match[1]);
                                            }
                                        }
                                    });

                                    // Method 6: Enhanced logo and image detection with JavaScript navigation
                                    document.querySelectorAll('img, [role="img"], .logo').forEach(el => {
                                        const src = el.src || el.getAttribute('src');
                                        const alt = el.alt || el.getAttribute('alt') || '';

                                        // Check if it's likely a logo or brand image
                                        const isLogo = src && (src.includes('logo') || alt.toLowerCase().includes('logo') ||
                                                              alt.toLowerCase().includes('brand') || el.className.includes('logo'));

                                        if (isLogo) {
                                            // Check if image is wrapped in a link
                                            const parentLink = el.closest('a');
                                            if (parentLink && parentLink.href) {
                                                links.push(parentLink.href);
                                            }

                                            // Enhanced JavaScript navigation detection (onClick handlers)
                                            else if (el.onclick || el.parentElement?.onclick || el.getAttribute('onclick')) {
                                                let destination = null;

                                                // Check onclick attribute
                                                const onclickAttr = el.getAttribute('onclick') || el.parentElement?.getAttribute('onclick');
                                                if (onclickAttr) {
                                                    // Look for URL patterns in onclick
                                                    const urlMatch = onclickAttr.match(/(?:window\\.location|location\\.href|navigate|push)\\s*=?\\s*['"]([^'"]+)['"]/);
                                                    if (urlMatch) {
                                                        destination = urlMatch[1];
                                                    }
                                                }

                                                // Check for data attributes indicating destination
                                                if (!destination) {
                                                    destination = el.getAttribute('data-href') ||
                                                                el.getAttribute('data-url') ||
                                                                el.getAttribute('data-link') ||
                                                                el.parentElement?.getAttribute('data-href');
                                                }

                                                // Only add if destination is same-domain
                                                if (destination && !destination.startsWith('http')) {
                                                    links.push(baseUrl + (destination.startsWith('/') ? destination : '/' + destination));
                                                } else if (destination && destination.includes(window.location.hostname)) {
                                                    links.push(destination);
                                                }
                                            }

                                            // Check for clickable images with data attributes
                                            const dataHref = el.getAttribute('data-href') || el.getAttribute('data-url');
                                            if (dataHref) {
                                                links.push(dataHref.startsWith('http') ? dataHref : baseUrl + dataHref);
                                            }
                                        }
                                    });

                                    // Method 7: Look for logo/brand elements that might be clickable
                                    document.querySelectorAll('[class*="logo"], [class*="brand"], [id*="logo"], [id*="brand"]').forEach(el => {
                                        // Check if the logo element itself is clickable
                                        const onclick = el.getAttribute('onclick');
                                        if (onclick && onclick.includes('location.href')) {
                                            const match = onclick.match(/location\\.href\\s*=\\s*['"]([^'"]+)['"]/);
                                            if (match) {
                                                links.push(match[1].startsWith('http') ? match[1] : baseUrl + match[1]);
                                            }
                                        }

                                        // Check if logo is wrapped in a link
                                        const parentLink = el.closest('a');
                                        if (parentLink && parentLink.href) {
                                            links.push(parentLink.href);
                                        }

                                        // Check for data attributes on logo elements
                                        const dataHref = el.getAttribute('data-href') || el.getAttribute('data-url');
                                        if (dataHref) {
                                            links.push(dataHref.startsWith('http') ? dataHref : baseUrl + dataHref);
                                        }
                                    });

                                    // Method 8: Look for modal triggers and popup content
                                    document.querySelectorAll('[data-toggle="modal"], [data-bs-toggle="modal"], [aria-haspopup="dialog"]').forEach(el => {
                                        const target = el.getAttribute('data-target') || el.getAttribute('data-bs-target') || el.getAttribute('href');
                                        if (target && target.startsWith('#')) {
                                            // Check if modal contains links
                                            const modal = document.querySelector(target);
                                            if (modal) {
                                                modal.querySelectorAll('a[href]').forEach(a => {
                                                    links.push(a.href);
                                                });
                                            }
                                        }
                                    });

                                    // Method 9: Extract from navigation menus
                                    document.querySelectorAll('nav *, .nav *, .navigation *, .menu *, [role="navigation"] *').forEach(el => {
                                        if (el.tagName === 'A' && el.href) {
                                            links.push(el.href);
                                        }
                                    });

                                    return [...new Set(links)]; // Remove duplicates
                                }
                            ''')

                            logger.info(f"📊 Found {len(links)} links via standard extraction on {url}")

                            # Method 10: Common SPA route discovery (from old version)
                            common_routes_links = await page.evaluate('''
                                () => {
                                    const discoveredRoutes = [];
                                    const baseUrl = window.location.origin;
                                    const commonRoutes = ['/', '/home', '/about', '/contact', '/services', '/products', '/faq', '/help', '/support', '/blog', '/news', '/privacy', '/privacy-policy', '/terms', '/overview'];
                                    const pageText = document.body.textContent.toLowerCase();

                                    commonRoutes.forEach(route => {
                                        const routeName = route === '/' ? 'home' : route.slice(1).replace(/-/g, ' ');

                                        // Check if route name appears in page content
                                        if (pageText.includes(routeName)) {
                                            discoveredRoutes.push(baseUrl + route);
                                        }

                                        // Check navigation elements for this route
                                        const navElements = Array.from(document.querySelectorAll('a, .nav-link, [to]'));
                                        for (const el of navElements) {
                                            const href = el.getAttribute('href') || el.getAttribute('to') || '';
                                            const text = el.textContent?.toLowerCase() || '';

                                            if (href.includes(route) || text.includes(routeName)) {
                                                discoveredRoutes.push(baseUrl + route);
                                                break;
                                            }
                                        }
                                    });

                                    return [...new Set(discoveredRoutes)];
                                }
                            ''')

                            for route_url in common_routes_links:
                                if route_url not in links:
                                    links.append(route_url)
                                    logger.info(f"Discovered common route: {route_url}")

                            # Method 11: React Router text-based inference
                            text_based_routes = await page.evaluate('''
                                () => {
                                    const routes = [];
                                    const baseUrl = window.location.origin;

                                    // Extract from navigation text
                                    document.querySelectorAll('nav *, .nav *, .navigation *, .menu *').forEach(el => {
                                        const text = el.textContent?.trim().toLowerCase();
                                        if (text && text.length < 30 && text.length > 2 && /^[a-z\\s]+$/.test(text)) {
                                            const possibleRoute = '/' + text.replace(/\\s+/g, '-');
                                            const commonPages = ['home', 'about', 'contact', 'services', 'products', 'faq', 'help', 'support', 'blog', 'privacy', 'privacy policy', 'terms', 'overview'];

                                            if (commonPages.includes(text)) {
                                                routes.push({
                                                    url: baseUrl + (text === 'home' ? '/' : possibleRoute),
                                                    text: text
                                                });
                                            }
                                        }
                                    });

                                    return routes;
                                }
                            ''')

                            for route_data in text_based_routes:
                                if route_data['url'] not in links:
                                    links.append(route_data['url'])
                                    logger.info(f"Discovered route from nav text '{route_data['text']}': {route_data['url']}")

                            # Method 12: External domain links (main site links)
                            external_links = await page.evaluate('''
                                () => {
                                    const externalLinks = [];

                                    document.querySelectorAll('a[href], img[src]').forEach(el => {
                                        let href = el.href || el.src;
                                        const text = el.textContent?.trim().toLowerCase() || el.alt?.toLowerCase() || '';

                                        if (href && href.startsWith('http') && !href.includes(window.location.hostname)) {
                                            // Only add if it looks like a main website (not social media)
                                            if (!href.includes('facebook') && !href.includes('twitter') && !href.includes('instagram') &&
                                                !href.includes('linkedin') && !href.includes('youtube') && !href.includes('github')) {

                                                // Check for redirect/main site indicators
                                                if (text.includes('visit') || text.includes('main site') || text.includes('official') ||
                                                    text.includes('more info') || text.includes('learn more') || text.includes('website') ||
                                                    text.includes('logo') || text.includes('home')) {
                                                    externalLinks.push(href);
                                                }
                                            }
                                        }
                                    });

                                    return [...new Set(externalLinks)];
                                }
                            ''')

                            for ext_link in external_links:
                                if ext_link not in links:
                                    links.append(ext_link)
                                    logger.info(f"Discovered external main site link: {ext_link}")

                            # Method 13: Enhanced React navigation and event listener detection
                            # Check for nav links that might use JavaScript event listeners
                            discovered_links = await page.evaluate('''
                                () => {
                                    const discoveredLinks = [];
                                    const navElements = Array.from(document.querySelectorAll('nav a, .nav-link, .navigation a, [class*="nav"] a, [role="navigation"] a, button, [class*="logo"], img[alt*="logo" i]'));

                                    for (const el of navElements) {
                                        const text = el.textContent?.trim() || el.alt || '';

                                        // Check for React Fiber (React 16+)
                                        const reactKeys = Object.keys(el).filter(k =>
                                            k.startsWith('__react') ||
                                            k.startsWith('_react')
                                        );

                                        for (const key of reactKeys) {
                                            try {
                                                let reactData = el[key];

                                                // Navigate React Fiber tree to find props
                                                if (reactData) {
                                                    // Try to get memoizedProps (React Fiber structure)
                                                    const props = reactData.memoizedProps ||
                                                                reactData.pendingProps ||
                                                                reactData.props ||
                                                                (reactData.return?.memoizedProps);

                                                    if (props) {
                                                        // Check for navigation props
                                                        const navUrl = props.href || props.to || props['data-href'];

                                                        if (navUrl && typeof navUrl === 'string' && !navUrl.startsWith('#')) {
                                                            discoveredLinks.push({
                                                                url: navUrl.startsWith('http') ? navUrl : window.location.origin + navUrl,
                                                                text: text,
                                                                source: 'react-fiber'
                                                            });
                                                        }

                                                        // Check for onClick handlers
                                                        if (props.onClick && typeof props.onClick === 'function') {
                                                            // Try to extract URL from function source
                                                            const fnString = props.onClick.toString();
                                                            const urlMatch = fnString.match(/['"]([\/\w-]+)['"]/) ||
                                                                           fnString.match(/window\.location\s*=\s*['"]([^'"]+)['"]/);

                                                            if (urlMatch && urlMatch[1] && !urlMatch[1].startsWith('#')) {
                                                                discoveredLinks.push({
                                                                    url: urlMatch[1].startsWith('http') ? urlMatch[1] : window.location.origin + urlMatch[1],
                                                                    text: text,
                                                                    source: 'react-onclick'
                                                                });
                                                            }
                                                        }
                                                    }
                                                }
                                            } catch (e) {
                                                // Ignore errors accessing React internals
                                            }
                                        }

                                        // Check if element or parent has onclick attribute that opens new window/tab
                                        const onclick = el.getAttribute('onclick') || el.parentElement?.getAttribute('onclick');
                                        if (onclick && onclick.includes('window.open')) {
                                            const match = onclick.match(/window\\.open\\(['"]([^'"]+)['"]/);
                                            if (match) {
                                                discoveredLinks.push({
                                                    url: match[1].startsWith('http') ? match[1] : window.location.origin + match[1],
                                                    text: text,
                                                    source: 'window.open'
                                                });
                                            }
                                        }
                                    }

                                    return discoveredLinks;
                                }
                            ''')

                            logger.info(f"🔍 Found {len(discovered_links)} links via React props/event detection")

                            for link_data in discovered_links:
                                if link_data['url'] not in links:
                                    links.append(link_data['url'])
                                    logger.info(f"Discovered link via {link_data['source']}: '{link_data['text']}' -> {link_data['url']}")

                            logger.info(f"📊 Total links after all extraction methods: {len(links)}")

                            # Add discovered links to crawl queue
                            added_count = 0
                            for link in links:
                                try:
                                    parsed_link = urlparse(link)
                                    if parsed_link.netloc == domain or not parsed_link.netloc:
                                        link_no_fragment = link.split('#')[0]
                                        if link_no_fragment and link_no_fragment not in self.crawled_urls:
                                            if link_no_fragment not in [u[0] for u in urls_to_crawl]:
                                                urls_to_crawl.append((link_no_fragment, depth + 1))
                                                added_count += 1
                                except Exception as e:
                                    continue

                            if added_count > 0:
                                logger.info(f"Added {added_count} new links to queue (total: {len(urls_to_crawl)})")

                        await page.close()

                    except Exception as e:
                        logger.error(f"Error crawling SPA {url}: {e}")
                        errors.append({'url': url, 'error': str(e)})
                        continue

            finally:
                await browser.close()

        return {
            'pages_crawled': pages_crawled,
            'pages_found': pages_crawled + len(urls_to_crawl),
            'errors': errors
        }

    @staticmethod
    async def is_spa_website(url: str) -> bool:
        """
        Detect if a website is a SPA by checking for JavaScript frameworks.
        Enhanced detection with both static HTML analysis and runtime checks.
        """
        try:
            import aiohttp

            # First, do a quick static HTML check (faster)
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                        if response.status == 200:
                            html = await response.text()

                            # Check for common SPA indicators in static HTML
                            static_indicators = [
                                '<div id="root"' in html,  # React
                                '<div id="app"' in html,   # Vue/general
                                '<div id="__next"' in html,  # Next.js
                                '<div id="__nuxt"' in html,  # Nuxt.js
                                'react' in html.lower() and '<script' in html,
                                'vue' in html.lower() and '<script' in html,
                                'angular' in html.lower() and '<script' in html,
                                '@vite/client' in html,  # Vite (often React/Vue)
                                '@react-refresh' in html,  # React with HMR
                                'data-reactroot' in html,
                                'data-reactid' in html,
                                'ng-app' in html,  # Angular
                                'v-app' in html,   # Vue
                                # Check if body has minimal content (typical of SPAs)
                                html.count('<div') < 5 and '<script' in html,
                            ]

                            # If 2+ indicators found in static HTML, it's likely a SPA
                            if sum(static_indicators) >= 2:
                                logger.info(f"🎯 SPA detected via static HTML analysis: {url}")
                                return True
            except Exception as static_check_error:
                logger.warning(f"Static HTML check failed, falling back to Playwright: {static_check_error}")

            # Fallback to Playwright runtime detection if static check inconclusive
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                try:
                    await page.goto(url, wait_until='domcontentloaded', timeout=10000)

                    # Check for common SPA indicators in rendered page
                    is_spa = await page.evaluate('''() => {
                        // Check for React
                        if (window.React || window._react || window.__REACT_DEVTOOLS_GLOBAL_HOOK__ ||
                            document.querySelector('[data-reactroot], [data-reactid]') ||
                            document.getElementById('root')) {
                            return true;
                        }
                        // Check for Vue
                        if (window.Vue || window.__VUE__ || document.querySelector('[data-v-]') ||
                            document.getElementById('app')) {
                            return true;
                        }
                        // Check for Angular
                        if (window.angular || window.ng || document.querySelector('[ng-app], [ng-controller], [ng-version]')) {
                            return true;
                        }
                        // Check for Next.js
                        if (document.getElementById('__next') || window.__NEXT_DATA__) {
                            return true;
                        }
                        // Check for Nuxt.js
                        if (document.getElementById('__nuxt') || window.__NUXT__) {
                            return true;
                        }
                        // Check for Svelte
                        if (window.__SVELTE__) {
                            return true;
                        }
                        return false;
                    }''')

                    await browser.close()

                    if is_spa:
                        logger.info(f"🎯 SPA detected via Playwright runtime check: {url}")

                    return is_spa

                except Exception as e:
                    logger.error(f"Error detecting SPA: {e}")
                    await browser.close()
                    return False

        except Exception as e:
            logger.error(f"Failed to launch browser for SPA detection: {e}")
            return False
