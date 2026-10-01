"""
Live top-bar data: Bangla date, weather and USD/EUR rates.

Sources (all free, no API key required):
    - Weather : Open-Meteo (https://open-meteo.com)
    - USD     : Bangladesh Bank inter-bank FX rate (https://www.bb.org.bd)
                -> fallback open.er-api.com (ExchangeRate-API free tier)
    - EUR     : open.er-api.com cross rate (Bangladesh Bank does not publish EUR)

Everything is cached in-process so the public portal never blocks on the network.
Failed refreshes keep serving the last good values, then the CMS branding values.
"""

import re
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

import requests

from src.common.bangla_calendar import format_topbar_date, to_bangla_digits
from src.common.logger import get_logger

logger = get_logger("webcreoling.integrations.live_data")

BB_FX_URL = "https://www.bb.org.bd/en/index.php?view=ForexRates"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_ER_API_URL = "https://open.er-api.com/v6/latest/USD"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_TIMEOUT = 6

WEATHER_TTL = 15 * 60
FX_TTL = 6 * 60 * 60

# Bangla city label -> (latitude, longitude)
CITY_COORDS = {
    "ঢাকা": (23.8103, 90.4125),
    "চট্টগ্রাম": (22.3569, 91.7832),
    "রাজশাহী": (24.3745, 88.6042),
    "খুলনা": (22.8088, 89.5644),
    "বরিশাল": (22.7010, 90.3535),
    "সিলেট": (24.8949, 91.8687),
    "রংপুর": (25.7439, 89.2752),
    "ময়মনসিংহ": (24.7471, 90.4167),
    "কক্সবাজার": (21.4376, 91.9775),
    "সৌদি আরব": (24.7136, 46.6753),
    "ঢাকা সিটি": (23.8103, 90.4125),
    "Dhaka": (23.8103, 90.4125),
    "Chattogram": (22.3569, 91.7832),
    "Chittagong": (22.3569, 91.7832),
    "Chakria": (21.4376, 91.9775),
}

# WMO weather interpretation codes -> (Bangla description, emoji)
WEATHER_CODES = {
    0: ("পরিষ্কার আকাশ", "☀️"),
    1: ("প্রধানত পরিষ্কার", "🌤️"),
    2: ("আংশিক মেঘলা", "⛅"),
    3: ("মেঘলা", "☁️"),
    45: ("কুয়াশা", "🌫️"),
    48: ("ঘন কুয়াশা", "🌫️"),
    51: ("হালকা গুঁড়ি বৃষ্টি", "🌦️"),
    53: ("গুঁড়ি গুঁড়ি বৃষ্টি", "🌦️"),
    55: ("ঘন গুঁড়ি বৃষ্টি", "🌧️"),
    56: ("হিম গুঁড়ি বৃষ্টি", "🌧️"),
    57: ("ঘন হিম গুঁড়ি", "🌧️"),
    61: ("হালকা বৃষ্টি", "🌦️"),
    63: ("মাঝারি বৃষ্টি", "🌧️"),
    65: ("প্রবল বৃষ্টি", "🌧️"),
    66: ("হাড়িপাড়ি বৃষ্টি", "🌧️"),
    67: ("প্রবল হাড়িপাড়ি", "🌧️"),
    71: ("হালকা তুষারপাত", "🌨️"),
    73: ("মাঝারি তুষারপাত", "🌨️"),
    75: ("প্রবল তুষারপাত", "❄️"),
    77: ("তুষার কণা", "❄️"),
    80: ("বৃষ্টির ছোঁয়া", "🌦️"),
    81: ("বৃষ্টির ঝড়", "🌧️"),
    82: ("তীব্র বৃষ্টি", "⛈️"),
    85: ("তুষার ঝড়", "🌨️"),
    86: ("তীব্র তুষার ঝড়", "❄️"),
    95: ("বজ্রসহ বৃষ্টি", "⛈️"),
    96: ("বজ্রসহ শিলাবৃষ্টি", "⛈️"),
    99: ("তীব্র বজ্রসহ বৃষ্টি", "⛈️"),
}

_cache: Dict[str, tuple] = {}
_cache_lock = threading.Lock()


def _cached(key: str, ttl: int) -> Optional[Any]:
    with _cache_lock:
        entry = _cache.get(key)
        if not entry:
            return None
        ts, value = entry
        if time.time() - ts > ttl:
            return None
        return value


def _store(key: str, value: Any) -> Any:
    with _cache_lock:
        _cache[key] = (time.time(), value)
    return value


def _get_json(url: str, **kwargs) -> dict:
    resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=kwargs.pop("headers", BROWSER_HEADERS), **kwargs)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------
def fetch_weather(city: str = "ঢাকা") -> Dict[str, Any]:
    """Current conditions for a Bangla/English city label via Open-Meteo."""
    cache_key = f"weather::{city}"
    cached = _cached(cache_key, WEATHER_TTL)
    if cached:
        return cached

    lat, lon = CITY_COORDS.get(city, CITY_COORDS["ঢাকা"])
    data = _get_json(
        OPEN_METEO_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,weather_code,relative_humidity_2m,wind_speed_10m",
            "timezone": "Asia/Dhaka",
        },
    )
    current = data.get("current", {})
    code = int(current.get("weather_code", -1))
    desc, emoji = WEATHER_CODES.get(code, ("আবহাওয়া ভালো", "🌤️"))
    temp = current.get("temperature_2m")

    payload = {
        "city": city or "ঢাকা",
        "temp": f"{to_bangla_digits(int(round(temp)))}° সে." if temp is not None else None,
        "temp_c": round(float(temp), 1) if temp is not None else None,
        "desc": desc,
        "icon": emoji,
        "humidity": current.get("relative_humidity_2m"),
        "wind": current.get("wind_speed_10m"),
        "source": "Open-Meteo",
        "updated_at": datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M"),
    }
    return _store(cache_key, payload)


# ---------------------------------------------------------------------------
# Currency rates
# ---------------------------------------------------------------------------
def _fetch_bb_usd() -> Optional[Dict[str, Any]]:
    """USD/BDT inter-bank rate published by Bangladesh Bank."""
    resp = requests.get(BB_FX_URL, timeout=REQUEST_TIMEOUT, headers=BROWSER_HEADERS)
    resp.raise_for_status()
    html = resp.text
    match = re.search(
        r"USD\s*</div>\s*<div>\s*([0-9]+(?:\.[0-9]+)?)\s*</div>\s*"
        r"<div>\s*([0-9]+(?:\.[0-9]+)?)\s*</div>\s*"
        r"<div>\s*([0-9]+(?:\.[0-9]+)?)\s*</div>",
        html,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError("Bangladesh Bank USD row not found")

    highest, lowest, war = (float(match.group(i)) for i in (1, 2, 3))
    rate = war or round((highest + lowest) / 2, 4)
    updated = None
    upd = re.search(r"Last update:\s*([^<]+)", html[match.end():])
    if upd:
        updated = upd.group(1).strip()
    return {"rate": rate, "source": "বাংলাদেশ ব্যাংক", "updated": updated, "detail": f"H:{highest} L:{lowest} W:{war}"}


def _fetch_open_api_rates() -> Dict[str, Any]:
    """Free no-key fallback: USD & EUR against BDT."""
    data = _get_json(OPEN_ER_API_URL)
    if data.get("result") != "success":
        raise ValueError("open.er-api.com returned an error payload")
    rates = data.get("rates", {})
    bdt = float(rates["BDT"])
    eur = float(rates["EUR"])
    return {
        "usd": round(bdt, 2),
        "eur": round(bdt / eur, 2),
        "source": data.get("provider") or "Open Exchange API",
        "updated": data.get("time_last_update_utc"),
    }


def fetch_fx_rates() -> Dict[str, Any]:
    """USD (Bangladesh Bank first) + EUR rates with graceful fallbacks."""
    cached = _cached("fx", FX_TTL)
    if cached:
        return cached

    payload: Dict[str, Any] = {"usd": None, "eur": None, "usd_source": None, "eur_source": None, "updated": None}

    try:
        bb = _fetch_bb_usd()
        payload["usd"] = round(bb["rate"], 2)
        payload["usd_source"] = bb["source"]
        payload["bb_detail"] = bb.get("detail")
        payload["updated"] = bb.get("updated")
    except Exception as exc:
        logger.warning(f"Bangladesh Bank FX fetch failed: {exc}")

    try:
        open_rates = _fetch_open_api_rates()
        if payload["usd"] is None:
            payload["usd"] = open_rates["usd"]
            payload["usd_source"] = "Open Exchange API"
        payload["eur"] = open_rates["eur"]
        payload["eur_source"] = open_rates["source"]
        payload.setdefault("updated", open_rates.get("updated"))
    except Exception as exc:
        logger.warning(f"Open FX API fetch failed: {exc}")

    if payload["usd"] is None:
        return cached or payload
    return _store("fx", payload)


# ---------------------------------------------------------------------------
# Combined top-bar payload
# ---------------------------------------------------------------------------
def get_topbar_data(branding: Optional[dict] = None) -> Dict[str, Any]:
    """Everything the portal top utility bar renders."""
    branding = branding or {}
    now = datetime.now(datetime.UTC)

    weather_city = (branding.get("weather_city") or "ঢাকা").strip()
    weather: Dict[str, Any]
    try:
        weather = dict(fetch_weather(weather_city))
    except Exception as exc:
        logger.warning(f"Weather fetch failed, using CMS fallback: {exc}")
        weather = {
            "city": weather_city,
            "temp": branding.get("weather_temp") or "২৮° সে.",
            "desc": branding.get("weather_desc") or "আংশিক মেঘলা",
            "icon": "⛅",
            "source": "CMS",
            "updated_at": None,
        }

    try:
        fx = dict(fetch_fx_rates())
    except Exception as exc:
        logger.warning(f"FX fetch failed, using CMS fallback: {exc}")
        fx = {"usd": None, "eur": None, "usd_source": None, "eur_source": None, "updated": None}

    if not fx.get("usd"):
        fx["usd"] = branding.get("usd_rate") or "১২১.৫০"
        fx["usd_source"] = fx.get("usd_source") or "CMS"
    if not fx.get("eur"):
        fx["eur"] = branding.get("eur_rate") or "১৩২.২০"
        fx["eur_source"] = fx.get("eur_source") or "CMS"

    # Display everything with Bengali numerals (keep raw numbers for reuse)
    if isinstance(fx.get("usd"), (int, float)):
        fx["usd_value"] = round(float(fx["usd"]), 2)
        fx["usd"] = to_bangla_digits(f"{fx['usd_value']:.2f}")
    if isinstance(fx.get("eur"), (int, float)):
        fx["eur_value"] = round(float(fx["eur"]), 2)
        fx["eur"] = to_bangla_digits(f"{fx['eur_value']:.2f}")

    return {
        "date_text": format_topbar_date(now),
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "weather": weather,
        "fx": fx,
    }
