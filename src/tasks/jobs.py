"""Scheduled background job functions.

Each function owns its DB session, logs structured progress, degrades
gracefully on external failures, and returns a human-readable status message
(the scheduler records it into the job telemetry).
"""

from datetime import datetime
from typing import Any, Dict, Optional

from src.common.logger import get_logger

logger = get_logger("webcreoling.tasks.jobs")


def multi_source_scrape_task(
    max_items: Optional[int] = None,
    sources: Optional[list] = None,
) -> str:
    """Scrape ALL configured sources (HTML / RSS / news APIs) with per-source
    exponential backoff — failed sources are skipped, the rest continue."""
    from src.scraper.multi_source import MultiSourceScraper
    summary = MultiSourceScraper.run_cycle(sources=sources, max_items=max_items)
    skipped = len(summary.get("skipped_sources", []))
    return (
        f"Multi-Source scrape: {summary['sources_ok']}/{summary['sources_enabled']} sources ok, "
        f"{skipped} skipped (retries exhausted) | fetched {summary['fetched']} | "
        f"ingested {summary['ingested']} | duplicates {summary['duplicates']} | "
        f"queued {summary['queued']} | auto-published {summary['auto_published']} | "
        f"failed {summary['failed']}."
    )


def approval_sweep_task() -> str:
    """Escalate overdue approval requests to the next senior role; auto-approve
    (approval by silence) when configured. All actions are audited."""
    from src.automation.agent_controller import AgenticController
    summary = AgenticController.sweep_timeouts()
    if summary.get("error"):
        return f"Approval sweep failed: {summary['error']}"
    if not summary.get("checked"):
        return "Approval sweep: no overdue requests."
    return (
        f"Approval sweep: {summary['checked']} overdue | escalated {summary['escalated']} | "
        f"auto-approved {summary['auto_approved']} | awaiting human {summary['waiting']}."
    )


def fact_check_reaudit_task(limit: int = 20) -> str:
    """Periodic dual-strategy re-audit of recent articles (cross-source confidence refresh)."""
    try:
        from src.automation.fact_checker import FactCheckService
        from src.storage.database import get_db_session
        from src.storage.models import Article

        audited = 0
        with get_db_session() as session:
            articles = session.query(Article).order_by(Article.id.desc()).limit(limit).all()
            for art in articles:
                try:
                    result = FactCheckService.full_check(
                        art.title, art.content_text or "", session=session
                    )
                    entities = dict(art.extracted_entities or {})
                    entities["fact_check_reaudit"] = {
                        "combined_confidence": result.get("combined_confidence"),
                        "strategy": result.get("strategy"),
                        "flags": result.get("flags"),
                        "at": datetime.utcnow().isoformat(),
                    }
                    art.extracted_entities = entities
                    audited += 1
                except Exception as art_exc:
                    logger.warning(f"Re-audit failed for article #{art.id}: {art_exc}")
        return f"Fact-check re-audit: refreshed {audited} recent article(s)."
    except Exception as exc:
        logger.error(f"Fact-check re-audit task failed: {exc}")
        return f"Fact-check re-audit failed: {exc}"
