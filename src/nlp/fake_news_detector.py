"""
AI Fake News & Fact-Checking Detector Model for WebCreoling.
Calculates Fake News Probability Percentage (0% - 100%), Factuality Confidence,
Linguistic Sensationalism, Anonymous Attribution Signals, and Domain Trustworthiness.
"""

import re
from typing import Dict, Any, List, Optional, Tuple
from src.common.logger import get_logger

logger = get_logger("webcreoling.nlp.fake_news_detector")


class FakeNewsDetectorEngine:
    """
    Evaluates articles for misinformation, sensationalism, clickbait, and fabrication.
    Produces a precise Fake News Probability (0.0% to 100.0%) and fact-check verdict.
    """

    # Sensational / Clickbait / Hoax / Exaggeration markers
    SENSATIONAL_KEYWORDS = [
        "বিস্ফোরক তথ্য", "চমকে দেওয়া", "অবিশ্বাস্য খবর", "গোপন ফাঁস",
        "হাতে নাতে ধরা", "হতবাক বিশ্ব", "না দেখলে চরম মিস", "ভাইরাল ভিডিও",
        "মহা বিপর্যয়", "রহস্যময় মৃত্যু", "ভুয়া", "গুজব", "মিথ্যা দাবি",
        "আসল সত্য ফাঁস", "মহাবিশ্ব কাঁপানো", "দেখুন কি করলেন", "চরম শিক্ষা",
        "shocking", "unbelievable", "you won't believe", "miracle cure",
        "viral video", "exposed", "secret leak", "breaking viral hoax",
    ]

    # Vague / Anonymous / Unverified Attribution patterns
    UNVERIFIED_ATTRIBUTION_PATTERNS = [
        r"বিশ্বস্ত সূত্রে জানা গেছে কিন্তু নাম প্রকাশে অনিচ্ছুক",
        r"নাম প্রকাশে অনিচ্ছুক এক কর্মকর্তা",
        r"সোশ্যাল মিডিয়ায় ছড়িয়ে পড়েছে",
        r"ফেসবুকে ভাইরাল হওয়া বার্তায়",
        r"গুঞ্জন উঠেছে",
        r"অনেকের দাবি",
        r"নাম প্রকাশ না করার শর্তে",
        r"বলা হচ্ছে যে",
        r"viral on social media",
        r"unconfirmed sources claim",
        r"rumors suggest",
    ]

    # Extreme Emotional / Urgency Call-to-Action Triggers
    EMOTIONAL_URGENCY_TRIGGERS = [
        "এখনই শেয়ার করুন", "সবাইকে জানিয়ে দিন", "চোখ কপালে উঠবে",
        "দেরি করবেন না", "না শেয়ার করলে বিপদ", "সাবধান সবাই",
        "share this immediately", "must watch", "warning to all",
    ]

    # Verified Reputable Journalism Domains / Outlets (High Trust)
    TRUSTED_DOMAINS = [
        "prothom alo", "প্রথম আলো", "the daily star", "ডেইলি স্টার",
        "bbc bangla", "bbc news", "বিবিসি বাংলা", "reuters", "al jazeera",
        "associated press", "ap news", "somoy tv", "jamuna tv", "dw বাংলা",
        "dw news", "bloomberg", "the guardian", "bdnews24", "dhaka tribune",
        "ittefaq", "কালের কণ্ঠ", "যুগান্তর",
    ]

    # Known Disinformation / Clickbait / Satire Sources
    UNVERIFIED_OR_SATIRE_DOMAINS = [
        "viral_rumor_desk", "unknown_blog", "clickbait_wire",
        "facebook_unverified_feed", "tik_rumor",
    ]

    @classmethod
    def evaluate(
        cls,
        title: str,
        content: str,
        source: str = "Open News Wire",
        author: Optional[str] = None,
        max_allowed_fake_pct: float = 50.0,
    ) -> Dict[str, Any]:
        """
        Calculates the Fake News Probability Percentage (0.0% - 100.0%) and returns
        a complete fact-checking report and publishability verdict.
        """
        title = title or ""
        content = content or ""
        source = source or ""
        author = author or ""
        combined_text = f"{title} {content}".lower()

        # Base neutral starting fake risk probability (35.0%)
        fake_risk: float = 35.0
        flags: List[str] = []
        source_lower = source.lower()

        # ----------------------------------------------------------------------
        # 1. Source Trustworthiness Weighting
        # ----------------------------------------------------------------------
        is_trusted = any(td in source_lower for td in cls.TRUSTED_DOMAINS)
        is_suspicious_source = any(sd in source_lower for sd in cls.UNVERIFIED_OR_SATIRE_DOMAINS)

        if is_trusted:
            fake_risk -= 25.0
            source_trust = 92.0
            flags.append("বিশ্বস্ত ও অনুমোদিত মূলধারার সংবাদ সংস্থা (-25% ফেক ঝুঁকি)")
        elif is_suspicious_source:
            fake_risk += 35.0
            source_trust = 25.0
            flags.append("অযাচাইকৃত অথবা ক্লিকবেট সংবাদ সোর্স (+35% ফেক ঝুঁকি)")
        else:
            source_trust = 60.0

        # ----------------------------------------------------------------------
        # 2. Sensationalism & Clickbait Term Analysis
        # ----------------------------------------------------------------------
        detected_sensational = []
        for kw in cls.SENSATIONAL_KEYWORDS:
            if kw.lower() in combined_text:
                detected_sensational.append(kw)

        if detected_sensational:
            penalty = min(35.0, len(detected_sensational) * 12.0)
            fake_risk += penalty
            flags.append(f"অতিরঞ্জিত/ক্লিকবেট শব্দ সনাক্ত ({', '.join(detected_sensational[:3])}) (+{penalty:.0f}%)")

        clickbait_index = min(100.0, len(detected_sensational) * 22.0)

        # ----------------------------------------------------------------------
        # 3. Anonymous / Unverified Attribution Signals
        # ----------------------------------------------------------------------
        unverified_patterns_matched = []
        for pattern in cls.UNVERIFIED_ATTRIBUTION_PATTERNS:
            if re.search(pattern, combined_text, re.IGNORECASE):
                unverified_patterns_matched.append(pattern)

        if unverified_patterns_matched:
            fake_risk += 18.0
            flags.append("অস্পষ্ট/বেনামী তথ্যসূত্রের উদ্ধৃতি (+18% ফেক ঝুঁকি)")

        # ----------------------------------------------------------------------
        # 4. Emotional Manipulation & Viral Call-to-Action Triggers
        # ----------------------------------------------------------------------
        urgency_found = []
        for trigger in cls.EMOTIONAL_URGENCY_TRIGGERS:
            if trigger.lower() in combined_text:
                urgency_found.append(trigger)

        if urgency_found:
            fake_risk += 15.0
            flags.append(f"আবেগীয় কারসাজি ও ভাইরাল করার নির্দেশাবলী ({', '.join(urgency_found[:2])}) (+15%)")

        # ----------------------------------------------------------------------
        # 5. Punctuation & Typography Extremism
        # ----------------------------------------------------------------------
        if "???" in title or "!!!" in title or "?!" in title or "!?" in title:
            fake_risk += 10.0
            flags.append("অস্বাভাবিক বিরামচিহ্ন/আবেগপূর্ণ শিরোনাম (+10%)")

        # ----------------------------------------------------------------------
        # 6. Content Depth, Quotations & Named Entity Verifiability
        # ----------------------------------------------------------------------
        content_len = len(content.strip())
        has_direct_quotes = any(q in content for q in ["“", "”", '"', "বলেছেন", "জানান", "মন্তব্য করেন", "said", "stated"])

        if has_direct_quotes:
            fake_risk -= 12.0
            flags.append("প্রত্যক্ষ উক্তি ও প্রাতিষ্ঠানিক বক্তব্য উপস্থিত (-12% ফেক ঝুঁকি)")

        if content_len >= 600:
            fake_risk -= 10.0
            flags.append("পূর্ণাঙ্গ ও তথ্যসমৃদ্ধ সংবাদ কলেবর (-10% ফেক ঝুঁকি)")
        elif content_len < 150:
            fake_risk += 15.0
            flags.append("অত্যন্ত সংক্ষিপ্ত ও অনুমানের ওপর নির্ভরশীল (+15% ফেক ঝুঁকি)")

        # ----------------------------------------------------------------------
        # 7. Final Fake Probability & Verdict Calculation
        # ----------------------------------------------------------------------
        # Clamp fake probability strictly between 2.0% and 98.0%
        final_fake_pct = round(min(98.0, max(2.0, fake_risk)), 1)
        factuality_score = round(100.0 - final_fake_pct, 1)

        # Categorical Verdict
        if final_fake_pct <= 20.0:
            verdict = "AUTHENTIC"
            verdict_label = "শতভাগ খাঁটি ও যাচাইকৃত"
            badge_color = "#10b981"  # Emerald Green
        elif final_fake_pct <= 40.0:
            verdict = "LIKELY_AUTHENTIC"
            verdict_label = "বিশ্বাসযোগ্য ও গ্রহণযোগ্য"
            badge_color = "#3b82f6"  # Blue
        elif final_fake_pct <= 55.0:
            verdict = "MODERATE_RISK"
            verdict_label = "মাঝারি সন্দেহ / স্পর্শকাতর"
            badge_color = "#f59e0b"  # Amber
        elif final_fake_pct <= 75.0:
            verdict = "HIGH_FAKE_PROBABILITY"
            verdict_label = "উচ্চ মাত্রার ফেক নিউজ ঝুঁকি"
            badge_color = "#ea580c"  # Orange
        else:
            verdict = "FABRICATED_HOAX"
            verdict_label = "বানোয়াট বা সম্পূর্ণ ভুয়া"
            badge_color = "#ef4444"  # Red

        # Compare against user configured threshold (e.g. 50%)
        is_publishable = final_fake_pct <= max_allowed_fake_pct

        if is_publishable:
            decision_code = "APPROVED_BY_TOLERANCE_GATE"
            decision_text = f"প্রকাশযোগ্য: ফেক সম্ভাব্যতা ({final_fake_pct}%) নির্ধারিত সহনশীলতার ({max_allowed_fake_pct}%) মধ্যে রয়েছে।"
        else:
            decision_code = "QUARANTINED_EXCEEDED_FAKE_THRESHOLD"
            decision_text = f"স্থগিত/বাতিল: ফেক সম্ভাব্যতা ({final_fake_pct}%) অনুমোদিত সহনশীলতার সীমা ({max_allowed_fake_pct}%) ছাড়িয়ে গেছে!"

        return {
            "fake_probability_pct": final_fake_pct,
            "factuality_score": factuality_score,
            "clickbait_score": round(clickbait_index, 1),
            "source_trust_score": round(source_trust, 1),
            "verdict": verdict,
            "verdict_label": verdict_label,
            "badge_color": badge_color,
            "is_publishable": is_publishable,
            "max_allowed_fake_pct": max_allowed_fake_pct,
            "decision_code": decision_code,
            "decision_text": decision_text,
            "flags": flags,
            "is_trusted_source": is_trusted,
        }
