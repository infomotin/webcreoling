"""
RAG & Specialized AI Chat Blueprint.
Serves the interactive web chat interface and JSON API endpoint for
conversational Q&A and task-specific commands (categorize, headline, summarize, NER).
Uses lazy-initialized singleton ChatPipeline with graceful degradation fallback.
"""

import logging
from flask import Blueprint, render_template, request, jsonify, current_app
from src.common.logger import get_logger

logger = get_logger("webcreoling.web.chat")

chat_bp = Blueprint("chat", __name__)

_CHAT_PIPELINE = None
_PIPELINE_INIT_FAILED = False   # Prevent repeated expensive retry on broken model path


def get_chat_pipeline():
    """
    Lazy-initialize singleton ChatPipeline for web sessions.
    Returns None (graceful degradation) if model loading fails.
    """
    global _CHAT_PIPELINE, _PIPELINE_INIT_FAILED
    if _CHAT_PIPELINE is not None:
        return _CHAT_PIPELINE
    if _PIPELINE_INIT_FAILED:
        return None

    try:
        from src.chat.interface import ChatPipeline
        _CHAT_PIPELINE = ChatPipeline()
        logger.info("ChatPipeline initialized successfully for web endpoint.")
        return _CHAT_PIPELINE
    except Exception as exc:
        _PIPELINE_INIT_FAILED = True
        logger.error(f"ChatPipeline initialization failed: {exc}", exc_info=True)
        return None


from src.web.auth import login_required, roles_required


@chat_bp.route("")
@login_required
@roles_required("admin", "editor")
def index_view():
    """Render interactive RAG chat page."""
    return render_template("chat.html")


@chat_bp.route("/api/message", methods=["POST"])
def send_message_api():
    """
    Process a chat message or explicit task command.

    Request JSON: {"message": "<user input>"}
    Response JSON: {intent, response, citations, related_posts, latency_seconds}
    On model unavailability, returns a rule-based fallback response.
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
        user_message = (data.get("message") or data.get("query") or "").strip()

        if not user_message:
            return jsonify({"error": "Empty message. Please send a question or task command."}), 400

        if len(user_message) > 2000:
            return jsonify({"error": "Message too long. Max 2000 characters."}), 400

        pipeline = get_chat_pipeline()

        if pipeline is None:
            # Graceful degradation: rule-based RAG without LLM generation
            return _fallback_response(user_message)

        result = pipeline.process_message(user_message)
        return jsonify(result)

    except Exception as exc:
        logger.error(f"Chat API error: {exc}", exc_info=True)
        return jsonify({"error": "Internal error processing message. Please try again."}), 500


def _fallback_response(user_message: str):
    """
    Rule-based fallback when ChatPipeline (LLM model) is unavailable.
    Uses RAGEngine for retrieval and IntentClassifier for task routing,
    but returns the article context directly instead of model-generated text.
    """
    try:
        from src.chat.task_handlers import IntentClassifier
        from src.chat.rag_engine import RAGEngine
        from src.finetuning.tasks import SpecializedTaskManager
        import json as _json
        import time

        start_time = time.time()
        intent, payload = IntentClassifier.parse_intent(user_message)
        rag = RAGEngine()

        if intent == "rag_qa":
            retrieved = rag.search_relevant_articles(payload)
            if retrieved:
                top = retrieved[0]
                response = f"প্রাপ্ত তথ্যানুযায়ী: {top.get('title', '')}। {(top.get('content_text') or '')[:250]}..."
            else:
                response = "এই বিষয়ে ডেটাবেসে কোনো তথ্য পাওয়া যায়নি।"
            citations = [
                {"id": a.get("id"), "title": a.get("title"), "source": a.get("source"),
                 "published_at": a.get("published_at"), "url": a.get("url")}
                for a in retrieved
            ]
        elif intent == "ner":
            entities = SpecializedTaskManager.heuristic_extract_entities(payload)
            response = _json.dumps(entities, ensure_ascii=False)
            citations = []
        elif intent == "categorize":
            response = "জাতীয় / সাধারণ সংবাদ"
            citations = []
        elif intent == "headline":
            response = payload[:60] + "..."
            citations = []
        elif intent == "summarize":
            sentences = user_message.split("।")[:2]
            response = "।".join(sentences).strip() + "।"
            citations = []
        else:
            response = "মডেল বর্তমানে অনুপলব্ধ। অনুগ্রহ করে পরে চেষ্টা করুন।"
            citations = []

        return jsonify({
            "intent": intent,
            "user_input": user_message,
            "response": response,
            "citations": citations,
            "related_posts": [],
            "latency_seconds": round(time.time() - start_time, 3),
            "fallback_mode": True,
        })

    except Exception as exc:
        logger.error(f"Fallback response error: {exc}", exc_info=True)
        return jsonify({
            "intent": "rag_qa",
            "user_input": user_message,
            "response": "সিস্টেম বর্তমানে অনুপলব্ধ।",
            "citations": [],
            "related_posts": [],
            "latency_seconds": 0.0,
            "fallback_mode": True,
        })
