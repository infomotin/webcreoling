"""Integration tests for Digital Newspaper Portal, Reader Interactions & Newsroom Editorial Management."""

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
    assert "সম্পাদকীয়".encode("utf-8") in res_editor.data or b"Newsroom" in res_editor.data


def test_editorial_article_crud_and_approval(client):
    """Test full CRUD operations, editing, approvals, archiving, and deletion by editor."""
    # Login as Editor
    client.post(
        "/auth/login",
        data={"username": "editor", "password": "editor123"},
        follow_redirects=True,
    )

    # 1. Create Draft Article
    res_create = client.post(
        "/admin/newspaper/article/create",
        data={
            "title": "জাতীয় অর্থনৈতিক পরিষদের নতুন প্রকল্প অনুমোদন",
            "category": "business",
            "author": "অর্থনীতি ব্যুরো",
            "summary": "জাতীয় অর্থনৈতিক পরিষদ আজ একাধিক উন্নয়ন প্রকল্প অনুমোদন করেছে।",
            "content_text": "আজ অনুষ্ঠিত একনেক সভায় মোট দশটি নতুন মেগা প্রকল্পের অনুমোদন প্রদান করা হয়েছে। এই প্রকল্পসমূহ দেশের অবকাঠামো উন্নয়নে অবদান রাখবে।",
            "is_featured": "1",
            "is_breaking": "1",
            "status": "draft",
        },
        follow_redirects=True,
    )
    assert res_create.status_code == 200

    # Retrieve created article
    with get_db_session() as session:
        repo = ArticleRepository(session)
        articles = repo.list_editorial_articles(search_query="জাতীয় অর্থনৈতিক")["articles"]
        assert len(articles) > 0
        art = articles[0]
        art_id = art.id
        assert art.scrape_status == "draft"
        assert art.is_featured == True
        assert art.is_breaking == True

    # 2. Approve and Publish Article
    res_approve = client.post(f"/admin/newspaper/article/approve/{art_id}", follow_redirects=True)
    assert res_approve.status_code == 200
    with get_db_session() as session:
        repo = ArticleRepository(session)
        updated_art = repo.get_by_id(art_id)
        assert updated_art.scrape_status == "completed"

    # 3. Edit Article
    res_edit = client.post(
        f"/admin/newspaper/article/edit/{art_id}",
        data={
            "title": "জাতীয় অর্থনৈতিক পরিষদের দশটি মেগা প্রকল্প অনুমোদন",
            "category": "business",
            "author": "অর্থনীতি ডেস্ক",
            "summary": "আপডেট সারসংক্ষেপ",
            "content_text": "সংশোধিত বিস্তারিত বিবরণ এখানে প্রকাশ করা হলো।",
            "status": "completed",
        },
        follow_redirects=True,
    )
    assert res_edit.status_code == 200
    with get_db_session() as session:
        repo = ArticleRepository(session)
        edited_art = repo.get_by_id(art_id)
        assert "দশটি মেগা" in edited_art.title

    # 4. Archive Article
    res_archive = client.post(f"/admin/newspaper/article/archive/{art_id}", follow_redirects=True)
    assert res_archive.status_code == 200
    with get_db_session() as session:
        repo = ArticleRepository(session)
        archived_art = repo.get_by_id(art_id)
        assert archived_art.scrape_status == "archived"

    # 5. Restore Article
    res_restore = client.post(f"/admin/newspaper/article/restore/{art_id}", follow_redirects=True)
    assert res_restore.status_code == 200
    with get_db_session() as session:
        repo = ArticleRepository(session)
        restored_art = repo.get_by_id(art_id)
        assert restored_art.scrape_status == "completed"

    # 6. Delete Article
    res_del = client.post(f"/admin/newspaper/article/delete/{art_id}", follow_redirects=True)
    assert res_del.status_code == 200
    with get_db_session() as session:
        repo = ArticleRepository(session)
        assert repo.get_by_id(art_id) is None


def test_editorial_poll_and_subscriber_management(client):
    """Test creating/deleting polls and deleting subscribers from the newsroom backend."""
    # Login as Editor
    client.post(
        "/auth/login",
        data={"username": "editor", "password": "editor123"},
        follow_redirects=True,
    )

    # 1. Create Poll
    res_create_poll = client.post(
        "/admin/newspaper/create-poll",
        data={
            "question": "ডিজিটাল সংবাদমাধ্যমের এআই ব্যবহারে বিশ্বাসযোগ্যতা কি বাড়বে?",
            "category": "প্রযুক্তি",
            "options": "হ্যাঁ\nনা\nমন্তব্য নেই",
        },
        follow_redirects=True,
    )
    assert res_create_poll.status_code == 200

    # 2. Toggle and Delete Poll
    with get_db_session() as session:
        repo = PortalRepository(session)
        polls = repo.list_all_polls()
        created_poll = [p for p in polls if "ডিজিটাল সংবাদমাধ্যমের" in p.question][0]
        poll_id = created_poll.id

    res_toggle = client.post(f"/admin/newspaper/toggle-poll/{poll_id}", follow_redirects=True)
    assert res_toggle.status_code == 200

    res_del_poll = client.post(f"/admin/newspaper/delete-poll/{poll_id}", follow_redirects=True)
    assert res_del_poll.status_code == 200

    # 3. Delete Subscriber
    with get_db_session() as session:
        repo = PortalRepository(session)
        repo.add_subscriber("temp_user_test@domain.com")
        session.commit()
        subs = repo.list_subscribers()
        temp_sub = [s for s in subs if s.email == "temp_user_test@domain.com"][0]
        sub_id = temp_sub.id

    res_del_sub = client.post(f"/admin/newspaper/delete-subscriber/{sub_id}", follow_redirects=True)
    assert res_del_sub.status_code == 200
