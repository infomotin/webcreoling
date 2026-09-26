"""Runtime integration configuration (DB-backed with .env / app defaults)."""

from typing import Any, Dict, Optional

from config.settings import settings
from src.storage.database import get_db_session
from src.storage.repositories import SiteConfigRepository

MAIL_KEY = "integrations_mail"
SMS_KEY = "integrations_sms"
PAYMENT_KEY = "integrations_payment"
OTP_KEY = "security_otp"

DEFAULT_MAIL_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "mail_server": getattr(settings, "MAIL_SERVER", "sandbox.smtp.mailtrap.io"),
    "mail_port": getattr(settings, "MAIL_PORT", 2525),
    "mail_username": getattr(settings, "MAIL_USERNAME", "6056bdc6c17f23"),
    "mail_password": getattr(settings, "MAIL_PASSWORD", "4e1119bb236ac7"),
    "mail_use_tls": getattr(settings, "MAIL_USE_TLS", True),
    "mail_use_ssl": getattr(settings, "MAIL_USE_SSL", False),
    "mail_default_sender": getattr(settings, "MAIL_DEFAULT_SENDER", "no-reply@daily-ai-alo.com"),
    "mail_timeout": 10,
}

DEFAULT_SMS_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "provider": "Generic HTTP Gateway",
    "api_url": "",
    "api_key": "",
    "sender_id": "",
    "method": "GET",
    "param_to": "to",
    "param_text": "msg",
    "extra_params": "",
    "test_mode": True,
}

DEFAULT_PAYMENT_CONFIG: Dict[str, Any] = {
    "provider": "SSLCommerz",
    "is_live": False,
    "store_id": getattr(settings, "SSLCOMMERZ_STORE_ID", "arobw6a3cf7767fa7c"),
    "store_password": getattr(settings, "SSLCOMMERZ_STORE_PASSWORD", "arobw6a3cf7767fa7c@ssl"),
    "sandbox_base_url": "https://sandbox.sslcommerz.com",
    "live_base_url": "https://securepay.sslcommerz.com",
    "currency": "BDT",
}

DEFAULT_OTP_CONFIG: Dict[str, Any] = {
    "register_email_otp": True,
    "login_2fa": False,
    "password_reset_otp": True,
    "sms_otp": False,
    "otp_length": 6,
    "otp_ttl_minutes": 10,
    "otp_max_attempts": 5,
    "otp_resend_cooldown_seconds": 60,
}

_DEFAULTS = {
    MAIL_KEY: DEFAULT_MAIL_CONFIG,
    SMS_KEY: DEFAULT_SMS_CONFIG,
    PAYMENT_KEY: DEFAULT_PAYMENT_CONFIG,
    OTP_KEY: DEFAULT_OTP_CONFIG,
}


def _load(key: str) -> Dict[str, Any]:
    merged = dict(_DEFAULTS[key])
    try:
        with get_db_session() as session:
            repo = SiteConfigRepository(session)
            stored = repo.get_config(key)
            if isinstance(stored, dict):
                merged.update(stored)
    except Exception:
        pass
    return merged


def get_mail_config() -> Dict[str, Any]:
    return _load(MAIL_KEY)


def get_sms_config() -> Dict[str, Any]:
    return _load(SMS_KEY)


def get_payment_config() -> Dict[str, Any]:
    return _load(PAYMENT_KEY)


def get_otp_config() -> Dict[str, Any]:
    return _load(OTP_KEY)


def save_config(key: str, value: Dict[str, Any]) -> None:
    if key not in _DEFAULTS:
        raise ValueError(f"Unknown integration config key: {key}")
    merged = dict(_DEFAULTS[key])
    merged.update(value or {})
    with get_db_session() as session:
        SiteConfigRepository(session).set_config(key, merged)


def mask_secret(value: Optional[str], keep: int = 4) -> str:
    """Mask a stored secret for safe display in the admin UI."""
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return "*" * max(6, len(value) - keep) + value[-keep:]
