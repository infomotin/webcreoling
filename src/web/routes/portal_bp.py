"""
Public Digital Newspaper Portal Blueprint.
Provides a modern Bangla digital newspaper frontend with breaking news tickers,
lead hero banners, auto-highlighted articles, opinion polls, likes, social shares, and newsletter subscription.
"""

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from sqlalchemy.orm import joinedload
from src.storage.database import get_db_session
from src.storage.models import Article
from src.storage.repositories import (
    ArticleRepository,
    PortalRepository,
    SiteConfigRepository,
    AdvertisementRepository,
    BlockchainLedgerRepository,
)

portal_bp = Blueprint("portal", __name__)


@portal_bp.context_processor
def inject_portal_globals():
    """Inject dynamic site branding, dynamic footer, and active ad banners into all portal views."""
    try:
        with get_db_session() as session:
            cfg_repo = SiteConfigRepository(session)
            ad_repo = AdvertisementRepository(session)
            cfg_repo.seed_default_configs()
            ad_repo.seed_default_ads()

            branding = cfg_repo.get_config("branding", {})
            footer = cfg_repo.get_config("footer", {})
            ads = ad_repo.get_active_ads_dict()

            return {
                "site_branding": branding,
                "site_footer": footer,
                "active_ads": ads,
            }
    except Exception:
        return {
            "site_branding": {},
            "site_footer": {},
            "active_ads": {},
        }


@portal_bp.route("")
@portal_bp.route("/")
def index_view():
    """Render public digital newspaper homepage."""
    category_filter = request.args.get("category", "").strip()
    search_query = request.args.get("q", "").strip()

    with get_db_session() as session:
        article_repo = ArticleRepository(session)
        portal_repo = PortalRepository(session)
        ad_repo = AdvertisementRepository(session)

        # Process any pending scheduled releases
        article_repo.process_scheduled_publishing()

        # Seed default poll if none exists
        portal_repo.seed_default_poll()

        # Track impression on header ad
        active_header = ad_repo.get_active_ad_by_slot("header_top")
        if active_header:
            ad_repo.record_impression(active_header.id)

        lead_hero = article_repo.get_lead_hero_article()
        exclude_id = lead_hero.id if lead_hero else None

        breaking_news = article_repo.get_breaking_news(limit=6)
        highlighted = article_repo.get_highlighted_articles(limit=8, exclude_id=exclude_id)
        trending = article_repo.get_trending_articles(limit=5)
        latest_news = session.query(Article).order_by(Article.id.desc()).limit(5).all()
        active_poll = portal_repo.get_active_poll()

        # Category Blocks
        national_news = article_repo.get_articles_by_category("bangladesh", limit=4, exclude_id=exclude_id)
        politics_news = article_repo.get_articles_by_category("politics", limit=4, exclude_id=exclude_id)
        international_news = article_repo.get_articles_by_category("international", limit=4, exclude_id=exclude_id)
        business_news = article_repo.get_articles_by_category("business", limit=4, exclude_id=exclude_id)
        tech_news = article_repo.get_articles_by_category("technology", limit=4, exclude_id=exclude_id)
        sports_news = article_repo.get_articles_by_category("sports", limit=4, exclude_id=exclude_id)
        entertainment_news = article_repo.get_articles_by_category("entertainment", limit=4, exclude_id=exclude_id)
        multimedia_news = article_repo.get_highlighted_articles(limit=4, exclude_id=exclude_id)
        latest_news = (
            session.query(Article)
            .options(joinedload(Article.images))
            .filter(Article.scrape_status == "completed")
            .order_by(Article.id.desc())
            .limit(6)
            .all()
        )

        # If search or category filter active
        filter_results = None
        if search_query:
            filter_results = article_repo.search_fts(search_query, top_k=12)
        elif category_filter:
            filter_results = article_repo.get_articles_by_category(category_filter, limit=12)

        return render_template(
            "portal.html",
            lead_hero=lead_hero,
            highlighted=highlighted,
            breaking_news=breaking_news,
            trending=trending,
            latest_news=latest_news,
            active_poll=active_poll.to_dict() if active_poll else None,
            national_news=national_news,
            politics_news=politics_news,
            international_news=international_news,
            business_news=business_news,
            tech_news=tech_news,
            sports_news=sports_news,
            entertainment_news=entertainment_news,
            multimedia_news=multimedia_news,
            category_filter=category_filter,
            search_query=search_query,
            filter_results=filter_results,
        )


@portal_bp.route("/section/<category>")
def section_view(category: str):
    """Render dedicated category/section news page in Prothom Alo style."""
    page = request.args.get("page", 1, type=int)
    with get_db_session() as session:
        article_repo = ArticleRepository(session)
        portal_repo = PortalRepository(session)

        data = article_repo.get_section_page_data(category=category, page=page, page_size=12)
        breaking_news = article_repo.get_breaking_news(limit=5)
        active_poll = portal_repo.get_active_poll()

        return render_template(
            "portal_section.html",
            category=category,
            section_hero=data["section_hero"],
            articles=data["articles"],
            section_trending=data["section_trending"],
            total_count=data["total_count"],
            page=data["page"],
            total_pages=data["total_pages"],
            breaking_news=breaking_news,
            active_poll=active_poll.to_dict() if active_poll else None,
        )


@portal_bp.route("/archive")
def archive_view():
    """Render archive explorer page with date picker, category filter, and historical date browsing."""
    date_str = request.args.get("date", "").strip() or None
    category = request.args.get("category", "").strip() or None
    page = request.args.get("page", 1, type=int)

    with get_db_session() as session:
        article_repo = ArticleRepository(session)
        portal_repo = PortalRepository(session)

        data = article_repo.get_archive_articles(date_str=date_str, category=category, page=page, page_size=15)
        breaking_news = article_repo.get_breaking_news(limit=5)
        active_poll = portal_repo.get_active_poll()

        return render_template(
            "portal_archive.html",
            selected_date=data["selected_date"],
            available_dates=data["available_dates"],
            articles=data["articles"],
            total_count=data["total_count"],
            page=data["page"],
            total_pages=data["total_pages"],
            category=data["category"],
            breaking_news=breaking_news,
            active_poll=active_poll.to_dict() if active_poll else None,
        )


@portal_bp.route("/article/<int:article_id>")
@portal_bp.route("/<int:article_id>")
def article_reader_view(article_id: int):
    """Render full professional article reader view."""
    with get_db_session() as session:
        article_repo = ArticleRepository(session)
        portal_repo = PortalRepository(session)
        ad_repo = AdvertisementRepository(session)

        # Track impression on mid article ad
        mid_ad = ad_repo.get_active_ad_by_slot("article_mid")
        if mid_ad:
            ad_repo.record_impression(mid_ad.id)

        # Increment view count
        article_repo.increment_views(article_id)
        article = article_repo.get_by_id(article_id)

        if not article:
            flash("নিবন্ধটি পাওয়া যায়নি বা মুছে ফেলা হয়েছে।", "warning")
            return redirect(url_for("portal.index_view"))

        related = article_repo.get_related_articles(article_id, category=article.category, limit=3)
        breaking_news = article_repo.get_breaking_news(limit=5)
        active_poll = portal_repo.get_active_poll()

        # Cryptographic Blockchain Verification Details
        ledger_repo = BlockchainLedgerRepository(session)
        is_valid, msg, ledger_info = ledger_repo.verify_article_ledger(article_id)

        return render_template(
            "portal_article.html",
            article=article,
            related_articles=related,
            breaking_news=breaking_news,
            active_poll=active_poll.to_dict() if active_poll else None,
            ledger_info=ledger_info,
            is_ledger_verified=is_valid,
        )


@portal_bp.route("/verify/<int:article_id>")
def article_verification_certificate_view(article_id: int):
    """Public Cryptographic Proof Certificate for News Article Verification."""
    with get_db_session() as session:
        article_repo = ArticleRepository(session)
        ledger_repo = BlockchainLedgerRepository(session)
        article = article_repo.get_by_id(article_id)

        if not article:
            flash("যাচাইকৃত আর্টিকেল পাওয়া যায়নি।", "warning")
            return redirect(url_for("portal.index_view"))

        is_valid, reason, details = ledger_repo.verify_article_ledger(article_id)
        block = ledger_repo.get_block_by_article_id(article_id)
        blockchain_stats = ledger_repo.get_blockchain_stats()

        if request.args.get("format") == "json":
            return jsonify({
                "article_id": article_id,
                "is_valid": is_valid,
                "reason": reason,
                "proof": details,
                "block": block.to_dict() if block else None,
                "stats": blockchain_stats,
            })

        return render_template(
            "portal_verify.html",
            article=article,
            is_valid=is_valid,
            reason=reason,
            details=details,
            block=block.to_dict() if block else None,
            blockchain_stats=blockchain_stats,
        )


@portal_bp.route("/ad/click/<int:ad_id>")
def ad_click_redirect(ad_id: int):
    """Record ad click and redirect user to target destination."""
    with get_db_session() as session:
        ad_repo = AdvertisementRepository(session)
        target_url = ad_repo.record_click(ad_id)
        if target_url:
            return redirect(target_url)
    return redirect(url_for("portal.index_view"))


@portal_bp.route("/api/like/<int:article_id>", methods=["POST"])
def toggle_like_api(article_id: int):
    """AJAX endpoint for toggling reader article like."""
    voter_ip = request.remote_addr or "127.0.0.1"
    with get_db_session() as session:
        repo = ArticleRepository(session)
        result = repo.toggle_like(article_id, voter_ip)
        return jsonify(result)


@portal_bp.route("/api/poll/vote", methods=["POST"])
def vote_poll_api():
    """AJAX endpoint for casting reader vote in opinion poll."""
    data = request.get_json(force=True, silent=True) or {}
    poll_id = int(data.get("poll_id", 0))
    option_id = int(data.get("option_id", 0))
    voter_ip = request.remote_addr or "127.0.0.1"

    if not poll_id or not option_id:
        return jsonify({"status": "error", "message": "অবৈধ ভোট ডেটা।"}), 400

    with get_db_session() as session:
        portal_repo = PortalRepository(session)
        res = portal_repo.vote_poll(poll_id, option_id, voter_ip)
        return jsonify(res)


@portal_bp.route("/api/subscribe", methods=["POST"])
def subscribe_newsletter_api():
    """AJAX endpoint for reader newsletter subscription."""
    data = request.get_json(force=True, silent=True) or {}
    email = data.get("email", "").strip()

    with get_db_session() as session:
        portal_repo = PortalRepository(session)
        res = portal_repo.add_subscriber(email)
        return jsonify(res)


@portal_bp.route("/media/placeholders/<filename>")
@portal_bp.route("/media/placeholder/<filename>")
def placeholder_image_view(filename: str):
    """Serve category-based placeholder SVG images with high-res styling."""
    from pathlib import Path
    from flask import send_from_directory
    clean_name = filename.lower().replace(".svg", "")
    placeholders_dir = Path(__file__).resolve().parent.parent / "static" / "img" / "placeholders"
    target_file = f"{clean_name}.svg"
    if not (placeholders_dir / target_file).exists():
        target_file = "default.svg"
    return send_from_directory(placeholders_dir, target_file, mimetype="image/svg+xml")


