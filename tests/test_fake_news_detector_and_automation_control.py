"""
Test Suite for AI Fake News Detector Model, Dynamic Tolerance Gate & Real-time Automation Control Hub.
"""

import pytest
from datetime import datetime
from src.nlp.fake_news_detector import FakeNewsDetectorEngine
from src.automation.ai_pilot_brain import AIPilotBrain
from src.storage.database import init_db, get_db_session
from src.storage.models import Article
from src.storage.repositories import (
    ArticleRepository,
    SiteConfigRepository,
    UserRepository,
)
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

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = admin_user.id
            sess["username"] = admin_user.username
            sess["role"] = "admin"
        yield client


# ==============================================================================
# 1. AI Fake News Detector Model Unit Tests
# ==============================================================================

def test_fake_news_detector_authentic_article():
    """Verify authentic news from trusted source gets very low fake probability (< 25%)."""
    report = FakeNewsDetectorEngine.evaluate(
        title="বাংলাদেশ ব্যাংকের নতুন গভর্নর হিসেবে দায়িত্ব নিলেন বিশিষ্ট অর্থনীতিবিদ",
        content="বাংলাদেশ ব্যাংকের নতুন গভর্নর হিসেবে আজ সকালে আনুষ্ঠানিকভাবে দায়িত্ব গ্রহণ করেছেন। তিনি বলেছেন, মূল্যস্ফীতি নিয়ন্ত্রণ এবং ব্যাংকিং খাতে শৃঙ্খলা ফেরানোই তাঁর প্রধান অগ্রাধিকার। তিনি সাংবাদিকদের জানান, নীতিগত সংস্কার অব্যাহত থাকবে।",
        source="Prothom Alo",
        author="অর্থনীতি ডেস্ক",
        max_allowed_fake_pct=50.0,
    )

    assert report["fake_probability_pct"] <= 25.0
    assert report["factuality_score"] >= 75.0
    assert report["verdict"] in ["AUTHENTIC", "LIKELY_AUTHENTIC"]
    assert report["is_publishable"] is True
    assert report["is_trusted_source"] is True


def test_fake_news_detector_sensational_clickbait_hoax():
    """Verify sensational clickbait and unverified rumor triggers high fake probability (> 50%)."""
    report = FakeNewsDetectorEngine.evaluate(
        title="বিস্ফোরক তথ্য ফাঁস! দেখুন কি করলেন প্রধানমন্ত্রী, চোখ কপালে উঠবে সবার???",
        content="সোশ্যাল মিডিয়ায় ছড়িয়ে পড়েছে গোপন ফাঁস! নাম প্রকাশে অনিচ্ছুক এক কর্মকর্তা দাবি করেছেন কাল থেকেই নাকি বিদ্যুৎ বন্ধ থাকবে। এখনই শেয়ার করুন সবাইকে জানিয়ে দিন!",
        source="viral_rumor_desk",
        author="ভাইরাল টিম",
        max_allowed_fake_pct=50.0,
    )

    assert report["fake_probability_pct"] > 50.0
    assert report["factuality_score"] < 50.0
    assert report["verdict"] in ["MODERATE_RISK", "HIGH_FAKE_PROBABILITY", "FABRICATED_HOAX"]
    assert report["is_publishable"] is False  # Exceeded 50% tolerance!
    assert report["decision_code"] == "QUARANTINED_EXCEEDED_FAKE_THRESHOLD"
    assert len(report["flags"]) >= 3


def test_fake_news_tolerance_threshold_gate():
    """Verify custom tolerance threshold (e.g. 50% vs 20%) changes publishability verdict."""
    test_title = "নতুন এআই চিপ বাজারে আনলো বৈশ্বিক প্রযুক্তি প্রতিষ্ঠান"
    test_content = "যুক্তরাষ্ট্রে আয়োজিত অনুষ্ঠানে নতুন এআই প্রসেসর উন্মোচন করা হয়েছে। এতে কম্পিউটিং গতি প্রায় তিন গুণ বৃদ্ধি পাবে বলে ধারণা করা হচ্ছে।"
    
    # At 50% tolerance (User's rule), moderate article is publishable
    report_50 = FakeNewsDetectorEngine.evaluate(
        title=test_title,
        content=test_content,
        source="Tech Open Feed",
        max_allowed_fake_pct=50.0,
    )
    assert report_50["is_publishable"] is True

    # At 5% strict tolerance, it exceeds the strict threshold
    report_5 = FakeNewsDetectorEngine.evaluate(
        title=test_title,
        content=test_content,
        source="Tech Open Feed",
        max_allowed_fake_pct=5.0,
    )
    assert report_5["is_publishable"] is False


# ==============================================================================
# 2. AI Pilot Brain End-to-End Fake News Integration
# ==============================================================================

def test_ai_pilot_brain_respects_fake_news_tolerance():
    """Verify AIPilotBrain automatically publishes <= 50% fake news and quarantines > 50%."""
    # 1. Clean news (Fake ~ 12%) -> Should AUTO_PUBLISH
    clean_article = {
        "url": "https://prothomalo.com/national/ai-education-2026",
        "source": "Prothom Alo",
        "title": "জাতীয় শিক্ষাক্রমে কৃত্রিম বুদ্ধিমত্তা ও প্রোগ্রামিং যুক্ত হচ্ছে",
        "content_text": "জাতীয় শিক্ষাক্রম ও পাঠ্যপুস্তক বোর্ড জানিয়েছে, আগামী শিক্ষাবর্ষ থেকেই মাধ্যমিক স্তরে এআই ও কোডিং বাধ্যতামূলক করা হচ্ছে। শিক্ষামন্ত্রী বলেছেন, চতুর্থ শিল্প বিপ্লবের জন্য শিক্ষার্থীদের প্রস্তুত করাই মূল লক্ষ্য।",
        "author": "শিক্ষা প্রতিবেদক",
        "category": "education",
    }
    processed_clean = AIPilotBrain.process_raw_article(
        raw_article=clean_article,
        max_allowed_fake_pct=50.0,
    )
    assert processed_clean["ai_decision"] in ["AUTO_PUBLISH", "QUEUE_FOR_REVIEW"]
    assert processed_clean["fake_probability_pct"] <= 50.0

    # 2. Clickbait Viral Hoax (Fake > 50%) -> Should QUARANTINE
    hoax_article = {
        "url": "https://clickbait-viral.com/hoax-cure-9988",
        "source": "clickbait_wire",
        "title": "অবিশ্বাস্য খবর! রাতারাতি ডায়াবেটিস দূর করার গোপন মহা ঔষধ আবিষ্কার??? না দেখলে মিস!",
        "content_text": "সোশ্যাল মিডিয়ায় ভাইরাল হওয়া বার্তায় দাবি করা হয়েছে এই গাছের পাতা খেলে আর কোনো দিন ওষুধ খেতে হবে না। এখনই শেয়ার করুন সবাইকে জানিয়ে দিন!",
        "author": "ভাইরাল ডাক্তার",
        "category": "health",
    }
    processed_hoax = AIPilotBrain.process_raw_article(
        raw_article=hoax_article,
        max_allowed_fake_pct=50.0,
    )
    assert processed_hoax["ai_decision"] == "QUARANTINED_HIGH_FAKE_RISK"
    assert processed_hoax["scrape_status"] == "archived"
    assert processed_hoax["fake_probability_pct"] > 50.0


# ==============================================================================
# 3. Web Routes & Real-time Live API Endpoints
# ==============================================================================

def test_automation_dashboard_view_and_kpis(client):
    """Test GET /admin/automation loads with fake news policy, KPIs and live feed."""
    resp = client.get("/admin/automation")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "অটোমেশন" in html
    assert "এআই ফেক নিউজ" in html
    assert "অনুমোদিত সর্বোচ্চ ফেক সম্ভাব্যতা সীমা" in html
    assert "লাইভ প্রকাশিত ও এআই বিশ্লেষিত সংবাদ ফিড" in html


def test_automation_update_fake_news_policy(client):
    """Test POST /admin/automation/fake-news-policy updates policy threshold."""
    resp = client.post(
        "/admin/automation/fake-news-policy",
        data={
            "max_fake_tolerance_pct": "50",
            "auto_publish_enabled": "1",
            "quarantine_high_fake": "1",
            "social_dispatch_enabled": "1",
            "strict_mode": "0",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "এআই ফেক নিউজ নীতি আপডেট সম্পন্ন" in html

    # Verify in DB
    with get_db_session() as session:
        config_repo = SiteConfigRepository(session)
        policy = config_repo.get_fake_news_policy()
        assert float(policy["max_fake_tolerance_pct"]) == 50.0
        assert policy["auto_publish_enabled"] is True


def test_automation_api_live_status_json(client):
    """Test GET /admin/automation/api/live-status returns JSON with KPIs and feed."""
    resp = client.get("/admin/automation/api/live-status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "kpis" in data
    assert "policy" in data
    assert "live_feed" in data
    assert "scheduler" in data
    assert data["policy"]["max_fake_tolerance_pct"] >= 0


def test_automation_article_override_and_audit(client):
    """Test POST /admin/automation/article-override/<id> and fact check audit."""
    # Seed an article in pending
    with get_db_session() as session:
        art_repo = ArticleRepository(session)
        art = art_repo.upsert_article(
            article_data={
                "url": "https://test-news.org/audit-sample-99",
                "source": "Sample Wire",
                "title": "ঢাকায় আধুনিক সাইবার ফরেনসিক ল্যাব উদ্বোধন",
                "content_text": "তথ্য ও যোগাযোগ প্রযুক্তি বিভাগ আজ নতুন সাইবার নিরাপত্তা ল্যাব উদ্বোধন করেছে।",
                "scrape_status": "pending",
                "category": "technology",
            }
        )
        art_id = art.id

    # 1. Override to publish
    resp = client.post(
        f"/admin/automation/article-override/{art_id}",
        data={"action": "publish"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "সফলভাবে লাইভ পোর্টালে প্রকাশিত" in resp.get_data(as_text=True)

    # 2. Run fact check audit
    resp_audit = client.post("/admin/automation/run-fact-check-audit", follow_redirects=True)
    assert resp_audit.status_code == 200
    assert "ফ্যাক্ট-চেকিং অডিট সম্পন্ন" in resp_audit.get_data(as_text=True)


# ==============================================================================
# 4. Automation Job CRUD & Scheduler Operations Tests
# ==============================================================================

def test_automation_job_crud_lifecycle(client):
    """Verify full CRUD lifecycle for scheduled automation jobs."""
    # 1. CREATE job
    create_payload = {
        "name": "Daily Tech Digest Ingester",
        "name_bn": "দৈনিক প্রযুক্তি সংবাদ ইনজেস্টার",
        "description": "স্বয়ংক্রিয়ভাবে প্রযুক্তি সংবাদ সংগ্রহ ও অনুবাদ করে",
        "job_type": "crawler",
        "interval_seconds": 600,
        "site_key": "bbc_bangla",
        "enabled": "true",
    }
    resp = client.post("/admin/automation/job/create", json=create_payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert "job" in data
    job_id = data["job"]["job_id"]
    assert data["job"]["name_bn"] == "দৈনিক প্রযুক্তি সংবাদ ইনজেস্টার"
    assert data["job"]["interval_seconds"] == 600

    # 2. READ / LIST jobs
    resp_list = client.get("/admin/automation/api/jobs")
    assert resp_list.status_code == 200
    jobs_data = resp_list.get_json()
    assert jobs_data["jobs_count"] >= 1
    found_job = next((j for j in jobs_data["jobs"] if j["job_id"] == job_id), None)
    assert found_job is not None

    # 3. READ single job
    resp_single = client.get(f"/admin/automation/api/job/{job_id}")
    assert resp_single.status_code == 200
    single_data = resp_single.get_json()
    assert single_data["status"] == "success"
    assert single_data["job"]["job_id"] == job_id

    # 4. UPDATE job
    update_payload = {
        "name": "Updated Tech Digest Ingester",
        "name_bn": "আপডেটেড প্রযুক্তি ইনজেস্টার",
        "description": "নতুন নিয়মে প্রযুক্তি সংবাদ সংগ্রহ করবে",
        "interval_seconds": 900,
    }
    resp_update = client.post(f"/admin/automation/job/update/{job_id}", json=update_payload)
    assert resp_update.status_code == 200
    update_data = resp_update.get_json()
    assert update_data["status"] == "success"
    assert update_data["job"]["interval_seconds"] == 900
    assert update_data["job"]["name_bn"] == "আপডেটেড প্রযুক্তি ইনজেস্টার"

    # 5. TOGGLE job (Pause / Resume)
    resp_toggle = client.post(f"/admin/automation/job/toggle/{job_id}", json={})
    assert resp_toggle.status_code == 200
    toggle_data = resp_toggle.get_json()
    assert toggle_data["status"] == "success"
    assert toggle_data["enabled"] is False

    # 6. TRIGGER job (Run now)
    resp_trigger = client.post(f"/admin/automation/job/trigger/{job_id}", json={})
    assert resp_trigger.status_code == 200
    trigger_data = resp_trigger.get_json()
    assert trigger_data["status"] in ["started", "warning"]

    # 7. DELETE job
    resp_delete = client.post(f"/admin/automation/job/delete/{job_id}", json={})
    assert resp_delete.status_code == 200
    delete_data = resp_delete.get_json()
    assert delete_data["status"] == "success"

    # Verify deleted
    resp_deleted_check = client.get(f"/admin/automation/api/job/{job_id}")
    assert resp_deleted_check.status_code == 404


def test_automation_batch_actions(client):
    """Test batch operations across all automation jobs."""
    # Batch Pause All
    resp_disable = client.post("/admin/automation/batch-action", json={"action": "disable_all"})
    assert resp_disable.status_code == 200
    assert resp_disable.get_json()["status"] == "success"

    # Batch Resume All
    resp_enable = client.post("/admin/automation/batch-action", json={"action": "enable_all"})
    assert resp_enable.status_code == 200
    assert resp_enable.get_json()["status"] == "success"

    # Batch Reset Stats
    resp_reset = client.post("/admin/automation/batch-action", json={"action": "reset_stats"})
    assert resp_reset.status_code == 200
    assert resp_reset.get_json()["status"] == "success"

