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
    unique_test_title = "টেস্ট খসড়া একনেক নতুন উন্নয়ন প্রকল্প অনুমোদন"
    res_create = client.post(
        "/admin/newspaper/article/create",
        data={
            "title": unique_test_title,
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
        from src.storage.models import Article
        from src.common.normalizer import BanglaTextNormalizer
        norm_title = BanglaTextNormalizer.normalize_article_text(unique_test_title)
        art = session.query(Article).filter(Article.title == norm_title).order_by(Article.id.desc()).first()
        if not art:
            art = session.query(Article).filter(Article.title.like("%একনেক%")).order_by(Article.id.desc()).first()
        assert art is not None
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


def test_site_branding_and_settings(client):
    """Test saving portal branding, exchange rates, and weather ticker configs."""
    # Login as Admin
    client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=True,
    )

    res_save = client.post(
        "/admin/newspaper/settings/save",
        data={
            "site_title": "প্রথম আলো টেস্ট পোর্টাল",
            "site_tagline": "ডিজিটাল এআই সংস্করণ",
            "logo_text": "প্রথম আলো",
            "edition": "ঢাকা টেস্ট সংস্করণ",
            "usd_rate": "১২২.০০",
            "eur_rate": "১৩৩.০০",
            "weather_city": "চট্টগ্রাম",
            "weather_temp": "২৯° সে.",
            "weather_desc": "রৌদ্রোজ্জ্বল",
        },
        follow_redirects=True,
    )
    assert res_save.status_code == 200

    # Verify tab renders saved configs
    res_tab = client.get("/admin/newspaper?tab=settings")
    assert res_tab.status_code == 200
    assert "১২২.০০".encode("utf-8") in res_tab.data
    assert "চট্টগ্রাম".encode("utf-8") in res_tab.data

    # Verify public portal reflects new branding
    res_public = client.get("/news")
    assert res_public.status_code == 200
    assert "চট্টগ্রাম".encode("utf-8") in res_public.data


def test_dynamic_footer_management(client):
    """Test saving dynamic footer, address, and credentials."""
    client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=True,
    )

    res_save = client.post(
        "/admin/newspaper/footer/save",
        data={
            "editor_in_chief": "ভারপ্রাপ্ত সম্পাদক: টেস্ট এডিটর",
            "publisher": "ক্রিয়েলিং এআই মিডিয়া",
            "office_address": "কারওয়ান বাজার, ঢাকা",
            "contact_email": "test_editorial@prothomalo.com",
            "contact_phone": "+8801700000000",
            "copyright_text": "© ২০২৬ টেস্ট স্বত্ব সংরক্ষিত।",
            "facebook_url": "https://facebook.com/test",
            "youtube_url": "https://youtube.com/test",
            "twitter_url": "https://twitter.com/test",
            "android_app_url": "https://play.google.com/test",
            "ios_app_url": "https://apple.com/test",
        },
        follow_redirects=True,
    )
    assert res_save.status_code == 200

    # Verify tab
    res_tab = client.get("/admin/newspaper?tab=footer")
    assert res_tab.status_code == 200
    assert "test_editorial@prothomalo.com".encode("utf-8") in res_tab.data


def test_advertisement_crud_and_click_tracking(client):
    """Test ad banner creation, toggling, impression count, and click redirection."""
    client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=True,
    )

    # 1. Create Ad
    res_create = client.post(
        "/admin/newspaper/ads/create",
        data={
            "title": "ইউনিট টেস্ট বিজ্ঞাপন",
            "slot": "header_top",
            "image_url": "https://example.com/test_banner.jpg",
            "target_url": "https://example.com/promo-target",
            "is_active": "1",
        },
        follow_redirects=True,
    )
    assert res_create.status_code == 200

    # Retrieve ad id
    from src.storage.repositories import AdvertisementRepository
    with get_db_session() as session:
        ad_repo = AdvertisementRepository(session)
        ads = ad_repo.get_all_ads()
        test_ad = [a for a in ads if a.title == "ইউনিট টেস্ট বিজ্ঞাপন"][0]
        ad_id = test_ad.id

    # 2. Toggle Status
    res_toggle = client.post(f"/admin/newspaper/ads/toggle/{ad_id}", follow_redirects=True)
    assert res_toggle.status_code == 200

    # 3. Ad Click Tracking & Redirect
    res_click = client.get(f"/news/ad/click/{ad_id}", follow_redirects=False)
    assert res_click.status_code == 302
    assert res_click.location == "https://example.com/promo-target"

    # 4. Delete Ad
    res_del = client.post(f"/admin/newspaper/ads/delete/{ad_id}", follow_redirects=True)
    assert res_del.status_code == 200


def test_scheduled_publishing_workflow(client):
    """Test article scheduled publishing with future datetime and publish-now action."""
    client.post(
        "/auth/login",
        data={"username": "editor", "password": "editor123"},
        follow_redirects=True,
    )

    # 1. Create Scheduled Article
    res_create = client.post(
        "/admin/newspaper/article/create",
        data={
            "title": "ভবিষ্যতে প্রকাশিতব্য আন্তর্জাতিক রিপোর্ট",
            "category": "international",
            "author": "আন্তর্জাতিক ডেস্ক",
            "summary": "শিডিউল সারসংক্ষেপ",
            "content_text": "এই সংবাদটি নির্ধারিত সময়ে স্বয়ংক্রিয়ভাবে প্রকাশ পাবে।",
            "scheduled_at": "2026-10-01T10:00",
            "status": "scheduled",
        },
        follow_redirects=True,
    )
    assert res_create.status_code == 200

    with get_db_session() as session:
        repo = ArticleRepository(session)
        sched_articles = repo.get_scheduled_articles()
        target = [a for a in sched_articles if "ভবিষ্যতে প্রকাশিতব্য" in a.title][0]
        art_id = target.id
        assert target.scrape_status == "scheduled"

    # 2. Publish Now
    res_now = client.post(f"/admin/newspaper/scheduler/publish-now/{art_id}", follow_redirects=True)
    assert res_now.status_code == 200

    with get_db_session() as session:
        repo = ArticleRepository(session)
        published = repo.get_by_id(art_id)
        assert published.scrape_status == "completed"

    # Cleanup
    client.post(f"/admin/newspaper/article/delete/{art_id}")


def test_security_and_audit_logging(client):
    """Test editorial audit action trail and logging."""
    client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=True,
    )

    res_audit_tab = client.get("/admin/newspaper?tab=security")
    assert res_audit_tab.status_code == 200
    assert "অডিট ট্রেইল".encode("utf-8") in res_audit_tab.data or "নিরাপত্তা".encode("utf-8") in res_audit_tab.data


def test_server_monitoring_telemetry(client):
    """Test server telemetry health metrics tab."""
    client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=True,
    )

    res_mon = client.get("/admin/newspaper?tab=monitor")
    assert res_mon.status_code == 200
    assert "CPU".encode("utf-8") in res_mon.data
    assert "RAM".encode("utf-8") in res_mon.data


def test_ai_pilot_analysis_api(client):
    """Test AI Pilot content analyzer endpoint."""
    client.post(
        "/auth/login",
        data={"username": "editor", "password": "editor123"},
        follow_redirects=True,
    )

    # 1. Save AI Pilot config
    res_cfg = client.post(
        "/admin/newspaper/aipilot/save",
        data={
            "enabled": "1",
            "auto_headline": "1",
            "auto_summary": "1",
            "auto_categorize": "1",
            "auto_hero_ranking": "1",
            "model_name": "webcreoling-lora-v1",
        },
        follow_redirects=True,
    )
    assert res_cfg.status_code == 200

    # 2. AJAX AI Pilot analysis
    res_analysis = client.post(
        "/admin/newspaper/aipilot/analyze",
        json={
            "title": "জাতীয় সংসদে নতুন প্রযুক্তি বাজেট প্রস্তাব পাস",
            "content_text": "জাতীয় সংসদে আজ তথ্যপ্রযুক্তি খাতে বাজেট বরাদ্দ বাড়ানোর বিষয়ে সিদ্ধান্ত গৃহীত হয়েছে। প্রধানমন্ত্রী নতুন এআই উদ্ভাবনী ল্যাব ও সফটওয়্যার পার্ক নির্মাণের ওপর গুরুত্বারোপ করেন। দেশের যুবসমাজ এতে ব্যাপকভাবে উপকৃত হবে।",
        },
    )
    assert res_analysis.status_code == 200
    data = res_analysis.get_json()
    assert data["status"] == "success"
    assert "predicted_category" in data["data"]
    assert "generated_summary" in data["data"]
    assert len(data["data"]["suggested_headlines"]) > 0

