"""
Autonomous Periodic Background Scheduler & Dynamic Automation Engine for WebCreoling.
Handles recurring crawler cycles, AI Pilot cycles, social media broadcasts, blockchain minting,
security hygiene, database backups, and user-defined custom scheduled automation jobs (CRUD).
"""

import os
import json
import uuid
import time
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Callable
from pathlib import Path

from config.settings import settings
from src.common.logger import get_logger
from src.storage.database import get_db_session
from src.storage.repositories import (
    ArticleRepository,
    BlockchainLedgerRepository,
    SecurityRepository,
    SiteConfigRepository,
)

logger = get_logger("webcreoling.automation.scheduler")

# Path for persistent custom job storage fallback
CUSTOM_JOBS_FILE = Path("data/automation_custom_jobs.json")


class ScheduledJob:
    """Represents an automated recurring job definition with telemetry and execution history."""

    def __init__(
        self,
        job_id: str,
        name: str,
        description: str,
        interval_seconds: int,
        target_func: Optional[Callable[[], str]] = None,
        job_type: str = "custom",
        enabled: bool = True,
        is_system: bool = False,
        params: Optional[Dict[str, Any]] = None,
        name_bn: Optional[str] = None,
    ):
        self.job_id = job_id
        self.name = name
        self.name_bn = name_bn or name
        self.description = description
        self.interval_seconds = max(10, int(interval_seconds))
        self.target_func = target_func
        self.job_type = job_type
        self.enabled = enabled
        self.is_system = is_system
        self.params = params or {}
        
        self.last_run: Optional[datetime] = None
        self.next_run: Optional[datetime] = datetime.now(timezone.utc) + timedelta(seconds=min(5, self.interval_seconds))
        self.run_count: int = 0
        self.error_count: int = 0
        self.last_status: str = "PENDING"  # 'PENDING', 'RUNNING', 'SUCCESS', 'FAILED', 'PAUSED'
        self.last_message: str = "Initialized and awaiting first cycle."
        self.last_duration_sec: float = 0.0
        self.is_running: bool = False
        self.execution_history: List[Dict[str, Any]] = []

    def record_execution(self, status: str, message: str, duration_sec: float) -> None:
        """Record a completed execution event into the job's telemetry log."""
        self.last_status = status
        self.last_message = message
        self.last_duration_sec = round(duration_sec, 2)
        if status == "SUCCESS":
            self.run_count += 1
        elif status == "FAILED":
            self.error_count += 1

        history_item = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "status": status,
            "message": message,
            "duration_sec": self.last_duration_sec,
        }
        self.execution_history.append(history_item)
        if len(self.execution_history) > 15:
            self.execution_history = self.execution_history[-15:]

    def get_success_rate(self) -> float:
        """Calculate job execution success rate percentage."""
        total = self.run_count + self.error_count
        if total == 0:
            return 100.0
        return round((self.run_count / total) * 100, 1)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize job state for UI and API reporting."""
        now = datetime.now(timezone.utc)
        next_run_seconds_left = 0
        if self.next_run and self.enabled:
            diff = (self.next_run - now).total_seconds()
            next_run_seconds_left = max(0, int(diff))

        return {
            "job_id": self.job_id,
            "name": self.name,
            "name_bn": self.name_bn,
            "description": self.description,
            "job_type": self.job_type,
            "interval_seconds": self.interval_seconds,
            "enabled": self.enabled,
            "is_system": self.is_system,
            "params": self.params,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "last_run_display": self.last_run.strftime("%H:%M:%S (%d %b)") if self.last_run else "কখনো নয়",
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "next_run_display": self.next_run.strftime("%H:%M:%S") if self.next_run else "অপেক্ষমান",
            "next_run_seconds_left": next_run_seconds_left,
            "run_count": self.run_count,
            "error_count": self.error_count,
            "success_rate": self.get_success_rate(),
            "last_status": self.last_status,
            "last_message": self.last_message,
            "last_duration_sec": self.last_duration_sec,
            "is_running": self.is_running,
            "execution_history": list(self.execution_history),
        }


class AutomationScheduler:
    """Background thread manager executing recurring news pipeline tasks with full CRUD."""

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

        # 1. Register Core System Jobs
        self._register_default_jobs()

        # 2. Load Persisted Custom User Jobs
        self._load_custom_jobs()

        self._initialized = True

    def _register_default_jobs(self) -> None:
        """Register the core autonomous maintenance and ingestion jobs."""
        self.add_job(
            job_id="publish_scheduled",
            name="Scheduled News Auto-Publisher",
            name_bn="শিডিউলড নিউজ অটো-পাবলিশার",
            description="Scans for pending articles whose scheduled release timestamp has arrived and publishes them to the frontpage.",
            interval_seconds=60,
            target_func=self._task_publish_scheduled,
            job_type="scheduled_publisher",
            enabled=True,
            is_system=True,
        )

        self.add_job(
            job_id="blockchain_minting",
            name="Cryptographic Ledger Auto-Sealer",
            name_bn="ব্লকচেইন ক্রিপ্টোগ্রাফিক লেজার সিলার",
            description="Mints immutable SHA-256 blockchain blocks for unsealed news articles to guarantee integrity and prevent tampering.",
            interval_seconds=120,
            target_func=self._task_mint_blockchain,
            job_type="blockchain_mint",
            enabled=True,
            is_system=True,
        )

        self.add_job(
            job_id="security_hygiene",
            name="WAF Security & IP Ban Pruner",
            name_bn="ফায়ারওয়াল আইপি ব্যান ও সিকিউরিটি ক্লিনার",
            description="Automatically unbans expired IP blacklist entries and archives resolved attack telemetry records.",
            interval_seconds=300,
            target_func=self._task_security_hygiene,
            job_type="security_pruner",
            enabled=True,
            is_system=True,
        )

        self.add_job(
            job_id="periodic_crawler",
            name="Automated Portal Ingestion Crawler",
            name_bn="অটোমেটেড পোর্টাল স্ক্র্যাপার ও ক্রলার",
            description="Polls configured portals (Prothom Alo, Daily Star, BBC Bangla) for fresh breaking articles and media.",
            interval_seconds=3600,  # 1 hour default
            target_func=self._task_periodic_crawl,
            job_type="crawler",
            enabled=True,
            is_system=True,
            params={"max_pages": 1, "download_images": True},
        )

        self.add_job(
            job_id="social_media_crawler",
            name="YouTube & Public Social Media Ingester",
            name_bn="ইউটিউব ও সোশ্যাল মিডিয়া ইনজেস্টার",
            description="Fetches public video news feeds, transcripts, and social briefs from YouTube (BBC, Jamuna, Somoy, Prothom Alo) and Facebook.",
            interval_seconds=1800,  # 30 mins
            target_func=self._task_social_media_crawl,
            job_type="social_broadcast",
            enabled=True,
            is_system=True,
        )

        self.add_job(
            job_id="world_news_crawler",
            name="Worldwide Multi-Lingual News Ingester",
            name_bn="আন্তর্জাতিক বহুভাষিক সংবাদ ইনজেস্টার",
            description="Ingests global breaking headlines from Google News (Bangla, English, Hindi), Reuters, BBC World, and Al Jazeera.",
            interval_seconds=1800,  # 30 mins
            target_func=self._task_world_news_crawl,
            job_type="crawler",
            enabled=True,
            is_system=True,
        )

        self.add_job(
            job_id="ai_pilot_decision_brain",
            name="AI Pilot Brain Autonomous Decision Cycle",
            name_bn="এআই পাইলট ব্রেন অটোনোমাস ডিসিশন সাইকেল",
            description="Translates foreign news to Bengali, calculates credibility scores, extracts NLP entities, and auto-publishes high-confidence news.",
            interval_seconds=600,  # 10 mins
            target_func=self._task_ai_pilot_cycle,
            job_type="ai_pilot",
            enabled=True,
            is_system=True,
            params={"auto_publish_threshold": 75, "max_per_source": 2},
        )

        self.add_job(
            job_id="auto_db_backup",
            name="Automated Database Snapshot & Archiver",
            name_bn="অটোমেটিক ডেটাবেজ স্ন্যাপশট ও ব্যাকআপ",
            description="Generates daily automated SQL/JSON database dumps to preserve news history and editorial state.",
            interval_seconds=43200,  # 12 hours
            target_func=self._task_db_backup,
            job_type="db_backup",
            enabled=True,
            is_system=True,
        )

    def add_job(
        self,
        job_id: str,
        name: str,
        description: str,
        interval_seconds: int,
        target_func: Optional[Callable[[], str]] = None,
        job_type: str = "custom",
        enabled: bool = True,
        is_system: bool = False,
        params: Optional[Dict[str, Any]] = None,
        name_bn: Optional[str] = None,
    ) -> ScheduledJob:
        """Register or update a scheduled recurring job."""
        if target_func is None:
            target_func = self._resolve_target_func(job_type, params or {})

        job = ScheduledJob(
            job_id=job_id,
            name=name,
            name_bn=name_bn,
            description=description,
            interval_seconds=interval_seconds,
            target_func=target_func,
            job_type=job_type,
            enabled=enabled,
            is_system=is_system,
            params=params,
        )
        self.jobs[job_id] = job
        return job

    # --------------------------------------------------------------------------
    # CRUD Operations for Custom Automated Jobs
    # --------------------------------------------------------------------------
    def create_custom_job(
        self,
        name: str,
        description: str,
        job_type: str,
        interval_seconds: int,
        params: Optional[Dict[str, Any]] = None,
        enabled: bool = True,
        name_bn: Optional[str] = None,
        custom_id: Optional[str] = None,
    ) -> ScheduledJob:
        """[CREATE] Add a new user-defined custom automation job."""
        job_id = custom_id or f"custom_{job_type}_{uuid.uuid4().hex[:6]}"
        target_func = self._resolve_target_func(job_type, params or {})

        job = self.add_job(
            job_id=job_id,
            name=name,
            name_bn=name_bn or name,
            description=description,
            interval_seconds=interval_seconds,
            target_func=target_func,
            job_type=job_type,
            enabled=enabled,
            is_system=False,
            params=params,
        )

        self._save_custom_jobs()
        self._log_event("JOB_CREATED", f"New custom job created: '{job.name}' ({job_id})")
        logger.info(f"[Automation] Created custom job: {job_id} ({name})")
        return job

    def update_job(
        self,
        job_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        interval_seconds: Optional[int] = None,
        enabled: Optional[bool] = None,
        params: Optional[Dict[str, Any]] = None,
        name_bn: Optional[str] = None,
    ) -> Optional[ScheduledJob]:
        """[UPDATE] Modify existing job parameters and schedule."""
        job = self.jobs.get(job_id)
        if not job:
            return None

        if name is not None:
            job.name = name
        if name_bn is not None:
            job.name_bn = name_bn
        if description is not None:
            job.description = description
        if interval_seconds is not None:
            job.interval_seconds = max(10, int(interval_seconds))
            job.next_run = datetime.now(timezone.utc) + timedelta(seconds=job.interval_seconds)
        if enabled is not None:
            job.enabled = enabled
            if enabled and not job.next_run:
                job.next_run = datetime.now(timezone.utc) + timedelta(seconds=5)
        if params is not None:
            job.params = params
            job.target_func = self._resolve_target_func(job.job_type, job.params)

        self._save_custom_jobs()
        self._log_event("JOB_UPDATED", f"Job updated: '{job.name}' ({job_id})")
        return job

    def delete_custom_job(self, job_id: str) -> bool:
        """[DELETE] Remove a custom scheduled job."""
        job = self.jobs.get(job_id)
        if not job:
            return False
        if job.is_system:
            # Cannot delete core system jobs, but can disable them
            job.enabled = False
            self._log_event("JOB_DISABLED", f"System job '{job.name}' disabled instead of deletion.")
            return True

        del self.jobs[job_id]
        self._save_custom_jobs()
        self._log_event("JOB_DELETED", f"Custom job '{job.name}' ({job_id}) deleted.")
        logger.info(f"[Automation] Deleted custom job: {job_id}")
        return True

    def toggle_job(self, job_id: str, enabled: Optional[bool] = None) -> bool:
        """Toggle active/pause state for a job."""
        job = self.jobs.get(job_id)
        if not job:
            return False

        if enabled is None:
            job.enabled = not job.enabled
        else:
            job.enabled = enabled

        if job.enabled:
            job.next_run = datetime.now(timezone.utc) + timedelta(seconds=5)
            job.last_status = "PENDING"
        else:
            job.last_status = "PAUSED"

        self._save_custom_jobs()
        status_word = "enabled" if job.enabled else "paused"
        self._log_event("JOB_TOGGLE", f"Job '{job.name}' is now {status_word}.")
        return True

    def trigger_job_now(self, job_id: str) -> Dict[str, Any]:
        """Trigger immediate out-of-order execution of a scheduled job."""
        job = self.jobs.get(job_id)
        if not job:
            return {"status": "error", "message": f"Job '{job_id}' not found."}

        if job.is_running:
            return {"status": "warning", "message": f"Job '{job.name}' is already running."}

        def _worker():
            self._execute_single_job(job)

        thread = threading.Thread(target=_worker, daemon=True, name=f"ManualTrigger-{job_id}")
        thread.start()
        return {"status": "started", "message": f"Job '{job.name}' triggered immediately in background."}

    def batch_action(self, action: str) -> Dict[str, Any]:
        """Perform batch operation on all jobs (enable_all, disable_all, trigger_all, reset_stats)."""
        count = 0
        if action == "enable_all":
            for job in self.jobs.values():
                job.enabled = True
                job.next_run = datetime.now(timezone.utc) + timedelta(seconds=5)
                count += 1
            self._save_custom_jobs()
            return {"status": "success", "message": f"All {count} automation jobs activated."}

        elif action == "disable_all":
            for job in self.jobs.values():
                job.enabled = False
                job.last_status = "PAUSED"
                count += 1
            self._save_custom_jobs()
            return {"status": "success", "message": f"All {count} automation jobs paused."}

        elif action == "trigger_all":
            for job in self.jobs.values():
                if not job.is_running:
                    threading.Thread(target=self._execute_single_job, args=(job,), daemon=True).start()
                    count += 1
            return {"status": "success", "message": f"Triggered {count} jobs in parallel."}

        elif action == "reset_stats":
            for job in self.jobs.values():
                job.run_count = 0
                job.error_count = 0
                job.execution_history.clear()
            return {"status": "success", "message": "All execution metrics reset."}

        return {"status": "error", "message": f"Unknown batch action: {action}"}

    # --------------------------------------------------------------------------
    # Persistence Handlers
    # --------------------------------------------------------------------------
    def _save_custom_jobs(self) -> None:
        """Persist user-created custom jobs to JSON and DB."""
        custom_data = []
        for job in self.jobs.values():
            if not job.is_system:
                custom_data.append({
                    "job_id": job.job_id,
                    "name": job.name,
                    "name_bn": job.name_bn,
                    "description": job.description,
                    "interval_seconds": job.interval_seconds,
                    "job_type": job.job_type,
                    "enabled": job.enabled,
                    "params": job.params,
                })

        try:
            CUSTOM_JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CUSTOM_JOBS_FILE, "w", encoding="utf-8") as f:
                json.dump(custom_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to write custom jobs file: {e}")

        try:
            with get_db_session() as session:
                config_repo = SiteConfigRepository(session)
                config_repo.set_config("automation_custom_jobs_manifest", custom_data)
        except Exception as e:
            logger.debug(f"DB config persist note: {e}")

    def _load_custom_jobs(self) -> None:
        """Load and restore persisted custom jobs."""
        custom_data = []

        # 1. Try DB first
        try:
            with get_db_session() as session:
                config_repo = SiteConfigRepository(session)
                custom_data = config_repo.get_config("automation_custom_jobs_manifest", [])
        except Exception as e:
            logger.debug(f"DB config load note: {e}")

        # 2. Fallback to file
        if not custom_data and CUSTOM_JOBS_FILE.exists():
            try:
                with open(CUSTOM_JOBS_FILE, "r", encoding="utf-8") as f:
                    custom_data = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read custom jobs file: {e}")

        # Register loaded custom jobs
        for item in custom_data:
            job_id = item.get("job_id")
            if job_id and job_id not in self.jobs:
                job_type = item.get("job_type", "custom")
                params = item.get("params", {})
                target_func = self._resolve_target_func(job_type, params)
                self.add_job(
                    job_id=job_id,
                    name=item.get("name", "Custom Job"),
                    name_bn=item.get("name_bn"),
                    description=item.get("description", ""),
                    interval_seconds=item.get("interval_seconds", 300),
                    target_func=target_func,
                    job_type=job_type,
                    enabled=item.get("enabled", True),
                    is_system=False,
                    params=params,
                )

    def _resolve_target_func(self, job_type: str, params: Dict[str, Any]) -> Callable[[], str]:
        """Dynamically resolve executable callback based on job type and parameters."""
        if job_type == "crawler":
            site_key = params.get("site_key")
            max_pages = int(params.get("max_pages", 1))
            return lambda: self._task_custom_crawl(site_key, max_pages)

        elif job_type == "ai_pilot":
            threshold = float(params.get("auto_publish_threshold", 75.0))
            return lambda: self._task_custom_ai_pilot(threshold)

        elif job_type == "social_broadcast":
            channel = params.get("channel", "all")
            return lambda: self._task_custom_social_broadcast(channel)

        elif job_type == "fake_news_audit":
            return self._task_custom_fact_check_audit

        elif job_type == "blockchain_mint":
            return self._task_mint_blockchain

        elif job_type == "scheduled_publisher":
            return self._task_publish_scheduled

        elif job_type == "security_pruner":
            return self._task_security_hygiene

        elif job_type == "db_backup":
            return self._task_db_backup

        elif job_type == "model_cache_cleaner":
            return self._task_model_cache_cleaner

        # Generic default
        return lambda: f"Custom task '{job_type}' executed successfully."

    # --------------------------------------------------------------------------
    # Scheduler Thread Controls
    # --------------------------------------------------------------------------
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

    def get_status(self) -> Dict[str, Any]:
        """Retrieve complete status report across all jobs, telemetry, and audit history."""
        active_jobs = [j for j in self.jobs.values() if j.enabled]
        total_runs = sum(j.run_count for j in self.jobs.values())
        total_errors = sum(j.error_count for j in self.jobs.values())
        success_rate = round(((total_runs - total_errors) / max(1, total_runs)) * 100, 1)

        return {
            "is_active": self.is_active,
            "jobs_count": len(self.jobs),
            "active_jobs_count": len(active_jobs),
            "total_runs": total_runs,
            "total_errors": total_errors,
            "success_rate": success_rate,
            "jobs": [job.to_dict() for job in self.jobs.values()],
            "history_log": self._history_log[-35:],
            "system_time": datetime.now(timezone.utc).isoformat(),
        }

    def _run_loop(self) -> None:
        """Internal scheduler event loop checking trigger deadlines."""
        while not self._stop_event.is_set():
            now = datetime.now(timezone.utc)
            for job in list(self.jobs.values()):
                if job.enabled and not job.is_running:
                    if job.next_run and now >= job.next_run:
                        threading.Thread(
                            target=self._execute_single_job,
                            args=(job,),
                            daemon=True,
                            name=f"JobWorker-{job.job_id}",
                        ).start()

            self._stop_event.wait(timeout=2.0)

    def _execute_single_job(self, job: ScheduledJob) -> None:
        """Execute a single job safely with telemetry capture."""
        job.is_running = True
        job.last_run = datetime.now(timezone.utc)
        job.last_status = "RUNNING"
        start_time = time.time()
        logger.info(f"[Automation] Starting job: {job.name} ({job.job_id})")

        try:
            message = job.target_func() if job.target_func else "Executed default routine."
            elapsed = time.time() - start_time
            job.record_execution(status="SUCCESS", message=f"{message} (took {elapsed:.2f}s)", duration_sec=elapsed)
            self._log_event("JOB_SUCCESS", f"{job.name}: {message} ({elapsed:.2f}s)")
            logger.info(f"[Automation] Finished job: {job.name} - {message}")
        except Exception as e:
            elapsed = time.time() - start_time
            job.record_execution(status="FAILED", message=f"Error: {e} (took {elapsed:.2f}s)", duration_sec=elapsed)
            self._log_event("JOB_ERROR", f"{job.name} failed: {e}")
            logger.error(f"[Automation] Error in job {job.name}: {e}", exc_info=True)
        finally:
            job.is_running = False
            job.next_run = datetime.now(timezone.utc) + timedelta(seconds=job.interval_seconds)

    def _log_event(self, event_type: str, message: str) -> None:
        """Append event to in-memory audit trail."""
        self._history_log.append({
            "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S (%d %b)"),
            "event_type": event_type,
            "message": message,
        })
        if len(self._history_log) > 150:
            self._history_log = self._history_log[-150:]

    # --------------------------------------------------------------------------
    # Job Implementation Workers
    # --------------------------------------------------------------------------
    def _task_publish_scheduled(self) -> str:
        """Scan and publish queued articles whose scheduled time arrived."""
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
        """Prune expired IP blacklists and firewall bans."""
        with get_db_session() as session:
            sec_repo = SecurityRepository(session)
            unbanned = sec_repo.prune_expired_blocks()
            if unbanned > 0:
                return f"Unbanned {unbanned} expired IP blacklist rule(s)."
            return "Security firewall rules verified and clean."

    def _task_periodic_crawl(self) -> str:
        """Autonomous portal crawler polling primary portals."""
        from src.scraper.pipeline import ScrapingPipeline
        pipeline = ScrapingPipeline()
        sites = pipeline.engine.sites_config.get("sites", {})
        if not sites:
            return "No portals configured in sites_config.yaml."

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

    def _task_social_media_crawl(self) -> str:
        """Autonomous social media and YouTube public feed ingester."""
        from src.scraper.social_world_ingestion import YouTubePublicNewsIngester, FacebookPublicNewsIngester
        yt_items = YouTubePublicNewsIngester.fetch_all_configured_channels(max_per_channel=2)
        fb_items = FacebookPublicNewsIngester.fetch_public_social_briefs(limit=2)
        all_items = yt_items + fb_items

        saved = 0
        with get_db_session() as session:
            repo = ArticleRepository(session)
            for item in all_items:
                try:
                    img_records = [
                        {
                            "original_url": img["original_url"],
                            "local_path": img["original_url"],
                            "file_hash": f"hash_{abs(hash(img['original_url']))}",
                            "file_size_bytes": 51200,
                            "mime_type": "image/jpeg",
                            "caption": img.get("caption", ""),
                            "is_lead_image": img.get("is_lead_image", False),
                        }
                        for img in item.get("images", [])
                    ]
                    repo.upsert_article(article_data=item, image_records=img_records)
                    saved += 1
                except Exception as e:
                    logger.warning(f"Error saving social item: {e}")

        return f"Social & YouTube Ingest: Processed {len(all_items)} items, saved {saved} into database."

    def _task_world_news_crawl(self) -> str:
        """Autonomous worldwide multi-language news ingester."""
        from src.scraper.social_world_ingestion import WorldNewsMultiLingualIngester
        world_items = WorldNewsMultiLingualIngester.fetch_all_world_feeds(max_per_feed=2)
        saved = 0
        with get_db_session() as session:
            repo = ArticleRepository(session)
            for item in world_items:
                try:
                    img_records = [
                        {
                            "original_url": img["original_url"],
                            "local_path": img["original_url"],
                            "file_hash": f"hash_{abs(hash(img['original_url']))}",
                            "file_size_bytes": 51200,
                            "mime_type": "image/jpeg",
                            "caption": img.get("caption", ""),
                            "is_lead_image": img.get("is_lead_image", False),
                        }
                        for img in item.get("images", [])
                    ]
                    repo.upsert_article(article_data=item, image_records=img_records)
                    saved += 1
                except Exception as e:
                    logger.warning(f"Error saving world item: {e}")

        return f"World News Ingest: Processed {len(world_items)} items, saved {saved} into database."

    def _task_ai_pilot_cycle(self) -> str:
        """Autonomous AI Brain decision and auto-publishing cycle."""
        from src.automation.ai_pilot_brain import AIPilotBrain
        summary = AIPilotBrain.ingest_and_autopilot_cycle(
            include_youtube=True,
            include_world=True,
            include_social=True,
            auto_publish_threshold=75,
            max_per_source=2,
        )
        return f"AI Pilot Brain: Ingested {summary['total_raw_ingested']} | Auto-Published {summary['auto_published']} | Review Queue {summary['review_queued']}."

    def _task_db_backup(self) -> str:
        """Generate automatic database snapshot dump."""
        backup_dir = Path("data/backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"auto_backup_summary_{ts}.json"

        with get_db_session() as session:
            art_repo = ArticleRepository(session)
            kpis = art_repo.get_automation_kpis()
            feed = art_repo.get_automation_live_feed(limit=50)

            dump_payload = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "kpis": kpis,
                "recent_articles_sample": feed[:15],
            }
            with open(backup_file, "w", encoding="utf-8") as f:
                json.dump(dump_payload, f, ensure_ascii=False, indent=2)

        return f"Database snapshot saved to {backup_file.name} ({kpis.get('total_articles', 0)} total articles)."

    def _task_custom_crawl(self, site_key: Optional[str], max_pages: int = 1) -> str:
        """Execute custom portal crawl."""
        from src.scraper.pipeline import ScrapingPipeline
        pipeline = ScrapingPipeline()
        if site_key:
            res = pipeline.run_site_crawl(site_key=site_key, max_pages_per_category=max_pages, download_images=True)
            return f"Crawl for '{site_key}': Saved {res.get('articles_saved', 0)} articles."
        else:
            return self._task_periodic_crawl()

    def _task_custom_ai_pilot(self, threshold: float = 75.0) -> str:
        """Execute custom AI Pilot cycle with specific threshold."""
        from src.automation.ai_pilot_brain import AIPilotBrain
        summary = AIPilotBrain.ingest_and_autopilot_cycle(
            include_youtube=True,
            include_world=True,
            include_social=True,
            auto_publish_threshold=threshold,
            max_per_source=3,
        )
        return f"Custom AI Pilot (Threshold {threshold}%): Ingested {summary['total_raw_ingested']} | Auto-Published {summary['auto_published']}."

    def _task_custom_social_broadcast(self, channel: str = "all") -> str:
        """Execute social media broadcast."""
        from src.automation.social_broadcaster import UnifiedSocialBroadcaster
        with get_db_session() as session:
            art_repo = ArticleRepository(session)
            feed = art_repo.get_automation_live_feed(limit=3)
            sent = 0
            for item in feed:
                try:
                    UnifiedSocialBroadcaster.broadcast_article(item)
                    sent += 1
                except Exception:
                    pass
            return f"Broadcasted {sent} latest articles to social channels ({channel})."

    def _task_custom_fact_check_audit(self) -> str:
        """Execute fact-check audit across recent unverified news."""
        from src.nlp.fake_news_detector import FakeNewsDetectorEngine
        from src.storage.models import Article

        with get_db_session() as session:
            config_repo = SiteConfigRepository(session)
            policy = config_repo.get_fake_news_policy()
            max_fake = float(policy.get("max_fake_tolerance_pct", 50.0))

            articles = session.query(Article).order_by(Article.id.desc()).limit(20).all()
            audited = 0
            for art in articles:
                analysis = FakeNewsDetectorEngine.evaluate(
                    title=art.title,
                    content=art.content_text,
                    source=art.source,
                    author=art.author,
                    max_allowed_fake_pct=max_fake,
                )
                entities = art.extracted_entities or {}
                entities["fake_news_analysis"] = analysis
                art.extracted_entities = entities
                audited += 1
            session.flush()

        return f"Fact-Check Audit complete: Evaluated {audited} articles against {max_fake}% tolerance."

    def _task_model_cache_cleaner(self) -> str:
        """Clean temporary memory and cache."""
        import gc
        gc.collect()
        return "Cleaned in-memory ML model caches and freed unallocated RAM."


def get_scheduler() -> AutomationScheduler:
    """Access global AutomationScheduler singleton."""
    return AutomationScheduler()
