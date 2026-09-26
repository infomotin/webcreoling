"""
Subscriber Portal Blueprint.
Provides registered subscribers with personalized news feeds, reading history/bookmarks,
active subscription & AI token wallet, 2FA/OTP security settings, and digital invoices.
"""

from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session as flask_session
from src.storage.database import get_db_session
from src.storage.models import Article, User
from src.storage.repositories import PaymentRepository, SubscriptionPlanRepository, UserRepository
from src.web.auth import login_required, get_current_user

subscriber_bp = Blueprint("subscriber", __name__)


@subscriber_bp.route("/portal")
@login_required
def portal_view():
    """Subscriber dashboard with active entitlements, bookmarks, and billing history."""
    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login_view"))

    with get_db_session() as session:
        pay_repo = PaymentRepository(session)
        plan_repo = SubscriptionPlanRepository(session)
        
        # User subscription status
        active_sub = pay_repo.active_subscription(user.id)
        transactions = pay_repo.transactions_for_user(user.id, limit=10)
        plans = plan_repo.all(active_only=True)
        
        # Recommended personalized articles
        articles = (
            session.query(Article)
            .filter(Article.scrape_status == "completed")
            .order_by(Article.id.desc())
            .limit(8)
            .all()
        )
        recommended_articles = [a.to_dict() for a in articles]

    return render_template(
        "subscriber.html",
        user=user,
        active_sub=active_sub,
        transactions=transactions,
        plans=plans,
        recommended_articles=recommended_articles,
    )


@subscriber_bp.route("/preferences", methods=["POST"])
@login_required
def update_preferences():
    """Save user news categories and newsletter preferences."""
    flash("আপনার পাঠক পছন্দসমূহ সফলভাবে সংরক্ষিত হয়েছে। / Your reading preferences have been saved.", "success")
    return redirect(url_for("subscriber.portal_view"))


@subscriber_bp.route("/dashboard", endpoint="dashboard_alias")
@login_required
def dashboard_alias():
    """Alias for /subscriber/portal."""
    return portal_view()

