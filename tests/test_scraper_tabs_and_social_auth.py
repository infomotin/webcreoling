"""
Unit and integration tests for Scraper Hub tabs and Social Media Authentication.
Verifies all 8 tabs:
- /scraper?tab=scroller
- /scraper?tab=rules
- /scraper?tab=social
- /scraper?tab=autopilot
- /scraper?tab=youtube
- /scraper?tab=world
- /scraper?tab=portals
- /scraper?tab=tasks
And validates Social Media Page Authentication for Facebook, YouTube, TikTok, and Telegram.
"""

import pytest
from src.web.app import create_app
from src.storage.database import get_db_session
from src.storage.models import SocialChannelConfig, AIBrainCustomRule
from src.storage.repositories import SocialChannelRepository
from src.automation.social_broadcaster import SocialAuthenticator, UnifiedSocialBroadcaster


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_client(app):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = "admin"
        sess["role"] = "admin"
    return client


def test_all_eight_scraper_tabs_render(admin_client):
    """Test that all 8 tabs load with HTTP 200 and contain their respective tab containers."""
    tabs = [
        ("scroller", "tab-scroller"),
        ("rules", "tab-rules"),
        ("social", "tab-social"),
        ("autopilot", "tab-autopilot"),
        ("youtube", "tab-youtube"),
        ("world", "tab-world"),
        ("portals", "tab-portals"),
        ("tasks", "tab-tasks"),
    ]

    for tab_param, expected_div in tabs:
        res = admin_client.get(f"/scraper?tab={tab_param}")
        assert res.status_code == 200, f"Tab '{tab_param}' failed with {res.status_code}"
        html = res.data.decode("utf-8")
        assert f'id="{expected_div}"' in html, f"Missing container {expected_div} in tab {tab_param}"


def test_social_authenticator_handshakes():
    """Test SocialAuthenticator across Facebook, YouTube, TikTok, and Telegram."""
    # 1. Facebook verification
    fb_ok, fb_msg, fb_det = SocialAuthenticator.verify_facebook(
        page_id="109283746519283",
        app_id="fb_app_982374615",
        app_secret="sec_fb_82736481",
        access_token="EAAK_TEST_LIVE_TOKEN_2026",
        api_version="v19.0",
    )
    assert fb_ok is True
    assert "সফল" in fb_msg
    assert fb_det["verified"] is True
    assert fb_det["platform"] == "facebook"

    # 2. YouTube verification
    yt_ok, yt_msg, yt_det = SocialAuthenticator.verify_youtube(
        channel_id="UC_ProthomAloNews",
        app_id="yt_client_829374.apps.googleusercontent.com",
        app_secret="GOCSPX-secret123",
        access_token="ya29.a0ARrdaM_SAMPLE_OAUTH_TOKEN",
    )
    assert yt_ok is True
    assert "সফল" in yt_msg
    assert yt_det["verified"] is True
    assert yt_det["platform"] == "youtube"

    # 3. TikTok verification
    tt_ok, tt_msg, tt_det = SocialAuthenticator.verify_tiktok(
        page_id_or_username="@ProthomAloNewsDaily",
        client_key="aw_tiktok_client_key",
        client_secret="sec_tiktok_9988",
        access_token="act.tiktok.open.token.sample",
    )
    assert tt_ok is True
    assert "সফল" in tt_msg
    assert tt_det["verified"] is True
    assert tt_det["platform"] == "tiktok"

    # 4. Telegram verification
    tg_ok, tg_msg, tg_det = SocialAuthenticator.verify_telegram(
        chat_id="@ProthomAloInstantWire",
        bot_token="192837465:AAH_SAMPLE_TELEGRAM_BOT_TOKEN",
    )
    assert tg_ok is True
    assert "সফল" in tg_msg
    assert tg_det["verified"] is True
    assert tg_det["platform"] == "telegram"


def test_social_authenticator_missing_credentials():
    """Test that missing required fields produce clear errors."""
    ok, msg, det = SocialAuthenticator.verify_facebook(page_id="", app_id=None, app_secret=None, access_token="")
    assert ok is False
    assert "Page ID এবং Access Token" in msg

    ok, msg, det = SocialAuthenticator.verify_youtube(channel_id="", app_id=None, app_secret=None, access_token="")
    assert ok is False
    assert "Channel ID" in msg

    ok, msg, det = SocialAuthenticator.verify_tiktok(page_id_or_username="", client_key=None, client_secret=None, access_token="")
    assert ok is False
    assert "Username" in msg


def test_api_test_social_connection_ajax(admin_client):
    """Test the AJAX test-connection endpoint called by the modal."""
    res = admin_client.post("/scraper/api/social-channels/test-connection", json={
        "platform": "facebook",
        "page_id_or_channel_id": "fb_page_live_123",
        "app_id": "fb_app_9999",
        "app_secret": "fb_sec_8888",
        "access_token": "EAAK_TEST_LIVE_TOKEN_2026",
        "api_version": "v19.0",
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "সফল" in data["message"]
    assert data["details"]["verified"] is True


def test_save_and_verify_social_channel(admin_client):
    """Test saving a new social channel with OAuth2 credentials and verifying it."""
    res = admin_client.post("/scraper/social-channels/save", data={
        "platform": "youtube",
        "account_name": "Prothom Alo Test YouTube Bulletin",
        "page_id_or_channel_id": "UC_ProthomAloLiveTest",
        "app_id": "yt_client_live.apps.googleusercontent.com",
        "app_secret": "GOCSPX-secretLive",
        "access_token": "ya29.a0ARrdaM_SAMPLE_TOKEN",
        "refresh_token": "1//04live_sample_refresh",
        "api_version": "v3",
        "is_active": "1",
        "is_primary": "1",
        "verify_now": "1",
    }, follow_redirects=True)

    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "Prothom Alo Test YouTube Bulletin" in html
    assert "সংরক্ষিত ও ভেরিফাইড" in html

    # Verify channel in database
    with get_db_session() as session:
        repo = SocialChannelRepository(session)
        ch = session.query(SocialChannelConfig).filter_by(account_name="Prothom Alo Test YouTube Bulletin").first()
        assert ch is not None
        assert ch.platform == "youtube"
        assert ch.status == "HEALTHY"
        assert ch.api_version == "v3"
        assert ch.refresh_token == "1//04live_sample_refresh"

        # Test verification route for this channel
        res_v = admin_client.post(f"/scraper/social-channels/verify-credentials/{ch.id}", follow_redirects=True)
        assert res_v.status_code == 200
        assert "সফল" in res_v.data.decode("utf-8")


def test_safe_secret_preservation_on_edit(admin_client):
    """Test that editing a channel with masked asterisks does not wipe the real secret."""
    with get_db_session() as session:
        repo = SocialChannelRepository(session)
        ch = repo.create_or_update_channel(
            platform="facebook",
            account_name="Secret Preservation Test Page",
            page_id_or_channel_id="fb_page_secret_preservation",
            app_id="app_sec_test",
            app_secret="REAL_TOP_SECRET_STRING_123",
            access_token="REAL_TOP_ACCESS_TOKEN_456",
            refresh_token="REAL_TOP_REFRESH_TOKEN_789",
        )
        ch_id = ch.id
        session.commit()

    # Submit an update with masked values
    res = admin_client.post("/scraper/social-channels/save", data={
        "channel_id": str(ch_id),
        "platform": "facebook",
        "account_name": "Secret Preservation Test Page (Updated)",
        "page_id_or_channel_id": "fb_page_secret_preservation",
        "app_id": "app_sec_test",
        "app_secret": "********",
        "access_token": "REAL_TOP...456",
        "refresh_token": "********",
        "verify_now": "0",
    }, follow_redirects=True)

    assert res.status_code == 200

    with get_db_session() as session:
        repo = SocialChannelRepository(session)
        updated = repo.get_channel_by_id(ch_id)
        assert updated.account_name == "Secret Preservation Test Page (Updated)"
        # Secrets must NOT be replaced by '********' or 'REAL_TOP...456'
        assert updated.app_secret == "REAL_TOP_SECRET_STRING_123"
        assert updated.access_token == "REAL_TOP_ACCESS_TOKEN_456"
        assert updated.refresh_token == "REAL_TOP_REFRESH_TOKEN_789"

        # Cleanup
        repo.delete_channel(ch_id)
        session.commit()


def test_tab_redirects_stay_on_same_tab(admin_client):
    """Test that actions from portals and youtube tabs redirect back to the same tab."""
    res_crawl = admin_client.post("/scraper/trigger", data={"site_key": ""}, follow_redirects=False)
    assert res_crawl.status_code == 302
    assert "tab=portals" in res_crawl.headers["Location"]

    res_social = admin_client.post("/scraper/trigger-social", data={"max_items": 1}, follow_redirects=False)
    assert res_social.status_code == 302
    assert "tab=youtube" in res_social.headers["Location"]
