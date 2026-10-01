"""
Bangla (Bengali) calendar + Bangla date formatting helpers.

Bangladesh's national calendar (Shahidullah committee 1966, adopted 1987,
revised 2019):
    - The year starts on 14 April (Pohela Boishakh).
    - Boishakh ... Ashwin have 31 days each.
    - Kartik, Ogrohayon, Poush, Magh have 30 days each.
    - Falgun has 29 days (30 in a Gregorian leap year).
    - Chaitra has 30 days.
"""

import calendar
from datetime import date, datetime
from typing import Dict, Union

from src.common.normalizer import BanglaTextNormalizer

BANGLA_MONTHS = [
    "বৈশাখ",
    "জ্যৈষ্ঠ",
    "আষাঢ়",
    "শ্রাবণ",
    "ভাদ্র",
    "আশ্বিন",
    "কার্তিক",
    "অগ্রহায়ণ",
    "পৌষ",
    "মাঘ",
    "ফাল্গুন",
    "চৈত্র",
]

BANGLA_WEEKDAYS = [
    "রবিবার",
    "সোমবার",
    "মঙ্গলবার",
    "বুধবার",
    "বৃহস্পতিবার",
    "শুক্রবার",
    "শনিবার",
]

BANGLA_GREGORIAN_MONTHS = [
    "জানুয়ারি",
    "ফেব্রুয়ারি",
    "মার্চ",
    "এপ্রিল",
    "মে",
    "জুন",
    "জুলাই",
    "আগস্ট",
    "সেপ্টেম্বর",
    "অক্টোবর",
    "নভেম্বর",
    "ডিসেম্বর",
]

BANGLA_YEAR_OFFSET = 593
BAISHAKH_START = (4, 14)


def to_bangla_digits(value: Union[int, float, str]) -> str:
    """Render a number/string using Bengali numerals (০-৯)."""
    if isinstance(value, float):
        text = f"{value:.2f}"
    else:
        text = str(value)
    return BanglaTextNormalizer.english_to_bangla_digits(text)


def _coerce(value: Union[datetime, date]) -> date:
    if isinstance(value, datetime):
        return value.date()
    return value


def bangla_calendar_parts(value: Union[datetime, date]) -> Dict[str, Union[int, str]]:
    """Break a Gregorian date into Bangla-calendar day / month / year parts."""
    day = _coerce(value)
    start_year = day.year if (day.month, day.day) >= BAISHAKH_START else day.year - 1
    start = date(start_year, *BAISHAKH_START)
    offset = (day - start).days

    falgun_days = 30 if calendar.isleap(start_year + 1) else 29
    month_lengths = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, falgun_days, 30]

    month_index = 0
    remaining = offset
    for length in month_lengths:
        if remaining < length:
            break
        remaining -= length
        month_index += 1
    month_index = min(month_index, 11)

    return {
        "day": remaining + 1,
        "month": month_index,
        "month_name": BANGLA_MONTHS[month_index],
        "year": start_year - BANGLA_YEAR_OFFSET,
    }


def format_bangla_calendar(value: Union[datetime, date]) -> str:
    """e.g. '৭ আশ্বিন ১৪৩৩'."""
    parts = bangla_calendar_parts(value)
    return f"{to_bangla_digits(parts['day'])} {parts['month_name']} {to_bangla_digits(parts['year'])}"


def format_gregorian_bangla(value: Union[datetime, date]) -> str:
    """e.g. 'মঙ্গলবার, ২২ সেপ্টেম্বর ২০২৬'."""
    day = _coerce(value)
    weekday = BANGLA_WEEKDAYS[day.weekday()]
    month = BANGLA_GREGORIAN_MONTHS[day.month - 1]
    return f"{weekday}, {to_bangla_digits(day.day)} {month} {to_bangla_digits(day.year)}"


def format_topbar_date(value: Union[datetime, date, None] = None) -> str:
    """Full top-bar date line combining the Gregorian and Bangla calendars."""
    day = value or datetime.now(datetime.UTC)
    return f"{format_gregorian_bangla(day)} • {format_bangla_calendar(day)}"
