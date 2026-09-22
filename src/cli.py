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


if __name__ == "__main__":
    app()


