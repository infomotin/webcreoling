"""
Integration Tests — End-to-End Pipeline: Mock Scrape → SQLite → FTS5 → RAG Prompt.
Tests the complete data flow without GPU or network dependencies.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from src.scraper.parsers.bangla_portal import BanglaPortalParser
from src.scraper.mock_bangla_portal import MOCK_ARTICLES
from src.storage.repositories import ArticleRepository
from src.chat.rag_engine import RAGEngine
from src.chat.task_handlers import IntentClassifier
from src.finetuning.tasks import SpecializedTaskManager
from src.common.normalizer import BanglaTextNormalizer


# ---------------------------------------------------------------------------
# 1. Parser → Structured Data
# ---------------------------------------------------------------------------

class TestParserToStructuredData:
    """Test that BanglaPortalParser outputs clean structured dicts."""

    def test_full_article_parsing(self):
        """Parse a complete HTML article and validate all fields."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title" content="ঢাকায় বিজয় উৎসব অনুষ্ঠিত">
            <meta property="og:image" content="https://example.bd/images/victory.jpg">
            <meta property="article:published_time" content="2026-09-22T10:00:00Z">
            <meta name="author" content="সিনিয়র প্রতিবেদক">
            <script type="application/ld+json">
            {"@type": "NewsArticle", "headline": "ঢাকায় বিজয় উৎসব অনুষ্ঠিত",
             "datePublished": "2026-09-22T10:00:00Z",
             "author": {"name": "সিনিয়র প্রতিবেদক"}}
            </script>
        </head>
        <body>
            <article>
                <h1>ঢাকায় বিজয় উৎসব অনুষ্ঠিত</h1>
                <p>রাজধানী ঢাকায় আজ বিজয় দিবস উপলক্ষে এক বিশাল উৎসব অনুষ্ঠিত হয়েছে।</p>
                <p>হাজার হাজার মানুষ সরকারি বিভিন্ন কার্যক্রমে অংশ নিয়েছেন।</p>
                <p>প্রধানমন্ত্রী অনুষ্ঠানে প্রধান অতিথি হিসেবে উপস্থিত ছিলেন।</p>
            </article>
        </body>
        </html>
        """
        parser = BanglaPortalParser()
        result = parser.parse_article(html, url="https://example.bd/news/victory-celebration", category="national")

        assert "ঢাকায় বিজয় উৎসব" in result["title"]
        assert result["author"] == "সিনিয়র প্রতিবেদক"
        assert result["published_at"] is not None
        assert "ঢাকায় আজ বিজয় দিবস" in result["content_text"]
        assert result["lead_image_url"] == "https://example.bd/images/victory.jpg"
        assert result["category"] == "national"
        assert result["missing_fields"] == []

    def test_class_selector_extraction(self):
        """Verify that div.story-content CSS selector works via soup.select()."""
        html = """
        <html><body>
            <div class="story-content">
                <p>এটি কাস্টম সিলেক্টর দিয়ে বের করা সংবাদের অনুচ্ছেদ।</p>
                <p>আরও গুরুত্বপূর্ণ তথ্য এখানে আছে বিস্তারিতভাবে।</p>
            </div>
        </body></html>
        """
        parser = BanglaPortalParser()
        result = parser.parse_article(html, url="https://example.bd/news/test")
        # Should extract content from div.story-content via soup.select()
        assert "কাস্টম সিলেক্টর" in result["content_text"]

    def test_article_link_extraction(self):
        """Verify article URL extraction filters out navigation links."""
        html = """
        <html><body>
            <a href="/news/article-123">গুরুত্বপূর্ণ সংবাদ</a>
            <a href="/tag/politics">পলিটিক্স ট্যাগ</a>
            <a href="/author/journalist">সাংবাদিক প্রোফাইল</a>
            <a href="/news/article-456">আরেকটি সংবাদ</a>
            <a href="https://external.com/news/x">বাহ্যিক সংবাদ</a>
        </body></html>
        """
        parser = BanglaPortalParser()
        links = parser.extract_article_links(html, base_url="https://example.bd")
        # Should have article-123 and article-456 but NOT tag or author pages
        assert any("article-123" in url for url in links)
        assert any("article-456" in url for url in links)
        assert not any("/tag/" in url for url in links)
        assert not any("/author/" in url for url in links)


# ---------------------------------------------------------------------------
# 2. Storage Layer Integration
# ---------------------------------------------------------------------------

class TestStorageIntegration:
    """Test article upsert, retrieval, deduplication, and FTS5 search."""

    def test_upsert_creates_article_with_images(self, article_repo, db_session, sample_article_data, sample_image_records):
        """Full upsert creates article with correct fields and images."""
        article = article_repo.upsert_article(sample_article_data, image_records=sample_image_records)
        db_session.commit()

        assert article.id is not None
        assert article.title == sample_article_data["title"]
        assert article.category == "politics"
        assert len(article.images) == 1
        assert article.images[0].is_lead_image is True
        assert article.images[0].file_hash == "abc123def456abc123def456"

    def test_upsert_deduplication(self, article_repo, db_session, sample_article_data):
        """Re-upserting the same URL should update, not create a duplicate."""
        article_repo.upsert_article(sample_article_data)
        db_session.commit()
        count_before = article_repo.count_articles()

        # Upsert again with updated title
        updated = {**sample_article_data, "title": "আপডেট করা শিরোনাম"}
        article = article_repo.upsert_article(updated)
        db_session.commit()
        count_after = article_repo.count_articles()

        assert count_before == count_after  # No duplicate
        assert article.title == "আপডেট করা শিরোনাম"

    def test_count_articles_by_source(self, populated_db):
        """Count articles filtered by source."""
        session = populated_db
        repo = ArticleRepository(session)
        count = repo.count_articles(source="test_portal")
        assert count == 5

    def test_training_dataset_retrieval(self, populated_db):
        """get_training_dataset should return all valid articles."""
        session = populated_db
        repo = ArticleRepository(session)
        articles = repo.get_training_dataset(min_char_length=30)
        assert len(articles) == 5
        # Verify attributes are accessible (no DetachedInstanceError)
        for art in articles:
            _ = art.title
            _ = art.content_text
            _ = art.category
            _ = art.extracted_entities  # Was causing DetachedInstanceError before fix


# ---------------------------------------------------------------------------
# 3. Multi-Task Dataset Builder
# ---------------------------------------------------------------------------

class TestMultiTaskDatasetBuilder:
    """Test dataset construction for all 4 NLP tasks."""

    def _make_article(self, idx: int):
        from src.storage.models import Article
        return Article(
            id=idx,
            url=f"http://test.bd/news/{idx}",
            source="test",
            title=f"পরীক্ষামূলক শিরোনাম {idx}",
            category="politics",
            content_text=f"এটি সংবাদ নম্বর {idx}। ঢাকায় আজ গুরুত্বপূর্ণ ঘটনা ঘটেছে। বিস্তারিত তথ্য প্রকাশিত হয়েছে।",
            summary=f"সংবাদ {idx} এর সারসংক্ষেপ।",
            extracted_entities={"Person": ["প্রধানমন্ত্রী"], "Location": ["ঢাকা"], "Organization": ["সংসদ"]},
        )

    def test_all_tasks_represented(self):
        """DatasetDict should contain samples for all 4 tasks."""
        articles = [self._make_article(i) for i in range(1, 10)]
        ds = SpecializedTaskManager.build_multi_task_dataset(articles)
        assert "train" in ds and "validation" in ds
        tasks_in_train = set(ds["train"]["task"])
        for task in ["categorize", "headline", "summarize", "ner"]:
            assert task in tasks_in_train, f"Task '{task}' missing from training dataset"

    def test_selected_tasks_only(self):
        """When selected_tasks is specified, only those tasks appear."""
        articles = [self._make_article(i) for i in range(1, 10)]
        ds = SpecializedTaskManager.build_multi_task_dataset(articles, selected_tasks=["categorize", "ner"])
        tasks = set(ds["train"]["task"]) | set(ds["validation"]["task"])
        assert "headline" not in tasks
        assert "summarize" not in tasks
        assert "categorize" in tasks

    def test_empty_articles_produces_dummy_sample(self):
        """Empty article list should produce a dummy sample to prevent crash."""
        ds = SpecializedTaskManager.build_multi_task_dataset([])
        total = len(ds["train"]) + len(ds["validation"])
        assert total >= 1

    def test_ner_heuristic_entity_extraction(self):
        """Heuristic extractor correctly identifies Bangla entities."""
        text = "ঢাকায় প্রধানমন্ত্রী ও স্পিকার জাতীয় সংসদে বক্তব্য দিয়েছেন।"
        entities = SpecializedTaskManager.heuristic_extract_entities(text)
        assert "ঢাকা" in entities["Location"]
        assert "প্রধানমন্ত্রী" in entities["Person"]
        assert "সংসদ" in entities["Organization"]


# ---------------------------------------------------------------------------
# 4. RAG Engine — Prompt Construction & Intent Classification
# ---------------------------------------------------------------------------

class TestRAGAndChat:
    """Test the RAG prompt builder and intent classification pipeline."""

    def test_rag_prompt_has_all_sections(self):
        """Built RAG prompt contains source context, question, and answer prefix."""
        rag = RAGEngine()
        retrieved = [
            {
                "id": 1,
                "title": "বাজেট পেশ করা হয়েছে",
                "source": "prothom_alo",
                "published_at": "2026-09-22",
                "content_text": "জাতীয় বাজেটে শিক্ষা ও স্বাস্থ্য খাতে বরাদ্দ বৃদ্ধি পেয়েছে।",
            }
        ]
        prompt = rag.build_rag_prompt("বাজেটে শিক্ষায় কত বরাদ্দ?", retrieved)
        assert "তথ্যসূত্র:" in prompt
        assert "বাজেট পেশ করা হয়েছে" in prompt
        assert "প্রশ্ন:" in prompt
        assert "-> উত্তর:" in prompt

    def test_rag_prompt_empty_context(self):
        """Empty retrieved articles produces Bangla no-data message."""
        rag = RAGEngine()
        prompt = rag.build_rag_prompt("অজানা প্রশ্ন", [])
        assert "পাওয়া যায়নি" in prompt

    def test_intent_categorize(self):
        intent, payload = IntentClassifier.parse_intent(
            "categorize this: বাংলাদেশ ক্রিকেট দলের ঐতিহাসিক জয়"
        )
        assert intent == "categorize"
        assert "ক্রিকেট" in payload

    def test_intent_headline(self):
        intent, payload = IntentClassifier.parse_intent(
            "generate a headline for this: অর্থনীতিতে নতুন উন্নয়ন প্রকল্প শুরু হয়েছে"
        )
        assert intent == "headline"

    def test_intent_summarize(self):
        intent, payload = IntentClassifier.parse_intent(
            "summarize this: বাংলাদেশ ও ভারতের মধ্যে নতুন বাণিজ্য চুক্তি স্বাক্ষরিত হয়েছে"
        )
        assert intent == "summarize"

    def test_intent_ner(self):
        intent, payload = IntentClassifier.parse_intent(
            "extract entities from this: ঢাকায় প্রধানমন্ত্রী বক্তব্য দিয়েছেন"
        )
        assert intent == "ner"

    def test_intent_bangla_qa_is_rag(self):
        """Pure Bangla questions without explicit command should route to RAG."""
        intent, payload = IntentClassifier.parse_intent(
            "আজকে সংসদে কী আলোচনা হয়েছিল?"
        )
        assert intent == "rag_qa"

    def test_task_prompt_format(self):
        """Task prompt builders produce correct formatted prompts."""
        from src.finetuning.tasks import TaskPrefixes
        prompt = IntentClassifier.build_task_prompt("categorize", "সংসদে বাজেট আলোচনা")
        assert TaskPrefixes.CATEGORIZE in prompt
        assert "-> বিভাগ:" in prompt

        prompt = IntentClassifier.build_task_prompt("ner", "ঢাকায় প্রধানমন্ত্রী")
        assert TaskPrefixes.NER in prompt
        assert "-> সত্তা:" in prompt


# ---------------------------------------------------------------------------
# 5. Normalizer & Text Processing
# ---------------------------------------------------------------------------

class TestNormalizer:
    """Validate Bangla Unicode normalizer edge cases."""

    def test_zero_width_chars_removed(self):
        raw = "বাংলাদেশ\u200cের উন্নয়ন\u200b কাজ চলছে।"
        clean = BanglaTextNormalizer.normalize_article_text(raw)
        assert "\u200b" not in clean
        assert "\u200c" not in clean

    def test_boilerplate_removal(self):
        raw = "আরও পড়ুন : অন্য একটি সংবাদ\nমূল সংবাদ এখানে শুরু।"
        clean = BanglaTextNormalizer.remove_boilerplates(raw)
        # The 'আরও পড়ুন' link line (with the article title) should be removed
        assert "অন্য একটি সংবাদ" not in clean
        # Main content line should remain
        assert "মূল সংবাদ" in clean


    def test_bangla_to_english_digits(self):
        assert BanglaTextNormalizer.bangla_to_english_digits("২০২৬") == "2026"

    def test_english_to_bangla_digits(self):
        assert BanglaTextNormalizer.english_to_bangla_digits("2026") == "২০২৬"

    def test_sentence_splitting(self):
        text = "বাংলাদেশ একটি সুন্দর দেশ। এখানে অনেক নদী আছে। প্রকৃতি অত্যন্ত মনোরম।"
        sentences = BanglaTextNormalizer.extract_sentences(text)
        assert len(sentences) >= 2
        assert any("সুন্দর দেশ" in s for s in sentences)
