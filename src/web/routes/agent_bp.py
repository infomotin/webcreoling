"""AI Agent Controller routes: role-routed approval inbox with timeout escalation.

Access: admin + approval roles (editorial_lead, ad_manager, onboarding_officer)
plus editors as junior reviewers who may only FLAG for senior judgment.
"""

from flask import Blueprint, jsonify, redirect, render_template, request, url_for, flash

from src.web.auth import get_current_user, roles_required

agent_bp = Blueprint("agent", __name__)

# editors = junior screeners (flag only); senior roles give final verdicts; admin bypasses
APPROVAL_ROLES = ("admin", "editor", "editorial_lead", "ad_manager", "onboarding_officer")

REQUEST_TYPE_LABELS = {
    "ad_inquiry": ("বিজ্ঞাপন অনুসন্ধান", "Ad Inquiries"),
    "news_submission": ("নিউজ সাবমিশন", "News Submissions"),
    "editorial_review": ("রিপোর্টার পোস্ট রিভিউ", "Editorial Reviews"),
    "reporter_onboarding": ("রিপোর্টার অনবোর্ডিং", "Reporter Onboarding"),
}


@agent_bp.route("/")
@roles_required(*APPROVAL_ROLES)
def index_view():
    """Approval inbox: pending/flagged requests, audit trail & policy settings."""
    from src.automation.agent_controller import AgenticController

    active_type = request.args.get("type") or ""
    active_status = request.args.get("status") or ""
    data = AgenticController.inbox_view_data(
        request_type=active_type or None,
        status=active_status or None,
        limit=80,
        audit_limit=50,
    )
    return render_template(
        "agent.html",
        requests=data["requests"],
        audit=data["audit"],
        policy=data["policy"],
        open_count=data["open_count"],
        sweep=data["sweep"],
        active_type=active_type,
        active_status=active_status,
        type_labels=REQUEST_TYPE_LABELS,
    )


@agent_bp.route("/decision/<int:request_id>", methods=["POST"])
@roles_required(*APPROVAL_ROLES)
def decision_view(request_id: int):
    """Approve / reject / flag a request (role-checked inside the controller)."""
    from src.automation.agent_controller import AgenticController

    decision = (request.form.get("decision") or "").lower()
    note = request.form.get("note", "").strip()
    user = get_current_user()
    res = AgenticController.decide(request_id, decision, user, note)

    if res.get("success"):
        status = res.get("status", decision)
        if status == "flagged":
            flash(f"#{request_id} ফ্ল্যাগ করা হয়েছে — সিনিয়র রোলের চূড়ান্ত সিদ্ধান্ত অপেক্ষায়। "
                  f"Flagged for senior judgment.", "warning")
        else:
            flash(f"#{request_id} {status}. {res.get('message', '')}", "success")
    else:
        flash(f"সিদ্ধান্ত ব্যর্থ / Decision failed: {res.get('error', 'unknown')}", "danger")
    return redirect(request.referrer or url_for("agent.index_view"))


@agent_bp.route("/policy", methods=["POST"])
@roles_required("admin")
def policy_save():
    """Save approval timeout / auto-approval / role-recipient policy (admin only)."""
    from src.automation.agent_controller import AgenticController

    data = {
        "escalation_hours": max(1, int(request.form.get("escalation_hours", 6))),
        "auto_approve_hours": max(1, int(request.form.get("auto_approve_hours", 24))),
        "auto_approve_enabled": request.form.get("auto_approve_enabled") in ("1", "true", "on", "yes"),
        "max_escalation_level": max(0, min(3, int(request.form.get("max_escalation_level", 1)))),
        "notify_on_create": request.form.get("notify_on_create") in ("1", "true", "on", "yes"),
        "enabled": request.form.get("enabled") in ("1", "true", "on", "yes"),
        "role_recipients": {
            "editorial_lead": request.form.get("recipient_editorial_lead", "").strip(),
            "ad_manager": request.form.get("recipient_ad_manager", "").strip(),
            "onboarding_officer": request.form.get("recipient_onboarding_officer", "").strip(),
            "admin": request.form.get("recipient_admin", "").strip(),
        },
    }
    AgenticController.save_policy(data)
    flash("অনুমোদন পলিসি সংরক্ষিত হয়েছে / Approval policy saved.", "success")
    return redirect(url_for("agent.index_view"))


@agent_bp.route("/sweep", methods=["POST"])
@roles_required("admin")
def sweep_now():
    """Manually run the timeout escalation / auto-approval sweep."""
    from src.automation.agent_controller import AgenticController
    summary = AgenticController.sweep_timeouts()
    flash(f"সুইপ সম্পন্ন / Sweep complete: {summary}", "info")
    return redirect(url_for("agent.index_view"))


@agent_bp.route("/api/inbox")
@roles_required(*APPROVAL_ROLES)
def api_inbox():
    from src.automation.agent_controller import AgenticController
    data = AgenticController.inbox_view_data(
        request_type=request.args.get("type") or None,
        status=request.args.get("status") or None,
        limit=int(request.args.get("limit", 50)),
    )
    return jsonify({"success": True, **data})
