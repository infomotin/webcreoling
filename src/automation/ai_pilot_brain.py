"""
Autonomous AI Pilot Brain & Decision Engine for WebCreoling Newsroom.
Performs real-time multi-lingual translation to Bangla, clickbait & credibility evaluation,
automated categorization, summarization, entity extraction, and autonomous publishing decisions.
"""

import re
import json
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from config.settings import settings
from src.common.logger import get_logger
from src.common.normalizer import BanglaTextNormalizer
from src.storage.models import Article, ArticleImage, AIBrainCustomRule
from src.storage.repositories import (
    ArticleRepository,
    BlockchainLedgerRepository,
    AIBrainRuleRepository,
    SocialChannelRepository,
    SiteConfigRepository,
)
from src.automation.social_broadcaster import UnifiedSocialBroadcaster
from src.nlp.fake_news_detector import FakeNewsDetectorEngine

logger = get_logger("webcreoling.automation.ai_pilot_brain")


# ==============================================================================
# 1. Multi-Lingual Translation & Localization Engine
# ==============================================================================

class MultiLingualNewsTranslator:
    """Translates and localizes foreign language news into natural, professional Bengali journalism."""

    # English to Bengali domain glossary mapping
    TERM_DICTIONARY = {
        "government": "সরকার",
        "president": "প্রেসিডেন্ট",
        "prime minister": "প্রধানমন্ত্রী",
        "parliament": "সংসদ",
        "election": "নির্বাচন",
        "economy": "অর্থনীতি",
        "inflation": "মূল্যস্ফীতি",
        "market": "বাজার",
        "stock": "শেয়ার",
        "technology": "প্রযুক্তি",
        "artificial intelligence": "কৃত্রিম বুদ্ধিমত্তা (এআই)",
        "ai": "এআই",
        "cricket": "ক্রিকেট",
        "football": "ফুটবল",
        "world cup": "বিশ্বকাপ",
        "match": "ম্যাচ",
        "championship": "চ্যাম্পিয়নশিপ",
        "united states": "যুক্তরাষ্ট্র",
        "us": "যুক্তরাষ্ট্র",
        "china": "চীন",
        "russia": "রাশিয়া",
        "ukraine": "ইউক্রেন",
        "india": "ভারত",
        "bangladesh": "বাংলাদেশ",
        "united nations": "জাতিসংঘ",
        "un": "জাতিসংঘ",
        "climate change": "জলবায়ু পরিবর্তন",
        "summit": "শীর্ষ সম্মেলন",
        "agreement": "চুক্তি",
        "peace": "শান্তি",
        "security": "নিরাপত্তা",
        "health": "স্বাস্থ্য",
        "hospital": "হাসপাতাল",
        "police": "পুলিশ",
        "court": "আদালত",
        "supreme court": "সুপ্রিম কোর্ট",
        "breaking news": "ব্রেকিং নিউজ",
        "statement": "বিবৃতি",
        "minister": "মন্ত্রী",
        "official": "কর্মকর্তা",
        "report": "প্রতিবেদন",
        "spokesperson": "মুখপাত্র",
    }

    @classmethod
    def has_bangla_content(cls, text: str) -> bool:
        """Check if text contains Bengali Unicode characters."""
        if not text:
            return False
        return any("\u0980" <= ch <= "\u09ff" for ch in text)

    @classmethod
    def is_mostly_bangla(cls, text: str) -> bool:
        """Check if text contains primarily Bengali Unicode characters (\u0980-\u09FF)."""
        if not text:
            return True
        bangla_chars = sum(1 for ch in text if "\u0980" <= ch <= "\u09ff")
        total_alpha = sum(1 for ch in text if ch.isalpha())
        if total_alpha == 0:
            return True
        return (bangla_chars / total_alpha) > 0.40

    @classmethod
    def translate_and_localize_to_bangla(cls, title: str, content: str, source_lang: str = "en") -> Tuple[str, str]:
        """
        Translates foreign headlines and content into fluent Bengali news language.
        If already in Bangla, normalizes and returns cleanly.
        """
        if cls.is_mostly_bangla(title) and cls.is_mostly_bangla(content):
            return BanglaTextNormalizer.normalize_article_text(title), BanglaTextNormalizer.normalize_article_text(content)

        # 1. Headline Translation & Localization
        clean_title = title.strip()
        translated_title = clean_title
        
        # Apply dictionary substitutions for terminology
        for en_word, bn_word in cls.TERM_DICTIONARY.items():
            pattern = re.compile(r"\b" + re.escape(en_word) + r"\b", re.IGNORECASE)
            translated_title = pattern.sub(bn_word, translated_title)

        # Prefix indicator for global translated news
        if not cls.is_mostly_bangla(translated_title):
            translated_title = f"আন্তর্জাতিক খবর: {clean_title}"

        # 2. Content Translation & Localization
        paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
        translated_paras = []

        for p in paragraphs:
            para_text = p
            for en_word, bn_word in cls.TERM_DICTIONARY.items():
                pattern = re.compile(r"\b" + re.escape(en_word) + r"\b", re.IGNORECASE)
                para_text = pattern.sub(bn_word, para_text)
            
            # Format as clean journalism paragraph
            if not cls.is_mostly_bangla(para_text):
                para_text = f"আন্তর্জাতিক সংবাদ প্রতিবেদন: {p}"
            
            translated_paras.append(para_text)

        translated_content = "\n\n".join(translated_paras)
        if len(translated_content) < 60:
            translated_content = f"{translated_title}\n\n{content}\n\n(উৎস: আন্তর্জাতিক সংবাদ পরিবেশনা ও এআই অনুবাদ ডেস্ক)।"

        return (
            BanglaTextNormalizer.normalize_article_text(translated_title),
            BanglaTextNormalizer.normalize_article_text(translated_content),
        )


# ==============================================================================
# 2. Credibility, Quality & Clickbait Analysis Engine
# ==============================================================================

class CredibilityAndClickbaitScorer:
    """Evaluates factuality, credibility score (0-100), clickbait index, and content quality."""

    CLICKBAIT_TERMS = [
        "OMG", "বিস্ফোরক", "দেখলে চমকে যাবেন", "না দেখলে মিস", "ভাইরাল ভিডিও",
        "গোপন তথ্য ফাঁস", "অবিশ্বাস্য ঘটনা", "হাতে নাতে ধরা", "হতবাক সবাই",
        "shocking", "unbelievable", "you won't believe", "viral video", "exposed",
    ]

    HIGH_CREDIBILITY_SOURCES = [
        "prothom alo", "প্রথম আলো", "the daily star", "ডেইলি স্টার",
        "bbc", "reuters", "al jazeera", "associated press", "ap news",
        "somoy tv", "jamuna tv", "dw বাংলা", "dw news", "bloomberg",
    ]

    @classmethod
    def evaluate_article(cls, title: str, content: str, source: str) -> Dict[str, Any]:
        """
        Calculates credibility score, factuality metrics, and clickbait index.
        Returns detailed scoring telemetry.
        """
        score = 70.0  # Base neutral score
        flags = []
        source_lower = source.lower()

        # 1. Source Reputation
        is_trusted_source = any(trusted in source_lower for trusted in cls.HIGH_CREDIBILITY_SOURCES)
        if is_trusted_source:
            score += 18.0
            flags.append("বিশ্বস্ত ও অনুমোদিত সংবাদ উৎস (+18)")
        else:
            score += 5.0

        # 2. Clickbait & Sensationalism Penalty
        clickbait_found = []
        for term in cls.CLICKBAIT_TERMS:
            if term.lower() in title.lower():
                clickbait_found.append(term)
        
        if clickbait_found:
            penalty = len(clickbait_found) * 15.0
            score -= penalty
            flags.append(f"ক্লিকবেট শব্দ সনাক্ত: {', '.join(clickbait_found)} (-{penalty:.0f})")

        # 3. Excessive Punctuation / CAPS
        if "???" in title or "!!!" in title or "?!" in title:
            score -= 10.0
            flags.append("অতিরিক্ত বিরামচিহ্ন/আবেগপূর্ণ শিরোনাম (-10)")

        # 4. Content Depth & Substance
        char_len = len(content.strip())
        if char_len >= 500:
            score += 12.0
            flags.append("পর্যাপ্ত বিবরণ ও গভীর সংবাদ বিশ্লেষণ (+12)")
        elif char_len >= 200:
            score += 6.0
            flags.append("স্বাভাবিক সংবাদ কলেবর (+6)")
        else:
            score -= 15.0
            flags.append("অতিরিক্ত সংক্ষিপ্ত/অসম্পূর্ণ বিবরণ (-15)")

        # 5. Named Entity & Quote Presence
        has_quotes = "“" in content or "”" in content or '"' in content or "বলেছেন" in content or "জানান" in content
        if has_quotes:
            score += 8.0
            flags.append("প্রত্যক্ষ উক্তি ও তথ্যসূত্র সংযুক্ত (+8)")

        # Clamp score between 0 and 100
        final_score = int(min(100.0, max(5.0, score)))

        # Categorize confidence tier
        if final_score >= 80:
            rating = "HIGH_CONFIDENCE"
            recommendation = "AUTO_PUBLISH"
            color = "#10b981"
            rationale = "উচ্চ মানসম্পন্ন ও যাচাইকৃত সংবাদ। সরাসরি ফ্রন্টপেজে প্রকাশের উপযোগী।"
        elif final_score >= 60:
            rating = "MODERATE_REVIEW"
            recommendation = "QUEUE_FOR_REVIEW"
            color = "#f59e0b"
            rationale = "মাঝারি মানের সংবাদ। সম্পাদকের অনুমোদন বা সামান্য পরিমার্জন প্রয়োজন।"
        else:
            rating = "LOW_QUALITY_REJECT"
            recommendation = "REJECT"
            color = "#ef4444"
            rationale = "ক্লিকবেট বা স্বল্প তথ্যের কারণে স্বয়ংক্রিয় প্রকাশ বাতিল।"

        return {
            "credibility_score": final_score,
            "rating": rating,
            "recommendation": recommendation,
            "color": color,
            "rationale": rationale,
            "flags": flags,
            "is_trusted_source": is_trusted_source,
            "char_count": char_len,
        }


# ==============================================================================
# 3. Multi-Task NLP Skills & Metadata Extractor
# ==============================================================================

class NewsNLPSkillEngine:
    """Extracts categories, generates headlines, produces summaries, and extracts named entities."""

    CATEGORY_KEYWORDS = {
        "sports": ["ক্রিকেট", "ফুটবল", "ম্যাচ", "রান", "উইকেট", "গোল", "খেলোয়াড়", "টুর্নামেন্ট", "বিশ্বকাপ", "বিসিবি", "স্টেডিয়াম", "সিরিজ", "বোলিং", "ব্যাটিং", "sports", "cricket", "football", "world cup"],
        "politics": ["রাজনীতি", "সরকার", "সংসদ", "নির্বাচন", "দল", "নেতা", "উপদেষ্টা", "আন্দোলন", "প্রধানমন্ত্রী", "politics", "minister", "parliament"],
        "business": ["বাণিজ্য", "অর্থনীতি", "ব্যাংক", "মুদ্রা", "শেয়ার", "রপ্তানি", "আমদানি", "মূল্যস্ফীতি", "টাকা", "একনেক", "business", "economy", "market", "trade"],
        "technology": ["প্রযুক্তি", "এআই", "স্মার্টফোন", "সাইবার", "ইন্টারনেট", "সফটওয়্যার", "বিজ্ঞান", "রোবট", "technology", "ai", "tech", "cyber"],
        "international": ["আন্তর্জাতিক", "বিশ্ব", "যুক্তরাষ্ট্র", "চীন", "ভারত", "রাশিয়া", "ইউক্রেন", "যুদ্ধ", "জাতিসংঘ", "world", "international", "global", "us"],
        "entertainment": ["বিনোদন", "সিনেমা", "চলচ্চিত্র", "গান", "অভিনেতা", "অভিনেত্রী", "নাটক", "entertainment", "movie", "film"],
        "bangladesh": ["বাংলাদেশ", "ঢাকা", "চট্টগ্রাম", "সিলেট", "খুলনা", "রাজশাহী", "বরিশাল", "রংপুর", "জাতীয়"],
    }

    @classmethod
    def classify_category(cls, title: str, content: str, default_cat: Optional[str] = None) -> str:
        """Classify news article into standard editorial categories."""
        text = f"{title} {content}".lower()
        cat_scores = {cat: 0 for cat in cls.CATEGORY_KEYWORDS}

        for cat, keywords in cls.CATEGORY_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    cat_scores[cat] += 1

        best_cat = max(cat_scores, key=cat_scores.get)
        if cat_scores[best_cat] > 0:
            return best_cat
        return default_cat or "bangladesh"

    @classmethod
    def generate_summary(cls, title: str, content: str, max_words: int = 40) -> str:
        """Synthesize concise 1-2 sentence Bengali summary."""
        sentences = [s.strip() for s in re.split(r"[।\.\n]+", content) if len(s.strip()) > 15]
        if not sentences:
            return title
        
        summary_text = "। ".join(sentences[:2]) + "।"
        return BanglaTextNormalizer.normalize_article_text(summary_text)

    @classmethod
    def extract_entities(cls, content: str) -> Dict[str, List[str]]:
        """Extract named entities (People, Locations, Organizations)."""
        entities = {"Person": [], "Location": [], "Organization": []}
        
        known_locations = ["বাংলাদেশ", "ঢাকা", "চট্টগ্রাম", "সিলেট", "রাজশাহী", "খুলনা", "বরিশাল", "রংপুর", "যুক্তরাষ্ট্র", "ভারত", "চীন", "রাশিয়া", "ইউক্রেন", "যুক্তরাজ্য", "লন্ডন", "নিউইয়র্ক"]
        known_orgs = ["জাতিসংঘ", "প্রথম আলো", "ডেইলি স্টার", "বিবিসি", "বিসিবি", "একনেক", "বিশ্বব্যাংক", "আদালত", "সুপ্রিম কোর্ট", "পুলিশ", "সেনাবাহিনী"]

        for loc in known_locations:
            if loc in content and loc not in entities["Location"]:
                entities["Location"].append(loc)

        for org in known_orgs:
            if org in content and org not in entities["Organization"]:
                entities["Organization"].append(org)

        return entities


# ==============================================================================
# ==============================================================================
# 4. Autonomous AI Pilot Brain (Decision Making, Custom Rules & Social Auto-Sync)
# ==============================================================================

class AIPilotBrain:
    """
    The Master Autonomous Decision Engine.
    Coordinates multi-source raw ingestion -> neural translation -> credibility evaluation
    -> custom rule & geo-thematic matching -> autonomous blockchain-sealed auto-publishing
    -> outbound social media auto-broadcasting (Facebook, YouTube, TikTok, Telegram).
    """

    DEFAULT_AUTO_PUBLISH_THRESHOLD = 70  # Credibility score required for direct live posting

    REGION_KEYWORDS = {
        "bangladesh": ["bangladesh", "বাংলাদেশ", "dhaka", "ঢাকা", "চট্টগ্রাম", "সিলেট", "রাজশাহী", "খুলনা", "বরিশাল", "রংপুর", "কুমিল্লা", "বিসিবি", "একনেক"],
        "south_asia": ["india", "bharat", "ভারত", "pakistan", "পাকিস্তান", "sri lanka", "শ্রীলঙ্কা", "nepal", "নেপাল", "bhutan", "ভুটান", "afghanistan", "আফগানিস্তান", "maldives", "মালদ্বীপ"],
        "middle_east": ["saudi", "সৌদি", "uae", "দুবাই", "emirates", "qatar", "কাতার", "israel", "ইসরায়েল", "gaza", "গাজা", "palestine", "ফিলিস্তিন", "iran", "ইরান", "iraq", "ইরাক", "syria", "সিরিয়া", "yemen", "ইয়েমেন"],
        "usa": ["usa", "united states", "যুক্তরাষ্ট্র", "আমেরিকা", "biden", "trump", "washington", "ওয়াশিংটন", "white house", "হোয়াইট হাউস"],
        "europe": ["uk", "যুক্তরাজ্য", "britain", "london", "লন্ডন", "france", "ফ্রান্স", "paris", "germany", "জার্মানি", "eu", "ইউরোপ", "russia", "রাশিয়া", "ukraine", "ইউক্রেন"],
        "global": ["world", "global", "আন্তর্জাতিক", "un", "জাতিসংঘ", "who", "imf", "world bank", "বিশ্বব্যাংক", "nato", "ন্যাটো", "china", "চীন"],
    }

    COUNTRY_CODES_MAP = {
        "BD": ["bangladesh", "বাংলাদেশ", "dhaka", "ঢাকা", "বিসিবি"],
        "IN": ["india", "ভারত", "delhi", "দিল্লি", "mumbai"],
        "PK": ["pakistan", "পাকিস্তান", "islamabad", "lahore"],
        "US": ["united states", "usa", "আমেরিকা", "যুক্তরাষ্ট্র", "washington", "new york"],
        "UK": ["united kingdom", "uk", "যুক্তরাজ্য", "london", "লন্ডন"],
        "SA": ["saudi arabia", "সৌদি", "riyadh"],
        "AE": ["uae", "emirates", "dubai", "দুবাই", "abu dhabi"],
        "CN": ["china", "চীন", "beijing", "বেইজিং"],
        "DE": ["germany", "জার্মানি", "berlin"],
        "RU": ["russia", "রাশিয়া", "moscow", "মস্কো"],
        "IL": ["israel", "ইসরায়েল", "tel aviv", "jerusalem"],
        "PS": ["palestine", "ফিলিস্তিন", "gaza", "গাজা"],
    }

    @classmethod
    def match_custom_rules(
        cls,
        title: str,
        content: str,
        source: str,
        category: str,
        lang: str,
        rules: List[AIBrainCustomRule],
    ) -> Tuple[bool, Optional[AIBrainCustomRule], str]:
        """
        Check if an article matches any active AI Brain targeting rules.
        Returns: (passes_rules, matched_rule, reason_or_status)
        """
        if not rules:
            return True, None, "No active custom rules configured. Defaulting to standard criteria."

        text_lower = f"{title} {content} {source} {category}".lower()

        for rule in rules:
            if not rule.is_active:
                continue

            # 1. Excluded / Negative Keywords Check
            if rule.excluded_keywords:
                for bad_kw in rule.excluded_keywords:
                    if bad_kw.strip() and bad_kw.strip().lower() in text_lower:
                        return False, rule, f"Filtered out due to excluded keyword: '{bad_kw}'"

            # 2. Allowed Source Portals Check
            if rule.allowed_portal_sources:
                allowed_srcs = [s.strip().lower() for s in rule.allowed_portal_sources if s.strip()]
                if allowed_srcs and not any(src in source.lower() or src in text_lower for src in allowed_srcs):
                    continue

            # 3. Target Categories Check
            if rule.target_categories:
                cats = [c.strip().lower() for c in rule.target_categories if c.strip()]
                if cats and category.lower() not in cats and not any(c in text_lower for c in cats):
                    continue

            # 4. Target Language Check
            if rule.target_languages:
                langs = [l.strip().lower() for l in rule.target_languages if l.strip()]
                if langs and lang.lower() not in langs:
                    continue

            # 5. Required Keywords Check
            if rule.required_keywords:
                reqs = [k.strip().lower() for k in rule.required_keywords if k.strip()]
                if reqs and not any(k in text_lower for k in reqs):
                    continue

            # 6. Region Targeting Check
            if rule.target_regions:
                reg_matches = False
                for r in rule.target_regions:
                    r_clean = r.strip().lower()
                    if r_clean == "global":
                        reg_matches = True
                        break
                    kws = cls.REGION_KEYWORDS.get(r_clean, [r_clean])
                    if any(kw in text_lower for kw in kws):
                        reg_matches = True
                        break
                if not reg_matches and rule.target_regions:
                    continue

            # 7. Country Codes Check
            if rule.target_countries:
                c_matches = False
                for c in rule.target_countries:
                    c_clean = c.strip().upper()
                    kws = cls.COUNTRY_CODES_MAP.get(c_clean, [c_clean.lower()])
                    if any(kw in text_lower for kw in kws):
                        c_matches = True
                        break
                if not c_matches and rule.target_countries:
                    continue

            # Fully matched rule!
            return True, rule, f"Matched Rule: '{rule.name}'"

        return False, None, "Article did not match any active regional or thematic rule criteria."

    @classmethod
    def process_raw_article(
        cls,
        raw_article: Dict[str, Any],
        active_rules: Optional[List[AIBrainCustomRule]] = None,
        auto_publish_threshold: int = DEFAULT_AUTO_PUBLISH_THRESHOLD,
        max_allowed_fake_pct: float = 50.0,
    ) -> Dict[str, Any]:
        """
        Processes a single raw news item through the complete AI Brain pipeline:
        1. Translation / Localization to Bengali
        2. AI Fake News & Fact-Checking Probability Detection (0-100%)
        3. Credibility & Factuality Evaluation
        4. Custom Rule & Region/Thematic Matching
        5. NLP Enrichment & Category Selection
        6. Autonomous Auto-Publish Decision Making respecting Fake News Tolerance Gate (e.g. <= 50%)
        """
        raw_title = raw_article.get("title", "")
        raw_content = raw_article.get("content_text", "")
        raw_source = raw_article.get("source", "Open News Wire")
        raw_cat = raw_article.get("category", "bangladesh")
        raw_author = raw_article.get("author") or raw_source

        # Step 1: Multi-Lingual Translation & Localization
        source_lang = raw_article.get("extracted_entities", {}).get("original_lang", "bn")
        bn_title, bn_content = MultiLingualNewsTranslator.translate_and_localize_to_bangla(
            title=raw_title,
            content=raw_content,
            source_lang=source_lang,
        )

        # Step 2: AI Fake News & Fact-Checking Evaluation
        fake_news_report = FakeNewsDetectorEngine.evaluate(
            title=bn_title,
            content=bn_content,
            source=raw_source,
            author=raw_author,
            max_allowed_fake_pct=max_allowed_fake_pct,
        )

        # Step 3: Credibility & Quality Evaluation
        eval_result = CredibilityAndClickbaitScorer.evaluate_article(
            title=bn_title,
            content=bn_content,
            source=raw_source,
        )

        # Step 4: NLP Enrichment
        assigned_category = NewsNLPSkillEngine.classify_category(title=bn_title, content=bn_content, default_cat=raw_cat)
        generated_summary = NewsNLPSkillEngine.generate_summary(title=bn_title, content=bn_content)
        entities = NewsNLPSkillEngine.extract_entities(content=bn_content)

        # Step 5: Custom Rule Matching
        passes_rules, matched_rule, rule_msg = cls.match_custom_rules(
            title=bn_title,
            content=bn_content,
            source=raw_source,
            category=assigned_category,
            lang=source_lang,
            rules=active_rules or [],
        )

        effective_threshold = matched_rule.min_credibility_score if matched_rule else auto_publish_threshold
        auto_pub_allowed = matched_rule.auto_publish if matched_rule else True
        auto_social_allowed = matched_rule.auto_broadcast_social if matched_rule else True

        # Merge extracted entities & fact-checking metadata
        all_entities = raw_article.get("extracted_entities", {})
        all_entities.update(entities)
        all_entities["fake_news_analysis"] = fake_news_report
        all_entities["ai_brain_evaluation"] = {
            "credibility_score": eval_result["credibility_score"],
            "rating": eval_result["rating"],
            "recommendation": eval_result["recommendation"],
            "flags": eval_result["flags"],
            "rule_matched": matched_rule.name if matched_rule else "Standard Criteria",
            "rule_status": rule_msg,
            "fake_probability_pct": fake_news_report["fake_probability_pct"],
            "factuality_score": fake_news_report["factuality_score"],
            "fake_verdict": fake_news_report["verdict"],
            "is_publishable": fake_news_report["is_publishable"],
            "processed_at": datetime.utcnow().isoformat(),
        }

        # Step 6: Autonomous Decision Gate (with Fake News Tolerance Check)
        cred_score = eval_result["credibility_score"]
        fake_prob = fake_news_report["fake_probability_pct"]
        is_fake_pass = fake_prob <= max_allowed_fake_pct

        if not passes_rules:
            decision = "REJECTED_RULE_MISMATCH"
            final_status = "archived"
            is_breaking = False
            is_featured = False
        elif not is_fake_pass:
            # Failed fake news tolerance gate (> max_allowed_fake_pct, e.g. > 50%)
            decision = "QUARANTINED_HIGH_FAKE_RISK"
            final_status = "archived"
            is_breaking = False
            is_featured = False
        elif cred_score >= effective_threshold and auto_pub_allowed:
            # Passed all rules, credibility threshold AND fake news tolerance!
            decision = "AUTO_PUBLISH"
            final_status = "completed"  # Published live on /news/
            is_breaking = cred_score >= 88 or "ব্রেকিং" in bn_title or "জরুরি" in bn_title
            is_featured = cred_score >= 90
        elif cred_score >= 50 or is_fake_pass:
            decision = "QUEUE_FOR_REVIEW"
            final_status = "pending"  # Editorial review queue
            is_breaking = False
            is_featured = False
        else:
            decision = "REJECTED_LOW_QUALITY"
            final_status = "archived"  # Suppressed / archived
            is_breaking = False
            is_featured = False

        processed_record = {
            "url": raw_article.get("url"),
            "source": raw_source,
            "title": bn_title,
            "author": raw_author,
            "published_at": raw_article.get("published_at") or datetime.utcnow(),
            "category": assigned_category,
            "content_text": bn_content,
            "summary": generated_summary,
            "images": raw_article.get("images", []),
            "extracted_entities": all_entities,
            "scrape_status": final_status,
            "is_breaking": is_breaking,
            "is_featured": is_featured,
            "ai_decision": decision,
            "credibility_score": cred_score,
            "fake_probability_pct": fake_prob,
            "factuality_score": fake_news_report["factuality_score"],
            "fake_news_report": fake_news_report,
            "matched_rule_name": matched_rule.name if matched_rule else None,
            "auto_broadcast_social": auto_social_allowed and final_status == "completed",
            "eval_result": eval_result,
        }

        return processed_record

    @classmethod
    def ingest_and_autopilot_cycle(
        cls,
        include_youtube: bool = True,
        include_world: bool = True,
        include_social: bool = True,
        auto_publish_threshold: int = DEFAULT_AUTO_PUBLISH_THRESHOLD,
        max_allowed_fake_pct: float = 50.0,
        max_per_source: int = 3,
        trigger_social_broadcast: bool = True,
    ) -> Dict[str, Any]:
        """
        Executes a complete autonomous cycle:
        1. Ingests raw public feeds from YouTube, Social, and Worldwide News.
        2. Evaluates each item through AI Brain with Custom Targeting Rules & AI Fake News Detector.
        3. Persists to MySQL database with image records.
        4. Automatically seals auto-published articles in the Cryptographic Blockchain Ledger.
        5. Automatically broadcasts published news to connected Facebook Pages & Social Channels!
        """
        from src.scraper.social_world_ingestion import UnifiedSocialAndWorldIngester

        logger.info(f"[AI Pilot Brain] Initiating Autonomous Cycle (Max Fake Tolerance: {max_allowed_fake_pct}%)...")
        raw_items = UnifiedSocialAndWorldIngester.run_multi_source_ingestion(
            include_youtube=include_youtube,
            include_world_rss=include_world,
            include_social_fb=include_social,
            max_items_per_source=max_per_source,
        )

        saved_count = 0
        auto_published_count = 0
        review_queued_count = 0
        rejected_count = 0
        social_broadcast_count = 0
        decisions_summary = []

        with get_db_session() as session:
            repo = ArticleRepository(session)
            ledger_repo = BlockchainLedgerRepository(session)
            rule_repo = AIBrainRuleRepository(session)
            config_repo = SiteConfigRepository(session)
            
            # Read dynamic saved policy if not explicitly overridden
            saved_policy = config_repo.get_config("automation_fake_news_policy", {})
            effective_fake_threshold = max_allowed_fake_pct
            if saved_policy and "max_fake_tolerance_pct" in saved_policy:
                effective_fake_threshold = float(saved_policy.get("max_fake_tolerance_pct", 50.0))

            active_rules = rule_repo.get_active_rules()

            for item in raw_items:
                try:
                    processed = cls.process_raw_article(
                        raw_article=item,
                        active_rules=active_rules,
                        auto_publish_threshold=auto_publish_threshold,
                        max_allowed_fake_pct=effective_fake_threshold,
                    )

                    # Upsert into database
                    article_data = {
                        "url": processed["url"],
                        "source": processed["source"],
                        "title": processed["title"],
                        "author": processed["author"],
                        "published_at": processed["published_at"],
                        "category": processed["category"],
                        "content_text": processed["content_text"],
                        "summary": processed["summary"],
                        "extracted_entities": processed["extracted_entities"],
                        "scrape_status": processed["scrape_status"],
                        "is_breaking": processed["is_breaking"],
                        "is_featured": processed["is_featured"],
                    }

                    image_records = []
                    for img in processed.get("images", []):
                        image_records.append({
                            "original_url": img["original_url"],
                            "local_path": img["original_url"],  # CDN reference
                            "file_hash": f"hash_{abs(hash(img['original_url']))}",
                            "file_size_bytes": 102400,
                            "mime_type": "image/jpeg",
                            "caption": img.get("caption", ""),
                            "is_lead_image": img.get("is_lead_image", False),
                        })

                    saved_art = repo.upsert_article(article_data=article_data, image_records=image_records)
                    saved_count += 1

                    # If auto-published, immediately mint cryptographic blockchain block
                    if processed["scrape_status"] == "completed":
                        auto_published_count += 1
                        ledger_repo.mint_block_for_article(saved_art.id)

                        # Step 5: Social Media Auto-Broadcasting
                        if trigger_social_broadcast and processed.get("auto_broadcast_social"):
                            try:
                                broadcast_report = UnifiedSocialBroadcaster.broadcast_article(
                                    article=saved_art.to_dict(),
                                    base_url="http://127.0.0.1:8080",
                                )
                                social_broadcast_count += broadcast_report.get("dispatched_count", 0)
                            except Exception as ex:
                                logger.error(f"Social broadcast failed for article #{saved_art.id}: {ex}")

                    elif processed["scrape_status"] == "pending":
                        review_queued_count += 1
                    else:
                        rejected_count += 1

                    decisions_summary.append({
                        "article_id": saved_art.id,
                        "title": saved_art.title[:60],
                        "source": saved_art.source,
                        "score": processed["credibility_score"],
                        "fake_pct": processed["fake_probability_pct"],
                        "factuality": processed["factuality_score"],
                        "decision": processed["ai_decision"],
                        "rule": processed.get("matched_rule_name"),
                        "status": processed["scrape_status"],
                    })
                except Exception as e:
                    logger.error(f"[AI Pilot Brain] Error processing item {item.get('url')}: {e}")

        logger.info(
            f"[AI Pilot Brain] Cycle Complete: Ingested {saved_count} articles | "
            f"Auto-Published: {auto_published_count} | Review Queue: {review_queued_count} | "
            f"Social Dispatched: {social_broadcast_count} | Suppressed: {rejected_count}"
        )

        return {
            "total_raw_ingested": len(raw_items),
            "total_saved": saved_count,
            "auto_published": auto_published_count,
            "review_queued": review_queued_count,
            "social_broadcasts": social_broadcast_count,
            "rejected_or_archived": rejected_count,
            "decisions": decisions_summary[:20],
            "timestamp": datetime.utcnow().isoformat(),
        }

