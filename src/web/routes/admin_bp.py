"""
Admin Management Blueprint.
Provides User and Role Management for Admin users.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from src.storage.database import get_db_session
from src.storage.repositories import UserRepository
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
