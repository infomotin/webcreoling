"""One-time password (OTP) issue / verify service with hashed storage."""

import hashlib
import random
import string
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from config.settings import settings
from src.common.logger import get_logger
from src.integrations.config_service import get_otp_config
from src.storage.database import get_db_session
from src.storage.repositories import OtpCode, OtpRepository

logger = get_logger("webcreoling.integrations.otp")

OTP_SALT = "webcreoling-otp-v1"
SEND_MODE_AUTO = "auto"


def _hash(code: str) -> str:
    secret = f"{OTP_SALT}:{getattr(settings, 'APP_NAME', 'webcreoling')}"
    return hashlib.sha256(f"{secret}:{code}".encode("utf-8")).hexdigest()


def generate_code(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


def issue_code(destination: str, purpose: str, channel: str = "email",
               user_id: Optional[int] = None,
               cfg: Optional[Dict[str, Any]] = None) -> Tuple[Optional[str], Optional[str]]:
    """Create a fresh OTP. Returns (plaintext_code, error_reason)."""
    cfg = cfg or get_otp_config()
    length = int(cfg.get("otp_length") or 6)
    ttl_minutes = int(cfg.get("otp_ttl_minutes") or 10)
    cooldown = int(cfg.get("otp_resend_cooldown_seconds") or 60)

    try:
        with get_db_session() as session:
            repo = OtpRepository(session)
            repo.purge_expired()
            latest = repo.latest_for(destination, purpose)
            if latest and not latest.is_used:
                elapsed = (datetime.utcnow() - (latest.created_at or datetime.utcnow())).total_seconds()
                if elapsed < cooldown:
                    wait = int(cooldown - elapsed)
                    return None, f"cooldown:{wait}"
            code = generate_code(length)
            otp = OtpCode(
                channel=channel,
                destination=destination,
                purpose=purpose,
                code_hash=_hash(code),
                attempts=0,
                max_attempts=int(cfg.get("otp_max_attempts") or 5),
                user_id=user_id,
                is_used=False,
                expires_at=datetime.utcnow() + timedelta(minutes=ttl_minutes),
            )
            repo.add(otp)
            return code, None
    except Exception as exc:
        logger.error(f"OTP issue failed: {exc}", exc_info=True)
        return None, str(exc)


def verify_code(destination: str, purpose: str, code: str,
                cfg: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    """Verify an OTP for (destination, purpose). Returns (ok, reason)."""
    cfg = cfg or get_otp_config()
    code = (code or "").strip()
    if not code:
        return False, "empty"

    try:
        with get_db_session() as session:
            repo = OtpRepository(session)
            otp = repo.latest_for(destination, purpose)
            if otp is None:
                return False, "not_found"
            if otp.is_used:
                return False, "already_used"
            if otp.expires_at and otp.expires_at < datetime.utcnow():
                return False, "expired"
            if otp.attempts >= otp.max_attempts:
                return False, "too_many_attempts"
            otp.attempts += 1
            if otp.code_hash != _hash(code):
                repo.save(otp)
                return False, "mismatch"
            otp.is_used = True
            repo.save(otp)
            return True, "ok"
    except Exception as exc:
        logger.error(f"OTP verify failed: {exc}", exc_info=True)
        return False, str(exc)


def deliver_otp(session, destination: str, code: str, purpose: str,
                channel: str = "email", expires_minutes: int = 10) -> Dict[str, Any]:
    """Send the issued code over the chosen channel."""
    if channel == "sms":
        from src.integrations.sms_service import send_sms
        message = f"আপনার ভেরিফিকেশন কোড: {code} ({expires_minutes} মিনিট বৈধ) - দি ডেইলি এআই আলো"
        return send_sms(destination, message, purpose=purpose)

    from src.integrations.mail_service import send_otp_mail
    return send_otp_mail(session, destination, code, purpose=purpose,
                         expires_minutes=expires_minutes)
