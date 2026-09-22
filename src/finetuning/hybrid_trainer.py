"""
Hybrid Multi-Task Fine-Tuning Trainer using LoRA (PEFT).
Trains task-specific adapters on top of a single base model for Categorization, Headline Gen, Summarization, and NER.
"""

from pathlib import Path
from typing import Optional, Dict, Any, List
import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
    DataCollatorForLanguageModeling,
)
from peft import (
    LoraConfig,
    get_peft_model,
    TaskType,
    PeftModel,
)
from config.settings import settings
from src.common.logger import get_logger
from src.storage.database import get_db_session
from src.storage.repositories import ArticleRepository
from src.finetuning.tasks import SpecializedTaskManager

logger = get_logger("webcreoling.finetuning.hybrid_trainer")


class HybridFineTuner:
    """Trains a single base model with hybrid LoRA adapters across all 4 news skills."""

    def __init__(
        self,
        base_model_path: Optional[Path] = None,
        output_dir: Optional[Path] = None,
        r: int = settings.LORA_R,
        lora_alpha: int = settings.LORA_ALPHA,
        lora_dropout: float = settings.LORA_DROPOUT,
    ):
        self.base_model_path = str(base_model_path or (settings.CHECKPOINTS_DIR / "base_model"))
        self.output_dir = output_dir or (settings.CHECKPOINTS_DIR / "final_specialized_model")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.r = r
        self.lora_alpha = lora_alpha
        self.lora_dropout = lora_dropout

        self.tokenizer = self._load_tokenizer()

    def _load_tokenizer(self) -> AutoTokenizer:
        """Load tokenizer from base checkpoint or model name."""
        try:
            tokenizer = AutoTokenizer.from_pretrained(self.base_model_path)
        except Exception:
            tokenizer = AutoTokenizer.from_pretrained(settings.BASE_MODEL_NAME)

        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token or "<|endoftext|>"
            tokenizer.pad_token_id = tokenizer.eos_token_id

        return tokenizer

    def load_peft_model(self) -> PeftModel:
        """Load base causal LM and wrap with LoRA multi-task adapter."""
        logger.info(f"Loading base model for LoRA fine-tuning from {self.base_model_path}...")
        try:
            base_model = AutoModelForCausalLM.from_pretrained(self.base_model_path)
        except Exception as e:
            logger.warning(f"Base model checkpoint not found at {self.base_model_path}: {e}. Loading '{settings.BASE_MODEL_NAME}'.")
            base_model = AutoModelForCausalLM.from_pretrained(settings.BASE_MODEL_NAME)

        base_model.resize_token_embeddings(len(self.tokenizer))

        # Determine target modules depending on architecture
        target_modules = ["c_attn", "c_proj"]
        if hasattr(base_model, "config") and hasattr(base_model.config, "model_type"):
            mtype = base_model.config.model_type.lower()
            if "llama" in mtype or "qwen" in mtype or "smollm" in mtype:
                target_modules = ["q_proj", "k_proj", "v_proj", "o_proj"]

        lora_config = LoraConfig(
            task_type=TaskType.CAUSAL_LM,
            r=self.r,
            lora_alpha=self.lora_alpha,
            lora_dropout=self.lora_dropout,
            bias="none",
            target_modules=target_modules,
        )

        peft_model = get_peft_model(base_model, lora_config)
        peft_model.print_trainable_parameters()
        return peft_model

    def fine_tune(
        self,
        num_epochs: int = 3,
        batch_size: int = settings.TRAIN_BATCH_SIZE,
        learning_rate: float = 3e-4,
        articles_limit: Optional[int] = None,
        selected_tasks: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Train hybrid LoRA adapter on combined or task-specific dataset.
        Saves final specialized model and adapters.
        """
        logger.info(f"Extracting articles from SQLite for fine-tuning on tasks: {selected_tasks or 'ALL'}...")
        with get_db_session() as session:
            repo = ArticleRepository(session)
            articles = repo.get_training_dataset(limit=articles_limit)

        if not articles:
            # Fallback to mock articles
            from src.scraper.mock_bangla_portal import MOCK_ARTICLES
            from src.storage.models import Article
            articles = [
                Article(
                    id=i + 1,
                    url=f"http://example.com/{a['id']}",
                    source="mock_news",
                    title=a["title"],
                    author=a["author"],
                    category=a["category"],
                    content_text=a["content"],
                    summary=a["summary"],
                    extracted_entities=a.get("entities", {}),
                )
                for i, a in enumerate(MOCK_ARTICLES)
            ]

        # Build Task-Specific or Multi-Task Dataset
        multi_task_ds = SpecializedTaskManager.build_multi_task_dataset(articles, selected_tasks=selected_tasks)

        # Tokenize
        tokenizer = self.tokenizer
        max_len = settings.MAX_SEQ_LENGTH

        def _tokenize(batch):
            tokens = tokenizer(
                batch["text"],
                truncation=True,
                max_length=max_len,
                padding="max_length",
                return_tensors=None,
            )
            tokens["labels"] = [
                [(t if t != tokenizer.pad_token_id else -100) for t in seq]
                for seq in tokens["input_ids"]
            ]
            return tokens

        tokenized_ds = multi_task_ds.map(
            _tokenize,
            batched=True,
            remove_columns=multi_task_ds["train"].column_names,
            desc="Tokenizing multi-task dataset",
        )

        model = self.load_peft_model()

        training_args = TrainingArguments(
            output_dir=str(self.output_dir / "runs"),
            num_train_epochs=num_epochs,
            per_device_train_batch_size=batch_size,
            per_device_eval_batch_size=batch_size,
            gradient_accumulation_steps=settings.GRADIENT_ACCUMULATION_STEPS,
            learning_rate=learning_rate,
            weight_decay=settings.WEIGHT_DECAY,
            warmup_steps=2,
            logging_steps=5,
            eval_strategy="epoch",
            save_strategy="epoch",
            save_total_limit=1,
            seed=settings.SEED,
            use_cpu=True,
            report_to="none",
            dataloader_num_workers=0,
        )

        trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=tokenized_ds["train"],
            eval_dataset=tokenized_ds["validation"],
            data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False),
        )

        logger.info("Executing Hybrid LoRA Fine-Tuning across all 4 tasks (CPU)...")
        train_result = trainer.train()
        eval_metrics = trainer.evaluate()

        # Save specialized model checkpoint and adapter
        logger.info(f"Saving final specialized model and LoRA weights to {self.output_dir}...")
        model.save_pretrained(str(self.output_dir))
        self.tokenizer.save_pretrained(str(self.output_dir))

        summary = {
            "output_dir": str(self.output_dir),
            "train_loss": train_result.training_loss,
            "eval_loss": eval_metrics.get("eval_loss", 0.0),
            "total_samples": len(tokenized_ds["train"]) + len(tokenized_ds["validation"]),
            "epochs": num_epochs,
            "tasks_covered": selected_tasks or ["categorization", "headline_generation", "summarization", "ner"],
        }
        return summary
