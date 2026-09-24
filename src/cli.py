"""
Command-Line Interface for WebCreoling News Scraping & AI Pipeline.
Built with Typer and Rich.
"""

import sys
from pathlib import Path
from typing import Optional, List
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from config.settings import settings
from src.storage.database import init_db, get_db_session
from src.storage.repositories import ArticleRepository
from src.scraper.pipeline import ScrapingPipeline
from src.scraper.engine import ScraperEngine
from src.scraper.mock_bangla_portal import MockBanglaPortalServer
from src.training.base_trainer import BaseLLMTrainer
from src.finetuning.hybrid_trainer import HybridFineTuner
from src.finetuning.evaluator import MultiTaskEvaluator
from src.chat.interface import ChatPipeline
from src.pipeline import EndToEndNewsPipeline

app = typer.Typer(
    name="webcreoling",
    help="End-to-End Bangla News Web Scraping, SQLite Storage, CPU LLM Training & RAG Chat Pipeline",
    add_completion=False,
)
console = Console()


@app.command()
def setup_db():
    """Initialize SQLite database tables and FTS5 full-text search index."""
    init_db()
    console.print("[bold green]✓ Database and FTS5 search virtual tables initialized successfully.[/bold green]")


@app.command()
def db_stats():
    """Display article counts, category breakdowns, and media storage statistics."""
    with get_db_session() as session:
        repo = ArticleRepository(session)
        stats = repo.get_database_stats()

    table = Table(title="SQLite Database Overview", border_style="cyan")
    table.add_column("Category / Metric", style="bold white")
    table.add_column("Count", style="green")

    table.add_row("Total Scraped Articles", str(stats["total_articles"]))
    table.add_row("Total Downloaded Images", str(stats["total_images"]))
    table.add_section()

    for source, count in stats["by_source"].items():
        table.add_row(f"Source: {source}", str(count))
    table.add_section()

    for cat, count in stats["by_category"].items():
        table.add_row(f"Category: {cat}", str(count))
    table.add_section()

    for status, count in stats["by_status"].items():
        table.add_row(f"Scrape Status: {status}", str(count))

    console.print(table)


@app.command()
def search_db(query: str = typer.Argument(..., help="Search terms in Bangla or English"), top_k: int = 5):
    """Search articles in SQLite database using FTS5 full-text search."""
    with get_db_session() as session:
        repo = ArticleRepository(session)
        results = repo.search_fts(query, top_k=top_k)

    if not results:
        console.print(f"[yellow]No articles matched query: '{query}'[/yellow]")
        return

    console.print(f"[bold green]Found {len(results)} matching articles for '{query}':[/bold green]\n")
    for i, res in enumerate(results, 1):
        console.print(Panel(
            f"[bold cyan]{res['title']}[/bold cyan]\n"
            f"[dim]Source: {res['source']} | Date: {res['published_at']} | Category: {res['category']}[/dim]\n\n"
            f"{res['content_text'][:250]}...\n\n"
            f"[dim]URL: {res['url']}[/dim]",
            title=f"Result #{i}",
        ))


@app.command()
def scrape_url(
    url: str = typer.Argument(..., help="Full article URL to scrape"),
    site_key: Optional[str] = typer.Option(None, help="Site key in sites_config.yaml"),
    category: Optional[str] = typer.Option(None, help="Article category override"),
):
    """Scrape a single article with exponential retry backoff and store in SQLite."""
    pipeline = ScrapingPipeline()
    with get_db_session() as session:
        article = pipeline.process_and_save_article(
            session=session,
            article_url=url,
            site_key=site_key,
            category=category,
            download_images=True,
        )
        if article:
            console.print(f"[bold green]✓ Article saved successfully![/bold green] (ID: {article.id})")
            console.print(f"Title: [bold]{article.title}[/bold]")
            console.print(f"Author: {article.author} | Published: {article.published_at}")
            console.print(f"Images Downloaded: {len(article.images)}")
        else:
            console.print("[bold red]Failed to scrape article.[/bold red]")


@app.command()
def scrape_site(
    site_key: str = typer.Argument(..., help="Portal key (e.g. 'prothom_alo', 'daily_star_bangla', 'bbc_bangla')"),
    max_pages: int = typer.Option(2, help="Max pagination depth per category"),
):
    """Crawl a portal across all configured categories and download images."""
    pipeline = ScrapingPipeline()
    console.print(f"[bold cyan]Starting crawl for portal '{site_key}'...[/bold cyan]")
    res = pipeline.run_site_crawl(site_key=site_key, max_pages_per_category=max_pages)
    console.print(f"[bold green]✓ Crawl complete![/bold green] Saved {res['articles_saved']} articles and {res['images_downloaded']} images.")


@app.command()
def train_base(
    epochs: int = typer.Option(1, help="Number of training epochs"),
    batch_size: int = typer.Option(2, help="Batch size per CPU worker"),
    limit: Optional[int] = typer.Option(None, help="Max articles to train on"),
):
    """Train base Causal LM on domain text data (CPU-optimized)."""
    trainer = BaseLLMTrainer()
    summary = trainer.train(num_epochs=epochs, batch_size=batch_size, articles_limit=limit)
    console.print(f"[bold green]✓ Base model trained and saved to {summary['output_dir']}[/bold green]")


@app.command()
def finetune(
    epochs: int = typer.Option(2, help="Number of LoRA fine-tuning epochs"),
    batch_size: int = typer.Option(2, help="Batch size per CPU worker"),
):
    """Fine-tune base model with hybrid LoRA adapters across 4 specialized skills."""
    tuner = HybridFineTuner()
    summary = tuner.fine_tune(num_epochs=epochs, batch_size=batch_size)
    console.print(f"[bold green]✓ Specialized LoRA model saved to {summary['output_dir']}[/bold green]")


@app.command()
def evaluate():
    """Evaluate fine-tuned model across Categorization, Headline Gen, Summarization, and NER."""
    evaluator = MultiTaskEvaluator()
    report = evaluator.run_full_evaluation()
    console.print("[bold green]✓ Evaluation completed![/bold green]")


@app.command()
def chat():
    """Start interactive terminal chat session with RAG Q&A and explicit task commands."""
    chat_engine = ChatPipeline()
    chat_engine.interactive_session()


@app.command()
def serve_mock(port: int = typer.Option(8765, help="Port to bind mock server")):
    """Start hermetic mock Bangla news portal server for local offline testing."""
    console.print(f"[bold cyan]Starting Mock Bangla News Portal on http://127.0.0.1:{port}...[/bold cyan]")
    server = MockBanglaPortalServer(port=port)
    server.start()
    console.print("[green]Mock server is running. Press Ctrl+C to stop.[/green]")
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
        console.print("\n[dim]Mock server stopped.[/dim]")


@app.command()
def run_pipeline(
    use_mock: bool = typer.Option(True, help="Use hermetic mock server for fast reproducible run"),
    interactive: bool = typer.Option(False, help="Launch interactive chat after pipeline finishes"),
):
    """Run complete end-to-end pipeline: Scrape -> Store -> Train -> Finetune -> Eval -> Verify."""
    runner = EndToEndNewsPipeline()
    runner.run_full_pipeline(use_mock_server=use_mock, interactive_chat=interactive)


@app.command()
def serve_web(
    host: str = typer.Option("127.0.0.1", help="Host address to bind"),
    port: int = typer.Option(8080, help="Port to run Flask web application"),
    debug: bool = typer.Option(False, help="Enable Flask debug mode"),
):
    """Launch the WebCreoling Flask Web Dashboard with RBAC Authentication."""
    from src.web.app import create_app
    console.print(f"[bold cyan]Starting WebCreoling Flask Web Dashboard on http://{host}:{port}[/bold cyan]")
    console.print("[dim]Pre-seeded Roles: admin / editor / analyst / viewer (Password: <username>123)[/dim]")
    flask_app = create_app()
    flask_app.run(host=host, port=port, debug=debug)


@app.command()
def run_automation():
    """Run autonomous background scheduler daemon in standalone CLI mode."""
    from src.automation.scheduler import get_scheduler
    import time
    scheduler = get_scheduler()
    scheduler.start()
    console.print("[bold green]✓ Autonomous background scheduler started.[/bold green]")
    console.print("[cyan]Active Recurring Jobs:[/cyan]")
    for job in scheduler.jobs.values():
        console.print(f"  • [bold]{job.name}[/bold] (every {job.interval_seconds}s) - {job.description}")
    console.print("\n[dim]Press Ctrl+C to terminate scheduler daemon...[/dim]")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        scheduler.stop()
        console.print("[yellow]Scheduler daemon stopped.[/yellow]")


@app.command()
def mint_blockchain():
    """Mint tamper-proof SHA-256 blockchain ledger blocks for unsealed articles."""
    from src.storage.repositories import BlockchainLedgerRepository
    with get_db_session() as session:
        repo = BlockchainLedgerRepository(session)
        count = repo.mint_all_unmined_articles()
        integrity = repo.verify_chain_integrity()

    if count > 0:
        console.print(f"[bold green]✓ Successfully minted {count} blockchain block(s)![/bold green]")
    else:
        console.print("[green]All news articles are already sealed in blockchain ledger.[/green]")

    is_valid = integrity.get("chain_valid", integrity.get("is_valid", False))
    if is_valid:
        console.print(f"[bold cyan]✓ Chain Integrity: 100% VALID (Total Blocks: {integrity.get('total_blocks')})[/bold cyan]")
    else:
        console.print(f"[bold red]⚠ Chain Integrity Warning: {integrity.get('message', integrity.get('error'))}[/bold red]")


@app.command()
def publish_scheduled():
    """Publish pending articles whose scheduled release time has arrived."""
    with get_db_session() as session:
        repo = ArticleRepository(session)
        count = repo.process_scheduled_publishing()
    if count > 0:
        console.print(f"[bold green]✓ Published {count} scheduled news article(s) to frontpage![/bold green]")
    else:
        console.print("[cyan]No scheduled articles reached release time.[/cyan]")


@app.command()
def export_dataset(
    output_path: str = typer.Option("data/export_news.jsonl", help="Target output file (.jsonl or .csv)"),
    status: str = typer.Option("completed", help="Filter articles by status (e.g. 'completed')"),
):
    """Export cleaned Bangla news dataset for LLM training."""
    import json
    import csv
    with get_db_session() as session:
        repo = ArticleRepository(session)
        articles = repo.get_all(status=status, limit=100000)
        articles_data = [
            {
                "id": a.id,
                "title": a.title,
                "content": a.content_text,
                "category": a.category,
                "author": a.author,
                "published_at": str(a.published_at),
                "source": a.source,
                "url": a.url,
            }
            for a in articles
        ]

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    if output_path.endswith(".csv"):
        with open(out_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "title", "content_text", "category", "author", "published_at", "source", "url"])
            for a in articles_data:
                writer.writerow([a["id"], a["title"], a["content"], a["category"], a["author"], a["published_at"], a["source"], a["url"]])
    else:
        with open(out_file, "w", encoding="utf-8") as f:
            for a in articles_data:
                f.write(json.dumps(a, ensure_ascii=False) + "\n")

    console.print(f"[bold green]✓ Exported {len(articles_data)} articles to {output_path}[/bold green]")


@app.command()
def full_system_check():
    """Run comprehensive health diagnostic for MySQL, storage, AI models, and blockchain."""
    from src.storage.repositories import (
        ArticleRepository,
        UserRepository,
        BlockchainLedgerRepository,
        SecurityRepository,
    )
    console.print(Panel("[bold cyan]WebCreoling Enterprise System Diagnostics[/bold cyan]", border_style="cyan"))

    # 1. Database Connection & Stats
    try:
        with get_db_session() as session:
            art_repo = ArticleRepository(session)
            stats = art_repo.get_database_stats()
            user_repo = UserRepository(session)
            user_count = len(user_repo.list_all_users())
            sec_repo = SecurityRepository(session)
            sec_stats = sec_repo.get_security_stats()
            ledger_repo = BlockchainLedgerRepository(session)
            integrity = ledger_repo.verify_chain_integrity()

        console.print(f"[green]✓ Database Connection (MySQL): CONNECTED ({settings.DB_NAME} on {settings.DB_HOST}:{settings.DB_PORT})[/green]")
        console.print(f"  • Total Articles: [bold]{stats['total_articles']}[/bold]")
        console.print(f"  • Total Images: [bold]{stats['total_images']}[/bold]")
        console.print(f"  • Total Users: [bold]{user_count}[/bold]")
        console.print(f"  • WAF Security Rules Active: [bold]{sec_stats.get('total_rules', 0)}[/bold]")
        is_valid = integrity.get("chain_valid", integrity.get("is_valid", False))
        console.print(f"  • Blockchain Ledger: [bold]{integrity.get('total_blocks', 0)} blocks[/bold] (Valid: {is_valid})")
    except Exception as e:
        console.print(f"[bold red]✗ Database Error: {e}[/bold red]")

    # 2. Storage Directories
    dirs = [settings.DATA_DIR, settings.DB_DIR, settings.MODELS_DIR, settings.IMAGES_DIR, settings.LOGS_DIR]
    all_dirs_ok = True
    for d in dirs:
        if not d.exists():
            all_dirs_ok = False
            console.print(f"[yellow]⚠ Directory missing: {d}[/yellow]")
    if all_dirs_ok:
        console.print("[green]✓ All runtime directories present and accessible.[/green]")

    console.print("\n[bold green]✓ System diagnostics completed successfully.[/bold green]")


if __name__ == "__main__":
    app()


