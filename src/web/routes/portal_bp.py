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
from src.common.seo import build_meta_description, parse_post_slug, embeddable_video_url
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


def get_special_edition(requested_edition: str = "") -> dict | None:
    """Detect or activate commemorative special day editions:
    - victory_day: মহান বিজয় দিবস (১৬ ডিসেম্বর)
    - independence_day: মহান স্বাধীনতা দিবস (২৬ মার্চ)
    - language_day: আন্তর্জাতিক মাতৃভাষা দিবস (২১ ফেব্রুয়ারি)
    - historical: বিশ্ব ঐতিহাসিক দিবস
    """
    edition_key = (requested_edition or "").strip().lower()
    now = datetime.now()
    if not edition_key:
        if now.month == 12 and now.day == 16:
            edition_key = "victory_day"
        elif now.month == 3 and now.day == 26:
            edition_key = "independence_day"
        elif now.month == 2 and now.day == 21:
            edition_key = "language_day"

    editions = {
        "victory_day": {
            "key": "victory_day",
            "name": "বিজয় দিবস",
            "title": "মহান বিজয় দিবস বিশেষ ডিজিটাল সংস্করণ",
            "date_bn": "১৬ ডিসেম্বর — মহান বিজয় দিবস",
            "badge": "🔴🟢 বিশেষ বিজয় দিবস সংখ্যা",
            "motto": "এক সাগর রক্তের বিনিময়ে বাংলার স্বাধীনতা আনলে যারা, আমরা তোমাদের ভুলব না",
            "theme_class": "edition-victory-day",
            "tribute_heading": "১৬ ডিসেম্বর: রক্তস্নাত ঐতিহাসিক বিজয়ের অমর গৌরবগাঁথা",
            "historic_tribute": "১৯৭১ সালের ১৬ ডিসেম্বর রেসকোর্স ময়দানে পাকিস্তানি হানাদার বাহিনীর ৯৩ হাজার সেনার নিঃশর্ত আত্মসমর্পণের মধ্য দিয়ে অর্জিত হয় বীর বাঙালির বহুকাঙ্ক্ষিত ঐতিহাসিক বিজয়। আজকের এই গৌরবময় দিনে জাতির শ্রেষ্ঠ সন্তান সকল বীর মুক্তিযোদ্ধা ও শহীদদের প্রতি জানাই গভীর বিনম্র শ্রদ্ধাঞ্জলি।",
            "timeline": [
                {"time": "১৬ ডিসেম্বর ১৯৭১, বিকাল ৪:৩১", "title": "আত্মসমর্পণ দলিল স্বাক্ষর", "desc": "রেসকোর্স ময়দানে পাকিস্তানি লেফটেন্যান্ট জেনারেল নিয়াজীর ঐতিহাসিক আত্মসমর্পণ দলিলে স্বাক্ষর।"},
                {"time": "১০:০০ পূর্বাহ্ন", "title": "স্বাধীনতার জয়ধ্বনি", "desc": "মুক্ত রাজধানী ঢাকায় লক্ষ কোটি মুক্তিকামী জনতার জয় বাংলা স্লোগানে মুখরিত রাজপথ।"},
                {"time": "আন্তর্জাতিক স্বীকৃতি", "title": "নতুন রাষ্ট্রের অভ্যুদয়", "desc": "বিশ্বের বুকে মাথা উঁচু করে দাঁড়াল রক্তস্নাত স্বাধীন সার্বভৌম বাংলাদেশ।"},
            ],
        },
        "independence_day": {
            "key": "independence_day",
            "name": "স্বাধীনতা দিবস",
            "title": "মহান স্বাধীনতা ও জাতীয় দিবস বিশেষ সংস্করণ",
            "date_bn": "২৬ মার্চ — মহান স্বাধীনতা দিবস",
            "badge": "🔴🟢 স্বাধীনতা দিবস বিশেষ আয়োজন",
            "motto": "রক্তে ভেজা এই বাংলায় মুক্তিকামী জনতার চিরভাস্বর অহংকার",
            "theme_class": "edition-independence-day",
            "tribute_heading": "২৬ মার্চ: মুক্তির অবিনাশী প্রত্যয় ও স্বাধীনতার মহান ঘোষণা",
            "historic_tribute": "১৯৭১ সালের ২৬ মার্চের প্রথম প্রহরে সর্বকালের সর্বশ্রেষ্ঠ বাঙালি জাতির পিতা বঙ্গবন্ধু শেখ মুজিবুর রহমানের স্বাধীনতার ঐতিহাসিক ঘোষণার মধ্য দিয়ে সূচিত হয় বীরত্বপূর্ণ মুক্তিযুদ্ধ। রক্তক্ষয়ী নয় মাসের সংগ্রামের সূচনালগ্নে সকল অমর শহীদদের প্রতি বিনম্র শ্রদ্ধা।",
            "timeline": [
                {"time": "২৬ মার্চ ১৯৭১, প্রথম প্রহর", "title": "স্বাধীনতার ঘোষণা", "desc": "ওয়্যারলেস ও বেতার মাধ্যমে প্রচারিত হয় বাংলার অবিসংবাদিত স্বাধীনতার বার্তা।"},
                {"time": "২৫ মার্চ কালরাত", "title": "অপারেশন সার্চলাইট", "desc": "পাক হানাদারদের বর্বরোচিত হত্যাযজ্ঞের বিরুদ্ধে দুর্বার প্রতিরোধ গড়ে তোলে বাঙালি।"},
                {"time": "মুক্তিসংগ্রামের সূচনা", "title": "জনযুদ্ধের সূচনা", "desc": "পদ্মা-মেঘনা-যমুনার তীরে তীরে গর্জে ওঠে মুক্তিসেনাদের মরণপণ প্রতিরোধ।"},
            ],
        },
        "language_day": {
            "key": "language_day",
            "name": "মাতৃভাষা দিবস",
            "title": "মহান একুশে ফেব্রুয়ারি ও আন্তর্জাতিক মাতৃভাষা দিবস",
            "date_bn": "২১ ফেব্রুয়ারি — অমর একুশে",
            "badge": "⚫ অমর একুশে বিশেষ সংস্করণ",
            "motto": "আমার ভাইয়ের রক্তে রাঙানো একুশে ফেব্রুয়ারি, আমি কি ভুলিতে পারি",
            "theme_class": "edition-language-day",
            "tribute_heading": "২১ ফেব্রুয়ারি: ভাষার জন্য আত্মদানের বিশ্বস্বীকৃত অমর ইতিহাস",
            "historic_tribute": "১৯৫২ সালের এই দিনে মাতৃভাষা বাংলার মর্যাদা রক্ষার দাবিতে রাজপথে বুকের তাজা রক্ত ঢেলে দিয়েছিলেন সালাম, বরকত, রফিক, জব্বারসহ নাম না জানা বীর শহীদরা। তাদের আত্মত্যাগের বিনিময়ে আজ বাংলা ভাষা ও একুশে ফেব্রুয়ারি বিশ্বজুড়ে আন্তর্জাতিক মাতৃভাষা দিবস হিসেবে স্বীকৃত।",
            "timeline": [
                {"time": "২১ ফেব্রুয়ারি ১৯৫২", "title": "আমতলায় ১৪৪ ধারা ভঙ্গ", "desc": "ঢাকা বিশ্ববিদ্যালয় প্রাঙ্গণে ঐতিহাসিক ছাত্র সমাবেশ ও পুলিশের গুলিবর্ষণ।"},
                {"time": "২৩ ফেব্রুয়ারি ১৯৫২", "title": "প্রথম শহীদ মিনার", "desc": "শহীদদের পবিত্র রক্তস্মৃতিতে মেডিকেল কলেজ হোস্টেলে গড়ে ওঠে প্রথম স্মৃতির মিনার।"},
                {"time": "১৭ নভেম্বর ১৯৯৯", "title": "ইউনেস্কোর স্বীকৃতি", "desc": "একুশে ফেব্রুয়ারিকে বিশ্ব মাতৃভাষা দিবস হিসেবে সর্বসম্মত স্বীকৃতি দান।"},
            ],
        },
        "historical": {
            "key": "historical",
            "name": "ঐতিহাসিক দিবস",
            "title": "বিশ্ব ঐতিহাসিক দিবস বিশেষ আর্কাইভ সংস্করণ",
            "date_bn": "ইতিহাসের পাতায় আজকের দিন",
            "badge": "🏛️ বিশ্ব ইতিহাস ও ঐতিহ্য",
            "motto": "ইতিহাসের আলোয় বর্তমানের দিকদর্শন ও ভবিষ্যতের পথচলা",
            "theme_class": "edition-historical",
            "tribute_heading": "ইতিহাসের মোড় ঘোরানো স্মরণীয় দিন ও সভ্যতার রূপান্তর",
            "historic_tribute": "মানব সভ্যতার অগ্রগতি, বিশ্ব বিপ্লব এবং জাতিসমূহের আত্মনিয়ন্ত্রণাধিকারের ঐতিহাসিক সন্ধিক্ষণগুলোকে শ্রদ্ধার সাথে স্মরণ করে আজকের এই বিশেষ ঐতিহাসিক সংখ্যা।",
            "timeline": [
                {"time": "ঐতিহাসিক অধ্যায়", "title": "জ্ঞান ও মুক্তির জাগরণ", "desc": "শিল্পবিপ্লব ও গণতান্ত্রিক আন্দোলনের সোনালী দিনপঞ্জি।"},
                {"time": "বিশ্বশান্তির অঙ্গীকার", "title": "আন্তর্জাতিক ন্যায়বিচার", "desc": "জাতিসংঘ সনদ ও মানবাধিকারের সর্বজনীন ঘোষণার রূপরেখা।"},
            ],
        },
    }
    return editions.get(edition_key)


@portal_bp.route("", endpoint="newspaper_home")
@portal_bp.route("")
@portal_bp.route("/")
def index_view():
    """Render public digital newspaper homepage."""
    category_filter = request.args.get("category", "").strip()
    search_query = request.args.get("q", "").strip()
    edition_param = request.args.get("edition", "").strip() or request.args.get("special", "").strip()
    special_edition = get_special_edition(edition_param)

    with get_db_session() as session:
        article_repo = ArticleRepository(session)
        portal_repo = PortalRepository(session)
        ad_repo = AdvertisementRepository(session)

        # Process any pending scheduled releases — the background scheduler runs
        # this every 60 s anyway, so the homepage only triggers it at most once
        # per 30 s per process instead of on every single hit.
        cached("portal.scheduled_publish_tick", 30.0, article_repo.process_scheduled_publishing)

        # Demo polls are never seeded automatically; admins create them explicitly.

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
        
        # Dedicated video news items for responsive iframe video theatre
        video_news = article_repo.get_video_articles(limit=6)
        multimedia_news = highlighted[:4]

        # "সর্বশেষ সংবাদ" — a fixed server-rendered list of the newest stories.
        # The page never fetches more after it renders (no infinite scroll).
        feed_query = apply_public_content_filter(
            session.query(Article)
            .options(joinedload(Article.images))
            .filter(Article.scrape_status == "completed")
        )
        feed_limit = 24
        feed_items = (
            feed_query.order_by(Article.published_at.desc(), Article.id.desc())
            .limit(feed_limit)
            .all()
        )
        # "Latest news" is simply the head of the same newest-first stream
        # (identical ordering & filters), so it needs no query of its own.
        latest_news = feed_items[:6]

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
            active_poll=active_poll.to_dict() if active_poll else None,
            national_news=national_news,
            politics_news=politics_news,
            international_news=international_news,
            business_news=business_news,
            tech_news=tech_news,
            sports_news=sports_news,
            entertainment_news=entertainment_news,
            multimedia_news=multimedia_news,
            video_news=video_news,
            special_edition=special_edition,
            category_filter=category_filter,
            search_query=search_query,
            filter_results=filter_results,
            embeddable_video_url=embeddable_video_url,
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


@portal_bp.route("/api/bulletins")
def bulletins_api():
    """Realtime endpoint returning breaking updates, notices, and system alerts for the live notification bell."""
    with get_db_session() as session:
        article_repo = ArticleRepository(session)
        breaking = article_repo.get_breaking_news(limit=6)
        breaking_list = [
            {
                "id": b.id,
                "title": b.title,
                "category": b.category or "ব্রেকিং",
                "url": post_url(b),
                "time": b.published_at.strftime("%I:%M %p") if b.published_at else "এখনই",
                "views": b.views_count or 0,
            }
            for b in breaking
        ]

        notices = [
            {
                "id": "notice-1",
                "title": "দি ডেইলি এআই আলো: রিয়েল-টাইম বাংলা এআই নিউজ পোর্টাল আপডেট সক্রিয়",
                "type": "official",
                "tag": "বিজ্ঞপ্তি",
                "date": datetime.now().strftime("%d %b %Y"),
                "summary": "আমাদের সংবাদ সিস্টেমে স্বয়ংক্রিয় এআই সত্যতা যাচাইকরণ ও তাৎক্ষণিক লাইভ ফিড চালু রয়েছে।",
            },
            {
                "id": "notice-2",
                "title": "মতামত ও সম্পাদকীয় বিভাগে নতুন কলাম প্রকাশের আমন্ত্রণ",
                "type": "editorial",
                "tag": "সম্পাদকীয়",
                "date": datetime.now().strftime("%d %b %Y"),
                "summary": "অর্থনীতি, সমাজ ও প্রযুক্তির সমসাময়িক বিষয়ে উপ-সম্পাদকীয় কলাম পাঠাতে সম্পাদক বরাবর ইমেইল করুন।",
            },
            {
                "id": "notice-3",
                "title": "লাইভ আবহাওয়া ও ডলার/ইউরো বিনিময় হার পর্যবেক্ষণ ব্যবস্থা সক্রিয়",
                "type": "system",
                "tag": "অর্থনীতি",
                "date": datetime.now().strftime("%d %b %Y"),
                "summary": "বাংলাদেশ ব্যাংক ও আন্তর্জাতিক উৎস থেকে সংগৃহীত সরাসরি আর্থিক সূচক প্রদর্শিত হচ্ছে।",
            },
        ]

        return jsonify({
            "status": "success",
            "breaking": breaking_list,
            "notices": notices,
            "total_alerts": len(breaking_list) + len(notices),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })


@portal_bp.route("/opinion")
@portal_bp.route("/editorial")
def opinion_view():
    """Dedicated Editorial, Sub-Editorial, and In-Depth Opinion Page."""
    tab = request.args.get("tab", "all").strip().lower()
    with get_db_session() as session:
        article_repo = ArticleRepository(session)
        portal_repo = PortalRepository(session)

        breaking_news = article_repo.get_breaking_news(limit=5)
        active_poll = portal_repo.get_active_poll()

        # Fetch articles in opinion/editorial categories
        opinion_articles = article_repo.get_articles_by_category("opinion", limit=24)
        if not opinion_articles:
            # Fallback to high-quality completed articles for rich presentation
            opinion_articles = article_repo.get_highlighted_articles(limit=16)

        # Distribute into Chief Editorial, Sub-Editorial/Deputy, and Guest Columnists
        lead_editorial = opinion_articles[0] if opinion_articles else None
        sub_editorials = opinion_articles[1:5] if len(opinion_articles) > 1 else []
        columnist_pieces = opinion_articles[5:13] if len(opinion_articles) > 5 else opinion_articles[:8]

        # Distinguished Editorial Board & Deputy Columnists Profiles
        columnists_profiles = [
            {
                "name": "মাহবুবুল হক সৈকত",
                "designation": "প্রধান সম্পাদক ও প্রধান কলামিস্ট",
                "department": "সম্পাদকীয় বোর্ড",
                "avatar": "/static/img/placeholders/opinion.svg",
                "focus": "রাষ্ট্রনীতি, গণতন্ত্র ও সাংবিধানিক সংস্কার",
                "quote": "সত্যের নির্ভীক প্রকাশই একটি মুক্ত সমাজের প্রধান রক্ষাকবচ।",
                "articles_count": 48,
            },
            {
                "name": "ড. আতিকুর রহমান",
                "designation": "ডেপুটি এডিটর (উপ-সম্পাদকীয়)",
                "department": "উপ-সম্পাদকীয় ও বিশ্লেষণ বিভাগ",
                "avatar": "/static/img/placeholders/business.svg",
                "focus": "সামষ্টিক অর্থনীতি, মুদ্রা নীতি ও বাণিজ্য",
                "quote": "অর্থনৈতিক ভারসাম্য ছাড়া সামাজিক ন্যায়বিচার প্রতিষ্ঠা অসম্ভব।",
                "articles_count": 34,
            },
            {
                "name": "মাহরীন সুলতানা",
                "designation": "সহকারী সম্পাদক ও নীতি বিশ্লেষক",
                "department": "শিক্ষা ও প্রযুক্তি বিভাগ",
                "avatar": "/static/img/placeholders/technology.svg",
                "focus": "কৃত্রিম বুদ্ধিমত্তা, যুবশক্তি ও রূপান্তর",
                "quote": "প্রযুক্তির সুফল সাধারণের দোরগোড়ায় পৌঁছালেই রূপান্তর সার্থক।",
                "articles_count": 29,
            },
            {
                "name": "অধ্যাপক জামিল চৌধুরী",
                "designation": "বিশেষ অতিথি কলামিস্ট",
                "department": "আন্তর্জাতিক সম্পর্ক বিভাগ",
                "avatar": "/static/img/placeholders/international.svg",
                "focus": "ভূ-রাজনীতি, দক্ষিণ এশিয়া ও কূটনীতি",
                "quote": "কূটনৈতিক দূরদর্শিতাই বৈশ্বিক সংকটে সার্বভৌমত্বের মূল চাবিকাঠি।",
                "articles_count": 22,
            },
        ]

        return render_template(
            "portal_editorial.html",
            lead_editorial=lead_editorial,
            sub_editorials=sub_editorials,
            columnist_pieces=columnist_pieces,
            columnists_profiles=columnists_profiles,
            breaking_news=breaking_news,
            active_poll=active_poll.to_dict() if active_poll else None,
            current_tab=tab,
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


