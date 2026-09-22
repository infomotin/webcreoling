"""
Scraper Engine with Polite Rate Limiting, Date Range Filtering & Site Configurations.
"""

import random
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Generator
from urllib.parse import urlparse
import yaml
from config.settings import settings
from src.common.logger import get_logger
from src.scraper.js_renderer import JSRenderingManager
from src.scraper.parsers.bangla_portal import BanglaPortalParser
from src.scraper.parsers.generic_news import GenericNewsParser

logger = get_logger("webcreoling.scraper.engine")


class DomainRateLimiter:
    """Enforces polite delays with random jitter between requests to each domain."""

    def __init__(self, default_delay: float = 1.0, jitter: float = 0.5):
        self.default_delay = default_delay
        self.jitter = jitter
        self._last_request_time: Dict[str, float] = {}

    def wait_for_turn(self, url: str) -> None:
        """Wait if needed before issuing the next request to this domain."""
        domain = urlparse(url).netloc
        now = time.time()
        last_time = self._last_request_time.get(domain, 0.0)

        # Compute delay with jitter
        jitter_amount = random.uniform(-self.jitter, self.jitter)
        target_delay = max(0.2, self.default_delay + jitter_amount)

        elapsed = now - last_time
        if elapsed < target_delay:
            sleep_duration = target_delay - elapsed
            time.sleep(sleep_duration)

        self._last_request_time[domain] = time.time()


class ScraperEngine:
    """Coordinates web crawling, site configurations, pagination, and article discovery."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or (settings.CONFIG_DIR / "sites_config.yaml")
        self.sites_config = self._load_config()
        self.js_manager = JSRenderingManager()
        self.rate_limiter = DomainRateLimiter(
            default_delay=settings.DEFAULT_SCRAPE_DELAY,
            jitter=settings.SCRAPE_DELAY_JITTER,
        )

    def _load_config(self) -> Dict[str, Any]:
        """Load YAML configuration for newspaper portals."""
        if not self.config_path.exists():
            logger.warning(f"Config file {self.config_path} not found. Using default configs.")
            return {"sites": {}, "global_settings": {}}

        with open(self.config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def get_site_config(self, site_key: str) -> Optional[Dict[str, Any]]:
        """Retrieve configuration for a specific portal key or domain."""
        sites = self.sites_config.get("sites", {})
        if site_key in sites:
            return sites[site_key]

        # Match by domain
        for key, conf in sites.items():
            if conf.get("domain") and conf.get("domain") in site_key:
                return conf

        return None

    def get_parser_for_site(self, site_config: Optional[Dict[str, Any]]) -> BanglaPortalParser:
        """Instantiate parser configured with site-specific selectors."""
        if site_config:
            return BanglaPortalParser(site_config=site_config)
        return GenericNewsParser()

    def crawl_category(
        self,
        site_key: str,
        category_name: str,
        max_pages: int = 5,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Generator[str, None, None]:
        """
        Crawl a portal's category pages, traversing pagination and yielding article URLs.
        Filters by date range if publication dates are discoverable.
        """
        site_config = self.get_site_config(site_key)
        if not site_config:
            logger.error(f"No configuration found for site: {site_key}")
            return

        if not site_config.get("enabled", True) or site_config.get("js_mode") == "skip":
            logger.info(f"Site {site_key} is disabled or marked to skip. Skipping.")
            return

        parser = self.get_parser_for_site(site_config)
        js_mode = site_config.get("js_mode", "hybrid")

        # Find category config
        cat_config = None
        for cat in site_config.get("categories", []):
            if cat.get("name") == category_name:
                cat_config = cat
                break

        if not cat_config:
            logger.warning(f"Category '{category_name}' not defined for site '{site_key}'.")
            return

        base_url = site_config.get("base_url", "")
        pagination_pattern = cat_config.get("pagination_pattern", cat_config.get("url"))
        discovered_urls = set()

        for page in range(1, max_pages + 1):
            if "{page}" in pagination_pattern:
                page_url = pagination_pattern.format(page=page)
            elif page == 1:
                page_url = cat_config.get("url")
            else:
                break

            logger.info(f"Crawling [{site_key}] category '{category_name}' - Page {page}: {page_url}")
            self.rate_limiter.wait_for_turn(page_url)

            html, was_js, status = self.js_manager.fetch_content(page_url, js_mode=js_mode)
            if not html:
                logger.warning(f"Failed to fetch page {page_url} (status: {status}). Stopping pagination.")
                break

            article_links = parser.extract_article_links(html, base_url=base_url)
            logger.info(f"Discovered {len(article_links)} article links on page {page}.")

            if not article_links:
                break

            new_links = 0
            for link in article_links:
                if link not in discovered_urls:
                    discovered_urls.add(link)
                    new_links += 1
                    yield link

            # If no new links found on this page, stop pagination
            if new_links == 0:
                logger.debug("No new links discovered on this page. Reached end of pagination.")
                break

    def close(self) -> None:
        """Clean up underlying resources."""
        self.js_manager.close()
