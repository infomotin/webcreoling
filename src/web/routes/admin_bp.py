"""
Admin Management Blueprint.
Provides User Management and Editorial Newspaper Management (Featured stories, Opinion polls, Subscribers).
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from src.storage.database import get_db_session
from src.storage.repositories import UserRepository, ArticleRepository, PortalRepository
from src.web.auth import login_required, roles_required

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/users")
@login_required
@roles_required("admin")
def users_view():
    """List all registered users and their RBAC roles."""
    with get_db_session() as session:
        repo = UserRepository(session)
        users = repo.list_all_users()
        users_data = [u.to_dict() for u in users]

    return render_template("users.html", users=users_data)


@admin_bp.route("/users/create", methods=["POST"])
@login_required
@roles_required("admin")
def create_user():
    """Admin creates a new user."""
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()
    role = request.form.get("role", "viewer").strip().lower()

    if not username or not email or not password:
        flash("Username, email, and password are required.", "danger")
        return redirect(url_for("admin.users_view"))

    with get_db_session() as session:
        repo = UserRepository(session)
        if repo.get_by_username(username):
            flash(f"Username '{username}' already exists.", "danger")
            return redirect(url_for("admin.users_view"))
        if repo.get_by_email(email):
            flash(f"Email '{email}' already exists.", "danger")
            return redirect(url_for("admin.users_view"))

        repo.create_user(username=username, email=email, password=password, role=role)
        flash(f"User '{username}' created with role '{role.capitalize()}'.", "success")

    return redirect(url_for("admin.users_view"))


@admin_bp.route("/users/<int:user_id>/role", methods=["POST"])
@login_required
@roles_required("admin")
def update_user_role(user_id: int):
    """Admin updates a user's role."""
    new_role = request.form.get("role", "viewer").strip().lower()
    with get_db_session() as session:
        repo = UserRepository(session)
        user = repo.update_role(user_id=user_id, new_role=new_role)
        if user:
            flash(f"Updated role for '{user.username}' to '{new_role.capitalize()}'.", "success")
        else:
            flash("User not found.", "danger")

    return redirect(url_for("admin.users_view"))


@admin_bp.route("/newspaper")
@login_required
@roles_required("admin", "editor")
def newspaper_management_view():
    """Manage frontend newspaper: highlighted hero stories, polls, and newsletter subscribers."""
    with get_db_session() as session:
        article_repo = ArticleRepository(session)
        portal_repo = PortalRepository(session)

        articles = article_repo.get_highlighted_articles(limit=25)
        polls = portal_repo.list_all_polls()
        subscribers = portal_repo.list_subscribers()

        return render_template(
            "admin_newspaper.html",
            articles=articles,
            polls=[p.to_dict() for p in polls],
            subscribers=[s.to_dict() for s in subscribers],
        )


@admin_bp.route("/newspaper/toggle-feature/<int:article_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def toggle_article_featured(article_id: int):
    """Toggle article featured/hero status."""
    with get_db_session() as session:
        repo = ArticleRepository(session)
        state = repo.toggle_featured(article_id)
        status_str = "Featured (Lead Story)" if state else "Unfeatured"
        flash(f"Article #{article_id} is now {status_str}.", "success")
    return redirect(url_for("admin.newspaper_management_view"))


@admin_bp.route("/newspaper/toggle-breaking/<int:article_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def toggle_article_breaking(article_id: int):
    """Toggle article breaking news ticker status."""
    with get_db_session() as session:
        repo = ArticleRepository(session)
        state = repo.toggle_breaking(article_id)
        status_str = "Added to Breaking News Ticker" if state else "Removed from Breaking News"
        flash(f"Article #{article_id}: {status_str}.", "success")
    return redirect(url_for("admin.newspaper_management_view"))


@admin_bp.route("/newspaper/create-poll", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def create_poll():
    """Create a new reader opinion poll."""
    question = request.form.get("question", "").strip()
    category = request.form.get("category", "জাতীয়").strip()
    options_raw = request.form.get("options", "").strip()

    options = [opt.strip() for opt in options_raw.splitlines() if opt.strip()]

    if not question or len(options) < 2:
        flash("Poll must have a question and at least 2 options.", "warning")
        return redirect(url_for("admin.newspaper_management_view"))

    with get_db_session() as session:
        repo = PortalRepository(session)
        repo.create_poll(question=question, options=options, category=category)
        flash("New reader opinion poll created and published successfully!", "success")

    return redirect(url_for("admin.newspaper_management_view"))


@admin_bp.route("/newspaper/toggle-poll/<int:poll_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def toggle_poll_status(poll_id: int):
    """Toggle poll active/closed state."""
    with get_db_session() as session:
        repo = PortalRepository(session)
        state = repo.toggle_poll_status(poll_id)
        status_str = "Active" if state else "Closed"
        flash(f"Poll #{poll_id} is now {status_str}.", "success")
    return redirect(url_for("admin.newspaper_management_view"))

