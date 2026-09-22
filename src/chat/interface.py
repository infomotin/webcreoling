"""
Hybrid Chat & Task Interface.
Integrates RAG Conversational Q&A over SQLite and Specialized Task Execution
(Categorization, Headline Generation, Summarization, and Named Entity Recognition).
"""

import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
import torch
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel
from config.settings import settings
from src.common.logger import get_logger
from src.chat.rag_engine import RAGEngine
from src.chat.task_handlers import IntentClassifier
from src.chat.audit_logger import ChatAuditLogger

logger = get_logger("webcreoling.chat.interface")
console = Console()


class ChatPipeline:
    """Production chat pipeline supporting conversational RAG Q&A and explicit task execution."""

    def __init__(
        self,
        model_dir: Optional[Path] = None,
        base_model_name: str = settings.BASE_MODEL_NAME,
    ):
        self.model_dir = model_dir or (settings.CHECKPOINTS_DIR / "final_specialized_model")
        self.base_model_name = base_model_name
        self.rag_engine = RAGEngine(top_k=settings.RAG_TOP_K)
        self.audit_logger = ChatAuditLogger()
        self.model, self.tokenizer = self._load_inference_model()

    def _load_inference_model(self):
        """Load tokenizer and fine-tuned model or fallback base model."""
        logger.info("Initializing inference model for chat...")
        try:
            tokenizer = AutoTokenizer.from_pretrained(str(self.model_dir))
        except Exception:
            tokenizer = AutoTokenizer.from_pretrained(self.base_model_name)

        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token or "<|endoftext|>"
            tokenizer.pad_token_id = tokenizer.eos_token_id

        try:
            if (self.model_dir / "adapter_config.json").exists():
                base_model = AutoModelForCausalLM.from_pretrained(self.base_model_name)
                base_model.resize_token_embeddings(len(tokenizer))
                model = PeftModel.from_pretrained(base_model, str(self.model_dir))
                logger.info(f"Loaded fine-tuned LoRA model from {self.model_dir}")
            elif (self.model_dir / "model.safetensors").exists() or (self.model_dir / "pytorch_model.bin").exists():
                model = AutoModelForCausalLM.from_pretrained(str(self.model_dir))
                logger.info(f"Loaded specialized model from {self.model_dir}")
            else:
                base_model_dir = settings.CHECKPOINTS_DIR / "base_model"
                if base_model_dir.exists():
                    model = AutoModelForCausalLM.from_pretrained(str(base_model_dir))
                else:
                    model = AutoModelForCausalLM.from_pretrained(self.base_model_name)
        except Exception as e:
            logger.warning(f"Falling back to default base model: {e}")
            model = AutoModelForCausalLM.from_pretrained(self.base_model_name)

        model.resize_token_embeddings(len(tokenizer))
        model.eval()
        return model, tokenizer

    def generate(self, prompt: str, max_new_tokens: int = 120, temperature: float = 0.7) -> str:
        """Generate model response on CPU."""
        inputs = self.tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=0.9,
                do_sample=temperature > 0.0,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )
        output_tokens = outputs[0][inputs["input_ids"].shape[1]:]
        decoded = self.tokenizer.decode(output_tokens, skip_special_tokens=True)
        # Strip trailing endoftext or stop tags
        return decoded.split("<|endoftext|>")[0].strip()

    def process_message(self, user_input: str) -> Dict[str, Any]:
        """
        Process a user input, determine intent (RAG Q&A vs Explicit Task),
        generate the response, log the interaction, and return formatted payload.
        """
        start_time = time.time()
        intent, payload = IntentClassifier.parse_intent(user_input)

        retrieved_articles = []
        citations = []

        if intent == "rag_qa":
            # 1. Conversational Q&A with RAG retrieval
            retrieved_articles = self.rag_engine.search_relevant_articles(payload, top_k=settings.RAG_TOP_K)
            prompt = self.rag_engine.build_rag_prompt(payload, retrieved_articles)
            raw_response = self.generate(prompt, max_new_tokens=150, temperature=0.6)

            # Build citations
            for art in retrieved_articles:
                citations.append({
                    "id": art.get("id"),
                    "title": art.get("title"),
                    "source": art.get("source"),
                    "published_at": art.get("published_at"),
                    "url": art.get("url"),
                    "image_paths": art.get("images", []),
                })

            final_text = raw_response
            if not final_text and retrieved_articles:
                # Fallback clean synthesis if generative model produces short token
                top_art = retrieved_articles[0]
                final_text = f"প্রাপ্ত তথ্যানুযায়ী: {top_art['title']}। {top_art.get('content_text', '')[:250]}..."

        else:
            # 2. Explicit Task Execution
            prompt = IntentClassifier.build_task_prompt(intent, payload)
            raw_response = self.generate(prompt, max_new_tokens=100, temperature=0.1)  # Low temp for deterministic tasks
            final_text = raw_response.split("\n\n")[0].strip()

            # Rule fallback guarantee if lightweight model output is too brief
            if not final_text or len(final_text) < 2:
                if intent == "categorize":
                    final_text = "জাতীয় / সাধারণ সংবাদ"
                elif intent == "headline":
                    final_text = payload[:50] + "..."
                elif intent == "summarize":
                    final_text = payload[:180] + "..."
                elif intent == "ner":
                    from src.finetuning.tasks import SpecializedTaskManager
                    import json
                    final_text = json.dumps(SpecializedTaskManager.heuristic_extract_entities(payload), ensure_ascii=False)

        latency = time.time() - start_time
        retrieved_ids = [a.get("id") for a in retrieved_articles]

        # Audit logging
        self.audit_logger.log_interaction(
            mode=intent,
            user_input=user_input,
            response_text=final_text,
            retrieved_article_ids=retrieved_ids,
            latency_seconds=latency,
        )

        # Build rich related posts list
        related_posts = []
        for art in retrieved_articles:
            related_posts.append({
                "id": art.get("id"),
                "title": art.get("title"),
                "source": art.get("source"),
                "category": art.get("category", "general"),
                "published_at": art.get("published_at"),
                "url": art.get("url"),
                "snippet": art.get("snippet", ""),
                "lead_image": art.get("lead_image"),
                "image_paths": art.get("images", []),
            })

        return {
            "intent": intent,
            "user_input": user_input,
            "response": final_text,
            "citations": citations,
            "related_posts": related_posts,
            "latency_seconds": round(latency, 3),
        }

    def interactive_session(self) -> None:
        """Run rich interactive CLI chat loop."""
        console.print(Panel.fit(
            "[bold cyan]WebCreoling Bangla News AI Assistant[/bold cyan]\n"
            "[green]• Conversational RAG Q&A:[/green] Ask questions about news (e.g. 'সংসদে কী আলোচনা হয়েছে?')\n"
            "[yellow]• Explicit Tasks:[/yellow]\n"
            "   1. 'categorize this article: <text>'\n"
            "   2. 'generate a headline for this: <text>'\n"
            "   3. 'summarize this: <text>'\n"
            "   4. 'extract entities from this: <text>'\n"
            "[dim]Type 'exit' or 'quit' to close.[/dim]",
            title="[bold]Chat & News Agent[/bold]",
            border_style="cyan",
        ))

        while True:
            try:
                user_msg = console.input("\n[bold green]User > [/bold green]").strip()
                if not user_msg:
                    continue
                if user_msg.lower() in ["exit", "quit", "q"]:
                    console.print("[dim]Exiting chat. Goodbye![/dim]")
                    break

                with console.status("[cyan]Processing and reasoning...[/cyan]"):
                    result = self.process_message(user_msg)

                # Render Response Panel
                intent = result["intent"]
                response = result["response"]
                citations = result["citations"]
                latency = result["latency_seconds"]

                intent_badge = f"[bold magenta]Task: {intent.upper()}[/bold magenta]" if intent != "rag_qa" else "[bold blue]RAG Q&A[/bold blue]"
                console.print(Panel(
                    f"{intent_badge}\n\n[bold white]{response}[/bold white]",
                    title="[bold green]Assistant Response[/bold green]",
                    subtitle=f"[dim]Latency: {latency}s[/dim]",
                    border_style="green",
                ))

                # Display Citations if available
                if citations:
                    console.print("[bold yellow]📰 Sources & Media Citations:[/bold yellow]")
                    for i, cit in enumerate(citations, 1):
                        img_str = f" | [cyan]Local Image:[/cyan] {cit['image_paths'][0]}" if cit.get("image_paths") else ""
                        console.print(f"  [dim]{i}.[/dim] [bold]{cit['title']}[/bold] ({cit['source']}, {cit['published_at']}){img_str}")

            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]Session terminated.[/dim]")
                break
            except Exception as e:
                console.print(f"[bold red]Error:[/bold red] {e}")
                logger.error(f"Chat error: {e}", exc_info=True)
