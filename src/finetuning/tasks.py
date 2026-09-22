"""
Specialized News Task Definitions & Prompt Formatters.
Supports 4 core skills: Categorization, Headline Generation, Summarization, and Named Entity Recognition (NER).
"""

import json
import re
from typing import Dict, Any, List, Optional
from datasets import Dataset, DatasetDict
from src.common.logger import get_logger
from src.common.normalizer import BanglaTextNormalizer
from src.storage.models import Article

logger = get_logger("webcreoling.finetuning.tasks")


class TaskPrefixes:
    """Standardized multi-task instruction prefixes."""
    CATEGORIZE = "[টাস্ক: বিভাগ নির্ধারণ]"
    HEADLINE = "[টাস্ক: শিরোনাম তৈরি]"
    SUMMARIZE = "[টাস্ক: সারসংক্ষেপ তৈরি]"
    NER = "[টাস্ক: সত্তা নিষ্কাশন]"


class SpecializedTaskManager:
    """Manages prompt generation, task sample creation, and output parsing for the 4 core skills."""

    @classmethod
    def format_categorize_sample(cls, content: str, category: str) -> str:
        """Format input/output prompt for Article Categorization."""
        truncated_content = content[:600].strip()
        return f"{TaskPrefixes.CATEGORIZE}\nখবর: {truncated_content}\n-> বিভাগ: {category.strip()}\n<|endoftext|>"

    @classmethod
    def format_headline_sample(cls, content: str, title: str) -> str:
        """Format input/output prompt for Headline Generation."""
        truncated_content = content[:700].strip()
        return f"{TaskPrefixes.HEADLINE}\nখবর: {truncated_content}\n-> শিরোনাম: {title.strip()}\n<|endoftext|>"

    @classmethod
    def format_summarize_sample(cls, content: str, summary: Optional[str] = None) -> str:
        """Format input/output prompt for Content Summarization."""
        truncated_content = content[:800].strip()
        if not summary:
            # Create extractive summary from first 2 sentences if none provided
            sentences = BanglaTextNormalizer.extract_sentences(content)
            summary = "। ".join(sentences[:2]) + "।" if sentences else content[:150]
        return f"{TaskPrefixes.SUMMARIZE}\nখবর: {truncated_content}\n-> সারসংক্ষেপ: {summary.strip()}\n<|endoftext|>"

    @classmethod
    def format_ner_sample(cls, content: str, entities: Optional[Dict[str, List[str]]] = None) -> str:
        """Format input/output prompt for Named Entity Recognition."""
        truncated_content = content[:600].strip()
        if not entities:
            entities = cls.heuristic_extract_entities(content)
        entities_json = json.dumps(entities, ensure_ascii=False)
        return f"{TaskPrefixes.NER}\nখবর: {truncated_content}\n-> সত্তা: {entities_json}\n<|endoftext|>"

    @classmethod
    def heuristic_extract_entities(cls, text: str) -> Dict[str, List[str]]:
        """
        Rule-based entity extractor fallback for Bengali text
        (Identifies key organizations, locations, and persons based on patterns).
        """
        org_keywords = [
            "সংসদ", "নির্বাচন কমিশন", "ক্রিকেট বোর্ড", "বিসিবি", "সরকার", "আদালত",
            "হাইকোর্ট", "সুপ্রিম কোর্ট", "বিশ্ববিদ্যালয়", "ব্যাংক", "জাতিসংঘ", "ডিএসই",
        ]
        loc_keywords = [
            "ঢাকা", "চট্টগ্রাম", "সিলেট", "রাজশাহী", "খুলনা", "বরিশাল", "রংপুর",
            "ময়মনসিংহ", "বাংলাদেশ", "যুক্তরাষ্ট্র", "ভারত", "যুক্তরাজ্য", "মিরপুর",
        ]
        person_keywords = [
            "প্রধানমন্ত্রী", "রাষ্ট্রপতি", "স্পিকার", "অধিনায়ক", "বিচারপতি", "মন্ত্রী",
            "মহাসচিব", "পরিচালক", "চেয়ারম্যান",
        ]

        entities = {"Person": [], "Location": [], "Organization": []}

        for kw in person_keywords:
            if kw in text and kw not in entities["Person"]:
                entities["Person"].append(kw)

        for kw in loc_keywords:
            if kw in text and kw not in entities["Location"]:
                entities["Location"].append(kw)

        for kw in org_keywords:
            if kw in text and kw not in entities["Organization"]:
                entities["Organization"].append(kw)

        return entities

    @classmethod
    def build_multi_task_dataset(cls, articles: List[Article]) -> DatasetDict:
        """
        Construct a balanced multi-task training dataset containing all 4 specialized skills.
        """
        samples = []

        for art in articles:
            content = BanglaTextNormalizer.normalize_article_text(art.content_text or "")
            title = BanglaTextNormalizer.normalize_article_text(art.title or "")
            category = art.category or "general"
            summary = BanglaTextNormalizer.normalize_article_text(art.summary or "")
            entities = art.extracted_entities or None

            if len(content) < 60 or not title:
                continue

            # 1. Categorization Sample
            samples.append({
                "task": "categorize",
                "text": cls.format_categorize_sample(content, category),
                "target": category,
            })

            # 2. Headline Generation Sample
            samples.append({
                "task": "headline",
                "text": cls.format_headline_sample(content, title),
                "target": title,
            })

            # 3. Summarization Sample
            samples.append({
                "task": "summarize",
                "text": cls.format_summarize_sample(content, summary),
                "target": summary,
            })

            # 4. Named Entity Recognition Sample
            samples.append({
                "task": "ner",
                "text": cls.format_ner_sample(content, entities),
                "target": json.dumps(entities or cls.heuristic_extract_entities(content), ensure_ascii=False),
            })

        logger.info(f"Built multi-task hybrid dataset with {len(samples)} total samples across 4 tasks.")
        dataset = Dataset.from_list(samples)
        split = dataset.train_test_split(test_size=0.15, seed=42)
        return DatasetDict({"train": split["train"], "validation": split["test"]})
