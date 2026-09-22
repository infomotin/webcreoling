"""
One-Time Sequential Pipeline Orchestrator.
Executes the full pipeline sequentially:
URL Input -> Web Scraping -> SQLite Storage & Media -> Text Preprocessing -> Base Training -> Hybrid Fine-Tuning -> Evaluation -> Chat.
"""

import sys
from typing import Optional, List, Dict, Any
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from config.settings import settings
from src.common.logger import get_logger
from src.storage.database import init_db, get_db_session
from src.storage.repositories import ArticleRepository
from src.scraper.engine import ScraperEngine
from src.scraper.pipeline import ScrapingPipeline
from src.scraper.mock_bangla_portal import MockBanglaPortalServer
from src.training.base_trainer import BaseLLMTrainer
from src.training.llama_cpp_exporter import LlamaCppExporter
from src.finetuning.hybrid_trainer import HybridFineTuner
from src.finetuning.evaluator import MultiTaskEvaluator
from src.chat.interface import ChatPipeline

logger = get_logger("webcreoling.pipeline")
console = Console()


class EndToEndNewsPipeline:
    """Sequential runner that automates all stages from raw URLs to specialized AI models."""

    def __init__(self):
        self.scraper_engine = ScraperEngine()
        self.scraper_pipeline = ScrapingPipeline(engine=self.scraper_engine)

    def run_full_pipeline(
        self,
        site_keys: Optional[List[str]] = None,
        use_mock_server: bool = True,
        max_pages_per_category: int = 2,
        base_train_epochs: int = 1,
        finetune_epochs: int = 2,
        interactive_chat: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute the entire end-to-end pipeline in one sequential flow.
        """
        console.print(Panel.fit(
            "[bold cyan]WebCreoling End-to-End Bangla News AI Pipeline[/bold cyan]\n"
            "1. Database Initialization & FTS5 Indexing\n"
            "2. Web Scraping & Local Image Deduplication\n"
            "3. SQLite Persistence & Text Sanitization\n"
            "4. Base Causal LM Pretraining (CPU)\n"
            "5. Hybrid LoRA Fine-Tuning (4 Tasks)\n"
            "6. Model Evaluation (ROUGE, BLEU, F1, Accuracy)\n"
            "7. RAG & Task Verification",
            title="[bold yellow]Pipeline Execution Plan[/bold yellow]",
            border_style="yellow",
        ))

        mock_server = None
        if use_mock_server:
            console.print("\n[bold cyan]▶ Step 0: Starting Hermetic Mock Bangla Portal on http://127.0.0.1:8765[/bold cyan]")
            mock_server = MockBanglaPortalServer()
            mock_server.start()

        results = {}

        try:
            # ----------------------------------------------------
            # Step 1: Initialize Database & FTS5 Full-Text Index
            # ----------------------------------------------------
            console.print("\n[bold cyan]▶ Step 1: Initializing SQLite Database & FTS5 Full-Text Search...[/bold cyan]")
            init_db()

            # ----------------------------------------------------
            # Step 2: Web Scraping & Media Download
            # ----------------------------------------------------
            target_sites = site_keys or (["mock_bangla_portal"] if use_mock_server else ["prothom_alo", "daily_star_bangla", "bbc_bangla"])
            console.print(f"\n[bold cyan]▶ Step 2: Scraping News Articles from: {target_sites}...[/bold cyan]")

            total_scraped = 0
            for site in target_sites:
                try:
                    crawl_res = self.scraper_pipeline.run_site_crawl(
                        site_key=site,
                        max_pages_per_category=max_pages_per_category,
                        download_images=True,
                    )
                    total_scraped += crawl_res["articles_saved"]
                    console.print(f"  [green]✓[/green] [{site}] Saved {crawl_res['articles_saved']} articles, {crawl_res['images_downloaded']} images.")
                except Exception as e:
                    console.print(f"  [red]✗[/red] [{site}] Error during crawl: {e}")

            results["articles_scraped"] = total_scraped

            # Display Database Statistics
            with get_db_session() as session:
                repo = ArticleRepository(session)
                stats = repo.get_database_stats()
                results["db_stats"] = stats

            table = Table(title="Database Statistics After Ingestion", border_style="cyan")
            table.add_column("Metric", style="bold white")
            table.add_column("Value", style="green")
            table.add_row("Total Articles", str(stats["total_articles"]))
            table.add_row("Total Downloaded Images", str(stats["total_images"]))
            table.add_row("Categories", ", ".join(f"{k}: {v}" for k, v in stats["by_category"].items()))
            console.print(table)

            # ----------------------------------------------------
            # Step 3: Base Causal LM Training (CPU)
            # ----------------------------------------------------
            console.print(f"\n[bold cyan]▶ Step 3: Training Base Causal LM ({settings.BASE_MODEL_NAME}) on CPU...[/bold cyan]")
            base_trainer = BaseLLMTrainer(
                model_name=settings.BASE_MODEL_NAME,
                output_dir=settings.CHECKPOINTS_DIR / "base_model",
            )
            base_train_summary = base_trainer.train(
                num_epochs=base_train_epochs,
                batch_size=settings.TRAIN_BATCH_SIZE,
            )
            results["base_train"] = base_train_summary
            console.print(f"  [green]✓[/green] Base model trained! Eval Loss: {base_train_summary['eval_loss']:.4f}, Perplexity: {base_train_summary['perplexity']:.2f}")

            # ----------------------------------------------------
            # Step 4: Hybrid Multi-Task LoRA Fine-Tuning
            # ----------------------------------------------------
            console.print("\n[bold cyan]▶ Step 4: Hybrid LoRA Fine-Tuning across 4 Specialized Skills...[/bold cyan]")
            fine_tuner = HybridFineTuner(
                base_model_path=settings.CHECKPOINTS_DIR / "base_model",
                output_dir=settings.CHECKPOINTS_DIR / "final_specialized_model",
            )
            finetune_summary = fine_tuner.fine_tune(
                num_epochs=finetune_epochs,
                batch_size=settings.TRAIN_BATCH_SIZE,
            )
            results["finetune"] = finetune_summary
            console.print(f"  [green]✓[/green] Fine-tuning completed! Final Eval Loss: {finetune_summary['eval_loss']:.4f}")

            # Create llama.cpp GGUF manifest
            exporter = LlamaCppExporter(checkpoint_dir=settings.CHECKPOINTS_DIR / "final_specialized_model")
            manifest_path = exporter.create_llama_cpp_manifest()
            console.print(f"  [green]✓[/green] llama.cpp export manifest generated at {manifest_path}")

            # ----------------------------------------------------
            # Step 5: Comprehensive Model Evaluation
            # ----------------------------------------------------
            console.print("\n[bold cyan]▶ Step 5: Evaluating Specialized Model Performance...[/bold cyan]")
            evaluator = MultiTaskEvaluator(model_dir=settings.CHECKPOINTS_DIR / "final_specialized_model")
            eval_report = evaluator.run_full_evaluation()
            results["evaluation"] = eval_report

            eval_table = Table(title="Fine-Tuned Model Performance across 4 Skills", border_style="magenta")
            eval_table.add_column("Specialized Skill", style="bold white")
            eval_table.add_column("Primary Metrics", style="yellow")

            tasks = eval_report.get("tasks", {})
            cat = tasks.get("article_categorization", {})
            eval_table.add_row("1. Article Categorization", f"Accuracy: {cat.get('accuracy', 0.0) * 100:.1f}%")

            head = tasks.get("headline_generation", {})
            eval_table.add_row("2. Headline Generation", f"ROUGE-L: {head.get('rougeL', 0.0):.4f} | BLEU: {head.get('bleu', 0.0):.4f}")

            summ = tasks.get("content_summarization", {})
            eval_table.add_row("3. Content Summarization", f"ROUGE-1: {summ.get('rouge1', 0.0):.4f} | ROUGE-L: {summ.get('rougeL', 0.0):.4f}")

            ner = tasks.get("named_entity_recognition", {})
            eval_table.add_row("4. Named Entity Recognition (NER)", f"F1-Score: {ner.get('f1', 0.0):.4f} (P: {ner.get('precision', 0.0):.2f}, R: {ner.get('recall', 0.0):.2f})")

            console.print(eval_table)

            # ----------------------------------------------------
            # Step 6: Verification via Chat / Inference Pipeline
            # ----------------------------------------------------
            console.print("\n[bold cyan]▶ Step 6: Verifying RAG & Explicit Task Chat Pipeline...[/bold cyan]")
            chat = ChatPipeline(model_dir=settings.CHECKPOINTS_DIR / "final_specialized_model")

            # Test 1: RAG Q&A
            rag_test = chat.process_message("সংসদে কী কী বিষয় নিয়ে আলোচনা হয়েছে?")
            console.print(Panel(
                f"[bold blue]Query:[/bold blue] সংসদে কী কী বিষয় নিয়ে আলোচনা হয়েছে?\n"
                f"[bold green]Response:[/bold green] {rag_test['response']}\n"
                f"[bold yellow]Citations:[/bold yellow] {len(rag_test['citations'])} articles matched in SQLite FTS5",
                title="[bold]Test 1: Conversational RAG Q&A Verification[/bold]",
            ))

            # Test 2: Categorization
            cat_test = chat.process_message("categorize this article: মিরপুর শেরেবাংলা জাতীয় ক্রিকেট স্টেডিয়ামে বাংলাদেশ ৫ উইকেটে জয়ী হয়েছে।")
            console.print(Panel(
                f"[bold blue]Input:[/bold blue] categorize this article: মিরপুর শেরেবাংলা স্টেডিয়াম...\n"
                f"[bold green]Predicted Category:[/bold green] {cat_test['response']}",
                title="[bold]Test 2: Explicit Categorization Task[/bold]",
            ))

            # Test 3: Headline Generation
            head_test = chat.process_message("generate a headline for this: চলতি অর্থবছরে বাংলাদেশের তৈরি পোশাক ও চামড়াজাত পণ্য থেকে রেকর্ড পরিমাণ রপ্তানি আয় হয়েছে।")
            console.print(Panel(
                f"[bold blue]Input:[/bold blue] generate a headline for this: চলতি অর্থবছরে...\n"
                f"[bold green]Generated Headline:[/bold green] {head_test['response']}",
                title="[bold]Test 3: Explicit Headline Generation Task[/bold]",
            ))

            # Test 4: Summarization
            summ_test = chat.process_message("summarize this: জাতিসংঘ সাধারণ অধিবেশনে বিশ্বনেতারা জলবায়ু পরিবর্তনের ক্ষয়ক্ষতি কাটিয়ে উঠতে ক্ষতিগ্রস্ত দেশগুলোকে জরুরি সহায়তা প্রদানের প্রস্তাব উত্থাপিত করেছেন।")
            console.print(Panel(
                f"[bold blue]Input:[/bold blue] summarize this: জাতিসংঘ সাধারণ অধিবেশনে...\n"
                f"[bold green]Summary:[/bold green] {summ_test['response']}",
                title="[bold]Test 4: Explicit Summarization Task[/bold]",
            ))

            # Test 5: NER
            ner_test = chat.process_message("extract entities from this: ঢাকায় প্রধানমন্ত্রী ও স্পিকার জাতীয় সংসদে গুরুত্বপূর্ণ আলোচনায় অংশ নিয়েছেন।")
            console.print(Panel(
                f"[bold blue]Input:[/bold blue] extract entities from this: ঢাকায় প্রধানমন্ত্রী...\n"
                f"[bold green]Extracted Entities:[/bold green] {ner_test['response']}",
                title="[bold]Test 5: Explicit NER Task[/bold]",
            ))

            console.print("\n[bold green]✓ Entire End-to-End Pipeline Completed Successfully![/bold green]")

            if interactive_chat:
                chat.interactive_session()

        finally:
            if mock_server:
                mock_server.stop()
            self.scraper_engine.close()

        return results
