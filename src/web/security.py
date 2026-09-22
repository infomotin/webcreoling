"""
Enterprise Web Application Firewall (WAF) and Threat Defense Engine.
Detects and mitigates SQLi, XSS, Path Traversal, and RCE attacks in real-time.
Manages IP blacklisting, strike-based auto-bans, and Country Geo-Firewalls.
"""

import re
import ipaddress
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any
from flask import request, abort, render_template_string, jsonify
from src.common.logger import get_logger

logger = get_logger("webcreoling.web.security")

# Threat Regex Signatures
SQLI_PATTERNS = re.compile(
    r"(\b(union(\s+all)?\s+select|select\s+.*\s+from|insert\s+into|drop\s+table|delete\s+from|update\s+.*\s+set|truncate\s+table|exec\s*\(|execute\s*\(|benchmark\s*\(|pg_sleep\s*\(|sleep\s*\(|information_schema|waitfor\s+delay)\b|(--|/\*|\*/|;\s*drop\b|\bOR\s+['\"0-9]+=['\"0-9]+|\bAND\s+['\"0-9]+=['\"0-9]+))",
    re.IGNORECASE,
)

XSS_PATTERNS = re.compile(
    r"(<\s*script.*?>|javascript\s*:|onload\s*=|onerror\s*=|onclick\s*=|onmouseover\s*=|onfocus\s*=|document\.cookie|<iframe|<embed|<object|eval\s*\(|alert\s*\(|prompt\s*\(|confirm\s*\()",
    re.IGNORECASE,
)

PATH_TRAVERSAL_PATTERNS = re.compile(
    r"(\.\./|\.\.\\|/etc/passwd|/etc/shadow|/proc/self|/boot\.ini|win\.ini|windows/system32|/WEB-INF/)",
    re.IGNORECASE,
)

RCE_PATTERNS = re.compile(
    r"(;\s*(cat|ls|dir|whoami|netstat|powershell|cmd\.exe|wget|curl|bash|sh|nc|ncat)\b|\|\s*(cat|ls|dir|whoami|powershell)|system\s*\(|passthru\s*\(|shell_exec\s*\(|popen\s*\(|proc_open\s*\()",
    re.IGNORECASE,
)

# In-memory Strike Tracker: {ip: {"strikes": count, "first_seen": datetime}}
STRIKE_TRACKER: Dict[str, Dict[str, Any]] = {}
AUTO_BAN_THRESHOLD = 3
STRIKE_WINDOW_MINUTES = 15

# Localhost / Private IPs Whitelist for Safe Local Administration
WHITELIST_IPS = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}


def get_client_ip() -> str:
    """Extract real client IP address from proxy headers or remote address."""
    for header in ["CF-Connecting-IP", "X-Forwarded-For", "X-Real-IP"]:
        val = request.headers.get(header)
        if val:
            ip = val.split(",")[0].strip()
            if ip:
                return ip
    return request.remote_addr or "127.0.0.1"


def get_client_country() -> str:
    """Extract client country code from Cloudflare or geo header, or test header."""
    header_country = request.headers.get("CF-IPCountry") or request.headers.get("X-Country-Code")
    if header_country and len(header_country.strip()) == 2:
        return header_country.strip().upper()
    return "BD"  # Default simulated local region


def is_ip_whitelisted(ip: str) -> bool:
    """Check if IP is local/whitelisted from hard auto-banning."""
    if ip in WHITELIST_IPS:
        return True
    try:
        ip_obj = ipaddress.ip_address(ip)
        if ip_obj.is_private or ip_obj.is_loopback:
            return True
    except Exception:
        pass
    return False


def inspect_text_payload(text: str) -> Optional[Tuple[str, str]]:
    """Inspect a single string for malicious injection signatures."""
    if not text or not isinstance(text, str):
        return None

    # Check SQLi
    sqli_match = SQLI_PATTERNS.search(text)
    if sqli_match:
        return "SQL_INJECTION", sqli_match.group(0)[:100]

    # Check XSS
    xss_match = XSS_PATTERNS.search(text)
    if xss_match:
        return "XSS_ATTACK", xss_match.group(0)[:100]

    # Check Path Traversal
    path_match = PATH_TRAVERSAL_PATTERNS.search(text)
    if path_match:
        return "PATH_TRAVERSAL", path_match.group(0)[:100]

    # Check RCE
    rce_match = RCE_PATTERNS.search(text)
    if rce_match:
        return "RCE_COMMAND", rce_match.group(0)[:100]

    return None


def inspect_request_payloads() -> Optional[Tuple[str, str]]:
    """Scan query params, form fields, JSON data, and User-Agent."""
    # 1. Query Parameters
    for key, val in request.args.items():
        res = inspect_text_payload(f"{key}={val}")
        if res:
            return res

    # 2. Form Data
    if request.form:
        for key, val in request.form.items():
            # Allow rich text content in article content_text if admin is editing, but still scan SQLi/RCE
            if key in ["content_text", "summary"]:
                # Check for high-risk SQLi and RCE, allow basic HTML tags
                sqli_match = SQLI_PATTERNS.search(val)
                if sqli_match:
                    return "SQL_INJECTION", sqli_match.group(0)[:100]
                rce_match = RCE_PATTERNS.search(val)
                if rce_match:
                    return "RCE_COMMAND", rce_match.group(0)[:100]
                continue

            res = inspect_text_payload(f"{key}={val}")
            if res:
                return res

    # 3. JSON Payloads
    if request.is_json:
        try:
            json_data = request.get_json(silent=True) or {}
            json_str = str(json_data)
            res = inspect_text_payload(json_str)
            if res:
                return res
        except Exception:
            pass

    # 4. Dangerous User-Agent
    ua = request.headers.get("User-Agent", "")
    res = inspect_text_payload(ua)
    if res:
        return res

    return None


BLOCKED_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="bn">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>403 Forbidden - Security Defense System</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background: #0b0f19; color: #f3f4f6; display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 20px; }
        .shield-box { max-width: 620px; width: 100%; background: #111827; border: 1px solid #ef4444; border-radius: 12px; padding: 36px; box-shadow: 0 20px 40px rgba(239,68,68,0.15); text-align: center; }
        .shield-icon { font-size: 64px; margin-bottom: 16px; display: inline-block; filter: drop-shadow(0 0 12px #ef4444); }
        h1 { color: #f87171; font-size: 26px; font-weight: 800; margin-bottom: 12px; }
        p { color: #9ca3af; font-size: 15px; line-height: 1.6; margin-bottom: 24px; }
        .details-badge { background: #1f2937; border: 1px solid #374151; padding: 14px 18px; border-radius: 8px; text-align: left; font-family: monospace; font-size: 13px; color: #e5e7eb; margin-bottom: 24px; }
        .details-badge div { margin-bottom: 6px; }
        .details-badge div:last-child { margin-bottom: 0; }
        .tag { color: #ef4444; font-weight: bold; }
        .btn-return { display: inline-block; background: #2563eb; color: #fff; padding: 10px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; transition: 0.2s; }
        .btn-return:hover { background: #1d4ed8; }
    </style>
</head>
<body>
    <div class="shield-box">
        <div class="shield-icon">🛡️</div>
        <h1>403 Forbidden — Security Firewall Block</h1>
        <p>আপনার অনুরোধটি এন্টারপ্রাইজ সিকিউরিটি ফায়ারওয়াল দ্বারা ব্লক করা হয়েছে। সার্ভারের সার্বিক নিরাপত্তা রক্ষার্থে ক্ষতিকর বা অননুমোদিত রিকোয়েস্ট প্রতিহত করা হলো।</p>
        
        <div class="details-badge">
            <div><span class="tag">Security Trigger:</span> {{ reason }}</div>
            <div><span class="tag">Client IP:</span> {{ ip }}</div>
            <div><span class="tag">Country Code:</span> {{ country }}</div>
            <div><span class="tag">Timestamp:</span> {{ timestamp }}</div>
            <div><span class="tag">Incident ID:</span> WAF-{{ incident_id }}</div>
        </div>

        <a href="/news/" class="btn-return">নিউজ পোর্টাল হোমপেজে যান</a>
    </div>
</body>
</html>"""


def record_strike_and_check_autoban(ip: str, threat_type: str, payload_sample: str) -> bool:
    """Track IP strikes and auto-ban if threshold is reached."""
    if is_ip_whitelisted(ip):
        return False

    now = datetime.utcnow()
    if ip not in STRIKE_TRACKER:
        STRIKE_TRACKER[ip] = {"strikes": 1, "first_seen": now}
    else:
        info = STRIKE_TRACKER[ip]
        if now - info["first_seen"] > timedelta(minutes=STRIKE_WINDOW_MINUTES):
            STRIKE_TRACKER[ip] = {"strikes": 1, "first_seen": now}
        else:
            info["strikes"] += 1

    if STRIKE_TRACKER[ip]["strikes"] >= AUTO_BAN_THRESHOLD:
        from src.storage.database import get_db_session
        from src.storage.repositories import SecurityRepository
        with get_db_session() as sess:
            sec_repo = SecurityRepository(sess)
            sec_repo.block_ip(
                ip_address=ip,
                reason=f"Automated WAF Strike Ban ({threat_type}: {payload_sample[:50]})",
                blocked_by="WAF_AUTO_SHIELD",
                threat_score=100,
                duration_hours=24,
            )
        logger.warning(f"🚨 WAF Auto-Banned Malicious IP {ip} after {STRIKE_TRACKER[ip]['strikes']} strikes.")
        return True
    return False


def run_security_firewall():
    """
    Middleware function executed on every incoming HTTP request.
    Validates IP blacklist, Geo Country rules, and inspects malicious payloads.
    """
    path = request.path

    # Allow static assets and favicon to pass quickly
    if path.startswith("/static/") or path.startswith("/data/images/") or path == "/favicon.ico":
        return None

    client_ip = get_client_ip()
    client_country = get_client_country()

    from src.storage.database import get_db_session
    from src.storage.repositories import SecurityRepository

    with get_db_session() as sess:
        sec_repo = SecurityRepository(sess)

        # 1. Check IP Blacklist
        if sec_repo.is_ip_blocked(client_ip):
            logger.warning(f"🛑 Dropped request from Blacklisted IP: {client_ip} to {path}")
            # Log threat
            sec_repo.log_threat(
                threat_type="IP_BLACKLIST",
                ip_address=client_ip,
                request_path=path,
                request_method=request.method,
                payload_sample="Attempted access from blacklisted IP",
                country_code=client_country,
                user_agent=request.headers.get("User-Agent", "")[:450],
                action_taken="BLOCKED_403",
            )
            html = render_template_string(
                BLOCKED_PAGE_TEMPLATE,
                reason="IP Address is Blacklisted on Server",
                ip=client_ip,
                country=client_country,
                timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                incident_id=int(datetime.utcnow().timestamp()),
            )
            return html, 403

        # 2. Check Country / Geo-Firewall (ignore whitelisted local development IPs)
        if not is_ip_whitelisted(client_ip) and sec_repo.is_country_blocked(client_country):
            logger.warning(f"🛑 Dropped request from Geo-Blocked Country: {client_country} (IP: {client_ip}) to {path}")
            sec_repo.log_threat(
                threat_type="GEO_BLOCKED",
                ip_address=client_ip,
                request_path=path,
                request_method=request.method,
                payload_sample=f"Geographic access restricted for country: {client_country}",
                country_code=client_country,
                user_agent=request.headers.get("User-Agent", "")[:450],
                action_taken="BLOCKED_403",
            )
            html = render_template_string(
                BLOCKED_PAGE_TEMPLATE,
                reason=f"Geographic Region ({client_country}) Blocked by Administrator Policy",
                ip=client_ip,
                country=client_country,
                timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                incident_id=int(datetime.utcnow().timestamp()),
            )
            return html, 403

        # 3. WAF Payload Deep Inspection (SQLi, XSS, Path Traversal, RCE)
        threat = inspect_request_payloads()
        if threat:
            threat_type, sample = threat
            logger.error(f"🚨 WAF DETECTED THREAT [{threat_type}] from {client_ip} on {path}: {sample}")

            auto_banned = record_strike_and_check_autoban(client_ip, threat_type, sample)
            action_taken = "AUTO_BANNED_IP" if auto_banned else "BLOCKED_403"

            sec_repo.log_threat(
                threat_type=threat_type,
                ip_address=client_ip,
                request_path=path,
                request_method=request.method,
                payload_sample=sample,
                country_code=client_country,
                user_agent=request.headers.get("User-Agent", "")[:450],
                action_taken=action_taken,
            )

            html = render_template_string(
                BLOCKED_PAGE_TEMPLATE,
                reason=f"Malicious Payload Violation Detected ({threat_type})",
                ip=client_ip,
                country=client_country,
                timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                incident_id=int(datetime.utcnow().timestamp()),
            )
            return html, 403

    return None
