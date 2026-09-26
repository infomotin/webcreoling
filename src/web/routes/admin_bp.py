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
from src.storage.models import Article
from src.storage.repositories import (
    UserRepository,
    ArticleRepository,
    PortalRepository,
    SiteConfigRepository,
    AdvertisementRepository,
    AuditLogRepository,
    SystemMonitorRepository,
    AIPilotHelper,
    SecurityRepository,
    BlockchainLedgerRepository,
    EmergencyVaultRepository,
)
from src.security.emergency_cipher_vault import get_emergency_vault
from src.datacenter.heavy_data_manager import get_heavy_data_manager
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


@admin_bp.route("/newsroom")
@login_required
@roles_required("admin", "editor")
def newsroom_view():
    """Shortcut redirect to Newsroom Management."""
    return redirect(url_for("admin.newspaper_management_view"))


@admin_bp.route("/security")
@login_required
@roles_required("admin", "editor")
def security_view():
    """Shortcut redirect to Newsroom Security & WAF tab."""
    return redirect(url_for("admin.newspaper_management_view", tab="security"))


@admin_bp.route("/blockchain")
@login_required
@roles_required("admin", "editor")
def blockchain_view():
    """Shortcut redirect to Newsroom Blockchain Ledger tab."""
    return redirect(url_for("admin.newspaper_management_view", tab="blockchain"))


@admin_bp.route("/settings")
@login_required
@roles_required("admin", "editor")
def settings_view():
    """Shortcut redirect to Newsroom Portal Settings tab."""
    return redirect(url_for("admin.newspaper_management_view", tab="settings"))


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
            flash(f"Role for user '{user.username}' updated to '{new_role.capitalize()}'.", "success")
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
        sec_repo = SecurityRepository(session)
        ledger_repo = BlockchainLedgerRepository(session)

        # 0. Process any pending scheduled article releases
        article_repo.process_scheduled_publishing()

        # Seed defaults
        cfg_repo.seed_default_configs()
        ad_repo.seed_default_ads()
        portal_repo.seed_default_poll()
        sec_repo.seed_default_security_rules()
        ledger_repo.ensure_genesis_block()

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

        # 5. Security Operations Center (SOC) & Cryptographic Ledger Data
        sec_metrics = sec_repo.get_security_metrics()
        blocked_ips = sec_repo.get_blocked_ips()
        blocked_countries = sec_repo.get_blocked_countries()
        threat_logs = sec_repo.get_threat_logs(limit=40)
        blockchain_stats = ledger_repo.get_blockchain_stats()
        ledger_blocks_data = ledger_repo.get_ledger_blocks(limit=25, page=1)
        chain_audit = ledger_repo.audit_full_chain()

        # 6. Autonomous AI Brain Security Vault & Heavy Data Capacity Metrics
        vault_repo = EmergencyVaultRepository(session)
        vault_engine = get_emergency_vault()
        heavy_mgr = get_heavy_data_manager()

        vault_state = vault_repo.get_vault_state()
        threat_assessment = vault_engine.assess_threat_status(session)
        heavy_metrics = heavy_mgr.get_heavy_data_metrics(session)

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
            sec_metrics=sec_metrics,
            blocked_ips=[ip.to_dict() for ip in blocked_ips],
            blocked_countries=[c.to_dict() for c in blocked_countries],
            threat_logs=[t.to_dict() for t in threat_logs],
            blockchain_stats=blockchain_stats,
            ledger_blocks=[b.to_dict() for b in ledger_blocks_data["blocks"]],
            chain_audit=chain_audit,
            vault_state=vault_state.to_dict(),
            threat_assessment=threat_assessment,
            heavy_metrics=heavy_metrics,
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
    original_source_url = request.form.get("original_source_url", "").strip()
    source_status = request.form.get("source_status", "ACTIVE").strip()
    creation_origin = request.form.get("creation_origin", "MANUAL").strip()
    position_placement = request.form.get("position_placement", "STANDARD").strip()
    display_order = int(request.form.get("display_order", 0) or 0)
    is_pinned = bool(request.form.get("is_pinned"))
    is_featured = bool(request.form.get("is_featured")) or (position_placement in ["LEAD", "FEATURED"])
    is_breaking = bool(request.form.get("is_breaking")) or (position_placement == "BREAKING")
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
            original_source_url=original_source_url,
            source_status=source_status,
            creation_origin=creation_origin,
            position_placement=position_placement,
            display_order=display_order,
            is_pinned=is_pinned,
        )

        audit_repo.log_action(
            username=current_username,
            action="article_create",
            resource_type="article",
            resource_id=str(article.id),
            details={
                "title": article.title[:60],
                "status": article.scrape_status,
                "category": article.category,
                "placement": article.position_placement,
                "origin": article.creation_origin,
            },
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
    original_source_url = request.form.get("original_source_url")
    source_status = request.form.get("source_status")
    source_removed_notice = request.form.get("source_removed_notice")
    creation_origin = request.form.get("creation_origin")
    position_placement = request.form.get("position_placement")
    display_order_raw = request.form.get("display_order")
    display_order = int(display_order_raw) if (display_order_raw and display_order_raw.isdigit()) else None
    is_pinned = bool(request.form.get("is_pinned")) if "is_pinned" in request.form else None
    is_featured = bool(request.form.get("is_featured")) if "is_featured" in request.form else None
    is_breaking = bool(request.form.get("is_breaking")) if "is_breaking" in request.form else None
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
            original_source_url=original_source_url if original_source_url is not None else None,
            source_status=source_status if source_status else None,
            source_removed_notice=source_removed_notice if source_removed_notice is not None else None,
            creation_origin=creation_origin if creation_origin else None,
            position_placement=position_placement if position_placement else None,
            display_order=display_order,
            is_pinned=is_pinned,
        )
        if updated:
            audit_repo.log_action(
                username=current_username,
                action="article_edit",
                resource_type="article",
                resource_id=str(article_id),
                details={"title": updated.title[:60], "status": updated.scrape_status, "placement": updated.position_placement},
                ip_address=request.remote_addr,
            )
            flash(f"সংবাদ #{article_id} সফলভাবে আপডেট করা হয়েছে!", "success")
        else:
            flash("সংবাদ পাওয়া যায়নি।", "danger")

    return redirect(url_for("admin.newspaper_management_view"))


@admin_bp.route("/newspaper/article/placement/<int:article_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def update_placement_route(article_id: int):
    """Quick update for placement position, display sequence order, pinned status and source status."""
    data = request.get_json(silent=True) or request.form
    position_placement = data.get("position_placement")
    display_order_val = data.get("display_order")
    display_order = int(display_order_val) if (display_order_val is not None and str(display_order_val).isdigit()) else None
    is_pinned = bool(data.get("is_pinned")) if "is_pinned" in data else None
    source_status = data.get("source_status")
    source_removed_notice = data.get("source_removed_notice")

    with get_db_session() as session:
        repo = ArticleRepository(session)
        updated = repo.update_article_placement(
            article_id=article_id,
            position_placement=position_placement,
            display_order=display_order,
            is_pinned=is_pinned,
            source_status=source_status,
            source_removed_notice=source_removed_notice,
        )
        if not updated:
            if request.is_json:
                return jsonify({"status": "error", "message": "Article not found"}), 404
            flash("সংবাদ পাওয়া যায়নি।", "danger")
            return redirect(url_for("admin.newspaper_management_view"))

        if request.is_json:
            return jsonify({
                "success": True,
                "status": "success",
                "article_id": article_id,
                "placement": updated.position_placement,
                "display_order": updated.display_order,
                "is_pinned": updated.is_pinned,
                "source_status": updated.source_status,
            })

        flash(f"সংবাদ #{article_id}-এর পজিশন ও ক্রমিক সফলভাবে পরিবর্তন করা হয়েছে!", "success")
        return redirect(url_for("admin.newspaper_management_view"))


@admin_bp.route("/newspaper/article/check-source/<int:article_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def check_source_status_route(article_id: int):
    """Audit whether the source URL is active or removed."""
    with get_db_session() as session:
        repo = ArticleRepository(session)
        audit_res = repo.check_source_url_status(article_id)
        return jsonify(audit_res)


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


@admin_bp.route("/newspaper/article/placement/<int:article_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def update_article_placement(article_id: int):
    """Update article placement position, serial order, and pin status."""
    if request.is_json:
        data = request.get_json() or {}
        placement = data.get("position_placement", "STANDARD")
        order = int(data.get("display_order", 0))
        is_pinned = bool(data.get("is_pinned", False))
    else:
        placement = request.form.get("position_placement", "STANDARD")
        order = int(request.form.get("display_order", 0))
        is_pinned = bool(request.form.get("is_pinned"))

    with get_db_session() as session:
        repo = ArticleRepository(session)
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "editor")

        updated = repo.update_article_placement(
            article_id=article_id,
            position_placement=placement,
            display_order=order,
            is_pinned=is_pinned,
        )

        if not updated:
            if request.is_json:
                return jsonify({"success": False, "message": "সংবাদ পাওয়া যায়নি।"}), 404
            flash("সংবাদ পাওয়া যায়নি।", "danger")
            return redirect(url_for("admin.newspaper_management_view"))

        audit_repo.log_action(
            username=current_username,
            action="update_placement",
            resource_type="article",
            resource_id=str(article_id),
            details={"placement": placement, "order": order, "is_pinned": is_pinned},
            ip_address=request.remote_addr,
        )

        if request.is_json:
            return jsonify({
                "success": True,
                "placement": updated.position_placement,
                "display_order": updated.display_order,
                "is_pinned": updated.is_pinned,
                "message": "লেআউট প্লেসমেন্ট ও ক্রম সফলভাবে সংরক্ষিত হয়েছে।",
            })

        flash(f"সংবাদ #{article_id}-এর পোর্টাল প্লেসমেন্ট ও ক্রম আপডেট করা হয়েছে।", "success")
    return redirect(url_for("admin.newspaper_management_view"))


@admin_bp.route("/newspaper/article/check-source/<int:article_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def check_article_source(article_id: int):
    """Audit the original source URL to see if it is active or has been removed/unpublished."""
    with get_db_session() as session:
        repo = ArticleRepository(session)
        audit_res = repo.check_source_url_status(article_id)
        article = repo.get_by_id(article_id)
        
        status = audit_res.get("source_status") or audit_res.get("status") or "ACTIVE"
        notice = audit_res.get("notice") or (article.source_removed_notice if article else "")
        
        return jsonify({
            "success": True,
            "status": status,
            "notice": notice,
            "source_url": article.original_source_url if article else "",
            "message": f"উৎস স্থিতি: {status}",
        })


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


# =========================================================================
# SECURITY OPERATIONS CENTER (SOC) & BLOCKCHAIN CONTROLLER ROUTES
# =========================================================================

@admin_bp.route("/newspaper/security/block-ip", methods=["POST"])
@login_required
@roles_required("admin")
def admin_block_ip():
    """Manually add an IP address to the firewall blacklist."""
    ip_address = request.form.get("ip_address", "").strip()
    reason = request.form.get("reason", "Manual administrator blacklist").strip()
    duration_hours_raw = request.form.get("duration_hours", "").strip()
    duration_hours = int(duration_hours_raw) if duration_hours_raw.isdigit() else None

    if not ip_address:
        flash("IP ঠিকানা প্রদান করা আবশ্যক।", "warning")
        return redirect(url_for("admin.newspaper_management_view", tab="security"))

    with get_db_session() as session:
        sec_repo = SecurityRepository(session)
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "admin")

        sec_repo.block_ip(
            ip_address=ip_address,
            reason=reason,
            blocked_by=current_username,
            threat_score=100,
            duration_hours=duration_hours,
        )
        audit_repo.log_action(
            username=current_username,
            action="ip_blacklist_add",
            resource_type="security",
            resource_id=ip_address,
            details={"ip": ip_address, "reason": reason, "duration_hours": duration_hours},
            ip_address=request.remote_addr,
        )
        dur_str = f" ({duration_hours} ঘণ্টার জন্য)" if duration_hours else " (স্থায়ী)"
        flash(f"IP ঠিকানা '{ip_address}' সফলভাবে ব্লকলিস্টে যুক্ত করা হয়েছে{dur_str}!", "success")

    return redirect(url_for("admin.newspaper_management_view", tab="security"))


@admin_bp.route("/newspaper/security/unblock-ip/<int:ip_id>", methods=["POST"])
@login_required
@roles_required("admin")
def admin_unblock_ip(ip_id: int):
    """Remove an IP address from the firewall blacklist."""
    with get_db_session() as session:
        sec_repo = SecurityRepository(session)
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "admin")

        if sec_repo.unblock_ip(ip_id):
            audit_repo.log_action(
                username=current_username,
                action="ip_blacklist_remove",
                resource_type="security",
                resource_id=str(ip_id),
                ip_address=request.remote_addr,
            )
            flash(f"IP ব্লকলিস্ট রেকর্ড #{ip_id} সফলভাবে প্রত্যাহার করা হয়েছে।", "success")
        else:
            flash("IP রেকর্ড পাওয়া যায়নি।", "danger")

    return redirect(url_for("admin.newspaper_management_view", tab="security"))


@admin_bp.route("/newspaper/security/block-country", methods=["POST"])
@login_required
@roles_required("admin")
def admin_block_country():
    """Add a country to the geographic firewall."""
    country_code = request.form.get("country_code", "").strip().upper()
    country_name = request.form.get("country_name", "").strip()
    reason = request.form.get("reason", "Geographic firewall security policy").strip()

    if not country_code or len(country_code) != 2:
        flash("সঠিক ২ অক্ষরের ISO কান্ট্রি কোড (যেমন: RU, CN, KP) প্রদান করুন।", "warning")
        return redirect(url_for("admin.newspaper_management_view", tab="security"))

    with get_db_session() as session:
        sec_repo = SecurityRepository(session)
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "admin")

        sec_repo.block_country(country_code=country_code, country_name=country_name, reason=reason)
        audit_repo.log_action(
            username=current_username,
            action="country_firewall_add",
            resource_type="security",
            resource_id=country_code,
            details={"country_code": country_code, "country_name": country_name, "reason": reason},
            ip_address=request.remote_addr,
        )
        flash(f"দেশ '{country_code}' ({country_name or country_code}) জিও-ফায়ারওয়ালে ব্লক করা হয়েছে।", "success")

    return redirect(url_for("admin.newspaper_management_view", tab="security"))


@admin_bp.route("/newspaper/security/toggle-country/<int:country_id>", methods=["POST"])
@login_required
@roles_required("admin")
def admin_toggle_country(country_id: int):
    """Toggle country geo-blocking rule active/inactive."""
    with get_db_session() as session:
        sec_repo = SecurityRepository(session)
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "admin")

        state = sec_repo.toggle_country(country_id)
        audit_repo.log_action(
            username=current_username,
            action="country_firewall_toggle",
            resource_type="security",
            resource_id=str(country_id),
            details={"is_active": state},
            ip_address=request.remote_addr,
        )
        status_label = "সক্রিয় (Active)" if state else "নিষ্ক্রিয় (Disabled)"
        flash(f"জিও-ফায়ারওয়াল রুল #{country_id}: {status_label} করা হয়েছে।", "success")

    return redirect(url_for("admin.newspaper_management_view", tab="security"))


@admin_bp.route("/newspaper/security/delete-country/<int:country_id>", methods=["POST"])
@login_required
@roles_required("admin")
def admin_delete_country(country_id: int):
    """Delete country geo-blocking rule."""
    with get_db_session() as session:
        sec_repo = SecurityRepository(session)
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "admin")

        if sec_repo.delete_country(country_id):
            audit_repo.log_action(
                username=current_username,
                action="country_firewall_delete",
                resource_type="security",
                resource_id=str(country_id),
                ip_address=request.remote_addr,
            )
            flash(f"জিও-ফায়ারওয়াল রুল #{country_id} মুছে ফেলা হয়েছে।", "success")
        else:
            flash("রুল মোছা যায়নি।", "danger")

    return redirect(url_for("admin.newspaper_management_view", tab="security"))


@admin_bp.route("/newspaper/blockchain/audit", methods=["GET", "POST"])
@login_required
@roles_required("admin", "editor")
def blockchain_audit_scan():
    """Trigger full end-to-end cryptographic blockchain ledger integrity audit."""
    with get_db_session() as session:
        ledger_repo = BlockchainLedgerRepository(session)
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "admin")

        result = ledger_repo.audit_full_chain()
        audit_repo.log_action(
            username=current_username,
            action="blockchain_audit_scan",
            resource_type="blockchain",
            details=result,
            ip_address=request.remote_addr,
        )

        if request.is_json or request.args.get("format") == "json":
            return jsonify(result)

        if result.get("chain_valid"):
            flash(f"✅ ব্লকচেইন অডিট সম্পন্ন: সর্বমোট {result.get('total_blocks')} টি ব্লক শতভাগ অক্ষত ও বৈধ!", "success")
        else:
            flash(f"⚠️ সতর্কতা: ব্লকচেইন অডিটে {len(result.get('tampered_blocks', []))} টি অমিল বা টেম্পারিং ধরা পড়েছে!", "danger")

    return redirect(url_for("admin.newspaper_management_view", tab="security"))


@admin_bp.route("/newspaper/blockchain/mint-missing", methods=["POST"])
@login_required
@roles_required("admin")
def blockchain_mint_missing():
    """Batch-mint cryptographic blocks for legacy articles lacking blockchain proofs."""
    with get_db_session() as session:
        ledger_repo = BlockchainLedgerRepository(session)
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "admin")

        count = ledger_repo.mint_all_unmined_articles()
        audit_repo.log_action(
            username=current_username,
            action="blockchain_batch_mint",
            resource_type="blockchain",
            details={"minted_count": count},
            ip_address=request.remote_addr,
        )
        flash(f"সফলভাবে {count} টি পুরনো সংবাদের ক্রিপ্টোগ্রাফিক ব্লক মিন্ট ও ডিজিটাল সাইন করা হয়েছে!", "success")

    return redirect(url_for("admin.newspaper_management_view", tab="security"))


@admin_bp.route("/newspaper/blockchain/verify-article/<int:article_id>", methods=["GET", "POST"])
@login_required
@roles_required("admin", "editor")
def blockchain_verify_article_endpoint(article_id: int):
    """Verify an individual article's cryptographic hashes against the immutable ledger."""
    with get_db_session() as session:
        ledger_repo = BlockchainLedgerRepository(session)
        is_valid, message, details = ledger_repo.verify_article_ledger(article_id)

        return jsonify({
            "article_id": article_id,
            "is_valid": is_valid,
            "message": message,
            "details": details,
        })


# ==============================================================================
# Autonomous AI Brain Emergency Encryption Vault Endpoints
# ==============================================================================

@admin_bp.route("/newspaper/security/vault/settings", methods=["POST"])
@login_required
@roles_required("admin")
def update_vault_settings():
    """Update AI Brain Auto-Lockdown thresholds and security notification email."""
    auto_lockdown = bool(request.form.get("auto_lockdown_enabled"))
    threshold = int(request.form.get("threat_threshold_score", 75) or 75)
    email = request.form.get("recipient_email", "").strip()

    with get_db_session() as session:
        repo = EmergencyVaultRepository(session)
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "admin")

        repo.update_settings(
            auto_lockdown_enabled=auto_lockdown,
            threat_threshold_score=threshold,
            recipient_email=email,
        )
        audit_repo.log_action(
            username=current_username,
            action="VAULT_SETTINGS_UPDATED",
            resource_type="EMERGENCY_VAULT",
            details={"auto_lockdown": auto_lockdown, "threshold": threshold, "email": email},
            ip_address=request.remote_addr,
        )
        flash("এআই ব্রেন অটোনোমাস ডিফেন্স ও সিকিউরিটি ইমেইল কনফিগারেশন সংরক্ষিত হয়েছে।", "success")

    return redirect(url_for("admin.newspaper_management_view", tab="security"))


@admin_bp.route("/newspaper/security/vault/lockdown", methods=["POST"])
@login_required
@roles_required("admin")
def trigger_emergency_lockdown_route():
    """Manually activate the Emergency Self-Encryption Kill-Switch."""
    custom_reason = request.form.get("reason", "Manual Admin Emergency Lockdown Activated").strip()
    target_email = request.form.get("recipient_email", "").strip()

    with get_db_session() as session:
        vault_engine = get_emergency_vault()
        current_username = flask_session.get("username", "admin")

        res = vault_engine.trigger_lockdown(
            session=session,
            trigger_type="MANUAL_ADMIN_KILLSWITCH",
            actor=current_username,
            custom_reason=custom_reason,
            recipient_email=target_email or None,
        )

        if res.get("success"):
            flash(
                f"🚨 জরুরি ভল্ট লকডাউন ও AES-256 এনক্রিপশন সক্রিয় হয়েছে! {res.get('encrypted_articles_count')}টি আর্টিকেল এনক্রিপ্ট করা হয়েছে। আপনার মাস্টার রিকভারি কোড [{res.get('unlock_code')}] ইমেইল ({res.get('recipient_email')}) ঠিকানায় পাঠানো হয়েছে।",
                "danger",
            )
        else:
            flash(res.get("message", "লকডাউন সক্রিয় করা যায়নি।"), "warning")

    return redirect(url_for("admin.newspaper_management_view", tab="security"))


@admin_bp.route("/newspaper/security/vault/simulate-attack", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def simulate_attack_route():
    """Simulate a cyberattack vector to test the AI Brain's automated defense response."""
    attack_type = request.form.get("attack_type", "SQL_INJECTION_CLUSTER").strip()

    with get_db_session() as session:
        vault_engine = get_emergency_vault()
        res = vault_engine.simulate_ai_hack_attempt(session, attack_type=attack_type)
        assessment = res.get("threat_assessment", {})

        if assessment.get("auto_lockdown_triggered"):
            flash(
                f"🚨 এআই ব্রেন স্বয়ংক্রিয় প্রতিরক্ষা সক্রিয়! থ্রেট লেভেল ছিল {assessment.get('threat_score')}/100। সিস্টেম স্বয়ংক্রিয়ভাবে লকডাউন ও এনক্রিপ্ট হয়েছে এবং ইমেইলে মাস্টার কি পাঠানো হয়েছে।",
                "danger",
            )
        else:
            flash(
                f"🛡️ সিমুলেটেড আক্রমণ প্রতিহত হয়েছে ({res.get('simulated_attack_type')})। বর্তমান থ্রেট স্কোর: {assessment.get('threat_score')}/100 ({assessment.get('threat_status')})।",
                "warning" if assessment.get("threat_score", 0) >= 50 else "info",
            )

    return redirect(url_for("admin.newspaper_management_view", tab="security"))


@admin_bp.route("/newspaper/security/vault/decrypt", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def decrypt_and_restore_vault_route():
    """Enter the secret recovery key to decrypt data and reactivate the news portal."""
    unlock_code = request.form.get("unlock_code", "").strip()

    if not unlock_code:
        flash("অনুগ্রহ করে জরুরি রিকভারি কোড প্রদান করুন।", "warning")
        return redirect(url_for("admin.newspaper_management_view", tab="security"))

    with get_db_session() as session:
        vault_engine = get_emergency_vault()
        current_username = flask_session.get("username", "admin")
        res = vault_engine.unlock_and_restore(session, unlock_code=unlock_code, actor=current_username)

        if res.get("success"):
            flash(f"✅ {res.get('message')}", "success")
        else:
            flash(f"❌ {res.get('message')}", "danger")

    return redirect(url_for("admin.newspaper_management_view", tab="security"))


@admin_bp.route("/newspaper/security/vault/status", methods=["GET"])
@login_required
def vault_status_json():
    """JSON endpoint for live threat gauge & emergency vault telemetry."""
    with get_db_session() as session:
        vault_repo = EmergencyVaultRepository(session)
        vault_engine = get_emergency_vault()
        state = vault_repo.get_vault_state()
        assessment = vault_engine.assess_threat_status(session)

        return jsonify({
            "vault_state": state.to_dict(),
            "threat_assessment": assessment,
        })


# ==============================================================================
# Heavy DataHub & High Capacity Storage Management Endpoints
# ==============================================================================

@admin_bp.route("/newspaper/datahub/optimize", methods=["POST"])
@login_required
@roles_required("admin")
def optimize_database_route():
    """Execute high-capacity database defragmentation, vacuum, and memory reclaim."""
    with get_db_session() as session:
        heavy_mgr = get_heavy_data_manager()
        current_username = flask_session.get("username", "admin")
        res = heavy_mgr.optimize_database(session, actor=current_username)

        if res.get("success"):
            flash(f"✅ {res.get('message')}", "success")
        else:
            flash(f"❌ {res.get('message')}", "danger")

    return redirect(url_for("admin.newspaper_management_view", tab="datahub"))


@admin_bp.route("/newspaper/datahub/bulk-archive", methods=["POST"])
@login_required
@roles_required("admin")
def bulk_archive_route():
    """Bulk archive stale non-pinned articles older than specified days."""
    days = int(request.form.get("days_old", 180) or 180)
    with get_db_session() as session:
        heavy_mgr = get_heavy_data_manager()
        current_username = flask_session.get("username", "admin")
        res = heavy_mgr.bulk_archive_stale_articles(session, days_old=days, actor=current_username)
        flash(f"📦 {res.get('message')}", "info")

    return redirect(url_for("admin.newspaper_management_view", tab="datahub"))


@admin_bp.route("/newspaper/datahub/rebuild-index", methods=["POST"])
@login_required
@roles_required("admin")
def rebuild_search_index_route():
    """Rebuild full-text search indexes for high-throughput searching."""
    with get_db_session() as session:
        heavy_mgr = get_heavy_data_manager()
        current_username = flask_session.get("username", "admin")
        res = heavy_mgr.rebuild_search_index(session, actor=current_username)
        flash(f"🔍 {res.get('message')}", "success" if res.get("success") else "danger")

    return redirect(url_for("admin.newspaper_management_view", tab="datahub"))


@admin_bp.route("/newspaper/datahub/media-sync", methods=["POST"])
@login_required
@roles_required("admin")
def media_cloud_sync_route():
    """Batch synchronize media cache to Cloud Storage providers."""
    with get_db_session() as session:
        heavy_mgr = get_heavy_data_manager()
        current_username = flask_session.get("username", "admin")
        res = heavy_mgr.sync_media_to_cloud(session, actor=current_username)
        flash(f"☁️ {res.get('message')}", "success")

    return redirect(url_for("admin.newspaper_management_view", tab="datahub"))


# ==============================================================================
# Autonomous Pipeline Scheduler, Fake News Detector & Async Task Manager
# ==============================================================================

@admin_bp.route("/automation")
@login_required
@roles_required("admin", "editor")
def automation_view():
    """Automation Control Hub: Monitor periodic scheduled jobs, AI fake news detector, and live article stream."""
    from src.automation.scheduler import get_scheduler
    from src.automation.task_manager import get_task_manager

    scheduler = get_scheduler()
    task_manager = get_task_manager()

    scheduler_status = scheduler.get_status()
    recent_tasks = task_manager.list_tasks(limit=25)

    with get_db_session() as session:
        art_repo = ArticleRepository(session)
        config_repo = SiteConfigRepository(session)
        
        fake_news_policy = config_repo.get_fake_news_policy()
        max_fake = float(fake_news_policy.get("max_fake_tolerance_pct", 50.0))
        automation_kpis = art_repo.get_automation_kpis()
        live_feed = art_repo.get_automation_live_feed(limit=25, max_allowed_fake_pct=max_fake)

    return render_template(
        "admin_automation.html",
        scheduler_status=scheduler_status,
        recent_tasks=recent_tasks,
        fake_news_policy=fake_news_policy,
        automation_kpis=automation_kpis,
        live_feed=live_feed,
    )


@admin_bp.route("/automation/fake-news-policy", methods=["POST"])
@login_required
@roles_required("admin")
def automation_update_fake_news_policy():
    """Update global AI Fake News tolerance threshold and publishing gates."""
    max_fake = float(request.form.get("max_fake_tolerance_pct", 50.0))
    auto_pub = request.form.get("auto_publish_enabled") == "1"
    quarantine = request.form.get("quarantine_high_fake") == "1"
    social_disp = request.form.get("social_dispatch_enabled") == "1"
    strict_mode = request.form.get("strict_mode") == "1"

    if max_fake <= 20.0:
        policy_name = f"কঠোর সুরক্ষা গেট (<= {max_fake:.0f}% ফেক অনুমোদিত)"
    elif max_fake <= 50.0:
        policy_name = f"ভারসাম্যপূর্ণ/সহনশীল গেট (<= {max_fake:.0f}% ফেক অনুমোদিত)"
    else:
        policy_name = f"উদার সহনশীলতা গেট (<= {max_fake:.0f}% ফেক অনুমোদিত)"

    policy_payload = {
        "max_fake_tolerance_pct": max_fake,
        "auto_publish_enabled": auto_pub,
        "quarantine_high_fake": quarantine,
        "social_dispatch_enabled": social_disp,
        "strict_mode": strict_mode,
        "policy_name": policy_name,
    }

    with get_db_session() as session:
        config_repo = SiteConfigRepository(session)
        audit_repo = AuditLogRepository(session)
        current_username = flask_session.get("username", "admin")

        updated = config_repo.update_fake_news_policy(policy_payload)
        audit_repo.log_action(
            username=current_username,
            action="update_fake_news_policy",
            resource_type="automation_policy",
            details=updated,
            ip_address=request.remote_addr,
        )

    flash(f"✅ এআই ফেক নিউজ নীতি আপডেট সম্পন্ন! অনুমোদিত সর্বোচ্চ ফেক সীমা: {max_fake:.0f}% ({policy_name})", "success")
    return redirect(url_for("admin.automation_view"))


@admin_bp.route("/automation/run-full-cycle", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def automation_run_full_cycle():
    """Trigger immediate full AI Pilot Ingestion, Translation, Fact-Check & Auto-Publishing cycle."""
    from src.automation.ai_pilot_brain import AIPilotBrain

    with get_db_session() as session:
        config_repo = SiteConfigRepository(session)
        policy = config_repo.get_fake_news_policy()
        max_fake = float(policy.get("max_fake_tolerance_pct", 50.0))

    res = AIPilotBrain.ingest_and_autopilot_cycle(
        include_youtube=True,
        include_world=True,
        include_social=True,
        max_allowed_fake_pct=max_fake,
        max_per_source=3,
        trigger_social_broadcast=policy.get("social_dispatch_enabled", True),
    )

    flash(
        f"🚀 সম্পূর্ণ এআই অটোমেশন সাইকেল সম্পন্ন! "
        f"মোট ইনজেস্ট: {res['total_raw_ingested']} | "
        f"খাঁটি বলে স্বয়ংক্রিয় প্রকাশিত: {res['auto_published']} | "
        f"সোশ্যাল মিডিয়ায় প্রেরিত: {res['social_broadcasts']} | "
        f"রিভিউ কিউ: {res['review_queued']} | "
        f"ফেক/বাতিল: {res['rejected_or_archived']}",
        "success",
    )
    return redirect(url_for("admin.automation_view"))


@admin_bp.route("/automation/run-fact-check-audit", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def automation_run_fact_check_audit():
    """Run AI Fake News & Fact-Checking audit across all pending or recent news articles."""
    from src.nlp.fake_news_detector import FakeNewsDetectorEngine

    with get_db_session() as session:
        config_repo = SiteConfigRepository(session)
        art_repo = ArticleRepository(session)
        policy = config_repo.get_fake_news_policy()
        max_fake = float(policy.get("max_fake_tolerance_pct", 50.0))

        articles = session.query(Article).order_by(Article.id.desc()).limit(50).all()
        audited_count = 0
        promoted_count = 0
        quarantined_count = 0

        for art in articles:
            entities = art.extracted_entities or {}
            analysis = FakeNewsDetectorEngine.evaluate(
                title=art.title,
                content=art.content_text,
                source=art.source,
                author=art.author,
                max_allowed_fake_pct=max_fake,
            )
            entities["fake_news_analysis"] = analysis
            art.extracted_entities = entities
            audited_count += 1

            if analysis["fake_probability_pct"] <= max_fake and art.scrape_status in ["pending", "draft"]:
                art.scrape_status = "completed"
                promoted_count += 1
            elif analysis["fake_probability_pct"] > max_fake and art.scrape_status == "completed":
                art.scrape_status = "archived"
                quarantined_count += 1

        session.flush()

    flash(
        f"🔍 ফ্যাক্ট-চেকিং অডিট সম্পন্ন! মোট যাচাই: {audited_count} টি | "
        f"সহনশীলতায় অনুমোদিত: {promoted_count} টি | "
        f"ফেক হিসেবে কোয়ারেন্টাইন: {quarantined_count} টি।",
        "info",
    )
    return redirect(url_for("admin.automation_view"))


@admin_bp.route("/automation/article-override/<int:article_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def automation_article_override(article_id: int):
    """Manually override an article's status directly from the live automation stream."""
    from src.automation.social_broadcaster import UnifiedSocialBroadcaster

    action = request.form.get("action", "publish")
    art_dict = None
    with get_db_session() as session:
        art_repo = ArticleRepository(session)
        ledger_repo = BlockchainLedgerRepository(session)
        article = session.query(Article).filter(Article.id == article_id).first()

        if not article:
            flash("সংবাদ পাওয়া যায়নি।", "danger")
            return redirect(url_for("admin.automation_view"))

        if action == "publish":
            article.scrape_status = "completed"
            article.updated_at = datetime.utcnow()
            ledger_repo.mint_block_for_article(article.id)
            session.flush()
            art_dict = article.to_dict()
            flash(f"সংবাদ #{article.id} সফলভাবে লাইভ পোর্টালে প্রকাশিত এবং সোশ্যাল মিডিয়ায় ব্রডকাস্ট করা হয়েছে!", "success")
        elif action == "quarantine":
            article.scrape_status = "archived"
            article.updated_at = datetime.utcnow()
            session.flush()
            flash(f"সংবাদ #{article.id} স্থগিত ও কোয়ারেন্টাইন করা হয়েছে।", "warning")

    # Broadcast to social channels outside DB session to prevent nested transaction contention
    if art_dict:
        try:
            UnifiedSocialBroadcaster.broadcast_article(art_dict)
        except Exception as e:
            pass

    return redirect(url_for("admin.automation_view"))


@admin_bp.route("/automation/api/live-status", methods=["GET"])
@login_required
def automation_api_live_status():
    """Live Real-time JSON API endpoint returning live counters, policy, and recently evaluated news stream."""
    from src.automation.scheduler import get_scheduler
    from src.automation.task_manager import get_task_manager

    scheduler = get_scheduler()
    task_manager = get_task_manager()

    with get_db_session() as session:
        art_repo = ArticleRepository(session)
        config_repo = SiteConfigRepository(session)
        
        policy = config_repo.get_fake_news_policy()
        max_fake = float(policy.get("max_fake_tolerance_pct", 50.0))
        kpis = art_repo.get_automation_kpis()
        feed = art_repo.get_automation_live_feed(limit=25, max_allowed_fake_pct=max_fake)

    return jsonify({
        "scheduler": scheduler.get_status(),
        "policy": policy,
        "kpis": kpis,
        "recent_tasks": task_manager.list_tasks(limit=10),
        "live_feed": feed,
        "timestamp": datetime.utcnow().isoformat(),
    })


@admin_bp.route("/automation/toggle-scheduler", methods=["POST"])
@login_required
@roles_required("admin")
def automation_toggle_scheduler():
    """Start or Stop the autonomous background scheduler."""
    from src.automation.scheduler import get_scheduler

    scheduler = get_scheduler()
    if scheduler.is_active:
        scheduler.stop()
        flash("Autonomous background scheduler stopped.", "warning")
    else:
        scheduler.start()
        flash("Autonomous background scheduler started.", "success")

    return redirect(url_for("admin.automation_view"))


# ------------------------------------------------------------------------------
# Automation Jobs CRUD Endpoints
# ------------------------------------------------------------------------------

@admin_bp.route("/automation/job/create", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def automation_create_job():
    """[CREATE] Create a new scheduled recurring automation job."""
    from src.automation.scheduler import get_scheduler
    scheduler = get_scheduler()

    data = request.get_json(silent=True) or request.form
    name = (data.get("name") or "নতুন স্বয়ংক্রিয় জব").strip()
    name_bn = (data.get("name_bn") or name).strip()
    description = (data.get("description") or "স্বয়ংক্রিয় শিডিউলার জব").strip()
    job_type = (data.get("job_type") or "crawler").strip()
    interval_seconds = int(data.get("interval_seconds", 300))
    enabled = str(data.get("enabled", "true")).lower() in ["1", "true", "on", "yes"]

    params = {}
    if isinstance(data.get("params"), dict):
        params = data.get("params")
    else:
        # Extract form field params
        if "site_key" in data:
            params["site_key"] = data.get("site_key")
        if "max_pages" in data:
            params["max_pages"] = int(data.get("max_pages", 1))
        if "auto_publish_threshold" in data:
            params["auto_publish_threshold"] = float(data.get("auto_publish_threshold", 75.0))
        if "channel" in data:
            params["channel"] = data.get("channel")

    job = scheduler.create_custom_job(
        name=name,
        name_bn=name_bn,
        description=description,
        job_type=job_type,
        interval_seconds=interval_seconds,
        params=params,
        enabled=enabled,
    )

    if request.is_json:
        return jsonify({"status": "success", "message": f"Job '{name}' created successfully!", "job": job.to_dict()})

    flash(f"✅ নতুন অটোমেশন জব '{name}' সফলভাবে তৈরি করা হয়েছে! (ব্যবধান: {interval_seconds}s)", "success")
    return redirect(url_for("admin.automation_view"))


@admin_bp.route("/automation/job/update/<job_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def automation_update_job(job_id: str):
    """[UPDATE] Modify existing job parameters, name, interval, or state."""
    from src.automation.scheduler import get_scheduler
    scheduler = get_scheduler()

    data = request.get_json(silent=True) or request.form
    name = data.get("name")
    name_bn = data.get("name_bn")
    description = data.get("description")
    interval_raw = data.get("interval_seconds")
    interval_seconds = int(interval_raw) if interval_raw is not None else None
    enabled = str(data.get("enabled", "")).lower() in ["1", "true", "on", "yes"] if "enabled" in data else None

    params = None
    if "params" in data and isinstance(data["params"], dict):
        params = data["params"]

    updated = scheduler.update_job(
        job_id=job_id,
        name=name,
        name_bn=name_bn,
        description=description,
        interval_seconds=interval_seconds,
        enabled=enabled,
        params=params,
    )

    if not updated:
        if request.is_json:
            return jsonify({"status": "error", "message": f"Job '{job_id}' not found."}), 404
        flash(f"ত্রুটি: জব '{job_id}' পাওয়া যায়নি।", "danger")
        return redirect(url_for("admin.automation_view"))

    if request.is_json:
        return jsonify({"status": "success", "message": f"Job '{updated.name}' updated!", "job": updated.to_dict()})

    flash(f"✅ জব '{updated.name}' সফলভাবে আপডেট করা হয়েছে!", "success")
    return redirect(url_for("admin.automation_view"))


@admin_bp.route("/automation/job/delete/<job_id>", methods=["POST"])
@login_required
@roles_required("admin")
def automation_delete_job(job_id: str):
    """[DELETE] Remove a custom scheduled job."""
    from src.automation.scheduler import get_scheduler
    scheduler = get_scheduler()

    success = scheduler.delete_custom_job(job_id)
    if success:
        if request.is_json:
            return jsonify({"status": "success", "message": f"Job '{job_id}' deleted."})
        flash(f"🗑️ জব '{job_id}' মুছে ফেলা হয়েছে।", "success")
    else:
        if request.is_json:
            return jsonify({"status": "error", "message": f"Could not delete job '{job_id}'."}), 400
        flash(f"ত্রুটি: জব '{job_id}' মুছে ফেলা যায়নি।", "danger")

    return redirect(url_for("admin.automation_view"))


@admin_bp.route("/automation/job/toggle/<job_id>", methods=["POST"])
@admin_bp.route("/automation/toggle-job/<job_id>", methods=["POST"])
@login_required
@roles_required("admin")
def automation_toggle_job(job_id: str):
    """Enable or disable a specific recurring job."""
    from src.automation.scheduler import get_scheduler
    scheduler = get_scheduler()

    job = scheduler.jobs.get(job_id)
    if not job:
        if request.is_json:
            return jsonify({"status": "error", "message": f"Job '{job_id}' not found."}), 404
        flash(f"Job '{job_id}' not found.", "danger")
        return redirect(url_for("admin.automation_view"))

    new_state = not job.enabled
    scheduler.toggle_job(job_id, new_state)
    state_str = "সক্রিয় (Active)" if new_state else "স্থগিত (Paused)"

    if request.is_json:
        return jsonify({"status": "success", "enabled": new_state, "message": f"Job '{job.name}' is now {state_str}."})

    flash(f"জব '{job.name}' সফলভাবে {state_str} করা হয়েছে।", "info")
    return redirect(url_for("admin.automation_view"))


@admin_bp.route("/automation/job/trigger/<job_id>", methods=["POST"])
@admin_bp.route("/automation/trigger-job/<job_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def automation_trigger_job(job_id: str):
    """Trigger immediate execution of a scheduled recurring job."""
    from src.automation.scheduler import get_scheduler
    scheduler = get_scheduler()

    res = scheduler.trigger_job_now(job_id)
    if request.is_json:
        return jsonify(res)

    if res.get("status") == "started":
        flash(f"⚡ জব '{job_id}' অবিলম্বে ব্যাকগ্রাউন্ডে রান করা হয়েছে!", "success")
    else:
        flash(res.get("message", "Could not trigger job."), "warning")

    return redirect(url_for("admin.automation_view"))


@admin_bp.route("/automation/batch-action", methods=["POST"])
@login_required
@roles_required("admin")
def automation_batch_action():
    """Perform batch operations on all scheduler jobs."""
    from src.automation.scheduler import get_scheduler
    scheduler = get_scheduler()

    data = request.get_json(silent=True) or request.form
    action = data.get("action", "enable_all")
    res = scheduler.batch_action(action)

    if request.is_json:
        return jsonify(res)

    flash(f"⚡ ব্যাচ অ্যাকশন: {res.get('message')}", "success")
    return redirect(url_for("admin.automation_view"))


@admin_bp.route("/automation/update-interval/<job_id>", methods=["POST"])
@login_required
@roles_required("admin")
def automation_update_interval(job_id: str):
    """Update job recurrence frequency interval in seconds."""
    from src.automation.scheduler import get_scheduler
    scheduler = get_scheduler()

    interval = int(request.form.get("interval_seconds", 60))
    if scheduler.update_job_interval(job_id, interval):
        flash(f"Updated interval for '{job_id}' to {interval} seconds.", "success")
    else:
        flash(f"Could not update interval for '{job_id}'.", "danger")

    return redirect(url_for("admin.automation_view"))


@admin_bp.route("/automation/api/jobs", methods=["GET"])
@login_required
def automation_api_jobs():
    """JSON API endpoint returning full list of jobs with execution stats."""
    from src.automation.scheduler import get_scheduler
    scheduler = get_scheduler()
    return jsonify(scheduler.get_status())


@admin_bp.route("/automation/api/job/<job_id>", methods=["GET"])
@login_required
def automation_api_single_job(job_id: str):
    """JSON API endpoint returning single job details and execution history."""
    from src.automation.scheduler import get_scheduler
    scheduler = get_scheduler()
    job = scheduler.jobs.get(job_id)
    if not job:
        return jsonify({"status": "error", "message": f"Job '{job_id}' not found."}), 404
    return jsonify({"status": "success", "job": job.to_dict()})


@admin_bp.route("/automation/submit-task", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def automation_submit_task():
    """Dispatch an asynchronous heavy background job (Crawl, Train, Fine-tune, Eval, Full Pipeline)."""
    from src.automation.task_manager import get_task_manager

    task_type = request.form.get("task_type", "").strip().upper()
    task_manager = get_task_manager()

    if task_type == "CRAWL":
        site_key = request.form.get("site_key", "prothom_alo")
        max_pages = int(request.form.get("max_pages", 2))
        task = task_manager.submit_crawl_task(site_key=site_key, max_pages=max_pages)
        flash(f"Asynchronous Portal Crawl task #{task.task_id} queued!", "success")

    elif task_type == "BASE_TRAIN":
        epochs = int(request.form.get("epochs", 1))
        batch_size = int(request.form.get("batch_size", 2))
        limit = int(request.form.get("limit", 0)) or None
        task = task_manager.submit_base_train_task(epochs=epochs, batch_size=batch_size, limit=limit)
        flash(f"Asynchronous Base LLM Training task #{task.task_id} queued!", "success")

    elif task_type == "FINETUNE":
        epochs = int(request.form.get("epochs", 2))
        batch_size = int(request.form.get("batch_size", 2))
        task = task_manager.submit_finetune_task(epochs=epochs, batch_size=batch_size)
        flash(f"Asynchronous LoRA Fine-Tuning task #{task.task_id} queued!", "success")

    elif task_type == "EVALUATION":
        task = task_manager.submit_evaluation_task()
        flash(f"Asynchronous Multi-Task Evaluation task #{task.task_id} queued!", "success")

    elif task_type == "FULL_PIPELINE":
        use_mock = request.form.get("use_mock") == "1"
        base_epochs = int(request.form.get("base_epochs", 1))
        finetune_epochs = int(request.form.get("finetune_epochs", 2))
        task = task_manager.submit_full_pipeline_task(
            use_mock_server=use_mock,
            base_epochs=base_epochs,
            finetune_epochs=finetune_epochs,
        )
        flash(f"Asynchronous Full Pipeline task #{task.task_id} queued!", "success")

    else:
        flash(f"Unknown task type: '{task_type}'.", "danger")

    return redirect(url_for("admin.automation_view"))


@admin_bp.route("/automation/api/tasks", methods=["GET"])
@login_required
def automation_api_tasks():
    """JSON API endpoint returning recent asynchronous tasks for live polling."""
    from src.automation.task_manager import get_task_manager

    task_manager = get_task_manager()
    return jsonify(task_manager.list_tasks(limit=30))


@admin_bp.route("/automation/api/task/<task_id>", methods=["GET"])
@login_required
def automation_api_single_task(task_id: str):
    """JSON API endpoint returning details for a single task."""
    from src.automation.task_manager import get_task_manager

    task_manager = get_task_manager()
    task = task_manager.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(task.to_dict())


# =========================================================================
# EMERGENCY CIPHER VAULT & SECURITY CONTROLS
# =========================================================================

@admin_bp.route("/newspaper/security/vault/update-settings", methods=["POST"])
@admin_bp.route("/update_vault_settings", methods=["POST"])
@login_required
@roles_required("admin")
def update_vault_settings():
    """Update AI Brain Emergency Vault defense threshold and manual/auto mode."""
    auto_lockdown = bool(request.form.get("auto_lockdown_enabled"))
    threat_threshold = int(request.form.get("threat_threshold_score", 85))
    recipient_email = request.form.get("recipient_email", "").strip() or "chief-security@daily-ai-alo.com"

    with get_db_session() as session:
        vault = get_emergency_vault()
        state = vault.get_or_create_state(session)
        state.auto_lockdown_enabled = auto_lockdown
        state.threat_threshold_score = threat_threshold
        state.recipient_email = recipient_email
        session.flush()

        mode_str = "স্বয়ংক্রিয় এআই ডিফেন্স (Autonomous)" if auto_lockdown else "ম্যানুয়াল মোড (Manual Mode - Safe)"
        flash(f"সিকিউরিটি ভল্ট পলিসি আপডেট সম্পন্ন: {mode_str}, থ্রেশহোল্ড: {threat_threshold}।", "success")

    return redirect(url_for("admin.newspaper_management_view", tab="security"))


@admin_bp.route("/newspaper/security/vault/lockdown", methods=["POST"])
@admin_bp.route("/trigger_emergency_lockdown_route", methods=["POST"])
@login_required
@roles_required("admin")
def trigger_emergency_lockdown_route():
    """Manually trigger emergency AES-256 vault encryption and lockdown."""
    reason = request.form.get("reason", "Manual Administrator Emergency Vault Lockdown Activated")
    recipient_email = request.form.get("recipient_email", "chief-security@daily-ai-alo.com")
    current_username = flask_session.get("username", "admin")

    with get_db_session() as session:
        vault = get_emergency_vault()
        result = vault.trigger_lockdown(
            session=session,
            trigger_type="MANUAL_ADMIN_KILLSWITCH",
            actor=current_username,
            custom_reason=reason,
            recipient_email=recipient_email,
        )
        if result.get("success"):
            code = result.get("unlock_code")
            flash(f"🚨 জরুরি লকডাউন ও এনক্রিপশন সফল! মাস্টার রিকভারি কোড: {code} (ইমেইলে পাঠানো হয়েছে)", "danger")
        else:
            flash(result.get("message", "লকডাউন কার্যকর করা যায়নি।"), "warning")

    return redirect(url_for("admin.newspaper_management_view", tab="security"))


@admin_bp.route("/newspaper/security/vault/decrypt", methods=["POST"])
@admin_bp.route("/decrypt_and_restore_vault_route", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def decrypt_and_restore_vault_route():
    """Decrypt and restore all articles with the master emergency recovery code."""
    unlock_code = request.form.get("unlock_code", "").strip()
    current_username = flask_session.get("username", "admin")

    if not unlock_code:
        flash("অনুগ্রহ করে মাস্টার ডিক্রিপশন কোড প্রদান করুন।", "warning")
        return redirect(url_for("admin.newspaper_management_view", tab="security"))

    with get_db_session() as session:
        vault = get_emergency_vault()
        result = vault.unlock_and_restore(
            session=session,
            unlock_code=unlock_code,
            actor=current_username,
        )
        if result.get("success"):
            flash(result.get("message"), "success")
        else:
            flash(result.get("message"), "danger")

    return redirect(url_for("admin.newspaper_management_view", tab="security"))


@admin_bp.route("/newspaper/security/vault/force-restore-all", methods=["POST"])
@admin_bp.route("/force_restore_all_news_route", methods=["POST"])
@login_required
@roles_required("admin")
def force_restore_all_news_route():
    """Emergency master reset: remove all encrypted news markers and restore clean database."""
    current_username = flask_session.get("username", "admin")
    with get_db_session() as session:
        vault = get_emergency_vault()
        result = vault.force_restore_and_unencrypt_all(session, actor=current_username)
        flash(result.get("message", "সকল সংবাদ সফলভাবে রিস্টোর ও আনলক করা হয়েছে।"), "success")

    return redirect(url_for("admin.newspaper_management_view", tab="security"))


@admin_bp.route("/newspaper/security/vault/simulate-attack", methods=["POST"])
@admin_bp.route("/simulate_attack_route", methods=["POST"])
@login_required
@roles_required("admin")
def simulate_attack_route():
    """Simulate an attack payload to test WAF and threat calculation."""
    attack_type = request.form.get("attack_type", "SQL_INJECTION_CLUSTER")
    with get_db_session() as session:
        vault = get_emergency_vault()
        result = vault.simulate_attack(session, attack_type=attack_type)
        flash(f"⚡ সিমুলেটেড আক্রমণ '{attack_type}' পরীক্ষা সফল! WAF দ্বারা আইপি প্রতিহত ও লগ করা হয়েছে।", "info")

    return redirect(url_for("admin.newspaper_management_view", tab="security"))


@admin_bp.route("/newspaper/security/vault/status", methods=["GET"])
@login_required
def vault_live_status():
    """JSON API for real-time vault and threat assessment."""
    with get_db_session() as session:
        vault = get_emergency_vault()
        assessment = vault.assess_threat_status(session)
        state = vault.get_or_create_state(session)
        return jsonify({
            "state": state.to_dict(),
            "assessment": assessment,
        })


