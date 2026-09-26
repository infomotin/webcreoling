"""
Authentication Blueprint.
Handles User Login, Registration, Logout, Profile Views,
OTP verification (register / login 2FA / password reset) and language toggle.
"""

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session,
)

from src.storage.database import get_db_session
from src.storage.repositories import UserRepository
from src.web.auth import login_user, logout_user, get_current_user, login_required
from src.integrations.config_service import get_otp_config
from src.integrations.otp_service import issue_code, verify_code, deliver_otp

auth_bp = Blueprint("auth", __name__)


def _mask_destination(value: str) -> str:
    """Mask an email/phone for display on the OTP screen."""
    if not value:
        return ""
    if "@" in value:
        name, domain = value.split("@", 1)
        head = name[:2] if len(name) > 2 else name[:1]
        return f"{head}***@{domain}"
    if len(value) <= 4:
        return "*" * len(value)
    return value[:3] + "*" * max(3, len(value) - 6) + value[-3:]


def _otp_mode():
    """Determine the pending OTP flow from the session."""
    if session.get("pending_registration"):
        return "register", "register_verify", session["pending_registration"].get("email")
    if session.get("pending_2fa"):
        return "login", "login_2fa", session["pending_2fa"].get("email")
    if session.get("pending_reset"):
        return "reset", "password_reset", session["pending_reset"].get("email")
    return None, None, None


def _issue_and_deliver(destination: str, purpose: str, channel: str = "email",
                       user_id=None):
    """Issue an OTP and deliver it. Returns (ok, message)."""
    cfg = get_otp_config()
    code, err = issue_code(destination, purpose, channel=channel, user_id=user_id, cfg=cfg)
    if err:
        if err.startswith("cooldown:"):
            wait = err.split(":", 1)[1]
            return False, f"আবার পাঠাতে {wait} সেকেন্ড অপেক্ষা করুন / Please wait {wait}s before resending."
        return False, f"OTP তৈরি ব্যর্থ / OTP issue failed: {err}"

    ttl = int(cfg.get("otp_ttl_minutes") or 10)
    result = deliver_otp(None, destination, code, purpose,
                         channel=channel, expires_minutes=ttl)
    if result.get("ok"):
        extra = " (সিমুলেটেড / simulated)" if result.get("simulated") else ""
        return True, f"ভেরিফিকেশন কোড পাঠানো হয়েছে{extra} / Code sent to {_mask_destination(destination)}."
    # Delivery failed — sandbox fallback so the user is never locked out
    return True, f"SMTP অদৃশ্য — স্যান্ডবক্স কোড: {code} / SMTP unavailable, sandbox code: {code}"


@auth_bp.route("/lang/<code>")
def lang_view(code: str):
    """Toggle the admin panel / site interface language (bn <-> en)."""
    session["lang"] = "en" if code.lower().startswith("e") else "bn"
    target = request.args.get("next") or request.referrer or url_for("dashboard.index_view")
    return redirect(target)


@auth_bp.route("/login", methods=["GET", "POST"])
def login_view():
    """User login view (optional OTP two-factor when enabled)."""
    if get_current_user():
        return redirect(url_for("dashboard.index_view"))

    if request.method == "POST":
        username_or_email = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        next_url = request.args.get("next") or url_for("dashboard.index_view")

        if not username_or_email or not password:
            flash("Please enter both username and password.", "danger")
            return render_template("login.html")

        with get_db_session() as session_db:
            repo = UserRepository(session_db)
            user = repo.authenticate(username_or_email, password)
            if user:
                otp_cfg = get_otp_config()
                if otp_cfg.get("login_2fa") and user.email:
                    session_db.expunge(user)
                    session["pending_2fa"] = {"user_id": user.id, "email": user.email, "next": next_url}
                    ok, msg = _issue_and_deliver(user.email, "login_2fa", "email", user_id=user.id)
                    flash(msg, "info" if ok else "warning")
                    return redirect(url_for("auth.verify_view"))
                # Expunge user to maintain state
                session_db.expunge(user)
                login_user(user)
                flash(f"Welcome back, {user.username}! (Role: {user.role.capitalize()})", "success")
                return redirect(next_url)
            else:
                flash("Invalid username or password.", "danger")

    return render_template("login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register_view():
    """User registration view (email OTP verification when enabled)."""
    if get_current_user():
        return redirect(url_for("dashboard.index_view"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        phone = request.form.get("phone", "").strip()
        requested_role = request.form.get("role", "viewer").strip().lower()

        # Disallow self-registration as admin; default to viewer or analyst
        if requested_role not in ["viewer", "analyst", "editor"]:
            requested_role = "viewer"

        if not username or not email or not password:
            flash("All fields are required.", "danger")
            return render_template("register.html")

        with get_db_session() as session_db:
            repo = UserRepository(session_db)
            if repo.get_by_username(username):
                flash(f"Username '{username}' is already taken.", "danger")
                return render_template("register.html")
            if repo.get_by_email(email):
                flash(f"Email '{email}' is already registered.", "danger")
                return render_template("register.html")

            otp_cfg = get_otp_config()
            if otp_cfg.get("register_email_otp"):
                session["pending_registration"] = {
                    "username": username,
                    "email": email,
                    "password": password,
                    "phone": phone,
                    "role": requested_role,
                }
                ok, msg = _issue_and_deliver(email, "register_verify", "email")
                flash(msg, "info" if ok else "warning")
                return redirect(url_for("auth.verify_view"))

            new_user = repo.create_user(
                username=username,
                email=email,
                password=password,
                role=requested_role,
            )
            session_db.commit()
            session_db.expunge(new_user)
            login_user(new_user)
            flash(f"Account created successfully as {new_user.role.capitalize()}!", "success")
            return redirect(url_for("dashboard.index_view"))

    return render_template("register.html")


@auth_bp.route("/verify", methods=["GET", "POST"])
def verify_view():
    """OTP verification screen for register / login 2FA / password reset."""
    mode, purpose, destination = _otp_mode()
    if mode is None:
        flash("সেশনের মেয়াদ শেষ হয়েছে / Verification session expired.", "warning")
        return redirect(url_for("auth.login_view"))

    cfg = get_otp_config()

    if request.method == "POST":
        code = request.form.get("code", "").strip()
        ok, reason = verify_code(destination, purpose, code, cfg=cfg)
        if not ok:
            messages = {
                "expired": "কোডের মেয়াদ শেষ / Code expired.",
                "already_used": "কোড আগেই ব্যবহার হয়েছে / Code already used.",
                "too_many_attempts": "অনেকবার ভুল হয়েছে / Too many wrong attempts.",
                "not_found": "কোড পাওয়া যায়নি / Code not found.",
            }
            flash(messages.get(reason, f"ভুল কোড / Invalid code ({reason})."), "danger")
            return render_template("otp_verify.html", mode=mode,
                                   destination=_mask_destination(destination), cfg=cfg)

        if mode == "register":
            data = session.pop("pending_registration", None)
            with get_db_session() as session_db:
                repo = UserRepository(session_db)
                new_user = repo.create_user(
                    username=data["username"],
                    email=data["email"],
                    password=data["password"],
                    role=data.get("role") or "viewer",
                )
                if hasattr(new_user, "phone"):
                    new_user.phone = data.get("phone") or None
                    new_user.is_verified = True
                session_db.commit()
                session_db.expunge(new_user)
                login_user(new_user)
            flash(f"ইমেইল ভেরিফাই সফল! অ্যাকাউন্ট তৈরি হয়েছে / Email verified. Account created!", "success")
            return redirect(url_for("dashboard.index_view"))

        if mode == "login":
            pending = session.pop("pending_2fa", None)
            with get_db_session() as session_db:
                repo = UserRepository(session_db)
                user = repo.get_by_id(pending["user_id"]) if pending else None
                if user and user.is_active:
                    session_db.expunge(user)
                    login_user(user)
                    flash(f"Two-factor verified. Welcome back, {user.username}!", "success")
                    return redirect(pending.get("next") or url_for("dashboard.index_view"))
            flash("ইউজার পাওয়া যায়নি / User not found.", "danger")
            return redirect(url_for("auth.login_view"))

        if mode == "reset":
            email = session.get("pending_reset", {}).get("email")
            session.pop("pending_reset", None)
            session["reset_email_ok"] = email
            flash("ভেরিফিকেশন সফল — নতুন পাসওয়ার্ড দিন / Verified — set a new password.", "success")
            return redirect(url_for("auth.reset_view"))

    return render_template("otp_verify.html", mode=mode,
                           destination=_mask_destination(destination), cfg=cfg)


@auth_bp.route("/verify/resend", methods=["POST"])
def verify_resend_view():
    """Re-send the current OTP (respects cooldown)."""
    mode, purpose, destination = _otp_mode()
    if mode is None:
        flash("সেশনের মেয়াদ শেষ / Verification session expired.", "warning")
        return redirect(url_for("auth.login_view"))
    user_id = session.get("pending_2fa", {}).get("user_id")
    ok, msg = _issue_and_deliver(destination, purpose, "email", user_id=user_id)
    flash(msg, "info" if ok else "warning")
    return redirect(url_for("auth.verify_view"))


@auth_bp.route("/forgot", methods=["GET", "POST"])
def forgot_view():
    """Request a password-reset OTP by email."""
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        if not email:
            flash("ইমেইল দিন / Enter your email.", "danger")
            return render_template("forgot_password.html")

        with get_db_session() as session_db:
            repo = UserRepository(session_db)
            user = repo.get_by_email(email)
            otp_cfg = get_otp_config()
            if user and otp_cfg.get("password_reset_otp"):
                session["pending_reset"] = {"email": email}
                ok, msg = _issue_and_deliver(email, "password_reset", "email", user_id=user.id)
                flash(msg, "info" if ok else "warning")
                return redirect(url_for("auth.verify_view"))
            # OTP disabled or unknown email — avoid account enumeration, generic message
            flash("যদি ইমেইলটি থাকে, পাসওয়ার্ড রিসেট নির্দেশনা পাঠানো হয়েছে। / If the email exists, reset instructions were sent.", "info")
            return redirect(url_for("auth.login_view"))
    return render_template("forgot_password.html")


@auth_bp.route("/reset", methods=["GET", "POST"])
def reset_view():
    """Set a new password after OTP verification."""
    if not session.get("reset_email_ok"):
        return redirect(url_for("auth.forgot_view"))

    if request.method == "POST":
        password = request.form.get("password", "").strip()
        confirm = request.form.get("confirm", "").strip()
        if not password or len(password) < 6:
            flash("পাসওয়ার্ড কমপক্ষে ৬ অক্ষর হতে হবে / Password must be at least 6 characters.", "danger")
            return render_template("reset_password.html")
        if password != confirm:
            flash("পাসওয়ার্ড মিলছে না / Passwords do not match.", "danger")
            return render_template("reset_password.html")

        email = session.pop("reset_email_ok", None)
        session.pop("pending_reset", None)
        with get_db_session() as session_db:
            repo = UserRepository(session_db)
            user = repo.get_by_email(email) if email else None
            if user:
                user.set_password(password)
                session_db.flush()
        flash("পাসওয়ার্ড পরিবর্তন হয়েছে — নতুন পাসওয়ার্ডে লগইন করুন / Password changed — please sign in.", "success")
        return redirect(url_for("auth.login_view"))
    return render_template("reset_password.html")


@auth_bp.route("/logout")
def logout_view():
    """Log out current user."""
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login_view"))


@auth_bp.route("/profile")
@login_required
def profile_view():
    """User profile overview."""
    user = get_current_user()
    return render_template("profile.html", user=user)
