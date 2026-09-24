import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, send_from_directory, render_template
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
    )

    if test_config:
        app.config.update(test_config)

    # Ensure database is initialized and seed default users & security rules
    init_db()
    with get_db_session() as session:
        user_repo = UserRepository(session)
        user_repo.seed_default_users()
        from src.storage.repositories import SecurityRepository, BlockchainLedgerRepository, DataCenterRepository, SiteConfigRepository
        sec_repo = SecurityRepository(session)
        sec_repo.seed_default_security_rules()
        ledger_repo = BlockchainLedgerRepository(session)
        ledger_repo.ensure_genesis_block()
        dc_repo = DataCenterRepository(session)
        dc_repo.seed_default_providers()
        dc_repo.seed_default_replica_nodes()
        cfg_repo = SiteConfigRepository(session)
        cfg_repo.seed_default_configs()

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
        return {
            "current_user": user,
            "is_admin": user.role == "admin" if user else False,
            "is_editor": user.role in ["admin", "editor"] if user else False,
            "is_analyst": user.role in ["admin", "editor", "analyst"] if user else False,
            "is_viewer": user is not None,
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

    app.register_blueprint(portal_bp, url_prefix="/news")
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(dashboard_bp, url_prefix="")
    app.register_blueprint(scraper_bp, url_prefix="/scraper")
    app.register_blueprint(article_bp, url_prefix="/articles")
    app.register_blueprint(training_bp, url_prefix="/training")
    app.register_blueprint(chat_bp, url_prefix="/chat")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(datacenter_bp, url_prefix="/admin/datacenter")

    @app.errorhandler(404)
    def page_not_found(e):
        return render_template("404.html"), 404

    @app.errorhandler(403)
    def forbidden_error(e):
        return render_template("403.html"), 403

    # Start autonomous background scheduler if not in test suite
    if not app.config.get("TESTING"):
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
