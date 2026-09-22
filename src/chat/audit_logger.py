"""
Chat Audit Logger.
Persists conversational Q&A queries, retrieved context IDs, commands, and model outputs into JSONL.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from config.settings import settings


class ChatAuditLogger:
    """Logs chat interactions to data/chat_history.jsonl."""

    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = log_path or (settings.DATA_DIR / "chat_history.jsonl")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_interaction(
        self,
        mode: str,
        user_input: str,
        response_text: str,
        retrieved_article_ids: Optional[list] = None,
        latency_seconds: float = 0.0,
    ) -> None:
        """Append an interaction entry to the JSONL log file."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "mode": mode,  # 'rag_qa' or 'explicit_task'
            "user_input": user_input,
            "response": response_text,
            "retrieved_article_ids": retrieved_article_ids or [],
            "latency_seconds": round(latency_seconds, 3),
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
