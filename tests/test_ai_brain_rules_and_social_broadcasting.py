"""
Integration Tests for AI Brain Custom Rule Engine, Multi-Lingual Targeting,
and Outbound Social Media Auto-Broadcasting (Facebook, YouTube, TikTok, Telegram) with Anti-Ban Failover.
"""

import pytest
from src.web.app import create_app
from src.storage.database import init_db, get_db_session
from src.storage.models import AIBrainCustomRule, SocialChannelConfig, SocialBroadcastLog, Article
from src.storage.repositories import AIBrainRuleRepository, SocialChannelRepository, ArticleRepository
from src.automation.social_broadcaster import (
    FacebookPagePublisher,
    YouTubeWirePublisher,
    TikTokNewsPublisher,
    TelegramChannelPublisher,
    UnifiedSocialBroadcaster,
)
from src.automation.ai_pilot_brain import AIPilotBrain, MultiLingualNewsTranslator, CredibilityAndClickbaitScorer


@pytest.fixture
def client():
    """Flask test client fixture."""
    init_db()
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    with app.test_client() as client:
        yield client


# ==============================================================================
# 1. AI Brain Custom Rule Engine Repository Tests
# ==============================================================================

def test_ai_brain_rule_crud_and_matching():
    """Test creating, updating, toggling, and matching AI Brain custom rules."""
    init_db()
    with get_db_session() as session:
        repo = AIBrainRuleRepository(session)
        
        # 1. Create Custom Rule
        rule = repo.create_or_update_rule(
            name="মিডল ইস্ট ও গ্লোবাল ইকোনমি ফোকাস",
            target_regions=["middle_east", "global"],
            target_countries=["SA", "AE", "QA"],
            target_languages=["en", "ar", "bn"],
            target_categories=["business", "international"],
            required_keywords=["Oil", "Economy", "Saudi"],
            excluded_keywords=["gambling", "casino"],
            min_credibility_score=72.0,
            auto_translate_to_bangla=True,
            auto_publish=True,
            auto_broadcast_social=True,
            custom_prompt_rules="মধ্যপ্রাচ্যের অর্থনৈতিক ও জ্বালানি খবরের ওপর বিশেষ গুরুত্ব প্রদান করুন।",
        )
        assert rule.id is not None
        rule_id = rule.id
        assert rule.min_credibility_score == 72.0

        # 2. Rule Matching Evaluation
        # Positive Match
        match_pass, matched_r, msg = AIPilotBrain.match_custom_rules(
            title="Saudi Arabia Announces Major Green Energy Investment",
            content="Saudi Arabia launched a new oil and green economy framework for the Middle East.",
            source="Reuters Global",
            category="business",
            lang="en",
            rules=[rule],
        )
        assert match_pass is True
        assert matched_r is not None

        # Negative Match due to excluded keyword
        match_fail_excl, _, _ = AIPilotBrain.match_custom_rules(
            title="Online Casino and Gambling in Middle East",
            content="A report on illegal gambling activities.",
            source="Random Wire",
            category="business",
            lang="en",
            rules=[rule],
        )
        assert match_fail_excl is False

        # 3. Toggle Rule
        state = repo.toggle_rule(rule_id)
        assert state is False
        state_on = repo.toggle_rule(rule_id)
        assert state_on is True

        # 4. Delete Rule
        assert repo.delete_rule(rule_id) is True
        assert repo.get_rule_by_id(rule_id) is None


# ==============================================================================
# 2. Social Media Outbound Channel Repository & Failover Tests
# ==============================================================================

def test_social_channel_management_and_anti_ban_failover():
    """Test channel configuration, failover switching upon simulated page ban, and broadcast logging."""
    init_db()
    with get_db_session() as session:
        repo = SocialChannelRepository(session)
        
        # 1. Create Backup Channel
        backup_ch = repo.create_or_update_channel(
            platform="facebook",
            account_name="দৈনিক সংবাদ ব্যাকআপ পেজ",
            page_id_or_channel_id="998877665544",
            access_token="EAAK_BACKUP_TEST_TOKEN",
            is_active=True,
            is_primary=False,
        )
        backup_id = backup_ch.id

        # 2. Create Primary Channel with failover pointer
        primary_ch = repo.create_or_update_channel(
            platform="facebook",
            account_name="প্রথম আলো প্রাইমারি ফেসবুক পেজ",
            page_id_or_channel_id="112233445566",
            access_token="EAAK_PRIMARY_TEST_TOKEN",
            is_active=True,
            is_primary=True,
            failover_account_id=backup_id,
        )
        primary_id = primary_ch.id
        assert primary_ch.status == "HEALTHY"

        # 3. Simulate FB Page Ban / Token Restriction
        failover_activated = repo.mark_channel_restricted(
            channel_id=primary_id,
            error_message="(#368) The action attempted has been deemed abusive or restricted.",
        )
        assert failover_activated is not None
        assert failover_activated.id == backup_id
        assert failover_activated.status == "BACKUP_ACTIVE"

        # Check primary is marked restricted
        prim = repo.get_channel_by_id(primary_id)
        assert prim.status == "RESTRICTED"

        # 4. Broadcast Logging
        log = repo.log_broadcast(
            article_id=1,
            channel_id=backup_id,
            platform="facebook",
            target_account=backup_ch.account_name,
            post_payload={"title": "ব্রেকিং নিউজ টেস্ট"},
            external_post_id="998877665544_12345",
            dispatch_status="FALLBACK_SWITCHED",
        )
        assert log.id is not None
        assert log.dispatch_status == "FALLBACK_SWITCHED"

        # Cleanup
        repo.delete_channel(primary_id)
        repo.delete_channel(backup_id)


# ==============================================================================
# 3. Social Media Formatter & Dispatcher Tests (FB, YT, TikTok, Telegram)
# ==============================================================================

def test_social_media_publishers():
    """Test payload builders and mock/simulated dispatchers for all social channels."""
    sample_article = {
        "id": 101,
        "title": "বাংলাদেশ ও বিশ্বব্যাংকের মধ্যে নতুন অর্থায়ন চুক্তি সই",
        "summary": "অর্থনৈতিক প্রবৃদ্ধি ও ডিজিটাল রূপান্তরের জন্য ৫০ কোটি ডলারের ঋণ চুক্তি স্বাক্ষরিত হয়েছে।",
        "category": "business",
    }

    # 1. Facebook Page Publisher
    fb_data = FacebookPagePublisher.format_post_message(sample_article, base_url="http://127.0.0.1:8080")
    assert "🔴" in fb_data["message"]
    assert "http://127.0.0.1:8080/news/101" in fb_data["message"]
    assert "#বাণিজ্য" in fb_data["message"]

    fb_success, fb_msg, fb_res = FacebookPagePublisher.publish_to_page(
        page_id="1092837465",
        access_token="EAAK_SAMPLE_TOKEN",
        post_data=fb_data,
        is_simulation=True,
    )
    assert fb_success is True
    assert "id" in fb_res

    # 2. YouTube Community Wire Publisher
    yt_data = YouTubeWirePublisher.format_community_wire(sample_article, base_url="http://127.0.0.1:8080")
    assert "📢" in yt_data["community_post_text"]
    assert "shorts_caption" in yt_data

    # 3. TikTok News Insight Publisher
    tiktok_data = TikTokNewsPublisher.format_tiktok_script(sample_article)
    assert "hook_text" in tiktok_data
    assert "body_teleprompter" in tiktok_data
    assert "#TikTokNews" in tiktok_data["caption"]

    # 4. Telegram Channel Publisher
    tg_success, tg_msg, tg_res = TelegramChannelPublisher.publish_to_channel(
        bot_token="SAMPLE_BOT_TOKEN",
        chat_id="@ProthomAloNews",
        article=sample_article,
    )
    assert tg_success is True


# ==============================================================================
# 4. End-to-End AI Pilot Ingestion -> Rule Match -> Publish -> Social Sync
# ==============================================================================

def test_full_ai_pilot_brain_with_rules_and_social_sync():
    """Test full cycle: raw news -> translation -> custom rule matching -> auto-publish -> social broadcast."""
    init_db()
    
    raw_foreign_news = {
        "url": "https://reuters.com/tech/ai-innovation-chip-2026",
        "source": "Reuters Global Technology",
        "title": "Global Semiconductor Alliance Launches Next-Gen AI Superchip",
        "content_text": "Tech leaders gathered in Washington to unveil a groundbreaking AI chip with 5x speed and efficiency. Prime minister and industry chiefs praised the advancement.",
        "author": "Tech Wire Bureau",
        "category": "technology",
        "extracted_entities": {"original_lang": "en"},
    }

    # Process through AI Brain
    processed = AIPilotBrain.process_raw_article(
        raw_article=raw_foreign_news,
        auto_publish_threshold=65,
    )

    # 1. Verify Translation to Bengali
    assert MultiLingualNewsTranslator.has_bangla_content(processed["title"])
    assert MultiLingualNewsTranslator.has_bangla_content(processed["content_text"])

    # 2. Verify Rule Matching & Decision
    assert processed["ai_decision"] in ["AUTO_PUBLISH", "QUEUE_FOR_REVIEW"]
    assert processed["credibility_score"] >= 65

    # 3. Verify Social Broadcasting Dispatch Execution
    with get_db_session() as session:
        repo = ArticleRepository(session)
        art = repo.upsert_article(
            article_data={
                "url": processed["url"],
                "source": processed["source"],
                "title": processed["title"],
                "author": processed["author"],
                "published_at": processed["published_at"],
                "category": processed["category"],
                "content_text": processed["content_text"],
                "summary": processed["summary"],
                "scrape_status": "completed",
            }
        )
        art_dict = art.to_dict()

    broadcast_report = UnifiedSocialBroadcaster.broadcast_article(art_dict)
    assert broadcast_report["total_channels"] >= 1
    assert broadcast_report["dispatched_count"] >= 1


# ==============================================================================
# 5. Web Routes & Scraper Dashboard Endpoint Tests
# ==============================================================================

def test_web_routes_for_rules_and_social_channels(client):
    """Test HTTP endpoints for saving AI rules and configuring social accounts."""
    # Login as Admin
    client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=True,
    )

    # 1. Scraper Dashboard View
    res_dash = client.get("/scraper")
    assert res_dash.status_code == 200
    assert "এআই রুল ইঞ্জিন".encode("utf-8") in res_dash.data or b"Brain Rules" in res_dash.data

    # 2. Save Custom AI Rule via Form
    res_save_rule = client.post(
        "/scraper/rules/save",
        data={
            "name": "স্পেশাল খেলাধুলা ও ক্রিকেট রুল",
            "target_regions": ["bangladesh", "south_asia"],
            "target_countries": "BD, IN",
            "target_languages": ["bn", "en"],
            "target_categories": ["sports"],
            "required_keywords": "cricket, match",
            "min_credibility_score": "70",
            "auto_translate_to_bangla": "1",
            "auto_publish": "1",
            "auto_broadcast_social": "1",
        },
        follow_redirects=True,
    )
    assert res_save_rule.status_code == 200

    # 3. Save Social Channel via Form
    res_save_social = client.post(
        "/scraper/social-channels/save",
        data={
            "platform": "facebook",
            "account_name": "প্রথম আলো স্পোর্টস লাইভ পেজ",
            "page_id_or_channel_id": "9911223344",
            "app_id": "fb_app_123",
            "access_token": "EAAK_SAMPLE_SPORTS_TOKEN",
            "is_active": "1",
            "is_primary": "1",
        },
        follow_redirects=True,
    )
    assert res_save_social.status_code == 200

    # 4. JSON API Broadcast Logs
    res_logs = client.get("/scraper/api/broadcast-logs")
    assert res_logs.status_code == 200
    data = res_logs.get_json()
    assert isinstance(data, list)


def test_ai_brain_rule_verification_diagnostics():
    """Test AI Brain diagnostic simulator verification engine with country codes, regions, keywords, and credibility."""
    init_db()
    with get_db_session() as session:
        repo = AIBrainRuleRepository(session)
        # Create dedicated test rule
        test_rule = repo.create_or_update_rule(
            name="ইউএস ও ইউরোপ টেকনোলজি পলিসি রুল",
            target_regions=["usa", "europe"],
            target_countries=["US", "UK", "DE"],
            target_languages=["en", "bn"],
            target_categories=["technology", "business"],
            required_keywords=["chip", "semiconductor"],
            excluded_keywords=["phishing", "scam"],
            min_credibility_score=70.0,
            auto_translate_to_bangla=True,
            auto_publish=True,
            auto_broadcast_social=True,
        )

        # 1. Test Positive Diagnostic Verification
        diag_pass = AIPilotBrain.verify_article_against_rules(
            sample_title="US and UK Semiconductor Alliance announces next-gen quantum chip",
            sample_content="Government officials in Washington and London confirmed major investments into quantum computing and chip fabrication.",
            sample_source="Tech Wire Direct",
            sample_category="technology",
            sample_country_code="US",
            sample_language="en",
            rules=[test_rule],
        )
        assert diag_pass["overall_match"] is True
        assert diag_pass["matched_rule_name"] == test_rule.name
        assert diag_pass["decision"] in ["AUTO_PUBLISH", "QUEUE_FOR_REVIEW"]
        assert len(diag_pass["synthesized_title"]) > 5
        assert len(diag_pass["synthesized_body"]) > 20

        # 2. Test Negative Verification due to Excluded Keyword
        diag_fail_excl = AIPilotBrain.verify_article_against_rules(
            sample_title="Semiconductor scam and phishing alert in technology sector",
            sample_content="Authorities warned of a phishing scam involving fake chip manufacturing stocks in the US.",
            sample_source="Tech Wire Direct",
            sample_category="technology",
            sample_country_code="US",
            sample_language="en",
            rules=[test_rule],
        )
        assert diag_fail_excl["overall_match"] is False
        assert diag_fail_excl["decision"] == "REJECTED_RULE_MISMATCH"

        # 3. Test Negative Verification due to Unmatched Country Code / Region
        diag_fail_region = AIPilotBrain.verify_article_against_rules(
            sample_title="Local agricultural production in South America",
            sample_content="Farming yields improved across the countryside.",
            sample_source="Farming News",
            sample_category="agriculture",
            sample_country_code="BR",
            sample_language="en",
            rules=[test_rule],
        )
        assert diag_fail_region["overall_match"] is False


def test_social_channel_failover_simulation_endpoint(client):
    """Test HTTP endpoint for Anti-Ban Failover Simulation and verify backup dispatch & logs."""
    init_db()
    with get_db_session() as session:
        repo = SocialChannelRepository(session)
        # Create backup and primary channel
        backup = repo.create_or_update_channel(
            platform="facebook",
            account_name="অটোমেটেড ব্যাকআপ পেজ (পরীক্ষামূলক)",
            page_id_or_channel_id="bk_page_999111",
            access_token="EAAK_BACKUP_TOKEN_123",
            is_active=True,
            is_primary=False,
        )
        primary = repo.create_or_update_channel(
            platform="facebook",
            account_name="প্রধান ফেসবুক পেজ (পরীক্ষামূলক)",
            page_id_or_channel_id="prim_page_111999",
            access_token="EAAK_PRIMARY_TOKEN_123",
            is_active=True,
            is_primary=True,
            failover_account_id=backup.id,
        )
        primary_id = primary.id
        backup_id = backup.id

    # Login as Admin
    client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=True,
    )

    # Trigger Failover Simulation
    res_failover = client.post(
        f"/scraper/social-channels/test-failover/{primary_id}",
        follow_redirects=True,
    )
    assert res_failover.status_code == 200

    # Verify status in database
    with get_db_session() as session:
        repo = SocialChannelRepository(session)
        prim_updated = repo.get_channel_by_id(primary_id)
        bk_updated = repo.get_channel_by_id(backup_id)
        assert prim_updated.status == "RESTRICTED"
        assert bk_updated.status == "BACKUP_ACTIVE"

        # Verify broadcast log entry
        logs = repo.get_broadcast_logs(limit=5)
        fallback_log = next((l for l in logs if l.dispatch_status == "FALLBACK_SWITCHED"), None)
        assert fallback_log is not None
        assert fallback_log.channel_id == backup_id

    # Test Reset Status Endpoint
    res_reset = client.post(
        f"/scraper/social-channels/reset-status/{primary_id}",
        follow_redirects=True,
    )
    assert res_reset.status_code == 200

    with get_db_session() as session:
        repo = SocialChannelRepository(session)
        prim_reset = repo.get_channel_by_id(primary_id)
        assert prim_reset.status == "HEALTHY"


def test_rule_json_retrieval_and_api_verify(client):
    """Test AJAX JSON routes for fetching rule configs and live diagnostic verification."""
    # Login as Admin
    client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=True,
    )

    # 1. Fetch first rule JSON
    with get_db_session() as session:
        repo = AIBrainRuleRepository(session)
        rules = repo.get_all_rules()
        rule_id = rules[0].id if rules else None

    if rule_id:
        res_get = client.get(f"/scraper/rules/get/{rule_id}")
        assert res_get.status_code == 200
        rule_data = res_get.get_json()
        assert "name" in rule_data
        assert "target_regions" in rule_data

    # 2. Post to Live Rule Verification API
    res_verify = client.post(
        "/scraper/api/verify-rule",
        json={
            "title": "Bangladesh economy surges with $10 billion export milestone",
            "content": "Official reports from Dhaka confirm rapid growth in technological and manufacturing exports across global markets.",
            "source": "Financial Express",
            "category": "business",
            "country_code": "BD",
            "language": "en",
        },
    )
    assert res_verify.status_code == 200
    diag = res_verify.get_json()
    assert "overall_match" in diag
    assert "factuality_score" in diag
    assert "synthesized_title" in diag
    assert "decision" in diag

