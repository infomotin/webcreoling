"""
Explicit Task Parser & Intent Classifier for Chat Interface.
Maps user inputs to either RAG Conversational Q&A or one of the 4 specialized skills.
"""

import re
from typing import Dict, Any, Tuple, Optional
from src.finetuning.tasks import TaskPrefixes


class IntentClassifier:
    """Classifies user chat messages into explicit task commands or conversational RAG queries."""

    # Regex patterns for explicit commands (English and Bangla)
    PATTERNS = {
        "categorize": [
            r"^categorize\s+(?:this\s+)?(?:article\s*[:\-]?)?\s*(.*)$",
            r"^classify\s+(?:this\s+)?(?:article\s*[:\-]?)?\s*(.*)$",
            r"^বিভাগ\s*(?:নির্ধারণ\s*[:\-]?)?\s*(.*)$",
        ],
        "headline": [
            r"^generate\s+(?:a\s+)?headline\s+(?:for\s+this\s*[:\-]?)?\s*(.*)$",
            r"^headline\s*[:\-]?\s*(.*)$",
            r"^শিরোনাম\s*(?:তৈরি\s*[:\-]?)?\s*(.*)$",
        ],
        "summarize": [
            r"^summarize\s+(?:this\s+)?(?:article\s*[:\-]?)?\s*(.*)$",
            r"^summary\s*[:\-]?\s*(.*)$",
            r"^সারসংক্ষেপ\s*(?:করুন\s*[:\-]?)?\s*(.*)$",
        ],
        "ner": [
            r"^extract\s+entities\s+(?:from\s+this\s*[:\-]?)?\s*(.*)$",
            r"^ner\s*[:\-]?\s*(.*)$",
            r"^সত্তা\s*(?:নিষ্কাশন\s*[:\-]?)?\s*(.*)$",
        ],
    }

    @classmethod
    def parse_intent(cls, user_input: str) -> Tuple[str, str]:
        """
        Determine if the user provided an explicit command or a general question.

        Returns:
            (intent_name, clean_payload)
            intent_name is one of: 'categorize', 'headline', 'summarize', 'ner', or 'rag_qa'
        """
        text = user_input.strip()

        for intent, patterns in cls.PATTERNS.items():
            for pat in patterns:
                match = re.match(pat, text, re.IGNORECASE | re.DOTALL)
                if match:
                    payload = match.group(1).strip()
                    if payload:
                        return intent, payload

        # Default to Conversational RAG Q&A
        return "rag_qa", text

    @classmethod
    def build_task_prompt(cls, intent: str, text_payload: str) -> str:
        """Construct the prompt formatted for the fine-tuned multi-task model."""
        if intent == "categorize":
            return f"{TaskPrefixes.CATEGORIZE}\nখবর: {text_payload[:600]}\n-> বিভাগ:"
        elif intent == "headline":
            return f"{TaskPrefixes.HEADLINE}\nখবর: {text_payload[:600]}\n-> শিরোনাম:"
        elif intent == "summarize":
            return f"{TaskPrefixes.SUMMARIZE}\nখবর: {text_payload[:600]}\n-> সারসংক্ষেপ:"
        elif intent == "ner":
            return f"{TaskPrefixes.NER}\nখবর: {text_payload[:600]}\n-> সত্তা:"
        else:
            return text_payload
