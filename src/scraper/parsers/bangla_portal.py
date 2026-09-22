"""
Bangla Portal Article Parser.
Supports multi-selector fallback hierarchy (CSS -> JSON-LD -> OpenGraph -> Heuristics)
and robust extraction of Bangla newspaper articles.
"""

import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from src.common.logger import get_logger
from src.common.normalizer import BanglaTextNormalizer
from src.common.utils import parse_iso_or_bangla_date
from src.scraper.parsers.base import BaseParser

logger = get_logger("webcreoling.scraper.parser")


class BanglaPortalParser(BaseParser):
    """Specialized parser for Bangla newspaper portals with multi-layer selector fallbacks."""

    def __init__(self, site_config: Optional[Dict[str, Any]] = None):
        self.config = site_config or {}
        self.selectors = self.config.get("selectors", {})

    def extract_article_links(self, html: str, base_url: str) -> List[str]:
        """Extract article URLs from catalog, section, or archive pages."""
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        links = set()
        domain = urlparse(base_url).netloc

        # 1. Use configured selectors if available
        custom_selectors = self.selectors.get("article_links", [])
        for selector in custom_selectors:
            for tag in soup.select(selector):
                href = tag.get("href")
                if href:
                    full_url = urljoin(base_url, href)
                    if self._is_valid_article_url(full_url, domain):
                        links.add(full_url)

        # 2. Heuristic fallback: find all anchor tags matching standard news URL patterns
        if not links:
            for tag in soup.find_all("a", href=True):
                href = tag["href"]
                full_url = urljoin(base_url, href)
                if self._is_valid_article_url(full_url, domain):
                    # Filter out short or navigation links
                    links.add(full_url)

        return sorted(list(links))

    def _is_valid_article_url(self, url: str, domain: str) -> bool:
        """Filter out non-article URLs like categories, tag pages, javascript, or external ads."""
        parsed = urlparse(url)
        # Verify same domain or subdomain
        if domain and not (parsed.netloc == domain or parsed.netloc.endswith("." + domain)):
            return False

        path = parsed.path.lower()
        # Exclude common non-article routes
        excluded_tokens = [
            "/tag/", "/topic/", "/author/", "/login", "/register", "/search",
            "/privacy", "/terms", "/archive", "/about", "/contact", ".pdf",
            ".jpg", ".png", ".rss", "javascript:", "#",
        ]
        if any(token in path for token in excluded_tokens):
            return False

        # Must have reasonable path depth
        if path in ["", "/", "/index.html", "/index.php"]:
            return False

        return True

    def parse_article(self, html: str, url: str, category: Optional[str] = None) -> Dict[str, Any]:
        """
        Extract structured article data using multi-selector fallback strategy.
        Tracks any missing fields for exponential retry or database storage.
        """
        if not html:
            return {
                "url": url,
                "title": "",
                "content_text": "",
                "author": None,
                "published_at": None,
                "category": category,
                "lead_image_url": None,
                "image_urls": [],
                "missing_fields": ["title", "content_text", "published_at", "lead_image"],
            }

        soup = BeautifulSoup(html, "lxml")
        missing_fields = []

        # ----------------------------------------------------
        # 1. Extract JSON-LD Metadata if present
        # ----------------------------------------------------
        json_ld_data = self._extract_json_ld(soup)

        # ----------------------------------------------------
        # 2. Extract Title (CSS -> JSON-LD -> OpenGraph -> h1)
        # ----------------------------------------------------
        title = self._extract_field(
            soup=soup,
            configured_selectors=self.selectors.get("title", []),
            json_ld_val=json_ld_data.get("headline") or json_ld_data.get("name"),
            og_prop="og:title",
            fallback_tags=["h1"],
        )
        if not title:
            missing_fields.append("title")

        # ----------------------------------------------------
        # 3. Extract Published Date (CSS -> JSON-LD -> OpenGraph -> time)
        # ----------------------------------------------------
        date_str = self._extract_date_str(soup, json_ld_data)
        published_at = parse_iso_or_bangla_date(date_str) if date_str else None
        if not published_at:
            missing_fields.append("published_at")

        # ----------------------------------------------------
        # 4. Extract Author (CSS -> JSON-LD -> meta author)
        # ----------------------------------------------------
        author = self._extract_author(soup, json_ld_data)
        if not author:
            missing_fields.append("author")

        # ----------------------------------------------------
        # 5. Extract Category (URL -> Config -> JSON-LD -> meta)
        # ----------------------------------------------------
        final_category = category or json_ld_data.get("articleSection") or self._extract_category_from_url_or_meta(soup, url)

        # ----------------------------------------------------
        # 6. Extract Article Body Text (CSS -> JSON-LD -> article p)
        # ----------------------------------------------------
        content_text = self._extract_content(soup, json_ld_data)
        if not content_text or len(content_text) < 50:
            missing_fields.append("content_text")

        # ----------------------------------------------------
        # 7. Extract Images (Lead Image + Article Images)
        # ----------------------------------------------------
        lead_image_url, image_urls = self._extract_images(soup, json_ld_data, url)
        if not lead_image_url and not image_urls:
            missing_fields.append("lead_image")

        return {
            "url": url,
            "title": BanglaTextNormalizer.normalize_article_text(title or ""),
            "content_text": BanglaTextNormalizer.normalize_article_text(content_text or ""),
            "author": author,
            "published_at": published_at,
            "category": final_category or "general",
            "lead_image_url": lead_image_url,
            "image_urls": image_urls,
            "missing_fields": missing_fields,
        }

    def _extract_json_ld(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract schema.org NewsArticle / Article JSON-LD script."""
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                if not script.string:
                    continue
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "Article" in item.get("@type", ""):
                            return item
                elif isinstance(data, dict):
                    if "Article" in data.get("@type", ""):
                        return data
                    # Check @graph
                    if "@graph" in data and isinstance(data["@graph"], list):
                        for item in data["@graph"]:
                            if isinstance(item, dict) and "Article" in item.get("@type", ""):
                                return item
            except Exception:
                continue
        return {}

    def _extract_field(
        self,
        soup: BeautifulSoup,
        configured_selectors: List[str],
        json_ld_val: Optional[str],
        og_prop: Optional[str],
        fallback_tags: List[str],
    ) -> Optional[str]:
        """Multi-layer field extraction."""
        # 1. Custom configured selectors
        for selector in configured_selectors:
            if selector.startswith("meta"):
                tag = soup.select_one(selector)
                if tag and tag.get("content"):
                    return tag["content"].strip()
            else:
                tag = soup.select_one(selector)
                if tag and tag.get_text(strip=True):
                    return tag.get_text(strip=True)

        # 2. JSON-LD value
        if json_ld_val and str(json_ld_val).strip():
            return str(json_ld_val).strip()

        # 3. OpenGraph meta tag
        if og_prop:
            og_tag = soup.find("meta", property=og_prop) or soup.find("meta", attrs={"name": og_prop})
            if og_tag and og_tag.get("content"):
                return og_tag["content"].strip()

        # 4. Fallback HTML tags
        for tag_name in fallback_tags:
            tag = soup.find(tag_name)
            if tag and tag.get_text(strip=True):
                return tag.get_text(strip=True)

        return None

    def _extract_date_str(self, soup: BeautifulSoup, json_ld: Dict[str, Any]) -> Optional[str]:
        """Extract publication date string from selectors or metadata."""
        # 1. Selectors
        for selector in self.selectors.get("published_at", []):
            tag = soup.select_one(selector)
            if tag:
                if tag.name == "meta" and tag.get("content"):
                    return tag["content"]
                if tag.get("datetime"):
                    return tag["datetime"]
                if tag.get_text(strip=True):
                    return tag.get_text(strip=True)

        # 2. JSON-LD
        if json_ld.get("datePublished"):
            return str(json_ld["datePublished"])
        if json_ld.get("dateCreated"):
            return str(json_ld["dateCreated"])

        # 3. OpenGraph / Standard Meta
        for name in ["article:published_time", "pubdate", "publish_date", "date"]:
            meta = soup.find("meta", property=name) or soup.find("meta", attrs={"name": name})
            if meta and meta.get("content"):
                return meta["content"]

        # 4. Time tag
        time_tag = soup.find("time")
        if time_tag:
            return time_tag.get("datetime") or time_tag.get_text(strip=True)

        return None

    def _extract_author(self, soup: BeautifulSoup, json_ld: Dict[str, Any]) -> Optional[str]:
        """Extract author name."""
        # 1. Custom selectors
        for selector in self.selectors.get("author", []):
            tag = soup.select_one(selector)
            if tag:
                if tag.name == "meta" and tag.get("content"):
                    return tag["content"].strip()
                if tag.get_text(strip=True):
                    return tag.get_text(strip=True)

        # 2. JSON-LD
        author_data = json_ld.get("author")
        if isinstance(author_data, dict):
            return author_data.get("name")
        elif isinstance(author_data, list) and len(author_data) > 0:
            if isinstance(author_data[0], dict):
                return author_data[0].get("name")
            return str(author_data[0])
        elif isinstance(author_data, str):
            return author_data

        # 3. Meta author
        meta = soup.find("meta", attrs={"name": "author"})
        if meta and meta.get("content"):
            return meta["content"].strip()

        return None

    def _extract_category_from_url_or_meta(self, soup: BeautifulSoup, url: str) -> Optional[str]:
        """Infer news category from URL path or OpenGraph section."""
        # Meta section
        sec = soup.find("meta", property="article:section")
        if sec and sec.get("content"):
            return sec["content"].strip().lower()

        # Parse URL segments
        path = urlparse(url).path.lower()
        category_keywords = {
            "politics": ["politics", "rajniti", "রাজনীতি"],
            "sports": ["sports", "khela", "খেলা"],
            "business": ["business", "banijjo", "বাণিজ্য", "অর্থনীতি", "economy"],
            "technology": ["technology", "tech", "বিজ্ঞান-প্রযুক্তি", "বিজ্ঞান", "তথ্যপ্রযুক্তি"],
            "international": ["world", "international", "আন্তর্জাতিক", "বিশ্ব"],
            "entertainment": ["entertainment", "binodon", "বিনোদন", "cinema"],
            "bangladesh": ["bangladesh", "national", "জাতীয়", "বাংলাদেশ"],
            "opinion": ["opinion", "motamot", "মতামত", "editorial"],
        }
        for cat_name, keywords in category_keywords.items():
            if any(kw in path for kw in keywords):
                return cat_name

        return "general"

    def _extract_content(self, soup: BeautifulSoup, json_ld: Dict[str, Any]) -> Optional[str]:
        """Extract full article paragraph text."""
        # 1. Custom configured selectors
        for selector in self.selectors.get("content", []):
            paragraphs = soup.select(selector)
            if paragraphs:
                texts = [p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)]
                joined = "\n\n".join(texts)
                if len(joined) >= 60:
                    return joined

        # 2. JSON-LD articleBody
        if json_ld.get("articleBody"):
            return str(json_ld["articleBody"])

        # 3. Standard semantic article / main paragraphs
        for container in soup.find_all(["article", "main", "div.story-content", "div.article-content"]):
            paragraphs = container.find_all("p")
            texts = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20]
            if texts:
                joined = "\n\n".join(texts)
                if len(joined) >= 80:
                    return joined

        # 4. Fallback: all top-level p tags
        all_p = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 25]
        if all_p:
            return "\n\n".join(all_p)

        return None

    def _extract_images(
        self, soup: BeautifulSoup, json_ld: Dict[str, Any], base_url: str
    ) -> Tuple[Optional[str], List[str]]:
        """Extract lead image URL and all embedded article image URLs."""
        lead_image_url = None
        image_urls = []

        # 1. OpenGraph lead image
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            lead_image_url = urljoin(base_url, og_img["content"])

        # 2. JSON-LD image
        if not lead_image_url and json_ld.get("image"):
            img_val = json_ld["image"]
            if isinstance(img_val, str):
                lead_image_url = urljoin(base_url, img_val)
            elif isinstance(img_val, list) and len(img_val) > 0:
                lead_image_url = urljoin(base_url, img_val[0])
            elif isinstance(img_val, dict) and img_val.get("url"):
                lead_image_url = urljoin(base_url, img_val["url"])

        # 3. Configured lead image selectors
        if not lead_image_url:
            for selector in self.selectors.get("lead_image", []):
                tag = soup.select_one(selector)
                if tag:
                    src = tag.get("src") or tag.get("data-src") or tag.get("content")
                    if src:
                        lead_image_url = urljoin(base_url, src)
                        break

        # 4. Extract all embedded images
        for selector in self.selectors.get("article_images", ["article img", "main img"]):
            for img_tag in soup.select(selector):
                src = img_tag.get("src") or img_tag.get("data-src")
                if src:
                    full_src = urljoin(base_url, src)
                    if full_src.startswith(("http://", "https://")) and full_src not in image_urls:
                        image_urls.append(full_src)

        if lead_image_url and lead_image_url not in image_urls:
            image_urls.insert(0, lead_image_url)

        return lead_image_url, image_urls
