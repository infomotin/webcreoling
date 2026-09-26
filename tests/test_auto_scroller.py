"""
Test Suite for the Auto Scroller pipeline:
scrape -> raw store -> classify -> 98% similarity mining -> Bangla translation ->
copyright-safe regeneration -> AI Brain gate -> auto/manual portal publishing
(with original source link preserved).
"""

import re
import uuid

import pytest

from src.automation.auto_scroller import AutoScroller
from src.automation.scheduler import get_scheduler
from src.nlp.news_synthesizer import AINewsSynthesizerAndParaphraser
from src.storage.database import init_db, get_db_session
from src.storage.models import Article, RawNewsItem
from src.storage.repositories import ArticleRepository, SiteConfigRepository, UserRepository
from src.web.app import create_app


def _nonce() -> str:
    return uuid.uuid4().hex[:10]


def _clean_bn_news(nonce: str) -> str:
    return (
        f"রাজধানী ঢাকার কেন্দ্রীয় জাতীয় সংসদ ভবনে আজ সকালে একটি বিশেষ অনুষ্ঠানের আয়োজন করা হয়েছে [{nonce}]। "
        "সংশ্লিষ্ট সূত্র জানিয়েছেন, অনুষ্ঠানে দেশের বিভিন্ন জেলা থেকে প্রতিনিদের উপস্থিত ছিলেন। "
        "আমলারা জানান, নতুন পরিকল্পনা বাস্তবায়নে প্রয়োজনীয় অর্থায়নের কথা নিশ্চিত করা হয়েছে। "
        "বিশেষজ্ঞরা বলেছেন, এই উদ্যোগ আগামী বছরের মধ্যে দেশের অর্থনৈতিক প্রবৃদ্ধিতে ইতিবাচক প্রভাব ফেলবে। "
        "প্রতিবেদনে উল্লেখ করা হয়েছে, দুই হাজার ছাব্বিশ সালের প্রথম প্রান্তিকে প্রাথমিক ফলাফল প্রকাশ করা হবে।"
    )


@pytest.fixture
def client():
    """Create test client with authenticated admin session."""
    init_db()
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with get_db_session() as session:
        user_repo = UserRepository(session)
        admin_user = user_repo.get_by_username("admin")
        if not admin_user:
            admin_user = user_repo.create_user("admin", "admin@webcreoling.ai", "admin123", role="admin")

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = admin_user.id
            sess["username"] = admin_user.username
            sess["role"] = "admin"
        yield client


def _cleanup(item_ids=None, article_ids=None):
    with get_db_session() as session:
        for aid in article_ids or []:
            art = session.query(Article).filter(Article.id == aid).first()
            if art:
                session.delete(art)
        for iid in item_ids or []:
            item = session.query(RawNewsItem).filter(RawNewsItem.id == iid).first()
            if item:
                session.delete(item)
        session.commit()


@pytest.fixture(scope="module", autouse=True)
def purge_test_news_data():
    """Remove Auto Scroller test artifacts from prior runs so dedup never trips across runs."""

    def _purge():
        with get_db_session() as session:
            session.query(RawNewsItem).filter(
                RawNewsItem.source_url.like("https://news.example.test/%")
            ).delete(synchronize_session=False)
            session.query(Article).filter(
                Article.original_source_url.like("https://news.example.test/%")
            ).delete(synchronize_session=False)
            session.commit()

    _purge()
    yield
    _purge()


# ==============================================================================
# 1. Similarity Mining (98% Duplicate Detection)
# ==============================================================================

def test_text_similarity_identity_and_difference():
    text = "বাংলাদেশে নতুন রেলপথ উদ্বোধন করা হয়েছে আজ"
    assert AutoScroller.text_similarity(text, text) == 1.0
    assert AutoScroller.text_similarity(text, "") == 0.0
    diff = AutoScroller.text_similarity(text, "ইউরোপে ফুটবল চ্যাম্পিয়নশিপ শেষ হয়েছে গতকাল")
    assert diff < 0.98  # far below the duplicate-mining threshold


def test_ingest_classifies_and_queues_until_manual_publish():
    """Auto-post OFF: item goes through classify -> mine -> rewrite -> AI gate and waits in queue."""
    nonce = _nonce()
    url = f"https://news.example.test/{nonce}/parliament-event"
    res = AutoScroller.ingest_raw_item(
        source_url=url,
        title=f"সংসদ ভবনে বিশেষ অনুষ্ঠানের আয়োজন {nonce}",
        content=_clean_bn_news(nonce),
        source_name="Test Wire",
        category="bangladesh",
    )
    assert res["success"] is True
    assert res["status"] == "queued"
    assert res["ai_decision"] in ("AUTO_PUBLISH", "QUEUE_FOR_REVIEW")

    with get_db_session() as session:
        item = session.query(RawNewsItem).filter(RawNewsItem.id == res["item_id"]).first()
        assert item is not None
        assert item.status == "queued"
        assert item.category in ("bangladesh", "politics", "business")  # auto-classified
        assert item.regenerated_title and item.regenerated_body
        assert item.regenerated_summary
        assert item.meaning_retention_score and item.meaning_retention_score >= 95.0

        # Copyright-safe: no source sentence may appear verbatim in the rewrite
        src_sentences = [s.strip() for s in re.split(r"(?<=[।!?])\s+", _clean_bn_news(nonce)) if s.strip()]
        for s in src_sentences:
            assert s not in item.regenerated_body

        _cleanup(item_ids=[res["item_id"]])


def test_exact_source_url_deduplicated():
    nonce = _nonce()
    url = f"https://news.example.test/{nonce}/same-url-story"
    first = AutoScroller.ingest_raw_item(
        source_url=url, title=f"শিক্ষা কমিশনের নতুন নির্দেশনা {nonce}",
        content=_clean_bn_news(nonce), source_name="Test Wire",
    )
    second = AutoScroller.ingest_raw_item(source_url=url, title="ignored", content="ignored")
    assert first["success"] and second["success"]
    assert second.get("skipped") == "duplicate_url"
    assert second["item_id"] == first["item_id"]
    _cleanup(item_ids=[first["item_id"]])


def test_98_percent_similarity_mining_marks_duplicate():
    """Same story from a different URL must be flagged as duplicate at >= 98% similarity."""
    nonce = _nonce()
    content = _clean_bn_news(nonce)
    url_a = f"https://news.example.test/{nonce}/story-a"
    url_b = f"https://news.example.test/{nonce}/story-b"
    a = AutoScroller.ingest_raw_item(
        source_url=url_a, title=f"অর্থনৈতিক প্রবৃদ্ধির নতুন সম্ভাবনা {nonce}", content=content, source_name="Wire A",
    )
    assert a["status"] in ("queued", "auto_published", "rejected")
    b = AutoScroller.ingest_raw_item(
        source_url=url_b, title=f"অর্থনৈতিক প্রবৃদ্ধির নতুন সম্ভাবনা {nonce}", content=content, source_name="Wire B",
    )
    assert b["status"] == "duplicate"
    assert b["similarity_score"] >= 0.98
    assert b["duplicate_of_url"] == url_a
    _cleanup(item_ids=[a["item_id"], b["item_id"]])


# ==============================================================================
# 2. Copyright-Safe Regeneration (95-98% meaning retention)
# ==============================================================================

def test_force_rewrite_is_copyright_safe_and_keeps_meaning():
    raw_content = (
        "জাতীয় জাদুঘরে আজ নতুন প্রদর্শনীর উদ্বোধন করা হয়েছে।\n"
        "সংস্কৃতি মন্ত্রণালয়ের পক্ষ থেকে জানানো হয়েছে, প্রদর্শনীতে দেশের পঁয়তাল্লিশটি জেলার ঐতিহ্যবাহী নিদর্শন রাখা হয়েছে।\n"
        "দর্শনার্থীরা সকাল ন’টা থেকে রাত আটটা পর্যন্ত প্রবেশ করতে পারবেন বলে জানিয়েছে কর্তৃপক্ষ।\n"
        "বিশেষজ্ঞরা মনে করেন, এই উদ্যোগ দেশের পর্যটন খাতকে নতুন মাত্রা দেবে আগামী বছরে।"
    )
    report = AINewsSynthesizerAndParaphraser.process_and_synthesize_news(
        raw_title="জাতীয় জাদুঘরে নতুন প্রদর্শনীর উদ্বোধন",
        raw_content=raw_content,
        source_name="Test Desk",
        force_rewrite=True,
    )
    body = report["synthesized_body"]
    assert body
    assert report["meaning_retention_score"] >= 95.0

    # No verbatim source sentence may survive the rewrite
    src_sentences = [s.strip() for s in raw_content.split("\n") if s.strip()]
    for s in src_sentences:
        assert s not in body

    # Source attribution line must be present
    assert "প্রতিবেদন তৈরিতে" in body


# ==============================================================================
# 3. Auto-Post Publishing with Original Source Link
# ==============================================================================

def test_auto_post_publishes_with_original_source_link():
    nonce = _nonce()
    url = f"https://news.example.test/{nonce}/auto-post-story"
    with get_db_session() as session:
        AutoScroller.save_config(session, {"auto_post_enabled": True, "source_urls": ""})
        session.commit()

    try:
        res = AutoScroller.ingest_raw_item(
            source_url=url,
            title=f"কৃষি খাতে নতুন প্রযুক্তি প্রবেশ করছে {nonce}",
            content=_clean_bn_news(nonce),
            source_name="Agri Wire",
            category="bangladesh",
        )
        assert res["success"] is True
        if res["status"] == "auto_published":
            assert res["article_id"]
            with get_db_session() as session:
                art = session.query(Article).filter(Article.id == res["article_id"]).first()
                assert art is not None
                assert art.original_source_url == url
                assert url in art.content_text  # in-body source credit
                assert art.creation_origin == "AI_SYNTHESIZED"
                assert art.scrape_status == "completed"
                art_id = art.id
            _cleanup(item_ids=[res["item_id"]], article_ids=[art_id])
        else:
            # AI Brain withheld auto-publish: item must wait in the queue instead
            assert res["status"] == "queued"
            _cleanup(item_ids=[res["item_id"]])
    finally:
        with get_db_session() as session:
            AutoScroller.save_config(session, {"auto_post_enabled": False})
            session.commit()


def test_process_waiting_queue_respects_auto_post_flag():
    """With auto-post OFF the queue is never released automatically."""
    result = AutoScroller.process_waiting_queue()
    assert result["published"] == 0
    assert "note" in result  # explains that items wait for manual publish


def test_manual_publish_and_reject_routes(client):
    nonce = _nonce()
    url = f"https://news.example.test/{nonce}/manual-publish-story"
    res = AutoScroller.ingest_raw_item(
        source_url=url,
        title=f"স্বাস্থ্য খাতে নতুন পদক্ষেপ {nonce}",
        content=_clean_bn_news(nonce),
        source_name="Health Wire",
    )
    assert res["status"] == "queued"
    item_id = res["item_id"]

    try:
        resp = client.post(f"/scraper/scroller/publish/{item_id}", follow_redirects=True)
        assert resp.status_code == 200

        with get_db_session() as session:
            item = session.query(RawNewsItem).filter(RawNewsItem.id == item_id).first()
            assert item.status == "published_manual"
            assert item.article_id
            art = session.query(Article).filter(Article.id == item.article_id).first()
            assert art is not None
            assert art.original_source_url == url
            art_id = art.id

        # Second item -> reject flow
        res2 = AutoScroller.ingest_raw_item(
            source_url=f"https://news.example.test/{nonce}/reject-story",
            title=f"বাতিলযোগ্য সংবাদ {nonce}",
            content=_clean_bn_news(nonce),
            source_name="Wire",
        )
        resp2 = client.post(f"/scraper/scroller/reject/{res2['item_id']}", follow_redirects=True)
        assert resp2.status_code == 200
        with get_db_session() as session:
            item2 = session.query(RawNewsItem).filter(RawNewsItem.id == res2["item_id"]).first()
            assert item2.status == "rejected"

        _cleanup(item_ids=[item_id, res2["item_id"]], article_ids=[art_id])
    except Exception:
        _cleanup(item_ids=[item_id], article_ids=[])
        raise


# ==============================================================================
# 4. Translation Stage (non-Bangla sources -> Bangla)
# ==============================================================================

def test_non_bangla_source_translated_to_bangla():
    nonce = _nonce()
    url = f"https://news.example.test/{nonce}/english-story"
    res = AutoScroller.ingest_raw_item(
        source_url=url,
        title=f"Global markets rally as central bank signals rate cut {nonce}",
        content=(
            "Global stock markets rallied on Monday after the central bank signaled an interest rate cut. "
            "Investors welcomed the move as a positive sign for economic growth. "
            f"Analysts said the policy decision could boost consumer spending {nonce}."
        ),
        source_name="World Wire",
    )
    assert res["success"] is True
    with get_db_session() as session:
        item = session.query(RawNewsItem).filter(RawNewsItem.id == res["item_id"]).first()
        assert item.needs_translation is True
        assert item.translated is True
        assert item.language == "en"
        _cleanup(item_ids=[res["item_id"]])


# ==============================================================================
# 5. Routes, Config & Scheduler Integration
# ==============================================================================

def test_scroller_config_and_run_cycle_routes(client):
    resp = client.post("/scraper/scroller/config", data={
        "source_urls": "https://news.example.test/a, https://news.example.test/b",
        "enabled": "1",
        "translate_to_bangla": "1",
        "similarity_threshold": "0.97",
        "ai_publish_threshold": "72",
        "max_items_per_cycle": "4",
        "category": "bangladesh",
    }, follow_redirects=True)
    assert resp.status_code == 200

    with get_db_session() as session:
        cfg = SiteConfigRepository(session).get_auto_scroller_config()
        assert cfg["similarity_threshold"] == 0.97
        assert cfg["ai_publish_threshold"] == 72.0
        assert cfg["max_items_per_cycle"] == 4
        assert "news.example.test/a" in cfg["source_urls"]
        # restore defaults so later runs are not network-bound
        AutoScroller.save_config(session, {
            "source_urls": "", "similarity_threshold": 0.98,
            "ai_publish_threshold": 75.0, "max_items_per_cycle": 10,
        })
        session.commit()

    # Run cycle with no configured sources -> safe no-op summary (no network)
    resp2 = client.post("/scraper/scroller/run", data={"source_urls": "", "max_items": "1"}, follow_redirects=True)
    assert resp2.status_code == 200

    api = client.get("/scraper/api/scroller/items")
    assert api.status_code == 200
    payload = api.get_json()
    assert payload["success"] is True
    assert "items" in payload and "stats" in payload


def test_scroller_dashboard_tab_renders(client):
    resp = client.get("/scraper?tab=scroller")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "tab-scroller" in html
    assert "/scraper/scroller/config" in html
    assert "/scraper/scroller/run" in html
    assert "অটো স্ক্রলার" in html


def test_scheduler_has_auto_scroller_job():
    scheduler = get_scheduler()
    assert "auto_scroller_cycle" in scheduler.jobs
    job = scheduler.jobs["auto_scroller_cycle"]
    assert job.job_type == "auto_scroller"
    assert job.enabled is True

    resolver = scheduler._resolve_target_func("auto_scroller", {"max_items": 2})
    assert callable(resolver)


def test_run_cycle_empty_config_is_noop():
    summary = AutoScroller.run_cycle(source_urls=[], max_items=3)
    assert summary["scraped"] == 0
    assert summary["failed"] == 0
    assert isinstance(summary["errors"], list)
