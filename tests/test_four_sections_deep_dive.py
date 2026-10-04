import json
import pytest
from src.web.app import create_app
from src.storage.database import init_db, get_db_session
from src.storage.repositories import UserRepository, DataCenterRepository
from src.datacenter.storage_manager import CloudStorageManager

@pytest.fixture
def auth_client():
    init_db()
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with get_db_session() as session:
        user_repo = UserRepository(session)
        admin = user_repo.get_by_username("admin")
        if not admin:
            admin = user_repo.create_user("admin", "admin@webcreoling.ai", "admin123", role="admin")

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = admin.id
            sess["username"] = admin.username
            sess["role"] = "admin"
        yield client

# ==============================================================================
# 1. TRAINING SECTION TESTS (http://127.0.0.1:8080/training)
# ==============================================================================
def test_training_section_view_and_simulation(auth_client):
    # Test GET /training
    resp = auth_client.get("/training")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "AI Model Training, Topic Splitter & Optimization Studio" in html
    assert "tab-topics" in html
    assert "tab-finetune" in html
    assert "tab-scrape-learn" in html
    assert "tab-local-upload" in html
    assert "tab-inference-playground" in html

    # Test GET /training?tab=finetune
    resp_tab = auth_client.get("/training?tab=finetune")
    assert resp_tab.status_code == 200

    # Test POST /training/api/portal-brain-simulate
    sim_resp = auth_client.post(
        "/training/api/portal-brain-simulate",
        json={"raw_news": "বাংলাদেশ ব্যাংকের গভর্নর মূল্যস্ফীতি নিয়ন্ত্রণে নতুন নীতি ঘোষণা করেছেন।"},
        headers={"Content-Type": "application/json"}
    )
    assert sim_resp.status_code == 200
    sim_data = sim_resp.get_json()
    assert sim_data["status"] == "success"
    assert "pipeline_result" in sim_data
    assert "latency_ms" in sim_data["pipeline_result"]
    assert len(sim_data["pipeline_result"]["steps"]) >= 4
    assert sim_data["pipeline_result"]["published_article"]["category"] == "অর্থনীতি"

# ==============================================================================
# 2. ADMIN AUTOMATION SECTION TESTS (http://127.0.0.1:8080/admin/automation)
# ==============================================================================
def test_admin_automation_section(auth_client):
    # Test GET /admin/automation
    resp = auth_client.get("/admin/automation")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "অটোমেশন, শিডিউলার ও এআই ফেক নিউজ কন্ট্রোল প্যানেল" in html
    assert "tab-jobs" in html
    assert "tab-policy" in html
    assert "tab-live-stream" in html

    # Test GET /admin/automation/api/jobs
    jobs_resp = auth_client.get("/admin/automation/api/jobs")
    assert jobs_resp.status_code == 200
    jobs_data = jobs_resp.get_json()
    assert "is_active" in jobs_data
    assert "jobs" in jobs_data

    # Test POST /admin/automation/update-interval/<job_id>
    update_resp = auth_client.post(
        "/admin/automation/update-interval/rss_social_harvester",
        data={"interval_seconds": "900"},
        follow_redirects=False
    )
    assert update_resp.status_code == 302
    assert "/admin/automation" in update_resp.headers["Location"]

# ==============================================================================
# 3. DATACENTER & CLOUD CREDENTIALS TESTS (http://127.0.0.1:8080/admin/datacenter/)
# ==============================================================================
def test_datacenter_cloud_credentials(auth_client):
    # Test GET /admin/datacenter/
    resp = auth_client.get("/admin/datacenter/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "ক্লাউড স্টোরেজ" in html or "Data Center" in html
    assert "fields_google_drive" in html
    assert "fields_s3" in html
    assert "fields_ftp" in html
    assert "fields_mega" in html

    # Test Saving FTP Provider with credentials
    ftp_resp = auth_client.post(
        "/admin/datacenter/storage/save",
        data={
            "provider_type": "ftp",
            "name": "Enterprise SFTP Offsite Storage",
            "cdn_base_url": "https://mirror.the-daily-ai-alo.org/media",
            "ftp_host": "ftp.example.com",
            "ftp_port": "21",
            "ftp_user": "newsroom_ftp_user",
            "ftp_password": "SecretFtpPassword123!",
            "ftp_remote_dir": "/public_html/cdn",
            "use_tls": "1",
        },
        follow_redirects=False
    )
    assert ftp_resp.status_code == 302

    # Test Saving AWS S3 Provider with credentials
    s3_resp = auth_client.post(
        "/admin/datacenter/storage/save",
        data={
            "provider_type": "s3",
            "name": "AWS S3 Wasabi Edge Media Store",
            "cdn_base_url": "https://s3.ap-southeast-1.wasabisys.com/the-daily-ai-alo-cdn",
            "access_key_id": "AKIAEXAMPLE12345678",
            "secret_access_key": "SecretS3Key1234567890abcdef",
            "bucket_name": "the-daily-ai-alo-cdn",
            "region": "ap-southeast-1",
            "endpoint_url": "https://s3.ap-southeast-1.wasabisys.com",
        },
        follow_redirects=False
    )
    assert s3_resp.status_code == 302

    # Test Saving Mega.nz Provider with credentials
    mega_resp = auth_client.post(
        "/admin/datacenter/storage/save",
        data={
            "provider_type": "mega",
            "name": "Mega Encrypted Media Archive",
            "cdn_base_url": "https://mega.nz/file",
            "mega_email": "storage@the-daily-ai-alo.org",
            "mega_password": "MegaSuperSecurePass2026!",
        },
        follow_redirects=False
    )
    assert mega_resp.status_code == 302

    # Verify providers saved in DB with credentials
    with get_db_session() as session:
        dc_repo = DataCenterRepository(session)
        provs = dc_repo.list_storage_providers()
        prov_types = [p.provider_type for p in provs]
        assert "ftp" in prov_types
        assert "s3" in prov_types
        assert "mega" in prov_types

    # Test Connection Check with CloudStorageManager
    ftp_check = CloudStorageManager.test_provider_connection({
        "provider_type": "ftp",
        "name": "Test FTP",
        "credentials_json": {"ftp_host": "ftp.example.com", "username": "ftp_user", "password": "pass"}
    })
    assert "status" in ftp_check
    assert ftp_check["status"] in ("ONLINE", "CONNECTION_FAILED")

    s3_check = CloudStorageManager.test_provider_connection({
        "provider_type": "s3",
        "name": "Test S3",
        "credentials_json": {"access_key_id": "AKIA...", "bucket_name": "media-cdn", "region": "ap-southeast-1"}
    })
    assert s3_check["status"] == "ONLINE"

    mega_check = CloudStorageManager.test_provider_connection({
        "provider_type": "mega",
        "name": "Test Mega",
        "credentials_json": {"user_email": "user@mega.nz", "password": "pass"}
    })
    assert mega_check["status"] == "ONLINE"

# ==============================================================================
# 4. AGENT SECTION TESTS (http://127.0.0.1:8080/agent/ and /agent)
# ==============================================================================
def test_agent_section_both_urls(auth_client):
    # Test GET /agent/ (with trailing slash)
    resp_slash = auth_client.get("/agent/")
    assert resp_slash.status_code == 200
    html_slash = resp_slash.get_data(as_text=True)
    assert "এআই এজেন্ট" in html_slash or "AI Agent" in html_slash
    assert "অনুমোদন ইনবক্স" in html_slash or "Approval Inbox" in html_slash

    # Test GET /agent (without trailing slash)
    resp_noslash = auth_client.get("/agent", follow_redirects=True)
    assert resp_noslash.status_code == 200
    html_noslash = resp_noslash.get_data(as_text=True)
    assert "এআই এজেন্ট" in html_noslash or "AI Agent" in html_noslash

    # Test API Inbox
    api_resp = auth_client.get("/agent/api/inbox")
    assert api_resp.status_code == 200
    api_data = api_resp.get_json()
    assert api_data["success"] is True
    assert "requests" in api_data
    assert "policy" in api_data
