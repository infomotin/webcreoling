"""Optional standalone APScheduler entrypoint.

The web app uses the built-in `AutomationScheduler` thread by default (simplest
for the MVP timeline). This module lets a deployment run the same job functions
on APScheduler instead — run with:

    python -m src.tasks.apscheduler_runner

For multi-node / heavy-throughput scale later, migrate these job functions to
Celery (same signatures; only the transport changes).
"""

import logging
from typing import Any, Dict

from src.common.logger import get_logger

logger = get_logger("webcreoling.tasks.apscheduler")

# Default intervals (seconds) — spec target: news sources every 2-4 hours,
# approval escalation sweep hourly.
DEFAULT_JOBS: Dict[str, Dict[str, Any]] = {
    "multi_source_scrape": {"interval": 3 * 3600, "job_id": "multi_source_scrape"},
    "approval_sweep": {"interval": 3600, "job_id": "approval_sweep"},
    "fact_check_reaudit": {"interval": 6 * 3600, "job_id": "fact_check_reaudit"},
}


def _run_multi_source_scrape() -> None:
    from src.tasks.jobs import multi_source_scrape_task
    logger.info(multi_source_scrape_task())


def _run_approval_sweep() -> None:
    from src.tasks.jobs import approval_sweep_task
    logger.info(approval_sweep_task())


def _run_fact_check_reaudit() -> None:
    from src.tasks.jobs import fact_check_reaudit_task
    logger.info(fact_check_reaudit_task())


def build_scheduler():
    """Construct an APScheduler BackgroundScheduler with the standard job set."""
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(_run_multi_source_scrape, "interval",
                      seconds=DEFAULT_JOBS["multi_source_scrape"]["interval"],
                      id="multi_source_scrape", replace_existing=True,
                      max_instances=1, coalesce=True)
    scheduler.add_job(_run_approval_sweep, "interval",
                      seconds=DEFAULT_JOBS["approval_sweep"]["interval"],
                      id="approval_sweep", replace_existing=True,
                      max_instances=1, coalesce=True)
    scheduler.add_job(_run_fact_check_reaudit, "interval",
                      seconds=DEFAULT_JOBS["fact_check_reaudit"]["interval"],
                      id="fact_check_reaudit", replace_existing=True,
                      max_instances=1, coalesce=True)
    return scheduler


def main() -> None:  # pragma: no cover - manual entrypoint
    scheduler = build_scheduler()
    scheduler.start()
    logger.info("APScheduler standalone runner started with jobs: "
                f"{[j.id for j in scheduler.get_jobs()]}")
    try:
        import time
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown(wait=False)
        logger.info("APScheduler runner stopped.")


if __name__ == "__main__":
    main()
