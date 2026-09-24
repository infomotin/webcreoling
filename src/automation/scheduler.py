"""
Autonomous Periodic Background Scheduler for WebCreoling News Pipeline.
Handles automated crawler cycles, scheduled publishing releases, blockchain sealing, and security hygiene.
"""

import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable
from config.settings import settings
from src.common.logger import get_logger
from src.storage.database import get_db_session
from src.storage.repositories import (
    ArticleRepository,
    BlockchainLedgerRepository,
    SecurityRepository,
)

logger = get_logger("webcreoling.automation.scheduler")


class ScheduledJob:
    """Represents an automated recurring job definition."""

    def __init__(
        self,
        job_id: str,
        name: str,
        description: str,
        interval_seconds: int,
        target_func: Callable[[], str],
        enabled: bool = True,
    ):
        self.job_id = job_id
        self.name = name
        self.description = description
        self.interval_seconds = interval_seconds
        self.target_func = target_func
        self.enabled = enabled
        self.last_run: Optional[datetime] = None
        self.next_run: Optional[datetime] = datetime.utcnow() + timedelta(seconds=min(5, interval_seconds))
        self.run_count: int = 0
        self.error_count: int = 0
        self.last_status: str = "PENDING"
        self.last_message: str = "Initialized and awaiting first cycle."
        self.is_running: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize job state for UI and API reporting."""
        return {
            "job_id": self.job_id,
            "name": self.name,
            "description": self.description,
            "interval_seconds": self.interval_seconds,
            "enabled": self.enabled,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "run_count": self.run_count,
            "error_count": self.error_count,
            "last_status": self.last_status,
            "last_message": self.last_message,
            "is_running": self.is_running,
        }


class AutomationScheduler:
    """Background thread manager executing recurring news pipeline tasks."""

    _instance: Optional["AutomationScheduler"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AutomationScheduler, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        self.jobs: Dict[str, ScheduledJob] = {}
        self.is_active: bool = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._history_log: List[Dict[str, Any]] = []
        self._register_default_jobs()
        self._initialized = True

    def _register_default_jobs(self) -> None:
        """Register the core autonomous maintenance and ingestion jobs."""
        self.add_job(
            job_id="publish_scheduled",
            name="Scheduled News Auto-Publisher",
            description="Scans for pending articles whose scheduled release timestamp has arrived and publishes them to the frontpage.",
            interval_seconds=60,
            target_func=self._task_publish_scheduled,
            enabled=True,
        )

        self.add_job(
            job_id="blockchain_minting",
            name="Cryptographic Ledger Auto-Sealer",
            description="Mints immutable SHA-256 blockchain blocks for unsealed news articles to guarantee integrity and prevent tampering.",
            interval_seconds=120,
            target_func=self._task_mint_blockchain,
            enabled=True,
        )

        self.add_job(
            job_id="security_hygiene",
            name="WAF Security & IP Ban Pruner",
            description="Automatically unbans expired IP blacklist entries and archives resolved attack telemetry records.",
            interval_seconds=300,
            target_func=self._task_security_hygiene,
            enabled=True,
        )

        self.add_job(
            job_id="periodic_crawler",
            name="Automated Portal Ingestion Crawler",
            description="Polls configured portals (Prothom Alo, Daily Star, BBC Bangla) for fresh breaking articles and media.",
            interval_seconds=3600,  # 1 hour default
            target_func=self._task_periodic_crawl,
            enabled=True,
        )

    def add_job(
        self,
        job_id: str,
        name: str,
        description: str,
        interval_seconds: int,
        target_func: Callable[[], str],
        enabled: bool = True,
    ) -> None:
        """Register or update a scheduled recurring job."""
        self.jobs[job_id] = ScheduledJob(
            job_id=job_id,
            name=name,
            description=description,
            interval_seconds=interval_seconds,
            target_func=target_func,
            enabled=enabled,
        )

    def start(self) -> None:
        """Start the background scheduler thread."""
        with self._lock:
            if self.is_active and self._thread and self._thread.is_alive():
                logger.info("Automation scheduler is already running.")
                return

            self.is_active = True
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="WebCreoling-Scheduler")
            self._thread.start()
            logger.info("Automation background scheduler started successfully.")
            self._log_event("SCHEDULER_START", "Autonomous background scheduler service started.")

    def stop(self) -> None:
        """Stop the background scheduler thread."""
        with self._lock:
            if not self.is_active:
                return

            self.is_active = False
            self._stop_event.set()
            logger.info("Automation background scheduler stopping...")
            self._log_event("SCHEDULER_STOP", "Autonomous background scheduler stopped.")

    def trigger_job_now(self, job_id: str) -> Dict[str, Any]:
        """Trigger an immediate out-of-order execution of a scheduled job."""
        job = self.jobs.get(job_id)
        if not job:
            return {"status": "error", "message": f"Job '{job_id}' not found."}

        def _worker():
            self._execute_single_job(job)

        thread = threading.Thread(target=_worker, daemon=True, name=f"ManualTrigger-{job_id}")
        thread.start()
        return {"status": "started", "message": f"Job '{job.name}' triggered immediately in background."}

    def update_job_interval(self, job_id: str, interval_seconds: int) -> bool:
        """Update job interval in seconds."""
        job = self.jobs.get(job_id)
        if job:
            job.interval_seconds = max(10, interval_seconds)
            job.next_run = datetime.utcnow() + timedelta(seconds=job.interval_seconds)
            return True
        return False

    def toggle_job(self, job_id: str, enabled: bool) -> bool:
        """Enable or disable a specific job."""
        job = self.jobs.get(job_id)
        if job:
            job.enabled = enabled
            if enabled:
                job.next_run = datetime.utcnow() + timedelta(seconds=5)
            return True
        return False

    def get_status(self) -> Dict[str, Any]:
        """Retrieve complete status report across all jobs and history."""
        return {
            "is_active": self.is_active,
            "jobs_count": len(self.jobs),
            "jobs": [job.to_dict() for job in self.jobs.values()],
            "history_log": self._history_log[-25:],
        }

    def _run_loop(self) -> None:
        """Internal scheduler event loop."""
        while not self._stop_event.is_set():
            now = datetime.utcnow()
            for job in self.jobs.values():
                if job.enabled and not job.is_running:
                    if job.next_run and now >= job.next_run:
                        # Dispatch job execution in a thread
                        threading.Thread(
                            target=self._execute_single_job,
                            args=(job,),
                            daemon=True,
                            name=f"JobWorker-{job.job_id}",
                        ).start()

            # Sleep briefly before next tick
            self._stop_event.wait(timeout=2.0)

    def _execute_single_job(self, job: ScheduledJob) -> None:
        """Execute a single job safely and update metrics."""
        job.is_running = True
        job.last_run = datetime.utcnow()
        start_time = time.time()
        logger.info(f"[Automation] Starting job: {job.name} ({job.job_id})")

        try:
            message = job.target_func()
            elapsed = time.time() - start_time
            job.last_status = "SUCCESS"
            job.last_message = f"{message} (took {elapsed:.2f}s)"
            job.run_count += 1
            self._log_event("JOB_SUCCESS", f"{job.name}: {message} ({elapsed:.2f}s)")
            logger.info(f"[Automation] Finished job: {job.name} - {message}")
        except Exception as e:
            elapsed = time.time() - start_time
            job.last_status = "FAILED"
            job.last_message = f"Error: {e} (took {elapsed:.2f}s)"
            job.error_count += 1
            self._log_event("JOB_ERROR", f"{job.name} failed: {e}")
            logger.error(f"[Automation] Error in job {job.name}: {e}", exc_info=True)
        finally:
            job.is_running = False
            job.next_run = datetime.utcnow() + timedelta(seconds=job.interval_seconds)

    def _log_event(self, event_type: str, message: str) -> None:
        """Append event to in-memory audit trail."""
        self._history_log.append({
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
            "event_type": event_type,
            "message": message,
        })
        if len(self._history_log) > 100:
            self._history_log = self._history_log[-100:]

    # --------------------------------------------------------------------------
    # Job Implementation Methods
    # --------------------------------------------------------------------------
    def _task_publish_scheduled(self) -> str:
        """Scan and publish queued articles."""
        with get_db_session() as session:
            repo = ArticleRepository(session)
            count = repo.process_scheduled_publishing()
            if count > 0:
                return f"Published {count} scheduled news article(s)."
            return "No pending scheduled articles reached release time."

    def _task_mint_blockchain(self) -> str:
        """Mint cryptographic blockchain blocks for unsealed articles."""
        with get_db_session() as session:
            ledger_repo = BlockchainLedgerRepository(session)
            count = ledger_repo.mint_all_unmined_articles()
            if count > 0:
                return f"Minted {count} cryptographic blockchain block(s)."
            return "All articles are cryptographically sealed in the ledger."

    def _task_security_hygiene(self) -> str:
        """Prune expired IP blacklists."""
        with get_db_session() as session:
            sec_repo = SecurityRepository(session)
            unbanned = sec_repo.prune_expired_blocks()
            if unbanned > 0:
                return f"Unbanned {unbanned} expired IP blacklist rule(s)."
            return "Security firewall rules verified and clean."

    def _task_periodic_crawl(self) -> str:
        """Autonomous portal crawler."""
        from src.scraper.pipeline import ScrapingPipeline
        pipeline = ScrapingPipeline()
        sites = pipeline.engine.sites_config.get("sites", {})
        if not sites:
            return "No portals configured in sites_config.yaml."

        # Pick first 2 portals per cycle to be polite
        site_keys = list(sites.keys())[:2]
        total_articles = 0
        total_images = 0

        for site_key in site_keys:
            try:
                res = pipeline.run_site_crawl(site_key=site_key, max_pages_per_category=1, download_images=True)
                total_articles += res.get("articles_saved", 0)
                total_images += res.get("images_downloaded", 0)
            except Exception as e:
                logger.warning(f"Periodic crawl error for '{site_key}': {e}")

        return f"Autonomous crawl finished: Saved {total_articles} articles, {total_images} images."


def get_scheduler() -> AutomationScheduler:
    """Access global AutomationScheduler singleton."""
    return AutomationScheduler()
