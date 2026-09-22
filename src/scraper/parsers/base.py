"""
Abstract Base Parser Interface for Article Extraction.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup


class BaseParser(ABC):
    """Abstract interface for website and article parsers."""

    @abstractmethod
    def extract_article_links(self, html: str, base_url: str) -> List[str]:
        """Extract article URLs from category or index pages."""
        pass

    @abstractmethod
    def parse_article(self, html: str, url: str, category: Optional[str] = None) -> Dict[str, Any]:
        """
        Extract structured fields from an article HTML page.

        Returns a dictionary with:
            - title: str
            - content_text: str
            - author: Optional[str]
            - published_at: Optional[datetime]
            - category: Optional[str]
            - lead_image_url: Optional[str]
            - image_urls: List[str]
            - missing_fields: List[str]
        """
        pass
