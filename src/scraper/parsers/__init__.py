"""Parser exports."""
from src.scraper.parsers.base import BaseParser
from src.scraper.parsers.bangla_portal import BanglaPortalParser
from src.scraper.parsers.generic_news import GenericNewsParser

__all__ = ["BaseParser", "BanglaPortalParser", "GenericNewsParser"]
