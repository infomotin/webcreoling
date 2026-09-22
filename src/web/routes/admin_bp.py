"""
Admin Management Blueprint.
Provides User Management and Editorial Newspaper Management (Full CRUD, Approvals, Archiving, Polls, Subscribers).
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


# =========================================================================
# EDITORIAL NEWSPAPER NEWSROOM CMS ROUTES
# =========================================================================

@admin_bp.route("/newspaper")
@login_required
@roles_required("admin", "editor")
def newspaper_management_view():
    """
    Dedicated Editorial Newsroom CMS dashboard:
    KPI Metrics, Full Article CRUD, Moderation Queue, Category filtering, Polls, Subscribers & Archive.
    """
    search_query = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    status = request.args.get("status", "").strip()
    active_tab = request.args.get("tab", "articles").strip()

    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1

    with get_db_session() as session:
        article_repo = ArticleRepository(session)
        portal_repo = PortalRepository(session)

        # 1. Real-time Editorial KPI Metrics
        kpis = article_repo.get_editorial_kpis()

        # 2. Paginated & Filtered Articles Feed
        articles_data = article_repo.list_editorial_articles(
            search_query=search_query,
            category=category,
            status=status,
            page=page,
            page_size=15,
        )

        # 3. Opinion Polls & Newsletter Subscribers
        polls = portal_repo.list_all_polls()
        subscribers = portal_repo.list_subscribers()
        archive_dates = article_repo.get_available_archive_dates(limit=20)

        # Available unique categories in database
        stats = article_repo.get_database_stats()
        categories = list(stats.get("by_category", {}).keys())
        if not categories:
            categories = ["politics", "bangladesh", "business", "international", "sports", "technology", "news"]

        return render_template(
            "admin_newspaper.html",
            kpis=kpis,
            articles=articles_data["articles"],
            total_count=articles_data["total_count"],
            page=articles_data["page"],
            total_pages=articles_data["total_pages"],
            search_query=search_query,
            category_filter=category,
            status_filter=status,
            active_tab=active_tab,
            categories=categories,
            polls=[p.to_dict() for p in polls],
            subscribers=[s.to_dict() for s in subscribers],
            archive_dates=archive_dates,
        )


@admin_bp.route("/newspaper/article/create", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def create_article():
    """Create and publish/draft a new article directly from editorial desk."""
    title = request.form.get("title", "").strip()
    category = request.form.get("category", "general").strip()
    author = request.form.get("author", "").strip()
    summary = request.form.get("summary", "").strip()
    content_text = request.form.get("content_text", "").strip()
    image_path = request.form.get("image_path", "").strip()
    is_featured = bool(request.form.get("is_featured"))
    is_breaking = bool(request.form.get("is_breaking"))
    status = request.form.get("status", "completed").strip()

    if not title or not content_text:
        flash("সংবাদের শিরোনাম এবং বিস্তারিত বিবরণ দেওয়া আবশ্যক।", "warning")
        return redirect(url_for("admin.newspaper_management_view"))

    with get_db_session() as session:
        repo = ArticleRepository(session)
        article = repo.create_editorial_article(
            title=title,
            category=category,
            content_text=content_text,
            author=author,
            summary=summary,
            image_path=image_path,
            is_featured=is_featured,
            is_breaking=is_breaking,
            status=status,
        )
        status_label = "সরাসরি প্রকাশিত" if status == "completed" else "খসড়া হিসেবে সংরক্ষিত"
        flash(f"সংবাদ #{article.id} ('{article.title[:40]}...') {status_label} হয়েছে!", "success")

    return redirect(url_for("admin.newspaper_management_view"))


@admin_bp.route("/newspaper/article/edit/<int:article_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def edit_article(article_id: int):
    """Edit existing article details."""
    title = request.form.get("title", "").strip()
    category = request.form.get("category", "").strip()
    author = request.form.get("author", "").strip()
    summary = request.form.get("summary", "").strip()
    content_text = request.form.get("content_text", "").strip()
    image_path = request.form.get("image_path", "").strip()
    is_featured = bool(request.form.get("is_featured"))
    is_breaking = bool(request.form.get("is_breaking"))
    status = request.form.get("status", "completed").strip()

    with get_db_session() as session:
        repo = ArticleRepository(session)
        updated = repo.update_editorial_article(
            article_id=article_id,
            title=title if title else None,
            category=category if category else None,
            author=author if author else None,
            summary=summary if summary else None,
            content_text=content_text if content_text else None,
            image_path=image_path if image_path else None,
            is_featured=is_featured,
            is_breaking=is_breaking,
            status=status,
        )
        if updated:
            flash(f"সংবাদ #{article_id} সফলভাবে আপডেট করা হয়েছে!", "success")
        else:
            flash("সংবাদ পাওয়া যায়নি।", "danger")

    return redirect(url_for("admin.newspaper_management_view"))


@admin_bp.route("/newspaper/article/delete/<int:article_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def delete_article(article_id: int):
    """Permanently delete an article."""
    with get_db_session() as session:
        repo = ArticleRepository(session)
        if repo.delete_article(article_id):
            flash(f"সংবাদ #{article_id} স্থায়ীভাবে মুছে ফেলা হয়েছে।", "success")
        else:
            flash("সংবাদ মুছে ফেলতে ব্যর্থ হয়েছে।", "danger")

    return redirect(url_for("admin.newspaper_management_view"))


@admin_bp.route("/newspaper/article/approve/<int:article_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def approve_article(article_id: int):
    """Approve a draft/pending article and make it published."""
    with get_db_session() as session:
        repo = ArticleRepository(session)
        if repo.approve_article(article_id):
            flash(f"সংবাদ #{article_id} সম্পাদকীয় অনুমোদন লাভ করেছে এবং প্রকাশিত হয়েছে!", "success")
        else:
            flash("অনুমোদন সম্পন্ন করা যায়নি।", "danger")

    return redirect(url_for("admin.newspaper_management_view", status="pending"))


@admin_bp.route("/newspaper/article/archive/<int:article_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def archive_article(article_id: int):
    """Move an article to the archive."""
    with get_db_session() as session:
        repo = ArticleRepository(session)
        if repo.archive_article(article_id):
            flash(f"সংবাদ #{article_id} আর্কাইভে স্থানান্তর করা হয়েছে।", "success")
        else:
            flash("আর্কাইভ করা যায়নি।", "danger")

    return redirect(url_for("admin.newspaper_management_view"))


@admin_bp.route("/newspaper/article/restore/<int:article_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def restore_article(article_id: int):
    """Restore an archived article back to published."""
    with get_db_session() as session:
        repo = ArticleRepository(session)
        if repo.restore_article(article_id):
            flash(f"সংবাদ #{article_id} সফলভাবে পুনরুদ্ধার ও পুনঃপ্রকাশ করা হয়েছে!", "success")
        else:
            flash("পুনরুদ্ধার করা যায়নি।", "danger")

    return redirect(url_for("admin.newspaper_management_view", status="archived"))


@admin_bp.route("/newspaper/toggle-feature/<int:article_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def toggle_article_featured(article_id: int):
    """Toggle article featured/hero status."""
    with get_db_session() as session:
        repo = ArticleRepository(session)
        state = repo.toggle_featured(article_id)
        status_str = "শীর্ষ সংবাদ হিসেবে নির্বাচন করা হয়েছে" if state else "শীর্ষ সংবাদ থেকে বাদ দেওয়া হয়েছে"
        flash(f"সংবাদ #{article_id}: {status_str}।", "success")
    return redirect(url_for("admin.newspaper_management_view"))


@admin_bp.route("/newspaper/toggle-breaking/<int:article_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def toggle_article_breaking(article_id: int):
    """Toggle article breaking news ticker status."""
    with get_db_session() as session:
        repo = ArticleRepository(session)
        state = repo.toggle_breaking(article_id)
        status_str = "ব্রেকিং নিউজ টিকারে যুক্ত করা হয়েছে" if state else "ব্রেকিং নিউজ টিকার থেকে সরানো হয়েছে"
        flash(f"সংবাদ #{article_id}: {status_str}।", "success")
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
        flash("জরিপে একটি প্রশ্ন এবং অন্তত ২টি অপশন থাকা আবশ্যক।", "warning")
        return redirect(url_for("admin.newspaper_management_view", tab="polls"))

    with get_db_session() as session:
        repo = PortalRepository(session)
        repo.create_poll(question=question, options=options, category=category)
        flash("নতুন জনমত জরিপ তৈরি ও সক্রিয় করা হয়েছে!", "success")

    return redirect(url_for("admin.newspaper_management_view", tab="polls"))


@admin_bp.route("/newspaper/toggle-poll/<int:poll_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def toggle_poll_status(poll_id: int):
    """Toggle poll active/closed state."""
    with get_db_session() as session:
        repo = PortalRepository(session)
        state = repo.toggle_poll_status(poll_id)
        status_str = "সক্রিয় (Active)" if state else "স্থগিত (Closed)"
        flash(f"জরিপ #{poll_id}: {status_str} করা হয়েছে।", "success")
    return redirect(url_for("admin.newspaper_management_view", tab="polls"))


@admin_bp.route("/newspaper/delete-poll/<int:poll_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def delete_poll(poll_id: int):
    """Permanently delete an opinion poll."""
    with get_db_session() as session:
        repo = PortalRepository(session)
        if repo.delete_poll(poll_id):
            flash(f"জরিপ #{poll_id} মুছে ফেলা হয়েছে।", "success")
        else:
            flash("জরিপ মোছা যায়নি।", "danger")
    return redirect(url_for("admin.newspaper_management_view", tab="polls"))


@admin_bp.route("/newspaper/delete-subscriber/<int:subscriber_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def delete_subscriber(subscriber_id: int):
    """Remove a subscriber from the newsletter list."""
    with get_db_session() as session:
        repo = PortalRepository(session)
        if repo.delete_subscriber(subscriber_id):
            flash(f"গ্রাহক #{subscriber_id} মুছে ফেলা হয়েছে।", "success")
        else:
            flash("গ্রাহক মোছা যায়নি।", "danger")
    return redirect(url_for("admin.newspaper_management_view", tab="subscribers"))
