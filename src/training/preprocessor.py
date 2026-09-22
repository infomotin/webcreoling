"""
Text Preprocessor for LLM Training.
Normalizes Bangla Unicode text, removes boilerplate, filters by length, and formats for Causal LM.
"""

from typing import Dict, Any, List, Optional
from src.common.logger import get_logger
from src.common.normalizer import BanglaTextNormalizer
from src.storage.models import Article

logger = get_logger("webcreoling.training.preprocessor")


class TextPreprocessor:
    """Prepares and cleans scraped article text for LLM training."""

    def __init__(self, min_char_length: int = 60, max_char_length: int = 5000):
        self.min_char_length = min_char_length
        self.max_char_length = max_char_length

    def clean_and_normalize(self, text: str) -> str:
        """Apply comprehensive Bangla Unicode normalization and whitespace cleaning."""
        return BanglaTextNormalizer.normalize_article_text(text, remove_boilerplates=True)

    def prepare_causal_lm_text(self, article: Article) -> Optional[str]:
        """
        Format a single article into continuous Causal Language Modeling text:
        Title -> Category -> Body -> End of Text.
        """
        title = self.clean_and_normalize(article.title or "")
        body = self.clean_and_normalize(article.content_text or "")
        category = (article.category or "general").strip()

        if len(body) < self.min_char_length or not title:
            return None

        # Truncate if excessively long
        if len(body) > self.max_char_length:
            body = body[:self.max_char_length]

        formatted_text = f"শিরোনাম: {title}\nবিভাগ: {category}\n\n{body}\n<|endoftext|>"
        return formatted_text

    def process_article_batch(self, articles: List[Article]) -> List[Dict[str, Any]]:
        """Process a list of articles and return clean dataset records."""
        processed = []
        for article in articles:
            text = self.prepare_causal_lm_text(article)
            if text:
                processed.append({
                    "id": article.id,
                    "title": self.clean_and_normalize(article.title),
                    "category": article.category or "general",
                    "text": text,
                    "content": self.clean_and_normalize(article.content_text),
                    "summary": self.clean_and_normalize(article.summary or ""),
                    "entities": article.extracted_entities or {},
                })
        logger.info(f"Preprocessed {len(processed)} valid training samples from {len(articles)} articles.")
        return processed
