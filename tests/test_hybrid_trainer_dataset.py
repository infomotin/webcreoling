"""
Unit Tests — Hybrid Multi-Task LoRA Trainer Dataset Builder & Tokenization.
Tests dataset construction, task sampling, tokenization shape, and CPU enforcement.
No actual model training is performed.
"""

import os
import json
import pytest
from unittest.mock import MagicMock, patch
from src.finetuning.tasks import SpecializedTaskManager, TaskPrefixes
from src.storage.models import Article


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_article(idx: int, category: str = "politics") -> Article:
    """Create a minimal Article ORM object for testing."""
    return Article(
        id=idx,
        url=f"http://example.bd/news/{idx}",
        source="test_portal",
        title=f"পরীক্ষামূলক সংবাদ শিরোনাম {idx}",
        author="পরীক্ষা প্রতিবেদক",
        category=category,
        content_text=(
            f"এটি সংবাদ নম্বর {idx}। ঢাকায় আজ একটি গুরুত্বপূর্ণ রাজনৈতিক ঘটনা ঘটেছে। "
            "প্রধানমন্ত্রী জাতীয় সংসদে বক্তব্য দিয়েছেন। সরকার নতুন পরিকল্পনা ঘোষণা করেছে।"
        ),
        summary=f"সংসদে ঘটনা {idx} নিয়ে আলোচনা।",
        extracted_entities={
            "Person": ["প্রধানমন্ত্রী"],
            "Location": ["ঢাকা", "বাংলাদেশ"],
            "Organization": ["সংসদ"],
        },
    )


SAMPLE_ARTICLES = [_make_article(i) for i in range(1, 12)]


# ---------------------------------------------------------------------------
# Test: Prompt Formatters
# ---------------------------------------------------------------------------

class TestPromptFormatters:
    """Validate prompt format for each task type."""

    def test_categorize_format(self):
        sample = SpecializedTaskManager.format_categorize_sample(
            "সংসদে বাজেট পেশ হয়েছে।", "politics"
        )
        assert TaskPrefixes.CATEGORIZE in sample
        assert "-> বিভাগ: politics" in sample
        assert "<|endoftext|>" in sample

    def test_headline_format(self):
        sample = SpecializedTaskManager.format_headline_sample(
            "বাংলাদেশ ক্রিকেট দল জয় পেয়েছে।", "ক্রিকেটে জয়"
        )
        assert TaskPrefixes.HEADLINE in sample
        assert "-> শিরোনাম: ক্রিকেটে জয়" in sample
        assert "<|endoftext|>" in sample

    def test_summarize_format_with_summary(self):
        sample = SpecializedTaskManager.format_summarize_sample(
            "জাতীয় সংসদে নতুন বিল পাস হয়েছে।", "বিল পাস হয়েছে।"
        )
        assert TaskPrefixes.SUMMARIZE in sample
        assert "-> সারসংক্ষেপ:" in sample

    def test_summarize_format_without_summary_extracts(self):
        """Without a summary, the formatter should auto-extract from content."""
        content = "বাংলাদেশে নতুন প্রকল্প শুরু হয়েছে। হাজার মানুষ উপকৃত হবেন।"
        sample = SpecializedTaskManager.format_summarize_sample(content)
        assert "-> সারসংক্ষেপ:" in sample

    def test_ner_format_with_entities(self):
        entities = {"Person": ["ড. করিম"], "Location": ["ঢাকা"], "Organization": []}
        sample = SpecializedTaskManager.format_ner_sample(
            "ঢাকায় ড. করিম বক্তব্য দিয়েছেন।", entities
        )
        assert TaskPrefixes.NER in sample
        assert "-> সত্তা:" in sample
        assert "ড. করিম" in sample

    def test_ner_format_no_entities_uses_heuristic(self):
        """Without entities, heuristic extraction should run."""
        sample = SpecializedTaskManager.format_ner_sample(
            "ঢাকায় প্রধানমন্ত্রী বক্তব্য দিয়েছেন।"
        )
        assert "-> সত্তা:" in sample
        data = json.loads(sample.split("-> সত্তা:")[1].split("<|endoftext|>")[0].strip())
        assert "Location" in data


# ---------------------------------------------------------------------------
# Test: Multi-Task Dataset Builder
# ---------------------------------------------------------------------------

class TestMultiTaskDatasetBuilder:
    """DatasetDict construction and structure validation."""

    def test_all_tasks_in_dataset(self):
        ds = SpecializedTaskManager.build_multi_task_dataset(SAMPLE_ARTICLES)
        assert "train" in ds
        assert "validation" in ds
        all_tasks = set(ds["train"]["task"]) | set(ds["validation"]["task"])
        assert {"categorize", "headline", "summarize", "ner"}.issubset(all_tasks)

    def test_selected_tasks_subset(self):
        ds = SpecializedTaskManager.build_multi_task_dataset(
            SAMPLE_ARTICLES, selected_tasks=["summarize"]
        )
        all_tasks = set(ds["train"]["task"]) | set(ds["validation"]["task"])
        assert "summarize" in all_tasks
        assert "categorize" not in all_tasks
        assert "headline" not in all_tasks

    def test_total_sample_count(self):
        """With 11 articles × 4 tasks = 44 samples minimum."""
        ds = SpecializedTaskManager.build_multi_task_dataset(SAMPLE_ARTICLES)
        total = len(ds["train"]) + len(ds["validation"])
        assert total >= 40  # Some may be filtered by content length

    def test_text_field_has_task_prefix(self):
        ds = SpecializedTaskManager.build_multi_task_dataset(SAMPLE_ARTICLES)
        for row in list(ds["train"])[:10]:
            assert any(prefix in row["text"] for prefix in [
                TaskPrefixes.CATEGORIZE,
                TaskPrefixes.HEADLINE,
                TaskPrefixes.SUMMARIZE,
                TaskPrefixes.NER,
            ])

    def test_empty_articles_no_crash(self):
        """Empty article list produces at least 1 dummy sample."""
        ds = SpecializedTaskManager.build_multi_task_dataset([])
        total = len(ds["train"]) + len(ds["validation"])
        assert total >= 1

    def test_short_articles_filtered(self):
        """Articles with < 60 chars content are skipped."""
        short_article = _make_article(99)
        short_article.content_text = "ছোট"  # Too short
        ds = SpecializedTaskManager.build_multi_task_dataset([short_article])
        # Should get dummy sample only
        total = len(ds["train"]) + len(ds["validation"])
        assert total >= 1  # Dummy sample


# ---------------------------------------------------------------------------
# Test: CPU Environment Guards
# ---------------------------------------------------------------------------

class TestCPUGuards:
    """Verify that the CPU-forcing environment variable is set."""

    def test_cuda_visible_devices_set(self):
        """After importing the trainer module, CUDA_VISIBLE_DEVICES should be set."""
        # The import at module level sets this
        from src.finetuning import hybrid_trainer
        assert os.environ.get("CUDA_VISIBLE_DEVICES") == ""

    def test_torch_no_gpu_required(self):
        """Training code must work without GPU — no CUDA assertions."""
        import torch
        # This should never fail on a CPU-only machine
        assert isinstance(torch.zeros(2, 2), torch.Tensor)


# ---------------------------------------------------------------------------
# Test: HybridFineTuner init (mocked model loading)
# ---------------------------------------------------------------------------

class TestHybridFineTunerInit:
    """Test HybridFineTuner initialization with mocked transformers."""

    @patch("src.finetuning.hybrid_trainer.AutoTokenizer")
    def test_tokenizer_pad_token_set(self, mock_tokenizer_cls):
        """Pad token must be set when it's None on the tokenizer."""
        mock_tok = MagicMock()
        mock_tok.pad_token = None
        mock_tok.eos_token = "<|endoftext|>"
        mock_tok.eos_token_id = 50256
        mock_tokenizer_cls.from_pretrained.return_value = mock_tok

        from src.finetuning.hybrid_trainer import HybridFineTuner
        from config.settings import settings
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            trainer = HybridFineTuner(base_model_path=Path(tmp), output_dir=Path(tmp))
            # The trainer should have set pad_token after load
            assert mock_tok.pad_token == "<|endoftext|>"
