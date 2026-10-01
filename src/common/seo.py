"""
SEO helpers: transliteration, slug generation and canonical post permalinks.

Public posts are served at `/news/<post_slug>` where the slug always starts with
the article id: `1602-dhaka-fire-incident`. Bengali headlines are transliterated
to Latin so the URL stays readable, ASCII safe and search-engine friendly.
"""

import re
import unicodedata
from typing import Optional

# Bengali consonants
_CONSONANTS = {
    "ক": "k", "খ": "kh", "গ": "g", "ঘ": "gh", "ঙ": "ng",
    "চ": "ch", "ছ": "ch", "জ": "j", "ঝ": "jh", "ঞ": "n",
    "ট": "t", "ঠ": "th", "ড": "d", "ঢ": "dh", "ণ": "n",
    "ত": "t", "থ": "th", "দ": "d", "ধ": "dh", "ন": "n",
    "প": "p", "ফ": "f", "ব": "b", "ভ": "bh", "ম": "m",
    "য": "y", "র": "r", "ল": "l",
    "শ": "sh", "ষ": "ss", "স": "s", "হ": "h",
    "ড়": "r", "ঢ়": "rh", "য়": "y", "ৎ": "t",
}

# Independent vowels
_VOWELS = {
    "অ": "a", "আ": "a", "ই": "i", "ঈ": "i", "উ": "u", "ঊ": "u",
    "ঋ": "ri", "এ": "e", "ঐ": "oi", "ও": "o", "ঔ": "au",
}

# Dependent vowel signs (matra)
_MATRAS = {
    "া": "a", "ি": "i", "ী": "i", "ু": "u", "ূ": "u", "ৃ": "ri",
    "ে": "e", "ৈ": "oi", "ো": "o", "ৌ": "au", "ৗ": "au",
}

# Diacritics / signs that do not add a syllable
_IGNORED = {"ঁ", "ং", "ঃ", "়", "্"}

_DIGITS = {"০": "0", "১": "1", "২": "2", "৩": "3", "৪": "4",
           "৫": "5", "৬": "6", "৭": "7", "৮": "8", "৯": "9"}

POST_SLUG_RE = re.compile(r"^(?P<id>\d+)(?:-(?P<rest>[a-z0-9\-]*))?$")
MAX_SLUG_WORDS = 10


def transliterate(text: str) -> str:
    """Best-effort Bengali → Latin transliteration (keeps ASCII text as-is)."""
    if not text:
        return ""

    # Normalise: decompose and drop canonical combining marks (nukta etc.)
    text = unicodedata.normalize("NFC", text)
    out = []
    for ch in text:
        if ch in _IGNORED:
            continue
        if ch in _DIGITS:
            out.append(_DIGITS[ch])
        elif ch in _CONSONANTS:
            out.append(_CONSONANTS[ch])
        elif ch in _MATRAS:
            out.append(_MATRAS[ch])
        elif ch in _VOWELS:
            out.append(_VOWELS[ch])
        elif ch.isalnum() and ch.isascii():
            out.append(ch.lower())
        elif ch.isspace() or ch in "-–—_.,":
            out.append(" ")
        # anything else is dropped
    return "".join(out)


def slugify(text: str, max_words: int = MAX_SLUG_WORDS) -> str:
    """Build a lowercase ASCII slug; returns '' when nothing usable remains."""
    raw = transliterate(text)
    raw = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    raw = re.sub(r"-{2,}", "-", raw)
    if not raw:
        return ""
    words = [w for w in raw.split("-") if w]
    slug = "-".join(words[:max_words])
    return slug[:120].strip("-")


def build_post_slug(article_id: int, title: str) -> str:
    """Canonical permalink slug: `<id>-<readable-title>` (never empty)."""
    readable = slugify(title or "")
    return f"{article_id}-{readable}" if readable else f"{article_id}-news"


def parse_post_slug(value: str) -> Optional[int]:
    """Extract the article id from a canonical slug, or None if invalid."""
    if not value:
        return None
    match = POST_SLUG_RE.match(value.strip().lower())
    if not match:
        return None
    return int(match.group("id"))


def canonical_path(slug: Optional[str], article_id: int) -> str:
    """Public permalink for a post."""
    return f"/news/{slug}" if slug else f"/news/{article_id}"


def build_meta_description(summary: Optional[str], content: Optional[str], limit: int = 155) -> str:
    """Plain-text meta description for search engines."""
    text = (summary or "").strip() or (content or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:limit].rstrip()


def embeddable_video_url(url: str) -> Optional[str]:
    """
    Normalise a share link into an embeddable iframe URL.
    Supports YouTube (watch / youtu.be / shorts), Facebook posts and Vimeo.
    """
    if not url:
        return None
    url = url.strip()

    # Already an embed URL
    if "youtube.com/embed/" in url or "player.vimeo.com/video/" in url:
        return url

    youtube = re.search(
        r"(?:youtube\.com/(?:watch\?.*?v=|shorts/|embed/)|youtu\.be/)([\w\-]{6,20})", url
    )
    if youtube:
        return f"https://www.youtube.com/embed/{youtube.group(1)}"

    vimeo = re.search(r"vimeo\.com/(\d+)", url)
    if vimeo:
        return f"https://player.vimeo.com/video/{vimeo.group(1)}"

    if re.match(r"^https?://", url):
        return url
    return None
