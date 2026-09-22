"""
Scraping Pipeline Orchestrator.
Fetches articles, handles 3-attempt exponential backoff retries on missing data,
downloads images, and persists structured records into SQLite.
"""

import time
from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from config.settings import settings
from src.common.logger import get_logger
from src.storage.database import get_db_session
from src.storage.media_manager import MediaManager
from src.storage.models import Article
from src.storage.repositories import ArticleRepository, ScrapeLogRepository
from src.scraper.engine import ScraperEngine
from src.scraper.parsers.bangla_portal import BanglaPortalParser
from src.scraper.parsers.generic_news import GenericNewsParser

logger = get_logger("webcreoling.scraper.pipeline")


class ScrapingPipeline:
    """End-to-end scraper pipeline for processing news URLs and catalogs."""

    def __init__(self, engine: Optional[ScraperEngine] = None):
        self.engine = engine or ScraperEngine()
        self.media_manager = MediaManager()

    def scrape_article_with_retries(
        self,
        url: str,
        site_key: Optional[str] = None,
        category: Optional[str] = None,
        max_attempts: int = 3,
        base_backoff: float = 1.5,
    ) -> Dict[str, Any]:
        """
        Scrape a single article with exponential backoff retries (up to 3 attempts).
        If fields (text or images) are missing after retries, returns record with
        null/empty fields rather than discarding the article.
        """
        # Determine site config
        site_config = self.engine.get_site_config(site_key or url)
        parser = self.engine.get_parser_for_site(site_config)
        js_mode = site_config.get("js_mode", "hybrid") if site_config else "hybrid"
        source_name = site_config.get("name", site_key or "General News") if site_config else "General News"

        parsed_article = None
        was_js = False

        for attempt in range(1, max_attempts + 1):
            self.engine.rate_limiter.wait_for_turn(url)
            logger.info(f"Scraping [{attempt}/{max_attempts}] {url}")

            # On retry attempts >= 2, upgrade rendering mode to Selenium if hybrid was used
            current_js_mode = js_mode
            if attempt > 1 and js_mode == "hybrid":
                current_js_mode = "selenium_only"

            html, was_js_rendered, status = self.engine.js_manager.fetch_content(
                url, js_mode=current_js_mode, min_body_length=200
            )
            was_js = was_js_rendered

            if html:
                parsed_article = parser.parse_article(html, url=url, category=category)
                missing_fields = parsed_article.get("missing_fields", [])

                # Check if critical content is present
                has_text = bool(parsed_article.get("content_text") and len(parsed_article["content_text"]) >= 50)
                has_title = bool(parsed_article.get("title"))

                if has_text and has_title:
                    # Successfully parsed main text
                    parsed_article["scrape_status"] = "completed" if not missing_fields else "partial"
                    parsed_article["retry_count"] = attempt - 1
                    parsed_article["js_rendered"] = was_js
                    parsed_article["source"] = site_key or source_name
                    return parsed_article

                logger.warning(
                    f"Attempt {attempt} for {url} had missing fields: {missing_fields}. Retrying with backoff..."
                )

            # Exponential backoff delay: base * (2 ^ (attempt - 1))
            if attempt < max_attempts:
                backoff_delay = base_backoff * (2 ** (attempt - 1))
                time.sleep(backoff_delay)

        # Retries exhausted: store what we have with null/empty values rather than skipping
        if not parsed_article:
            parsed_article = {
                "url": url,
                "title": "",
                "content_text": "",
                "author": None,
                "published_at": None,
                "category": category,
                "lead_image_url": None,
                "image_urls": [],
                "missing_fields": ["title", "content_text", "published_at", "lead_image"],
            }

        parsed_article["scrape_status"] = "partial" if parsed_article.get("title") else "failed"
        parsed_article["retry_count"] = max_attempts
        parsed_article["js_rendered"] = was_js
        parsed_article["source"] = site_key or source_name
        logger.warning(f"All {max_attempts} attempts exhausted for {url}. Saving with available/empty fields.")
        return parsed_article

    def process_and_save_article(
        self,
        session: Session,
        article_url: str,
        site_key: Optional[str] = None,
        category: Optional[str] = None,
        download_images: bool = True,
    ) -> Optional[Article]:
        """Scrape an article, download its images, and save the complete record to SQLite."""
        article_data = self.scrape_article_with_retries(
            url=article_url,
            site_key=site_key,
            category=category,
        )

        repo = ArticleRepository(session)
        image_records = []

        # Download images if requested
        if download_images and article_data.get("image_urls"):
            lead_url = article_data.get("lead_image_url")
            pub_date = article_data.get("published_at")
            source = article_data.get("source", "news")

            for img_url in article_data["image_urls"]:
                img_metadata = self.media_manager.download_and_store_image(
                    image_url=img_url,
                    source=source,
                    pub_date=pub_date,
                )
                if img_metadata:
                    img_metadata["is_lead_image"] = (img_url == lead_url)
                    image_records.append(img_metadata)

        # Save to database
        article = repo.upsert_article(article_data, image_records=image_records)
        return article

    def run_site_crawl(
        self,
        site_key: str,
        max_pages_per_category: int = 3,
        categories: Optional[List[str]] = None,
        download_images: bool = True,
    ) -> Dict[str, Any]:
        """Crawl an entire site across its categories and persist all discovered articles."""
        site_config = self.engine.get_site_config(site_key)
        if not site_config:
            raise ValueError(f"Site key '{site_key}' not found in configuration.")

        target_categories = categories or [c["name"] for c in site_config.get("categories", [])]
        logger.info(f"Starting crawl for site '{site_key}' across categories: {target_categories}")

        total_found = 0
        total_saved = 0
        total_images = 0
        errors = 0

        with get_db_session() as session:
            log_repo = ScrapeLogRepository(session)
            log_entry = log_repo.start_log(source=site_key, job_type="crawl")
            session.commit()

            try:
                for cat_name in target_categories:
                    for article_url in self.engine.crawl_category(
                        site_key=site_key,
                        category_name=cat_name,
                        max_pages=max_pages_per_category,
                    ):
                        total_found += 1
                        try:
                            article = self.process_and_save_article(
                                session=session,
                                article_url=article_url,
                                site_key=site_key,
                                category=cat_name,
                                download_images=download_images,
                            )
                            if article:
                                total_saved += 1
                                total_images += len(article.images)
                            session.commit()
                        except Exception as e:
                            errors += 1
                            logger.error(f"Error processing article {article_url}: {e}", exc_info=True)

                log_repo.finish_log(
                    log_id=log_entry.id,
                    articles_found=total_found,
                    articles_saved=total_saved,
                    images_downloaded=total_images,
                    errors_count=errors,
                    status="completed",
                )
            except Exception as e:
                log_repo.finish_log(
                    log_id=log_entry.id,
                    articles_found=total_found,
                    articles_saved=total_saved,
                    images_downloaded=total_images,
                    errors_count=errors,
                    status="failed",
                    error_details=str(e),
                )
                raise

        return {
            "site_key": site_key,
            "articles_found": total_found,
            "articles_saved": total_saved,
            "images_downloaded": total_images,
            "errors": errors,
        }
