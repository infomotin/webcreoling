"""
Auto Scroller Pipeline (অটো স্ক্রলার পাইপলাইন).

End-to-end autonomous news flow:
  1. Scrape source portal / news URLs (raw ingest into RawNewsItem staging table).
  2. Auto-classify category (NLP skill engine).
  3. 98% similarity mining against recent raw items & published articles (dedup gate).
  4. Translate non-Bangla content into Bangla (MultiLingualNewsTranslator).
  5. Copyright-safe full-content regeneration (95-98% meaning retention, never verbatim).
  6. AI Brain decision (credibility / fake-news / truth gate).
  7. Wait for AI Brain & manual publish — or auto-post directly to /news/ portal
     when `auto_post_enabled` is on — always carrying the original source link + image.
"""

import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from src.common.logger import get_logger
from src.storage.database import get_db_session
from src.storage.models import RawNewsItem, Article
from src.storage.repositories import (
    ArticleRepository,
    RawNewsItemRepository,
    SiteConfigRepository,
)

logger = get_logger("webcreoling.automation.auto_scroller")


class AutoScroller:
    """Autonomous scrape -> raw store -> classify -> mine -> rewrite -> AI gate -> publish pipeline."""

    SIMILARITY_THRESHOLD = 0.98
    SIMILARITY_SAMPLE_SIZE = 250  # how many recent raw items / articles to compare against

    REJECT_DECISIONS = {
        "REJECTED_RULE_MISMATCH",
        "REJECTED_LOW_QUALITY",
        "QUARANTINED_HIGH_FAKE_RISK",
    }

    # ------------------------------------------------------------------
    # Similarity mining (98% duplicate detection)
    # ------------------------------------------------------------------
    @staticmethod
    def normalize_text(text: str) -> str:
        text = (text or "").lower()
        text = re.sub(r"\s+", " ", text)
        return re.sub(r"[^\w\u0980-\u09ff ]", "", text).strip()

    @classmethod
    def text_similarity(cls, a: str, b: str) -> float:
        """Similarity score in [0,1]: max of sequence ratio and word-shingle Jaccard."""
        na, nb = cls.normalize_text(a), cls.normalize_text(b)
        if not na or not nb:
            return 0.0
        if na == nb:
            return 1.0

        ratio = SequenceMatcher(None, na[:4000], nb[:4000]).ratio()

        def shingles(text: str) -> set:
            words = text.split()
            if len(words) < 3:
                return set(words)
            return {" ".join(words[i:i + 3]) for i in range(len(words) - 2)}

        sa, sb = shingles(na), shingles(nb)
        jaccard = len(sa & sb) / len(sa | sb) if sa and sb else 0.0
        return round(max(ratio, jaccard), 4)

    @classmethod
    def find_similar(
        cls,
        session,
        title: str,
        content: str,
        threshold: float,
        exclude_id: Optional[int] = None,
    ) -> Tuple[float, Optional[str]]:
        """Mine recent raw items & portal articles for near-duplicates (>= threshold)."""
        candidate = f"{title} {content}"
        best_score, best_url = 0.0, None

        raw_items = (
            session.query(RawNewsItem)
            .filter(RawNewsItem.status.notin_(["failed", "duplicate"]))
            .order_by(RawNewsItem.id.desc())
            .limit(cls.SIMILARITY_SAMPLE_SIZE)
            .all()
        )
        for item in raw_items:
            if exclude_id and item.id == exclude_id:
                continue
            score = cls.text_similarity(candidate, f"{item.title_raw} {item.content_raw or ''}")
            if score > best_score:
                best_score, best_url = score, item.source_url
            if best_score >= 1.0:
                return best_score, best_url

        articles = (
            session.query(Article)
            .order_by(Article.id.desc())
            .limit(cls.SIMILARITY_SAMPLE_SIZE)
            .all()
        )
        for art in articles:
            score = cls.text_similarity(candidate, f"{art.title} {art.content_text or ''}")
            if score > best_score:
                best_score, best_url = score, (art.original_source_url or art.url)
            if best_score >= 1.0:
                return best_score, best_url

        return round(best_score, 4), (best_url if best_score >= threshold else None)

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------
    @staticmethod
    def get_config(session) -> Dict[str, Any]:
        return SiteConfigRepository(session).get_auto_scroller_config()

    @staticmethod
    def save_config(session, data: Dict[str, Any]) -> Dict[str, Any]:
        return SiteConfigRepository(session).update_auto_scroller_config(data)

    # ------------------------------------------------------------------
    # Stage 1-6: ingest a single raw item through the whole pipeline
    # ------------------------------------------------------------------
    @classmethod
    def ingest_raw_item(
        cls,
        source_url: str,
        title: str,
        content: str,
        source_name: Optional[str] = None,
        author: Optional[str] = None,
        image_url: Optional[str] = None,
        category: Optional[str] = None,
        source_key: Optional[str] = None,
        session=None,
    ) -> Dict[str, Any]:
        """Run one raw news item through classify -> mine -> translate -> rewrite -> AI gate -> publish."""
        owns_session = session is None
        if owns_session:
            ctx = get_db_session()
            session = ctx.__enter__()
        try:
            result = cls._ingest_in_session(
                session, source_url, title, content,
                source_name=source_name, author=author, image_url=image_url,
                category=category, source_key=source_key,
            )
            if owns_session:
                session.commit()
            return result
        except Exception as e:
            if owns_session:
                session.rollback()
            logger.error(f"[Auto Scroller] ingest failed for {source_url}: {e}", exc_info=True)
            return {"success": False, "error": str(e), "source_url": source_url}
        finally:
            if owns_session:
                ctx.__exit__(None, None, None)

    @classmethod
    def _ingest_in_session(
        cls,
        session,
        source_url: str,
        title: str,
        content: str,
        source_name: Optional[str] = None,
        author: Optional[str] = None,
        image_url: Optional[str] = None,
        category: Optional[str] = None,
        source_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        from src.automation.ai_pilot_brain import (
            AIPilotBrain,
            MultiLingualNewsTranslator,
            NewsNLPSkillEngine,
        )

        cfg = cls.get_config(session)
        threshold = float(cfg.get("similarity_threshold", cls.SIMILARITY_THRESHOLD))
        source_url = (source_url or "").strip()
        title = (title or "").strip()
        content = (content or "").strip()

        if not source_url or not title:
            return {"success": False, "error": "source_url and title are required"}

        # Exact same source URL already ingested?
        existing = session.query(RawNewsItem).filter(RawNewsItem.source_url == source_url).first()
        if existing:
            return {
                "success": True, "skipped": "duplicate_url", "status": existing.status,
                "item_id": existing.id, "source_url": source_url,
            }

        # Keep the ORIGINAL pre-translation text for fidelity scoring & fact-checking
        source_title_orig, source_content_orig = title, content
        fidelity_reference = content  # same-language baseline for rewrite fidelity

        # Step 1: classify category
        assigned_category = NewsNLPSkillEngine.classify_category(
            title=title, content=content, default_cat=category or cfg.get("category", "general")
        )

        # Step 2: language detection & Bangla translation (non-Bangla sources)
        needs_translation = not (
            MultiLingualNewsTranslator.is_mostly_bangla(title)
            and MultiLingualNewsTranslator.is_mostly_bangla(content)
        )
        translated = False
        lang = "bn" if not needs_translation else "en"
        if needs_translation and cfg.get("translate_to_bangla", True):
            try:
                title, content = MultiLingualNewsTranslator.translate_and_localize_to_bangla(
                    title=title, content=content, source_lang=lang
                )
                translated = True
                fidelity_reference = content  # compare rewrite against translated source
            except Exception as te:
                logger.warning(f"[Auto Scroller] translation failed: {te}")

        item = RawNewsItem(
            source_key=source_key,
            source_name=source_name,
            source_url=source_url,
            title_raw=title,
            content_raw=content,
            author_raw=author,
            image_url=image_url,
            language=lang,
            needs_translation=needs_translation,
            translated=translated,
            category=assigned_category,
            status="classified",
            meta={
                "source_title": source_title_orig[:8000],
                "source_content": source_content_orig[:40000],
                "fidelity_reference": (fidelity_reference or "")[:40000],
            },
        )
        session.add(item)
        session.flush()

        # Step 3: 98% similarity mining (duplicate gate) — duplicates are KEPT
        # as separate entries and LINKED (related_items) rather than merged.
        score, dup_url = cls.find_similar(
            session, title, content, threshold=threshold, exclude_id=item.id
        )
        if dup_url and score >= threshold:
            item.status = "duplicate"
            item.similarity_score = score
            item.duplicate_of_url = dup_url
            from src.automation.dedup import link_raw_items
            relation = link_raw_items(session, item, dup_url, score)
            item.meta = {**(item.meta or {}), "related_link": bool(relation)}
            session.flush()
            logger.info(f"[Auto Scroller] duplicate detected ({score:.4f}) -> linked, kept separately: {source_url}")
            return {
                "success": True, "status": "duplicate", "item_id": item.id,
                "similarity_score": score, "duplicate_of_url": dup_url,
                "linked": bool(relation), "source_url": source_url,
            }
        item.similarity_score = score
        item.status = "regenerated"
        session.flush()

        # Step 4-6: AI Brain (copyright-safe 95-98% rewrite + credibility + decision gate)
        try:
            processed = AIPilotBrain.process_raw_article(
                {
                    "url": source_url,
                    "title": title,
                    "content_text": content,
                    "source": source_name or item.source_name or "Auto Scroller Wire",
                    "category": assigned_category,
                    "author": author,
                },
                auto_publish_threshold=int(float(cfg.get("ai_publish_threshold", 75.0))),
                force_rewrite=True,
            )
        except Exception as pe:
            item.status = "failed"
            item.meta = {"error": str(pe)}
            session.flush()
            return {"success": False, "error": str(pe), "item_id": item.id, "source_url": source_url}

        item.regenerated_title = processed["title"]
        item.regenerated_summary = processed["summary"]
        item.regenerated_body = processed["content_text"]
        item.meaning_retention_score = processed.get("meaning_retention_score")
        item.ai_decision = processed.get("ai_decision")
        item.credibility_score = processed.get("credibility_score")
        item.factuality_score = processed.get("factuality_score")
        item.fake_probability_pct = processed.get("fake_probability_pct")
        item.ai_reason = (processed.get("eval_result") or {}).get("rating")
        item.meta = {
            **(item.meta or {}),
            "extracted_entities": processed.get("extracted_entities"),
            "is_breaking": processed.get("is_breaking", False),
            "is_featured": processed.get("is_featured", False),
            "processed_at": datetime.utcnow().isoformat(),
        }
        session.flush()

        # Step 6b: semantic fidelity of rewrite vs original source (embedding-based,
        # 98% target) — sub-target rewrites are flagged and NEVER auto-published.
        fidelity = None
        try:
            from src.nlp.semantic_fidelity import SemanticFidelity
            reference = (item.meta or {}).get("fidelity_reference") or content
            fidelity = SemanticFidelity.measure(reference, processed.get("content_text") or "")
            item.meta = {**(item.meta or {}), "semantic_fidelity": fidelity}
            session.flush()
        except Exception as fe:
            logger.warning(f"[Auto Scroller] fidelity measurement failed: {fe}")

        decision = item.ai_decision or "QUEUE_FOR_REVIEW"

        # Step 7: publish gate
        if decision in cls.REJECT_DECISIONS:
            item.status = "rejected"
            session.flush()
            return {
                "success": True, "status": "rejected", "item_id": item.id,
                "ai_decision": decision, "source_url": source_url,
            }

        fidelity_ok = bool(fidelity) and bool(fidelity.get("passed"))
        if decision == "AUTO_PUBLISH" and cfg.get("auto_post_enabled", False) and fidelity_ok:
            article_id = cls._publish_item(session, item, origin="auto")
            if article_id:
                return {
                    "success": True, "status": "auto_published", "item_id": item.id,
                    "article_id": article_id, "ai_decision": decision, "source_url": source_url,
                    "semantic_fidelity": fidelity,
                }

        # Default: wait for AI Brain / manual publish (also when fidelity < target)
        item.status = "queued"
        session.flush()
        return {
            "success": True, "status": "queued", "item_id": item.id,
            "ai_decision": decision, "source_url": source_url,
            "semantic_fidelity": fidelity,
            "reason": (
                "Fidelity below target — held for editorial review"
                if (fidelity and not fidelity.get("passed"))
                else "Waiting for AI Brain cycle or manual editor publish"
            ),
        }

    # ------------------------------------------------------------------
    # Publishing (always carries original source link + image)
    # ------------------------------------------------------------------
    @classmethod
    def _publish_item(cls, session, item: RawNewsItem, origin: str = "manual") -> Optional[int]:
        """Create the live /news/ portal article from a regenerated raw item."""
        from src.storage.media_manager import MediaManager

        if not item.regenerated_title or not item.regenerated_body:
            logger.warning(f"[Auto Scroller] item #{item.id} has no regenerated content to publish")
            return None

        # Original source attribution inside the body (portal also renders the link).
        # NOTE: appended AFTER create_editorial_article because BanglaTextNormalizer strips URLs.
        credit = f"মূল সংবাদ (Original Source): {item.source_url}"

        # Download lead image from the original news post
        image_path = None
        if item.image_url:
            try:
                img_meta = MediaManager().download_and_store_image(
                    image_url=item.image_url,
                    source=item.source_name or "auto_scroller",
                    pub_date=datetime.utcnow(),
                )
                if img_meta and img_meta.get("local_path"):
                    image_path = img_meta["local_path"]
                    item.lead_image_path = image_path
            except Exception as img_err:
                logger.warning(f"[Auto Scroller] image download failed for {item.source_url}: {img_err}")

        article_repo = ArticleRepository(session)
        article = article_repo.create_editorial_article(
            title=item.regenerated_title,
            category=item.category or "general",
            content_text=item.regenerated_body.rstrip(),
            author=item.author_raw or None,
            summary=item.regenerated_summary,
            image_path=image_path,
            is_featured=bool((item.meta or {}).get("is_featured")),
            is_breaking=bool((item.meta or {}).get("is_breaking")),
            status="completed",
            source=item.source_name or "Auto Scroller",
            original_source_url=item.source_url,
            creation_origin="AI_SYNTHESIZED",
            position_placement="STANDARD",
        )
        # Append source credit after creation (normalizer strips URLs during creation)
        if item.source_url and item.source_url not in article.content_text:
            article.content_text = f"{article.content_text.rstrip()}\n\n{credit}"

        # Link duplicate / near-duplicate articles (kept separate, never merged)
        related_ids: List[int] = []
        try:
            from src.automation.dedup import link_related_articles
            relations = link_related_articles(session, article)
            related_ids = [r.related_article_id for r in relations]
        except Exception as dedup_err:
            logger.warning(f"[Auto Scroller] related-article linking failed: {dedup_err}")

        article.extracted_entities = {
            **(article.extracted_entities or {}),
            "auto_scroller": {
                "raw_item_id": item.id,
                "origin": origin,
                "similarity_score": item.similarity_score,
                "meaning_retention_score": item.meaning_retention_score,
                "semantic_fidelity": (item.meta or {}).get("semantic_fidelity"),
                "ai_decision": item.ai_decision,
                "credibility_score": item.credibility_score,
                "factuality_score": item.factuality_score,
                "fake_probability_pct": item.fake_probability_pct,
                "original_source_url": item.source_url,
                "related_article_ids": related_ids,
                "publisher": "The Daily AI Alo (publisher credit; original byline/source preserved)",
                "published_at": datetime.utcnow().isoformat(),
            },
        }
        item.article_id = article.id
        item.status = "auto_published" if origin == "auto" else "published_manual"
        session.flush()
        logger.info(f"[Auto Scroller] published item #{item.id} -> article #{article.id}")
        return article.id

    @classmethod
    def manual_publish(cls, item_id: int) -> Dict[str, Any]:
        """Editor publishes a queued raw item to the live portal."""
        with get_db_session() as session:
            item = session.query(RawNewsItem).filter(RawNewsItem.id == item_id).first()
            if not item:
                return {"success": False, "error": f"Raw news item #{item_id} not found."}
            if item.status in ("auto_published", "published_manual"):
                return {"success": False, "error": "Item is already published.", "article_id": item.article_id}
            if item.status == "duplicate" and not item.regenerated_body:
                return {"success": False, "error": "Duplicate item has no regenerated content yet."}
            if not item.regenerated_body:
                return {"success": False, "error": "Item has no regenerated content yet."}
            if item.status == "duplicate":
                # Duplicates are kept separate + linked; the editor makes the final call.
                item.meta = {**(item.meta or {}), "duplicate_manual_publish": True}

            article_id = cls._publish_item(session, item, origin="manual")
            session.commit()
            if not article_id:
                return {"success": False, "error": "Publishing failed."}
            return {
                "success": True, "item_id": item_id, "article_id": article_id,
                "portal_url": f"/news/article/{article_id}",
            }

    @classmethod
    def manual_reject(cls, item_id: int) -> Dict[str, Any]:
        with get_db_session() as session:
            item = session.query(RawNewsItem).filter(RawNewsItem.id == item_id).first()
            if not item:
                return {"success": False, "error": f"Raw news item #{item_id} not found."}
            item.status = "rejected"
            session.flush()
            session.commit()
            return {"success": True, "item_id": item_id, "status": "rejected"}

    # ------------------------------------------------------------------
    # Waiting queue processing (AI Brain / scheduler driven)
    # ------------------------------------------------------------------
    @classmethod
    def process_waiting_queue(cls) -> Dict[str, Any]:
        """Publish all queued items when auto-post is enabled; otherwise report the backlog."""
        with get_db_session() as session:
            cfg = cls.get_config(session)
            queued = (
                session.query(RawNewsItem)
                .filter(RawNewsItem.status == "queued")
                .order_by(RawNewsItem.id.asc())
                .all()
            )
            if not cfg.get("auto_post_enabled", False):
                return {"queued_count": len(queued), "published": 0,
                        "note": "Auto-post is OFF — items wait for manual editor publish."}

            published, skipped = 0, 0
            for item in queued:
                fidelity = (item.meta or {}).get("semantic_fidelity")
                fidelity_ok = fidelity is None or bool(fidelity.get("passed"))
                if item.ai_decision == "AUTO_PUBLISH" and item.regenerated_body and fidelity_ok:
                    if cls._publish_item(session, item, origin="auto"):
                        published += 1
                else:
                    skipped += 1
            session.commit()
            return {"queued_count": len(queued), "published": published, "skipped": skipped}

    # ------------------------------------------------------------------
    # Full cycle: scrape configured source URLs -> pipeline
    # ------------------------------------------------------------------
    @classmethod
    def run_cycle(
        cls,
        source_urls: Optional[List[str]] = None,
        max_items: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Scrape source URLs (config fallback), ingest each through the Auto Scroller pipeline."""
        from src.scraper.custom_portal_ingester import CustomPortalIngester

        with get_db_session() as session:
            cfg = cls.get_config(session)
            if source_urls is None:
                source_urls = [
                    u.strip()
                    for u in str(cfg.get("source_urls", "")).replace("\n", ",").split(",")
                    if u.strip()
                ]
            limit = max_items or int(cfg.get("max_items_per_cycle", 10))

        summary = {
            "scraped": 0, "ingested": 0, "duplicates": 0, "rejected": 0,
            "queued": 0, "auto_published": 0, "failed": 0, "errors": [],
        }

        for url in source_urls[:limit]:
            try:
                raw = CustomPortalIngester.extract_raw_page_data(url)
            except Exception as se:
                summary["failed"] += 1
                summary["errors"].append({"url": url, "error": str(se)})
                continue

            summary["scraped"] += 1
            res = cls.ingest_raw_item(
                source_url=raw["url"],
                title=raw["raw_title"],
                content=raw["raw_content"],
                source_name=raw.get("default_source_name"),
                author=raw.get("author"),
                image_url=raw.get("lead_image_url"),
            )
            status = res.get("status")
            if res.get("skipped") == "duplicate_url":
                summary["duplicates"] += 1
            elif not res.get("success"):
                summary["failed"] += 1
                if res.get("error"):
                    summary["errors"].append({"url": url, "error": res["error"]})
            elif status == "duplicate":
                summary["duplicates"] += 1
            elif status == "rejected":
                summary["rejected"] += 1
            elif status == "auto_published":
                summary["auto_published"] += 1
                summary["ingested"] += 1
            elif status == "queued":
                summary["queued"] += 1
                summary["ingested"] += 1
            else:
                summary["ingested"] += 1

        logger.info(f"[Auto Scroller] cycle complete: {summary}")
        return summary

    # ------------------------------------------------------------------
    # Dashboard helpers
    # ------------------------------------------------------------------
    @classmethod
    def list_recent_items(cls, limit: int = 30, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with get_db_session() as session:
            q = session.query(RawNewsItem).order_by(RawNewsItem.id.desc())
            if status:
                q = q.filter(RawNewsItem.status == status)
            return [item.to_dict() for item in q.limit(limit).all()]

    @classmethod
    def get_stats(cls) -> Dict[str, Any]:
        with get_db_session() as session:
            rows = (
                session.query(RawNewsItem.status, Article.id)
                .outerjoin(Article, RawNewsItem.article_id == Article.id)
                .all()
            )
            counts: Dict[str, int] = {}
            for status, _ in rows:
                counts[status] = counts.get(status, 0) + 1
            return {
                "total": sum(counts.values()),
                "by_status": counts,
                "queued": counts.get("queued", 0),
                "auto_published": counts.get("auto_published", 0),
                "published_manual": counts.get("published_manual", 0),
                "duplicates": counts.get("duplicate", 0),
                "rejected": counts.get("rejected", 0),
            }
