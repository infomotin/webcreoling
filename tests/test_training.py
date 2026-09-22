"""Unit tests for Training, Preprocessing, and Normalizer."""

import pytest
from src.common.normalizer import BanglaTextNormalizer
from src.training.preprocessor import TextPreprocessor
from src.storage.models import Article


def test_bangla_normalizer_unicode_and_zwnj():
    raw = "বাংলাদেশ\u200cের উন্নয়ন  কাজ\u200b চলছে।"
    cleaned = BanglaTextNormalizer.normalize_article_text(raw)
    assert "\u200b" not in cleaned
    assert "\u200c" not in cleaned
    assert "বাংলাদেশের" in cleaned
    assert "কাজ চলছে।" in cleaned


def test_bangla_digits_conversion():
    bangla_num = "২০২৬ সালে"
    eng_num = BanglaTextNormalizer.bangla_to_english_digits(bangla_num)
    assert "2026" in eng_num

    converted_back = BanglaTextNormalizer.english_to_bangla_digits(eng_num)
    assert "২০২৬" in converted_back


def test_preprocessor_formatting():
    preprocessor = TextPreprocessor(min_char_length=30)
    article = Article(
        id=1,
        title="বাজেট ২০২৬",
        category="business",
        content_text="নতুন অর্থবছরের জাতীয় বাজেট সংসদে পেশ করা হয়েছে। সকল ক্ষেত্রে উন্নয়ন বরাদ্দ বৃদ্ধি পেয়েছে।",
    )
    formatted = preprocessor.prepare_causal_lm_text(article)
    assert formatted is not None
    assert "শিরোনাম: বাজেট ২০২৬" in formatted
    assert "বিভাগ: business" in formatted
    assert "<|endoftext|>" in formatted
