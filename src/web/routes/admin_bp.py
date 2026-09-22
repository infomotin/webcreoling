"""
Admin Management Blueprint.
Provides User Management and Editorial Newsroom CMS (Full CRUD, Approvals, Archiving,
Portal Settings, Dynamic Footer, Advertisement Management, Time-based Scheduling,
Security Audit Logs, Server & Health Monitoring, AI Pilot Mode).
"""

from datetime import datetime
from typing import Optional
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    session as flask_session,
)
from src.storage.database import get_db_session
from src.storage.repositories import (
    UserRepository,
    ArticleRepository,
    PortalRepository,
    SiteConfigRepository,
    AdvertisementRepository,
    AuditLogRepository,
    SystemMonitorRepository,
    AIPilotHelper,
)
from src.web.auth import login_required, roles_required

admin_bp = Blueprint("admin", __name__)


def parse_iso_datetime(val: Optional[str]) -> Optional[datetime]:
    """Helper to parse datetime inputs from web forms."""
    if not val or not val.strip():
        return None
    clean = val.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(clean, fmt)
        except ValueError:
            continue
    return None


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
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "admin")

        if repo.get_by_username(username):
            flash(f"Username '{username}' already exists.", "danger")
            return redirect(url_for("admin.users_view"))
        if repo.get_by_email(email):
            flash(f"Email '{email}' already exists.", "danger")
            return redirect(url_for("admin.users_view"))

        new_u = repo.create_user(username=username, email=email, password=password, role=role)
        audit_repo.log_action(
            username=current_username,
            action="user_created",
            resource_type="user",
            resource_id=str(new_u.id),
            details={"created_user": username, "role": role},
            ip_address=request.remote_addr,
        )
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
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "admin")

        user = repo.update_role(user_id=user_id, new_role=new_role)
        if user:
            audit_repo.log_action(
                username=current_username,
                action="user_role_updated",
                resource_type="user",
                resource_id=str(user_id),
                details={"target_user": user.username, "new_role": new_role},
                ip_address=request.remote_addr,
            )
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
    KPI Metrics, Full Article CRUD, Moderation Queue, Category filtering, Polls,
    Subscribers, Settings, Footer, Ads, Scheduling, Security, Monitor & AI Pilot.
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
        cfg_repo = SiteConfigRepository(session)
        ad_repo = AdvertisementRepository(session)
        audit_repo = AuditLogRepository(session)
        monitor_repo = SystemMonitorRepository(session)

        # 0. Process any pending scheduled article releases
        article_repo.process_scheduled_publishing()

        # Seed defaults
        cfg_repo.seed_default_configs()
        ad_repo.seed_default_ads()
        portal_repo.seed_default_poll()

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

        # 4. Advanced Modules Data
        scheduled_articles = article_repo.get_scheduled_articles()
        site_configs = cfg_repo.get_all_configs()
        ads = ad_repo.get_all_ads()
        audit_logs = audit_repo.get_audit_logs(limit=40)
        server_telemetry = monitor_repo.get_telemetry()

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
            scheduled_articles=[a.to_dict() for a in scheduled_articles],
            site_configs=site_configs,
            ads=[a.to_dict() for a in ads],
            audit_logs=[l.to_dict() for l in audit_logs],
            server_telemetry=server_telemetry,
        )


@admin_bp.route("/newspaper/article/create", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def create_article():
    """Create and publish/draft/schedule a new article directly from editorial desk."""
    title = request.form.get("title", "").strip()
    category = request.form.get("category", "general").strip()
    author = request.form.get("author", "").strip()
    summary = request.form.get("summary", "").strip()
    content_text = request.form.get("content_text", "").strip()
    image_path = request.form.get("image_path", "").strip()
    is_featured = bool(request.form.get("is_featured"))
    is_breaking = bool(request.form.get("is_breaking"))
    status = request.form.get("status", "completed").strip()
    scheduled_at_raw = request.form.get("scheduled_at", "").strip()
    scheduled_at = parse_iso_datetime(scheduled_at_raw)

    if not title or not content_text:
        flash("সংবাদের শিরোনাম এবং বিস্তারিত বিবরণ দেওয়া আবশ্যক।", "warning")
        return redirect(url_for("admin.newspaper_management_view"))

    with get_db_session() as session:
        repo = ArticleRepository(session)
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "editor")

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
            scheduled_at=scheduled_at,
        )

        audit_repo.log_action(
            username=current_username,
            action="article_create",
            resource_type="article",
            resource_id=str(article.id),
            details={"title": article.title[:60], "status": article.scrape_status, "category": article.category},
            ip_address=request.remote_addr,
        )

        if article.scrape_status == "scheduled":
            status_label = f"পরবর্তী প্রকাশের জন্য নির্ধারিত ({article.scheduled_at})"
        elif article.scrape_status == "completed":
            status_label = "সরাসরি প্রকাশিত"
        else:
            status_label = "খসড়া হিসেবে সংরক্ষিত"

        flash(f"সংবাদ #{article.id} ('{article.title[:40]}...') {status_label} হয়েছে!", "success")

    target_tab = "scheduler" if status == "scheduled" or scheduled_at else "articles"
    return redirect(url_for("admin.newspaper_management_view", tab=target_tab))


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
    scheduled_at_raw = request.form.get("scheduled_at", "").strip()
    scheduled_at = parse_iso_datetime(scheduled_at_raw)

    with get_db_session() as session:
        repo = ArticleRepository(session)
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "editor")

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
            scheduled_at=scheduled_at,
        )
        if updated:
            audit_repo.log_action(
                username=current_username,
                action="article_edit",
                resource_type="article",
                resource_id=str(article_id),
                details={"title": updated.title[:60], "status": updated.scrape_status},
                ip_address=request.remote_addr,
            )
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
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "editor")

        if repo.delete_article(article_id):
            audit_repo.log_action(
                username=current_username,
                action="article_delete",
                resource_type="article",
                resource_id=str(article_id),
                ip_address=request.remote_addr,
            )
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
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "editor")

        if repo.approve_article(article_id):
            audit_repo.log_action(
                username=current_username,
                action="article_approve",
                resource_type="article",
                resource_id=str(article_id),
                ip_address=request.remote_addr,
            )
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
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "editor")

        if repo.archive_article(article_id):
            audit_repo.log_action(
                username=current_username,
                action="article_archive",
                resource_type="article",
                resource_id=str(article_id),
                ip_address=request.remote_addr,
            )
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
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "editor")

        if repo.restore_article(article_id):
            audit_repo.log_action(
                username=current_username,
                action="article_restore",
                resource_type="article",
                resource_id=str(article_id),
                ip_address=request.remote_addr,
            )
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
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "editor")

        state = repo.toggle_featured(article_id)
        status_str = "শীর্ষ সংবাদ হিসেবে নির্বাচন করা হয়েছে" if state else "শীর্ষ সংবাদ থেকে বাদ দেওয়া হয়েছে"
        audit_repo.log_action(
            username=current_username,
            action="toggle_featured",
            resource_type="article",
            resource_id=str(article_id),
            details={"is_featured": state},
            ip_address=request.remote_addr,
        )
        flash(f"সংবাদ #{article_id}: {status_str}।", "success")
    return redirect(url_for("admin.newspaper_management_view"))


@admin_bp.route("/newspaper/toggle-breaking/<int:article_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def toggle_article_breaking(article_id: int):
    """Toggle article breaking news ticker status."""
    with get_db_session() as session:
        repo = ArticleRepository(session)
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "editor")

        state = repo.toggle_breaking(article_id)
        status_str = "ব্রেকিং নিউজ টিকারে যুক্ত করা হয়েছে" if state else "ব্রেকিং নিউজ টিকার থেকে সরানো হয়েছে"
        audit_repo.log_action(
            username=current_username,
            action="toggle_breaking",
            resource_type="article",
            resource_id=str(article_id),
            details={"is_breaking": state},
            ip_address=request.remote_addr,
        )
        flash(f"সংবাদ #{article_id}: {status_str}।", "success")
    return redirect(url_for("admin.newspaper_management_view"))


# =========================================================================
# SETTINGS & BRANDING
# =========================================================================

@admin_bp.route("/newspaper/settings/save", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def save_portal_settings():
    """Save site branding, rates, and weather ticker configurations."""
    site_title = request.form.get("site_title", "প্রথম আলো").strip()
    site_tagline = request.form.get("site_tagline", "").strip()
    logo_text = request.form.get("logo_text", "প্রথম আলো").strip()
    logo_image = request.form.get("logo_image", "").strip()
    edition = request.form.get("edition", "বাংলাদেশ সংস্করণ").strip()
    usd_rate = request.form.get("usd_rate", "১২১.৫০").strip()
    eur_rate = request.form.get("eur_rate", "১৩২.২০").strip()
    weather_city = request.form.get("weather_city", "ঢাকা").strip()
    weather_temp = request.form.get("weather_temp", "২৮° সে.").strip()
    weather_desc = request.form.get("weather_desc", "আংশিক মেঘলা").strip()

    branding_dict = {
        "site_title": site_title,
        "site_tagline": site_tagline,
        "logo_text": logo_text,
        "logo_image": logo_image,
        "edition": edition,
        "usd_rate": usd_rate,
        "eur_rate": eur_rate,
        "weather_city": weather_city,
        "weather_temp": weather_temp,
        "weather_desc": weather_desc,
    }

    with get_db_session() as session:
        cfg_repo = SiteConfigRepository(session)
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "admin")

        cfg_repo.set_config("branding", branding_dict)
        audit_repo.log_action(
            username=current_username,
            action="settings_save",
            resource_type="site_config",
            resource_id="branding",
            details=branding_dict,
            ip_address=request.remote_addr,
        )
        flash("পোর্টাল সেটিংস ও ব্র্যান্ডিং তথ্য সফলভাবে সংরক্ষিত হয়েছে!", "success")

    return redirect(url_for("admin.newspaper_management_view", tab="settings"))


# =========================================================================
# DYNAMIC FOOTER MANAGEMENT
# =========================================================================

@admin_bp.route("/newspaper/footer/save", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def save_dynamic_footer():
    """Save dynamic footer content, contact info, and links."""
    publisher = request.form.get("publisher", "").strip()
    editor_in_chief = request.form.get("editor_in_chief", "").strip()
    office_address = request.form.get("office_address", "").strip()
    contact_email = request.form.get("contact_email", "").strip()
    contact_phone = request.form.get("contact_phone", "").strip()
    copyright_text = request.form.get("copyright_text", "").strip()
    facebook_url = request.form.get("facebook_url", "").strip()
    youtube_url = request.form.get("youtube_url", "").strip()
    twitter_url = request.form.get("twitter_url", "").strip()
    android_app_url = request.form.get("android_app_url", "").strip()
    ios_app_url = request.form.get("ios_app_url", "").strip()

    footer_dict = {
        "publisher": publisher,
        "editor_in_chief": editor_in_chief,
        "office_address": office_address,
        "contact_email": contact_email,
        "contact_phone": contact_phone,
        "copyright_text": copyright_text,
        "facebook_url": facebook_url,
        "youtube_url": youtube_url,
        "twitter_url": twitter_url,
        "android_app_url": android_app_url,
        "ios_app_url": ios_app_url,
    }

    with get_db_session() as session:
        cfg_repo = SiteConfigRepository(session)
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "admin")

        cfg_repo.set_config("footer", footer_dict)
        audit_repo.log_action(
            username=current_username,
            action="footer_save",
            resource_type="site_config",
            resource_id="footer",
            details=footer_dict,
            ip_address=request.remote_addr,
        )
        flash("ডায়নামিক ফুটার ও সম্পাদকীয় তথ্যাবলী সফলভাবে সংরক্ষিত হয়েছে!", "success")

    return redirect(url_for("admin.newspaper_management_view", tab="footer"))


# =========================================================================
# ADVERTISEMENT MANAGEMENT
# =========================================================================

@admin_bp.route("/newspaper/ads/create", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def create_ad():
    """Create a new advertisement banner."""
    title = request.form.get("title", "").strip()
    slot = request.form.get("slot", "header_top").strip()
    image_url = request.form.get("image_url", "").strip()
    target_url = request.form.get("target_url", "").strip()
    is_active = bool(request.form.get("is_active"))

    if not title or not image_url or not target_url:
        flash("বিজ্ঞাপনের নাম, ছবির URL এবং গন্তব্য লিংক দেওয়া আবশ্যক।", "warning")
        return redirect(url_for("admin.newspaper_management_view", tab="ads"))

    with get_db_session() as session:
        ad_repo = AdvertisementRepository(session)
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "admin")

        ad = ad_repo.create_ad(
            title=title,
            slot=slot,
            image_url=image_url,
            target_url=target_url,
            is_active=is_active,
        )
        audit_repo.log_action(
            username=current_username,
            action="ad_create",
            resource_type="advertisement",
            resource_id=str(ad.id),
            details={"title": title, "slot": slot},
            ip_address=request.remote_addr,
        )
        flash(f"বিজ্ঞাপন ব্যানার '{title}' (#{ad.id}) তৈরি ও যুক্ত করা হয়েছে!", "success")

    return redirect(url_for("admin.newspaper_management_view", tab="ads"))


@admin_bp.route("/newspaper/ads/toggle/<int:ad_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def toggle_ad(ad_id: int):
    """Toggle advertisement active status."""
    with get_db_session() as session:
        ad_repo = AdvertisementRepository(session)
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "admin")

        state = ad_repo.toggle_ad_status(ad_id)
        audit_repo.log_action(
            username=current_username,
            action="ad_toggle",
            resource_type="advertisement",
            resource_id=str(ad_id),
            details={"is_active": state},
            ip_address=request.remote_addr,
        )
        status_str = "সক্রিয় (Active)" if state else "স্থগিত (Inactive)"
        flash(f"বিজ্ঞাপন #{ad_id}: {status_str} করা হয়েছে।", "success")

    return redirect(url_for("admin.newspaper_management_view", tab="ads"))


@admin_bp.route("/newspaper/ads/delete/<int:ad_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def delete_ad(ad_id: int):
    """Delete an advertisement banner."""
    with get_db_session() as session:
        ad_repo = AdvertisementRepository(session)
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "admin")

        if ad_repo.delete_ad(ad_id):
            audit_repo.log_action(
                username=current_username,
                action="ad_delete",
                resource_type="advertisement",
                resource_id=str(ad_id),
                ip_address=request.remote_addr,
            )
            flash(f"বিজ্ঞাপন #{ad_id} মুছে ফেলা হয়েছে।", "success")
        else:
            flash("বিজ্ঞাপন মোছা যায়নি।", "danger")

    return redirect(url_for("admin.newspaper_management_view", tab="ads"))


# =========================================================================
# TIME-BASED SCHEDULER ACTIONS
# =========================================================================

@admin_bp.route("/newspaper/scheduler/publish-now/<int:article_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def publish_scheduled_now(article_id: int):
    """Immediately release a scheduled article."""
    with get_db_session() as session:
        repo = ArticleRepository(session)
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "editor")

        updated = repo.update_editorial_article(
            article_id=article_id,
            status="completed",
            scheduled_at=None,
        )
        if updated:
            audit_repo.log_action(
                username=current_username,
                action="scheduled_publish_now",
                resource_type="article",
                resource_id=str(article_id),
                ip_address=request.remote_addr,
            )
            flash(f"সংবাদ #{article_id} অবিলম্বে প্রকাশিত হয়েছে!", "success")
        else:
            flash("সংবাদ পাওয়া যায়নি।", "danger")

    return redirect(url_for("admin.newspaper_management_view", tab="scheduler"))


# =========================================================================
# AI PILOT MODE ROUTES
# =========================================================================

@admin_bp.route("/newspaper/aipilot/save", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def save_aipilot_settings():
    """Save AI Pilot Mode configuration."""
    enabled = bool(request.form.get("enabled"))
    auto_headline = bool(request.form.get("auto_headline"))
    auto_summary = bool(request.form.get("auto_summary"))
    auto_categorize = bool(request.form.get("auto_categorize"))
    auto_hero_ranking = bool(request.form.get("auto_hero_ranking"))
    model_name = request.form.get("model_name", "webcreoling-lora-v1").strip()

    aipilot_dict = {
        "enabled": enabled,
        "auto_headline": auto_headline,
        "auto_summary": auto_summary,
        "auto_categorize": auto_categorize,
        "auto_hero_ranking": auto_hero_ranking,
        "model_name": model_name,
    }

    with get_db_session() as session:
        cfg_repo = SiteConfigRepository(session)
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "admin")

        cfg_repo.set_config("aipilot", aipilot_dict)
        audit_repo.log_action(
            username=current_username,
            action="aipilot_settings_save",
            resource_type="site_config",
            resource_id="aipilot",
            details=aipilot_dict,
            ip_address=request.remote_addr,
        )
        flash("এআই পাইলট মোড কনফিগারেশন সফলভাবে আপডেট করা হয়েছে!", "success")

    return redirect(url_for("admin.newspaper_management_view", tab="aipilot"))


@admin_bp.route("/newspaper/aipilot/analyze", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def analyze_article_ai():
    """AJAX endpoint for AI Pilot content analysis, category prediction, and summary generation."""
    data = request.get_json(force=True, silent=True) or {}
    title = data.get("title", "").strip()
    content_text = data.get("content_text", "").strip()

    if not content_text:
        return jsonify({"status": "error", "message": "বিশ্লেষণের জন্য সংবাদের বিস্তারিত বিবরণ প্রদান করুন।"}), 400

    analysis = AIPilotHelper.analyze_article(title=title, content_text=content_text)
    return jsonify({"status": "success", "data": analysis})


# =========================================================================
# POLLS & SUBSCRIBERS
# =========================================================================

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
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "editor")

        p = repo.create_poll(question=question, options=options, category=category)
        audit_repo.log_action(
            username=current_username,
            action="poll_create",
            resource_type="poll",
            resource_id=str(p.id),
            details={"question": question, "options": options},
            ip_address=request.remote_addr,
        )
        flash("নতুন জনমত জরিপ তৈরি ও সক্রিয় করা হয়েছে!", "success")

    return redirect(url_for("admin.newspaper_management_view", tab="polls"))


@admin_bp.route("/newspaper/toggle-poll/<int:poll_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def toggle_poll_status(poll_id: int):
    """Toggle poll active/closed state."""
    with get_db_session() as session:
        repo = PortalRepository(session)
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "editor")

        state = repo.toggle_poll_status(poll_id)
        audit_repo.log_action(
            username=current_username,
            action="poll_toggle",
            resource_type="poll",
            resource_id=str(poll_id),
            details={"is_active": state},
            ip_address=request.remote_addr,
        )
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
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "editor")

        if repo.delete_poll(poll_id):
            audit_repo.log_action(
                username=current_username,
                action="poll_delete",
                resource_type="poll",
                resource_id=str(poll_id),
                ip_address=request.remote_addr,
            )
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
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "admin")

        if repo.delete_subscriber(subscriber_id):
            audit_repo.log_action(
                username=current_username,
                action="subscriber_delete",
                resource_type="subscriber",
                resource_id=str(subscriber_id),
                ip_address=request.remote_addr,
            )
            flash(f"গ্রাহক #{subscriber_id} মুছে ফেলা হয়েছে।", "success")
        else:
            flash("গ্রাহক মোছা যায়নি।", "danger")
    return redirect(url_for("admin.newspaper_management_view", tab="subscribers"))
