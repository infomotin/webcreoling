"""
Utility Functions.
Image SHA-256 calculation, date parsing (ISO & Bangla), filesystem helpers, and JSON serializers.
"""

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Dict
from src.common.normalizer import BanglaTextNormalizer
from src.common.bangla_calendar import BANGLA_GREGORIAN_MONTHS


def utcnow() -> datetime:
    """Single source of truth for 'now': timezone-aware UTC."""
    return datetime.now(timezone.utc)


def ensure_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Normalize a datetime to timezone-aware UTC.

    Naive values are interpreted as UTC (the storage convention used for
    MySQL DATETIME columns and form inputs), aware values are converted.
    Prevents ``TypeError: can't compare offset-naive and offset-aware
    datetimes`` at input/DB boundaries. Returns ``None`` unchanged.
    """
    if value is None or not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)



def compute_sha256(data: bytes) -> str:
    """Calculate the SHA-256 hash of a byte string."""
    return hashlib.sha256(data).hexdigest()


def compute_file_sha256(filepath: Path) -> str:
    """Calculate the SHA-256 hash of an existing file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def sanitize_filename(name: str, max_length: int = 60) -> str:
    """Create a safe, portable filename slug from arbitrary text."""
    if not name:
        return "unnamed"
    # Replace unsafe characters with hyphen
    cleaned = re.sub(r'[\\/*?:"<>|#%&{}\\<>*?/$!\'":@+`|=]+', "-", name)
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    return cleaned[:max_length] if cleaned else "unnamed"


def parse_iso_or_bangla_date(date_str: Optional[str]) -> Optional[datetime]:
    """
    Parse date from various formats including ISO-8601, RFC-2822, and common Bangla/English dates.
    Returns a Python datetime object or None if parsing fails.
    """
    if not date_str or not date_str.strip():
        return None

    date_str = date_str.strip()

    # Convert any Bengali digits to English digits first
    date_str = BanglaTextNormalizer.bangla_to_english_digits(date_str)

    # Standard ISO formats: 2026-09-22T11:45:00Z, 2026-09-22T11:45:00+06:00, 2026-09-22
    iso_candidates = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d %B %Y",
        "%d %b %Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
    ]

    for fmt in iso_candidates:
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue

    # Try regex extraction of YYYY-MM-DD
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", date_str)
    if match:
        try:
            y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
            return datetime(y, m, d)
        except ValueError:
            pass

    relative = _parse_relative_bangla_time(date_str)
    if relative is not None:
        return relative

    return _parse_bangla_gregorian_date(date_str)


# "৪ ঘণ্টা আগে" / "৩০ মিনিট আগে" — portals print a relative stamp for stories
# younger than a day, so resolve it against the moment we scraped the page.
_BN_RELATIVE_UNITS = (
    (r"(\d+)\s*সেকেন্ড", 1),
    (r"(\d+)\s*মিনিট", 60),
    (r"(\d+)\s*ঘণ্টা", 3600),
    (r"(\d+)\s*দিন", 86400),
    (r"(\d+)\s*সপ্তাহ", 604800),
)


def _parse_relative_bangla_time(text: str) -> Optional[datetime]:
    """Resolve a Bangla relative timestamp ("4 hours ago") to an absolute UTC datetime."""
    if "আগে" not in text and "গতকাল" not in text:
        return None

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for pattern, seconds_per_unit in _BN_RELATIVE_UNITS:
        match = re.search(pattern, text)
        if match:
            return now - timedelta(seconds=int(match.group(1)) * seconds_per_unit)
    if "গতকাল" in text:
        return now - timedelta(days=1)
    if "আজ" in text:
        return now
    return None


# Bangla Gregorian month names as printed on Bangladeshi news portals.
# "26 সেপ্টেম্বর 2026, 01:12 অপরাহ্ন" -> 26 Sep 2026 13:12
_BN_MERIDIEM_AM = ("পূর্বাহ্ন", "সকাল")
_BN_MERIDIEM_PM = ("অপরাহ্ন", "বিকাল", "রাত", "দুপুর")


def _parse_bangla_gregorian_date(text: str) -> Optional[datetime]:
    """Parse a Bangla calendar date written with Gregorian month names."""
    for index, month_name in enumerate(BANGLA_GREGORIAN_MONTHS, start=1):
        if month_name not in text:
            continue

        # "26 সেপ্টেম্বর 2026" (day-month-year)
        match = re.search(rf"(\d{{1,2}})\s*{re.escape(month_name)}\s*,?\s*(\d{{4}})", text)
        if match:
            day, year = int(match.group(1)), int(match.group(2))
        else:
            # "সেপ্টেম্বর 26, 2026" (month-day-year)
            match = re.search(rf"{re.escape(month_name)}\s*,?\s*(\d{{1,2}})\s*,?\s*(\d{{4}})", text)
            if not match:
                continue
            day, year = int(match.group(1)), int(match.group(2))

        try:
            parsed = datetime(year, index, day)
        except ValueError:
            continue

        clock = re.search(r"(\d{1,2}):(\d{2})", text)
        if clock:
            hour, minute = int(clock.group(1)), int(clock.group(2))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                if hour <= 12 and any(m in text for m in _BN_MERIDIEM_PM):
                    if hour < 12:
                        hour += 12
                elif hour == 12 and any(m in text for m in _BN_MERIDIEM_AM):
                    hour = 0
                parsed = parsed.replace(hour=hour, minute=minute)
        return parsed

    return None


def format_file_size(size_in_bytes: int) -> str:
    """Format byte count into human-readable string (KB, MB, GB)."""
    if size_in_bytes < 1024:
        return f"{size_in_bytes} B"
    elif size_in_bytes < 1024 * 1024:
        return f"{size_in_bytes / 1024:.1f} KB"
    else:
        return f"{size_in_bytes / (1024 * 1024):.2f} MB"


def safe_write_json(filepath: Path, data: Any, indent: int = 2) -> None:
    """Write data to a JSON file safely with parent directory creation."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent, default=str)


def safe_read_json(filepath: Path) -> Any:
    """Read data from a JSON file safely."""
    if not filepath.exists():
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)
