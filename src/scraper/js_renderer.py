"""
JavaScript Rendering Strategy Manager.
Handles per-site rendering strategies: 'bs4_only', 'selenium_only', 'hybrid', and 'skip'.
Gracefully falls back to HTTP if Selenium/WebDriver is unavailable.
"""

from typing import Optional, Tuple
import httpx
from bs4 import BeautifulSoup
from config.settings import settings
from src.common.logger import get_logger

logger = get_logger("webcreoling.scraper.js_renderer")


class JSRenderingManager:
    """Manages static vs dynamic page retrieval based on per-site configuration."""

    def __init__(self):
        self._selenium_driver = None
        self._selenium_attempted = False
        self._selenium_available = False
        self.headers = {
            "User-Agent": settings.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "bn-BD,bn;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def _init_selenium(self) -> bool:
        """Lazy-initialize headless Selenium driver if available."""
        if self._selenium_attempted:
            return self._selenium_available

        self._selenium_attempted = True
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service

            chrome_options = Options()
            if settings.SELENIUM_HEADLESS:
                chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument(f"user-agent={settings.USER_AGENT}")
            chrome_options.add_argument("--blink-settings=imagesEnabled=false")  # Save bandwidth

            # Try initializing Chrome
            try:
                from webdriver_manager.chrome import ChromeDriverManager
                service = Service(ChromeDriverManager().install())
                self._selenium_driver = webdriver.Chrome(service=service, options=chrome_options)
            except Exception:
                # Fallback to default system PATH chromedriver
                self._selenium_driver = webdriver.Chrome(options=chrome_options)

            self._selenium_driver.set_page_load_timeout(settings.SELENIUM_TIMEOUT)
            self._selenium_available = True
            logger.info("Selenium Headless Chrome initialized successfully.")
            return True
        except Exception as e:
            logger.warning(
                f"Selenium WebDriver initialization failed: {e}. "
                "Falling back to high-performance static HTTP rendering."
            )
            self._selenium_available = False
            return False

    def fetch_static(self, url: str, timeout: int = 15) -> Tuple[Optional[str], int]:
        """Fetch static HTML using HTTPX client."""
        try:
            with httpx.Client(timeout=timeout, headers=self.headers, follow_redirects=True) as client:
                response = client.get(url)
                return response.text, response.status_code
        except Exception as e:
            logger.debug(f"Static HTTP request error for {url}: {e}")
            return None, 0

    def fetch_selenium(self, url: str) -> Tuple[Optional[str], int]:
        """Fetch dynamic HTML rendered via Selenium."""
        if not self._init_selenium() or self._selenium_driver is None:
            # Fallback to static fetch if Selenium is not configured
            return self.fetch_static(url)

        try:
            self._selenium_driver.get(url)
            page_source = self._selenium_driver.page_source
            return page_source, 200
        except Exception as e:
            logger.debug(f"Selenium fetch error for {url}: {e}")
            # Try static fallback
            return self.fetch_static(url)

    def fetch_content(
        self,
        url: str,
        js_mode: str = "hybrid",
        min_body_length: int = 300,
    ) -> Tuple[Optional[str], bool, str]:
        """
        Fetch web page content using the specified rendering strategy.

        Returns:
            (html_content, was_js_rendered, status_msg)
        """
        js_mode = (js_mode or "hybrid").lower()

        # 1. Skip Mode (for login/paywall/CAPTCHA protected sites)
        if js_mode == "skip":
            return None, False, "skipped_by_config"

        # 2. Static BeautifulSoup / HTTPX Only
        if js_mode == "bs4_only":
            html, status = self.fetch_static(url)
            if html and len(html) > 50:
                return html, False, "ok_static"
            return None, False, f"failed_http_{status}"

        # 3. Dynamic Selenium Only
        if js_mode == "selenium_only":
            html, status = self.fetch_selenium(url)
            if html and len(html) > 50:
                return html, True, "ok_selenium"
            return None, False, f"failed_selenium_{status}"

        # 4. Hybrid Mode: Fast Static first -> Fall back to Selenium if content appears empty
        html, status = self.fetch_static(url)
        if html and len(html) >= min_body_length:
            # Check if basic text is present
            soup = BeautifulSoup(html, "lxml")
            paragraphs = soup.find_all("p")
            text_len = sum(len(p.get_text(strip=True)) for p in paragraphs)
            if text_len >= 150:
                return html, False, "ok_static"

        logger.debug(f"Hybrid mode: static fetch had insufficient body ({url}). Attempting Selenium...")
        html_sel, status_sel = self.fetch_selenium(url)
        if html_sel and len(html_sel) > 50:
            return html_sel, True, "ok_selenium_fallback"

        # Return whatever static content we got if Selenium also didn't get more
        if html:
            return html, False, "ok_static_fallback"

        return None, False, "failed_all_methods"

    def close(self) -> None:
        """Close Selenium browser session if active."""
        if self._selenium_driver:
            try:
                self._selenium_driver.quit()
            except Exception:
                pass
            self._selenium_driver = None
