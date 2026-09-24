"""
Unit and Integration Tests for:
1. Original Source Attribution and Verification (original_source_url, source_status)
2. Source News Removed / Deleted Notice Banner on Article Reader View
3. Zero Image Errors and Fallback Vector Placeholders (lead_image_url, /media/placeholders/<category>.svg)
4. Manual Creation vs AI Synthesized / Scraped Origin Indicators (creation_origin)
5. Portal Layout Placement, Sequence Order, and Pinning Control (position_placement, display_order, is_pinned)
"""

import pytest
from src.web.app import create_app
from src.storage.database import init_db, get_db_session
from src.storage.models import Article
from src.storage.repositories import ArticleRepository, PortalRepository, UserRepository
from src.common.normalizer import BanglaTextNormalizer


@pytest.fixture
def client():
    init_db()
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    with app.test_client() as client:
        yield client


def test_article_source_provenance_and_removed_notice():
    """Verify storing original source metadata, removed-at-source status, and notice handling."""
    init_db()
    with get_db_session() as session:
        repo = ArticleRepository(session)
        
        # 1. Create Article with Active Original Source
        art = repo.create_editorial_article(
            title="বিশ্বব্যাংকের নতুন বৈশ্বিক টেকসই প্রযুক্তি প্রতিবেদন ২০২৬",
            content_text="বিশ্বজুড়ে টেকসই প্রযুক্তির ব্যবহার ও অর্থায়ন নিয়ে এক যুগান্তকারী প্রতিবেদন প্রকাশ করেছে বিশ্বব্যাংক।\n\nপ্রতিবেদনে উল্লেখ করা হয় উদীয়মান অর্থনীতির দেশসমূহ দ্রুত গতিতে কৃত্রিম বুদ্ধিমত্তা ও নবায়নযোগ্য শক্তি গ্রহণ করছে।",
            summary="বিশ্বব্যাংকের ২০২৬ সালের বৈশ্বিক টেকসই প্রযুক্তি সংক্রান্ত বিস্তারিত পর্যবেক্ষণ প্রতিবেদন।",
            category="business",
            author="দি ডেইলি এআই আলো সংবাদ ডেস্ক",
            source="World Bank Global Wire",
            original_source_url="https://worldbank.org/reports/sustainable-tech-2026",
            source_status="ACTIVE",
            creation_origin="AI_SYNTHESIZED",
            position_placement="FEATURED",
            display_order=2,
            is_pinned=False,
            is_featured=True,
            status="completed",
        )
        assert art.id is not None
        art_id = art.id
        assert art.original_source_url == "https://worldbank.org/reports/sustainable-tech-2026"
        assert art.source_status == "ACTIVE"
        assert art.creation_origin == "AI_SYNTHESIZED"
        assert art.position_placement == "FEATURED"
        assert art.display_order == 2

        # 2. Simulate Source Removal / Unpublishing and Notice Update
        updated_art = repo.update_editorial_article(
            article_id=art_id,
            source_status="REMOVED_AT_SOURCE",
            source_removed_notice="মূল প্রকাশকের ওয়েবসাইট থেকে এই সংবাদটি সরিয়ে নেওয়া হয়েছে। পাঠকদের সুবিধার্থে 'দি ডেইলি এআই আলো' আর্কাইভে এই কপি সংরক্ষিত রয়েছে।",
        )
        assert updated_art is not None
        assert updated_art.source_status == "REMOVED_AT_SOURCE"
        assert "সরিয়ে নেওয়া হয়েছে" in updated_art.source_removed_notice


def test_zero_image_errors_and_fallback_properties():
    """Verify lead_image_url property fallback logic and placeholder endpoints."""
    init_db()
    with get_db_session() as session:
        # Article with no image - should return category-based SVG placeholder
        no_img_article = Article(
            title="রাজনীতির নতুন প্রেক্ষাপট ও নির্বাচন সংস্কার",
            content_text="নির্বাচন কমিশন নতুন কাঠামোগত প্রস্তাব পেশ করেছে।",
            category="politics",
            source="Daily News",
        )
        lead_url = no_img_article.lead_image_url
        assert "politics.svg" in lead_url or "/static/img/placeholders/" in lead_url

        # Technology category fallback
        tech_article = Article(
            title="নতুন এআই মডেল উদ্বোধন",
            content_text="ওপেনএআই নতুন এআই গবেষণা প্রকাশ করেছে।",
            category="technology",
            source="Tech Wire",
        )
        assert "technology.svg" in tech_article.lead_image_url


def test_portal_placement_order_and_pinning():
    """Verify LEAD, BREAKING, FEATURED, CATEGORY_TOP placement and display_order sorting."""
    init_db()
    with get_db_session() as session:
        repo = ArticleRepository(session)
        portal_repo = PortalRepository(session)

        # Create 3 articles with distinct placements and orders
        lead_art = repo.create_editorial_article(
            title="প্রধান শিরোনাম: ২০২৬ সালের নতুন অর্থনৈতিক বাজেট ঘোষণা",
            content_text="জাতীয় সংসদে নতুন অর্থবছরের বাজেট পেশ করা হয়েছে। অর্থনৈতিক সমৃদ্ধি অর্জনে বিশেষ বরাদ্দের ঘোষণা।",
            summary="জাতীয় সংসদে নতুন অর্থবছরের বাজেট পেশ।",
            category="business",
            author="বিশেষ প্রতিবেদক",
            position_placement="LEAD",
            display_order=1,
            is_pinned=True,
            status="completed",
        )

        featured_art = repo.create_editorial_article(
            title="বিশেষ ফিচার: কৃত্রিম বুদ্ধিমত্তার ভবিষ্যৎ দিগন্ত",
            content_text="বিশ্বজুড়ে প্রযুক্তিবিদরা পরবর্তী প্রজন্মের সুপারইন্টেলিজেন্স নিয়ে গবেষণা জোরদার করেছেন।",
            summary="সুপারইন্টেলিজেন্স নিয়ে গবেষণা পর্যালোচনা।",
            category="technology",
            author="প্রযুক্তি ডেস্ক",
            position_placement="FEATURED",
            display_order=1,
            is_pinned=False,
            status="completed",
        )

        # Check lead hero article query picks pinned LEAD article
        hero = repo.get_lead_hero_article()
        assert hero is not None
        assert hero.id == lead_art.id or hero.is_pinned is True

        # Check placement update helper
        updated = repo.update_article_placement(
            article_id=featured_art.id,
            position_placement="SUB_LEAD",
            display_order=3,
            is_pinned=True,
        )
        assert updated is not None
        assert updated.position_placement == "SUB_LEAD"
        assert updated.display_order == 3
        assert updated.is_pinned is True


def test_article_reader_web_view_rendering(client):
    """Verify public article reader view renders source attribution card, removed notice, and image."""
    # 1. Create a test article with REMOVED_AT_SOURCE status
    with get_db_session() as session:
        repo = ArticleRepository(session)
        art = repo.create_editorial_article(
            title="টেস্ট আর্টিকেল: উৎস অপসারণ ও ফ্যাক্ট চেক নোটিশ",
            content_text="এটি একটি বিস্তারিত পরীক্ষামূলক প্রতিবেদন।\n\nদ্বিতীয় অনুচ্ছেদ যেখানে বিশ্লেষণ তুলে ধরা হয়েছে।",
            summary="পরীক্ষামূলক প্রতিবেদন সারাংশ",
            category="politics",
            author="ষ্টাফ রিপোর্টার",
            source="দৈনিক সমকাল",
            original_source_url="https://samakal.com/politics/article-removed-sample",
            source_status="REMOVED_AT_SOURCE",
            source_removed_notice="মূল সোর্স পেজটি সরিয়ে ফেলা হয়েছে।",
            creation_origin="MANUAL",
            status="completed",
        )
        art_id = art.id

    # 2. GET /news/<id>
    resp = client.get(f"/news/{art_id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Verify article header, image fallback handler, and content
    assert "টেস্ট আর্টিকেল" in html
    assert BanglaTextNormalizer.normalize_article_text("বিশ্লেষণ তুলে ধরা হয়েছে") in html
    
    # Verify Provenance & Source card
    assert "মূল সংবাদ উৎস" in html or "উৎস বিবরণী" in html
    assert "https://samakal.com/politics/article-removed-sample" in html
    assert "ম্যানুয়াল" in html or "ম্যানুয়াল" in html or "সম্পাদকীয়" in html
    
    # Verify Removed at Source warning banner
    assert "অপসারিত" in html or "সরিয়ে ফেলা হয়েছে" in html
    assert "আর্কাইভ কপি" in html or "সংরক্ষিত" in html


def test_newspaper_admin_placement_and_source_endpoints(client):
    """Test admin quick placement update and live source checking API endpoints."""
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = "admin"
        sess["role"] = "admin"

    with get_db_session() as session:
        repo = ArticleRepository(session)
        art = repo.create_editorial_article(
            title="এডমিন প্লেসমেন্ট কন্ট্রোল টেস্ট",
            content_text="কনটেন্ট...",
            category="technology",
            source="Reuters",
            original_source_url="https://httpbin.org/status/200",
            source_status="ACTIVE",
            position_placement="STANDARD",
            display_order=10,
            status="completed",
        )
        art_id = art.id

    # 1. POST Placement update via AJAX
    post_res = client.post(
        f"/admin/newspaper/article/placement/{art_id}",
        json={
            "position_placement": "LEAD",
            "display_order": 1,
            "is_pinned": True,
        }
    )
    assert post_res.status_code == 200
    data = post_res.get_json()
    assert data["success"] is True
    assert data["placement"] == "LEAD"
    assert data["display_order"] == 1
    assert data["is_pinned"] is True

    # 2. POST Source URL live audit check
    chk_res = client.post(f"/admin/newspaper/article/check-source/{art_id}")
    assert chk_res.status_code == 200
    chk_data = chk_res.get_json()
    assert chk_data["success"] is True
    assert "status" in chk_data
