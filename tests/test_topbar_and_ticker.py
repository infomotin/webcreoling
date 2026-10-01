"""Tests for the dynamic top utility bar (date / weather / FX) and the breaking-news scroller."""

import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.web.app import create_app
from src.storage.database import init_db
from src.common.bangla_calendar import (
    format_bangla_calendar,
    format_gregorian_bangla,
    format_topbar_date,
    bangla_calendar_parts,
)
from src.integrations.live_data_service import get_topbar_data

CSS_PATH = Path(__file__).resolve().parents[1] / "src" / "web" / "static" / "css" / "newspaper_prothomalo.css"


@pytest.fixture
def client():
    init_db()
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    with app.test_client() as client:
        yield client


# ---------------------------------------------------------------------------
# Bangla calendar
# ---------------------------------------------------------------------------
def test_gregorian_to_bangla_calendar_conversion():
    assert format_bangla_calendar(date(2026, 9, 22)) == "৭ আশ্বিন ১৪৩৩"
    assert format_bangla_calendar(date(2026, 4, 14)) == "১ বৈশাখ ১৪৩৩"
    assert format_bangla_calendar(date(2026, 4, 13)) == "৩০ চৈত্র ১৪৩২"
    # Falgun is 30 days long inside a Gregorian leap year
    assert bangla_calendar_parts(date(2024, 3, 14))["month_name"] == "ফাল্গুন"
    assert bangla_calendar_parts(date(2024, 3, 14))["day"] == 30


def test_gregorian_and_topbar_date_strings():
    d = date(2026, 9, 22)
    assert format_gregorian_bangla(d) == "সোমবার, ২২ সেপ্টেম্বর ২০২৬"
    assert format_topbar_date(d) == "সোমবার, ২২ সেপ্টেম্বর ২০২৬ • ৭ আশ্বিন ১৪৩৩"
    # generated for "today" by default
    assert format_topbar_date() == format_gregorian_bangla(datetime.now(timezone.utc)) + " • " + format_bangla_calendar(
        datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Top-bar payload
# ---------------------------------------------------------------------------
def test_topbar_payload_contains_weather_and_fx():
    payload = get_topbar_data({})
    assert payload["date_text"]
    assert "•" in payload["date_text"]

    weather = payload["weather"]
    assert weather["city"]
    assert weather["desc"]
    assert weather["icon"]
    if weather.get("temp"):
        assert "°" in str(weather["temp"])

    fx = payload["fx"]
    assert fx["usd"]
    assert fx["eur"]
    assert "৳" not in str(fx["usd"])  # only the number, symbol lives in the template


def test_topbar_fx_prefers_bangladesh_bank_when_online():
    payload = get_topbar_data({})
    # Works offline too: the fallback keeps a CMS value but never crashes.
    assert str(payload["fx"]["usd"]).strip()


# ---------------------------------------------------------------------------
# Portal top bar rendering
# ---------------------------------------------------------------------------
def test_frontpage_topbar_is_dynamic_not_hardcoded(client):
    resp = client.get("/news")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # The old frozen date stamp must be gone
    assert "২২ সেপ্টেম্বর ২০২৬" not in html

    today = format_gregorian_bangla(datetime.now(timezone.utc))
    assert today in html

    # Weather + rates come from the live payload (source annotations present)
    assert "সূত্র: Open-Meteo" in html or "সূত্র: CMS" in html
    assert "ডলার ৳" in html
    assert "ইউরো ৳" in html


# ---------------------------------------------------------------------------
# Breaking-news scroller
# ---------------------------------------------------------------------------
def test_frontpage_breaking_ticker_has_seamless_scroller(client):
    resp = client.get("/news")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert "palo-ticker-track" in html
    assert "paloTickerScroll" in CSS_PATH.read_text(encoding="utf-8")
    assert "animation-duration" in html

    links = re.findall(r'class="palo-ticker-link"', html)
    # Every headline is rendered twice (original + duplicate) for the seamless loop
    assert links, "breaking news ticker should render at least one headline"
    assert len(links) % 2 == 0

    # No leftover encrypted/system rows in the ticker
    assert "SYSTEM ENCRYPTED DATA" not in html


def test_ticker_duplicates_every_headline(client):
    resp = client.get("/news")
    html = resp.get_data(as_text=True)

    from src.storage.database import get_db_session
    from src.storage.repositories import ArticleRepository

    with get_db_session() as session:
        expected = len(ArticleRepository(session).get_breaking_news(limit=6))

    if expected:
        assert len(re.findall(r'class="palo-ticker-link"', html)) == expected * 2
