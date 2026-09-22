"""Unit tests for Scraper Module."""

import pytest
from bs4 import BeautifulSoup
from src.scraper.parsers.bangla_portal import BanglaPortalParser
from src.scraper.engine import DomainRateLimiter
from src.scraper.js_renderer import JSRenderingManager
from src.scraper.mock_bangla_portal import MockBanglaPortalServer, generate_sample_image


def test_bangla_parser_extraction():
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>পরীক্ষামূলক সংবাদ শিরোনাম</title>
        <meta property="og:title" content="পরীক্ষামূলক সংবাদ শিরোনাম">
        <meta property="og:image" content="http://example.com/img.jpg">
        <meta property="article:published_time" content="2026-09-21T12:00:00Z">
        <meta name="author" content="প্রতিবেদক">
    </head>
    <body>
        <article>
            <h1 class="article-title">পরীক্ষামূলক সংবাদ শিরোনাম</h1>
            <p>এটি একটি গুরুত্বপূর্ণ সংবাদ বিবরণ। দেশে নতুন অবকাঠামো নির্মাণ কাজ শুরু হয়েছে।</p>
            <p>সরকারের পক্ষ থেকে দ্রুত কাজ সম্পন্ন করার নির্দেশ দেওয়া হয়েছে।</p>
        </article>
    </body>
    </html>
    """
    parser = BanglaPortalParser()
    result = parser.parse_article(html_content, url="http://example.com/news/1", category="national")

    assert "পরীক্ষামূলক সংবাদ শিরোনাম" in result["title"]
    assert "অবকাঠামো নির্মাণ" in result["content_text"]
    assert result["author"] == "প্রতিবেদক"
    assert result["published_at"] is not None
    assert result["lead_image_url"] == "http://example.com/img.jpg"
    assert result["category"] == "national"
    assert len(result["missing_fields"]) == 0


def test_parser_fallback_selectors_and_missing_fields():
    # HTML missing lead image and author
    html_content = """
    <html>
    <body>
        <h1>শিরোনাম মাত্র</h1>
        <p>সংবাদের খুব সংক্ষিপ্ত বিবরণ।</p>
    </body>
    </html>
    """
    parser = BanglaPortalParser()
    result = parser.parse_article(html_content, url="http://example.com/news/2")

    assert result["title"] == "শিরোনাম মাত্র"
    assert "সংবাদের খুব সংক্ষিপ্ত বিবরণ" in result["content_text"]
    assert result["author"] is None
    assert result["lead_image_url"] is None
    # Missing fields should be tracked
    assert "lead_image" in result["missing_fields"]
    assert "author" in result["missing_fields"]


def test_rate_limiter():
    limiter = DomainRateLimiter(default_delay=0.1, jitter=0.0)
    import time
    t0 = time.time()
    limiter.wait_for_turn("http://example.com/page1")
    limiter.wait_for_turn("http://example.com/page2")
    elapsed = time.time() - t0
    assert elapsed >= 0.08


def test_js_rendering_modes():
    js_mgr = JSRenderingManager()
    # Test skip mode
    html, was_js, status = js_mgr.fetch_content("http://example.com", js_mode="skip")
    assert html is None
    assert status == "skipped_by_config"
    js_mgr.close()


def test_mock_portal_server():
    server = MockBanglaPortalServer(port=8766)
    server.start()
    try:
        import httpx
        res = httpx.get("http://127.0.0.1:8766/category/politics")
        assert res.status_code == 200
        assert "বিভাগ: politics" in res.text
    finally:
        server.stop()
