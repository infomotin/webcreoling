"""Regression tests: system-encrypted / locked placeholder articles must never surface publicly."""

import pytest
from datetime import datetime, timezone

from src.web.app import create_app
from src.storage.database import init_db, get_db_session
from src.storage.models import Article
from src.storage.repositories import (
    ArticleRepository,
    apply_public_content_filter,
    is_public_article,
    LOCKED_TITLE_MARKER,
)


MARKER = "SYSTEM ENCRYPTED DATA"


@pytest.fixture
def client():
    init_db()
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    with app.test_client() as client:
        yield client


def _login(client, username="admin", password="admin123"):
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


def _insert_raw_article(title, content_text="লক্ষ্যযোগ্য সংবাদের বিষয়বস্তু।", category="politics"):
    """Insert a raw row bypassing editorial normalisation so marker titles survive."""
    art = Article(
        url=f"https://daily-ai-alo.news/test/{abs(hash((title, content_text, datetime.now(timezone.utc)))) % 10**12}",
        original_source_url="https://daily-ai-alo.news/test",
        source="পরীক্ষা সূত্র",
        source_status="ACTIVE",
        creation_origin="MANUAL",
        position_placement="STANDARD",
        display_order=0,
        is_pinned=False,
        title=title,
        content_text=content_text,
        category=category,
        author="টেস্ট",
        scrape_status="completed",
        published_at=datetime.now(timezone.utc),
    )
    return art


def _cleanup(*ids):
    with get_db_session() as session:
        repo = ArticleRepository(session)
        for aid in ids:
            if aid:
                repo.delete_article(aid)


# ---------------------------------------------------------------------------
# 1. Repository-level filter
# ---------------------------------------------------------------------------
def test_public_content_filter_excludes_marker_rows():
    a_enc = _insert_raw_article(f"🔒 [SYSTEM ENCRYPTED DATA: 999] unknown")
    a_lock = _insert_raw_article(f"{LOCKED_TITLE_MARKER} এই সংবাদ লক করা হয়েছে")
    a_empty = _insert_raw_article("   ")
    a_ok = _insert_raw_article("নিয়মিত সংবাদ শিরোনাম")

    with get_db_session() as session:
        session.add(a_enc)
        session.add(a_lock)
        session.add(a_empty)
        session.add(a_ok)
        session.flush()
        enc_id, lock_id, empty_id, ok_id = a_enc.id, a_lock.id, a_empty.id, a_ok.id

        kept_ids = {r[0] for r in apply_public_content_filter(session.query(Article)).with_entities(Article.id).all()}
        assert enc_id not in kept_ids
        assert lock_id not in kept_ids
        assert empty_id not in kept_ids
        assert ok_id in kept_ids

        repo = ArticleRepository(session)
        assert is_public_article(session.get(Article, enc_id)) is False
        assert is_public_article(session.get(Article, lock_id)) is False
        assert is_public_article(session.get(Article, empty_id)) is False
        assert is_public_article(session.get(Article, ok_id)) is True

    _cleanup(enc_id, lock_id, empty_id, ok_id)


# ---------------------------------------------------------------------------
# 2. Ticker / breaking-news widget
# ---------------------------------------------------------------------------
def test_breaking_news_ticker_has_no_encrypted_posts():
    with get_db_session() as session:
        repo = ArticleRepository(session)
        items = repo.get_breaking_news(limit=10)
        titles = [a.title or "" for a in items]
        assert all(MARKER not in t for t in titles)
        assert all(not t.startswith(LOCKED_TITLE_MARKER) for t in titles)
        assert all(t.strip() for t in titles)


# ---------------------------------------------------------------------------
# 3. Public frontpage markup
# ---------------------------------------------------------------------------
def test_frontpage_contains_no_encrypted_marker(client):
    resp = client.get("/news")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert MARKER not in html
    assert "🔒 [SYSTEM" not in html


# ---------------------------------------------------------------------------
# 4. Live feed API fragments
# ---------------------------------------------------------------------------
def test_feed_api_never_returns_encrypted_fragments(client):
    resp = client.get("/news/api/feed?limit=50")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload is not None and "items" in payload
    body = resp.get_data(as_text=True)
    assert MARKER not in body
    for item in payload["items"]:
        assert item["id"] > 0
        assert item["html"].strip()


# ---------------------------------------------------------------------------
# 5. Article explorer (login-protected listing + search)
# ---------------------------------------------------------------------------
def test_article_list_and_search_hide_encrypted_posts(client):
    _login(client)

    listing = client.get("/articles")
    assert listing.status_code == 200
    html = listing.get_data(as_text=True)
    assert MARKER not in html

    search = client.get("/articles?q=SYSTEM")
    assert search.status_code == 200
    assert MARKER not in search.get_data(as_text=True)


# ---------------------------------------------------------------------------
# 6. Reader views for a marker row must refuse public access
# ---------------------------------------------------------------------------
def test_encrypted_article_reader_is_not_publicly_readable(client):
    art = _insert_raw_article(f"🔒 [SYSTEM ENCRYPTED DATA: 4242] placeholder", content_text="🔒 এই সংবাদের তথ্য সুরক্ষিত।")
    with get_db_session() as session:
        session.add(art)
        session.flush()
        art_id = art.id

    try:
        portal_resp = client.get(f"/news/{art_id}")
        assert portal_resp.status_code in (302, 404)
        assert MARKER not in portal_resp.get_data(as_text=True)

        _login(client)
        detail_resp = client.get(f"/articles/{art_id}")
        assert detail_resp.status_code == 404
    finally:
        _cleanup(art_id)


# ---------------------------------------------------------------------------
# 7. Search results coming back from the repository are clean
# ---------------------------------------------------------------------------
def test_repository_search_results_are_clean():
    with get_db_session() as session:
        repo = ArticleRepository(session)
        results = repo.search_fts("সংবাদ", top_k=30)
        for r in results:
            title = r.get("title") or ""
            assert MARKER not in title
            assert not title.startswith(LOCKED_TITLE_MARKER)
            assert title.strip()
