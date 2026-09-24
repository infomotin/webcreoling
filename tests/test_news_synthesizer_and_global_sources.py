"""
Test Suite for AI News Synthesizer (95% Core Meaning Preservation),
Worldwide Most Popular Newspapers Catalog, and Full Article Reader Views.
"""

import pytest
from src.nlp.news_synthesizer import AINewsSynthesizerAndParaphraser
from src.scraper.social_world_ingestion import WorldNewsMultiLingualIngester, UnifiedSocialAndWorldIngester
from src.automation.ai_pilot_brain import AIPilotBrain
from src.storage.database import get_db_session
from src.storage.models import Article
from src.storage.repositories import ArticleRepository
from src.web.app import create_app


def test_ai_news_synthesizer_factual_retention_and_bangla_generation():
    """Verify that AINewsSynthesizer preserves 95%+ meaning and generates structured Bengali journalism."""
    raw_title = "Federal Reserve announces 0.5% interest rate cut in Washington"
    raw_content = (
        'The Federal Reserve in Washington announced a 0.5% interest rate cut on Wednesday to support the economy. '
        'Chairman stated: "We are confident that inflation is moving sustainably toward 2%." '
        'Stock markets in New York responded positively with major indices gaining 1.5%.'
    )

    synth = AINewsSynthesizerAndParaphraser.process_and_synthesize_news(
        raw_title=raw_title,
        raw_content=raw_content,
        source_name="Reuters Global",
        category="business",
    )

    assert synth is not None
    assert synth["meaning_retention_score"] >= 95.0
    assert "যুক্তরাষ্ট্র" in synth["synthesized_title"] or "ফেডারেল রিজার্ভ" in synth["synthesized_title"] or "সুদের হার" in synth["synthesized_title"]
    assert len(synth["synthesized_body"]) > 300
    assert len(synth["synthesized_body"].split("\n\n")) >= 3  # Multi-paragraph structure
    assert synth["factuality_score"] >= 70.0
    assert synth["is_truth_verified"] is True
    assert synth["status"] == "completed"
    assert len(synth["key_takeaways"]) >= 2


def test_ai_news_synthesizer_truth_gate_threshold():
    """Verify that articles passing 70% truth threshold are marked verified and publishable."""
    raw_title = "United Nations launches climate change summit with 190 countries"
    raw_content = "Delegates from 190 countries gathered in Geneva for the United Nations climate summit to agree on emissions reductions."

    synth = AINewsSynthesizerAndParaphraser.process_and_synthesize_news(
        raw_title=raw_title,
        raw_content=raw_content,
        source_name="United Nations Wire",
        category="international",
    )

    assert synth["factuality_score"] >= 70.0
    assert synth["is_truth_verified"] is True
    assert synth["decision"] == "AUTO_PUBLISH"


def test_world_popular_newspapers_catalog():
    """Verify that top global newspapers are configured with metadata and fetch properly."""
    feeds = WorldNewsMultiLingualIngester.FEEDS
    assert "nytimes_world" in feeds
    assert "washington_post" in feeds
    assert "bbc_world_rss" in feeds
    assert "reuters_wire" in feeds
    assert "bloomberg_markets" in feeds
    assert "guardian_world" in feeds
    assert "aljazeera_rss" in feeds
    assert "cnn_world" in feeds
    assert "forbes_business" in feeds
    assert "dw_bangla_rss" in feeds

    # Test feed fetcher returns well-formed synthesized dictionaries
    items = WorldNewsMultiLingualIngester.fetch_rss_feed("bbc_world_rss", max_items=2)
    assert len(items) > 0
    assert items[0]["source"] is not None
    assert "images" in items[0]


def test_targeted_world_newspaper_ingestion():
    """Verify selective world newspaper ingestion."""
    items = WorldNewsMultiLingualIngester.fetch_all_world_feeds(
        max_per_feed=1,
        feed_keys=["nytimes_world", "bbc_world_rss"],
    )
    assert len(items) >= 1
    assert any(i["extracted_entities"]["feed_key"] in ["nytimes_world", "bbc_world_rss"] for i in items)


def test_ai_pilot_brain_with_synthesizer_and_truth_gate():
    """Verify that AIPilotBrain processes raw items through synthesizer and auto-publishes if >= 70% factuality."""
    raw_item = {
        "url": "https://www.reuters.com/test-article-synth-1",
        "source": "Reuters",
        "title": "Global oil prices drop by 3% amid increased supply",
        "author": "Reuters Energy Desk",
        "category": "business",
        "content_text": "Crude oil prices dropped by 3% on global markets following unexpected inventory surplus in major refining hubs.",
        "images": [{"original_url": "https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?w=800", "is_lead_image": True}],
        "extracted_entities": {"original_lang": "en"},
    }

    processed = AIPilotBrain.process_raw_article(raw_item, auto_publish_threshold=70)
    assert processed["factuality_score"] >= 70.0
    assert processed["meaning_retention_score"] >= 95.0
    assert processed["scrape_status"] == "completed"
    assert processed["ai_decision"] == "AUTO_PUBLISH"
    assert len(processed["content_text"].split("\n\n")) >= 3


def test_article_reader_view_renders_full_details_and_paragraphs():
    """Verify that article reader view at /news/<id> renders full paragraphs, executive summary box, and fact badges."""
    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        # Create a test synthesized article
        with get_db_session() as session:
            repo = ArticleRepository(session)
            art_data = {
                "url": "https://test.com/synth-full-article-176",
                "source": "Al Jazeera English Top News",
                "title": "আন্তর্জাতিক খবর: পাকিস্তান ও আফগানিস্তান বিমান হামলা নিয়ে বিশেষ প্রতিবেদন",
                "author": "আন্তর্জাতিক নিউজ ডেস্ক",
                "category": "international",
                "content_text": "প্রথম অনুচ্ছেদ: ঘটনাটি নিয়ে আন্তর্জাতিক অঙ্গনে বিস্তারিত আলোচনা চলছে।\n\nদ্বিতীয় অনুচ্ছেদ: সংশ্লিষ্ট কর্তৃপক্ষ পরিস্থিতির ওপর গভীর নজর রাখছে।\n\nতৃতীয় অনুচ্ছেদ: কূটনৈতিক মহলে সমঝোতার তাগিদ দেওয়া হয়েছে।",
                "summary": "পাকিস্তান ও আফগানিস্তান সীমান্ত পরিস্থিতি নিয়ে সর্বশেষ অগ্রগতি ও আন্তর্জাতিক প্রতিক্রিয়া।",
                "scrape_status": "completed",
                "extracted_entities": {
                    "news_synthesis": {
                        "meaning_retention_score": 95.5,
                        "factuality_score": 98.0,
                        "is_truth_verified": True,
                        "key_takeaways": ["মূল কেন্দ্রবিন্দু: পাকিস্তান", "ভাবধারা সংরক্ষণ: ৯৫%"],
                    }
                },
            }
            img_records = [{
                "original_url": "https://images.unsplash.com/photo-1526470608268-f674ce90ebd4?w=800",
                "local_path": "https://images.unsplash.com/photo-1526470608268-f674ce90ebd4?w=800",
                "file_hash": "testhash123",
                "file_size_bytes": 10240,
                "mime_type": "image/jpeg",
                "is_lead_image": True,
            }]
            created_art = repo.upsert_article(art_data, img_records)
            test_id = created_art.id

        res = client.get(f"/news/{test_id}")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "সংবাদ এক নজরে" in html
        assert "এআই সত্যতা যাচাই সূচক" in html
        assert "article-lead" in html
        assert "সংশ্লিষ্ট কর্তৃপক্ষ" in html
        assert "কূটনৈতিক মহলে" in html
