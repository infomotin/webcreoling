"""
Advanced Scraper, Social Media Ingestion & AI Pilot Management Blueprint.
Enables Admins and Editors to trigger portal crawls, ingest YouTube/Social news,
run Worldwide multi-lingual scrapers, and control the Autonomous AI Pilot Brain.
"""

from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from src.common.logger import get_logger
from src.scraper.engine import ScraperEngine
from src.scraper.pipeline import ScrapingPipeline
from src.scraper.custom_portal_ingester import CustomPortalIngester
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
from src.automation.auto_scroller import AutoScroller
from src.web.auth import login_required, roles_required

logger = get_logger("webcreoling.web.scraper_bp")
scraper_bp = Blueprint("scraper", __name__)


@scraper_bp.route("")
@login_required
def index_view():
    """Display configured portals, custom ingestion studio, social media presets, AI Pilot metrics, scheduler status, and live tasks."""
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

    recent_custom_articles = CustomPortalIngester.list_recent_custom_ingested(limit=15)

    with get_db_session() as session:
        scroller_config = AutoScroller.get_config(session)
    scroller_items = AutoScroller.list_recent_items(limit=25)
    scroller_stats = AutoScroller.get_stats()

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
        recent_custom_articles=recent_custom_articles,
        youtube_channels=YouTubePublicNewsIngester.DEFAULT_CHANNELS,
        world_feeds=WorldNewsMultiLingualIngester.FEEDS,
        social_outlets=FacebookPublicNewsIngester.PUBLIC_OUTLETS,
        scheduled_jobs=scheduler.get_status()["jobs"],
        recent_tasks=task_manager.list_tasks(limit=10),
        scroller_config=scroller_config,
        scroller_items=scroller_items,
        scroller_stats=scroller_stats,
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
    from src.storage.repositories import BlockchainLedgerRepository

    with get_db_session() as session:
        repo = ArticleRepository(session)
        article = repo.get_by_id(article_id)
        if not article:
            flash("সংবাদ পাওয়া যায়নি।", "danger")
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

        article.updated_at = datetime.utcnow()
        session.flush()

        # Re-seal cryptographic ledger so verification reflects the synthesized content
        try:
            BlockchainLedgerRepository(session).mint_block_for_article(article.id)
        except Exception as e:
            logger.warning(f"Could not re-mint ledger block for article #{article_id}: {e}")

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
    
    # Regions (multi-checkbox or comma-separated text)
    regions_list = request.form.getlist("target_regions")
    regions_raw = request.form.get("target_regions_text", "").strip()
    if regions_raw:
        regions_list.extend([r.strip().lower() for r in regions_raw.split(",") if r.strip()])
    regions = list(dict.fromkeys(regions_list))

    # Countries (comma-separated string e.g. BD, IN, US, UK, SA)
    countries_raw = request.form.get("target_countries", "").strip()
    countries = [c.strip().upper() for c in countries_raw.split(",") if c.strip()] if countries_raw else []

    # Languages
    languages_list = request.form.getlist("target_languages")
    languages_raw = request.form.get("target_languages_text", "").strip()
    if languages_raw:
        languages_list.extend([l.strip().lower() for l in languages_raw.split(",") if l.strip()])
    languages = list(dict.fromkeys(languages_list))

    # Categories
    categories_list = request.form.getlist("target_categories")
    categories_raw = request.form.get("target_categories_text", "").strip()
    if categories_raw:
        categories_list.extend([c.strip().lower() for c in categories_raw.split(",") if c.strip()])
    categories = list(dict.fromkeys(categories_list))

    # Allowed Portal Sources
    portals_list = request.form.getlist("allowed_portal_sources")
    portals_raw = request.form.get("allowed_portal_sources_text", "").strip()
    if portals_raw:
        portals_list.extend([p.strip().lower() for p in portals_raw.split(",") if p.strip()])
    portals = list(dict.fromkeys(portals_list))

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


@scraper_bp.route("/rules/get/<int:rule_id>")
@login_required
def get_rule_json(rule_id: int):
    """Return JSON details of a single rule for modal editing."""
    with get_db_session() as session:
        repo = AIBrainRuleRepository(session)
        rule = repo.get_rule_by_id(rule_id)
        if not rule:
            return jsonify({"error": "Rule not found"}), 404
        return jsonify(rule.to_dict())


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


@scraper_bp.route("/api/verify-rule", methods=["POST"])
@login_required
def api_verify_rule():
    """Real-time Diagnostic Verification API testing an article against active AI Brain rules."""
    req_json = request.get_json(silent=True) or request.form.to_dict()
    
    title = req_json.get("title", "").strip()
    content = req_json.get("content", "").strip()
    source = req_json.get("source", "Open News Wire").strip()
    category = req_json.get("category", "bangladesh").strip()
    country_code = req_json.get("country_code", "").strip()
    language = req_json.get("language", "bn").strip()

    if not title:
        return jsonify({"error": "Title is required for verification"}), 400

    with get_db_session() as session:
        repo = AIBrainRuleRepository(session)
        active_rules = repo.get_active_rules()
        
        result = AIPilotBrain.verify_article_against_rules(
            sample_title=title,
            sample_content=content,
            sample_source=source,
            sample_category=category,
            sample_country_code=country_code if country_code else None,
            sample_language=language,
            rules=active_rules,
        )

    return jsonify(result)


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


@scraper_bp.route("/social-channels/get/<int:channel_id>")
@login_required
def get_social_channel_json(channel_id: int):
    """Return JSON configuration of a single social channel for modal editing."""
    with get_db_session() as session:
        repo = SocialChannelRepository(session)
        channel = repo.get_channel_by_id(channel_id)
        if not channel:
            return jsonify({"error": "Channel not found"}), 404
        return jsonify(channel.to_dict())


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


@scraper_bp.route("/social-channels/reset-status/<int:channel_id>", methods=["POST"])
@roles_required("admin", "editor")
def reset_social_channel_status(channel_id: int):
    """Reset a restricted or backup channel back to HEALTHY."""
    with get_db_session() as session:
        repo = SocialChannelRepository(session)
        ch = repo.reset_channel_status(channel_id)
        if ch:
            flash(f"সোশ্যাল চ্যানেল '{ch.account_name}' এর স্ট্যাটাস রিসেট করে HEALTHY করা হয়েছে!", "success")
        else:
            flash("চ্যানেল পাওয়া যায়নি।", "danger")

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


@scraper_bp.route("/social-channels/test-failover/<int:channel_id>", methods=["POST"])
@roles_required("admin", "editor")
def test_channel_failover(channel_id: int):
    """Simulate Facebook/Platform API ban and execute Anti-Ban Failover to backup account."""
    res = UnifiedSocialBroadcaster.simulate_channel_failover(channel_id=channel_id)
    if res.get("success"):
        flash(f"🛡️ {res.get('message')}", "warning")
    else:
        flash(f"ফেইলওভার টেস্ট ব্যর্থ: {res.get('message')}", "danger")

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


# ==============================================================================
# Custom News Portal & Public Article Ingestion & AI 100% Original Studio Routes
# ==============================================================================

@scraper_bp.route("/custom-scrape-post", methods=["POST"])
@roles_required("admin", "editor")
def custom_scrape_post():
    """
    Standard Web Form: Ingests any public news URL, synthesizes 100% unique Bengali copy
    (preserving 95%+ core facts), and directly publishes to our live news portal.
    """
    url = request.form.get("url", "").strip()
    source_name = request.form.get("source_name", "").strip()
    category = request.form.get("category", "bangladesh").strip()
    target_placement = request.form.get("target_placement", "STANDARD").strip()
    publish_now = bool(request.form.get("publish_now", "1") in ["1", "true", "True", "on"])
    originality_mode = request.form.get("originality_mode", "100_percent_unique").strip()
    author_name = request.form.get("author_name", "").strip()
    custom_headline = request.form.get("custom_headline", "").strip()
    custom_body = request.form.get("custom_body", "").strip()

    if not url:
        flash("অনুগ্রহ করে একটি সঠিক সংবাদ বা পোর্টালের লিংক দিন।", "danger")
        return redirect(url_for("scraper.index_view", tab="custom"))

    try:
        res = CustomPortalIngester.scrape_and_synthesize_original_news(
            url=url,
            source_name=source_name or None,
            category=category,
            target_placement=target_placement,
            publish_now=publish_now,
            originality_mode=originality_mode,
            author_name=author_name or None,
            custom_headline=custom_headline or None,
            custom_body=custom_body or None,
        )
        status_txt = "আমাদের লাইভ নিউজ পোর্টালে সরাসরি প্রকাশ করা হয়েছে 🚀" if publish_now else "ড্রাফট হিসেবে সংরক্ষণ করা হয়েছে 📝"
        flash(
            f"সফল! সংবাদটি সংগ্রহ করে ১০০% অরিজিনাল কন্টেন্টে রূপান্তর করা হয়েছে এবং {status_txt} (ইউনিক স্কোর: {res['originality_score']}%, সত্যতা: {res['factuality_score']}%)",
            "success",
        )
        return redirect(url_for("scraper.index_view", tab="custom", highlight_id=res["article_id"]))
    except Exception as e:
        logger.error(f"Error in custom scrape post: {e}")
        flash(f"সংবাদ সংগ্রহ ও এআই রূপান্তরে ত্রুটি: {e}", "danger")
        return redirect(url_for("scraper.index_view", tab="custom"))


@scraper_bp.route("/api/custom-portal/scrape-and-publish", methods=["POST"])
@roles_required("admin", "editor")
def api_custom_portal_scrape_and_publish():
    """
    AJAX Endpoint: Ingests any public portal or news article URL, transforms into
    100% unique journalistic Bengali copy, and returns full side-by-side comparison telemetry.
    """
    req_data = request.get_json(silent=True) or request.form.to_dict()
    url = req_data.get("url", "").strip()
    source_name = req_data.get("source_name", "").strip()
    category = req_data.get("category", "bangladesh").strip()
    target_placement = req_data.get("target_placement", "STANDARD").strip()
    publish_now = bool(str(req_data.get("publish_now", "true")).lower() in ["true", "1", "yes", "on"])
    originality_mode = req_data.get("originality_mode", "100_percent_unique").strip()
    author_name = req_data.get("author_name", "").strip()
    custom_headline = req_data.get("custom_headline", "").strip()
    custom_body = req_data.get("custom_body", "").strip()

    if not url:
        return jsonify({"success": False, "error": "অনুগ্রহ করে একটি সঠিক সংবাদ বা পোর্টালের লিংক প্রদান করুন।"}), 400

    try:
        res = CustomPortalIngester.scrape_and_synthesize_original_news(
            url=url,
            source_name=source_name or None,
            category=category,
            target_placement=target_placement,
            publish_now=publish_now,
            originality_mode=originality_mode,
            author_name=author_name or None,
            custom_headline=custom_headline or None,
            custom_body=custom_body or None,
        )
        return jsonify(res)
    except Exception as e:
        logger.error(f"API Custom Scrape error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@scraper_bp.route("/api/custom-portal/publish-draft", methods=["POST"])
@roles_required("admin", "editor")
def api_custom_portal_publish_draft():
    """AJAX Endpoint: Instantly publishes an existing draft article to our live portal (/news/)."""
    req_data = request.get_json(silent=True) or request.form.to_dict()
    article_id = int(req_data.get("article_id", 0))
    position_placement = req_data.get("position_placement", "STANDARD")
    is_breaking = bool(str(req_data.get("is_breaking", "false")).lower() in ["true", "1", "yes"])
    is_featured = bool(str(req_data.get("is_featured", "false")).lower() in ["true", "1", "yes"])

    if not article_id:
        return jsonify({"success": False, "error": "আর্টিকেল আইডি আবশ্যক।"}), 400

    res = CustomPortalIngester.publish_article_to_portal(
        article_id=article_id,
        position_placement=position_placement,
        is_breaking=is_breaking,
        is_featured=is_featured,
    )
    return jsonify(res)


@scraper_bp.route("/api/custom-portal/recent-ingested")
@login_required
def api_custom_portal_recent_ingested():
    """JSON API returning list of recently scraped & AI-synthesized news articles."""
    limit = int(request.args.get("limit", 15))
    articles = CustomPortalIngester.list_recent_custom_ingested(limit=limit)
    return jsonify({"success": True, "articles": articles})





# ==============================================================================
# Auto Scroller (Scrape -> 98% Mine -> Rewrite -> AI Gate -> Auto/Manual Publish)
# ==============================================================================

@scraper_bp.route("/scroller/config", methods=["POST"])
@roles_required("admin", "editor")
def save_scroller_config():
    """Save Auto Scroller pipeline settings (source URLs, thresholds, auto-post toggle)."""
    data = {
        "enabled": bool(request.form.get("enabled")),
        "auto_post_enabled": bool(request.form.get("auto_post_enabled")),
        "translate_to_bangla": bool(request.form.get("translate_to_bangla")),
        "source_urls": request.form.get("source_urls", "").strip(),
        "similarity_threshold": float(request.form.get("similarity_threshold", 0.98)),
        "ai_publish_threshold": float(request.form.get("ai_publish_threshold", 75.0)),
        "max_items_per_cycle": int(request.form.get("max_items_per_cycle", 10)),
        "category": (request.form.get("category", "general") or "general").strip(),
    }
    if not 0.5 <= data["similarity_threshold"] <= 1.0:
        flash("Similarity threshold 0.5 থেকে 1.0 এর মধ্যে হতে হবে।", "danger")
        return redirect(url_for("scraper.index_view", tab="scroller"))

    with get_db_session() as session:
        AutoScroller.save_config(session, data)
        session.commit()

    auto_txt = "অটো-পোস্ট চালু ✅" if data["auto_post_enabled"] else "ম্যানুয়াল পাবলিশ (অপেক্ষমান)"
    flash(f"Auto Scroller কনফিগ সংরক্ষিত হয়েছে। {auto_txt}", "success")
    return redirect(url_for("scraper.index_view", tab="scroller"))


@scraper_bp.route("/scroller/run", methods=["POST"])
@roles_required("admin", "editor")
def run_scroller_cycle():
    """Trigger a background Auto Scroller cycle over the configured source URLs."""
    source_urls_raw = request.form.get("source_urls", "").strip()
    source_urls = [u.strip() for u in source_urls_raw.replace("\n", ",").split(",") if u.strip()] or None
    max_items = int(request.form.get("max_items", 5) or 5)

    task_mgr = get_task_manager()

    def _work(task):
        task.set_progress(15, "Auto Scroller: scraping source portals...")
        summary = AutoScroller.run_cycle(source_urls=source_urls, max_items=max_items)
        task.set_progress(80, "Auto Scroller: processing waiting queue...")
        queue_result = AutoScroller.process_waiting_queue()
        task.set_progress(100, "Cycle finished.")
        return {"cycle": summary, "queue": queue_result}

    task = task_mgr.submit_task(
        task_type="AUTO_SCROLLER",
        title="Auto Scroller Cycle (Scrape -> Mine -> Rewrite -> Publish)",
        worker_func=_work,
        description=f"Scraping up to {max_items} source URLs through the 98% similarity mining + AI Brain gate pipeline.",
    )
    flash(f"অটো স্ক্রলার সাইকেল শুরু হয়েছে (Task ID: {task.task_id})!", "success")
    return redirect(url_for("scraper.index_view", tab="scroller"))


@scraper_bp.route("/scroller/queue-process", methods=["POST"])
@roles_required("admin", "editor")
def process_scroller_queue():
    """Release the waiting queue: auto-post queued items when auto-post is enabled."""
    result = AutoScroller.process_waiting_queue()
    if result.get("published"):
        flash(f"কিউ থেকে {result['published']} টি সংবাদ পোর্টালে প্রকাশ করা হয়েছে 🚀", "success")
    else:
        flash(result.get("note", f"কিউ প্রসেস সম্পন্ন: {result.get('queued_count', 0)} টি আইটেম অপেক্ষমান।"), "info")
    return redirect(url_for("scraper.index_view", tab="scroller"))


@scraper_bp.route("/scroller/publish/<int:item_id>", methods=["POST"])
@roles_required("admin", "editor")
def publish_scroller_item(item_id: int):
    """Manually publish a queued Auto Scroller item to the live /news/ portal."""
    res = AutoScroller.manual_publish(item_id)
    if res.get("success"):
        flash(f"সংবাদ পোর্টালে প্রকাশ করা হয়েছে (Article #{res['article_id']}) — মূল সোর্স লিংকসহ 🚀", "success")
    else:
        flash(res.get("error", "প্রকাশ ব্যর্থ হয়েছে।", ), "danger")
    return redirect(url_for("scraper.index_view", tab="scroller"))


@scraper_bp.route("/scroller/reject/<int:item_id>", methods=["POST"])
@roles_required("admin", "editor")
def reject_scroller_item(item_id: int):
    """Reject a raw Auto Scroller item (never published)."""
    res = AutoScroller.manual_reject(item_id)
    if res.get("success"):
        flash(f"আইটেম #{item_id} বাতিল করা হয়েছে।", "warning")
    else:
        flash(res.get("error", "বাতিল করা যায়নি।"), "danger")
    return redirect(url_for("scraper.index_view", tab="scroller"))


@scraper_bp.route("/api/scroller/items")
@login_required
def api_scroller_items():
    """JSON list of recent Auto Scroller raw staging items."""
    limit = int(request.args.get("limit", 30))
    status = request.args.get("status") or None
    return jsonify({
        "success": True,
        "items": AutoScroller.list_recent_items(limit=limit, status=status),
        "stats": AutoScroller.get_stats(),
    })
