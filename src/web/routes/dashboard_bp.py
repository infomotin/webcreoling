"""
Dashboard Blueprint.
Provides the main application dashboard, metrics, and analytics overview.
"""

from pathlib import Path
from flask import Blueprint, render_template
from config.settings import settings
from src.common.utils import safe_read_json
from src.storage.database import get_db_session
from src.storage.models import Article, ScrapeLog, User, NewsletterSubscriber, Poll
from src.storage.repositories import ArticleRepository
from src.web.auth import login_required

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
def index_view():
    """Main dashboard displaying article stats, categories, and recent ingestion activity."""
    with get_db_session() as session:
        repo = ArticleRepository(session)
        stats = repo.get_database_stats()
        
        user_count = session.query(User).count()
        subscriber_count = session.query(NewsletterSubscriber).count()
        poll_count = session.query(Poll).count()

        # Fetch recent 6 articles
        recent_articles = (
            session.query(Article)
            .order_by(Article.id.desc())
            .limit(6)
            .all()
        )
        recent_articles_data = [a.to_dict() for a in recent_articles]

        # Fetch recent 5 scrape logs
        recent_logs = (
            session.query(ScrapeLog)
            .order_by(ScrapeLog.id.desc())
            .limit(6)
            .all()
        )
        recent_logs_data = [l.to_dict() for l in recent_logs]

    # Read recent chat history if available
    chat_history_file = settings.DATA_DIR / "chat_history.jsonl"
    recent_chats = []
    if chat_history_file.exists():
        try:
            with open(chat_history_file, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
                for l in lines[-5:]:
                    import json
                    entry = json.loads(l)
                    # Normalize keys
                    norm_entry = {
                        "mode": entry.get("mode", "rag_qa"),
                        "user_input": entry.get("user_input") or entry.get("query") or "",
                        "response": entry.get("response") or entry.get("response_text") or entry.get("answer") or "",
                        "latency_seconds": entry.get("latency_seconds", 0.0),
                    }
                    recent_chats.append(norm_entry)
            recent_chats.reverse()
        except Exception:
            pass

    return render_template(
        "dashboard.html",
        stats=stats,
        user_count=user_count,
        subscriber_count=subscriber_count,
        poll_count=poll_count,
        recent_articles=recent_articles_data,
        recent_logs=recent_logs_data,
        recent_chats=recent_chats,
    )
