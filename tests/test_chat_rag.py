"""Unit tests for Chat Intent Classification and RAG Prompt Generation."""

import pytest
from src.chat.task_handlers import IntentClassifier
from src.chat.rag_engine import RAGEngine


def test_intent_classification_explicit_commands():
    # Categorize
    intent, payload = IntentClassifier.parse_intent("categorize this article: মিরপুরে ক্রিকেট ম্যাচ শুরু হয়েছে")
    assert intent == "categorize"
    assert "মিরপুরে ক্রিকেট ম্যাচ" in payload

    # Headline
    intent, payload = IntentClassifier.parse_intent("generate a headline for this: চলতি অর্থবছরে পোশাক শিল্পে রপ্তানি বৃদ্ধি পেয়েছে")
    assert intent == "headline"
    assert "পোশাক শিল্পে রপ্তানি" in payload

    # Summarize
    intent, payload = IntentClassifier.parse_intent("summarize this: জাতিসংঘের বিশেষ অধিবেশনে জলবায়ু পরিবর্তন নিয়ে আলোচনা হয়েছে")
    assert intent == "summarize"
    assert "জাতিসংঘের বিশেষ অধিবেশনে" in payload

    # NER
    intent, payload = IntentClassifier.parse_intent("extract entities from this: ঢাকায় প্রধানমন্ত্রী বক্তব্য দিয়েছেন")
    assert intent == "ner"
    assert "ঢাকায় প্রধানমন্ত্রী বক্তব্য" in payload


def test_intent_classification_rag_qa():
    # General question
    intent, payload = IntentClassifier.parse_intent("সংসদে নতুন অধিবেশন কবে শুরু হবে?")
    assert intent == "rag_qa"
    assert "সংসদে নতুন অধিবেশন কবে শুরু হবে?" in payload


def test_rag_prompt_construction():
    rag = RAGEngine()
    mock_retrieved = [
        {
            "id": 1,
            "title": "সংসদের অধিবেশন শুরু",
            "source": "prothom_alo",
            "published_at": "2026-09-22",
            "content_text": "জাতীয় সংসদে অর্থনৈতিক বাজেট নিয়ে আলোচনা হয়েছে।",
        }
    ]
    prompt = rag.build_rag_prompt("সংসদে কী আলোচনা হয়েছে?", mock_retrieved)
    assert "তথ্যসূত্র:" in prompt
    assert "সংসদের অধিবেশন শুরু" in prompt
    assert "প্রশ্ন: সংসদে কী আলোচনা হয়েছে?" in prompt
    assert "-> উত্তর:" in prompt
