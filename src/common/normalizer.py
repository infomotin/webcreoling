"""
Bangla Text Normalizer & Sanitizer.
Handles Unicode normalization (NFC), zero-width character sanitization,
Bangla digit conversions, boilerplate removal, and text cleaning for LLM tokenization.
"""

import re
import unicodedata
from typing import Dict, List, Optional


class BanglaTextNormalizer:
    """Production-ready Unicode normalizer and cleaner for Bengali text."""

    # Bangla Unicode Range: \u0980-\u09FF
    BANGLA_DIGITS = "০১২৩৪৫৬৭৮৯"
    ENGLISH_DIGITS = "0123456789"
    BANGLA_TO_ENG_DIGITS: Dict[str, str] = dict(zip(BANGLA_DIGITS, ENGLISH_DIGITS))
    ENG_TO_BANGLA_DIGITS: Dict[str, str] = dict(zip(ENGLISH_DIGITS, BANGLA_DIGITS))

    # Common zero-width and invisible control characters
    ZERO_WIDTH_CHARS = [
        "\u200b",  # Zero-width space
        "\u200c",  # Zero-width non-joiner (ZWNJ)
        "\u200d",  # Zero-width joiner (ZWJ)
        "\ufeff",  # Byte order mark (BOM)
        "\u00a0",  # Non-breaking space
        "\u200e",  # Left-to-right mark
        "\u200f",  # Right-to-left mark
    ]

    # Newspaper boilerplate artifacts and captions to remove
    BOILERPLATE_PATTERNS: List[re.Pattern] = [
        re.compile(r"আরও\s*পড়ুন\s*:\s*[^\n]+", re.IGNORECASE),
        re.compile(r"ছবি\s*:\s*সংগৃহীত[^\n]*", re.IGNORECASE),
        re.compile(r"ফাইল\s*ছবি[^\n]*", re.IGNORECASE),
        re.compile(r"নিজস্ব\s*প্রতিবেদক\s*[,|\-]?\s*", re.IGNORECASE),
        re.compile(r"অনলাইন\s*ডেস্ক\s*[,|\-]?\s*", re.IGNORECASE),
        re.compile(r"বিশেষ\s*সংবাদদাতা\s*[,|\-]?\s*", re.IGNORECASE),
        re.compile(r"বিজ্ঞাপন\s*", re.IGNORECASE),
        re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE),  # URLs in body
    ]

    @classmethod
    def normalize_unicode(cls, text: str) -> str:
        """Apply Unicode NFC normalization to compose combining diacritics."""
        if not text:
            return ""
        return unicodedata.normalize("NFC", text)

    @classmethod
    def remove_zero_width_chars(cls, text: str, keep_zwnj_for_ligatures: bool = False) -> str:
        """Strip invisible formatting and zero-width artifacts."""
        if not text:
            return ""
        for char in cls.ZERO_WIDTH_CHARS:
            if keep_zwnj_for_ligatures and char == "\u200c":
                continue
            text = text.replace(char, "")
        return text

    @classmethod
    def remove_boilerplates(cls, text: str) -> str:
        """Strip common news site noise, captions, and related-article links."""
        if not text:
            return ""
        for pattern in cls.BOILERPLATE_PATTERNS:
            text = pattern.sub(" ", text)
        return text

    @classmethod
    def clean_whitespace(cls, text: str) -> str:
        """Standardize spaces, newlines, and tabs."""
        if not text:
            return ""
        # Collapse multiple spaces and tabs within lines
        text = re.sub(r"[ \t]+", " ", text)
        # Collapse multiple consecutive newlines into double newlines
        text = re.sub(r"\n\s*\n+", "\n\n", text)
        return text.strip()

    @classmethod
    def bangla_to_english_digits(cls, text: str) -> str:
        """Convert Bengali digits (০-৯) to English digits (0-9)."""
        if not text:
            return ""
        return "".join(cls.BANGLA_TO_ENG_DIGITS.get(ch, ch) for ch in text)

    @classmethod
    def english_to_bangla_digits(cls, text: str) -> str:
        """Convert English digits (0-9) to Bengali digits (০-৯)."""
        if not text:
            return ""
        return "".join(cls.ENG_TO_BANGLA_DIGITS.get(ch, ch) for ch in text)

    @classmethod
    def normalize_article_text(
        cls,
        text: str,
        remove_boilerplates: bool = True,
    ) -> str:
        """
        Complete end-to-end normalization pipeline for an article text.
        Produces clean, coherent Bengali text optimal for LLM training and tokenization.
        """
        if not text:
            return ""

        # 1. Unicode NFC Normalization
        text = cls.normalize_unicode(text)

        # 2. Remove invisible / zero-width characters
        text = cls.remove_zero_width_chars(text)

        # 3. Remove news boilerplate if requested
        if remove_boilerplates:
            text = cls.remove_boilerplates(text)

        # 4. Standardize quotes, dashes, and punctuation
        text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
        text = text.replace("—", " - ").replace("–", " - ")

        # 5. Clean whitespace
        text = cls.clean_whitespace(text)

        return text

    @classmethod
    def extract_sentences(cls, text: str) -> List[str]:
        """Split Bangla text into sentences using Bangla dari (|) and English punctuation."""
        if not text:
            return []
        # Split on Bangla dari (।), exclamation, question mark, or standard period
        sentences = re.split(r"[।?!।\n]+", text)
        return [cls.clean_whitespace(s) for s in sentences if cls.clean_whitespace(s)]
