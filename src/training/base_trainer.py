"""
CPU-Optimized Base Causal LM Trainer.
Trains lightweight language models on domain text data without GPU dependencies.
"""

import math
from pathlib import Path
from typing import Optional, Dict, Any
import torch
from transformers import (
    AutoModelForCausalLM,
    Trainer,
    TrainingArguments,
    DataCollatorForLanguageModeling,
)
from config.settings import settings
from src.common.logger import get_logger
from src.training.dataset_builder import DatasetBuilder

logger = get_logger("webcreoling.training.base_trainer")


class BaseLLMTrainer:
    """Coordinates base model training on raw scraped domain text."""

    def __init__(
        self,
        model_name: str = settings.BASE_MODEL_NAME,
        output_dir: Optional[Path] = None,
        max_seq_length: int = settings.MAX_SEQ_LENGTH,
    ):
        self.model_name = model_name
        self.output_dir = output_dir or (settings.CHECKPOINTS_DIR / "base_model")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.max_seq_length = max_seq_length

        self.dataset_builder = DatasetBuilder(
            tokenizer_name=self.model_name,
            max_seq_length=self.max_seq_length,
        )
        self.tokenizer = self.dataset_builder.tokenizer

        # Set PyTorch CPU multi-threading
        if settings.USE_CPU_ONLY:
            torch.set_num_threads(settings.NUM_CPU_THREADS)
            logger.info(f"Configured CPU execution with {settings.NUM_CPU_THREADS} threads.")

    def load_model(self) -> AutoModelForCausalLM:
        """Load base pre-trained causal language model."""
        logger.info(f"Loading base model architecture: {self.model_name}")
        try:
            model = AutoModelForCausalLM.from_pretrained(self.model_name)
        except Exception as e:
            logger.warning(f"Could not load {self.model_name}: {e}. Falling back to 'distilgpt2'.")
            model = AutoModelForCausalLM.from_pretrained("distilgpt2")

        # Resize token embeddings if pad token was added
        model.resize_token_embeddings(len(self.tokenizer))
        return model

    def train(
        self,
        num_epochs: int = settings.NUM_TRAIN_EPOCHS,
        batch_size: int = settings.TRAIN_BATCH_SIZE,
        learning_rate: float = settings.LEARNING_RATE,
        articles_limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute CPU-optimized training loop on scraped news corpus.
        Saves trained model checkpoint to output directory.
        """
        logger.info("Building dataset from SQLite for base training...")
        raw_dataset = self.dataset_builder.build_dataset_from_db(limit=articles_limit)
        tokenized_dataset = self.dataset_builder.tokenize_dataset(raw_dataset, text_column="text")

        model = self.load_model()

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

        data_collator = DataCollatorForLanguageModeling(
            tokenizer=self.tokenizer,
            mlm=False,
        )

        trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=tokenized_dataset["train"],
            eval_dataset=tokenized_dataset["validation"],
            data_collator=data_collator,
        )

        logger.info("Starting base model domain training (CPU)...")
        train_result = trainer.train()

        # Evaluate perplexity
        eval_metrics = trainer.evaluate()
        eval_loss = eval_metrics.get("eval_loss", 0.0)
        perplexity = math.exp(eval_loss) if eval_loss < 20 else float("inf")
        eval_metrics["perplexity"] = perplexity

        logger.info(f"Training completed! Validation Loss: {eval_loss:.4f}, Perplexity: {perplexity:.2f}")

        # Save model and tokenizer checkpoint
        logger.info(f"Saving base model checkpoint to {self.output_dir}...")
        trainer.save_model(str(self.output_dir))
        self.tokenizer.save_pretrained(str(self.output_dir))

        summary = {
            "output_dir": str(self.output_dir),
            "train_loss": train_result.training_loss,
            "eval_loss": eval_loss,
            "perplexity": perplexity,
            "train_samples": len(tokenized_dataset["train"]),
            "epochs": num_epochs,
        }
        return summary
