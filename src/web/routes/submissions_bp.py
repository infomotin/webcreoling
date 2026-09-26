"""Public submission intake: advertising inquiries, news submissions,
reporter applications. All route into the AI Agent approval workflow
(human-in-the-loop — nothing is published/sent without senior approval)."""

from flask import Blueprint, flash, redirect, render_template, request, url_for

submissions_bp = Blueprint("submissions", __name__)


def _form_bool(value) -> bool:
    return str(value or "").lower() in ("1", "true", "on", "yes")


@submissions_bp.route("/")
def index_view():
    active_type = request.args.get("type", "ad")
    if active_type not in ("ad", "news", "reporter"):
        active_type = "ad"
    return render_template("submissions.html", active_type=active_type)


@submissions_bp.route("/ad", methods=["POST"])
def ad_inquiry_submit():
    from src.automation.agent_controller import AgenticController

    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip()
    if not name or not email or "@" not in email:
        flash("নাম ও সঠিক ইমেইল প্রয়োজন। / Name and a valid email are required.", "danger")
        return redirect(url_for("submissions.index_view", type="ad"))

    res = AgenticController.submit_ad_inquiry(
        name=name,
        email=email,
        message=(request.form.get("message") or "").strip(),
        company=(request.form.get("company") or "").strip() or None,
        phone=(request.form.get("phone") or "").strip() or None,
        package_interest=(request.form.get("package_interest") or "").strip() or None,
        budget_note=(request.form.get("budget_note") or "").strip() or None,
    )
    if res.get("success"):
        flash(f"আপনার অনুসন্ধান গ্রহণ করা হয়েছে! উত্তরটি Ad Manager অনুমোদনের পর "
              f"ইমেইলে পাঠানো হবে (আবেদন #{res['inquiry_id']}). / "
              f"Inquiry received — reply will be sent after Ad Manager approval.", "success")
    else:
        flash(f"ব্যর্থ / Failed: {res.get('error', 'unknown error')}", "danger")
    return redirect(url_for("submissions.index_view", type="ad"))


@submissions_bp.route("/news", methods=["POST"])
def news_submit():
    from src.automation.agent_controller import AgenticController

    title = (request.form.get("title") or "").strip()
    content = (request.form.get("content") or "").strip()
    email = (request.form.get("email") or "").strip()
    if not title or len(content) < 50 or "@" not in email:
        flash("শিরোনাম, কমপক্ষে ৫০ অক্ষরের খসড়া ও সঠিক ইমেইল প্রয়োজন। / "
              "Title, ≥50 char body and valid email are required.", "danger")
        return redirect(url_for("submissions.index_view", type="news"))

    res = AgenticController.submit_news_submission(
        title=title,
        content=content,
        submitter_email=email,
        author_name=(request.form.get("author") or "").strip() or None,
        source_url=(request.form.get("source_url") or "").strip() or None,
        kind="external",
    )
    if res.get("success"):
        conf = res.get("combined_confidence")
        flash(f"সাবমিশন গ্রহণ — ফ্যাক্ট-চেক কনফিডেন্স {conf}%। Editorial Lead চূড়ান্ত "
              f"সিদ্ধান্ত নেবেন (#{res['submission_id']}). / Submitted for Editorial Lead review.",
              "success" if "low_confidence" not in (res.get("flags") or []) else "warning")
    else:
        flash(f"ব্যর্থ / Failed: {res.get('error', 'unknown error')}", "danger")
    return redirect(url_for("submissions.index_view", type="news"))


@submissions_bp.route("/reporter", methods=["POST"])
def reporter_apply():
    from src.automation.agent_controller import AgenticController

    full_name = (request.form.get("full_name") or "").strip()
    email = (request.form.get("email") or "").strip()
    if not full_name or "@" not in email:
        flash("পূর্ণ নাম ও সঠিক ইমেইল প্রয়োজন। / Full name and valid email required.", "danger")
        return redirect(url_for("submissions.index_view", type="reporter"))

    portfolio_raw = (request.form.get("portfolio_links") or "").strip()
    portfolio_links = [u.strip() for u in portfolio_raw.replace("\n", ",").split(",") if u.strip()]
    credentials = {
        "experience_years": (request.form.get("experience_years") or "").strip(),
        "outlet": (request.form.get("outlet") or "").strip(),
        "beat": (request.form.get("beat") or "").strip(),
        "credentials_note": (request.form.get("credentials_note") or "").strip(),
    }
    res = AgenticController.submit_reporter_application(
        full_name=full_name,
        email=email,
        phone=(request.form.get("phone") or "").strip() or None,
        credentials=credentials,
        portfolio_links=portfolio_links,
        sample_text=(request.form.get("sample_text") or "").strip(),
    )
    if res.get("success"):
        quality = (res.get("verification") or {}).get("quality_score", 0)
        flash(f"আবেদন জমা হয়েছে — ভেরিফিকেশন স্কোর {quality}/100। Onboarding Officer "
              f"অনুমোদনের পর রিপোর্টার অ্যাকাউন্ট তৈরি হবে (#{res['application_id']}).",
              "success")
    else:
        flash(f"ব্যর্থ / Failed: {res.get('error', 'unknown error')}", "danger")
    return redirect(url_for("submissions.index_view", type="reporter"))
