"""
Asynchronous Background Task Manager.
Executes and tracks long-running AI training, scraping, evaluation, and pipeline jobs without blocking HTTP requests.
"""

import uuid
import time
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional, Callable
from config.settings import settings
from src.common.logger import get_logger

logger = get_logger("webcreoling.automation.task_manager")


class AsyncTask:
    """Represents an active or finished asynchronous background execution."""

    def __init__(self, task_id: str, task_type: str, title: str, description: str = ""):
        self.task_id = task_id
        self.task_type = task_type
        self.title = title
        self.description = description
        self.status = "QUEUED"  # 'QUEUED', 'RUNNING', 'SUCCESS', 'FAILED'
        self.progress_pct = 0
        self.created_at = datetime.utcnow()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.log_lines: List[str] = []
        self.result_data: Dict[str, Any] = {}
        self.error_message: Optional[str] = None
        self._lock = threading.Lock()

    def add_log(self, text: str) -> None:
        """Add timestamped log entry."""
        with self._lock:
            ts = datetime.utcnow().strftime("%H:%M:%S")
            self.log_lines.append(f"[{ts}] {text}")
            if len(self.log_lines) > 200:
                self.log_lines = self.log_lines[-200:]

    def set_progress(self, pct: int, status_msg: Optional[str] = None) -> None:
        """Update percent completion and optional log message."""
        with self._lock:
            self.progress_pct = min(100, max(0, pct))
            if status_msg:
                self.add_log(status_msg)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize task state for JSON API."""
        with self._lock:
            elapsed = 0.0
            if self.started_at:
                end_time = self.completed_at or datetime.utcnow()
                elapsed = (end_time - self.started_at).total_seconds()

            return {
                "task_id": self.task_id,
                "task_type": self.task_type,
                "title": self.title,
                "description": self.description,
                "status": self.status,
                "progress_pct": self.progress_pct,
                "created_at": self.created_at.isoformat(),
                "started_at": self.started_at.isoformat() if self.started_at else None,
                "completed_at": self.completed_at.isoformat() if self.completed_at else None,
                "elapsed_seconds": round(elapsed, 1),
                "log_lines": list(self.log_lines),
                "result_data": self.result_data,
                "error_message": self.error_message,
            }


class AsyncTaskManager:
    """ThreadPool task manager coordinating long-running background tasks."""

    _instance: Optional["AsyncTaskManager"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AsyncTaskManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, max_workers: int = 4):
        if getattr(self, "_initialized", False):
            return

        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="AsyncTaskWorker")
        self.tasks: Dict[str, AsyncTask] = {}
        self._initialized = True

    def submit_task(
        self,
        task_type: str,
        title: str,
        worker_func: Callable[[AsyncTask], Dict[str, Any]],
        description: str = "",
    ) -> AsyncTask:
        """Submit a background job to the execution queue."""
        task_id = str(uuid.uuid4())[:8]
        task = AsyncTask(task_id=task_id, task_type=task_type, title=title, description=description)

        with self._lock:
            self.tasks[task_id] = task

        def _runner():
            task.started_at = datetime.utcnow()
            task.status = "RUNNING"
            task.add_log(f"Started job: {title}")
            logger.info(f"[Task {task_id}] Running: {title}")

            try:
                result = worker_func(task)
                task.status = "SUCCESS"
                task.progress_pct = 100
                task.result_data = result or {}
                task.add_log("Task completed successfully!")
                logger.info(f"[Task {task_id}] Completed successfully: {title}")
            except Exception as e:
                task.status = "FAILED"
                task.error_message = str(e)
                task.add_log(f"Task encountered error: {e}")
                logger.error(f"[Task {task_id}] Failed: {e}", exc_info=True)
            finally:
                task.completed_at = datetime.utcnow()

        self.executor.submit(_runner)
        return task

    def get_task(self, task_id: str) -> Optional[AsyncTask]:
        """Retrieve task by ID."""
        return self.tasks.get(task_id)

    def list_tasks(self, limit: int = 25) -> List[Dict[str, Any]]:
        """Return list of recent tasks sorted by creation timestamp."""
        sorted_tasks = sorted(self.tasks.values(), key=lambda t: t.created_at, reverse=True)
        return [t.to_dict() for t in sorted_tasks[:limit]]

    # --------------------------------------------------------------------------
    # Specialized Task Submissions
    # --------------------------------------------------------------------------
    def submit_crawl_task(self, site_key: str, max_pages: int = 2) -> AsyncTask:
        """Submit an asynchronous news portal crawl."""
        def _work(task: AsyncTask) -> Dict[str, Any]:
            from src.scraper.pipeline import ScrapingPipeline
            task.set_progress(10, f"Initializing scraper pipeline for '{site_key}'...")
            pipeline = ScrapingPipeline()
            task.set_progress(25, f"Crawling portal categories (max pages: {max_pages})...")
            res = pipeline.run_site_crawl(site_key=site_key, max_pages_per_category=max_pages, download_images=True)
            task.set_progress(90, "Scraping finished. Sealing database transactions...")
            return res

        return self.submit_task(
            task_type="CRAWL",
            title=f"Portal Crawl: {site_key}",
            description=f"Crawls up to {max_pages} pages per category on {site_key}.",
            worker_func=_work,
        )

    def submit_base_train_task(self, epochs: int = 1, batch_size: int = 2, limit: Optional[int] = None) -> AsyncTask:
        """Submit an asynchronous base LLM pre-training task."""
        def _work(task: AsyncTask) -> Dict[str, Any]:
            from src.training.base_trainer import BaseLLMTrainer
            task.set_progress(10, "Building dataset and tokenizing news articles from MySQL...")
            trainer = BaseLLMTrainer(model_name=settings.BASE_MODEL_NAME)
            task.set_progress(30, f"Executing {epochs} epoch(s) on CPU...")
            summary = trainer.train(num_epochs=epochs, batch_size=batch_size, articles_limit=limit)
            task.set_progress(95, "Saving trained model checkpoints and weights...")
            return summary

        return self.submit_task(
            task_type="BASE_TRAIN",
            title=f"Base LLM Training ({settings.BASE_MODEL_NAME})",
            description=f"Trains causal LM for {epochs} epoch(s) on local CPU.",
            worker_func=_work,
        )

    def submit_finetune_task(self, epochs: int = 2, batch_size: int = 2) -> AsyncTask:
        """Submit an asynchronous hybrid LoRA fine-tuning task."""
        def _work(task: AsyncTask) -> Dict[str, Any]:
            from src.finetuning.hybrid_trainer import HybridFineTuner
            from src.training.llama_cpp_exporter import LlamaCppExporter
            task.set_progress(10, "Setting up multi-task LoRA adapters for 4 skills...")
            tuner = HybridFineTuner()
            task.set_progress(30, f"Fine-tuning LoRA adapters across skills ({epochs} epochs)...")
            summary = tuner.fine_tune(num_epochs=epochs, batch_size=batch_size)
            task.set_progress(85, "Generating llama.cpp GGUF conversion manifest...")
            exporter = LlamaCppExporter()
            exporter.create_llama_cpp_manifest()
            task.set_progress(95, "LoRA weights saved successfully.")
            return summary

        return self.submit_task(
            task_type="FINETUNE",
            title="Hybrid LoRA Fine-Tuning (4 Skills)",
            description=f"Fine-tunes LoRA adapters for Categorization, Headlines, Summarization, NER.",
            worker_func=_work,
        )

    def submit_evaluation_task(self) -> AsyncTask:
        """Submit model evaluation across 4 benchmark tasks."""
        def _work(task: AsyncTask) -> Dict[str, Any]:
            from src.finetuning.evaluator import MultiTaskEvaluator
            task.set_progress(15, "Loading fine-tuned LoRA model checkpoint...")
            evaluator = MultiTaskEvaluator()
            task.set_progress(30, "Evaluating Categorization, ROUGE, BLEU, and NER F1...")
            report = evaluator.run_full_evaluation()
            task.set_progress(95, "Evaluation report generated.")
            return report

        return self.submit_task(
            task_type="EVALUATION",
            title="Multi-Task Model Evaluation",
            description="Evaluates fine-tuned model against test sets computing ROUGE, BLEU, and F1 scores.",
            worker_func=_work,
        )

    def submit_full_pipeline_task(
        self,
        site_keys: Optional[List[str]] = None,
        use_mock_server: bool = True,
        base_epochs: int = 1,
        finetune_epochs: int = 2,
    ) -> AsyncTask:
        """Submit the full end-to-end pipeline."""
        def _work(task: AsyncTask) -> Dict[str, Any]:
            from src.pipeline import EndToEndNewsPipeline
            task.set_progress(5, "Starting End-to-End News AI Pipeline...")
            pipeline_runner = EndToEndNewsPipeline()
            res = pipeline_runner.run_full_pipeline(
                site_keys=site_keys,
                use_mock_server=use_mock_server,
                base_train_epochs=base_epochs,
                finetune_epochs=finetune_epochs,
            )
            task.set_progress(100, "Full pipeline completed successfully!")
            return res

        return self.submit_task(
            task_type="FULL_PIPELINE",
            title="End-to-End News Pipeline",
            description="Runs complete ingestion -> training -> fine-tuning -> evaluation sequence.",
            worker_func=_work,
        )

    def submit_social_crawl_task(self, max_per_source: int = 3) -> AsyncTask:
        """Submit background YouTube and Social Media news ingestion task."""
        def _work(task: AsyncTask) -> Dict[str, Any]:
            from src.scraper.social_world_ingestion import YouTubePublicNewsIngester, FacebookPublicNewsIngester
            from src.storage.database import get_db_session
            from src.storage.repositories import ArticleRepository

            task.set_progress(15, "Connecting to public YouTube video news feeds (BBC, Jamuna, Somoy, Prothom Alo)...")
            yt_items = YouTubePublicNewsIngester.fetch_all_configured_channels(max_per_channel=max_per_source)
            task.set_progress(50, "Fetching public social news feeds and media briefs...")
            fb_items = FacebookPublicNewsIngester.fetch_public_social_briefs(limit=max_per_source)
            all_items = yt_items + fb_items

            task.set_progress(75, f"Storing {len(all_items)} social news items in MySQL...")
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

            task.set_progress(100, f"Social Ingestion Complete: Saved {saved} articles and media thumbnails.")
            return {"total_fetched": len(all_items), "total_saved": saved}

        return self.submit_task(
            task_type="SOCIAL_CRAWL",
            title="YouTube & Social News Ingestion",
            description=f"Ingests up to {max_per_source} public items per channel without API keys.",
            worker_func=_work,
        )

    def submit_world_crawl_task(self, max_per_source: int = 3) -> AsyncTask:
        """Submit background Worldwide multi-lingual news ingestion task."""
        def _work(task: AsyncTask) -> Dict[str, Any]:
            from src.scraper.social_world_ingestion import WorldNewsMultiLingualIngester
            from src.storage.database import get_db_session
            from src.storage.repositories import ArticleRepository

            task.set_progress(20, "Connecting to open Google News RSS feeds (Bangla, English, Hindi)...")
            world_items = WorldNewsMultiLingualIngester.fetch_all_world_feeds(max_per_feed=max_per_source)

            task.set_progress(60, f"Saving {len(world_items)} global news records into MySQL database...")
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

            task.set_progress(100, f"Worldwide Ingestion Complete: Saved {saved} global articles.")
            return {"total_fetched": len(world_items), "total_saved": saved}

        return self.submit_task(
            task_type="WORLD_CRAWL",
            title="Worldwide Multi-Lingual News Ingestion",
            description="Ingests global breaking headlines from Google News, Reuters, BBC, and Al Jazeera.",
            worker_func=_work,
        )

    def submit_ai_pilot_task(self, auto_publish_threshold: int = 75, max_per_source: int = 3) -> AsyncTask:
        """Submit an autonomous AI Pilot Brain evaluation and auto-publishing cycle."""
        def _work(task: AsyncTask) -> Dict[str, Any]:
            from src.automation.ai_pilot_brain import AIPilotBrain

            task.set_progress(15, "AI Pilot Brain: Ingesting public feeds across YouTube, Social, and Global News...")
            summary = AIPilotBrain.ingest_and_autopilot_cycle(
                include_youtube=True,
                include_world=True,
                include_social=True,
                auto_publish_threshold=auto_publish_threshold,
                max_per_source=max_per_source,
            )
            task.set_progress(
                100,
                f"AI Pilot Brain Finished: Ingested {summary['total_raw_ingested']} | Auto-Published {summary['auto_published']} | Review Queue {summary['review_queued']}.",
            )
            return summary

        return self.submit_task(
            task_type="AI_PILOT_AUTONOMOUS",
            title="AI Pilot Brain Autonomous Decision Cycle",
            description=f"Auto-translates, scores credibility, and auto-publishes news with score >= {auto_publish_threshold}%.",
            worker_func=_work,
        )


def get_task_manager() -> AsyncTaskManager:
    """Access global AsyncTaskManager singleton."""
    return AsyncTaskManager()
