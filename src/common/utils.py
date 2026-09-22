"""
Utility Functions.
Image SHA-256 calculation, date parsing (ISO & Bangla), filesystem helpers, and JSON serializers.
"""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Dict
from src.common.normalizer import BanglaTextNormalizer


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
