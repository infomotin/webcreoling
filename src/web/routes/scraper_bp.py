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
from src.storage.models import ScrapeLog, Article, AIBrainCustomRule, SocialChannelConfig, SocialBroadcastLog
from src.storage.repositories import ArticleRepository, AIBrainRuleRepository, SocialChannelRepository
from src.automation.social_broadcaster import UnifiedSocialBroadcaster, FacebookPagePublisher
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

        rule_repo = AIBrainRuleRepository(session)
        rules = rule_repo.get_all_rules()
        if not rules:
            rule_repo.seed_default_rules()
            rules = rule_repo.get_all_rules()

        social_repo = SocialChannelRepository(session)
        social_channels = social_repo.list_channels()
        broadcast_logs = social_repo.get_broadcast_logs(limit=15)

    return render_template(
        "scraper.html",
        sites=sites,
        logs=logs_data,
        stats=stats,
        pending_count=pending_count,
        published_count=published_count,
        rules=[r.to_dict() for r in rules],
        social_channels=[c.to_dict() for c in social_channels],
        broadcast_logs=[b.to_dict() for b in broadcast_logs],
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
    """Trigger background Worldwide multi-lingual newspaper ingestion & AI synthesis."""
    max_items = int(request.form.get("max_items", 3))
    selected_feeds = request.form.getlist("selected_feeds")
    feeds = [f for f in selected_feeds if f] if selected_feeds else None

    task_mgr = get_task_manager()
    task = task_mgr.submit_world_crawl_task(max_per_source=max_items, feed_keys=feeds)
    flash(f"বিশ্বের শীর্ষ সংবাদপত্রের সংবাদ সংগ্রহ ও এআই বিশ্লেষণ শুরু হয়েছে (Task ID: {task.task_id})!", "success")
    return redirect(url_for("scraper.index_view", tab="world"))


@scraper_bp.route("/trigger-ai-pilot", methods=["POST"])
@roles_required("admin", "editor")
def trigger_ai_pilot():
    """Trigger Autonomous AI Pilot Brain decision, 95% meaning synthesis, and auto-publishing cycle."""
    threshold = int(request.form.get("threshold", 70))
    max_items = int(request.form.get("max_items", 3))
    selected_feeds = request.form.getlist("selected_feeds")
    feeds = [f for f in selected_feeds if f] if selected_feeds else None

    task_mgr = get_task_manager()
    task = task_mgr.submit_ai_pilot_task(
        auto_publish_threshold=threshold,
        max_per_source=max_items,
        selected_world_feeds=feeds,
    )
    flash(f"AI Pilot Brain স্বয়ংক্রিয় সংবাদ বিশ্লেষণ ও ৭০% সত্যতা যাচাই চক্র চালু হয়েছে (Task ID: {task.task_id})!", "success")
    return redirect(url_for("scraper.index_view", tab="pilot"))


@scraper_bp.route("/synthesize/<int:article_id>", methods=["POST"])
@roles_required("admin", "editor")
def synthesize_existing_article(article_id: int):
    """Synthesize 95% meaning-preserved multi-paragraph report and evaluate 70% truth gate for any article."""
    from src.nlp.news_synthesizer import AINewsSynthesizerAndParaphraser
    from src.common.blockchain import BlockchainEngine

    with get_db_session() as session:
        repo = ArticleRepository(session)
        article = repo.get_by_id(article_id)
        if not article:
            flash("সংবাদ পাওয়া যায়নি।", "danger")
            return redirect(url_for("scraper.index_view"))

        synth = AINewsSynthesizerAndParaphraser.process_and_synthesize_news(
            raw_title=article.title,
            raw_content=article.content_text or article.summary or article.title,
            source_name=article.source or "ডিজিটাল সংবাদ ডেস্ক",
            author=article.author,
            category=article.category or "international",
        )

        article.title = synth["synthesized_title"]
        article.content_text = synth["synthesized_body"]
        article.summary = synth["executive_summary"]
        
        entities = dict(article.extracted_entities or {})
        entities["news_synthesis"] = {
            "meaning_retention_score": synth["meaning_retention_score"],
            "is_truth_verified": synth["is_truth_verified"],
            "key_takeaways": synth["key_takeaways"],
            "factuality_score": synth["factuality_score"],
            "core_facts": synth["core_facts"],
        }
        entities["fake_news_analysis"] = synth["fact_check_report"]
        article.extracted_entities = entities
        
        if synth["is_truth_verified"]:
            article.scrape_status = "completed"

        session.commit()
        flash(f"সংবাদ #{article_id} সফলভাবে এআই দ্বারা বিশ্লেষণ ও ৯৫% মূল ভাবধারা সহকারে পূর্ণাঙ্গ প্রতিবেদনে রূপান্তর করা হয়েছে! সত্যতা সূচক: {synth['factuality_score']}%", "success")

    return redirect(url_for("portal.article_reader_view", article_id=article_id))


@scraper_bp.route("/scrape-url", methods=["POST"])
@roles_required("admin", "editor")
def scrape_single_url():
    """Scrape and ingest an individual article URL with AI Brain evaluation and synthesis."""
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
                # Run AI Brain evaluation and synthesis
                eval_res = AIPilotBrain.process_raw_article({
                    "url": article.url,
                    "title": article.title,
                    "content_text": article.content_text,
                    "source": article.source,
                    "category": article.category,
                })
                # Update article with synthesized content
                article.title = eval_res["title"]
                article.content_text = eval_res["content_text"]
                article.summary = eval_res["summary"]
                article.extracted_entities = eval_res["extracted_entities"]
                article.scrape_status = eval_res["scrape_status"]
                session.commit()

                flash(
                    f"Article '{article.title[:40]}...' saved & synthesized! Factuality: {eval_res['factuality_score']}% (Status: {eval_res['scrape_status']})",
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


# ==============================================================================
# AI Brain Custom Rule Management Routes
# ==============================================================================

@scraper_bp.route("/rules/save", methods=["POST"])
@roles_required("admin", "editor")
def save_rule():
    """Create or update an AI Brain targeting rule."""
    rule_id_raw = request.form.get("rule_id", "").strip()
    rule_id = int(rule_id_raw) if rule_id_raw and rule_id_raw.isdigit() else None

    name = request.form.get("name", "Custom Rule").strip()
    regions = request.form.getlist("target_regions")
    countries_raw = request.form.get("target_countries", "").strip()
    countries = [c.strip().upper() for c in countries_raw.split(",") if c.strip()] if countries_raw else []
    languages = request.form.getlist("target_languages")
    categories = request.form.getlist("target_categories")
    portals = request.form.getlist("allowed_portal_sources")

    req_kw_raw = request.form.get("required_keywords", "").strip()
    required_keywords = [k.strip() for k in req_kw_raw.split(",") if k.strip()] if req_kw_raw else []

    excl_kw_raw = request.form.get("excluded_keywords", "").strip()
    excluded_keywords = [k.strip() for k in excl_kw_raw.split(",") if k.strip()] if excl_kw_raw else []

    min_score = float(request.form.get("min_credibility_score", 70.0))
    auto_translate = bool(request.form.get("auto_translate_to_bangla"))
    auto_publish = bool(request.form.get("auto_publish"))
    auto_broadcast_social = bool(request.form.get("auto_broadcast_social"))
    prompt_rules = request.form.get("custom_prompt_rules", "").strip()
    is_active = bool(request.form.get("is_active", True))

    with get_db_session() as session:
        repo = AIBrainRuleRepository(session)
        rule = repo.create_or_update_rule(
            rule_id=rule_id,
            name=name,
            target_regions=regions,
            target_countries=countries,
            target_languages=languages,
            target_categories=categories,
            required_keywords=required_keywords,
            excluded_keywords=excluded_keywords,
            allowed_portal_sources=portals,
            min_credibility_score=min_score,
            auto_translate_to_bangla=auto_translate,
            auto_publish=auto_publish,
            auto_broadcast_social=auto_broadcast_social,
            custom_prompt_rules=prompt_rules,
            is_active=is_active,
        )
        flash(f"AI Brain Rule '{rule.name}' saved successfully!", "success")

    return redirect(url_for("scraper.index_view", tab="rules"))


@scraper_bp.route("/rules/toggle/<int:rule_id>", methods=["POST"])
@roles_required("admin", "editor")
def toggle_rule(rule_id: int):
    """Toggle activation of an AI Brain targeting rule."""
    with get_db_session() as session:
        repo = AIBrainRuleRepository(session)
        new_state = repo.toggle_rule(rule_id)
        state_txt = "সক্রিয় (Active)" if new_state else "নিষ্ক্রিয় (Disabled)"
        flash(f"AI Brain রুল #{rule_id} এখন {state_txt}!", "info")

    return redirect(url_for("scraper.index_view", tab="rules"))


@scraper_bp.route("/rules/delete/<int:rule_id>", methods=["POST"])
@roles_required("admin", "editor")
def delete_rule(rule_id: int):
    """Delete an AI Brain targeting rule."""
    with get_db_session() as session:
        repo = AIBrainRuleRepository(session)
        repo.delete_rule(rule_id)
        flash(f"AI Brain রুল #{rule_id} মুছে ফেলা হয়েছে।", "warning")

    return redirect(url_for("scraper.index_view", tab="rules"))


# ==============================================================================
# Connected Social Media Channel Management Routes
# ==============================================================================

@scraper_bp.route("/social-channels/save", methods=["POST"])
@roles_required("admin", "editor")
def save_social_channel():
    """Connect a new social account or update existing credentials."""
    channel_id_raw = request.form.get("channel_id", "").strip()
    channel_id = int(channel_id_raw) if channel_id_raw and channel_id_raw.isdigit() else None

    platform = request.form.get("platform", "facebook").strip().lower()
    account_name = request.form.get("account_name", "").strip()
    page_id = request.form.get("page_id_or_channel_id", "").strip()
    app_id = request.form.get("app_id", "").strip()
    app_secret = request.form.get("app_secret", "").strip()
    access_token = request.form.get("access_token", "").strip()
    is_active = bool(request.form.get("is_active", True))
    is_primary = bool(request.form.get("is_primary", True))

    failover_raw = request.form.get("failover_account_id", "").strip()
    failover_id = int(failover_raw) if failover_raw and failover_raw.isdigit() else None

    if not account_name or not page_id:
        flash("অ্যাকাউন্টের নাম ও পেজ/চ্যানেল আইডি দেওয়া আবশ্যক।", "danger")
        return redirect(url_for("scraper.index_view", tab="social"))

    with get_db_session() as session:
        repo = SocialChannelRepository(session)
        ch = repo.create_or_update_channel(
            channel_id=channel_id,
            platform=platform,
            account_name=account_name,
            page_id_or_channel_id=page_id,
            app_id=app_id if app_id else None,
            app_secret=app_secret if app_secret else None,
            access_token=access_token if access_token else None,
            is_active=is_active,
            is_primary=is_primary,
            failover_account_id=failover_id,
        )
        flash(f"সোশ্যাল চ্যানেল '{ch.account_name}' ({platform.upper()}) সংরক্ষিত হয়েছে!", "success")

    return redirect(url_for("scraper.index_view", tab="social"))


@scraper_bp.route("/social-channels/toggle/<int:channel_id>", methods=["POST"])
@roles_required("admin", "editor")
def toggle_social_channel(channel_id: int):
    """Toggle active state of a social channel."""
    with get_db_session() as session:
        repo = SocialChannelRepository(session)
        state = repo.toggle_channel(channel_id)
        state_txt = "সক্রিয় (Active)" if state else "স্থগিত (Disabled)"
        flash(f"সোশ্যাল চ্যানেল #{channel_id} এখন {state_txt}!", "info")

    return redirect(url_for("scraper.index_view", tab="social"))


@scraper_bp.route("/social-channels/test/<int:channel_id>", methods=["POST"])
@roles_required("admin", "editor")
def test_broadcast_channel(channel_id: int):
    """Test-broadcast a sample breaking news item to a specific social channel."""
    with get_db_session() as session:
        repo = SocialChannelRepository(session)
        channel = repo.get_channel_by_id(channel_id)
        if not channel:
            flash("সোশ্যাল চ্যানেল পাওয়া যায়নি।", "danger")
            return redirect(url_for("scraper.index_view", tab="social"))

        sample_article = {
            "id": 1,
            "title": "টেস্ট সংবাদ: ডিজিটাল নিউজরুম এআই অটো-ব্রডকাস্ট টেস্ট",
            "summary": "আমাদের এআই রোবট স্বয়ংক্রিয়ভাবে আন্তর্জাতিক ও দেশীয় সংবাদ অনুবাদ ও ফিল্টার করে সরাসরি ফেসবুক, ইউটিউব ও টিকটকে পোস্ট করছে।",
            "category": "technology",
        }

        # Perform dispatch
        report = UnifiedSocialBroadcaster.broadcast_article(sample_article)
        flash(f"টেস্ট ব্রডকাস্ট সম্পন্ন হয়েছে! চ্যানেল: {channel.account_name} | ফলাফল: {report.get('dispatched_count')} টি সফল পোস্ট।", "success")

    return redirect(url_for("scraper.index_view", tab="social"))


@scraper_bp.route("/social-channels/delete/<int:channel_id>", methods=["POST"])
@roles_required("admin", "editor")
def delete_social_channel(channel_id: int):
    """Delete a social channel configuration."""
    with get_db_session() as session:
        repo = SocialChannelRepository(session)
        repo.delete_channel(channel_id)
        flash(f"সোশ্যাল চ্যানেল #{channel_id} মুছে ফেলা হয়েছে।", "warning")

    return redirect(url_for("scraper.index_view", tab="social"))


@scraper_bp.route("/api/broadcast-logs")
@login_required
def api_broadcast_logs():
    """Return recent outbound social media broadcast logs."""
    with get_db_session() as session:
        repo = SocialChannelRepository(session)
        logs = repo.get_broadcast_logs(limit=25)
    return jsonify([l.to_dict() for l in logs])

