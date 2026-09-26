"""SSLCommerz payment gateway service (sandbox + live)."""

import time
from typing import Any, Dict, Optional

import requests

from src.common.logger import get_logger
from src.integrations.config_service import get_payment_config

logger = get_logger("webcreoling.integrations.payment")

SESSION_ENDPOINT = "/gwprocess/v4/api.php"
VALIDATOR_ENDPOINT = "/validator/api/validationserverAPI.php"


def base_url(cfg: Optional[Dict[str, Any]] = None) -> str:
    cfg = cfg or get_payment_config()
    if cfg.get("is_live"):
        return (cfg.get("live_base_url") or "https://securepay.sslcommerz.com").rstrip("/")
    return (cfg.get("sandbox_base_url") or "https://sandbox.sslcommerz.com").rstrip("/")


def build_transaction_id(user_id: Optional[int] = None) -> str:
    return f"WC{int(time.time() * 1000)}{user_id or 0}"


def create_session(
    amount: float,
    tran_id: str,
    success_url: str,
    fail_url: str,
    cancel_url: str,
    ipn_url: str,
    customer: Optional[Dict[str, Any]] = None,
    product_name: str = "Subscription Plan",
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Initiate a checkout session and return the gateway redirect URL."""
    cfg = cfg or get_payment_config()
    customer = customer or {}

    payload = {
        "store_id": cfg.get("store_id"),
        "store_passwd": cfg.get("store_password"),
        "total_amount": round(float(amount), 2),
        "currency": cfg.get("currency") or "BDT",
        "tran_id": tran_id,
        "success_url": success_url,
        "fail_url": fail_url,
        "cancel_url": cancel_url,
        "ipn_url": ipn_url,
        "shipping_method": "NO",
        "product_name": product_name,
        "product_category": "Subscription",
        "product_profile": "non-physical-goods",
        "cus_name": customer.get("name") or "WebCreoling User",
        "cus_email": customer.get("email") or "user@example.com",
        "cus_add1": customer.get("add1") or "N/A",
        "cus_city": customer.get("city") or "Dhaka",
        "cus_country": customer.get("country") or "Bangladesh",
        "cus_phone": customer.get("phone") or "01700000000",
        "ship_name": customer.get("name") or "WebCreoling User",
        "ship_city": customer.get("city") or "Dhaka",
        "ship_add1": customer.get("add1") or "N/A",
        "ship_country": customer.get("country") or "Bangladesh",
    }

    url = f"{base_url(cfg)}{SESSION_ENDPOINT}"
    try:
        response = requests.post(url, data=payload, timeout=30)
        data = {}
        try:
            data = response.json()
        except ValueError:
            data = {"status": "FAILED", "failedreason": response.text[:300]}
    except Exception as exc:
        logger.error(f"SSLCommerz session error: {exc}")
        return {"ok": False, "error": str(exc)}

    status = str(data.get("status", "")).upper()
    gateway_url = data.get("GatewayPageURL") or ""
    if status == "SUCCESS" and gateway_url:
        return {
            "ok": True,
            "gateway_url": gateway_url,
            "session_key": data.get("sessionkey"),
            "status": status,
        }

    reason = data.get("failedreason") or data.get("status") or "Unknown gateway error"
    logger.warning(f"SSLCommerz session failed: {reason}")
    return {"ok": False, "error": str(reason), "raw": data}


def validate_payment(val_id: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Server-to-server validation of a returned transaction."""
    cfg = cfg or get_payment_config()
    url = f"{base_url(cfg)}{VALIDATOR_ENDPOINT}"
    params = {
        "val_id": val_id,
        "store_id": cfg.get("store_id"),
        "store_passwd": cfg.get("store_password"),
        "format": "json",
    }
    try:
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
    except Exception as exc:
        logger.error(f"SSLCommerz validation error: {exc}")
        return {"ok": False, "status": "ERROR", "error": str(exc)}

    status = str(data.get("status", "")).upper()
    ok = status == "VALID"
    return {
        "ok": ok,
        "status": status,
        "tran_id": data.get("tran_id"),
        "amount": data.get("currency_amount") or data.get("amount"),
        "currency": data.get("currency_type"),
        "payment_method": data.get("card_type") or data.get("bank_tran_id") or data.get("method") or "",
        "bank_tran_id": data.get("bank_tran_id"),
        "risk_level": data.get("risk_level"),
        "raw": data,
    }


def ipn_validate(trans_id: str, bank_tran_id: str = "", val_id: str = "",
                 cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """IPN endpoint handler helper — prefer val_id validation, fall back to tran search."""
    if val_id:
        return validate_payment(val_id, cfg=cfg)
    cfg = cfg or get_payment_config()
    url = f"{base_url(cfg)}{VALIDATOR_ENDPOINT}"
    params = {
        "trans_id": trans_id,
        "bank_tran_id": bank_tran_id,
        "store_id": cfg.get("store_id"),
        "store_passwd": cfg.get("store_password"),
        "format": "json",
    }
    try:
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
        status = str(data.get("status", "")).upper()
        return {"ok": status == "VALID", "status": status, "tran_id": data.get("tran_id"), "raw": data}
    except Exception as exc:
        return {"ok": False, "status": "ERROR", "error": str(exc)}
