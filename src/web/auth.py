"""
Authentication & Role-Based Access Control (RBAC) Module for Flask.
Provides session login/logout helpers, current_user loader, and @roles_required decorators.
"""

from functools import wraps
from typing import Optional, List, Callable, Any
from flask import session, redirect, url_for, flash, request, abort, g, jsonify
from src.storage.database import get_db_session
from src.storage.models import User
from src.storage.repositories import UserRepository


def get_current_user() -> Optional[User]:
    """Retrieve currently authenticated user from Flask session."""
    if hasattr(g, "_current_user") and g._current_user is not None:
        return g._current_user

    user_id = session.get("user_id")
    if not user_id:
        g._current_user = None
        return None

    with get_db_session() as db_sess:
        repo = UserRepository(db_sess)
        user = repo.get_by_id(user_id)
        if user and user.is_active:
            # Expunge to make usable outside db session
            db_sess.expunge(user)
            g._current_user = user
            return user

    g._current_user = None
    return None


def login_user(user: User) -> None:
    """Set authentication session for user."""
    session["user_id"] = user.id
    session["username"] = user.username
    session["role"] = user.role
    session.permanent = True
    g._current_user = user


def logout_user() -> None:
    """Clear user authentication session."""
    session.clear()
    g._current_user = None


def login_required(f: Callable) -> Callable:
    """Decorator requiring an authenticated active user session."""
    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        user = get_current_user()
        if not user:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized", "message": "Authentication required."}), 401
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("auth.login_view", next=request.url))
        return f(*args, **kwargs)
    return decorated_function


def roles_required(*roles: str) -> Callable:
    """
    Decorator requiring the user to have at least one of the specified roles.
    Admin users bypass all role restrictions automatically.
    """
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args: Any, **kwargs: Any) -> Any:
            user = get_current_user()
            if not user:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Unauthorized", "message": "Authentication required."}), 401
                flash("Please log in to access this resource.", "warning")
                return redirect(url_for("auth.login_view", next=request.url))

            # Check role (admin has access to everything)
            if user.role == "admin" or user.role in roles:
                return f(*args, **kwargs)

            # Insufficient permissions
            if request.path.startswith("/api/"):
                return jsonify({
                    "error": "Forbidden",
                    "message": f"Insufficient permissions. Required one of: {roles}. Your role: '{user.role}'."
                }), 403

            flash(f"Access Denied: Your role ('{user.role}') lacks permission for this action.", "danger")
            return redirect(url_for("dashboard.index_view"))

        return decorated_function
    return decorator
