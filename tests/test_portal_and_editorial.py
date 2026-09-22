"""Integration tests for Digital Newspaper Portal, Reader Interactions & Editorial Management."""

import pytest
from src.web.app import create_app
from src.storage.database import init_db, get_db_session
from src.storage.repositories import ArticleRepository, PortalRepository


@pytest.fixture
def client():
    """Flask test client fixture."""
    init_db()
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    with app.test_client() as client:
        yield client


def test_public_newspaper_portal_view(client):
    """Public digital newspaper frontpage should load without requiring login in Prothom Alo style."""
    response = client.get("/news")
    assert response.status_code == 200
    assert "প্রথম".encode("utf-8") in response.data or b"Prothom" in response.data


def test_section_wise_news_view(client):
    """Test dedicated section/category pages in Prothom Alo clone layout."""
    # Politics section
    res_politics = client.get("/news/section/politics")
    assert res_politics.status_code == 200
    assert "রাজনীতি".encode("utf-8") in res_politics.data

    # Business section
    res_business = client.get("/news/section/business")
    assert res_business.status_code == 200
    assert "বাণিজ্য".encode("utf-8") in res_business.data

    # Sports section
    res_sports = client.get("/news/section/sports")
    assert res_sports.status_code == 200
    assert "খেলা".encode("utf-8") in res_sports.data


def test_archive_view_with_selected_date(client):
    """Test newspaper archive viewing with date picker and selected date querying."""
    # General archive page
    res_archive = client.get("/news/archive")
    assert res_archive.status_code == 200
    assert "আর্কাইভ".encode("utf-8") in res_archive.data

    # Specific date archive
    res_date = client.get("/news/archive?date=2026-09-22")
    assert res_date.status_code == 200
    assert "2026-09-22".encode("utf-8") in res_date.data


def test_newspaper_article_view_and_like(client):
    """Test reading an article and toggling reader like."""
    with get_db_session() as session:
        art = ArticleRepository(session).get_lead_hero_article()
        art_id = art.id if art else 1

    # View article
    res_view = client.get(f"/news/{art_id}")
    assert res_view.status_code == 200

    # Toggle like
    res_like = client.post(f"/news/api/like/{art_id}")
    assert res_like.status_code == 200
    data = res_like.get_json()
    assert "liked" in data
    assert "likes_count" in data


def test_newsletter_subscription(client):
    """Test public newsletter subscription API."""
    res_sub = client.post(
        "/news/api/subscribe",
        json={"email": "reader_test@banglanews.com"},
    )
    assert res_sub.status_code == 200
    data = res_sub.get_json()
    assert data["status"] in ["success", "already_subscribed"]


def test_reader_poll_voting(client):
    """Test voting in reader opinion poll."""
    with get_db_session() as session:
        poll = PortalRepository(session).get_active_poll()
        if not poll:
            PortalRepository(session).seed_default_poll()
            session.commit()
            poll = PortalRepository(session).get_active_poll()
        poll_id = poll.id
        option_id = poll.options[0].id if poll.options else 1

    res_vote = client.post(
        "/news/api/poll/vote",
        json={"poll_id": poll_id, "option_id": option_id},
    )
    assert res_vote.status_code == 200
    data = res_vote.get_json()
    assert data["status"] in ["success", "already_voted"]


def test_editorial_management_access_control(client):
    """Editorial manager requires Editor or Admin role."""
    # Unauthenticated -> redirect to login
    res_unauth = client.get("/admin/newspaper", follow_redirects=False)
    assert res_unauth.status_code == 302

    # Login as Editor
    client.post(
        "/auth/login",
        data={"username": "editor", "password": "editor123"},
        follow_redirects=True,
    )
    res_editor = client.get("/admin/newspaper", follow_redirects=True)
    assert res_editor.status_code == 200
    assert b"Editorial &amp; Newspaper Management" in res_editor.data or b"Editorial & Newspaper Management" in res_editor.data

