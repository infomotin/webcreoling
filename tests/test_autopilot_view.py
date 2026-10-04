import pytest
from src.web.app import create_app

def test_scraper_autopilot_tab():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"
        
        # Test GET /scraper?tab=autopilot
        res = client.get("/scraper?tab=autopilot")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        # Check tab is marked active
        assert 'id="tab-autopilot" class="tab-pane active"' in html
        assert "এআই পাইলট অটোনোমাস মিশন কন্ট্রোল" in html
        assert "সাইকেল ফ্রিকোয়েন্সি" in html
        assert "সাফল্যের হার" in html
        assert "অটোনোমাস ব্যাকগ্রাউন্ড শিডিউল ও ট্রুথ গেট প্যারামিটার" in html
        assert "এআই পাইলট ব্রেন অটোনোমাস প্রকাশনা ও ডিসিশন লগ" in html

def test_autopilot_toggle_and_trigger():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"
            
        # Test update settings with float threshold
        res = client.post("/scraper/autopilot/update-settings", data={
            "interval_seconds": "300",
            "threshold": "0.75",
            "max_items": "5"
        }, follow_redirects=False)
        assert res.status_code == 302
        assert "tab=autopilot" in res.headers["Location"]
        
        # Test toggle
        res = client.post("/scraper/autopilot/toggle", follow_redirects=False)
        assert res.status_code == 302
        assert "tab=autopilot" in res.headers["Location"]
        
        # Test trigger-now (with mocked scheduler so we don't start live crawler)
        from unittest.mock import MagicMock, patch
        mock_scheduler = MagicMock()
        mock_scheduler.trigger_job_now.return_value = {"status": "started"}
        with patch("src.web.routes.scraper_bp.get_scheduler", return_value=mock_scheduler):
            res = client.post("/scraper/autopilot/trigger-now", follow_redirects=False)
            assert res.status_code == 302
            assert "tab=autopilot" in res.headers["Location"]
            mock_scheduler.trigger_job_now.assert_called_once_with("ai_pilot_decision_brain")

def test_autopilot_quick_publish():
    import uuid
    from src.storage.database import get_db_session
    from src.storage.models import Article
    from datetime import datetime, timezone
    
    app = create_app()
    app.config["TESTING"] = True
    
    # Create a test draft article with unique url
    article_id = None
    unique_url = f"https://example.com/test-pilot-publish-{uuid.uuid4().hex}"
    with get_db_session() as s:
        art = Article(
            url=unique_url,
            title="Test Pilot Draft Article",
            source="example.com",
            category="international",
            content_text="Sample text content for pilot article test.",
            scrape_status="draft",
            created_at=datetime.now(timezone.utc)
        )
        s.add(art)
        s.flush()
        article_id = art.id
        
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "admin"
            sess["role"] = "admin"
            
        res = client.post(f"/scraper/autopilot/quick-publish/{article_id}", follow_redirects=False)
        assert res.status_code == 302
        assert "tab=autopilot" in res.headers["Location"]
        
    with get_db_session() as s:
        art = s.get(Article, article_id)
        assert art is not None
        assert art.scrape_status == "completed"
        # Cleanup
        s.delete(art)

