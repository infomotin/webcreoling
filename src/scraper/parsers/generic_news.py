"""
Generic News Article Parser using Schema.org & OpenGraph standards.
"""

from typing import Dict, Any, List, Optional
from src.scraper.parsers.bangla_portal import BanglaPortalParser


class GenericNewsParser(BanglaPortalParser):
    """Fallback generic news parser leveraging standard web metadata and semantic tags."""

    def __init__(self):
        super().__init__(site_config={
            "selectors": {
                "article_links": ["article a", ".story a", ".news a", "h2 a", "h3 a"],
                "title": ["meta[property='og:title']", "h1", ".entry-title"],
                "author": ["meta[name='author']", ".author", ".byline"],
                "published_at": ["meta[property='article:published_time']", "time"],
                "content": ["article p", "main p", ".entry-content p", ".article-content p"],
                "lead_image": ["meta[property='og:image']", "article img"],
                "article_images": ["article img", ".content img"],
            }
        })
