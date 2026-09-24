"""
Test Suite for 360-degree Executive Dashboard, Live Visitor Telemetry,
Monitored Newspaper Directory CRUD, Top 10 World News, Trending Keywords, and Real-Time Notifications.
"""

import pytest
from src.storage.database import init_db, get_db_session
from src.storage.repositories import UserRepository, ArticleRepository
from src.automation.newspaper_monitor import get_newspaper_monitor
from src.web.app import create_app


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

        # Seed sample articles
        art_repo = ArticleRepository(session)
        art_repo.upsert_article({
            "url": "https://test-world-news.org/story-1",
            "source": "Reuters World",
            "title": "জাতিসংঘ সাধারণ পরিষদে বৈশ্বিক জলবায়ু চুক্তি চূড়ান্ত",
            "content_text": "বিশ্বের সকল দেশ কার্বন নিঃসরণ হ্রাসে নতুন আন্তর্জাতিক চুক্তি স্বাক্ষর করেছে।",
            "category": "world",
            "scrape_status": "completed",
        })

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = admin_user.id
            sess["username"] = admin_user.username
            sess["role"] = "admin"
        yield client


# ==============================================================================
# 1. Dashboard View & Analytics Rendering
# ==============================================================================

def test_dashboard_360_view_rendering(client):
    """Verify GET / loads with all executive analytics, world news, and newspaper watchlist."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "৩৬০° এক্সিকিউটিভ ড্যাশবোর্ড ও সার্বিক মনিটরিং হাব" in html
    assert "সংবাদপত্র লাইভ ডিরেক্টরি ও মনিটরিং ওয়াচলিস্ট" in html
    assert "শীর্ষ ১০টি আন্তর্জাতিক সংবাদ" in html
    assert "শীর্ষ আলোচিত শব্দমালা ও ট্রেন্ডিং টপিক" in html
    assert "অনলাইন ভিজিটর" in html
    assert "লোড টাইম ও ল্যাটেন্সি" in html


def test_dashboard_live_telemetry_api(client):
    """Verify GET /api/dashboard/telemetry returns visitor and performance metrics."""
    resp = client.get("/api/dashboard/telemetry")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "active_visitors_now" in data
    assert "today_pageviews" in data
    assert "page_load_time_ms" in data
    assert data["active_visitors_now"] > 0
    assert data["page_load_time_ms"] > 0


# ==============================================================================
# 2. Monitored Newspaper Watchlist CRUD Tests
# ==============================================================================

def test_newspaper_watchlist_crud_lifecycle(client):
    """Verify full CRUD lifecycle for monitored newspapers."""
    # 1. CREATE / ADD Newspaper
    add_payload = {
        "name": "The New York Times",
        "name_bn": "দ্য নিউ ইয়র্ক টাইমস",
        "url": "https://www.nytimes.com",
        "category": "আন্তর্জাতিক",
        "language": "English",
        "country": "USA",
        "scrape_interval_mins": 45,
        "notification_enabled": "true",
    }
    resp = client.post("/api/monitor/newspaper/add", json=add_payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    paper_id = data["newspaper"]["id"]
    assert "nytimes" in paper_id or "new_york" in paper_id
    assert data["newspaper"]["name_bn"] == "দ্য নিউ ইয়র্ক টাইমস"

    # 2. UPDATE Newspaper
    update_payload = {
        "name_bn": "দ্য নিউ ইয়র্ক টাইমস আন্তর্জাতিক",
        "category": "গ্লোবাল লিড",
        "scrape_interval_mins": 60,
    }
    resp_update = client.post(f"/api/monitor/newspaper/update/{paper_id}", json=update_payload)
    assert resp_update.status_code == 200
    update_data = resp_update.get_json()
    assert update_data["status"] == "success"
    assert update_data["newspaper"]["name_bn"] == "দ্য নিউ ইয়র্ক টাইমস আন্তর্জাতিক"
    assert update_data["newspaper"]["scrape_interval_mins"] == 60

    # 3. TOGGLE Monitoring
    resp_toggle = client.post(f"/api/monitor/newspaper/toggle/{paper_id}", json={})
    assert resp_toggle.status_code == 200
    toggle_data = resp_toggle.get_json()
    assert toggle_data["status"] == "success"
    assert toggle_data["is_monitoring_active"] is False

    # 4. TOGGLE Notifications
    resp_notif_toggle = client.post(f"/api/monitor/newspaper/toggle-notif/{paper_id}", json={})
    assert resp_notif_toggle.status_code == 200
    assert resp_notif_toggle.get_json()["status"] == "success"

    # 5. PING Newspaper
    resp_ping = client.post(f"/api/monitor/newspaper/ping/{paper_id}", json={})
    assert resp_ping.status_code == 200
    ping_data = resp_ping.get_json()
    assert ping_data["status"] == "success"
    assert "newspaper_status" in ping_data

    # 6. DELETE Newspaper
    resp_del = client.post(f"/api/monitor/newspaper/delete/{paper_id}", json={})
    assert resp_del.status_code == 200
    assert resp_del.get_json()["status"] == "success"


# ==============================================================================
# 3. Notifications System Tests
# ==============================================================================

def test_notification_dispatch_and_history(client):
    """Verify test notification dispatch and live notification retrieval."""
    # 1. Dispatch test notification
    resp_dispatch = client.post("/api/notifications/dispatch-test", json={})
    assert resp_dispatch.status_code == 200
    data = resp_dispatch.get_json()
    assert data["status"] == "success"
    assert "notification" in data
    assert "🔔" in data["notification"]["title"]

    # 2. Get live notifications
    resp_live = client.get("/api/notifications/live")
    assert resp_live.status_code == 200
    live_data = resp_live.get_json()
    assert "notifications" in live_data
    assert len(live_data["notifications"]) >= 1

    # 3. Mark read
    resp_read = client.post("/api/notifications/mark-read", json={})
    assert resp_read.status_code == 200
    assert resp_read.get_json()["status"] == "success"


# ==============================================================================
# 4. Top World News & Trending Keywords Extractor Tests
# ==============================================================================

def test_top_world_news_and_trending_words():
    """Verify NewspaperMonitorManager computes top 10 world news and trending keywords."""
    monitor = get_newspaper_monitor()
    
    # Top 10 World news
    world_news = monitor.get_top_ten_world_news()
    assert isinstance(world_news, list)
    assert len(world_news) <= 10
    if len(world_news) > 0:
        assert "title" in world_news[0]
        assert "rank" in world_news[0]

    # Trending words
    words = monitor.get_top_trending_words()
    assert isinstance(words, list)
    assert len(words) >= 3
    assert "word" in words[0]
    assert "trend_delta" in words[0]
