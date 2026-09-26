"""Background task layer (job functions executed by the scheduler).

The application's built-in APScheduler-style thread scheduler
(`src.automation.scheduler.AutomationScheduler`) executes these functions on
configurable intervals. `apscheduler_runner.py` provides an optional standalone
APScheduler entrypoint for deployments that prefer it (see README — the
built-in scheduler is the default for the 4-8 week MVP; migrate to Celery for
multi-node scale).
"""

from src.tasks.jobs import (  # noqa: F401
    approval_sweep_task,
    multi_source_scrape_task,
    fact_check_reaudit_task,
)
