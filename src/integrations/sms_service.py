"""Generic HTTP SMS gateway service with test-mode fallback."""

from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests

from src.common.logger import get_logger
from src.storage.database import get_db_session
from src.storage.repositories import MessageLog, MessageLogRepository
from src.integrations.config_service import get_sms_config

logger = get_logger("webcreoling.integrations.sms")


def _log(recipient: str, body: str, status: str, purpose: str = "general",
         error: Optional[str] = None) -> None:
    try:
        with get_db_session() as session:
            MessageLogRepository(session).add(
                MessageLog(
                    channel="sms",
                    recipient=recipient,
                    subject=None,
                    body=body[:1000],
                    purpose=purpose,
                    status=status,
                    error=error,
                )
            )
    except Exception as exc:
        logger.debug(f"SMS log write failed: {exc}")


def build_request(cfg: Dict[str, Any], phone: str, message: str):
    """Build (url, params) for the configured generic gateway."""
    url = (cfg.get("api_url") or "").strip()
    if not url:
        raise ValueError("SMS API URL is not configured")

    params = {}
    for pair in (cfg.get("extra_params") or "").split("&"):
        if "=" in pair:
            key, value = pair.split("=", 1)
            params[key.strip()] = value.strip()

    params[cfg.get("param_to") or "to"] = phone
    params[cfg.get("param_text") or "msg"] = message
    if cfg.get("api_key"):
        params["api_key"] = cfg["api_key"]
    if cfg.get("sender_id"):
        params["sender_id"] = cfg["sender_id"]

    if (cfg.get("method") or "GET").upper() == "POST":
        return url, params
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}", None


def send_sms(phone: str, message: str, purpose: str = "general") -> Dict[str, Any]:
    cfg = get_sms_config()
    if not cfg.get("enabled", True):
        _log(phone, message, "FAILED", purpose, "SMS service disabled")
        return {"ok": False, "error": "SMS service disabled"}

    if cfg.get("test_mode") or not (cfg.get("api_url") or "").strip():
        _log(phone, message, "SIMULATED", purpose, "Test mode / no API URL configured")
        logger.info(f"SMS simulated to {phone} [{purpose}]")
        return {"ok": True, "simulated": True}

    try:
        url, post_data = build_request(cfg, phone, message)
        timeout = int(cfg.get("timeout") or 15)
        if post_data is not None:
            response = requests.post(url, data=post_data, timeout=timeout)
        else:
            response = requests.get(url, timeout=timeout)
        ok = 200 <= response.status_code < 300
        _log(phone, message, "SENT" if ok else "FAILED", purpose,
             None if ok else f"HTTP {response.status_code}: {response.text[:300]}")
        if not ok:
            logger.warning(f"SMS gateway returned HTTP {response.status_code} for {phone}")
        return {
            "ok": ok,
            "simulated": False,
            "status_code": response.status_code,
            "response": response.text[:500],
            "error": None if ok else f"HTTP {response.status_code}",
        }
    except Exception as exc:
        _log(phone, message, "FAILED", purpose, str(exc))
        logger.warning(f"SMS to {phone} failed: {exc}")
        return {"ok": False, "simulated": False, "error": str(exc)}
