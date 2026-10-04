"""
Public Digital Newspaper Portal Blueprint.
Provides a modern Bangla digital newspaper frontend with breaking news tickers,
lead hero banners, auto-highlighted articles, opinion polls, likes, social shares, and newsletter subscription.
"""

from datetime import datetime

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, abort
from sqlalchemy.orm import joinedload
from src.storage.database import get_db_session
from src.storage.models import Article, ArticleComment
from src.common.seo import build_meta_description, parse_post_slug
from src.common.ttl_cache import cached
from src.web.auth import login_required, get_current_user
from src.storage.repositories import (
    ArticleRepository,
    PortalRepository,
    SiteConfigRepository,
    AdvertisementRepository,
    BlockchainLedgerRepository,
    apply_public_content_filter,
    is_public_article,
)
from src.integrations.live_data_service import get_topbar_data

portal_bp = Blueprint("portal", __name__)


def post_url(article) -> str:
    """SEO friendly permalink for a post (accepts Article, dict or plain id)."""
    if article is None:
        return url_for("portal.index_view")
    if isinstance(article, dict):
        slug, article_id = article.get("slug"), article.get("id")
    elif isinstance(article, int):
        slug, article_id = None, article
    else:
        slug, article_id = getattr(article, "slug", None), getattr(article, "id", None)
    if slug:
        return url_for("portal.post_view", post_slug=slug)
    if article_id:
        return url_for("portal.article_reader_view", article_id=article_id)
    return url_for("portal.index_view")


def _load_portal_globals() -> dict:
    """Load branding/footer/active ads in one round-trip (used as the cache producer)."""
    with get_db_session() as session:
        cfg_repo = SiteConfigRepository(session)
        ad_repo = AdvertisementRepository(session)
        return {
            "branding": cfg_repo.get_config("branding", {}),
            "footer": cfg_repo.get_config("footer", {}),
            "ads": ad_repo.get_active_ads_dict(),
        }


@portal_bp.context_processor
def inject_portal_globals():
    """Inject dynamic site branding, dynamic footer, and active ad banners into all portal views.

    The payload is read-mostly, so it is served from a 30 s process cache
    (~22 SELECTs -> 0 after the first request per window). Writers
    (SiteConfigRepository.set_config / AdvertisementRepository CRUD) call
    ``ttl_cache.invalidate("portal.globals")`` so edits show up immediately.
    Seeding itself happens once at application startup (``create_app``).
    """
    try:
        data = cached("portal.globals", 30.0, _load_portal_globals)
        return {
            "site_branding": data["branding"],
            "site_footer": data["footer"],
            "active_ads": data["ads"],
            "live_topbar": _safe_topbar(data["branding"]),
            "post_url": post_url,
        }
    except Exception:
        return {
            "site_branding": {},
            "site_footer": {},
            "active_ads": {},
            "live_topbar": _safe_topbar({}),
            "post_url": post_url,
        }


def _safe_topbar(branding: dict) -> dict:
    """Live date/weather/FX payload for the top utility bar (never raises)."""
    try:
        return get_topbar_data(branding)
    except Exception:
        return {}


@portal_bp.route("", endpoint="newspaper_home")
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

        # Process any pending scheduled releases — the background scheduler runs
        # this every 60 s anyway, so the homepage only triggers it at most once
        # per 30 s per process instead of on every single hit.
        cached("portal.scheduled_publish_tick", 30.0, article_repo.process_scheduled_publishing)

        # Seed default poll if none exists (throttled the same way)
        cached("portal.poll_seed_tick", 300.0, portal_repo.seed_default_poll)

        # Track impression on header ad
        active_header = ad_repo.get_active_ad_by_slot("header_top")
        if active_header:
            ad_repo.record_impression(active_header.id)

        lead_hero = article_repo.get_lead_hero_article()
        exclude_id = lead_hero.id if lead_hero else None

        breaking_news = article_repo.get_breaking_news(limit=6)
        highlighted = article_repo.get_highlighted_articles(limit=8, exclude_id=exclude_id)
        trending = article_repo.get_trending_articles(limit=5)
        active_poll = portal_repo.get_active_poll()

        # Category Blocks — fetched with a SINGLE query instead of one per block.
        category_blocks = article_repo.get_articles_by_categories(
            [
                "bangladesh",
                "politics",
                "international",
                "business",
                "technology",
                "sports",
                "entertainment",
            ],
            limit_per_category=4,
            exclude_id=exclude_id,
        )
        national_news = category_blocks["bangladesh"]
        politics_news = category_blocks["politics"]
        international_news = category_blocks["international"]
        business_news = category_blocks["business"]
        tech_news = category_blocks["technology"]
        sports_news = category_blocks["sports"]
        entertainment_news = category_blocks["entertainment"]
        # Multimedia slot reuses the top of the highlight list: one query instead
        # of two identical ORDER BY ... LIMIT scans (identical rows, same ordering).
        multimedia_news = highlighted[:4]

        # Live infinite-scroll stream (date-time wise, newest first).
        # Fetching limit+1 rows replaces the previous full-table COUNT(*)
        # (a non-sargable scan that cost ~15 ms per homepage hit).
        feed_query = apply_public_content_filter(
            session.query(Article)
            .options(joinedload(Article.images))
            .filter(Article.scrape_status == "completed")
        )
        feed_limit = 12
        feed_rows = (
            feed_query.order_by(Article.published_at.desc(), Article.id.desc())
            .limit(feed_limit + 1)
            .all()
        )
        feed_has_more = len(feed_rows) > feed_limit
        feed_items = feed_rows[:feed_limit]
        # "Latest news" is simply the head of the same newest-first stream
        # (identical ordering & filters), so it needs no query of its own.
        latest_news = feed_items[:6]
        feed_newest = (
            feed_items[0].published_at.strftime("%Y-%m-%d %H:%M:%S")
            if feed_items and feed_items[0].published_at
            else None
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
            feed_items=feed_items,
            feed_has_more=feed_has_more,
            feed_newest=feed_newest,
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


@portal_bp.route("/api/feed")
def feed_stream_api():
    """JSON feed for the live infinite-scroll news stream.

    Modes:
      - default:      next page of articles strictly older than ?before=cursor (date-time wise, newest first)
      - ?since=...:   brand-new articles published after that timestamp (for live prepend)
    Returns rendered HTML fragments so the portal keeps a single card markup source.
    """
    since = request.args.get("since", "").strip()
    before = request.args.get("before", "").strip()
    before_id = request.args.get("before_id", type=int)
    category = request.args.get("category", "").strip()
    limit = min(50, max(1, request.args.get("limit", 12, type=int)))

    def parse_dt(raw):
        raw = raw.replace("T", " ")[:19]
        try:
            return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    with get_db_session() as session:
        query = apply_public_content_filter(
            session.query(Article)
            .options(joinedload(Article.images))
            .filter(Article.scrape_status == "completed")
        )
        if category:
            query = query.filter(Article.category == category)

        if since:
            since_dt = parse_dt(since)
            items = (
                query.filter(Article.published_at > since_dt)
                .order_by(Article.published_at.desc(), Article.id.desc())
                .limit(limit)
                .all()
                if since_dt
                else []
            )
            has_more = False
        else:
            if before:
                before_dt = parse_dt(before)
                if before_dt:
                    query = query.filter(
                        (Article.published_at < before_dt)
                        | (
                            (Article.published_at == before_dt)
                            & (Article.id < (before_id or 0))
                        )
                    )
            # Fetch one extra row instead of running a COUNT(*) over the
            # non-sargable public-content filter (~15 ms on 1.9k articles).
            rows = (
                query.order_by(Article.published_at.desc(), Article.id.desc())
                .limit(limit + 1)
                .all()
            )
            has_more = len(rows) > limit
            items = rows[:limit]

        newest = None
        if items and items[0].published_at:
            newest = items[0].published_at.strftime("%Y-%m-%d %H:%M:%S")

        return jsonify(
            {
                "items": [
                    {
                        "id": art.id,
                        "html": render_template("partials/feed_item.html", art=art),
                    }
                    for art in items
                ],
                "count": len(items),
                "has_more": has_more,
                "newest": newest,
            }
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
    """Render full professional article reader view (legacy /news/<id> permalink)."""
    return _render_article_view(article_id)


@portal_bp.route("/<string:post_slug>")
def post_view(post_slug: str):
    """SEO friendly public permalink, e.g. /news/1602-dhaka-fire-incident."""
    with get_db_session() as session:
        article = ArticleRepository(session).get_by_slug(post_slug)
        if not article or not is_public_article(article):
            abort(404)
        article_id = article.id
    return _render_article_view(article_id)


def _render_article_view(article_id: int):
    """Shared article reader renderer (used by both permalink styles)."""
    with get_db_session() as session:
        article_repo = ArticleRepository(session)
        portal_repo = PortalRepository(session)
        ad_repo = AdvertisementRepository(session)

        # Track impression on mid article ad
        mid_ad = ad_repo.get_active_ad_by_slot("article_mid")
        if mid_ad:
            ad_repo.record_impression(mid_ad.id)

        # Increment view count
        article = article_repo.get_by_id(article_id)

        if not article:
            flash("নিবন্ধটি পাওয়া যায়নি বা মুছে ফেলা হয়েছে।", "warning")
            return redirect(url_for("portal.index_view"))

        # System-encrypted / placeholder rows must never be readable publicly
        if not is_public_article(article):
            flash("এই নিবন্ধটি আর পাবলিকভাবে উপলব্ধ নয়। / This article is no longer publicly available.", "warning")
            return redirect(url_for("portal.index_view"))

        # SEO permalink backfill for rows created before slugs existed
        article_repo.ensure_slug(article)

        article_repo.increment_views(article_id)

        related = article_repo.get_related_articles(article_id, category=article.category, limit=3)
        breaking_news = article_repo.get_breaking_news(limit=5)
        active_poll = portal_repo.get_active_poll()

        # Cryptographic Blockchain Verification Details
        # (pass the already-loaded article to skip a duplicate SELECT; the repo
        # only persists the verdict when it changes)
        ledger_repo = BlockchainLedgerRepository(session)
        is_valid, msg, ledger_info = ledger_repo.verify_article_ledger(article_id, article=article)

        return render_template(
            "portal_article.html",
            article=article,
            related_articles=related,
            breaking_news=breaking_news,
            active_poll=active_poll.to_dict() if active_poll else None,
            ledger_info=ledger_info,
            is_ledger_verified=is_valid,
            canonical_url=url_for("portal.post_view", post_slug=article.slug, _external=True),
            meta_description=build_meta_description(article.summary, article.content_text),
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


@portal_bp.route("/<int:article_id>/comment", methods=["POST"])
@login_required
def add_comment_view(article_id: int):
    """Post a reader comment — only registered, signed-in users may comment."""
    body = (request.form.get("body") or "").strip()
    user = get_current_user()

    if not body:
        flash("মন্তব্য খালি রাখা যাবে না / Comment cannot be empty.", "warning")
    elif len(body) > 2000:
        flash("মন্তব্য ২০০০ অক্ষরের বেশি হতে পারবে না / Comment is limited to 2000 characters.", "warning")
    else:
        with get_db_session() as session:
            repo = ArticleRepository(session)
            article = repo.get_by_id(article_id)
            if not article or not is_public_article(article):
                abort(404)
            repo.add_comment(
                article_id=article_id,
                user_id=getattr(user, "id", None),
                author_name=getattr(user, "username", None) or "পাঠক",
                body=body,
            )
        flash("আপনার মন্তব্য প্রকাশিত হয়েছে / Your comment has been published.", "success")

    return redirect(url_for("portal.article_reader_view", article_id=article_id) + "#comments")


@portal_bp.route("/comment/<int:comment_id>/delete", methods=["POST"])
@login_required
def delete_comment_view(comment_id: int):
    """Delete a comment (own comment, or any comment for editors/admins)."""
    user = get_current_user()
    force = bool(user and getattr(user, "role", "") in ("admin", "editor"))
    with get_db_session() as session:
        repo = ArticleRepository(session)
        comment = repo.session.query(ArticleComment).filter_by(id=comment_id).first()
        article_id = comment.article_id if comment else None
        ok = repo.delete_comment(comment_id, user_id=getattr(user, "id", None), force=force)
    if not ok:
        flash("মন্তব্যটি মুছে ফেলা যায়নি / Comment could not be deleted.", "warning")
    else:
        flash("মন্তব্য মুছে ফেলা হয়েছে / Comment deleted.", "success")
    if article_id:
        return redirect(url_for("portal.article_reader_view", article_id=article_id) + "#comments")
    return redirect(url_for("portal.index_view"))


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


