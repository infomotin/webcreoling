"""Multi-source news scraper: direct HTML, RSS feeds & third-party news APIs.

Resilient source handling (per-source, never global):
  * exponential backoff retry per source (backoff_base * 2^attempt)
  * sources that exhaust all retries are SKIPPED and recorded
  * remaining sources continue scraping — one bad source never pauses the job

Feeds the Auto Scroller pipeline (classify -> dedup -> rewrite -> AI gate ->
publish/queue) with normalized raw items.
"""

import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import requests

from src.common.logger import get_logger

logger = get_logger("webcreoling.scraper.multi_source")

DEFAULT_CONFIG: Dict[str, Any] = {
    "hours_between_runs": 3,          # 2-4h target window (spec)
    "backoff_base_seconds": 2.0,      # exponential backoff base per source
    "max_retries": 3,                 # attempts per source before skipping
    "per_source_limit": 5,            # max items ingested per source per cycle
    "request_timeout": 15,
    "sources": [
        {
            "key": "bbc_world_rss",
            "name": "BBC World News",
            "type": "rss",
            "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
            "category": "international",
            "enabled": True,
            "max_retries": 3,
            "backoff_base": 2.0,
            "max_items": 3,
        },
        {
            "key": "aljazeera_rss",
            "name": "Al Jazeera",
            "type": "rss",
            "url": "https://www.aljazeera.com/xml/rss/all.xml",
            "category": "international",
            "enabled": True,
            "max_retries": 2,
            "backoff_base": 2.0,
            "max_items": 3,
        },
        {
            "key": "prothom_alo_html",
            "name": "Prothom Alo (Direct HTML)",
            "type": "html",
            "url": "https://www.prothomalo.com",
            "category": "bangladesh",
            "enabled": False,
            "max_retries": 3,
            "backoff_base": 2.0,
            "max_items": 2,
        },
        {
            "key": "newsapi_top_headlines",
            "name": "NewsAPI Top Headlines",
            "type": "newsapi",
            "url": "https://newsapi.org/v2/top-headlines",
            "params": {"country": "us", "pageSize": 10},
            "category": "general",
            "enabled": False,       # requires NEWSAPI_API_KEY
            "max_retries": 3,
            "backoff_base": 2.0,
            "max_items": 5,
        },
        {
            "key": "guardian_world",
            "name": "The Guardian API",
            "type": "guardian",
            "url": "https://content.guardianapis.com/search",
            "params": {"section": "world", "page-size": 10},
            "category": "international",
            "enabled": False,       # requires GUARDIAN_API_KEY
            "max_retries": 3,
            "backoff_base": 2.0,
            "max_items": 5,
        },
    ],
}


class SourceFetchError(Exception):
    """Raised when a single fetch attempt fails (triggers a retry)."""


def _default_http_get(url: str, headers: Optional[Dict[str, str]] = None,
                      timeout: int = 15, params: Optional[Dict[str, Any]] = None) -> Any:
    hdrs = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WebCreolingNewsBot/1.0",
        "Accept": "application/rss+xml, application/xml, application/json, text/html, */*",
    }
    if headers:
        hdrs.update(headers)
    resp = requests.get(url, headers=hdrs, timeout=timeout, params=params)
    resp.raise_for_status()
    return resp


def _strip_html(text: str) -> str:
    if not text:
        return ""
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    except Exception:
        import re
        return re.sub(r"<[^>]+>", " ", text)


def fetch_with_retry(
    fetch_fn: Callable[[], List[Dict[str, Any]]],
    *,
    max_retries: int = 3,
    backoff_base: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
    label: str = "source",
) -> Dict[str, Any]:
    """Run fetch_fn with exponential backoff; skip the source after all retries.

    Returns {"ok": True, "items": [...], "attempts": n} on success or
    {"ok": False, "error": str, "attempts": n, "skipped": True} after exhaustion.
    """
    max_retries = max(1, int(max_retries))
    last_error: Optional[str] = None
    for attempt in range(max_retries):
        try:
            items = fetch_fn()
            return {"ok": True, "items": items or [], "attempts": attempt + 1}
        except Exception as exc:
            last_error = str(exc)
            if attempt < max_retries - 1:
                delay = float(backoff_base) * (2 ** attempt)
                logger.warning(
                    f"[Multi-Source] {label} attempt {attempt + 1}/{max_retries} failed: "
                    f"{exc} — retrying in {delay:.1f}s (exponential backoff)"
                )
                if delay > 0:
                    sleep(delay)
            else:
                logger.error(
                    f"[Multi-Source] {label} exhausted {max_retries} retries — SKIPPING source "
                    f"(continuing with remaining sources). Last error: {exc}"
                )
    return {"ok": False, "error": last_error or "unknown error",
            "attempts": max_retries, "skipped": True}


class MultiSourceScraper:
    """HTML / RSS / news-API scraping with per-source resilience."""

    # ------------------------------------------------------------------
    # Config (site_configs["news_sources"])
    # ------------------------------------------------------------------
    @staticmethod
    def get_config(session) -> Dict[str, Any]:
        from src.storage.repositories import SiteConfigRepository
        cfg = dict(DEFAULT_CONFIG)
        stored = SiteConfigRepository(session).get_config("news_sources", None)
        if isinstance(stored, dict):
            cfg.update(stored)
        return cfg

    @staticmethod
    def save_config(session, data: Dict[str, Any]) -> Dict[str, Any]:
        from src.storage.repositories import SiteConfigRepository
        from datetime import datetime
        repo = SiteConfigRepository(session)
        cfg = dict(DEFAULT_CONFIG)
        stored = repo.get_config("news_sources", None)
        if isinstance(stored, dict):
            cfg.update(stored)
        cfg.update(data)
        cfg["updated_at"] = datetime.utcnow().isoformat()
        repo.set_config("news_sources", cfg)
        return cfg

    # ------------------------------------------------------------------
    # Per-source fetchers
    # ------------------------------------------------------------------
    @classmethod
    def _fetch_rss(cls, source: Dict[str, Any], http_get, timeout: int) -> List[Dict[str, Any]]:
        import feedparser
        resp = http_get(source["url"], timeout=timeout)
        content = resp.content if hasattr(resp, "content") else resp
        feed = feedparser.parse(content)
        if getattr(feed, "bozo", False) and not feed.entries:
            raise SourceFetchError(f"RSS parse error: {getattr(feed, 'bozo_exception', 'unknown')}")
        if not feed.entries:
            raise SourceFetchError("RSS feed returned zero entries")

        items: List[Dict[str, Any]] = []
        feed_title = (feed.feed or {}).get("title") or source.get("name") or "RSS Wire"
        for entry in feed.entries:
            link = entry.get("link") or ""
            title = entry.get("title") or ""
            if not link or not title:
                continue
            body = entry.get("summary") or entry.get("description") or ""
            if not body and entry.get("content"):
                try:
                    body = entry.content[0].get("value", "")
                except Exception:
                    body = ""
            image_url = None
            try:
                media = entry.get("media_thumbnail") or entry.get("media_content") or []
                if media and isinstance(media, list):
                    image_url = media[0].get("url")
            except Exception:
                image_url = None
            published = entry.get("published") or entry.get("updated")
            items.append({
                "source_url": link,
                "title": title,
                "content": _strip_html(body),
                "source_name": source.get("name") or feed_title,
                "author": (entry.get("author") or None),
                "image_url": image_url,
                "category": source.get("category"),
                "source_key": source.get("key"),
                "published": published,
            })
        return items

    @classmethod
    def _fetch_html(cls, source: Dict[str, Any], http_get, timeout: int) -> List[Dict[str, Any]]:
        from src.scraper.custom_portal_ingester import CustomPortalIngester
        raw = CustomPortalIngester.extract_raw_page_data(source["url"])
        if not raw or not raw.get("raw_title"):
            raise SourceFetchError("HTML page yielded no article data")
        return [{
            "source_url": raw.get("url") or source["url"],
            "title": raw.get("raw_title"),
            "content": raw.get("raw_content") or "",
            "source_name": raw.get("default_source_name") or source.get("name"),
            "author": raw.get("author"),
            "image_url": raw.get("lead_image_url"),
            "category": source.get("category") or raw.get("category"),
            "source_key": source.get("key"),
            "published": raw.get("published_at"),
        }]

    @classmethod
    def _fetch_newsapi(cls, source: Dict[str, Any], http_get, timeout: int) -> List[Dict[str, Any]]:
        from config.settings import settings
        api_key = source.get("api_key") or getattr(settings, "NEWSAPI_API_KEY", "")
        if not api_key:
            raise SourceFetchError("NewsAPI API key not configured")
        params = dict(source.get("params") or {})
        params["apiKey"] = api_key
        resp = http_get(source.get("url") or "https://newsapi.org/v2/top-headlines",
                        headers={"X-Api-Key": api_key}, timeout=timeout, params=params)
        data = resp.json() if hasattr(resp, "json") else resp
        if isinstance(data, dict) and data.get("status") != "ok":
            raise SourceFetchError(f"NewsAPI error: {data.get('message', data.get('code'))}")
        articles = (data or {}).get("articles") or []
        items: List[Dict[str, Any]] = []
        for art in articles:
            link = art.get("url") or ""
            title = art.get("title") or ""
            if not link or not title or title == "[Removed]":
                continue
            source_meta = art.get("source") or {}
            items.append({
                "source_url": link,
                "title": title,
                "content": _strip_html(art.get("description") or "") + " " + _strip_html(art.get("content") or ""),
                "source_name": source_meta.get("name") or source.get("name"),
                "author": art.get("author"),
                "image_url": (art.get("urlToImage") or None),
                "category": source.get("category"),
                "source_key": source.get("key"),
                "published": art.get("publishedAt"),
            })
        return items

    @classmethod
    def _fetch_guardian(cls, source: Dict[str, Any], http_get, timeout: int) -> List[Dict[str, Any]]:
        from config.settings import settings
        api_key = source.get("api_key") or getattr(settings, "GUARDIAN_API_KEY", "")
        if not api_key:
            raise SourceFetchError("Guardian API key not configured")
        params = dict(source.get("params") or {})
        params.update({"api-key": api_key, "show-fields": "body,thumbnail,byline"})
        resp = http_get(source.get("url") or "https://content.guardianapis.com/search",
                        timeout=timeout, params=params)
        data = resp.json() if hasattr(resp, "json") else resp
        results = ((data or {}).get("response") or {}).get("results") or []
        items: List[Dict[str, Any]] = []
        for art in results:
            link = art.get("webUrl") or ""
            title = art.get("webTitle") or ""
            if not link or not title:
                continue
            fields = art.get("fields") or {}
            items.append({
                "source_url": link,
                "title": title,
                "content": _strip_html(fields.get("body") or ""),
                "source_name": "The Guardian",
                "author": fields.get("byline") or None,
                "image_url": fields.get("thumbnail") or None,
                "category": source.get("category"),
                "source_key": source.get("key"),
                "published": art.get("webPublicationDate"),
            })
        return items

    @classmethod
    def _fetch_once(cls, source: Dict[str, Any], http_get, timeout: int) -> List[Dict[str, Any]]:
        stype = str(source.get("type", "html")).lower()
        if stype == "rss":
            return cls._fetch_rss(source, http_get, timeout)
        if stype == "newsapi":
            return cls._fetch_newsapi(source, http_get, timeout)
        if stype == "guardian":
            return cls._fetch_guardian(source, http_get, timeout)
        return cls._fetch_html(source, http_get, timeout)

    @classmethod
    def fetch_source(
        cls,
        source: Dict[str, Any],
        *,
        max_retries: Optional[int] = None,
        backoff_base: Optional[float] = None,
        http_get=None,
        sleep: Callable[[float], None] = time.sleep,
        timeout: int = 15,
    ) -> Dict[str, Any]:
        """Fetch one source with exponential backoff; skip after retries exhaust."""
        http_get = http_get or _default_http_get
        retries = int(max_retries if max_retries is not None else source.get("max_retries", 3))
        backoff = float(backoff_base if backoff_base is not None else source.get("backoff_base", 2.0))
        return fetch_with_retry(
            lambda: cls._fetch_once(source, http_get, timeout),
            max_retries=retries,
            backoff_base=backoff,
            sleep=sleep,
            label=f"{source.get('key', source.get('name', 'source'))} ({source.get('type', '?')})",
        )

    # ------------------------------------------------------------------
    # Full cycle: iterate ALL sources, skip failures, continue the rest
    # ------------------------------------------------------------------
    @classmethod
    def run_cycle(
        cls,
        session=None,
        sources: Optional[List[Dict[str, Any]]] = None,
        max_items: Optional[int] = None,
        http_get=None,
        sleep: Callable[[float], None] = time.sleep,
        ingest=None,
    ) -> Dict[str, Any]:
        """Scrape every enabled source & push items through the Auto Scroller pipeline."""
        from src.storage.database import get_db_session

        if session is not None:
            cfg = cls.get_config(session)
        else:
            with get_db_session() as own:
                cfg = cls.get_config(own)

        if sources is None:
            sources = [s for s in (cfg.get("sources") or []) if s.get("enabled")]
        cfg_limit = int(cfg.get("per_source_limit", 5))
        timeout = int(cfg.get("request_timeout", 15))
        default_retries = int(cfg.get("max_retries", 3))
        default_backoff = float(cfg.get("backoff_base_seconds", 2.0))

        summary: Dict[str, Any] = {
            "sources_total": len(cfg.get("sources") or []),
            "sources_enabled": len(sources),
            "sources_ok": 0,
            "sources_failed": 0,
            "fetched": 0,
            "ingested": 0,
            "duplicates": 0,
            "queued": 0,
            "auto_published": 0,
            "rejected": 0,
            "failed": 0,
            "skipped_sources": [],
            "errors": [],
            "ran_at": datetime.utcnow().isoformat(),
        }

        if ingest is None:
            from src.automation.auto_scroller import AutoScroller
            ingest = AutoScroller.ingest_raw_item

        total_ingested = 0
        for source in sources:
            if max_items is not None and total_ingested >= max_items:
                break
            key = source.get("key") or source.get("name") or "source"
            res = cls.fetch_source(
                source,
                max_retries=source.get("max_retries", default_retries),
                backoff_base=source.get("backoff_base", default_backoff),
                http_get=http_get,
                sleep=sleep,
                timeout=timeout,
            )
            if not res.get("ok"):
                # SKIP this source, CONTINUE with the remaining ones
                summary["sources_failed"] += 1
                summary["skipped_sources"].append(
                    {"key": key, "type": source.get("type"), "error": res.get("error"),
                     "attempts": res.get("attempts")}
                )
                continue

            summary["sources_ok"] += 1
            items = res["items"][: int(source.get("max_items", cfg_limit))]
            summary["fetched"] += len(items)

            for item in items:
                if max_items is not None and total_ingested >= max_items:
                    break
                try:
                    ing = ingest(
                        source_url=item["source_url"],
                        title=item["title"],
                        content=item.get("content") or item["title"],
                        source_name=item.get("source_name"),
                        author=item.get("author"),
                        image_url=item.get("image_url"),
                        category=item.get("category"),
                        source_key=item.get("source_key") or key,
                    )
                except Exception as exc:
                    summary["failed"] += 1
                    summary["errors"].append({"source": key, "url": item.get("source_url"),
                                              "error": str(exc)})
                    continue

                if ing.get("skipped") == "duplicate_url":
                    summary["duplicates"] += 1
                    continue
                if not ing.get("success"):
                    summary["failed"] += 1
                    if ing.get("error"):
                        summary["errors"].append({"source": key, "url": item.get("source_url"),
                                                  "error": ing["error"]})
                    continue

                total_ingested += 1
                summary["ingested"] += 1
                status = ing.get("status")
                if status == "duplicate":
                    summary["duplicates"] += 1
                elif status == "rejected":
                    summary["rejected"] += 1
                elif status == "auto_published":
                    summary["auto_published"] += 1
                elif status == "queued":
                    summary["queued"] += 1

        logger.info(
            f"[Multi-Source] cycle done: {summary['sources_ok']}/{summary['sources_enabled']} "
            f"sources ok | fetched {summary['fetched']} | ingested {summary['ingested']} | "
            f"skipped {len(summary['skipped_sources'])}"
        )
        return summary
