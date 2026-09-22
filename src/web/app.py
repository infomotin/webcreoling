"""
Flask Application Factory & Route Registration.
Configures session security, Jinja2 context processors, media serving, and RBAC routes.
"""

from pathlib import Path
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

    # Ensure database is initialized and seed default users
    init_db()
    with get_db_session() as session:
        user_repo = UserRepository(session)
        user_repo.seed_default_users()

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

    app.register_blueprint(portal_bp, url_prefix="/news")
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(dashboard_bp, url_prefix="")
    app.register_blueprint(scraper_bp, url_prefix="/scraper")
    app.register_blueprint(article_bp, url_prefix="/articles")
    app.register_blueprint(training_bp, url_prefix="/training")
    app.register_blueprint(chat_bp, url_prefix="/chat")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    @app.errorhandler(404)
    def page_not_found(e):
        return render_template("404.html"), 404

    @app.errorhandler(403)
    def forbidden_error(e):
        return render_template("403.html"), 403

    return app


if __name__ == "__main__":
    app = create_app()
    print("=" * 70)
    print("Starting WebCreoling Flask Web App on http://127.0.0.1:8080")
    print("Default Accounts: admin / editor / analyst / viewer (Password: <username>123)")
    print("=" * 70)
    app.run(host="127.0.0.1", port=8080, debug=True)
