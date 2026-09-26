"""
Admin Integrations Blueprint — Mail Server, SMS Gateway, SSLCommerz Payments,
OTP/Security settings, Subscription Plans and outbound message logs.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash

from src.storage.database import get_db_session
from src.storage.repositories import (
    SiteConfigRepository,
    SubscriptionPlan,
    SubscriptionPlanRepository,
    PaymentRepository,
    MessageLogRepository,
)
from src.web.auth import roles_required
from src.integrations import config_service
from src.integrations.config_service import (
    MAIL_KEY, SMS_KEY, PAYMENT_KEY, OTP_KEY,
)
from src.integrations.mail_service import send_mail
from src.integrations.sms_service import send_sms

integrations_bp = Blueprint("integrations", __name__)


def _load_all():
    return {
        "mail": config_service.get_mail_config(),
        "sms": config_service.get_sms_config(),
        "payment": config_service.get_payment_config(),
        "otp": config_service.get_otp_config(),
    }


@integrations_bp.route("/")
@roles_required("admin")
def index_view():
    """Integrations control center (Mail / SMS / Payment / OTP / Plans / Logs)."""
    tab = request.args.get("tab", "mail")
    if tab not in ("mail", "sms", "payment", "otp", "plans", "logs"):
        tab = "mail"

    configs = _load_all()
    with get_db_session() as session:
        plans = SubscriptionPlanRepository(session).all()
        transactions = PaymentRepository(session).all_transactions(limit=50)
        logs = MessageLogRepository(session).recent(limit=100)

    return render_template(
        "admin_integrations.html",
        active_tab=tab,
        mail_cfg=configs["mail"],
        sms_cfg=configs["sms"],
        payment_cfg=configs["payment"],
        otp_cfg=configs["otp"],
        masked_mail_password=config_service.mask_secret(configs["mail"].get("mail_password")),
        masked_sms_key=config_service.mask_secret(configs["sms"].get("api_key")),
        masked_store_password=config_service.mask_secret(configs["payment"].get("store_password")),
        plans=plans,
        transactions=transactions,
        logs=logs,
    )


@integrations_bp.route("/mail/save", methods=["POST"])
@roles_required("admin")
def mail_save():
    form = request.form
    config_service.save_config(MAIL_KEY, {
        "enabled": form.get("enabled") == "on",
        "mail_server": form.get("mail_server", "").strip(),
        "mail_port": int(form.get("mail_port") or 2525),
        "mail_username": form.get("mail_username", "").strip(),
        "mail_password": form.get("mail_password", "").strip(),
        "mail_use_tls": form.get("mail_use_tls") == "on",
        "mail_use_ssl": form.get("mail_use_ssl") == "on",
        "mail_default_sender": form.get("mail_default_sender", "").strip(),
    })
    flash("মেইল কনফিগ সেভ হয়েছে / Mail configuration saved.", "success")
    return redirect(url_for("integrations.index_view", tab="mail"))


@integrations_bp.route("/mail/test", methods=["POST"])
@roles_required("admin")
def mail_test():
    to = (request.form.get("to") or "").strip()
    subject = (request.form.get("subject") or "WebCreoling Test Mail / টেস্ট মেইল").strip()
    if not to or "@" not in to:
        flash("সঠিক ইমেইল দিন / Enter a valid email address.", "danger")
        return redirect(url_for("integrations.index_view", tab="mail"))
    with get_db_session() as session:
        result = send_mail(
            session, to, subject,
            "<p>✅ টেস্ট মেইল সফল / Test mail delivered successfully.</p>"
            "<p>WebCreoling Mail Server (Mailtrap sandbox) integration is working.</p>",
            "Test mail delivered successfully. / টেস্ট মেইল সফল।",
            purpose="test",
        )
    if result.get("ok"):
        state = "টেস্ট মেইল পাঠানো হয়েছে (সিমুলেটেড)" if result.get("simulated") else "টেস্ট মেইল পাঠানো হয়েছে"
        flash(f"{state} / Test mail sent to {to}.", "success")
    else:
        flash(f"মেইল পাঠানো যায়নি / Mail failed: {result.get('error')}", "danger")
    return redirect(url_for("integrations.index_view", tab="mail"))


@integrations_bp.route("/sms/save", methods=["POST"])
@roles_required("admin")
def sms_save():
    form = request.form
    config_service.save_config(SMS_KEY, {
        "enabled": form.get("enabled") == "on",
        "provider": form.get("provider", "").strip() or "Generic HTTP Gateway",
        "api_url": form.get("api_url", "").strip(),
        "api_key": form.get("api_key", "").strip(),
        "sender_id": form.get("sender_id", "").strip(),
        "method": (form.get("method") or "GET").upper(),
        "param_to": form.get("param_to", "to").strip() or "to",
        "param_text": form.get("param_text", "msg").strip() or "msg",
        "extra_params": form.get("extra_params", "").strip(),
        "test_mode": form.get("test_mode") == "on",
    })
    flash("SMS গেটওয়ে কনফিগ সেভ হয়েছে / SMS gateway configuration saved.", "success")
    return redirect(url_for("integrations.index_view", tab="sms"))


@integrations_bp.route("/sms/test", methods=["POST"])
@roles_required("admin")
def sms_test():
    phone = (request.form.get("phone") or "").strip()
    message = (request.form.get("message") or "WebCreoling test SMS / টেস্ট এসএমএস").strip()
    if not phone:
        flash("ফোন নম্বর দিন / Enter a phone number.", "danger")
        return redirect(url_for("integrations.index_view", tab="sms"))
    result = send_sms(phone, message, purpose="test")
    if result.get("ok"):
        state = "টেস্ট এসএমএস সিমুলেটেড" if result.get("simulated") else "টেস্ট এসএমএস পাঠানো হয়েছে"
        flash(f"{state} / Test SMS to {phone}.", "success")
    else:
        flash(f"এসএমএস ব্যর্থ / SMS failed: {result.get('error')}", "danger")
    return redirect(url_for("integrations.index_view", tab="sms"))


@integrations_bp.route("/payment/save", methods=["POST"])
@roles_required("admin")
def payment_save():
    form = request.form
    config_service.save_config(PAYMENT_KEY, {
        "provider": form.get("provider", "SSLCommerz").strip() or "SSLCommerz",
        "is_live": form.get("is_live") == "on",
        "store_id": form.get("store_id", "").strip(),
        "store_password": form.get("store_password", "").strip(),
        "sandbox_base_url": form.get("sandbox_base_url", "").strip() or "https://sandbox.sslcommerz.com",
        "live_base_url": form.get("live_base_url", "").strip() or "https://securepay.sslcommerz.com",
        "currency": (form.get("currency") or "BDT").strip().upper(),
    })
    flash("পেমেন্ট গেটওয়ে কনফিগ সেভ হয়েছে / Payment gateway configuration saved.", "success")
    return redirect(url_for("integrations.index_view", tab="payment"))


@integrations_bp.route("/otp/save", methods=["POST"])
@roles_required("admin")
def otp_save():
    form = request.form
    config_service.save_config(OTP_KEY, {
        "register_email_otp": form.get("register_email_otp") == "on",
        "login_2fa": form.get("login_2fa") == "on",
        "password_reset_otp": form.get("password_reset_otp") == "on",
        "sms_otp": form.get("sms_otp") == "on",
        "otp_length": int(form.get("otp_length") or 6),
        "otp_ttl_minutes": int(form.get("otp_ttl_minutes") or 10),
        "otp_max_attempts": int(form.get("otp_max_attempts") or 5),
        "otp_resend_cooldown_seconds": int(form.get("otp_resend_cooldown_seconds") or 60),
    })
    flash("OTP ও সিকিউরিটি সেটিংস সেভ হয়েছে / OTP & security settings saved.", "success")
    return redirect(url_for("integrations.index_view", tab="otp"))


@integrations_bp.route("/plans/create", methods=["POST"])
@roles_required("admin")
def plan_create():
    form = request.form
    code = (form.get("code") or "").strip().lower()
    name = (form.get("name") or "").strip()
    if not code or not name:
        flash("প্ল্যান কোড ও নাম দিন / Plan code and name are required.", "danger")
        return redirect(url_for("integrations.index_view", tab="plans"))
    with get_db_session() as session:
        repo = SubscriptionPlanRepository(session)
        if repo.get_by_code(code):
            flash(f"প্ল্যান কোড '{code}' আগেই আছে / Plan code already exists.", "danger")
        else:
            features = [f.strip() for f in (form.get("features") or "").split("\n") if f.strip()]
            repo.add(SubscriptionPlan(
                code=code,
                name=name,
                name_en=(form.get("name_en") or "").strip(),
                price=float(form.get("price") or 0),
                currency=(form.get("currency") or "BDT").strip().upper(),
                duration_days=int(form.get("duration_days") or 30),
                features=features,
                is_active=form.get("is_active") == "on",
                sort_order=int(form.get("sort_order") or 0),
            ))
            flash("নতুন সাবস্ক্রিপশন প্ল্যান তৈরি হয়েছে / Subscription plan created.", "success")
    return redirect(url_for("integrations.index_view", tab="plans"))


@integrations_bp.route("/plans/<int:plan_id>/delete", methods=["POST"])
@roles_required("admin")
def plan_delete(plan_id: int):
    with get_db_session() as session:
        repo = SubscriptionPlanRepository(session)
        plan = repo.get_by_id(plan_id)
        if plan:
            repo.delete(plan)
            flash("প্ল্যান মুছে ফেলা হয়েছে / Plan deleted.", "success")
    return redirect(url_for("integrations.index_view", tab="plans"))


@integrations_bp.route("/plans/<int:plan_id>/toggle", methods=["POST"])
@roles_required("admin")
def plan_toggle(plan_id: int):
    with get_db_session() as session:
        repo = SubscriptionPlanRepository(session)
        plan = repo.get_by_id(plan_id)
        if plan:
            plan.is_active = not plan.is_active
            session.flush()
            flash("প্ল্যান স্ট্যাটাস পরিবর্তিত / Plan status toggled.", "success")
    return redirect(url_for("integrations.index_view", tab="plans"))
