"""Semantic fidelity measurement for AI-rewritten articles.

Measures how faithfully a rewritten article preserves the meaning of its source
using EMBEDDING-based cosine similarity (self-hosted Ollama / HF server) with a
target of >= 98% semantic accuracy. When the local LLM endpoint is unavailable,
degrades gracefully to an auditable lexical scorer (character n-gram + token
cosine + sequence ratio blend) with its own calibrated threshold.

Both score and method are surfaced in editorial review UIs and audit logs so
quality can be audited per article.
"""

import math
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.common.logger import get_logger
from src.integrations.llm_service import embed_text

logger = get_logger("webcreoling.nlp.semantic_fidelity")

EMBEDDING_THRESHOLD = 0.98     # 98% semantic accuracy target (embedding method)
LEXICAL_THRESHOLD = 0.60       # calibrated fallback when embeddings unavailable
SAMPLE_LIMIT = 6000            # chars considered per text (cost control)


class SemanticFidelity:
    """Embedding-first semantic fidelity scorer with lexical fallback."""

    @staticmethod
    def cosine(a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return dot / (na * nb)

    @staticmethod
    def normalize(text: str) -> str:
        text = (text or "").lower()
        text = re.sub(r"\s+", " ", text)
        return re.sub(r"[^\w\u0980-\u09ff ]", "", text).strip()

    @classmethod
    def _token_cosine(cls, a: str, b: str) -> float:
        ta, tb = a.split(), b.split()
        if not ta or not tb:
            return 0.0
        counts_a: Dict[str, int] = {}
        counts_b: Dict[str, int] = {}
        for t in ta:
            counts_a[t] = counts_a.get(t, 0) + 1
        for t in tb:
            counts_b[t] = counts_b.get(t, 0) + 1
        dot = sum(v * counts_b.get(k, 0) for k, v in counts_a.items())
        na = math.sqrt(sum(v * v for v in counts_a.values()))
        nb = math.sqrt(sum(v * v for v in counts_b.values()))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return dot / (na * nb)

    @classmethod
    def _char_ngram_jaccard(cls, a: str, b: str, n: int = 4) -> float:
        ga = {a[i:i + n] for i in range(max(0, len(a) - n + 1))}
        gb = {b[i:i + n] for i in range(max(0, len(b) - n + 1))}
        if not ga or not gb:
            return 0.0
        return len(ga & gb) / len(ga | gb)

    @classmethod
    def lexical_score(cls, original: str, rewritten: str) -> float:
        """Blend of token cosine, char-4gram Jaccard and sequence ratio (0..1)."""
        from difflib import SequenceMatcher
        a = cls.normalize(original)[:SAMPLE_LIMIT]
        b = cls.normalize(rewritten)[:SAMPLE_LIMIT]
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0
        tok = cls._token_cosine(a, b)
        ng = cls._char_ngram_jaccard(a, b)
        ratio = SequenceMatcher(None, a, b).ratio()
        return round(max(tok, 0.35 * tok + 0.35 * ng + 0.30 * ratio, ratio * 0.9), 4)

    @classmethod
    def measure(
        cls,
        original: str,
        rewritten: str,
        threshold: Optional[float] = None,
        embedding_threshold: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Score rewritten text fidelity against the original source text.

        Returns: {"score", "method", "threshold", "passed", "measured_at"}.
        """
        embedding_threshold = float(embedding_threshold or EMBEDDING_THRESHOLD)
        method = "embedding"
        score: Optional[float] = None

        orig_vec = embed_text((original or "")[:SAMPLE_LIMIT])
        if orig_vec:
            rew_vec = embed_text((rewritten or "")[:SAMPLE_LIMIT])
            if rew_vec:
                score = round(cls.cosine(orig_vec, rew_vec), 4)

        if score is None:
            method = "lexical_fallback"
            score = cls.lexical_score(original, rewritten)

        applicable_threshold = float(
            threshold if threshold is not None
            else (embedding_threshold if method == "embedding" else LEXICAL_THRESHOLD)
        )
        passed = score >= applicable_threshold
        result = {
            "score": score,
            "method": method,
            "threshold": applicable_threshold,
            "embedding_threshold": embedding_threshold,
            "passed": bool(passed),
            "measured_at": datetime.utcnow().isoformat(),
        }
        if not passed:
            logger.warning(
                f"[Semantic Fidelity] BELOW TARGET: {score:.4f} < {applicable_threshold} "
                f"({method}) — flagged for editorial review."
            )
        return result
