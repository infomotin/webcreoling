"""
Authentication Blueprint.
Handles User Login, Registration, Logout, and Profile Views.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from src.storage.database import get_db_session
from src.storage.repositories import UserRepository
from src.web.auth import login_user, logout_user, get_current_user, login_required

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login_view():
    """User login view."""
    if get_current_user():
        return redirect(url_for("dashboard.index_view"))

    if request.method == "POST":
        username_or_email = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        next_url = request.args.get("next") or url_for("dashboard.index_view")

        if not username_or_email or not password:
            flash("Please enter both username and password.", "danger")
            return render_template("login.html")

        with get_db_session() as session:
            repo = UserRepository(session)
            user = repo.authenticate(username_or_email, password)
            if user:
                # Expunge user to maintain state
                session.expunge(user)
                login_user(user)
                flash(f"Welcome back, {user.username}! (Role: {user.role.capitalize()})", "success")
                return redirect(next_url)
            else:
                flash("Invalid username or password.", "danger")

    return render_template("login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register_view():
    """User registration view."""
    if get_current_user():
        return redirect(url_for("dashboard.index_view"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        requested_role = request.form.get("role", "viewer").strip().lower()

        # Disallow self-registration as admin; default to viewer or analyst
        if requested_role not in ["viewer", "analyst", "editor"]:
            requested_role = "viewer"

        if not username or not email or not password:
            flash("All fields are required.", "danger")
            return render_template("register.html")

        with get_db_session() as session:
            repo = UserRepository(session)
            if repo.get_by_username(username):
                flash(f"Username '{username}' is already taken.", "danger")
                return render_template("register.html")
            if repo.get_by_email(email):
                flash(f"Email '{email}' is already registered.", "danger")
                return render_template("register.html")

            new_user = repo.create_user(
                username=username,
                email=email,
                password=password,
                role=requested_role,
            )
            session.commit()
            session.expunge(new_user)
            login_user(new_user)
            flash(f"Account created successfully as {new_user.role.capitalize()}!", "success")
            return redirect(url_for("dashboard.index_view"))

    return render_template("register.html")


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
