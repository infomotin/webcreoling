"""
Scraper Management Blueprint.
Enables Admins and Editors to trigger portal crawls and single article scrapes.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from src.scraper.engine import ScraperEngine
from src.scraper.pipeline import ScrapingPipeline
from src.storage.database import get_db_session
from src.storage.models import ScrapeLog
from src.web.auth import login_required, roles_required

scraper_bp = Blueprint("scraper", __name__)


@scraper_bp.route("")
@login_required
def index_view():
    """Display configured portals, JS modes, and recent crawl logs."""
    engine = ScraperEngine()
    sites = engine.sites_config.get("sites", {})

    with get_db_session() as session:
        logs = (
            session.query(ScrapeLog)
            .order_by(ScrapeLog.id.desc())
            .limit(10)
            .all()
        )
        logs_data = [l.to_dict() for l in logs]

    return render_template("scraper.html", sites=sites, logs=logs_data)


@scraper_bp.route("/trigger", methods=["POST"])
@roles_required("admin", "editor")
def trigger_crawl():
    """Trigger a crawl on a configured news portal."""
    site_key = request.form.get("site_key", "").strip()
    max_pages = int(request.form.get("max_pages", 2))

    if not site_key:
        flash("Please select a valid site.", "danger")
        return redirect(url_for("scraper.index_view"))

    pipeline = ScrapingPipeline()
    try:
        res = pipeline.run_site_crawl(site_key=site_key, max_pages_per_category=max_pages)
        flash(
            f"Crawl completed for '{site_key}'! Saved {res['articles_saved']} articles and {res['images_downloaded']} images.",
            "success",
        )
    except Exception as e:
        flash(f"Error crawling site '{site_key}': {e}", "danger")

    return redirect(url_for("scraper.index_view"))


@scraper_bp.route("/scrape-url", methods=["POST"])
@roles_required("admin", "editor")
def scrape_single_url():
    """Scrape and ingest an individual article URL."""
    url = request.form.get("url", "").strip()
    site_key = request.form.get("site_key") or None
    category = request.form.get("category") or None

    if not url:
        flash("Please provide a valid article URL.", "danger")
        return redirect(url_for("scraper.index_view"))

    pipeline = ScrapingPipeline()
    try:
        with get_db_session() as session:
            article = pipeline.process_and_save_article(
                session=session,
                article_url=url,
                site_key=site_key,
                category=category,
                download_images=True,
            )
            if article:
                flash(f"Article '{article.title[:40]}...' scraped and saved successfully!", "success")
            else:
                flash("Could not parse article from URL.", "warning")
    except Exception as e:
        flash(f"Error scraping URL: {e}", "danger")

    return redirect(url_for("scraper.index_view"))
