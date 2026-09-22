"""Unit tests for Multi-Task Fine-Tuning Task Manager."""

import json
from src.finetuning.tasks import TaskPrefixes, SpecializedTaskManager
from src.storage.models import Article


def test_specialized_task_formatting():
    content = "মিরপুরে বাংলাদেশ ও শ্রীলঙ্কার মধ্যকার টি-টোয়েন্টি ম্যাচ অনুষ্ঠিত হয়েছে।"
    title = "টি-টোয়েন্টিতে বাংলাদেশের জয়"
    category = "sports"

    # Categorization prompt
    cat_sample = SpecializedTaskManager.format_categorize_sample(content, category)
    assert TaskPrefixes.CATEGORIZE in cat_sample
    assert f"-> বিভাগ: {category}" in cat_sample

    # Headline prompt
    head_sample = SpecializedTaskManager.format_headline_sample(content, title)
    assert TaskPrefixes.HEADLINE in head_sample
    assert f"-> শিরোনাম: {title}" in head_sample

    # Summarize prompt
    summ_sample = SpecializedTaskManager.format_summarize_sample(content)
    assert TaskPrefixes.SUMMARIZE in summ_sample

    # NER prompt
    ner_sample = SpecializedTaskManager.format_ner_sample(content)
    assert TaskPrefixes.NER in ner_sample
    assert "-> সত্তা:" in ner_sample


def test_heuristic_entity_extraction():
    sample_text = "ঢাকায় প্রধানমন্ত্রী শেখ হাসিনা ও স্পিকার জাতীয় সংসদ অধিবেশনে উপস্থিত ছিলেন।"
    entities = SpecializedTaskManager.heuristic_extract_entities(sample_text)

    assert "Location" in entities
    assert "ঢাকা" in entities["Location"]
    assert "Person" in entities
    assert "প্রধানমন্ত্রী" in entities["Person"]
    assert "Organization" in entities
    assert "সংসদ" in entities["Organization"]
