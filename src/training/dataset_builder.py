"""
Dataset Builder for Hugging Face Transformers.
Loads raw news text from SQLite, applies normalization, splits into Train/Val/Test, and tokenizes.
"""

from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datasets import Dataset, DatasetDict
from transformers import AutoTokenizer, PreTrainedTokenizer
from config.settings import settings
from src.common.logger import get_logger
from src.storage.database import get_db_session
from src.storage.repositories import ArticleRepository
from src.training.preprocessor import TextPreprocessor

logger = get_logger("webcreoling.training.dataset_builder")


class DatasetBuilder:
    """Constructs train, validation, and test datasets from SQLite records."""

    def __init__(
        self,
        tokenizer_name: str = settings.BASE_MODEL_NAME,
        max_seq_length: int = settings.MAX_SEQ_LENGTH,
        save_dir: Optional[Path] = None,
    ):
        self.tokenizer_name = tokenizer_name
        self.max_seq_length = max_seq_length
        self.save_dir = save_dir or settings.PROCESSED_DATA_DIR
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.preprocessor = TextPreprocessor()
        self.tokenizer = self._load_tokenizer()

    def _load_tokenizer(self) -> PreTrainedTokenizer:
        """Initialize HuggingFace tokenizer with proper pad token."""
        logger.info(f"Loading tokenizer: {self.tokenizer_name}")
        try:
            tokenizer = AutoTokenizer.from_pretrained(self.tokenizer_name)
        except Exception as e:
            logger.warning(f"Failed to load tokenizer {self.tokenizer_name}: {e}. Falling back to gpt2.")
            tokenizer = AutoTokenizer.from_pretrained("gpt2")

        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token or "<|endoftext|>"
            tokenizer.pad_token_id = tokenizer.eos_token_id

        return tokenizer

    def build_dataset_from_db(
        self,
        limit: Optional[int] = None,
        train_ratio: float = 0.8,
        val_ratio: float = 0.1,
        test_ratio: float = 0.1,
    ) -> DatasetDict:
        """
        Extract articles from SQLite, format texts, and split into train/val/test splits.
        """
        with get_db_session() as session:
            repo = ArticleRepository(session)
            articles = repo.get_training_dataset(limit=limit)

        if not articles:
            logger.warning("No articles found in SQLite database. Creating fallback synthetic Bangla samples.")
            from src.scraper.mock_bangla_portal import MOCK_ARTICLES
            from src.storage.models import Article
            articles = []
            for item in MOCK_ARTICLES:
                art = Article(
                    id=len(articles) + 1,
                    url=f"http://example.com/{item['id']}",
                    source="mock_bangla",
                    title=item["title"],
                    author=item["author"],
                    category=item["category"],
                    content_text=item["content"],
                    summary=item["summary"],
                    extracted_entities=item.get("entities", {}),
                )
                articles.append(art)

        # Preprocess articles
        records = self.preprocessor.process_article_batch(articles)
        if not records:
            raise ValueError("Preprocessing resulted in 0 valid training samples.")

        # Create HuggingFace Dataset
        full_dataset = Dataset.from_list(records)

        # Split into Train / Val / Test
        test_val_ratio = val_ratio + test_ratio
        split_1 = full_dataset.train_test_split(test_size=test_val_ratio, seed=settings.SEED)
        train_ds = split_1["train"]

        # Further split test/val
        if test_ratio > 0 and len(split_1["test"]) > 1:
            rel_test_ratio = test_ratio / test_val_ratio
            split_2 = split_1["test"].train_test_split(test_size=rel_test_ratio, seed=settings.SEED)
            val_ds = split_2["train"]
            test_ds = split_2["test"]
        else:
            val_ds = split_1["test"]
            test_ds = split_1["test"]

        dataset_dict = DatasetDict({
            "train": train_ds,
            "validation": val_ds,
            "test": test_ds,
        })

        logger.info(
            f"Dataset built successfully: "
            f"Train={len(train_ds)}, Validation={len(val_ds)}, Test={len(test_ds)}"
        )
        return dataset_dict

    def tokenize_dataset(self, dataset_dict: DatasetDict, text_column: str = "text") -> DatasetDict:
        """Tokenize dataset for causal language modeling."""
        tokenizer = self.tokenizer
        max_length = self.max_seq_length

        def _tokenize_fn(batch):
            tokens = tokenizer(
                batch[text_column],
                truncation=True,
                max_length=max_length,
                padding="max_length",
                return_tensors=None,
            )
            tokens["labels"] = [
                [(t if t != tokenizer.pad_token_id else -100) for t in seq]
                for seq in tokens["input_ids"]
            ]
            return tokens

        tokenized = dataset_dict.map(
            _tokenize_fn,
            batched=True,
            remove_columns=dataset_dict["train"].column_names,
            desc="Tokenizing dataset for Causal LM",
        )
        return tokenized
