"""Fact-checking with a dual strategy:

  1. CROSS-SOURCE verification — cross-references the claims against multiple
     previously scraped sources stored in the database (articles + raw items).
  2. EXTERNAL fact-check APIs — configurable provider (Snopes / FactCheck.org /
     generic JSON endpoint) via environment/site config.

Both strategies are configurable, weighted, and surfaced as a combined
confidence score + flags for HUMAN review (the AI Agent never makes the final
verdict — it routes to the Editorial Lead).
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from src.common.logger import get_logger

logger = get_logger("webcreoling.automation.fact_check")

DEFAULT_POLICY: Dict[str, Any] = {
    "cross_source_enabled": True,
    "cross_source_min_similarity": 0.55,   # candidate corroboration threshold
    "cross_source_sample": 300,            # recent articles scanned
    "external_enabled": False,             # requires API url/key (off by default)
    "weight_cross_source": 0.6,
    "weight_external": 0.4,
    "low_confidence_threshold": 60.0,      # below -> flag for human review
    "high_confidence_threshold": 80.0,
    "updated_at": None,
}


def _extract_claims(title: str, content: str, max_claims: int = 4) -> List[str]:
    """Pull the most claim-like sentences (numbers, proper nouns, first sentences)."""
    import re
    text = f"{title or ''}. {content or ''}"
    sentences = [s.strip() for s in re.split(r"(?<=[।.!?\n])\s+", text) if s.strip()]
    scored: List[tuple] = []
    for sent in sentences:
        score = 0
        if re.search(r"\d", sent):
            score += 2
        if re.search(r"[A-Z\u0980-\u09ff]", sent):
            score += 1
        if 30 <= len(sent) <= 300:
            score += 1
        scored.append((score, sent))
    scored.sort(key=lambda x: x[0], reverse=True)
    picked = [s for _, s in scored[:max_claims]]
    return picked or [f"{title or ''}".strip()]


class FactCheckService:
    """Cross-source + external fact-checking with weighted confidence scoring."""

    # ------------------------------------------------------------------
    # Policy config
    # ------------------------------------------------------------------
    @staticmethod
    def get_policy(session=None) -> Dict[str, Any]:
        policy = dict(DEFAULT_POLICY)
        owns = session is None
        try:
            if owns:
                from src.storage.database import get_db_session
                ctx = get_db_session()
                session = ctx.__enter__()
            from src.storage.repositories import SiteConfigRepository
            stored = SiteConfigRepository(session).get_config("fact_check_policy", None)
            if isinstance(stored, dict):
                policy.update(stored)
        except Exception as exc:
            logger.debug(f"Fact-check policy load note: {exc}")
        finally:
            if owns:
                try:
                    ctx.__exit__(None, None, None)
                except Exception:
                    pass
        return policy

    @staticmethod
    def save_policy(session, data: Dict[str, Any]) -> Dict[str, Any]:
        from src.storage.repositories import SiteConfigRepository
        policy = dict(DEFAULT_POLICY)
        repo = SiteConfigRepository(session)
        stored = repo.get_config("fact_check_policy", None)
        if isinstance(stored, dict):
            policy.update(stored)
        policy.update(data)
        policy["updated_at"] = datetime.utcnow().isoformat()
        repo.set_config("fact_check_policy", policy)
        return policy

    # ------------------------------------------------------------------
    # Strategy 1: cross-source verification against the scraped DB corpus
    # ------------------------------------------------------------------
    @classmethod
    def cross_source_check(
        cls,
        title: str,
        content: str,
        session=None,
        policy: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from src.automation.auto_scroller import AutoScroller

        owns = session is None
        ctx = None
        try:
            if owns:
                from src.storage.database import get_db_session
                ctx = get_db_session()
                session = ctx.__enter__()
            policy = policy or cls.get_policy(session)
            if not policy.get("cross_source_enabled", True):
                return {"available": False, "reason": "disabled", "confidence": 0.0}

            from src.storage.models import Article
            min_sim = float(policy.get("cross_source_min_similarity", 0.55))
            sample = int(policy.get("cross_source_sample", 300))
            claim_text = f"{title} " + " ".join(_extract_claims(title, content))

            candidates = (
                session.query(Article)
                .order_by(Article.id.desc())
                .limit(sample)
                .all()
            )
            corroborating: List[Dict[str, Any]] = []
            distinct_sources = set()
            best_score = 0.0
            for art in candidates:
                score = AutoScroller.text_similarity(
                    claim_text, f"{art.title} {art.content_text or ''}"
                )
                if score >= min_sim:
                    corroborating.append({
                        "article_id": art.id,
                        "title": art.title,
                        "source": art.source,
                        "url": art.original_source_url or art.url,
                        "similarity": score,
                    })
                    distinct_sources.add(art.source or "unknown")
                    best_score = max(best_score, score)

            # Confidence model: base + distinct-source diversity + best-match strength
            confidence = 25.0 + 15.0 * len(distinct_sources) + 35.0 * best_score
            confidence = round(min(95.0, confidence), 1)
            return {
                "available": True,
                "method": "cross_source_db",
                "corroborating_count": len(corroborating),
                "distinct_sources": sorted(distinct_sources),
                "best_similarity": round(best_score, 4),
                "confidence": confidence,
                "corroborating": corroborating[:8],
                "checked_at": datetime.utcnow().isoformat(),
            }
        except Exception as exc:
            logger.warning(f"Cross-source fact-check failed (graceful): {exc}")
            return {"available": False, "error": str(exc), "confidence": 0.0}
        finally:
            if owns and ctx is not None:
                try:
                    ctx.__exit__(None, None, None)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Strategy 2: external fact-check APIs (Snopes / FactCheck.org / generic)
    # ------------------------------------------------------------------
    @classmethod
    def external_check(
        cls,
        title: str,
        content: str,
        policy: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        import requests as _requests
        from config.settings import settings

        policy = policy or cls.get_policy()
        if not policy.get("external_enabled", False):
            return {"available": False, "reason": "disabled", "confidence": 0.0}

        provider = getattr(settings, "FACTCHECK_PROVIDER", "generic") or "generic"
        url = getattr(settings, "FACTCHECK_API_URL", "") or ""
        key = getattr(settings, "FACTCHECK_API_KEY", "") or ""
        timeout = int(getattr(settings, "FACTCHECK_TIMEOUT", 10))

        # Well-known presets (users still supply their own endpoint/key)
        if not url:
            if provider == "snopes":
                url = "https://www.snopes.com/api/fact-check/"
            elif provider == "factcheck_org":
                url = "https://www.factcheck.org/api/query/"
        if not url:
            return {"available": False, "reason": "not_configured", "confidence": 0.0}

        claim = " ".join(_extract_claims(title, content, max_claims=1))
        try:
            resp = _requests.get(
                url,
                params={"q": claim, "claim": claim, "text": claim[:500],
                        "key": key, "api_key": key},
                headers={"X-Api-Key": key, "Authorization": f"Bearer {key}"},
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json() if "json" in (resp.headers.get("Content-Type") or "") else {"raw": resp.text[:2000]}

            # Lenient field extraction across providers
            verdict = None
            confidence_raw: Optional[float] = None
            if isinstance(data, dict):
                verdict = (data.get("verdict") or data.get("rating")
                           or data.get("result") or data.get("claim"))
                confidence_raw = data.get("confidence") or data.get("score") or data.get("rating_value")
                results = data.get("results")
                if isinstance(results, list) and results:
                    first = results[0] if isinstance(results[0], dict) else {}
                    verdict = verdict or first.get("rating") or first.get("verdict")
                    confidence_raw = confidence_raw or first.get("confidence") or first.get("score")
            confidence = float(confidence_raw) if confidence_raw is not None else 50.0
            if 0.0 < confidence <= 1.0:  # fraction-style values (0..1) -> percent scale
                confidence *= 100.0
            return {
                "available": True,
                "provider": provider,
                "verdict": str(verdict) if verdict else None,
                "confidence": round(min(95.0, max(0.0, confidence)), 1),
                "checked_at": datetime.utcnow().isoformat(),
            }
        except Exception as exc:
            logger.warning(f"External fact-check API unavailable (graceful): {exc}")
            return {"available": False, "error": str(exc), "confidence": 0.0}

    # ------------------------------------------------------------------
    # Combined dual-strategy result
    # ------------------------------------------------------------------
    @classmethod
    def full_check(cls, title: str, content: str, session=None) -> Dict[str, Any]:
        owns = session is None
        ctx = None
        try:
            if owns:
                from src.storage.database import get_db_session
                ctx = get_db_session()
                session = ctx.__enter__()
            policy = cls.get_policy(session)

            internal = cls.cross_source_check(title, content, session=session, policy=policy)
            external = cls.external_check(title, content, policy=policy)

            w_int = float(policy.get("weight_cross_source", 0.6))
            w_ext = float(policy.get("weight_external", 0.4))
            if external.get("available"):
                combined = w_int * float(internal.get("confidence", 0.0)) + \
                           w_ext * float(external.get("confidence", 0.0))
            else:
                combined = float(internal.get("confidence", 0.0))

            low_thr = float(policy.get("low_confidence_threshold", 60.0))
            flags: List[str] = []
            if internal.get("available") and internal.get("corroborating_count", 0) == 0:
                flags.append("no_cross_source_corroboration")
            if not external.get("available") and policy.get("external_enabled", False):
                flags.append("external_factcheck_unavailable")
            if combined < low_thr:
                flags.append("low_confidence")

            return {
                "cross_source": internal,
                "external": external,
                "combined_confidence": round(combined, 1),
                "low_confidence_threshold": low_thr,
                "flags": flags,
                "strategy": "dual" if external.get("available") else "cross_source_only",
                "checked_at": datetime.utcnow().isoformat(),
            }
        except Exception as exc:
            logger.error(f"Full fact-check failed: {exc}")
            return {"cross_source": {"available": False}, "external": {"available": False},
                    "combined_confidence": 0.0, "flags": ["fact_check_error", "low_confidence"],
                    "strategy": "error", "error": str(exc)}
        finally:
            if owns and ctx is not None:
                try:
                    ctx.__exit__(None, None, None)
                except Exception:
                    pass
