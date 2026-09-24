"""
Executive Intelligence & Real-time Analytics Dashboard Blueprint.
Provides comprehensive 360-degree newsroom overview, newspaper monitoring watchlist (CRUD),
visitor analytics, load time telemetry, Top 10 World News, Top Trending Keywords, Best Readers,
and Real-Time News Publishing Notifications.
"""

import json
from pathlib import Path
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from config.settings import settings
from src.storage.database import get_db_session
from src.storage.models import Article, ScrapeLog, User, NewsletterSubscriber, Poll
from src.storage.repositories import ArticleRepository
from src.web.auth import login_required, roles_required
from src.automation.newspaper_monitor import get_newspaper_monitor

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
def index_view():
    """Main 360-degree Executive Intelligence Dashboard."""
    monitor = get_newspaper_monitor()

    # 1. Fetch Newspaper Watchlist & Telemetry
    monitored_newspapers = monitor.list_monitored_newspapers()
    top_world_news = monitor.get_top_ten_world_news()
    trending_words = monitor.get_top_trending_words()
    visitor_telemetry = monitor.get_visitor_and_system_telemetry()
    reader_analytics = monitor.get_reader_analytics_and_best_users()
    notifications = monitor.get_notifications(limit=10)

    # 2. Database Stats & Recent Ingestion
    with get_db_session() as session:
        repo = ArticleRepository(session)
        stats = repo.get_database_stats()
        
        user_count = session.query(User).count()
        subscriber_count = session.query(NewsletterSubscriber).count()
        poll_count = session.query(Poll).count()

        # Fetch recent 8 articles
        recent_articles = (
            session.query(Article)
            .order_by(Article.id.desc())
            .limit(8)
            .all()
        )
        recent_articles_data = [a.to_dict() for a in recent_articles]

        # Fetch recent 6 scrape logs
        recent_logs = (
            session.query(ScrapeLog)
            .order_by(ScrapeLog.id.desc())
            .limit(6)
            .all()
        )
        recent_logs_data = [l.to_dict() for l in recent_logs]

    # 3. Read recent chat history if available
    chat_history_file = settings.DATA_DIR / "chat_history.jsonl"
    recent_chats = []
    if chat_history_file.exists():
        try:
            with open(chat_history_file, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
                for l in lines[-5:]:
                    entry = json.loads(l)
                    norm_entry = {
                        "mode": entry.get("mode", "rag_qa"),
                        "user_input": entry.get("user_input") or entry.get("query") or "",
                        "response": entry.get("response") or entry.get("response_text") or entry.get("answer") or "",
                        "latency_seconds": entry.get("latency_seconds", 0.0),
                    }
                    recent_chats.append(norm_entry)
            recent_chats.reverse()
        except Exception:
            pass

    return render_template(
        "dashboard.html",
        stats=stats,
        user_count=user_count,
        subscriber_count=subscriber_count,
        poll_count=poll_count,
        recent_articles=recent_articles_data,
        recent_logs=recent_logs_data,
        recent_chats=recent_chats,
        monitored_newspapers=monitored_newspapers,
        top_world_news=top_world_news,
        trending_words=trending_words,
        visitor_telemetry=visitor_telemetry,
        reader_analytics=reader_analytics,
        notifications=notifications,
    )


# ==============================================================================
# Newspaper Monitoring Watchlist (CRUD API Endpoints)
# ==============================================================================

@dashboard_bp.route("/api/monitor/newspaper/add", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def add_monitored_newspaper():
    """[CREATE] Add a new Newspaper URL to active monitoring watchlist."""
    data = request.get_json(silent=True) or request.form
    name = (data.get("name") or "নতুন সংবাদপত্র").strip()
    name_bn = (data.get("name_bn") or name).strip()
    url = (data.get("url") or "").strip()
    category = (data.get("category") or "জাতীয়").strip()
    language = (data.get("language") or "Bangla").strip()
    country = (data.get("country") or "Bangladesh").strip()
    rss_url = (data.get("rss_url") or "").strip()
    interval = int(data.get("scrape_interval_mins", 30))
    notif = str(data.get("notification_enabled", "true")).lower() in ["1", "true", "on", "yes"]

    if not url:
        if request.is_json:
            return jsonify({"status": "error", "message": "Portal URL is required."}), 400
        flash("সংবাদপত্রের URL প্রদান করা আবশ্যক।", "danger")
        return redirect(url_for("dashboard.index_view"))

    monitor = get_newspaper_monitor()
    item = monitor.add_newspaper(
        name=name,
        name_bn=name_bn,
        url=url,
        category=category,
        language=language,
        country=country,
        rss_url=rss_url,
        scrape_interval_mins=interval,
        notification_enabled=notif,
    )

    if request.is_json:
        return jsonify({"status": "success", "message": f"'{name}' added to monitoring watchlist!", "newspaper": item})

    flash(f"✅ '{name_bn}' সফলভাবে মনিটরিং ওয়াচলিস্টে যুক্ত করা হয়েছে!", "success")
    return redirect(url_for("dashboard.index_view"))


@dashboard_bp.route("/api/monitor/newspaper/update/<paper_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def update_monitored_newspaper(paper_id: str):
    """[UPDATE] Update monitored newspaper properties."""
    data = request.get_json(silent=True) or request.form
    name = data.get("name")
    name_bn = data.get("name_bn")
    url = data.get("url")
    category = data.get("category")
    interval = int(data["scrape_interval_mins"]) if "scrape_interval_mins" in data else None
    notif = str(data.get("notification_enabled", "")).lower() in ["1", "true", "on", "yes"] if "notification_enabled" in data else None

    monitor = get_newspaper_monitor()
    updated = monitor.update_newspaper(
        paper_id=paper_id,
        name=name,
        name_bn=name_bn,
        url=url,
        category=category,
        scrape_interval_mins=interval,
        notification_enabled=notif,
    )

    if not updated:
        if request.is_json:
            return jsonify({"status": "error", "message": "Newspaper not found."}), 404
        flash("সংবাদপত্র পাওয়া যায়নি।", "danger")
        return redirect(url_for("dashboard.index_view"))

    if request.is_json:
        return jsonify({"status": "success", "message": "Updated successfully!", "newspaper": updated})

    flash("✅ সংবাদপত্রের তথ্য আপডেট করা হয়েছে!", "success")
    return redirect(url_for("dashboard.index_view"))


@dashboard_bp.route("/api/monitor/newspaper/delete/<paper_id>", methods=["POST"])
@login_required
@roles_required("admin")
def delete_monitored_newspaper(paper_id: str):
    """[DELETE] Remove newspaper from monitoring watchlist."""
    monitor = get_newspaper_monitor()
    success = monitor.delete_newspaper(paper_id)

    if request.is_json:
        return jsonify({"status": "success" if success else "error", "message": "Deleted from watchlist." if success else "Not found."})

    if success:
        flash(f"🗑️ সংবাদপত্র '{paper_id}' ওয়াচলিস্ট থেকে মুছে ফেলা হয়েছে।", "success")
    else:
        flash("মুছে ফেলা সম্ভব হয়নি।", "danger")

    return redirect(url_for("dashboard.index_view"))


@dashboard_bp.route("/api/monitor/newspaper/toggle/<paper_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def toggle_monitored_newspaper(paper_id: str):
    """Toggle monitoring active state."""
    monitor = get_newspaper_monitor()
    state = monitor.toggle_monitoring(paper_id)
    if state is None:
        return jsonify({"status": "error", "message": "Not found"}), 404
    return jsonify({"status": "success", "is_monitoring_active": state, "message": f"Monitoring is now {'Active' if state else 'Paused'}."})


@dashboard_bp.route("/api/monitor/newspaper/toggle-notif/<paper_id>", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def toggle_newspaper_notifications(paper_id: str):
    """Toggle notification alerts for a specific newspaper."""
    monitor = get_newspaper_monitor()
    state = monitor.toggle_notifications(paper_id)
    if state is None:
        return jsonify({"status": "error", "message": "Not found"}), 404
    return jsonify({"status": "success", "notification_enabled": state, "message": f"Publish notifications {'Enabled' if state else 'Disabled'}."})


@dashboard_bp.route("/api/monitor/newspaper/ping/<paper_id>", methods=["POST"])
@login_required
def ping_newspaper_route(paper_id: str):
    """Perform a live HTTP ping check to verify portal latency and HTTP status."""
    monitor = get_newspaper_monitor()
    res = monitor.ping_newspaper(paper_id)
    return jsonify(res)


# ==============================================================================
# Live Notifications & Telemetry Endpoints
# ==============================================================================

@dashboard_bp.route("/api/notifications/dispatch-test", methods=["POST"])
@login_required
@roles_required("admin", "editor")
def dispatch_test_notification():
    """Dispatch a test news publish alert notification."""
    monitor = get_newspaper_monitor()
    notif = monitor.dispatch_notification(
        title="🔔 টেস্ট ব্রেকিং নিউজ নোটিফিকেশন",
        message="প্রথম আলো ও ডেইলি স্টারে নতুন গুরুত্বপূর্ণ জাতীয় সংবাদ প্রকাশিত হয়েছে। এআই পাইলট তাৎক্ষণিক বিশ্লেষণ শুরু করেছে।",
        source="Prothom Alo Live Feed",
        category="ব্রেকিং নিউজ",
        url="/news/",
    )
    return jsonify({"status": "success", "notification": notif})


@dashboard_bp.route("/api/notifications/live", methods=["GET"])
@login_required
def get_live_notifications():
    """Get latest notifications JSON for live polling."""
    monitor = get_newspaper_monitor()
    return jsonify({
        "notifications": monitor.get_notifications(limit=12),
        "count": len(monitor.notifications),
    })


@dashboard_bp.route("/api/notifications/mark-read", methods=["POST"])
@login_required
def mark_notifications_read():
    """Mark all notifications as read."""
    monitor = get_newspaper_monitor()
    monitor.mark_notifications_read()
    return jsonify({"status": "success", "message": "All marked as read."})


@dashboard_bp.route("/api/dashboard/telemetry", methods=["GET"])
@login_required
def get_live_telemetry():
    """JSON endpoint returning live visitor counts and system load time."""
    monitor = get_newspaper_monitor()
    telemetry = monitor.get_visitor_and_system_telemetry()
    return jsonify(telemetry)
