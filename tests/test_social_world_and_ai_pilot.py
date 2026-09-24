"""
Unit & Integration Tests for Social Media Ingestion, World Multi-Lingual Feeds, and AI Pilot Brain.
"""

import pytest
from src.scraper.social_world_ingestion import (
    YouTubePublicNewsIngester,
    WorldNewsMultiLingualIngester,
    FacebookPublicNewsIngester,
    UnifiedSocialAndWorldIngester,
)
from src.automation.ai_pilot_brain import (
    MultiLingualNewsTranslator,
    CredibilityAndClickbaitScorer,
    NewsNLPSkillEngine,
    AIPilotBrain,
)
from src.web.app import create_app
from src.storage.database import init_db, get_db_session
from src.storage.repositories import ArticleRepository, BlockchainLedgerRepository


@pytest.fixture
def client():
    """Flask test client fixture."""
    init_db()
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    with app.test_client() as client:
        yield client


def test_youtube_public_ingester():
    """Test YouTube public feed fetching and structure."""
    items = YouTubePublicNewsIngester.fetch_channel_feed("UC_wO4f7i_G_u89W1wP0qYsw", max_items=2)
    assert len(items) > 0
    first = items[0]
    assert "url" in first
    assert "title" in first
    assert len(first["title"]) > 0
    assert first["extracted_entities"]["platform"] == "youtube"


def test_world_news_multilingual_ingester():
    """Test world news RSS ingestion."""
    items = WorldNewsMultiLingualIngester.fetch_rss_feed("google_news_bangla", max_items=2)
    assert len(items) > 0
    first = items[0]
    assert "url" in first
    assert "title" in first
    assert "content_text" in first


def test_facebook_social_briefs_ingester():
    """Test public Facebook social news wire briefs."""
    items = FacebookPublicNewsIngester.fetch_public_social_briefs(limit=2)
    assert len(items) > 0
    first = items[0]
    assert first["extracted_entities"]["platform"] == "facebook"
    assert len(first["content_text"]) > 20


def test_multilingual_translator():
    """Test translating and localizing English/foreign headlines into natural Bangla."""
    en_title = "The Government announced new Artificial Intelligence policy for national security"
    en_content = "President and Prime Minister held a summit regarding economy and inflation."

    bn_title, bn_content = MultiLingualNewsTranslator.translate_and_localize_to_bangla(
        title=en_title,
        content=en_content,
        source_lang="en",
    )

    assert "সরকার" in bn_title or "এআই" in bn_title or "আন্তর্জাতিক" in bn_title
    assert "অর্থনীতি" in bn_content or "আন্তর্জাতিক" in bn_content


def test_credibility_and_clickbait_scoring():
    """Test credibility evaluator scoring legitimate vs clickbait stories."""
    # 1. High credibility story
    legit_eval = CredibilityAndClickbaitScorer.evaluate_article(
        title="জাতীয় অর্থনৈতিক পরিষদের নির্বাহী কমিটি সভায় নতুন উন্নয়ন প্রকল্প অনুমোদন",
        content="রাজধানীর শেরেবাংলা নগরে একনেক বৈঠকে মোট দশটি নতুন মেগা প্রকল্পের চূড়ান্ত অনুমোদন দেওয়া হয়েছে। বৈঠকে সভাপতিত্ব করেন দায়িত্বপ্রাপ্ত উপদেষ্টা। সংশ্লিষ্ট কর্মকর্তারা জানিয়েছেন, এতে দেশের অবকাঠামো উন্নয়ন ত্বরান্বিত হবে।",
        source="Prothom Alo",
    )
    assert legit_eval["credibility_score"] >= 75
    assert legit_eval["recommendation"] == "AUTO_PUBLISH"

    # 2. Clickbait story
    clickbait_eval = CredibilityAndClickbaitScorer.evaluate_article(
        title="OMG দেখলে চমকে যাবেন!!! ভাইরাল ভিডিওতে অবিশ্বাস্য ঘটনা ফাঁস?!",
        content="অল্প একটু লেখা।",
        source="Unknown Viral Blog",
    )
    assert clickbait_eval["credibility_score"] < 60
    assert clickbait_eval["recommendation"] in ["QUEUE_FOR_REVIEW", "REJECT"]


def test_nlp_skill_engine_categorization_and_summary():
    """Test category classification, summary synthesis, and entity extraction."""
    title = "বিসিবি সভাপতি জানিয়েছেন আসন্ন বিশ্বকাপের দল ঘোষণা আগামী সপ্তাহে"
    content = "মিরপুরে এক সংবাদ সম্মেলনে বাংলাদেশ ক্রিকেট দলের অগ্রগতি ও খেলোয়াড়দের ফর্ম নিয়ে কথা বলেন তিনি। ঢাকা স্টেডিয়ামে প্রস্তুতি ক্যাম্প চলবে।"

    cat = NewsNLPSkillEngine.classify_category(title=title, content=content)
    assert cat == "sports"

    summary = NewsNLPSkillEngine.generate_summary(title=title, content=content)
    assert len(summary) > 10

    entities = NewsNLPSkillEngine.extract_entities(content=content)
    assert "ঢাকা" in entities["Location"] or "বাংলাদেশ" in entities["Location"]


def test_ai_pilot_brain_full_cycle():
    """Test AI Pilot Brain processing, DB persistence, and blockchain auto-sealing."""
    sample_raw = {
        "url": "https://test-news-wire.org/ai-pilot-test-story-unique-12345",
        "source": "Prothom Alo Live Wire",
        "title": "আন্তর্জাতিক বাজারে জ্বালানি তেলের দাম হ্রাস পাওয়ায় স্বস্তি",
        "content_text": "বিশ্ববাজারে অপরিশোধিত জ্বালানি তেলের মূল্য কিছুটা হ্রাস পেয়েছে। অর্থনৈতিক বিশ্লেষকরা জানিয়েছেন, এর ফলে বৈশ্বিক মূল্যস্ফীতি নিয়ন্ত্রণে ইতিবাচক প্রভাব পড়বে। বিভিন্ন দেশ ইতোমধ্যে নতুন জ্বালানি নীতিমালা প্রণয়ন করেছে।",
        "category": "business",
        "images": [
            {
                "original_url": "https://images.unsplash.com/photo-1526304640581-d334cdbbf45e?w=800",
                "caption": "জ্বালানি বাজার চিত্র",
                "is_lead_image": True,
            }
        ],
        "extracted_entities": {"platform": "test_wire"},
    }

    processed = AIPilotBrain.process_raw_article(sample_raw, auto_publish_threshold=70)
    assert processed["ai_decision"] == "AUTO_PUBLISH"
    assert processed["scrape_status"] == "completed"
    assert processed["credibility_score"] >= 70

    # Save and verify blockchain minting
    with get_db_session() as session:
        repo = ArticleRepository(session)
        ledger_repo = BlockchainLedgerRepository(session)

        art_data = {k: v for k, v in processed.items() if k not in ["images", "ai_decision", "credibility_score", "eval_result"]}
        art = repo.upsert_article(article_data=art_data)
        block = ledger_repo.mint_block_for_article(art.id)

        assert block is not None
        assert block.block_hash is not None
        assert art.is_ledger_verified == True


def test_scraper_web_endpoints(client):
    """Test Scraper UI routes, trigger forms, and status API."""
    # Login as Editor
    client.post(
        "/auth/login",
        data={"username": "editor", "password": "editor123"},
        follow_redirects=True,
    )

    # Scraper hub page
    res_page = client.get("/scraper")
    assert res_page.status_code == 200
    assert "AI Scraper".encode("utf-8") in res_page.data or b"Scraper" in res_page.data

    # Scraper status JSON API
    res_api = client.get("/scraper/api/status")
    assert res_api.status_code == 200
    data = res_api.get_json()
    assert data["status"] == "online"
    assert "stats" in data
    assert "tasks" in data
