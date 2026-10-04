import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import urllib.parse

from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    send_from_directory,
    session as flask_session,
)
from config.settings import settings
from src.storage.database import init_db, get_db_session
from src.storage.repositories import UserRepository
from src.web.auth import get_current_user


def _load_or_create_secret_key() -> str:
    """Persist a random Flask signing key under ``data/instance/``.

    Replaces the previous deterministic fallback (sha256 of DB credentials),
    which any attacker with repository access could recompute and use to forge
    signed session cookies. The key file is created once with 0600 permissions
    and reused across restarts; if the filesystem is read-only an ephemeral
    key is generated for the lifetime of the process.
    """
    import secrets as _secrets

    key_file = PROJECT_ROOT / "data" / "instance" / "secret_key"
    try:
        if key_file.exists():
            existing = key_file.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key = _secrets.token_hex(32)
        key_file.write_text(key, encoding="utf-8")
        try:
            os.chmod(key_file, 0o600)
        except OSError:  # pragma: no cover - platform dependent
            pass
        print(f"[security] Generated new Flask SECRET_KEY at {key_file}")
        return key
    except OSError:
        return _secrets.token_hex(32)


def create_app(test_config: dict = None) -> Flask:
    """Initialize and configure the Flask web application."""
    app_dir = Path(__file__).resolve().parent
    template_dir = app_dir / "templates"
    static_dir = app_dir / "static"

    app = Flask(
        __name__,
        template_folder=str(template_dir),
        static_folder=str(static_dir),
        static_url_path="/static",
    )

    # SECRET_KEY: env var first, otherwise a persisted random key (see
    # _load_or_create_secret_key). Never derived from guessable inputs.
    flask_secret = (
        os.environ.get("FLASK_SECRET_KEY")
        or os.environ.get("SECRET_KEY")
        or getattr(settings, "FLASK_SECRET_KEY", "")
        or _load_or_create_secret_key()
    )

    app.config.from_mapping(
        SECRET_KEY=flask_secret,
        MAX_CONTENT_LENGTH=32 * 1024 * 1024,
        # Session hardening: HttpOnly (default) + SameSite=Lax blocks
        # cross-site POSTs from carrying the session cookie. Opt-in Secure
        # flag for HTTPS deployments.
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "").lower()
        in ("1", "true", "yes"),
        # ---- Default Mail Server Configuration (Mailtrap sandbox) ----
        MAIL_SERVER=getattr(settings, "MAIL_SERVER", "sandbox.smtp.mailtrap.io"),
        MAIL_PORT=getattr(settings, "MAIL_PORT", 2525),
        MAIL_USERNAME=getattr(settings, "MAIL_USERNAME", ""),
        MAIL_PASSWORD=getattr(settings, "MAIL_PASSWORD", ""),
        MAIL_USE_TLS=getattr(settings, "MAIL_USE_TLS", True),
        MAIL_USE_SSL=getattr(settings, "MAIL_USE_SSL", False),
        MAIL_DEFAULT_SENDER=settings.MAIL_DEFAULT_SENDER,
        # ---- SSLCommerz Payment Gateway (Sandbox) ----
        SSLCOMMERZ_STORE_ID=getattr(settings, "SSLCOMMERZ_STORE_ID", ""),
        SSLCOMMERZ_STORE_PASSWORD=getattr(settings, "SSLCOMMERZ_STORE_PASS", ""),
        SSLCOMMERZ_IS_LIVE=getattr(settings, "SSLCOMMERZ_IS_LIVE", False),
    )

    if test_config:
        app.config.update(test_config)

    # Ensure database is initialized and seed default users & security rules
    init_db()
    with get_db_session() as session:
        user_repo = UserRepository(session)
        user_repo.seed_default_users()
        # Master / basic-configuration seeds only. Demo content (ads, polls) is
        # intentionally NOT seeded — the portal ships without sample data.
        from src.storage.repositories import SecurityRepository, BlockchainLedgerRepository, DataCenterRepository, SiteConfigRepository, SubscriptionPlanRepository
        sec_repo = SecurityRepository(session)
        sec_repo.seed_default_security_rules()
        ledger_repo = BlockchainLedgerRepository(session)
        ledger_repo.ensure_genesis_block()
        dc_repo = DataCenterRepository(session)
        dc_repo.seed_default_providers()
        dc_repo.seed_default_replica_nodes()
        cfg_repo = SiteConfigRepository(session)
        cfg_repo.seed_default_configs()
        plan_repo = SubscriptionPlanRepository(session)
        plan_repo.ensure_default_plans()

    # Enterprise WAF Security & Threat Defense Guard
    from src.web.security import run_security_firewall
    @app.before_request
    def security_firewall_hook():
        return run_security_firewall()

    # CSRF mitigation without token plumbing: reject state-changing requests
    # that a browser attributes to another origin (Origin/Referer mismatch or
    # Sec-Fetch-Site: cross-site). Requests without those headers (tests,
    # curl, server-to-server) are unaffected.
    @app.before_request
    def csrf_origin_guard():
        if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
            return None
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            return jsonify({"error": "CSRF check failed", "message": "Cross-site request rejected."}), 403
        origin = request.headers.get("Origin") or request.headers.get("Referer")
        if origin:
            try:
                host = urllib.parse.urlsplit(origin).netloc
            except ValueError:
                return jsonify({"error": "CSRF check failed", "message": "Malformed Origin."}), 403
            if host and host.lower() not in {request.host.lower(), request.environ.get("HTTP_HOST", "").lower()}:
                return jsonify({"error": "CSRF check failed", "message": "Origin mismatch."}), 403
        return None

    # Hardening headers on every response.
    # NOTE: no Content-Security-Policy yet — templates rely on inline
    # <script> and onclick handlers, so a strict CSP needs a nonce refactor
    # across all templates first.
    @app.after_request
    def security_headers_hook(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"
        )
        if request.is_secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    # Global Language Switcher Hook
    @app.before_request
    def language_handler_hook():
        from flask import request, session as flask_session, g
        lang_arg = request.args.get("lang")
        if lang_arg in ("bn", "en"):
            flask_session["lang"] = lang_arg
            g.lang = lang_arg
        else:
            cookie_lang = request.cookies.get("app_lang")
            g.lang = flask_session.get("lang") or cookie_lang or "bn"
            flask_session["lang"] = g.lang

    # Jinja filter: escape a value for a single-quoted JS string literal that
    # lives inside a double-quoted HTML attribute (inline onclick handlers).
    # Blocks article titles/snippets like:  "); alert('xss'); //
    def _js_escape(value) -> str:
        text = "" if value is None else str(value)
        return (
            text.replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
        )

    app.jinja_env.filters["js_escape"] = _js_escape

    # Context processor to make current_user available across all templates
    @app.context_processor
    def inject_user_and_roles():
        from src.common.i18n import t, tr, get_current_language
        from src.common.site_identity import get_site_identity, get_security_recipient_email
        from src.web.routes.portal_bp import post_url
        user = get_current_user()
        lang = get_current_language()

        return {
            "current_user": user,
            "post_url": post_url,
            "is_admin": user.role == "admin" if user else False,
            "is_editor": user.role in ["admin", "editor"] if user else False,
            "is_reporter": user.role in ["reporter", "editor", "admin"] if user else False,
            "is_subscriber": user.role in ["subscriber", "viewer", "admin", "editor", "reporter", "analyst"] if user else False,
            "is_analyst": user.role in ["admin", "editor", "analyst"] if user else False,
            "is_viewer": user is not None,
            "can_agent": user.role in ["admin", "editor", "editorial_lead", "ad_manager", "onboarding_officer"] if user else False,
            "lang": lang,
            "current_lang": lang,
            "t": t,
            "_t": t,
            "tr": tr,
            "site_identity": get_site_identity(),
            "security_recipient_email": get_security_recipient_email(),
        }

    # Global direct language toggle route
    @app.route("/set-language/<lang_code>")
    def set_language_global(lang_code: str):
        from flask import request, redirect, session as flask_session
        clean_code = "en" if str(lang_code).lower() == "en" else "bn"
        flask_session["lang"] = clean_code
        next_url = request.args.get("next") or request.referrer or "/"
        if "/set-language/" in next_url or "/lang/" in next_url:
            next_url = "/"
        resp = redirect(next_url)
        resp.set_cookie("app_lang", clean_code, max_age=365 * 24 * 60 * 60)
        return resp

    # Route to serve downloaded article images safely
    @app.route("/media/images/<path:filename>")
    @app.route("/data/images/<path:filename>")
    def serve_media_images(filename: str):
        return send_from_directory(str(settings.IMAGES_DIR), filename)

    # Route to serve small editor-uploaded post videos (mp4/webm)
    @app.route("/media/videos/<path:filename>")
    @app.route("/data/videos/<path:filename>")
    def serve_media_videos(filename: str):
        try:
            settings.VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return send_from_directory(str(settings.VIDEOS_DIR), filename)

    # Register Blueprints
    from src.web.routes.auth_bp import auth_bp
    from src.web.routes.dashboard_bp import dashboard_bp
    from src.web.routes.portal_bp import portal_bp
    from src.web.routes.scraper_bp import scraper_bp
    from src.web.routes.article_bp import article_bp
    from src.web.routes.training_bp import training_bp
    from src.web.routes.chat_bp import chat_bp
    from src.web.routes.admin_bp import admin_bp
    from src.web.routes.datacenter_bp import datacenter_bp
    from src.web.routes.integrations_bp import integrations_bp
    from src.web.routes.billing_bp import billing_bp
    from src.web.routes.agent_bp import agent_bp
    from src.web.routes.submissions_bp import submissions_bp
    from src.web.routes.reporter_bp import reporter_bp
    from src.web.routes.subscriber_bp import subscriber_bp

    app.register_blueprint(portal_bp,   url_prefix="/news")
    app.register_blueprint(auth_bp,    url_prefix="/auth")
    app.register_blueprint(dashboard_bp, url_prefix="")     # serves "/"
    app.register_blueprint(scraper_bp,  url_prefix="/scraper")
    app.register_blueprint(article_bp,  url_prefix="/articles")
    app.register_blueprint(training_bp, url_prefix="/training")
    app.register_blueprint(chat_bp,     url_prefix="/chat")
    app.register_blueprint(admin_bp,    url_prefix="/admin")
    app.register_blueprint(datacenter_bp, url_prefix="/admin/datacenter")
    app.register_blueprint(integrations_bp, url_prefix="/admin/integrations")
    app.register_blueprint(billing_bp,  url_prefix="/billing")
    app.register_blueprint(agent_bp,      url_prefix="/agent")
    app.register_blueprint(submissions_bp, url_prefix="/submissions")
    app.register_blueprint(reporter_bp,   url_prefix="/reporter")
    app.register_blueprint(subscriber_bp, url_prefix="/subscriber")

    @app.errorhandler(404)
    def page_not_found(e):
        return render_template("404.html"), 404

    @app.errorhandler(403)
    def forbidden_error(e):
        return render_template("403.html"), 403

    # Start autonomous background scheduler if not in test suite
    running_under_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST"))
    if not app.config.get("TESTING") and not running_under_pytest:
        try:
            from src.automation.scheduler import get_scheduler
            scheduler = get_scheduler()
            scheduler.start()
        except Exception as e:
            app.logger.warning(f"Could not start automation scheduler: {e}")

    return app


if __name__ == "__main__":
    app = create_app()
    print("=" * 70)
    print(f"Starting WebCreoling Flask Web App on http://{settings.SERVER_HOST}:{settings.SERVER_PORT}")
    print("Default Accounts: admin / editor / analyst / viewer (Password: <username>123)")
    print(f"Connected Database: {settings.DB_NAME} (MySQL at {settings.DB_HOST}:{settings.DB_PORT})")
    print("=" * 70)
    app.run(host=settings.SERVER_HOST, port=settings.SERVER_PORT, debug=settings.DEBUG)
