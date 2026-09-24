"""
Article Explorer Blueprint.
Supports full-text FTS5 search, category filtering, and detailed article inspection with images.
"""

from flask import Blueprint, render_template, request, abort
from sqlalchemy import func
from src.storage.database import get_db_session
from src.storage.models import Article
from src.storage.repositories import ArticleRepository
from src.web.auth import login_required

article_bp = Blueprint("article", __name__)


@article_bp.route("")
@login_required
def list_articles_view():
    """List articles with search query and category filtering."""
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    page = int(request.args.get("page", 1))
    per_page = 12

    with get_db_session() as session:
        repo = ArticleRepository(session)
        
        if query:
            # Full-Text Search via FTS5
            search_results = repo.search_fts(query, top_k=50)
            articles_data = search_results
            total = len(search_results)
            # Slice for current page
            start_idx = (page - 1) * per_page
            articles_data = search_results[start_idx : start_idx + per_page]
        else:
            db_query = session.query(Article)
            if category:
                db_query = db_query.filter(Article.category == category)
            total = db_query.count()
            articles = (
                db_query.order_by(Article.id.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
                .all()
            )
            articles_data = [a.to_dict() for a in articles]

        # Get category breakdown for filter pills
        category_counts = dict(
            session.query(Article.category, func.count(Article.id))
            .group_by(Article.category)
            .all()
        )

    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template(
        "articles.html",
        articles=articles_data,
        query=query,
        selected_category=category,
        page=page,
        total_pages=total_pages,
        total=total,
    )


@article_bp.route("/<int:article_id>")
@login_required
def article_detail_view(article_id: int):
    """Detailed view of an individual article including downloaded media."""
    with get_db_session() as session:
        repo = ArticleRepository(session)
        article = repo.get_by_id(article_id)
        if not article:
            abort(404)
        article_data = article.to_dict()

    return render_template("article_detail.html", article=article_data)
