"""
Dynamic site identity resolvers.

All identity/contact values come from config.settings (env-overridable) with
fallback to the primary admin account. NO identity literals live in source
code or templates — templates consume ``site_identity`` from the app context.
"""

from typing import Dict, Optional

from config.settings import settings

_admin_email_cache: Dict[str, object] = {"email": None, "ts": 0.0}


def primary_admin_email() -> str:
    """Primary admin account email (cached for 60s), else seeded admin address."""
    import time

    now = time.time()
    cached = _admin_email_cache["email"]
    if cached and now - float(_admin_email_cache["ts"]) < 60:
        return str(cached)
    try:
        from src.storage.database import get_db_session
        from src.storage.models import User

        with get_db_session() as session:
            admin = (
                session.query(User)
                .filter(User.role == "admin")
                .order_by(User.id.asc())
                .first()
            )
            if admin and admin.email:
                _admin_email_cache["email"] = admin.email
                _admin_email_cache["ts"] = now
                return str(admin.email)
    except Exception:
        pass
    return f"admin@{settings.SEED_EMAIL_DOMAIN}"


def resolve_email(value: Optional[str]) -> str:
    """Use the provided address when valid, else the primary admin address."""
    if value and "@" in str(value).strip():
        return str(value).strip()
    return primary_admin_email()


def get_security_recipient_email() -> str:
    """Recipient for security/alert emails (settings.SECURITY_ALERT_EMAIL)."""
    return resolve_email(settings.SECURITY_ALERT_EMAIL)


def get_site_contact_email() -> str:
    """Public contact email (settings.SITE_CONTACT_EMAIL)."""
    return resolve_email(settings.SITE_CONTACT_EMAIL)


def get_site_identity() -> Dict[str, str]:
    """Identity dict injected into every template as ``site_identity``."""
    return {
        "title": settings.SITE_TITLE,
        "title_en": settings.SITE_TITLE_EN,
        "publisher": settings.SITE_PUBLISHER,
        "editor_in_chief": settings.SITE_EDITOR_IN_CHIEF,
        "office_address": settings.SITE_OFFICE_ADDRESS,
        "contact_email": get_site_contact_email(),
        "contact_phone": settings.SITE_CONTACT_PHONE,
        "copyright": settings.SITE_COPYRIGHT,
        "facebook_url": settings.SITE_FACEBOOK_URL,
        "youtube_url": settings.SITE_YOUTUBE_URL,
        "twitter_url": settings.SITE_TWITTER_URL,
        "newsletter_name": settings.SITE_NEWSLETTER_NAME,
        "mail_sender": settings.MAIL_DEFAULT_SENDER,
        "mail_sender_name": settings.MAIL_SENDER_NAME,
    }
