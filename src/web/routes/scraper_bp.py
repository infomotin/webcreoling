"""
Advanced Scraper, Social Media Ingestion & AI Pilot Management Blueprint.
Enables Admins and Editors to trigger portal crawls, ingest YouTube/Social news,
run Worldwide multi-lingual scrapers, and control the Autonomous AI Pilot Brain.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from src.scraper.engine import ScraperEngine
from src.scraper.pipeline import ScrapingPipeline
from src.scraper.social_world_ingestion import (
    YouTubePublicNewsIngester,
    WorldNewsMultiLingualIngester,
    FacebookPublicNewsIngester,
)
from src.automation.scheduler import get_scheduler
from src.automation.task_manager import get_task_manager
from src.automation.ai_pilot_brain import AIPilotBrain
from src.storage.database import get_db_session
from src.storage.models import ScrapeLog, Article
from src.storage.repositories import ArticleRepository
from src.web.auth import login_required, roles_required

scraper_bp = Blueprint("scraper", __name__)


@scraper_bp.route("")
@login_required
def index_view():
    """Display configured portals, social media presets, AI Pilot metrics, scheduler status, and live tasks."""
    engine = ScraperEngine()
    sites = engine.sites_config.get("sites", {})

    scheduler = get_scheduler()
    task_manager = get_task_manager()

    with get_db_session() as session:
        logs = (
            session.query(ScrapeLog)
            .order_by(ScrapeLog.id.desc())
            .limit(10)
            .all()
        )
        logs_data = [l.to_dict() for l in logs]

        repo = ArticleRepository(session)
        stats = repo.get_database_stats()
        pending_count = repo.count_articles(scrape_status="pending")
        published_count = repo.count_articles(scrape_status="completed")

    return render_template(
        "scraper.html",
        sites=sites,
        logs=logs_data,
        stats=stats,
        pending_count=pending_count,
        published_count=published_count,
        youtube_channels=YouTubePublicNewsIngester.DEFAULT_CHANNELS,
        world_feeds=WorldNewsMultiLingualIngester.FEEDS,
        social_outlets=FacebookPublicNewsIngester.PUBLIC_OUTLETS,
        scheduled_jobs=scheduler.get_status()["jobs"],
        recent_tasks=task_manager.list_tasks(limit=10),
    )


@scraper_bp.route("/trigger", methods=["POST"])
@roles_required("admin", "editor")
def trigger_crawl():
    """Trigger a background crawl on a configured news portal."""
    site_key = request.form.get("site_key", "").strip()
    max_pages = int(request.form.get("max_pages", 2))

    if not site_key:
        flash("Please select a valid site.", "danger")
        return redirect(url_for("scraper.index_view"))

    task_mgr = get_task_manager()
    task = task_mgr.submit_crawl_task(site_key=site_key, max_pages=max_pages)
    flash(f"Crawl job '{site_key}' submitted to background workers (Task ID: {task.task_id})!", "success")
    return redirect(url_for("scraper.index_view"))


@scraper_bp.route("/trigger-social", methods=["POST"])
@roles_required("admin", "editor")
def trigger_social_crawl():
    """Trigger background YouTube & Social Media news ingestion."""
    max_items = int(request.form.get("max_items", 3))
    task_mgr = get_task_manager()
    task = task_mgr.submit_social_crawl_task(max_per_source=max_items)
    flash(f"YouTube & Social Media Ingestion started (Task ID: {task.task_id})!", "success")
    return redirect(url_for("scraper.index_view"))


@scraper_bp.route("/trigger-world", methods=["POST"])
@roles_required("admin", "editor")
def trigger_world_crawl():
    """Trigger background Worldwide multi-lingual news ingestion."""
    max_items = int(request.form.get("max_items", 3))
    task_mgr = get_task_manager()
    task = task_mgr.submit_world_crawl_task(max_per_source=max_items)
    flash(f"Worldwide Multi-Lingual News Ingestion started (Task ID: {task.task_id})!", "success")
    return redirect(url_for("scraper.index_view"))


@scraper_bp.route("/trigger-ai-pilot", methods=["POST"])
@roles_required("admin", "editor")
def trigger_ai_pilot():
    """Trigger Autonomous AI Pilot Brain decision and auto-publishing cycle."""
    threshold = int(request.form.get("threshold", 75))
    max_items = int(request.form.get("max_items", 3))
    task_mgr = get_task_manager()
    task = task_mgr.submit_ai_pilot_task(auto_publish_threshold=threshold, max_per_source=max_items)
    flash(f"AI Pilot Brain Autonomous Decision Cycle launched (Task ID: {task.task_id})!", "success")
    return redirect(url_for("scraper.index_view"))


@scraper_bp.route("/scrape-url", methods=["POST"])
@roles_required("admin", "editor")
def scrape_single_url():
    """Scrape and ingest an individual article URL with AI Brain evaluation."""
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
                # Run AI Brain evaluation
                eval_res = AIPilotBrain.process_raw_article({
                    "url": article.url,
                    "title": article.title,
                    "content_text": article.content_text,
                    "source": article.source,
                    "category": article.category,
                })
                flash(
                    f"Article '{article.title[:40]}...' saved! AI Credibility Score: {eval_res['credibility_score']}% ({eval_res['ai_decision']})",
                    "success",
                )
            else:
                flash("Could not parse article from URL.", "warning")
    except Exception as e:
        flash(f"Error scraping URL: {e}", "danger")

    return redirect(url_for("scraper.index_view"))


@scraper_bp.route("/api/status")
@login_required
def api_scraper_status():
    """JSON API returning live tasks, scheduler jobs, and database metrics for AJAX dashboards."""
    scheduler = get_scheduler()
    task_mgr = get_task_manager()

    with get_db_session() as session:
        repo = ArticleRepository(session)
        stats = repo.get_database_stats()

    return jsonify({
        "status": "online",
        "stats": stats,
        "scheduler": scheduler.get_status(),
        "tasks": task_mgr.list_tasks(limit=15),
    })
