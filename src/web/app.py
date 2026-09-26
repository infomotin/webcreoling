import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, send_from_directory, render_template, session as flask_session
from config.settings import settings
from src.storage.database import init_db, get_db_session
from src.storage.repositories import UserRepository
from src.web.auth import get_current_user


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

    app.config.from_mapping(
        SECRET_KEY="webcreoling-production-secret-key-bangla-ai-pipeline",
        MAX_CONTENT_LENGTH=32 * 1024 * 1024,
        # ---- Default Mail Server Configuration (Mailtrap sandbox) ----
        MAIL_SERVER=getattr(settings, "MAIL_SERVER", "sandbox.smtp.mailtrap.io"),
        MAIL_PORT=getattr(settings, "MAIL_PORT", 2525),
        MAIL_USERNAME=getattr(settings, "MAIL_USERNAME", "6056bdc6c17f23"),
        MAIL_PASSWORD=getattr(settings, "MAIL_PASSWORD", "4e1119bb236ac7"),
        MAIL_USE_TLS=getattr(settings, "MAIL_USE_TLS", True),
        MAIL_USE_SSL=getattr(settings, "MAIL_USE_SSL", False),
        MAIL_DEFAULT_SENDER=getattr(settings, "MAIL_DEFAULT_SENDER", "no-reply@daily-ai-alo.com"),
        # ---- SSLCommerz Payment Gateway (Sandbox) ----
        SSLCOMMERZ_STORE_ID=getattr(settings, "SSLCOMMERZ_STORE_ID", "arobw6a3cf7767fa7c"),
        SSLCOMMERZ_STORE_PASSWORD=getattr(settings, "SSLCOMMERZ_STORE_PASSWORD", "arobw6a3cf7767fa7c@ssl"),
        SSLCOMMERZ_IS_LIVE=getattr(settings, "SSLCOMMERZ_IS_LIVE", False),
    )

    if test_config:
        app.config.update(test_config)

    # Ensure database is initialized and seed default users & security rules
    init_db()
    with get_db_session() as session:
        user_repo = UserRepository(session)
        user_repo.seed_default_users()
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

    # Autonomous AI Brain Emergency Vault & Self-Encryption Lockdown Guard
    @app.before_request
    def emergency_vault_lockdown_hook():
        from flask import request
        path = request.path
        if path.startswith("/static/") or path.startswith("/data/images/") or path == "/favicon.ico":
            return None
        # Whitelisted endpoints during emergency lockdown (decryption console & auth)
        if path in [
            "/admin/newspaper/security/vault/decrypt",
            "/admin/newspaper/security/vault/status",
            "/auth/login",
            "/auth/logout",
        ]:
            return None

        try:
            with get_db_session() as session:
                from src.storage.repositories import EmergencyVaultRepository
                vault_repo = EmergencyVaultRepository(session)
                state = vault_repo.get_vault_state()
                if state.is_locked:
                    return render_template("lockdown.html", vault_state=state.to_dict()), 503
        except Exception:
            pass
        return None

    # Context processor to make current_user available across all templates
    @app.context_processor
    def inject_user_and_roles():
        user = get_current_user()
        lang = flask_session.get("lang", "bn")

        def tr(bn_text, en_text=None):
            """Bilingual label helper: returns English text when lang == 'en'."""
            if lang == "en":
                return en_text if en_text is not None else bn_text
            return bn_text

        return {
            "current_user": user,
            "is_admin": user.role == "admin" if user else False,
            "is_editor": user.role in ["admin", "editor"] if user else False,
            "is_analyst": user.role in ["admin", "editor", "analyst"] if user else False,
            "is_viewer": user is not None,
            "can_agent": user.role in ["admin", "editor", "editorial_lead", "ad_manager", "onboarding_officer"] if user else False,
            "is_reporter": user.role in ["reporter", "editor", "admin"] if user else False,
            "lang": lang,
            "tr": tr,
        }

    # Route to serve downloaded article images safely
    @app.route("/media/images/<path:filename>")
    @app.route("/data/images/<path:filename>")
    def serve_media_images(filename: str):
        return send_from_directory(str(settings.IMAGES_DIR), filename)

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
