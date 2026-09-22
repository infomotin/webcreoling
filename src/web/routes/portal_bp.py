"""
Public Digital Newspaper Portal Blueprint.
Provides a modern Bangla digital newspaper frontend with breaking news tickers,
lead hero banners, auto-highlighted articles, opinion polls, likes, social shares, and newsletter subscription.
"""

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from src.storage.database import get_db_session
from src.storage.repositories import ArticleRepository, PortalRepository

portal_bp = Blueprint("portal", __name__)


@portal_bp.route("")
@portal_bp.route("/")
def index_view():
    """Render public digital newspaper homepage."""
    category_filter = request.args.get("category", "").strip()
    search_query = request.args.get("q", "").strip()

    with get_db_session() as session:
        article_repo = ArticleRepository(session)
        portal_repo = PortalRepository(session)

        # Seed default poll if none exists
        portal_repo.seed_default_poll()

        lead_hero = article_repo.get_lead_hero_article()
        exclude_id = lead_hero.id if lead_hero else None

        breaking_news = article_repo.get_breaking_news(limit=6)
        highlighted = article_repo.get_highlighted_articles(limit=6, exclude_id=exclude_id)
        trending = article_repo.get_trending_articles(limit=5)
        active_poll = portal_repo.get_active_poll()

        # Category Blocks
        politics_news = article_repo.get_articles_by_category("politics", limit=4, exclude_id=exclude_id)
        sports_news = article_repo.get_articles_by_category("sports", limit=4, exclude_id=exclude_id)
        business_news = article_repo.get_articles_by_category("business", limit=4, exclude_id=exclude_id)
        tech_news = article_repo.get_articles_by_category("technology", limit=4, exclude_id=exclude_id)
        international_news = article_repo.get_articles_by_category("international", limit=4, exclude_id=exclude_id)

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
            active_poll=active_poll.to_dict() if active_poll else None,
            politics_news=politics_news,
            sports_news=sports_news,
            business_news=business_news,
            tech_news=tech_news,
            international_news=international_news,
            category_filter=category_filter,
            search_query=search_query,
            filter_results=filter_results,
        )


@portal_bp.route("/<int:article_id>")
def article_reader_view(article_id: int):
    """Render full professional article reader view."""
    with get_db_session() as session:
        article_repo = ArticleRepository(session)
        portal_repo = PortalRepository(session)

        # Increment view count
        article_repo.increment_views(article_id)
        article = article_repo.get_by_id(article_id)

        if not article:
            flash("নিবন্ধটি পাওয়া যায়নি বা মুছে ফেলা হয়েছে।", "warning")
            return redirect(url_for("portal.index_view"))

        related = article_repo.get_related_articles(article_id, category=article.category, limit=3)
        breaking_news = article_repo.get_breaking_news(limit=5)
        active_poll = portal_repo.get_active_poll()

        return render_template(
            "portal_article.html",
            article=article,
            related_articles=related,
            breaking_news=breaking_news,
            active_poll=active_poll.to_dict() if active_poll else None,
        )


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
