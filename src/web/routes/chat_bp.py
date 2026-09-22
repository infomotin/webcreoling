"""
RAG & Specialized AI Chat Blueprint.
Serves the interactive web chat interface and JSON API endpoint for conversational Q&A and tasks.
"""

from flask import Blueprint, render_template, request, jsonify
from src.chat.interface import ChatPipeline
from src.web.auth import login_required, roles_required

chat_bp = Blueprint("chat", __name__)

_CHAT_PIPELINE = None


def get_chat_pipeline() -> ChatPipeline:
    """Lazy initialize singleton chat pipeline for web sessions."""
    global _CHAT_PIPELINE
    if _CHAT_PIPELINE is None:
        _CHAT_PIPELINE = ChatPipeline()
    return _CHAT_PIPELINE


@chat_bp.route("")
@login_required
@roles_required("admin", "editor", "analyst")
def index_view():
    """Render interactive chat page."""
    return render_template("chat.html")


@chat_bp.route("/api/message", methods=["POST"])
@login_required
@roles_required("admin", "editor", "analyst")
def send_message_api():
    """Process a chat message or task command via the AI pipeline."""
    data = request.get_json(force=True, silent=True) or {}
    user_message = (data.get("message") or data.get("query") or "").strip()

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    pipeline = get_chat_pipeline()
    result = pipeline.process_message(user_message)
    return jsonify(result)
