"""
Comprehensive Unit and Integration Tests for Custom News Portal Ingestion,
100% Original AI Journalistic Paraphrasing & Direct Live Portal Publishing.
"""

import pytest
from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup
from src.scraper.custom_portal_ingester import CustomPortalIngester
from src.storage.database import get_db_session
from src.storage.models import Article, User
from src.storage.repositories import ArticleRepository, UserRepository
from src.web.app import create_app


@pytest.fixture
def sample_news_html():
    return """
    <!DOCTYPE html>
    <html lang="bn">
    <head>
        <title>ঢাকায় মেট্রো রেলের নতুন রুট উদ্বোধন করলেন প্রধানমন্ত্রী - প্রথম আলো</title>
        <meta property="og:title" content="ঢাকায় মেট্রো রেলের নতুন রুট উদ্বোধন করলেন প্রধানমন্ত্রী">
        <meta property="og:description" content="রাজধানী ঢাকায় মেট্রো রেলের মতিঝিল থেকে কমলাপুর বর্ধিত অংশের পরীক্ষামূলক চলাচল শুরু হয়েছে।">
        <meta property="og:image" content="https://images.prothomalo.com/metro-rail.jpg">
        <meta property="article:published_time" content="2026-09-24T10:30:00Z">
        <meta name="author" content="স্টাফ রিপোর্টার">
    </head>
    <body>
        <header><h1>দৈনিক সংবাদ পোর্টাল</h1></header>
        <article class="story-content">
            <h1 class="article-title">ঢাকায় মেট্রো রেলের নতুন রুট উদ্বোধন করলেন প্রধানমন্ত্রী</h1>
            <p>রাজধানী ঢাকায় মেট্রো রেলের মতিঝিল থেকে কমলাপুর বর্ধিত অংশের পরীক্ষামূলক চলাচল শুরু হয়েছে। আজ বৃহস্পতিবার সকালে আনুষ্ঠানিকভাবে এই কার্যক্রমের শুভ উদ্বোধন ঘোষণা করা হয়।</p>
            <p>উদ্বোধনী অনুষ্ঠানে সড়ক পরিবহন মন্ত্রী জানান, “এই রুটের মাধ্যমে প্রতিদিন অতিরিক্ত ৫ লাখ যাত্রী দ্রুত ও স্বাচ্ছন্দ্যে যাতায়াত করতে পারবেন।” তিনি আরও উল্লেখ করেন যে ২০২৬ সালের ডিসেম্বরের মধ্যেই পুরো প্রকল্পটির পূর্ণাঙ্গ বাণিজ্যিক কার্যক্রম শুরু হবে।</p>
            <p>অনুষ্ঠানে বিশ্বব্যাংক ও জাইকার প্রতিনিধিরা উপস্থিত ছিলেন। পুরো প্রকল্পটিতে মোট ব্যয় হয়েছে প্রায় ৩৩ হাজার কোটি টাকা। এতে নগরবাসীর যাতায়াত সময় অন্তত ৪০ শতাংশ কমে আসবে বলে জরিপে উঠে এসেছে।</p>
            <p>নাগরিকরা এই নতুন উদ্যোগকে স্বাগত জানিয়েছেন এবং নগরীর যানজট নিরসনে এটি বৈপ্লবিক ভূমিকা রাখবে বলে আশা প্রকাশ করেছেন।</p>
        </article>
    </body>
    </html>
    """


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key-123"

    with app.test_client() as test_client:
        with app.app_context():
            # Seed test admin user for authenticated tests
            with get_db_session() as session:
                user_repo = UserRepository(session)
                admin = user_repo.get_by_username("admin_test_tester")
                if not admin:
                    admin = user_repo.create_user(
                        username="admin_test_tester",
                        email="admin_test_tester@example.com",
                        password="password123",
                        role="admin",
                    )
        # Login test client
        with test_client.session_transaction() as sess:
            sess["user_id"] = admin.id
            sess["username"] = admin.username
            sess["role"] = admin.role

        yield test_client


def test_extract_raw_page_data(sample_news_html):
    """Test universal extractor correctly pulls title, body, author, and lead image."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = sample_news_html

    with patch("requests.get", return_value=mock_resp):
        extracted = CustomPortalIngester.extract_raw_page_data("https://www.prothomalo.com/bangladesh/metro-news")

        assert "মেট্রো রেলের নতুন রুট" in extracted["raw_title"]
        assert "মতিঝিল থেকে কমলাপুর" in extracted["raw_content"]
        assert extracted["lead_image_url"] == "https://images.prothomalo.com/metro-rail.jpg"
        assert extracted["author"] == "স্টাফ রিপোর্টার"
        assert extracted["char_count"] > 100


def test_scrape_and_synthesize_100_percent_original_news(sample_news_html):
    """Test full pipeline: scraping + 100% original copy synthesis + live portal posting."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = sample_news_html

    with patch("requests.get", return_value=mock_resp):
        result = CustomPortalIngester.scrape_and_synthesize_original_news(
            url="https://www.prothomalo.com/bangladesh/metro-rail-extension",
            source_name="প্রথম আলো ডিজিটাল ডেস্ক",
            category="bangladesh",
            target_placement="LEAD",
            publish_now=True,
            originality_mode="100_percent_unique",
        )

        assert result["success"] is True
        assert result["article_id"] > 0
        assert result["is_live_published"] is True
        assert result["scrape_status"] == "completed"
        assert result["originality_score"] >= 95.0
        assert result["factuality_score"] >= 70.0
        assert result["position_placement"] == "LEAD"
        assert len(result["synthesized_title"]) > 10
        assert len(result["synthesized_body"]) > 100
        assert len(result["executive_summary"]) > 20
        assert "/news/article/" in result["portal_article_url"]

        # Verify in SQLite DB
        with get_db_session() as session:
            repo = ArticleRepository(session)
            art = repo.get_by_id(result["article_id"])
            assert art is not None
            assert art.title == result["synthesized_title"]
            assert art.position_placement == "LEAD"
            assert art.scrape_status == "completed"
            assert art.creation_origin == "AI_SYNTHESIZED"
            assert art.original_source_url == "https://www.prothomalo.com/bangladesh/metro-rail-extension"
            assert art.is_ledger_verified is True


def test_publish_draft_article():
    """Test transitioning a draft article to live publication on the portal."""
    with get_db_session() as session:
        repo = ArticleRepository(session)
        draft = repo.create_editorial_article(
            title="পরীক্ষামূলক ড্রাফট সংবাদ",
            content_text="এটি একটি ড্রাফট সংবাদ যা পরে লাইভ প্রকাশ করা হবে।",
            summary="ড্রাফট সারসংক্ষেপ",
            category="technology",
            status="pending",
        )
        draft_id = draft.id

    res = CustomPortalIngester.publish_article_to_portal(
        article_id=draft_id,
        position_placement="BREAKING",
        is_breaking=True,
    )

    assert res["success"] is True
    assert res["status"] == "completed"

    with get_db_session() as session:
        repo = ArticleRepository(session)
        updated = repo.get_by_id(draft_id)
        assert updated.scrape_status == "completed"
        assert updated.position_placement == "BREAKING"
        assert updated.is_breaking is True


def test_web_route_custom_scrape_post(client, sample_news_html):
    """Test form POST /scraper/custom-scrape-post redirects with flash message."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = sample_news_html

    with patch("requests.get", return_value=mock_resp):
        resp = client.post(
            "/scraper/custom-scrape-post",
            data={
                "url": "https://www.thedailystar.net/news/bangladesh/sample-post",
                "source_name": "The Daily Star Wire",
                "category": "business",
                "target_placement": "FEATURED",
                "publish_now": "1",
            },
            follow_redirects=True,
        )

        assert resp.status_code == 200
        assert "সফল!" in resp.get_data(as_text=True) or "১০০% অরিজিনাল" in resp.get_data(as_text=True)


def test_api_custom_portal_scrape_and_publish(client, sample_news_html):
    """Test JSON AJAX endpoint /scraper/api/custom-portal/scrape-and-publish."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = sample_news_html

    with patch("requests.get", return_value=mock_resp):
        resp = client.post(
            "/scraper/api/custom-portal/scrape-and-publish",
            json={
                "url": "https://www.bbc.com/bengali/news-12345",
                "source_name": "BBC Bengali Wire",
                "category": "international",
                "target_placement": "STANDARD",
                "publish_now": True,
            },
        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["article_id"] > 0
        assert data["originality_score"] >= 95.0
        assert data["is_live_published"] is True
        assert data["portal_article_url"].startswith("/news/article/")


def test_api_recent_custom_ingested(client):
    """Test JSON endpoint /scraper/api/custom-portal/recent-ingested."""
    resp = client.get("/scraper/api/custom-portal/recent-ingested?limit=5")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert isinstance(data["articles"], list)
