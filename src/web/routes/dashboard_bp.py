"""
Dashboard Blueprint.
Provides the main application dashboard, metrics, and analytics overview.
"""

from flask import Blueprint, render_template
from src.storage.database import get_db_session
from src.storage.models import Article, ScrapeLog
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
        
        # Fetch recent 5 articles
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
            .limit(5)
            .all()
        )
        recent_logs_data = [l.to_dict() for l in recent_logs]

    return render_template(
        "dashboard.html",
        stats=stats,
        recent_articles=recent_articles_data,
        recent_logs=recent_logs_data,
    )
