"""Reporter dashboard: submit posts for Editorial Lead review & track status."""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from src.web.auth import get_current_user, login_required, roles_required

reporter_bp = Blueprint("reporter", __name__)

REPORTER_ROLES = ("reporter", "editor", "admin")


@reporter_bp.route("/")
@login_required
@roles_required(*REPORTER_ROLES)
def index_view():
    from src.storage.database import get_db_session
    from src.storage.models import ApprovalRequest, NewsSubmission, ReporterApplication

    user = get_current_user()
    email = (user.email or "").lower() if user else ""
    username = user.username if user else ""

    with get_db_session() as session:
        my_submissions = [
            s.to_dict()
            for s in session.query(NewsSubmission)
            .filter(NewsSubmission.submitter_email == email)
            .order_by(NewsSubmission.id.desc())
            .limit(20)
            .all()
        ] if email else []
        my_application = None
        if email:
            app_row = (
                session.query(ReporterApplication)
                .filter(ReporterApplication.email == email)
                .order_by(ReporterApplication.id.desc())
                .first()
            )
            if app_row:
                my_application = app_row.to_dict()
        pending_count = 0
        if my_submissions:
            ids = [s["approval_request_id"] for s in my_submissions if s.get("approval_request_id")]
            if ids:
                from src.automation.agent_controller import OPEN_STATUSES
                pending_count = (
                    session.query(ApprovalRequest)
                    .filter(ApprovalRequest.id.in_(ids))
                    .filter(ApprovalRequest.status.in_(OPEN_STATUSES))
                    .count()
                )

    return render_template(
        "reporter.html",
        username=username,
        email=email,
        my_submissions=my_submissions,
        my_application=my_application,
        pending_count=pending_count,
    )


@reporter_bp.route("/submit", methods=["POST"])
@login_required
@roles_required(*REPORTER_ROLES)
def submit_post():
    from src.automation.agent_controller import AgenticController

    user = get_current_user()
    title = (request.form.get("title") or "").strip()
    content = (request.form.get("content") or "").strip()
    if not title or len(content) < 80:
        flash("শিরোনাম ও কমপক্ষে ৮০ অক্ষরের খসড়া প্রয়োজন। / Title and ≥80 char draft required.",
              "danger")
        return redirect(url_for("reporter.index_view"))

    email = (request.form.get("email") or user.email or "").strip() or \
        f"{user.username}@reporter.local"

    res = AgenticController.submit_news_submission(
        title=title,
        content=content,
        submitter_email=email,
        author_name=user.username,
        source_url=(request.form.get("source_url") or "").strip() or None,
        kind="reporter_post",
    )
    if res.get("success"):
        flash(f"পোস্ট জমা হয়েছে — Editorial Lead ফ্যাক্ট-চেক ও স্ক্রিনিংয়ের পর "
              f"চূড়ান্ত সিদ্ধান্ত নেবেন (#{res['submission_id']}). / "
              f"Post submitted for Editorial Lead review.", "success")
    else:
        flash(f"ব্যর্থ / Failed: {res.get('error', 'unknown error')}", "danger")
    return redirect(url_for("reporter.index_view"))
