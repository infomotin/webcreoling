"""
Data Repositories for Article & Scrape Log Management.
Provides high-performance batch retrieval for model training, FTS5 full-text search, and upsert logic.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy import func, text, desc
from sqlalchemy.orm import Session, joinedload
from src.common.logger import get_logger
from src.common.normalizer import BanglaTextNormalizer
from src.storage.models import (
    Article,
    ArticleImage,
    ScrapeLog,
    Poll,
    PollOption,
    PollVote,
    NewsletterSubscriber,
    ArticleLike,
    User,
    SiteConfig,
    Advertisement,
    EditorialAuditLog,
    BlockedIP,
    BlockedCountry,
    SecurityThreatLog,
    ArticleBlockLedger,
    AIBrainCustomRule,
    SocialChannelConfig,
    SocialBroadcastLog,
    DataCenterStorageProvider,
    DatabaseReplicaNode,
    DataCenterBackupArchive,
    DataCenterSecurityLog,
    EmergencyVaultState,
    EncryptedVaultBackupRecord,
    OtpCode,
    MessageLog,
    SubscriptionPlan,
    PaymentTransaction,
    UserSubscription,
    RawNewsItem,
)
from src.common.blockchain import BlockchainLedgerEngine

logger = get_logger("webcreoling.storage.repositories")


class ArticleRepository:
    """Repository handling Article and ArticleImage CRUD and queries."""

    def __init__(self, session: Session):
        self.session = session

    def get_by_url(self, url: str) -> Optional[Article]:
        """Fetch article by exact URL."""
        return (
            self.session.query(Article)
            .options(joinedload(Article.images))
            .filter(Article.url == url)
            .first()
        )

    def get_by_id(self, article_id: int) -> Optional[Article]:
        """Fetch article by primary key ID."""
        return (
            self.session.query(Article)
            .options(joinedload(Article.images))
            .filter(Article.id == article_id)
            .first()
        )

    def get_all(
        self,
        status: Optional[str] = None,
        source: Optional[str] = None,
        category: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[Article]:
        """Fetch list of articles with optional filters."""
        query = self.session.query(Article).options(joinedload(Article.images))
        if status:
            query = query.filter(Article.scrape_status == status)
        if source:
            query = query.filter(Article.source == source)
        if category:
            query = query.filter(Article.category == category)
        query = query.order_by(Article.id.desc())
        if offset:
            query = query.offset(offset)
        if limit:
            query = query.limit(limit)
        return query.all()

    def upsert_article(
        self,
        article_data: Dict[str, Any],
        image_records: Optional[List[Dict[str, Any]]] = None,
    ) -> Article:
        """
        Create or update an article along with its downloaded images.
        Normalizes text content and maintains relational links.
        """
        url = article_data["url"]
        existing = self.get_by_url(url)

        # Apply Bangla text normalization
        raw_text = article_data.get("content_text") or ""
        normalized_content = BanglaTextNormalizer.normalize_article_text(raw_text)
        normalized_title = BanglaTextNormalizer.normalize_article_text(article_data.get("title") or "")

        # Normalize author field to string if passed as list or tuple
        raw_author = article_data.get("author")
        if isinstance(raw_author, (list, tuple)):
            clean_author = ", ".join(str(a) for a in raw_author if a)
        elif raw_author:
            clean_author = str(raw_author)
        else:
            clean_author = None

        if existing:
            # Update fields
            existing.title = normalized_title
            existing.content_text = normalized_content
            existing.author = clean_author or existing.author
            existing.published_at = article_data.get("published_at") or existing.published_at
            existing.category = article_data.get("category") or existing.category
            existing.summary = article_data.get("summary") or existing.summary
            existing.scrape_status = article_data.get("scrape_status", existing.scrape_status)
            existing.missing_fields = article_data.get("missing_fields", existing.missing_fields)
            existing.retry_count = article_data.get("retry_count", existing.retry_count)
            existing.js_rendered = article_data.get("js_rendered", existing.js_rendered)
            existing.updated_at = datetime.utcnow()
            article = existing
        else:
            # Create new article
            article = Article(
                url=url,
                source=article_data["source"],
                title=normalized_title,
                author=clean_author,
                published_at=article_data.get("published_at"),
                category=article_data.get("category"),
                content_text=normalized_content,
                summary=article_data.get("summary"),
                extracted_entities=article_data.get("extracted_entities"),
                scrape_status=article_data.get("scrape_status", "completed"),
                missing_fields=article_data.get("missing_fields") or [],
                retry_count=article_data.get("retry_count", 0),
                js_rendered=article_data.get("js_rendered", False),
            )
            self.session.add(article)
            self.session.flush()  # populate article.id

        # Attach images
        if image_records:
            for img_info in image_records:
                # Check if this image URL is already associated
                img_exists = (
                    self.session.query(ArticleImage)
                    .filter(
                        ArticleImage.article_id == article.id,
                        ArticleImage.file_hash == img_info["file_hash"],
                    )
                    .first()
                )
                if not img_exists:
                    image_obj = ArticleImage(
                        article_id=article.id,
                        original_url=img_info["original_url"],
                        local_path=img_info["local_path"],
                        file_hash=img_info["file_hash"],
                        file_size_bytes=img_info.get("file_size_bytes"),
                        mime_type=img_info.get("mime_type"),
                        caption=img_info.get("caption"),
                        is_lead_image=img_info.get("is_lead_image", False),
                        download_status="downloaded",
                    )
                    self.session.add(image_obj)

        self.session.flush()
        return article

    def count_articles(
        self,
        source: Optional[str] = None,
        category: Optional[str] = None,
        scrape_status: Optional[str] = None,
    ) -> int:
        """Count total articles with optional filters."""
        query = self.session.query(func.count(Article.id))
        if source:
            query = query.filter(Article.source == source)
        if category:
            query = query.filter(Article.category == category)
        if scrape_status:
            query = query.filter(Article.scrape_status == scrape_status)
        return query.scalar() or 0

    def get_training_dataset(
        self,
        limit: Optional[int] = None,
        min_char_length: int = 60,
        categories: Optional[List[str]] = None,
    ) -> List[Article]:
        """
        Retrieve high-quality text records for model training.
        Filters out blank or overly short articles and eagerly loads all attributes.
        """
        query = (
            self.session.query(Article)
            .filter(func.length(Article.content_text) >= min_char_length)
            .filter(Article.title != "")
        )
        if categories:
            query = query.filter(Article.category.in_(categories))

        query = query.order_by(Article.id.asc())
        if limit:
            query = query.limit(limit)

        results = query.all()
        # Eagerly access and expunge all attributes to prevent DetachedInstanceError
        for art in results:
            _ = (art.id, art.title, art.content_text, art.category, art.summary, art.extracted_entities)
            self.session.expunge(art)

        return results

    def search_fts(self, query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Search articles using SQLite FTS5 index or MySQL LIKE query.
        """
        cleaned_query = query_text.strip().replace("'", "''").replace('"', '""')
        if not cleaned_query:
            return []

        bind_url = str(getattr(self.session.bind, "url", "")) if self.session.bind else ""
        if "sqlite" in bind_url:
            try:
                # FTS5 MATCH query with BM25 ranking on SQLite
                sql = text(
                    """
                    SELECT a.id, a.title, a.content_text, a.category, a.source, a.published_at, a.url,
                           rank
                    FROM articles_fts fts
                    JOIN articles a ON a.id = fts.id
                    WHERE articles_fts MATCH :query
                    ORDER BY rank
                    LIMIT :limit;
                    """
                )
                tokens = [t for t in cleaned_query.split() if len(t) > 1]
                fts_match_expr = " OR ".join(f'"{t}"*' for t in tokens) if tokens else f'"{cleaned_query}"'
                result = self.session.execute(sql, {"query": fts_match_expr, "limit": top_k}).fetchall()
                records = []
                for row in result:
                    records.append({
                        "id": row[0],
                        "title": row[1],
                        "content_text": row[2],
                        "category": row[3],
                        "source": row[4],
                        "published_at": row[5].isoformat() if row[5] else None,
                        "url": row[6],
                        "score": float(row[7]) if row[7] is not None else 0.0,
                    })
                return records
            except Exception as e:
                logger.debug(f"FTS5 search error (falling back to LIKE): {e}")

        # MySQL / Generic database query
        like_pattern = f"%{cleaned_query}%"
        fallback_res = (
            self.session.query(Article)
            .options(joinedload(Article.images))
            .filter(
                (Article.title.like(like_pattern)) | (Article.content_text.like(like_pattern))
            )
            .order_by(Article.published_at.desc())
            .limit(top_k)
            .all()
        )
        return [a.to_dict() for a in fallback_res]

    def get_lead_hero_article(self) -> Optional[Article]:
        """Fetch the primary highlighted lead/hero story for the newspaper frontpage."""
        # 1. Explicit LEAD placement or featured with pinned priority
        hero = (
            self.session.query(Article)
            .options(joinedload(Article.images))
            .filter(
                (Article.position_placement == "LEAD") | (Article.is_featured == True),
                Article.scrape_status == "completed"
            )
            .order_by(Article.is_pinned.desc(), Article.display_order.asc(), Article.published_at.desc(), Article.id.desc())
            .first()
        )
        if not hero:
            # Fallback to the latest article with images
            hero = (
                self.session.query(Article)
                .options(joinedload(Article.images))
                .filter(Article.scrape_status == "completed")
                .join(ArticleImage)
                .order_by(Article.is_pinned.desc(), Article.display_order.asc(), Article.published_at.desc(), Article.id.desc())
                .first()
            )
        if not hero:
            hero = (
                self.session.query(Article)
                .options(joinedload(Article.images))
                .filter(Article.scrape_status == "completed")
                .order_by(Article.is_pinned.desc(), Article.display_order.asc(), Article.id.desc())
                .first()
            )
        if not hero:
            hero = (
                self.session.query(Article)
                .options(joinedload(Article.images))
                .order_by(Article.id.desc())
                .first()
            )
        return hero

    def get_highlighted_articles(self, limit: int = 6, exclude_id: Optional[int] = None) -> List[Article]:
        """Fetch top auto-highlighted articles with related images for newspaper grid."""
        query = (
            self.session.query(Article)
            .options(joinedload(Article.images))
            .filter(func.length(Article.content_text) > 40)
            .filter(Article.scrape_status == "completed")
        )
        if exclude_id:
            query = query.filter(Article.id != exclude_id)

        # Order by pinned first, display order, featured status, reader engagement, recency
        query = query.order_by(
            Article.is_pinned.desc(),
            Article.display_order.asc(),
            Article.is_featured.desc(),
            Article.likes_count.desc(),
            Article.views_count.desc(),
            Article.id.desc()
        ).limit(limit)

        return query.all()

    def get_breaking_news(self, limit: int = 5) -> List[Article]:
        """Fetch breaking news items for ticker."""
        breaking = (
            self.session.query(Article)
            .filter((Article.is_breaking == True) | (Article.position_placement == "BREAKING"))
            .filter(Article.scrape_status == "completed")
            .order_by(Article.is_pinned.desc(), Article.display_order.asc(), Article.published_at.desc(), Article.id.desc())
            .limit(limit)
            .all()
        )
        if not breaking:
            breaking = (
                self.session.query(Article)
                .filter(Article.scrape_status == "completed")
                .order_by(Article.is_pinned.desc(), Article.display_order.asc(), Article.id.desc())
                .limit(limit)
                .all()
            )
        if not breaking:
            breaking = (
                self.session.query(Article)
                .order_by(Article.id.desc())
                .limit(limit)
                .all()
            )
        return breaking

    def get_trending_articles(self, limit: int = 5) -> List[Article]:
        """Fetch most read / most trending articles."""
        return (
            self.session.query(Article)
            .options(joinedload(Article.images))
            .filter(Article.scrape_status == "completed")
            .order_by((Article.views_count * 2 + Article.likes_count * 5).desc(), Article.id.desc())
            .limit(limit)
            .all()
        )

    def get_articles_by_category(self, category: str, limit: int = 4, exclude_id: Optional[int] = None) -> List[Article]:
        """Fetch articles belonging to a specific news category with synonym support and fallback."""
        cat_lower = (category or "").lower().strip()
        synonym_map = {
            "politics": ["politics", "রাজনীতি", "national"],
            "bangladesh": ["bangladesh", "national", "বাংলাদেশ", "জাতীয়"],
            "national": ["national", "bangladesh", "বাংলাদেশ", "জাতীয়"],
            "international": ["international", "world", "আন্তর্জাতিক", "বিশ্ব"],
            "world": ["world", "international", "আন্তর্জাতিক", "বিশ্ব"],
            "business": ["business", "economy", "বাণিজ্য", "অর্থনীতি", "শেয়ারবাজার"],
            "technology": ["technology", "tech", "বিজ্ঞান ও প্রযুক্তি", "প্রযুক্তি", "বিজ্ঞান"],
            "tech": ["tech", "technology", "বিজ্ঞান ও প্রযুক্তি", "প্রযুক্তি"],
            "sports": ["sports", "খেলাধুলা", "খেলা", "ক্রিকেট", "ফুটবল"],
            "entertainment": ["entertainment", "বিনোদন", "সংস্কৃতি", "তারকা"],
        }
        cats_to_match = synonym_map.get(cat_lower, [cat_lower])
        query = (
            self.session.query(Article)
            .options(joinedload(Article.images))
            .filter(Article.category.in_(cats_to_match))
            .filter(Article.scrape_status == "completed")
        )
        if exclude_id:
            query = query.filter(Article.id != exclude_id)
        results = query.order_by(
            Article.is_pinned.desc(),
            Article.display_order.asc(),
            Article.published_at.desc(),
            Article.id.desc()
        ).limit(limit).all()

        # If not enough articles for this specific category, backfill with completed articles to avoid empty gaps
        if len(results) < limit:
            existing_ids = [r.id for r in results]
            if exclude_id:
                existing_ids.append(exclude_id)
            filler_query = (
                self.session.query(Article)
                .options(joinedload(Article.images))
                .filter(Article.scrape_status == "completed")
                .filter(~Article.id.in_(existing_ids))
                .order_by(Article.id.desc())
                .limit(limit - len(results))
            )
            filler = filler_query.all()
            results.extend(filler)

        return results

    def get_related_articles(self, article_id: int, category: Optional[str] = None, limit: int = 3) -> List[Article]:
        """Fetch related articles based on category and recency."""
        query = (
            self.session.query(Article)
            .options(joinedload(Article.images))
            .filter(Article.id != article_id)
        )
        if category:
            query = query.filter(Article.category == category)
        return query.order_by(Article.id.desc()).limit(limit).all()

    def increment_views(self, article_id: int) -> int:
        """Increment view count for an article."""
        article = self.session.query(Article).filter(Article.id == article_id).first()
        if article:
            article.views_count = (article.views_count or 0) + 1
            self.session.flush()
            return article.views_count
        return 0

    def toggle_like(self, article_id: int, voter_ip: str) -> Dict[str, Any]:
        """Toggle reader like on an article."""
        article = self.session.query(Article).filter(Article.id == article_id).first()
        if not article:
            return {"liked": False, "likes_count": 0}

        existing_like = (
            self.session.query(ArticleLike)
            .filter(ArticleLike.article_id == article_id, ArticleLike.voter_ip == voter_ip)
            .first()
        )

        if existing_like:
            self.session.delete(existing_like)
            article.likes_count = max(0, (article.likes_count or 0) - 1)
            liked = False
        else:
            new_like = ArticleLike(article_id=article_id, voter_ip=voter_ip)
            self.session.add(new_like)
            article.likes_count = (article.likes_count or 0) + 1
            liked = True

        self.session.flush()
        return {"liked": liked, "likes_count": article.likes_count}

    def create_editorial_article(
        self,
        title: str,
        category: str,
        content_text: str,
        author: Optional[str] = None,
        summary: Optional[str] = None,
        image_path: Optional[str] = None,
        is_featured: bool = False,
        is_breaking: bool = False,
        status: str = "completed",
        scheduled_at: Optional[datetime] = None,
        source: Optional[str] = None,
        original_source_url: Optional[str] = None,
        source_status: str = "ACTIVE",
        source_removed_notice: Optional[str] = None,
        creation_origin: str = "MANUAL",
        position_placement: str = "STANDARD",
        display_order: int = 0,
        is_pinned: bool = False,
    ) -> Article:
        """Create and publish a new article directly from the editorial desk."""
        import uuid
        import hashlib

        normalized_title = BanglaTextNormalizer.normalize_article_text(title.strip())
        normalized_content = BanglaTextNormalizer.normalize_article_text(content_text.strip())
        slug = uuid.uuid4().hex[:12]
        url = f"https://daily-ai-alo.news/editorial/{slug}"
        orig_url = original_source_url.strip() if original_source_url else url

        # Determine published_at vs scheduled_at
        pub_at = None
        if scheduled_at and scheduled_at > datetime.utcnow():
            status = "scheduled"
        elif status == "completed":
            pub_at = datetime.utcnow()

        # Map placement to flags if specified
        if position_placement in ["LEAD", "FEATURED"]:
            is_featured = True
        elif position_placement == "BREAKING":
            is_breaking = True

        src_name = source.strip() if source else ("The Daily AI Alo সম্পাদকীয় ডেস্ক" if creation_origin == "MANUAL" else "সংবাদ সূত্র")

        article = Article(
            url=url,
            original_source_url=orig_url,
            source=src_name,
            source_status=source_status or "ACTIVE",
            source_removed_notice=source_removed_notice,
            creation_origin=creation_origin or "MANUAL",
            position_placement=position_placement or "STANDARD",
            display_order=display_order or 0,
            is_pinned=is_pinned or False,
            title=normalized_title,
            author=author.strip() if author else "দি ডেইলি এআই আলো নিজস্ব প্রতিবেদক",
            published_at=pub_at,
            scheduled_at=scheduled_at,
            category=category.strip() or "general",
            content_text=normalized_content,
            summary=summary.strip() if summary else normalized_content[:200] + "...",
            scrape_status=status,
            is_featured=is_featured,
            is_breaking=is_breaking,
            views_count=0,
            likes_count=0,
            shares_count=0,
        )
        self.session.add(article)
        self.session.flush()

        if image_path and image_path.strip():
            clean_path = image_path.strip().lstrip("/")
            file_hash = hashlib.sha256(clean_path.encode("utf-8")).hexdigest()[:16]
            img_obj = ArticleImage(
                article_id=article.id,
                original_url=url,
                local_path=clean_path,
                file_hash=file_hash,
                is_lead_image=True,
                download_status="downloaded",
            )
            self.session.add(img_obj)
            self.session.flush()

        # Mint immutable cryptographic block in blockchain ledger
        try:
            ledger_repo = BlockchainLedgerRepository(self.session)
            ledger_repo.mint_block_for_article(article.id)
        except Exception as e:
            logger.warning(f"Could not auto-mint block for new article #{article.id}: {e}")

        return article

    def update_editorial_article(
        self,
        article_id: int,
        title: Optional[str] = None,
        category: Optional[str] = None,
        author: Optional[str] = None,
        summary: Optional[str] = None,
        content_text: Optional[str] = None,
        image_path: Optional[str] = None,
        is_featured: Optional[bool] = None,
        is_breaking: Optional[bool] = None,
        status: Optional[str] = None,
        scheduled_at: Optional[datetime] = None,
        source: Optional[str] = None,
        original_source_url: Optional[str] = None,
        source_status: Optional[str] = None,
        source_removed_notice: Optional[str] = None,
        creation_origin: Optional[str] = None,
        position_placement: Optional[str] = None,
        display_order: Optional[int] = None,
        is_pinned: Optional[bool] = None,
    ) -> Optional[Article]:
        """Update an existing article from the editorial desk."""
        import hashlib
        article = self.get_by_id(article_id)
        if not article:
            return None

        if title is not None:
            article.title = BanglaTextNormalizer.normalize_article_text(title.strip())
        if category is not None:
            article.category = category.strip()
        if author is not None:
            article.author = author.strip()
        if source is not None:
            article.source = source.strip()
        if summary is not None:
            article.summary = summary.strip()
        if content_text is not None:
            article.content_text = BanglaTextNormalizer.normalize_article_text(content_text.strip())
        if is_featured is not None:
            article.is_featured = is_featured
        if is_breaking is not None:
            article.is_breaking = is_breaking
        if original_source_url is not None:
            article.original_source_url = original_source_url.strip()
        if source_status is not None:
            article.source_status = source_status.strip()
        if source_removed_notice is not None:
            article.source_removed_notice = source_removed_notice.strip()
        if creation_origin is not None:
            article.creation_origin = creation_origin.strip()
        if position_placement is not None:
            article.position_placement = position_placement.strip()
            if position_placement in ["LEAD", "FEATURED"]:
                article.is_featured = True
            elif position_placement == "BREAKING":
                article.is_breaking = True
        if display_order is not None:
            article.display_order = display_order
        if is_pinned is not None:
            article.is_pinned = is_pinned
        if scheduled_at is not None:
            article.scheduled_at = scheduled_at
            if scheduled_at > datetime.utcnow():
                article.scrape_status = "scheduled"
                article.published_at = None
        if status is not None:
            article.scrape_status = status
            if status == "completed" and not article.published_at:
                article.published_at = datetime.utcnow()
                article.scheduled_at = None

        if image_path and image_path.strip():
            clean_path = image_path.strip().lstrip("/")
            file_hash = hashlib.sha256(clean_path.encode("utf-8")).hexdigest()[:16]
            if article.images:
                lead_img = article.images[0]
                lead_img.local_path = clean_path
                lead_img.file_hash = file_hash
            else:
                img_obj = ArticleImage(
                    article_id=article.id,
                    original_url=article.url,
                    local_path=clean_path,
                    file_hash=file_hash,
                    is_lead_image=True,
                    download_status="downloaded",
                )
                self.session.add(img_obj)

        article.updated_at = datetime.utcnow()
        self.session.flush()

        # Re-mint cryptographic block to seal updated content in ledger
        try:
            ledger_repo = BlockchainLedgerRepository(self.session)
            ledger_repo.mint_block_for_article(article.id)
        except Exception as e:
            logger.warning(f"Could not re-mint block for updated article #{article.id}: {e}")

        return article

    def update_article_placement(
        self,
        article_id: int,
        position_placement: Optional[str] = None,
        display_order: Optional[int] = None,
        is_pinned: Optional[bool] = None,
        is_featured: Optional[bool] = None,
        is_breaking: Optional[bool] = None,
        source_status: Optional[str] = None,
        source_removed_notice: Optional[str] = None,
    ) -> Optional[Article]:
        """Update placement, sequence ordering, pin status, and source status."""
        article = self.get_by_id(article_id)
        if not article:
            return None
        if position_placement is not None:
            article.position_placement = position_placement
            if position_placement in ["LEAD", "FEATURED"]:
                article.is_featured = True
            elif position_placement == "BREAKING":
                article.is_breaking = True
        if display_order is not None:
            article.display_order = display_order
        if is_pinned is not None:
            article.is_pinned = is_pinned
        if is_featured is not None:
            article.is_featured = is_featured
        if is_breaking is not None:
            article.is_breaking = is_breaking
        if source_status is not None:
            article.source_status = source_status
        if source_removed_notice is not None:
            article.source_removed_notice = source_removed_notice
        article.updated_at = datetime.utcnow()
        self.session.flush()
        return article

    def check_source_url_status(self, article_id: int) -> Dict[str, Any]:
        """Audit whether an article's original source URL is still alive or has been removed at the source."""
        import httpx
        article = self.get_by_id(article_id)
        if not article:
            return {"status": "not_found", "message": "Article not found"}

        target_url = article.original_source_url or article.url
        if not target_url or not target_url.startswith(("http://", "https://")):
            return {"status": "manual", "source_status": article.source_status or "ACTIVE", "message": "Manual / In-house article"}

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            status_code = 200
            try:
                with httpx.Client(timeout=6, headers=headers, follow_redirects=True) as client:
                    res = client.head(target_url)
                    if res.status_code in [404, 410, 403]:
                        res_get = client.get(target_url)
                        status_code = res_get.status_code
                    else:
                        status_code = res.status_code
            except Exception:
                status_code = 404

            if status_code in [404, 410]:
                article.source_status = "REMOVED_AT_SOURCE"
                if not article.source_removed_notice:
                    article.source_removed_notice = "মূল উৎস থেকে এই সংবাদটি সরিয়ে ফেলা হয়েছে বা লিঙ্কটি অনুপলব্ধ। তবে The Daily AI Alo পোর্টালে এর একটি ভেরিফায়েড ও ক্রিপ্টোগ্রাফিক আর্কাইভড কপি সংরক্ষিত রয়েছে।"
                status_label = "REMOVED_AT_SOURCE"
            elif status_code >= 500:
                article.source_status = "UNAVAILABLE"
                status_label = "UNAVAILABLE"
            else:
                article.source_status = "ACTIVE"
                status_label = "ACTIVE"

            article.source_last_checked_at = datetime.utcnow()
            self.session.flush()
            return {
                "success": True,
                "status": "success",
                "article_id": article_id,
                "url": target_url,
                "http_status": status_code,
                "source_status": status_label,
                "is_active": (status_label == "ACTIVE"),
            }
        except Exception as e:
            logger.warning(f"Error checking source status for article #{article_id} ({target_url}): {e}")
            article.source_last_checked_at = datetime.utcnow()
            self.session.flush()
            return {
                "success": True,
                "status": "success",
                "article_id": article_id,
                "url": target_url,
                "error": str(e),
                "source_status": article.source_status or "UNAVAILABLE",
                "is_active": False,
            }

    def get_scheduled_articles(self) -> List[Article]:
        """Fetch all articles queued for future scheduled release."""
        return (
            self.session.query(Article)
            .options(joinedload(Article.images))
            .filter((Article.scrape_status == "scheduled") | (Article.scheduled_at != None))
            .order_by(Article.scheduled_at.asc(), Article.id.desc())
            .all()
        )

    def process_scheduled_publishing(self) -> int:
        """Scan and automatically publish articles whose scheduled release time has arrived."""
        now = datetime.utcnow()
        pending = (
            self.session.query(Article)
            .filter(Article.scrape_status == "scheduled", Article.scheduled_at <= now)
            .all()
        )
        published_count = 0
        for art in pending:
            art.scrape_status = "completed"
            art.published_at = now
            published_count += 1
        if published_count > 0:
            self.session.flush()
            logger.info(f"Auto-published {published_count} scheduled articles at {now.isoformat()}")
        return published_count

    def delete_article(self, article_id: int) -> bool:
        """Permanently delete an article and its associated images."""
        article = self.session.query(Article).filter(Article.id == article_id).first()
        if article:
            self.session.delete(article)
            self.session.flush()
            return True
        return False

    def approve_article(self, article_id: int) -> bool:
        """Approve and publish a draft or pending article."""
        article = self.session.query(Article).filter(Article.id == article_id).first()
        if article:
            article.scrape_status = "completed"
            if not article.published_at:
                article.published_at = datetime.utcnow()
            article.updated_at = datetime.utcnow()
            self.session.flush()
            return True
        return False

    def archive_article(self, article_id: int) -> bool:
        """Move an article to the archived state."""
        article = self.session.query(Article).filter(Article.id == article_id).first()
        if article:
            article.scrape_status = "archived"
            article.is_featured = False
            article.is_breaking = False
            article.updated_at = datetime.utcnow()
            self.session.flush()
            return True
        return False

    def restore_article(self, article_id: int) -> bool:
        """Restore an archived article back to published status."""
        article = self.session.query(Article).filter(Article.id == article_id).first()
        if article:
            article.scrape_status = "completed"
            article.updated_at = datetime.utcnow()
            self.session.flush()
            return True
        return False

    def list_editorial_articles(
        self,
        search_query: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        is_featured: Optional[bool] = None,
        is_breaking: Optional[bool] = None,
        page: int = 1,
        page_size: int = 15,
    ) -> Dict[str, Any]:
        """Fetch filtered and paginated articles for the newsroom editorial management desk."""
        query = self.session.query(Article).options(joinedload(Article.images))

        if search_query and search_query.strip():
            q = f"%{search_query.strip()}%"
            query = query.filter((Article.title.like(q)) | (Article.content_text.like(q)) | (Article.author.like(q)))

        if category and category.strip():
            query = query.filter(Article.category == category.strip())

        if status and status.strip():
            if status == "pending":
                query = query.filter(Article.scrape_status.in_(["pending", "draft", "partial"]))
            else:
                query = query.filter(Article.scrape_status == status.strip())

        if is_featured is not None:
            query = query.filter(Article.is_featured == is_featured)

        if is_breaking is not None:
            query = query.filter(Article.is_breaking == is_breaking)

        total_count = query.count()
        articles = (
            query.order_by(Article.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        total_pages = max(1, (total_count + page_size - 1) // page_size)

        return {
            "articles": articles,
            "total_count": total_count,
            "page": page,
            "total_pages": total_pages,
            "search_query": search_query or "",
            "category_filter": category or "",
            "status_filter": status or "",
        }

    def get_editorial_kpis(self) -> Dict[str, int]:
        """Fetch real-time newsroom key performance indicators."""
        total_articles = self.session.query(func.count(Article.id)).scalar() or 0
        published_count = self.session.query(func.count(Article.id)).filter(Article.scrape_status == "completed").scalar() or 0
        pending_count = self.session.query(func.count(Article.id)).filter(Article.scrape_status.in_(["draft", "pending", "partial"])).scalar() or 0
        archived_count = self.session.query(func.count(Article.id)).filter(Article.scrape_status == "archived").scalar() or 0
        featured_count = self.session.query(func.count(Article.id)).filter(Article.is_featured == True).scalar() or 0
        breaking_count = self.session.query(func.count(Article.id)).filter(Article.is_breaking == True).scalar() or 0

        return {
            "total_articles": total_articles,
            "published_count": published_count,
            "pending_count": pending_count,
            "archived_count": archived_count,
            "featured_count": featured_count,
            "breaking_count": breaking_count,
        }

    def get_database_stats(self) -> Dict[str, Any]:
        """Fetch general article and database statistics."""
        kpis = self.get_editorial_kpis()
        return {
            "total_articles": kpis.get("total_articles", 0),
            "completed_articles": kpis.get("published_count", 0),
            "pending_articles": kpis.get("pending_count", 0),
            "archived_articles": kpis.get("archived_count", 0),
            "featured_articles": kpis.get("featured_count", 0),
            "breaking_articles": kpis.get("breaking_count", 0),
        }

    def toggle_featured(self, article_id: int) -> bool:
        """Toggle featured/lead status of an article."""
        article = self.session.query(Article).filter(Article.id == article_id).first()
        if article:
            article.is_featured = not bool(article.is_featured)
            self.session.flush()
            return article.is_featured
        return False

    def toggle_breaking(self, article_id: int) -> bool:
        """Toggle breaking news ticker status of an article."""
        article = self.session.query(Article).filter(Article.id == article_id).first()
        if article:
            article.is_breaking = not bool(article.is_breaking)
            self.session.flush()
            return article.is_breaking
        return False

    def get_section_page_data(self, category: str, page: int = 1, page_size: int = 12) -> Dict[str, Any]:
        """Fetch section articles, lead hero for the category, and trending in that section."""
        query = (
            self.session.query(Article)
            .options(joinedload(Article.images))
            .filter(Article.category == category)
        )
        total_count = query.count()

        # Lead hero in section: first article with image or first article
        section_hero = query.filter(Article.images.any()).order_by(Article.id.desc()).first()
        if not section_hero:
            section_hero = query.order_by(Article.id.desc()).first()

        exclude_id = section_hero.id if section_hero else None

        articles_query = query
        if exclude_id and page == 1:
            articles_query = articles_query.filter(Article.id != exclude_id)

        articles = (
            articles_query
            .order_by(Article.published_at.desc(), Article.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        # Section trending
        section_trending = (
            query.order_by((Article.views_count * 2 + Article.likes_count * 5).desc(), Article.id.desc())
            .limit(5)
            .all()
        )

        total_pages = max(1, (total_count + page_size - 1) // page_size)

        return {
            "category": category,
            "section_hero": section_hero,
            "articles": articles,
            "section_trending": section_trending,
            "total_count": total_count,
            "page": page,
            "total_pages": total_pages,
        }

    def get_automation_live_feed(self, limit: int = 25, max_allowed_fake_pct: float = 50.0) -> List[Dict[str, Any]]:
        """Fetch real-time feed of recently processed/scraped articles with live fact-checking and fake news metrics."""
        from src.nlp.fake_news_detector import FakeNewsDetectorEngine
        articles = (
            self.session.query(Article)
            .options(joinedload(Article.images))
            .order_by(Article.id.desc())
            .limit(limit)
            .all()
        )

        feed = []
        for art in articles:
            entities = art.extracted_entities or {}
            fake_analysis = entities.get("fake_news_analysis")
            if not fake_analysis:
                # Calculate on the fly and persist
                fake_analysis = FakeNewsDetectorEngine.evaluate(
                    title=art.title,
                    content=art.content_text,
                    source=art.source,
                    author=art.author,
                    max_allowed_fake_pct=max_allowed_fake_pct,
                )
                entities["fake_news_analysis"] = fake_analysis
                art.extracted_entities = entities
                self.session.flush()

            lead_img = None
            if art.images:
                lead_img = art.images[0].local_path or art.images[0].original_url

            # Formatting decision badge
            is_fake = fake_analysis["fake_probability_pct"] > max_allowed_fake_pct
            if art.scrape_status == "completed":
                status_badge = "PUBLISHED"
                status_label = "পোর্টাল ও সোশ্যাল মিডিয়ায় প্রকাশিত"
                badge_class = "badge-success"
            elif art.scrape_status == "pending":
                status_badge = "PENDING_REVIEW"
                status_label = "রিভিউ কিউতে অপেক্ষমান"
                badge_class = "badge-warning"
            else:
                status_badge = "QUARANTINED"
                status_label = "স্থগিত / কোয়ারেন্টাইন"
                badge_class = "badge-danger" if is_fake else "badge-secondary"

            feed.append({
                "id": art.id,
                "title": art.title,
                "source": art.source,
                "category": art.category or "জাতীয়",
                "author": art.author or art.source,
                "published_at": art.published_at.strftime("%I:%M %p, %d %b") if art.published_at else (art.created_at.strftime("%I:%M %p, %d %b") if art.created_at else "এখন"),
                "lead_image": lead_img,
                "scrape_status": art.scrape_status,
                "status_badge": status_badge,
                "status_label": status_label,
                "badge_class": badge_class,
                "is_ledger_verified": bool(art.is_ledger_verified),
                "block_number": art.block_number,
                "fake_probability_pct": fake_analysis.get("fake_probability_pct", 0.0),
                "factuality_score": fake_analysis.get("factuality_score", 100.0),
                "clickbait_score": fake_analysis.get("clickbait_score", 0.0),
                "verdict": fake_analysis.get("verdict", "AUTHENTIC"),
                "verdict_label": fake_analysis.get("verdict_label", "যাচাইকৃত"),
                "badge_color": fake_analysis.get("badge_color", "#10b981"),
                "is_publishable": fake_analysis.get("is_publishable", True),
                "decision_text": fake_analysis.get("decision_text", ""),
                "flags": fake_analysis.get("flags", []),
                "url": f"/news/{art.id}",
            })

        return feed

    def get_automation_kpis(self) -> Dict[str, Any]:
        """Fetch high-level counters for the automation hub."""
        total = self.session.query(func.count(Article.id)).scalar() or 0
        published = self.session.query(func.count(Article.id)).filter(Article.scrape_status == "completed").scalar() or 0
        pending = self.session.query(func.count(Article.id)).filter(Article.scrape_status.in_(["pending", "draft", "partial"])).scalar() or 0
        quarantined = self.session.query(func.count(Article.id)).filter(Article.scrape_status == "archived").scalar() or 0
        blockchain_sealed = self.session.query(func.count(Article.id)).filter(Article.is_ledger_verified == True).scalar() or 0

        return {
            "total_articles": total,
            "published_articles": published,
            "pending_articles": pending,
            "quarantined_articles": quarantined,
            "blockchain_sealed": blockchain_sealed,
        }

    def get_available_archive_dates(self, limit: int = 60) -> List[str]:
        """Fetch distinct dates available in the archive."""
        try:
            dates = (
                self.session.query(func.date(Article.published_at))
                .filter(Article.published_at != None)
                .distinct()
                .order_by(func.date(Article.published_at).desc())
                .limit(limit)
                .all()
            )
            date_list = [d[0] for d in dates if d[0]]
            if not date_list:
                dates_c = (
                    self.session.query(func.date(Article.created_at))
                    .distinct()
                    .order_by(func.date(Article.created_at).desc())
                    .limit(limit)
                    .all()
                )
                date_list = [d[0] for d in dates_c if d[0]]
            return date_list or [datetime.utcnow().strftime("%Y-%m-%d")]
        except Exception:
            return [datetime.utcnow().strftime("%Y-%m-%d")]

    def get_archive_articles(
        self,
        date_str: Optional[str] = None,
        category: Optional[str] = None,
        page: int = 1,
        page_size: int = 15,
    ) -> Dict[str, Any]:
        """Fetch articles for the selected archive date with optional category filtering and pagination."""
        available_dates = self.get_available_archive_dates()
        target_date = date_str or (available_dates[0] if available_dates else datetime.utcnow().strftime("%Y-%m-%d"))

        query = self.session.query(Article).options(joinedload(Article.images))

        # Date filter
        query = query.filter(
            (func.date(Article.published_at) == target_date) | 
            (func.date(Article.created_at) == target_date)
        )

        if category:
            query = query.filter(Article.category == category)

        total_count = query.count()
        articles = (
            query.order_by(Article.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        total_pages = max(1, (total_count + page_size - 1) // page_size)

        return {
            "selected_date": target_date,
            "available_dates": available_dates,
            "articles": articles,
            "total_count": total_count,
            "page": page,
            "total_pages": total_pages,
            "category": category,
        }

    def get_database_stats(self) -> Dict[str, Any]:
        """Aggregate statistical summary of database records."""
        total_articles = self.session.query(func.count(Article.id)).scalar() or 0
        total_images = self.session.query(func.count(ArticleImage.id)).scalar() or 0
        total_views = self.session.query(func.sum(Article.views_count)).scalar() or 0
        total_likes = self.session.query(func.sum(Article.likes_count)).scalar() or 0

        # Group by source
        source_counts = dict(
            self.session.query(Article.source, func.count(Article.id))
            .group_by(Article.source)
            .all()
        )

        # Group by category
        category_counts = dict(
            self.session.query(Article.category, func.count(Article.id))
            .group_by(Article.category)
            .all()
        )

        # Status breakdown
        status_counts = dict(
            self.session.query(Article.scrape_status, func.count(Article.id))
            .group_by(Article.scrape_status)
            .all()
        )

        return {
            "total_articles": total_articles,
            "total_images": total_images,
            "total_views": total_views,
            "total_likes": total_likes,
            "by_source": source_counts,
            "by_category": category_counts,
            "by_status": status_counts,
        }


class ScrapeLogRepository:
    """Repository handling ScrapeLog records."""

    def __init__(self, session: Session):
        self.session = session

    def start_log(self, source: str, job_type: str = "crawl") -> ScrapeLog:
        """Create an active scraping log."""
        log = ScrapeLog(source=source, job_type=job_type, status="in_progress")
        self.session.add(log)
        self.session.flush()
        return log

    def finish_log(
        self,
        log_id: int,
        articles_found: int,
        articles_saved: int,
        images_downloaded: int,
        errors_count: int,
        status: str = "completed",
        error_details: Optional[str] = None,
    ) -> Optional[ScrapeLog]:
        """Complete a scrape log."""
        log = self.session.query(ScrapeLog).filter(ScrapeLog.id == log_id).first()
        if log:
            log.end_time = datetime.utcnow()
            log.articles_found = articles_found
            log.articles_saved = articles_saved
            log.images_downloaded = images_downloaded
            log.errors_count = errors_count
            log.status = status
            log.error_details = error_details
            self.session.flush()
        return log


from src.storage.models import User


class UserRepository:
    """Repository managing User accounts and Role-Based Access Control."""

    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, user_id: int) -> Optional[User]:
        """Retrieve user by ID."""
        return self.session.query(User).filter(User.id == user_id).first()

    def get_by_username(self, username: str) -> Optional[User]:
        """Retrieve user by username."""
        return self.session.query(User).filter(User.username == username.strip()).first()

    def get_by_email(self, email: str) -> Optional[User]:
        """Retrieve user by email."""
        return self.session.query(User).filter(User.email == email.strip().lower()).first()

    def create_user(
        self,
        username: str,
        email: str,
        password: str,
        role: str = "viewer",
    ) -> User:
        """Create and persist a new user with hashed password."""
        user = User(
            username=username.strip(),
            email=email.strip().lower(),
            role=role.lower(),
        )
        user.set_password(password)
        self.session.add(user)
        self.session.flush()
        return user

    def authenticate(self, username_or_email: str, password: str) -> Optional[User]:
        """Authenticate user credentials."""
        identifier = username_or_email.strip()
        user = (
            self.session.query(User)
            .filter((User.username == identifier) | (User.email == identifier.lower()))
            .first()
        )
        if user and user.is_active and user.check_password(password):
            return user
        return None

    def list_all_users(self) -> List[User]:
        """List all users in the system."""
        return self.session.query(User).order_by(User.id.asc()).all()

    get_all_users = list_all_users

    def update_role(self, user_id: int, new_role: str) -> Optional[User]:
        """Change a user's permission role."""
        user = self.get_by_id(user_id)
        if user:
            user.role = new_role.lower()
            self.session.flush()
        return user

    def seed_default_users(self, force_reset_passwords: bool = False) -> Dict[str, str]:
        """Seed default accounts for each role if no users exist or update if forced."""
        default_accounts = [
            ("admin", "admin@webcreoling.ai", "admin123", "admin"),
            ("editor", "editor@webcreoling.ai", "editor123", "editor"),
            ("analyst", "analyst@webcreoling.ai", "analyst123", "analyst"),
            ("viewer", "viewer@webcreoling.ai", "viewer123", "viewer"),
        ]
        created = {}
        for username, email, pwd, role in default_accounts:
            existing = self.get_by_username(username)
            if not existing:
                self.create_user(username=username, email=email, password=pwd, role=role)
                created[username] = role
            elif force_reset_passwords:
                existing.set_password(pwd)
                existing.role = role
                existing.is_active = True
                self.session.flush()
                created[username] = role
        return created


class PortalRepository:
    """Repository managing Opinion Polls, Voting, and Newsletter Subscribers."""

    def __init__(self, session: Session):
        self.session = session

    def get_active_poll(self) -> Optional[Poll]:
        """Fetch current active opinion poll with options."""
        return (
            self.session.query(Poll)
            .options(joinedload(Poll.options))
            .filter(Poll.is_active == True)
            .order_by(Poll.id.desc())
            .first()
        )

    def vote_poll(self, poll_id: int, option_id: int, voter_ip: str) -> Dict[str, Any]:
        """Cast vote for a poll option with duplicate IP check."""
        poll = self.session.query(Poll).filter(Poll.id == poll_id, Poll.is_active == True).first()
        if not poll:
            return {"status": "error", "message": "ভোটগ্রহণ সক্রিয় নয় বা পাওয়া যায়নি।"}

        existing_vote = (
            self.session.query(PollVote)
            .filter(PollVote.poll_id == poll_id, PollVote.voter_ip == voter_ip)
            .first()
        )
        if existing_vote:
            return {
                "status": "already_voted",
                "message": "আপনি ইতিমধ্যে এই জরিপে ভোট দিয়েছেন।",
                "poll": poll.to_dict(),
            }

        option = self.session.query(PollOption).filter(PollOption.id == option_id, PollOption.poll_id == poll_id).first()
        if not option:
            return {"status": "error", "message": "অবৈধ অপশন।"}

        option.votes_count = (option.votes_count or 0) + 1
        poll.total_votes = (poll.total_votes or 0) + 1
        vote = PollVote(poll_id=poll_id, option_id=option_id, voter_ip=voter_ip)
        self.session.add(vote)
        self.session.flush()

        return {
            "status": "success",
            "message": "আপনার ভোট সফলভাবে গ্রহণ করা হয়েছে!",
            "poll": poll.to_dict(),
        }

    def create_poll(self, question: str, options: List[str], category: str = "national") -> Poll:
        """Create a new poll with choices."""
        poll = Poll(question=question.strip(), category=category, is_active=True, total_votes=0)
        self.session.add(poll)
        self.session.flush()

        for opt in options:
            if opt.strip():
                p_opt = PollOption(poll_id=poll.id, option_text=opt.strip(), votes_count=0)
                self.session.add(p_opt)

        self.session.flush()
        return poll

    def list_all_polls(self) -> List[Poll]:
        """List all polls for editorial administration."""
        return self.session.query(Poll).options(joinedload(Poll.options)).order_by(Poll.id.desc()).all()

    def toggle_poll_status(self, poll_id: int) -> bool:
        """Toggle poll active/inactive status."""
        poll = self.session.query(Poll).filter(Poll.id == poll_id).first()
        if poll:
            poll.is_active = not bool(poll.is_active)
            self.session.flush()
            return poll.is_active
        return False

    def add_subscriber(self, email: str) -> Dict[str, Any]:
        """Add email subscriber to newsletter."""
        cleaned = email.strip().lower()
        if not cleaned or "@" not in cleaned:
            return {"status": "error", "message": "সঠিক ইমেইল ঠিকানা প্রদান করুন।"}

        existing = self.session.query(NewsletterSubscriber).filter(NewsletterSubscriber.email == cleaned).first()
        if existing:
            return {"status": "already_subscribed", "message": "আপনি আগেই সাবস্ক্রাইব করেছেন!"}

        sub = NewsletterSubscriber(email=cleaned)
        self.session.add(sub)
        self.session.flush()
        return {"status": "success", "message": "ধন্যবাদ! ব্রেকিং নিউজ ও সাপ্তাহিক বুলেটিনে যুক্ত হয়েছেন।"}

    def list_subscribers(self) -> List[NewsletterSubscriber]:
        """List all newsletter subscribers."""
        return self.session.query(NewsletterSubscriber).order_by(NewsletterSubscriber.id.desc()).all()

    def delete_poll(self, poll_id: int) -> bool:
        """Delete an opinion poll and its options/votes."""
        poll = self.session.query(Poll).filter(Poll.id == poll_id).first()
        if poll:
            self.session.delete(poll)
            self.session.flush()
            return True
        return False

    def delete_subscriber(self, subscriber_id: int) -> bool:
        """Delete a newsletter subscriber."""
        sub = self.session.query(NewsletterSubscriber).filter(NewsletterSubscriber.id == subscriber_id).first()
        if sub:
            self.session.delete(sub)
            self.session.flush()
            return True
        return False

    def seed_default_poll(self) -> None:
        """Seed initial active poll if none exists."""
        active = self.get_active_poll()
        if not active:
            self.create_poll(
                question="২০২৬ সালের বাজেটে প্রযুক্তিতে এআই অটোমেশন ও স্মার্ট বাংলাদেশ অবকাঠামোতে বরাদ্দ কি পর্যাপ্ত?",
                options=["হ্যাঁ, যথেষ্ট", "না, আরও বাড়ানো উচিত", "মন্তব্য নেই"],
                category="জাতীয়",
            )


class SiteConfigRepository:
    """Repository for site configurations, branding, dynamic footer, rates, weather, and AI pilot mode settings."""

    def __init__(self, session: Session):
        self.session = session

    def get_config(self, key: str, default: Any = None) -> Any:
        record = self.session.query(SiteConfig).filter(SiteConfig.key == key).first()
        if record and record.value is not None:
            return record.value
        return default

    def set_config(self, key: str, value: Any) -> SiteConfig:
        record = self.session.query(SiteConfig).filter(SiteConfig.key == key).first()
        if record:
            record.value = value
            record.updated_at = datetime.utcnow()
        else:
            record = SiteConfig(key=key, value=value)
            self.session.add(record)
        self.session.flush()
        return record

    def get_all_configs(self) -> Dict[str, Any]:
        records = self.session.query(SiteConfig).all()
        configs = {}
        for r in records:
            configs[r.key] = r.value
        return configs

    def get_fake_news_policy(self) -> Dict[str, Any]:
        """Fetch active AI Fake News & Fact-Checking policy thresholds and gates."""
        default_policy = {
            "max_fake_tolerance_pct": 50.0,
            "auto_publish_enabled": True,
            "quarantine_high_fake": True,
            "social_dispatch_enabled": True,
            "strict_mode": False,
            "policy_name": "স্ট্যান্ডার্ড সহনশীলতা গেট (<= ৫০% ফেক অনুমোদিত)",
            "updated_at": datetime.utcnow().isoformat(),
        }
        return self.get_config("automation_fake_news_policy", default_policy)

    def update_fake_news_policy(self, policy_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update and persist AI Fake News & Fact-Checking tolerance policy."""
        current = self.get_fake_news_policy()
        current.update(policy_data)
        current["updated_at"] = datetime.utcnow().isoformat()
        self.set_config("automation_fake_news_policy", current)
        return current

    def get_auto_scroller_config(self) -> Dict[str, Any]:
        """Fetch Auto Scroller pipeline settings (scrape -> classify -> dedup -> rewrite -> publish)."""
        default_cfg = {
            "enabled": True,
            "source_urls": "",
            "auto_post_enabled": False,
            "similarity_threshold": 0.98,
            "ai_publish_threshold": 75.0,
            "translate_to_bangla": True,
            "max_items_per_cycle": 10,
            "category": "general",
            "updated_at": datetime.utcnow().isoformat(),
        }
        return self.get_config("auto_scroller", default_cfg)

    def update_auto_scroller_config(self, data: Dict[str, Any]) -> Dict[str, Any]:
        current = self.get_auto_scroller_config()
        current.update(data)
        current["updated_at"] = datetime.utcnow().isoformat()
        self.set_config("auto_scroller", current)
        return current


    def seed_default_configs(self, force: bool = False) -> None:
        defaults = {
            "branding": {
                "site_title": "দি ডেইলি এআই আলো",
                "site_title_en": "The Daily AI Alo",
                "site_tagline": "পুরোপুরি এআই ভিত্তিক সংবাদ পোর্টাল",
                "site_motto": "বিশ্বের সব সংবাদ একই জায়গায় ও বাংলায়",
                "logo_text": "দি ডেইলি এআই আলো",
                "logo_subtitle": "The Daily AI Alo — বিশ্বের সব সংবাদ একই জায়গায় ও বাংলায়",
                "logo_image": "",
                "edition": "গ্লোবাল ও বাংলাদেশ সংস্করণ",
                "usd_rate": "১২১.৫০",
                "eur_rate": "১৩২.২০",
                "weather_city": "ঢাকা",
                "weather_temp": "২৮° সে.",
                "weather_desc": "আংশিক মেঘলা",
            },
            "footer": {
                "publisher": "The Daily AI Alo Media & Tech Labs",
                "editor_in_chief": "প্রধান সম্পাদক ও প্রধান এআই প্রযুক্তিবিদ: ড. এআই টিম",
                "office_address": "সিলিকন টাওয়ার, লেভেল ১২, গুলশান-২, ঢাকা ১২১২।",
                "contact_email": "editorial@daily-ai-alo.com",
                "contact_phone": "+৮৮০ ২ ৮১৮০০৭৮",
                "copyright_text": "© ২০২৬ দি ডেইলি এআই আলো (The Daily AI Alo)। বিশ্বের সব সংবাদ একই জায়গায় ও বাংলায়।",
                "facebook_url": "https://facebook.com/TheDailyAIAlo",
                "youtube_url": "https://youtube.com/c/TheDailyAIAlo",
                "twitter_url": "https://twitter.com/TheDailyAIAlo",
                "android_app_url": "https://play.google.com",
                "ios_app_url": "https://apple.com/app-store",
            },
            "aipilot": {
                "enabled": True,
                "auto_headline": True,
                "auto_summary": True,
                "auto_categorize": True,
                "auto_hero_ranking": True,
                "model_name": "webcreoling-lora-v1",
            },
            "integrations_mail": {
                "enabled": True,
                "mail_server": "sandbox.smtp.mailtrap.io",
                "mail_port": 2525,
                "mail_username": "6056bdc6c17f23",
                "mail_password": "4e1119bb236ac7",
                "mail_use_tls": True,
                "mail_use_ssl": False,
                "mail_default_sender": "no-reply@daily-ai-alo.com",
                "mail_timeout": 10,
            },
            "integrations_sms": {
                "enabled": True,
                "provider": "Generic HTTP Gateway",
                "api_url": "",
                "api_key": "",
                "sender_id": "",
                "method": "GET",
                "param_to": "to",
                "param_text": "msg",
                "extra_params": "",
                "test_mode": True,
            },
            "integrations_payment": {
                "provider": "SSLCommerz",
                "is_live": False,
                "store_id": "arobw6a3cf7767fa7c",
                "store_password": "arobw6a3cf7767fa7c@ssl",
                "sandbox_base_url": "https://sandbox.sslcommerz.com",
                "live_base_url": "https://securepay.sslcommerz.com",
                "currency": "BDT",
            },
            "security_otp": {
                "register_email_otp": True,
                "login_2fa": False,
                "password_reset_otp": True,
                "sms_otp": False,
                "otp_length": 6,
                "otp_ttl_minutes": 10,
                "otp_max_attempts": 5,
                "otp_resend_cooldown_seconds": 60,
            },
            "auto_scroller": {
                "enabled": True,
                "source_urls": "",
                "auto_post_enabled": False,
                "similarity_threshold": 0.98,
                "ai_publish_threshold": 75.0,
                "translate_to_bangla": True,
                "max_items_per_cycle": 10,
                "category": "general",
            },
        }
        for key, val in defaults.items():
            existing = self.session.query(SiteConfig).filter(SiteConfig.key == key).first()
            if not existing or force:
                self.set_config(key, val)


class AdvertisementRepository:
    """Repository managing advertisement banners, slots, active status, impressions, and clicks."""

    def __init__(self, session: Session):
        self.session = session

    def get_all_ads(self) -> List[Advertisement]:
        return self.session.query(Advertisement).order_by(Advertisement.id.desc()).all()

    def get_active_ad_by_slot(self, slot: str) -> Optional[Advertisement]:
        return (
            self.session.query(Advertisement)
            .filter(Advertisement.slot == slot, Advertisement.is_active == True)
            .order_by(Advertisement.id.desc())
            .first()
        )

    def get_active_ads_dict(self) -> Dict[str, Optional[Dict[str, Any]]]:
        slots = ["header_top", "sidebar_square", "article_mid", "footer_sticky"]
        res: Dict[str, Optional[Dict[str, Any]]] = {}
        for slot in slots:
            ad = self.get_active_ad_by_slot(slot)
            if ad:
                res[slot] = ad.to_dict()
            else:
                res[slot] = None
        return res

    def create_ad(
        self,
        title: str,
        slot: str,
        image_url: str,
        target_url: str,
        is_active: bool = True,
    ) -> Advertisement:
        ad = Advertisement(
            title=title.strip(),
            slot=slot.strip(),
            image_url=image_url.strip(),
            target_url=target_url.strip(),
            is_active=is_active,
            views_count=0,
            clicks_count=0,
        )
        self.session.add(ad)
        self.session.flush()
        return ad

    def update_ad(
        self,
        ad_id: int,
        title: Optional[str] = None,
        slot: Optional[str] = None,
        image_url: Optional[str] = None,
        target_url: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[Advertisement]:
        ad = self.session.query(Advertisement).filter(Advertisement.id == ad_id).first()
        if not ad:
            return None
        if title is not None:
            ad.title = title.strip()
        if slot is not None:
            ad.slot = slot.strip()
        if image_url is not None:
            ad.image_url = image_url.strip()
        if target_url is not None:
            ad.target_url = target_url.strip()
        if is_active is not None:
            ad.is_active = is_active
        self.session.flush()
        return ad

    def toggle_ad_status(self, ad_id: int) -> bool:
        ad = self.session.query(Advertisement).filter(Advertisement.id == ad_id).first()
        if ad:
            ad.is_active = not bool(ad.is_active)
            self.session.flush()
            return ad.is_active
        return False

    def delete_ad(self, ad_id: int) -> bool:
        ad = self.session.query(Advertisement).filter(Advertisement.id == ad_id).first()
        if ad:
            self.session.delete(ad)
            self.session.flush()
            return True
        return False

    def record_impression(self, ad_id: int) -> int:
        ad = self.session.query(Advertisement).filter(Advertisement.id == ad_id).first()
        if ad:
            ad.views_count = (ad.views_count or 0) + 1
            self.session.flush()
            return ad.views_count
        return 0

    def record_click(self, ad_id: int) -> Optional[str]:
        ad = self.session.query(Advertisement).filter(Advertisement.id == ad_id).first()
        if ad:
            ad.clicks_count = (ad.clicks_count or 0) + 1
            self.session.flush()
            return ad.target_url
        return None

    def seed_default_ads(self) -> None:
        default_ads = [
            (
                "বিকাশ ক্যাশব্যাক ও ডিজিটাল পেমেন্ট অফার",
                "header_top",
                "https://images.unsplash.com/photo-1559526324-4b87b5e36e44?w=900&auto=format&fit=crop&q=80",
                "https://bkash.com",
            ),
            (
                "গ্রামীণফোন ৫জি সুপার স্পিড নেটওয়ার্ক",
                "sidebar_square",
                "https://images.unsplash.com/photo-1519389950473-47ba0277781c?w=600&auto=format&fit=crop&q=80",
                "https://grameenphone.com",
            ),
            (
                "দারাজ মেগা বৈশাখী সুপার সেল ২০২৬",
                "article_mid",
                "https://images.unsplash.com/photo-1607082348824-0a96f2a4b9da?w=900&auto=format&fit=crop&q=80",
                "https://daraz.com.bd",
            ),
            (
                "নগদ ইসলামিক ডিজিটাল ব্যাংকিং - লেনদেন এখন শূন্য খরচে",
                "footer_sticky",
                "https://images.unsplash.com/photo-1563986768609-322da13575f3?w=900&auto=format&fit=crop&q=80",
                "https://nagad.com.bd",
            ),
        ]
        for title, slot, img, url in default_ads:
            existing = self.session.query(Advertisement).filter(Advertisement.slot == slot).first()
            if not existing:
                self.create_ad(title=title, slot=slot, image_url=img, target_url=url, is_active=True)
            elif not existing.is_active:
                existing.is_active = True
                self.session.flush()


class AuditLogRepository:
    """Repository managing audit logs for editorial and administrative actions."""

    def __init__(self, session: Session):
        self.session = session

    def log_action(
        self,
        username: str,
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> EditorialAuditLog:
        log = EditorialAuditLog(
            username=username or "system",
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            details=details or {},
            ip_address=ip_address or "127.0.0.1",
            user_id=user_id,
        )
        self.session.add(log)
        self.session.flush()
        return log

    def get_audit_logs(
        self,
        limit: int = 50,
        action_filter: Optional[str] = None,
        resource_filter: Optional[str] = None,
    ) -> List[EditorialAuditLog]:
        query = self.session.query(EditorialAuditLog)
        if action_filter:
            query = query.filter(EditorialAuditLog.action == action_filter)
        if resource_filter:
            query = query.filter(EditorialAuditLog.resource_type == resource_filter)
        return query.order_by(EditorialAuditLog.id.desc()).limit(limit).all()


class SystemMonitorRepository:
    """Repository providing real-time server health, disk, database, and background pipeline metrics."""

    def __init__(self, session: Session):
        self.session = session

    def get_telemetry(self) -> Dict[str, Any]:
        import shutil
        import os
        import sys
        import platform
        from config.settings import settings

        # Database File Size
        db_path = str(settings.DB_DIR / "news_pipeline.db")
        db_size_mb = 0.0
        if os.path.exists(db_path):
            db_size_mb = round(os.path.getsize(db_path) / (1024 * 1024), 2)

        # Disk Storage
        try:
            total_b, used_b, free_b = shutil.disk_usage(str(settings.BASE_DIR))
            disk_total_gb = round(total_b / (1024 ** 3), 1)
            disk_used_gb = round(used_b / (1024 ** 3), 1)
            disk_free_gb = round(free_b / (1024 ** 3), 1)
            disk_percent = round((used_b / total_b) * 100, 1) if total_b > 0 else 0
        except Exception:
            disk_total_gb, disk_used_gb, disk_free_gb, disk_percent = 100.0, 30.0, 70.0, 30.0

        # Memory & CPU
        cpu_percent = 14.5
        ram_percent = 48.0
        ram_used_gb = 3.8
        ram_total_gb = 8.0
        try:
            import psutil
            cpu_percent = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            ram_percent = mem.percent
            ram_used_gb = round(mem.used / (1024 ** 3), 1)
            ram_total_gb = round(mem.total / (1024 ** 3), 1)
        except Exception:
            pass

        # Counts
        total_articles = self.session.query(Article).count()
        total_published = self.session.query(Article).filter(Article.scrape_status == "completed").count()
        total_scheduled = self.session.query(Article).filter(Article.scrape_status == "scheduled").count()
        total_archived = self.session.query(Article).filter(Article.scrape_status == "archived").count()
        total_images = self.session.query(ArticleImage).count()
        total_polls = self.session.query(Poll).count()
        total_subscribers = self.session.query(NewsletterSubscriber).count()
        total_ads = self.session.query(Advertisement).count()

        # Scraper health
        last_scrape = self.session.query(ScrapeLog).order_by(ScrapeLog.id.desc()).first()
        scraper_status = "idle"
        last_scrape_time = None
        if last_scrape:
            scraper_status = last_scrape.status
            last_scrape_time = last_scrape.start_time.isoformat() if last_scrape.start_time else None

        # AI Model Checkpoint Status
        lora_dir = (getattr(settings, "MODELS_DIR", settings.DATA_DIR / "checkpoints")) / "adapters"
        has_lora_checkpoint = lora_dir.exists() and any(lora_dir.iterdir()) if lora_dir.exists() else False

        return {
            "cpu_percent": cpu_percent,
            "ram_percent": ram_percent,
            "ram_used_gb": ram_used_gb,
            "ram_total_gb": ram_total_gb,
            "disk_total_gb": disk_total_gb,
            "disk_used_gb": disk_used_gb,
            "disk_free_gb": disk_free_gb,
            "disk_percent": disk_percent,
            "db_size_mb": db_size_mb,
            "total_articles": total_articles,
            "total_published": total_published,
            "total_scheduled": total_scheduled,
            "total_archived": total_archived,
            "total_images": total_images,
            "total_polls": total_polls,
            "total_subscribers": total_subscribers,
            "total_ads": total_ads,
            "scraper_status": scraper_status,
            "last_scrape_time": last_scrape_time,
            "has_lora_checkpoint": has_lora_checkpoint,
            "python_version": platform.python_version(),
            "platform": f"{platform.system()} {platform.release()}",
            "status": "healthy",
        }


class AIPilotHelper:
    """Intelligent Newsroom Editorial Assistant for auto-headline, summarization, and hero ranking."""

    CATEGORY_KEYWORDS = {
        "জাতীয়": ["প্রধানমন্ত্রী", "মন্ত্রী", "সরকার", "সংসদ", "আদালত", "নির্বাচন", "পুলিশ", "বিচার", "আইন", "জাতীয়", "বিএনপি", "আওয়ামী", "প্রশাসন", "রাজধানী"],
        "আন্তর্জাতিক": ["যুক্তরাষ্ট্র", "চীন", "ভারত", "রাশিয়া", "ইউক্রেন", "ইসরায়েল", "গাজা", "জাতিসংঘ", "আন্তর্জাতিক", "প্রেসিডেন্ট", "হোয়াইট হাউস", "মধ্যপ্রাচ্য"],
        "অর্থনীতি": ["টাকা", "ডলার", "ব্যাংক", "মুদ্রাস্ফীতি", "বাজেট", "অর্থনীতি", "রপ্তানি", "আমদানি", "রাজস্ব", "শেয়ারবাজার", "অর্থ", "মূল্যস্ফীতি", "বাণিজ্য"],
        "খেলা": ["ক্রিকেট", "ফুটবল", "ম্যাচ", "বিশ্বকাপ", "রান", "উইকেট", "গোল", "বিপিএল", "আইপিএল", "খেলোয়াড়", "অধিনায়ক", "সিরিজ", "টেস্ট", "টুর্নামেন্ট"],
        "বিনোদন": ["সিনেমা", "নাটক", "অভিনেতা", "অভিনেত্রী", "গান", "সঙ্গীত", "চলচ্চিত্র", "হলিউড", "বলিউড", "ঢালিউড", "তারকা", "পরিচালক", "ওটিটি"],
        "প্রযুক্তি": ["এআই", "কৃত্রিম বুদ্ধিমত্তা", "রোবট", "মোবাইল", "স্মার্টফোন", "ইন্টারনেট", "সফটওয়্যার", "অ্যাপ", "গুগল", "মাইক্রোসফট", "প্রযুক্তি", "কম্পিউটার"],
        "শিক্ষা": ["বিশ্ববিদ্যালয়", "শিক্ষার্থী", "পরীক্ষা", "এইচএসসি", "এসএসসি", "ভর্তি", "শিক্ষক", "কলেজ", "স্কুল", "শিক্ষা"],
        "লাইফস্টাইল": ["স্বাস্থ্য", "ডায়েট", "রান্না", "ভ্রমণ", "রূপচর্চা", "জীবনযাপন", "চিকিৎসা", "রোগ", "হাসপাতাল"],
        "মতামত": ["সম্পাদকীয়", "কলাম", "বিশ্লেষণ", "মতামত", "দৃষ্টিভঙ্গি", "পর্যালোচনা"],
    }

    @classmethod
    def predict_category(cls, text: str) -> str:
        """Predict news category based on keyword density."""
        cleaned = text.lower()
        scores = {}
        for cat, kw_list in cls.CATEGORY_KEYWORDS.items():
            count = sum(1 for kw in kw_list if kw in cleaned)
            if count > 0:
                scores[cat] = count
        if scores:
            return max(scores, key=scores.get)
        return "জাতীয়"

    @classmethod
    def generate_summary(cls, content_text: str, max_sentences: int = 3) -> str:
        """Generate high quality Bengali summary."""
        sentences = [s.strip() for s in content_text.replace("\n", " ").split("।") if len(s.strip()) > 15]
        if not sentences:
            return content_text[:200] + "..."
        chosen = sentences[:max_sentences]
        return "। ".join(chosen) + "।"

    @classmethod
    def generate_headline_suggestions(cls, title: str, content_text: str) -> List[str]:
        """Generate alternative punchy news headlines."""
        suggestions = []
        if title:
            clean_title = title.strip().rstrip("।")
            suggestions.append(f"বিশেষ প্রতিবেদন: {clean_title}")
            suggestions.append(f"{clean_title} — বিস্তারিত তথ্য ও এআই বিশ্লেষণ")
            if len(clean_title.split()) > 4:
                short_title = " ".join(clean_title.split()[:5])
                suggestions.append(f"{short_title} নিয়ে নতুন আপডেট")
        
        # Sentence extract
        sentences = [s.strip() for s in content_text.split("।") if len(s.strip()) > 20]
        if sentences:
            first_sent = sentences[0]
            if len(first_sent) < 80:
                suggestions.append(first_sent)

        return suggestions[:4]

    @classmethod
    def analyze_article(cls, title: str, content_text: str) -> Dict[str, Any]:
        """Full AI Pilot analysis for editorial composer."""
        predicted_cat = cls.predict_category(f"{title} {content_text}")
        summary = cls.generate_summary(content_text)
        headlines = cls.generate_headline_suggestions(title, content_text)
        
        word_count = len(content_text.split())
        reading_time_mins = max(1, round(word_count / 120))
        
        # Sentiment heuristic
        positive_words = ["উন্নতি", "সাফল্য", "জয়", "অর্জন", "ইতিবাচক", "বৃদ্ধি", "উদ্বোধন", "পুরস্কার"]
        negative_words = ["মৃত্যু", "নিহত", "দুর্ঘটনা", "সংকট", "পতন", "ক্ষতি", "হামলা", "অগ্নিসংযোগ", "মামলা"]
        pos_score = sum(1 for w in positive_words if w in content_text)
        neg_score = sum(1 for w in negative_words if w in content_text)
        if pos_score > neg_score:
            sentiment = "ইতিবাচক (Positive)"
        elif neg_score > pos_score:
            sentiment = "উদ্বেগজনক / সংবেদনশীল (Alert)"
        else:
            sentiment = "নিরপেক্ষ (Neutral)"

        return {
            "predicted_category": predicted_cat,
            "generated_summary": summary,
            "suggested_headlines": headlines,
            "word_count": word_count,
            "reading_time_mins": reading_time_mins,
            "sentiment": sentiment,
            "seo_slug": "-".join(title.split()[:6]).lower(),
        }


# ==============================================================================
# Enterprise Security & Web Application Firewall Repository
# ==============================================================================

class SecurityRepository:
    """Repository managing IP Blacklists, Country Geo-Firewalls, and Threat Logs."""

    def __init__(self, session: Session):
        self.session = session

    def get_threat_logs(
        self,
        limit: int = 50,
        threat_type: Optional[str] = None,
        ip_filter: Optional[str] = None,
    ) -> List[SecurityThreatLog]:
        """Fetch recent security threat events."""
        query = self.session.query(SecurityThreatLog)
        if threat_type:
            query = query.filter(SecurityThreatLog.threat_type == threat_type)
        if ip_filter:
            query = query.filter(SecurityThreatLog.ip_address.like(f"%{ip_filter.strip()}%"))
        return query.order_by(SecurityThreatLog.id.desc()).limit(limit).all()

    def log_threat(
        self,
        threat_type: str,
        ip_address: str,
        request_path: str,
        request_method: str = "GET",
        payload_sample: Optional[str] = None,
        country_code: Optional[str] = None,
        user_agent: Optional[str] = None,
        action_taken: str = "BLOCKED_403",
    ) -> SecurityThreatLog:
        """Record a detected attack or security violation."""
        log = SecurityThreatLog(
            threat_type=threat_type,
            ip_address=ip_address.strip(),
            request_path=request_path[:1000],
            request_method=request_method,
            payload_sample=payload_sample[:2000] if payload_sample else None,
            country_code=(country_code or "XX").upper()[:10],
            user_agent=user_agent[:450] if user_agent else None,
            action_taken=action_taken,
        )
        self.session.add(log)
        self.session.flush()
        return log

    def get_blocked_ips(self) -> List[BlockedIP]:
        """Retrieve all currently registered blacklisted IPs."""
        return self.session.query(BlockedIP).order_by(BlockedIP.id.desc()).all()

    def block_ip(
        self,
        ip_address: str,
        reason: str = "Manual Admin Blacklist",
        blocked_by: str = "admin",
        threat_score: int = 100,
        duration_hours: Optional[int] = None,
    ) -> BlockedIP:
        """Add or update an IP address on the blacklist with optional expiration."""
        ip_clean = ip_address.strip()
        from datetime import timedelta
        expires_at = datetime.utcnow() + timedelta(hours=duration_hours) if duration_hours else None

        existing = self.session.query(BlockedIP).filter(BlockedIP.ip_address == ip_clean).first()
        if existing:
            existing.reason = reason
            existing.blocked_by = blocked_by
            existing.threat_score = threat_score
            existing.expires_at = expires_at
            record = existing
        else:
            record = BlockedIP(
                ip_address=ip_clean,
                reason=reason,
                blocked_by=blocked_by,
                threat_score=threat_score,
                expires_at=expires_at,
            )
            self.session.add(record)
        self.session.flush()
        return record

    def unblock_ip(self, ip_id: int) -> bool:
        """Remove an IP address from the blacklist."""
        record = self.session.query(BlockedIP).filter(BlockedIP.id == ip_id).first()
        if record:
            self.session.delete(record)
            self.session.flush()
            return True
        return False

    def is_ip_blocked(self, ip_address: str) -> bool:
        """Check if an IP is actively blacklisted, removing expired entries."""
        ip_clean = ip_address.strip()
        record = self.session.query(BlockedIP).filter(BlockedIP.ip_address == ip_clean).first()
        if not record:
            return False

        if record.expires_at and record.expires_at <= datetime.utcnow():
            self.session.delete(record)
            self.session.flush()
            return False

        return True

    def prune_expired_blocks(self) -> int:
        """Remove expired IP blacklist records from the database."""
        now = datetime.utcnow()
        expired = self.session.query(BlockedIP).filter(BlockedIP.expires_at != None, BlockedIP.expires_at <= now).all()
        count = len(expired)
        for r in expired:
            self.session.delete(r)
        self.session.flush()
        return count

    def get_blocked_countries(self) -> List[BlockedCountry]:
        """Fetch all country geo-firewall rules."""
        return self.session.query(BlockedCountry).order_by(BlockedCountry.id.desc()).all()

    def block_country(
        self,
        country_code: str,
        country_name: Optional[str] = None,
        reason: str = "Geographic firewall policy",
    ) -> BlockedCountry:
        """Add a country to the geo-firewall."""
        code_clean = country_code.strip().upper()
        name = country_name.strip() if country_name else code_clean
        existing = self.session.query(BlockedCountry).filter(BlockedCountry.country_code == code_clean).first()
        if existing:
            existing.country_name = name
            existing.reason = reason
            existing.is_active = True
            self.session.flush()
            return existing

        record = BlockedCountry(
            country_code=code_clean,
            country_name=name,
            reason=reason,
            is_active=True,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def toggle_country(self, country_id: int) -> bool:
        """Toggle active/inactive status of a country block rule."""
        record = self.session.query(BlockedCountry).filter(BlockedCountry.id == country_id).first()
        if record:
            record.is_active = not bool(record.is_active)
            self.session.flush()
            return record.is_active
        return False

    def delete_country(self, country_id: int) -> bool:
        """Delete a country from geo-firewall rules."""
        record = self.session.query(BlockedCountry).filter(BlockedCountry.id == country_id).first()
        if record:
            self.session.delete(record)
            self.session.flush()
            return True
        return False

    def is_country_blocked(self, country_code: str) -> bool:
        """Check if country code is currently geo-blocked."""
        if not country_code:
            return False
        code_clean = country_code.strip().upper()
        record = (
            self.session.query(BlockedCountry)
            .filter(BlockedCountry.country_code == code_clean, BlockedCountry.is_active == True)
            .first()
        )
        return record is not None

    def get_security_metrics(self) -> Dict[str, Any]:
        """Aggregate security overview and threat level indicators."""
        total_blocked_ips = self.session.query(func.count(BlockedIP.id)).scalar() or 0
        total_blocked_countries = self.session.query(func.count(BlockedCountry.id)).filter(BlockedCountry.is_active == True).scalar() or 0
        total_threats = self.session.query(func.count(SecurityThreatLog.id)).scalar() or 0

        # Threats by type
        sqli_count = self.session.query(func.count(SecurityThreatLog.id)).filter(SecurityThreatLog.threat_type == "SQL_INJECTION").scalar() or 0
        xss_count = self.session.query(func.count(SecurityThreatLog.id)).filter(SecurityThreatLog.threat_type == "XSS_ATTACK").scalar() or 0
        traversal_count = self.session.query(func.count(SecurityThreatLog.id)).filter(SecurityThreatLog.threat_type == "PATH_TRAVERSAL").scalar() or 0
        rce_count = self.session.query(func.count(SecurityThreatLog.id)).filter(SecurityThreatLog.threat_type == "RCE_COMMAND").scalar() or 0
        geo_count = self.session.query(func.count(SecurityThreatLog.id)).filter(SecurityThreatLog.threat_type == "GEO_BLOCKED").scalar() or 0
        ip_count = self.session.query(func.count(SecurityThreatLog.id)).filter(SecurityThreatLog.threat_type == "IP_BLACKLIST").scalar() or 0

        # Calculate threat level
        if total_threats == 0:
            threat_level = "NORMAL"
            threat_color = "#10b981"
        elif total_threats < 10:
            threat_level = "ELEVATED"
            threat_color = "#f59e0b"
        else:
            threat_level = "HIGH DEFENSE"
            threat_color = "#ef4444"

        recent_logs = self.get_threat_logs(limit=10)

        return {
            "total_blocked_ips": total_blocked_ips,
            "total_blocked_countries": total_blocked_countries,
            "total_threats": total_threats,
            "sqli_count": sqli_count,
            "xss_count": xss_count,
            "traversal_count": traversal_count,
            "rce_count": rce_count,
            "geo_count": geo_count,
            "ip_count": ip_count,
            "threat_level": threat_level,
            "threat_color": threat_color,
            "recent_logs": [log.to_dict() for log in recent_logs],
            "waf_mode": "ACTIVE_BLOCK",
        }

    get_security_stats = get_security_metrics

    def seed_default_security_rules(self) -> None:
        """Seed initial Geo-Firewall country entries if none exist."""
        if self.session.query(BlockedCountry).count() == 0:
            default_countries = [
                ("KP", "North Korea", "High cyber attack origin zone"),
                ("RU", "Russian Federation", "Automated botnet threat policy"),
                ("IR", "Iran", "Policy-restricted region"),
            ]
            for code, name, reason in default_countries:
                self.block_country(code, name, reason)


# ==============================================================================
# Cryptographic Blockchain Article Ledger Repository
# ==============================================================================

class BlockchainLedgerRepository:
    """Repository managing the immutable cryptographic article ledger and verification proofs."""

    def __init__(self, session: Session):
        self.session = session

    def ensure_genesis_block(self) -> ArticleBlockLedger:
        """Ensure Genesis Block (#0) exists as the cryptographic root."""
        genesis = self.session.query(ArticleBlockLedger).filter(ArticleBlockLedger.block_number == 0).first()
        if not genesis:
            g_data = BlockchainLedgerEngine.create_genesis_block_data()
            genesis = ArticleBlockLedger(**g_data)
            self.session.add(genesis)
            self.session.flush()
            logger.info("Initialized Blockchain Genesis Block #0 for Prothom Alo Newsroom.")
        return genesis

    def get_latest_block(self) -> ArticleBlockLedger:
        """Fetch the most recent cryptographic block in the chain."""
        self.ensure_genesis_block()
        return self.session.query(ArticleBlockLedger).order_by(ArticleBlockLedger.block_number.desc()).first()

    def get_block_by_number(self, block_number: int) -> Optional[ArticleBlockLedger]:
        """Retrieve block by index number."""
        return self.session.query(ArticleBlockLedger).filter(ArticleBlockLedger.block_number == block_number).first()

    def get_block_by_article_id(self, article_id: int) -> Optional[ArticleBlockLedger]:
        """Retrieve cryptographic block certifying a specific article."""
        return self.session.query(ArticleBlockLedger).filter(ArticleBlockLedger.article_id == article_id).first()

    def mint_block_for_article(self, article_id: int) -> Optional[ArticleBlockLedger]:
        """
        Mint a new cryptographic block or update existing block for an article.
        Calculates SHA-256 Merkle root and HMAC signature, then updates the Article record.
        """
        article = self.session.query(Article).filter(Article.id == article_id).first()
        if not article:
            return None

        self.ensure_genesis_block()
        latest = self.get_latest_block()

        # Check if article already has a block
        existing_block = self.get_block_by_article_id(article_id)
        if existing_block:
            # Re-mint with current block number and previous hash
            block_num = existing_block.block_number
            prev_hash = existing_block.prev_block_hash
        else:
            block_num = (latest.block_number or 0) + 1
            prev_hash = latest.block_hash

        minted_data = BlockchainLedgerEngine.mint_article_block(
            block_number=block_num,
            article_id=article.id,
            title=article.title,
            content_text=article.content_text,
            author=article.author,
            prev_block_hash=prev_hash,
            timestamp=datetime.utcnow(),
        )

        if existing_block:
            for k, v in minted_data.items():
                setattr(existing_block, k, v)
            block_record = existing_block
        else:
            block_record = ArticleBlockLedger(**minted_data)
            self.session.add(block_record)

        # Update Article record with cryptographic ledger proof
        article.block_number = block_record.block_number
        article.block_hash = block_record.block_hash
        article.prev_hash = block_record.prev_block_hash
        article.digital_signature = block_record.digital_signature
        article.is_ledger_verified = True

        self.session.flush()
        logger.info(f"Minted cryptographic block #{block_record.block_number} for Article #{article.id} ({block_record.block_hash[:16]}...)")
        return block_record

    def mint_all_unmined_articles(self) -> int:
        """Mint cryptographic blocks for all existing articles that lack a ledger record."""
        self.ensure_genesis_block()
        unmined_articles = (
            self.session.query(Article)
            .filter((Article.block_number == None) | (Article.block_hash == None))
            .order_by(Article.id.asc())
            .all()
        )

        minted_count = 0
        for art in unmined_articles:
            self.mint_block_for_article(art.id)
            minted_count += 1

        self.session.flush()
        return minted_count

    def recalculate_and_seal_chain(self) -> int:
        """Re-links and seals the entire chain sequentially from Genesis to current tip."""
        from src.common.blockchain import GENESIS_PREV_HASH
        self.ensure_genesis_block()
        blocks = self.session.query(ArticleBlockLedger).order_by(ArticleBlockLedger.block_number.asc()).all()
        if not blocks:
            return 0

        prev_hash = GENESIS_PREV_HASH
        for idx, blk in enumerate(blocks):
            blk.block_number = idx
            if idx == 0:
                blk.prev_block_hash = GENESIS_PREV_HASH
            else:
                blk.prev_block_hash = prev_hash

            ts_str = blk.timestamp.isoformat() if blk.timestamp else datetime.utcnow().isoformat()
            blk.block_hash = BlockchainLedgerEngine.calculate_block_hash(
                block_number=idx,
                article_id=blk.article_id or 0,
                merkle_root=blk.merkle_root or "",
                prev_block_hash=blk.prev_block_hash,
                timestamp_iso=ts_str,
                nonce=blk.nonce or 0,
            )
            blk.digital_signature = BlockchainLedgerEngine.generate_digital_signature(blk.block_hash)
            blk.verification_status = "VALID"
            prev_hash = blk.block_hash

            if blk.article_id:
                art = self.session.query(Article).filter(Article.id == blk.article_id).first()
                if art:
                    art.block_number = blk.block_number
                    art.block_hash = blk.block_hash
                    art.prev_hash = blk.prev_block_hash
                    art.digital_signature = blk.digital_signature
                    art.is_ledger_verified = True

        self.session.flush()
        return len(blocks)

    def verify_article_ledger(self, article_id: int) -> Tuple[bool, str, Dict[str, Any]]:
        """Verify an article's cryptographic validity against its ledger block."""
        article = self.session.query(Article).filter(Article.id == article_id).first()
        if not article:
            return False, "আর্টিকেল পাওয়া যায়নি।", {}

        block = self.get_block_by_article_id(article_id)
        if not block:
            # Try minting on the fly if unmined
            block = self.mint_block_for_article(article_id)
            if not block:
                return False, "এই আর্টিকেলের জন্য কোনো ব্লকচেইন লেজার ব্লক পাওয়া যায়নি।", {}

        is_valid, reason, details = BlockchainLedgerEngine.verify_article_block(
            block=block.to_dict(),
            title=article.title,
            content_text=article.content_text,
            author=article.author,
        )

        # Update verification flag
        article.is_ledger_verified = is_valid
        block.verification_status = "VALID" if is_valid else "TAMPERED"
        self.session.flush()

        details["article_id"] = article.id
        details["title"] = article.title
        details["author"] = article.author
        details["timestamp"] = block.timestamp.isoformat() if block.timestamp else None
        details["block_number"] = block.block_number
        details["block_hash"] = block.block_hash
        details["prev_block_hash"] = block.prev_block_hash
        details["digital_signature"] = block.digital_signature
        return is_valid, reason, details

    def audit_full_chain(self) -> Dict[str, Any]:
        """Perform a complete end-to-end blockchain validation scan across all minted blocks."""
        self.ensure_genesis_block()
        blocks = self.session.query(ArticleBlockLedger).order_by(ArticleBlockLedger.block_number.asc()).all()
        blocks_data = [b.to_dict() for b in blocks]
        audit_result = BlockchainLedgerEngine.audit_entire_chain(blocks_data)
        return audit_result

    verify_chain_integrity = audit_full_chain

    def get_ledger_blocks(self, limit: int = 25, page: int = 1) -> Dict[str, Any]:
        """Fetch paginated ledger blocks for the Blockchain Explorer UI."""
        self.ensure_genesis_block()
        query = self.session.query(ArticleBlockLedger)
        total_count = query.count()
        blocks = (
            query.order_by(ArticleBlockLedger.block_number.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        total_pages = max(1, (total_count + limit - 1) // limit)
        return {
            "blocks": blocks,
            "total_count": total_count,
            "page": page,
            "total_pages": total_pages,
        }

    def get_blockchain_stats(self) -> Dict[str, Any]:
        """Get aggregate blockchain summary metrics."""
        self.ensure_genesis_block()
        total_blocks = self.session.query(func.count(ArticleBlockLedger.block_number)).scalar() or 0
        verified_articles = self.session.query(func.count(Article.id)).filter(Article.is_ledger_verified == True).scalar() or 0
        latest = self.get_latest_block()
        tampered_count = self.session.query(func.count(ArticleBlockLedger.block_number)).filter(ArticleBlockLedger.verification_status == "TAMPERED").scalar() or 0

        return {
            "total_blocks": total_blocks,
            "verified_articles": verified_articles,
            "latest_block_number": latest.block_number if latest else 0,
            "latest_block_hash": latest.block_hash if latest else None,
            "tampered_count": tampered_count,
            "chain_health": "100% SECURE" if tampered_count == 0 else "ANOMALY DETECTED",
            "hash_algorithm": "SHA-256 + Merkle Tree",
            "signature_algorithm": "HMAC-SHA256 Server Key",
        }


# ==============================================================================
# AI Brain Custom Rule Engine Repository
# ==============================================================================

class AIBrainRuleRepository:
    """Repository handling custom AI Brain filtering, geo-targeting, language, and translation rules."""

    def __init__(self, session: Session):
        self.session = session

    def get_all_rules(self) -> List[AIBrainCustomRule]:
        """Fetch all configured AI Brain rules."""
        return self.session.query(AIBrainCustomRule).order_by(AIBrainCustomRule.id.asc()).all()

    def get_active_rules(self) -> List[AIBrainCustomRule]:
        """Fetch active targeting rules."""
        rules = self.session.query(AIBrainCustomRule).filter(AIBrainCustomRule.is_active == True).all()
        if not rules:
            self.seed_default_rules()
            rules = self.session.query(AIBrainCustomRule).filter(AIBrainCustomRule.is_active == True).all()
        return rules

    def get_rule_by_id(self, rule_id: int) -> Optional[AIBrainCustomRule]:
        """Fetch single rule by ID."""
        return self.session.query(AIBrainCustomRule).filter(AIBrainCustomRule.id == rule_id).first()

    def create_or_update_rule(
        self,
        name: str,
        target_regions: Optional[List[str]] = None,
        target_countries: Optional[List[str]] = None,
        target_languages: Optional[List[str]] = None,
        target_categories: Optional[List[str]] = None,
        required_keywords: Optional[List[str]] = None,
        excluded_keywords: Optional[List[str]] = None,
        allowed_portal_sources: Optional[List[str]] = None,
        min_credibility_score: float = 70.0,
        auto_translate_to_bangla: bool = True,
        auto_publish: bool = True,
        auto_broadcast_social: bool = True,
        custom_prompt_rules: Optional[str] = None,
        is_active: bool = True,
        rule_id: Optional[int] = None,
    ) -> AIBrainCustomRule:
        """Create a new AI Brain targeting rule or update existing."""
        if rule_id:
            rule = self.get_rule_by_id(rule_id)
            if not rule:
                rule = AIBrainCustomRule()
                self.session.add(rule)
        else:
            rule = AIBrainCustomRule()
            self.session.add(rule)

        rule.name = name.strip()
        rule.target_regions = target_regions or []
        rule.target_countries = target_countries or []
        rule.target_languages = target_languages or []
        rule.target_categories = target_categories or []
        rule.required_keywords = required_keywords or []
        rule.excluded_keywords = excluded_keywords or []
        rule.allowed_portal_sources = allowed_portal_sources or []
        rule.min_credibility_score = float(min_credibility_score)
        rule.auto_translate_to_bangla = bool(auto_translate_to_bangla)
        rule.auto_publish = bool(auto_publish)
        rule.auto_broadcast_social = bool(auto_broadcast_social)
        rule.custom_prompt_rules = custom_prompt_rules.strip() if custom_prompt_rules else ""
        rule.is_active = bool(is_active)
        rule.updated_at = datetime.utcnow()

        self.session.flush()
        return rule

    def toggle_rule(self, rule_id: int) -> bool:
        """Toggle active state of a targeting rule."""
        rule = self.get_rule_by_id(rule_id)
        if rule:
            rule.is_active = not bool(rule.is_active)
            rule.updated_at = datetime.utcnow()
            self.session.flush()
            return rule.is_active
        return False

    def delete_rule(self, rule_id: int) -> bool:
        """Delete an AI Brain custom rule."""
        rule = self.get_rule_by_id(rule_id)
        if rule:
            self.session.delete(rule)
            self.session.flush()
            return True
        return False

    def seed_default_rules(self) -> None:
        """Seed high-intelligence default rules if database is clean."""
        count = self.session.query(func.count(AIBrainCustomRule.id)).scalar() or 0
        if count > 0:
            return

        rule1 = AIBrainCustomRule(
            name="দক্ষিণ এশিয়া ও বাংলাদেশ প্রায়োরিটি (South Asia & Bangladesh Priority)",
            is_active=True,
            target_regions=["bangladesh", "south_asia", "global"],
            target_countries=["BD", "IN", "PK"],
            target_languages=["bn", "en", "hi", "ur"],
            target_categories=["politics", "business", "technology", "international", "sports"],
            required_keywords=[],
            excluded_keywords=["জুয়া", "ক্যাসিনো", "প্রাপ্তবয়স্ক", "পর্নোগ্রাফি", "অশ্লীল"],
            allowed_portal_sources=[],
            min_credibility_score=70.0,
            auto_translate_to_bangla=True,
            auto_publish=True,
            auto_broadcast_social=True,
            custom_prompt_rules="বাংলাদেশ ও দক্ষিণ এশিয়ার যেকোনো গুরুত্বপূর্ণ সংবাদ সর্বোচ্চ বিশ্বাসযোগ্যতায় প্রকাশ ও সোশ্যাল মিডিয়ায় শেয়ার করুন।",
        )
        rule2 = AIBrainCustomRule(
            name="আন্তর্জাতিক প্রযুক্তি ও এআই ট্রেন্ডস (Global Tech & AI Trends)",
            is_active=True,
            target_regions=["global", "usa", "europe", "middle_east"],
            target_countries=["US", "UK", "SA", "AE", "CN", "DE"],
            target_languages=["en", "ar"],
            target_categories=["technology", "science", "business"],
            required_keywords=["AI", "Artificial Intelligence", "Tech", "Space", "Startup", "Software"],
            excluded_keywords=["clickbait", "rumor", "leak"],
            allowed_portal_sources=[],
            min_credibility_score=75.0,
            auto_translate_to_bangla=True,
            auto_publish=True,
            auto_broadcast_social=True,
            custom_prompt_rules="বিশ্বের শীর্ষ বিজ্ঞান ও প্রযুক্তি আবিষ্কারের খবর সাবলীল বাংলায় অনুবাদ করে প্রকাশ করুন।",
        )
        self.session.add_all([rule1, rule2])
        self.session.flush()


# ==============================================================================
# Social Media Channel & Broadcast Repository
# ==============================================================================

class SocialChannelRepository:
    """Repository handling Connected Social Media Accounts, Token Management, and Outbound Sync."""

    def __init__(self, session: Session):
        self.session = session

    def list_channels(self) -> List[SocialChannelConfig]:
        """Fetch all configured social channels."""
        channels = self.session.query(SocialChannelConfig).order_by(SocialChannelConfig.id.asc()).all()
        if not channels:
            self.seed_default_channels()
            channels = self.session.query(SocialChannelConfig).order_by(SocialChannelConfig.id.asc()).all()
        return channels

    def get_channel_by_id(self, channel_id: int) -> Optional[SocialChannelConfig]:
        """Fetch single channel config by ID."""
        return self.session.query(SocialChannelConfig).filter(SocialChannelConfig.id == channel_id).first()

    def get_active_channels(self, platform: Optional[str] = None) -> List[SocialChannelConfig]:
        """Fetch operational channels for outbound broadcasting."""
        query = self.session.query(SocialChannelConfig).filter(SocialChannelConfig.is_active == True)
        if platform:
            query = query.filter(SocialChannelConfig.platform == platform.strip().lower())
        return query.all()

    def create_or_update_channel(
        self,
        platform: str,
        account_name: str,
        page_id_or_channel_id: str,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        access_token: Optional[str] = None,
        webhook_verify_token: Optional[str] = None,
        is_active: bool = True,
        is_primary: bool = True,
        failover_account_id: Optional[int] = None,
        channel_id: Optional[int] = None,
    ) -> SocialChannelConfig:
        """Add or update social media account credentials."""
        if channel_id:
            channel = self.get_channel_by_id(channel_id)
            if not channel:
                channel = SocialChannelConfig()
                self.session.add(channel)
        else:
            channel = SocialChannelConfig()
            self.session.add(channel)

        channel.platform = platform.strip().lower()
        channel.account_name = account_name.strip()
        channel.page_id_or_channel_id = page_id_or_channel_id.strip()
        if app_id is not None:
            channel.app_id = app_id.strip()
        if app_secret is not None:
            channel.app_secret = app_secret.strip()
        if access_token is not None:
            channel.access_token = access_token.strip()
        if webhook_verify_token is not None:
            channel.webhook_verify_token = webhook_verify_token.strip()
        channel.is_active = bool(is_active)
        channel.is_primary = bool(is_primary)
        channel.failover_account_id = failover_account_id if failover_account_id else None
        channel.status = "HEALTHY"
        channel.updated_at = datetime.utcnow()

        self.session.flush()
        return channel

    def toggle_channel(self, channel_id: int) -> bool:
        """Toggle active state of a social channel."""
        channel = self.get_channel_by_id(channel_id)
        if channel:
            channel.is_active = not bool(channel.is_active)
            channel.updated_at = datetime.utcnow()
            self.session.flush()
            return channel.is_active
        return False

    def delete_channel(self, channel_id: int) -> bool:
        """Delete social channel configuration."""
        channel = self.get_channel_by_id(channel_id)
        if channel:
            self.session.delete(channel)
            self.session.flush()
            return True
        return False

    def mark_channel_restricted(self, channel_id: int, error_message: str) -> Optional[SocialChannelConfig]:
        """Mark channel as restricted upon Facebook/Platform API ban or token revocation and switch to failover."""
        channel = self.get_channel_by_id(channel_id)
        if not channel:
            return None

        channel.status = "RESTRICTED"
        channel.last_error_message = error_message
        channel.updated_at = datetime.utcnow()
        self.session.flush()

        logger.warning(f"Social channel #{channel.id} ({channel.account_name}) marked as RESTRICTED. Error: {error_message}")

        # Activate failover account if configured
        if channel.failover_account_id:
            failover = self.get_channel_by_id(channel.failover_account_id)
            if failover and failover.status != "RESTRICTED":
                failover.is_active = True
                failover.status = "BACKUP_ACTIVE"
                self.session.flush()
                logger.info(f"Automatically activated fallback failover account: {failover.account_name} (ID: #{failover.id})")
                return failover
        return channel

    def reset_channel_status(self, channel_id: int) -> Optional[SocialChannelConfig]:
        """Reset a restricted or failover channel back to HEALTHY state."""
        channel = self.get_channel_by_id(channel_id)
        if channel:
            channel.status = "HEALTHY"
            channel.last_error_message = None
            channel.is_active = True
            channel.updated_at = datetime.utcnow()
            self.session.flush()
            return channel
        return None

    def record_broadcast_success(self, channel_id: int) -> None:
        """Increment success counter and update timestamp."""
        channel = self.get_channel_by_id(channel_id)
        if channel:
            channel.total_posts_dispatched = (channel.total_posts_dispatched or 0) + 1
            channel.last_post_at = datetime.utcnow()
            if channel.status != "BACKUP_ACTIVE":
                channel.status = "HEALTHY"
            self.session.flush()

    def log_broadcast(
        self,
        platform: str,
        target_account: str,
        dispatch_status: str,
        article_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        post_payload: Optional[Dict[str, Any]] = None,
        external_post_id: Optional[str] = None,
        response_data: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> SocialBroadcastLog:
        """Log an outbound social media dispatch event."""
        log = SocialBroadcastLog(
            article_id=article_id,
            channel_id=channel_id,
            platform=platform,
            target_account=target_account,
            post_payload=post_payload or {},
            external_post_id=external_post_id,
            dispatch_status=dispatch_status,
            response_data=response_data or {},
            error_message=error_message,
            created_at=datetime.utcnow(),
        )
        self.session.add(log)
        self.session.flush()
        return log

    def get_broadcast_logs(self, limit: int = 25) -> List[SocialBroadcastLog]:
        """Fetch recent outbound social media broadcast logs."""
        return (
            self.session.query(SocialBroadcastLog)
            .order_by(SocialBroadcastLog.id.desc())
            .limit(limit)
            .all()
        )

    def seed_default_channels(self) -> None:
        """Seed default social media accounts and anti-ban failover configurations."""
        count = self.session.query(func.count(SocialChannelConfig.id)).scalar() or 0
        if count > 0:
            return

        # 1. Facebook Backup Account
        fb_backup = SocialChannelConfig(
            platform="facebook",
            account_name="প্রথম আলো ডিজিটাল বার্তা (Backup Page)",
            page_id_or_channel_id="109283746519284",
            app_id="fb_app_982374616",
            app_secret="sec_fb_82736482",
            access_token="EAAK_BACKUP_ACCESS_TOKEN_PROTHOM_ALO_2026",
            is_active=True,
            is_primary=False,
            status="HEALTHY",
        )
        self.session.add(fb_backup)
        self.session.flush()

        # 2. Facebook Primary Account (with failover pointing to backup)
        fb_primary = SocialChannelConfig(
            platform="facebook",
            account_name="প্রথম আলো অফিসিয়াল নিউজ পেজ (Primary)",
            page_id_or_channel_id="109283746519283",
            app_id="fb_app_982374615",
            app_secret="sec_fb_82736481",
            access_token="EAAK_PRIMARY_ACCESS_TOKEN_PROTHOM_ALO_2026",
            is_active=True,
            is_primary=True,
            status="HEALTHY",
            failover_account_id=fb_backup.id,
        )

        # 3. YouTube Wire & Shorts
        yt = SocialChannelConfig(
            platform="youtube",
            account_name="প্রথম আলো ডিজিটাল ভিডিও বুলেটিন (YouTube Wire)",
            page_id_or_channel_id="UC_ProthomAloDigitalNews",
            app_id="yt_client_829374",
            access_token="ya29.a0ARrdaM_SAMPLE_OAUTH_TOKEN",
            is_active=True,
            is_primary=True,
            status="HEALTHY",
        )

        # 4. TikTok News Flash
        tiktok = SocialChannelConfig(
            platform="tiktok",
            account_name="@ProthomAloNewsDaily (TikTok Wire)",
            page_id_or_channel_id="tiktok_open_news_wire_bd",
            app_id="tiktok_app_771829",
            access_token="act.tiktok.open.token.sample",
            is_active=True,
            is_primary=True,
            status="HEALTHY",
        )

        # 5. Telegram Instant Wire
        tg = SocialChannelConfig(
            platform="telegram",
            account_name="@ProthomAloInstantWire (Telegram Channel)",
            page_id_or_channel_id="@ProthomAloInstantWire",
            app_id="bot192837465",
            access_token="192837465:AAH_SAMPLE_TELEGRAM_BOT_TOKEN",
            is_active=True,
            is_primary=True,
            status="HEALTHY",
        )

        self.session.add_all([fb_primary, yt, tiktok, tg])
        self.session.flush()


# ==============================================================================
# Website Data Center, Cloud Storage & Database Failover Repository
# ==============================================================================

class DataCenterRepository:
    """
    Repository for Website Data Center, Parallel Cloud Media Storage,
    Database High-Availability (HA) Failover Nodes, Automated Backups, and Security Audit Logs.
    """

    def __init__(self, session: Session):
        self.session = session

    # --------------------------------------------------------------------------
    # 1. Multi-Cloud Storage Providers (Google Drive, Mega, S3, FTP)
    # --------------------------------------------------------------------------
    def list_storage_providers(self) -> List[DataCenterStorageProvider]:
        """Fetch all configured cloud storage providers."""
        providers = self.session.query(DataCenterStorageProvider).order_by(DataCenterStorageProvider.id.asc()).all()
        if not providers:
            self.seed_default_providers()
            providers = self.session.query(DataCenterStorageProvider).order_by(DataCenterStorageProvider.id.asc()).all()
        return providers

    def get_storage_provider(self, provider_id: int) -> Optional[DataCenterStorageProvider]:
        """Fetch single cloud storage provider by ID."""
        return self.session.query(DataCenterStorageProvider).filter(DataCenterStorageProvider.id == provider_id).first()

    def get_primary_storage_provider(self) -> Optional[DataCenterStorageProvider]:
        """Fetch active primary cloud storage provider for public media CDN delivery."""
        return (
            self.session.query(DataCenterStorageProvider)
            .filter(DataCenterStorageProvider.is_primary == True, DataCenterStorageProvider.is_active == True)
            .first()
        )

    def get_active_storage_providers(self) -> List[DataCenterStorageProvider]:
        """Fetch operational cloud storage providers for mirroring and replication."""
        return (
            self.session.query(DataCenterStorageProvider)
            .filter(DataCenterStorageProvider.is_active == True)
            .order_by(DataCenterStorageProvider.is_primary.desc(), DataCenterStorageProvider.id.asc())
            .all()
        )

    def create_or_update_storage_provider(
        self,
        provider_type: str,
        name: str,
        credentials_json: Optional[Dict[str, Any]] = None,
        cdn_base_url: Optional[str] = None,
        capacity_total_bytes: float = 16106127360.0,
        capacity_used_bytes: float = 1073741824.0,
        sync_mode: str = "PRIMARY_CDN",
        is_active: bool = True,
        is_primary: bool = False,
        provider_id: Optional[int] = None,
    ) -> DataCenterStorageProvider:
        """Create a new cloud storage integration or update existing."""
        if provider_id:
            provider = self.get_storage_provider(provider_id)
            if not provider:
                provider = DataCenterStorageProvider()
                self.session.add(provider)
        else:
            provider = DataCenterStorageProvider()
            self.session.add(provider)

        if is_primary:
            self.session.query(DataCenterStorageProvider).update({DataCenterStorageProvider.is_primary: False})

        provider.provider_type = provider_type.strip().lower()
        provider.name = name.strip()
        if credentials_json is not None:
            provider.credentials_json = credentials_json
        if cdn_base_url is not None:
            provider.cdn_base_url = cdn_base_url.strip()
        provider.capacity_total_bytes = float(capacity_total_bytes)
        provider.capacity_used_bytes = float(capacity_used_bytes)
        provider.sync_mode = sync_mode.strip().upper()
        provider.is_active = bool(is_active)
        provider.is_primary = bool(is_primary)
        provider.last_health_check = datetime.utcnow()
        provider.updated_at = datetime.utcnow()

        self.session.flush()
        return provider

    def toggle_storage_provider(self, provider_id: int) -> bool:
        """Toggle active state of a cloud storage provider."""
        provider = self.get_storage_provider(provider_id)
        if provider:
            provider.is_active = not bool(provider.is_active)
            self.session.flush()
            return provider.is_active
        return False

    def delete_storage_provider(self, provider_id: int) -> bool:
        """Delete a cloud storage provider."""
        provider = self.get_storage_provider(provider_id)
        if provider:
            self.session.delete(provider)
            self.session.flush()
            return True
        return False

    def set_primary_storage_provider(self, provider_id: int) -> bool:
        """Promote a cloud storage provider to primary CDN source."""
        provider = self.get_storage_provider(provider_id)
        if provider:
            self.session.query(DataCenterStorageProvider).update({DataCenterStorageProvider.is_primary: False})
            provider.is_primary = True
            provider.is_active = True
            self.session.flush()
            return True
        return False

    def seed_default_providers(self) -> None:
        """Seed default multi-cloud storage integrations."""
        count = self.session.query(func.count(DataCenterStorageProvider.id)).scalar() or 0
        if count > 0:
            return

        p1 = DataCenterStorageProvider(
            provider_type="google_drive",
            name="Google Drive Enterprise Media Hub (Primary)",
            credentials_json={
                "client_id": "982347102938-apps.googleusercontent.com",
                "folder_id": "1A2B3C4D5E6F7G8H9I_GoogleDriveMediaRoot",
                "api_key": "AIzaSyD_EXAMPLE_GDRIVE_API_KEY_2026",
                "service_account_email": "media-sa@the-daily-ai-alo.iam.gserviceaccount.com",
            },
            cdn_base_url="https://drive.google.com/uc?export=view&id=",
            capacity_total_bytes=100 * (1024 ** 3),
            capacity_used_bytes=14.2 * (1024 ** 3),
            is_active=True,
            is_primary=True,
            sync_mode="PRIMARY_CDN",
            status="ONLINE",
        )
        p2 = DataCenterStorageProvider(
            provider_type="mega",
            name="Mega.nz Ultra Cloud Store (Encrypted Mirror)",
            credentials_json={
                "user_email": "datacenter@the-daily-ai-alo.com",
                "api_key": "mega_key_sec_819283746",
                "vault_folder": "TheDailyAIAlo_MediaVault",
            },
            cdn_base_url="https://mega.nz/file/",
            capacity_total_bytes=50 * (1024 ** 3),
            capacity_used_bytes=14.2 * (1024 ** 3),
            is_active=True,
            is_primary=False,
            sync_mode="AUTO_MIRROR",
            status="ONLINE",
        )
        p3 = DataCenterStorageProvider(
            provider_type="s3",
            name="AWS S3 / Wasabi High-Speed Edge Storage",
            credentials_json={
                "bucket_name": "the-daily-ai-alo-cdn",
                "region": "ap-southeast-1",
                "access_key_id": "AKIA_SAMPLE_WASABI_KEY_2026",
                "secret_access_key": "s3_secret_w9283746152",
            },
            cdn_base_url="https://s3.ap-southeast-1.wasabisys.com/the-daily-ai-alo-cdn/",
            capacity_total_bytes=500 * (1024 ** 3),
            capacity_used_bytes=28.5 * (1024 ** 3),
            is_active=True,
            is_primary=False,
            sync_mode="AUTO_MIRROR",
            status="ONLINE",
        )
        p4 = DataCenterStorageProvider(
            provider_type="ftp",
            name="Offsite Disaster Recovery SFTP Server",
            credentials_json={
                "ftp_host": "sftp.offsite-backup-node.org",
                "ftp_port": 22,
                "username": "alo_backup_user",
                "remote_dir": "/var/www/daily_alo_backups",
            },
            cdn_base_url="https://sftp-mirror.offsite-backup-node.org/media/",
            capacity_total_bytes=1000 * (1024 ** 3),
            capacity_used_bytes=45.8 * (1024 ** 3),
            is_active=True,
            is_primary=False,
            sync_mode="BACKUP_ONLY",
            status="ONLINE",
        )

        self.session.add_all([p1, p2, p3, p4])
        self.session.flush()

    # --------------------------------------------------------------------------
    # 2. Database High-Availability (HA) Replicas & Auto-Failover
    # --------------------------------------------------------------------------
    def list_replica_nodes(self) -> List[DatabaseReplicaNode]:
        """Fetch all database topology nodes sorted by failover priority."""
        nodes = self.session.query(DatabaseReplicaNode).order_by(DatabaseReplicaNode.auto_failover_priority.asc()).all()
        if not nodes:
            self.seed_default_replica_nodes()
            nodes = self.session.query(DatabaseReplicaNode).order_by(DatabaseReplicaNode.auto_failover_priority.asc()).all()
        return nodes

    def get_replica_node(self, node_id: int) -> Optional[DatabaseReplicaNode]:
        """Fetch single database replica node by ID."""
        return self.session.query(DatabaseReplicaNode).filter(DatabaseReplicaNode.id == node_id).first()

    def get_current_primary_node(self) -> Optional[DatabaseReplicaNode]:
        """Fetch currently active master database node serving the application."""
        return self.session.query(DatabaseReplicaNode).filter(DatabaseReplicaNode.is_current_primary == True).first()

    def create_or_update_node(
        self,
        node_name: str,
        host: str,
        port: int = 3306,
        database_name: str = "ai_news",
        username: str = "root",
        password_masked: str = "••••••••",
        is_active: bool = True,
        is_current_primary: bool = False,
        auto_failover_priority: int = 1,
        node_id: Optional[int] = None,
    ) -> DatabaseReplicaNode:
        """Create a new database replica node or update existing configuration."""
        if node_id:
            node = self.get_replica_node(node_id)
            if not node:
                node = DatabaseReplicaNode()
                self.session.add(node)
        else:
            node = DatabaseReplicaNode()
            self.session.add(node)

        if is_current_primary:
            self.session.query(DatabaseReplicaNode).update({DatabaseReplicaNode.is_current_primary: False})

        node.node_name = node_name.strip()
        node.host = host.strip()
        node.port = int(port)
        node.database_name = database_name.strip()
        node.username = username.strip()
        node.password_masked = password_masked
        node.is_active = bool(is_active)
        node.is_current_primary = bool(is_current_primary)
        node.auto_failover_priority = int(auto_failover_priority)
        node.last_heartbeat = datetime.utcnow()
        node.updated_at = datetime.utcnow()

        self.session.flush()
        return node

    def toggle_node(self, node_id: int) -> bool:
        """Toggle active state of a database replica node."""
        node = self.get_replica_node(node_id)
        if node:
            node.is_active = not bool(node.is_active)
            self.session.flush()
            return node.is_active
        return False

    def delete_node(self, node_id: int) -> bool:
        """Delete a database replica node."""
        node = self.get_replica_node(node_id)
        if node:
            self.session.delete(node)
            self.session.flush()
            return True
        return False

    def set_primary_node(self, node_id: int) -> bool:
        """Promote a standby database replica node to primary active master."""
        node = self.get_replica_node(node_id)
        if node:
            self.session.query(DatabaseReplicaNode).update({
                DatabaseReplicaNode.is_current_primary: False,
                DatabaseReplicaNode.replication_status: "STANDBY_READY"
            })
            node.is_current_primary = True
            node.is_active = True
            node.replication_status = "SYNCED"
            node.last_heartbeat = datetime.utcnow()
            self.session.flush()
            return True
        return False

    def update_node_health(self, node_id: int, status: str, latency_ms: float) -> Optional[DatabaseReplicaNode]:
        """Update node heartbeat status and response latency."""
        node = self.get_replica_node(node_id)
        if node:
            node.replication_status = status
            node.latency_ms = round(latency_ms, 2)
            node.last_heartbeat = datetime.utcnow()
            self.session.flush()
            return node
        return None

    def seed_default_replica_nodes(self) -> None:
        """Seed default high-availability database cluster topology."""
        count = self.session.query(func.count(DatabaseReplicaNode.id)).scalar() or 0
        if count > 0:
            return

        n1 = DatabaseReplicaNode(
            node_name="Primary Database Node (Production MySQL)",
            host="127.0.0.1",
            port=3306,
            database_name="ai_news",
            username="root",
            password_masked="••••••••",
            is_active=True,
            is_current_primary=True,
            replication_status="SYNCED",
            latency_ms=0.8,
            auto_failover_priority=1,
        )
        n2 = DatabaseReplicaNode(
            node_name="Standby Replica Node Alpha (Singapore VPS Cluster)",
            host="db-sg.the-daily-ai-alo.net",
            port=3306,
            database_name="ai_news",
            username="ai_alo_replica",
            password_masked="••••••••",
            is_active=True,
            is_current_primary=False,
            replication_status="STANDBY_READY",
            latency_ms=18.4,
            auto_failover_priority=2,
        )
        n3 = DatabaseReplicaNode(
            node_name="Disaster Recovery Node Beta (Frankfurt High-Availability)",
            host="db-eu.backup-datacenter.org",
            port=3306,
            database_name="ai_news_dr",
            username="alo_dr_admin",
            password_masked="••••••••",
            is_active=True,
            is_current_primary=False,
            replication_status="STANDBY_READY",
            latency_ms=115.2,
            auto_failover_priority=3,
        )

        self.session.add_all([n1, n2, n3])
        self.session.flush()

    # --------------------------------------------------------------------------
    # 3. Automated & Scheduled Backup Archives
    # --------------------------------------------------------------------------
    def list_backups(self, limit: int = 50) -> List[DataCenterBackupArchive]:
        """Fetch all backup archives."""
        return (
            self.session.query(DataCenterBackupArchive)
            .order_by(DataCenterBackupArchive.id.desc())
            .limit(limit)
            .all()
        )

    def get_backup_by_id(self, backup_id: int) -> Optional[DataCenterBackupArchive]:
        """Fetch single backup archive record by ID."""
        return self.session.query(DataCenterBackupArchive).filter(DataCenterBackupArchive.id == backup_id).first()

    def create_backup_record(
        self,
        backup_name: str,
        backup_type: str,
        file_path: str,
        file_size_bytes: float,
        sha256_checksum: str,
        target_cloud_destinations: Optional[List[str]] = None,
        cloud_upload_status: Optional[Dict[str, str]] = None,
        is_encrypted: bool = True,
        encryption_algorithm: str = "AES-256-GCM",
        status: str = "COMPLETED",
    ) -> DataCenterBackupArchive:
        """Record newly generated backup archive."""
        rec = DataCenterBackupArchive(
            backup_name=backup_name.strip(),
            backup_type=backup_type.strip(),
            file_path=file_path.strip(),
            file_size_bytes=float(file_size_bytes),
            sha256_checksum=sha256_checksum,
            target_cloud_destinations=target_cloud_destinations or [],
            cloud_upload_status=cloud_upload_status or {},
            is_encrypted=is_encrypted,
            encryption_algorithm=encryption_algorithm,
            status=status,
            created_at=datetime.utcnow(),
        )
        self.session.add(rec)
        self.session.flush()
        return rec

    def delete_backup(self, backup_id: int) -> bool:
        """Delete a backup archive and purge local file."""
        rec = self.get_backup_by_id(backup_id)
        if rec:
            import os
            try:
                if os.path.exists(rec.file_path):
                    os.remove(rec.file_path)
            except Exception:
                pass
            self.session.delete(rec)
            self.session.flush()
            return True
        return False

    # --------------------------------------------------------------------------
    # 4. Data Center Security Audit Logs
    # --------------------------------------------------------------------------
    def log_event(
        self,
        event_type: str,
        description: str,
        severity: str = "INFO",
        actor: str = "AI DataCenter Engine",
        metadata_json: Optional[Dict[str, Any]] = None,
        ip_address: str = "127.0.0.1",
    ) -> DataCenterSecurityLog:
        """Log a data center event (failover, sync, backup, auth)."""
        log = DataCenterSecurityLog(
            event_type=event_type,
            description=description,
            severity=severity,
            actor=actor,
            metadata_json=metadata_json or {},
            ip_address=ip_address,
            created_at=datetime.utcnow(),
        )
        self.session.add(log)
        self.session.flush()
        return log

    def list_logs(
        self,
        limit: int = 50,
        event_type: Optional[str] = None,
        severity: Optional[str] = None,
    ) -> List[DataCenterSecurityLog]:
        """Fetch recent security and data center audit logs."""
        query = self.session.query(DataCenterSecurityLog)
        if event_type:
            query = query.filter(DataCenterSecurityLog.event_type == event_type)
        if severity:
            query = query.filter(DataCenterSecurityLog.severity == severity)
        return query.order_by(DataCenterSecurityLog.id.desc()).limit(limit).all()

    # --------------------------------------------------------------------------
    # 5. Aggregate Telemetry & Summary
    # --------------------------------------------------------------------------
    def get_datacenter_summary(self) -> Dict[str, Any]:
        """Aggregate high-level overview metrics for data center operations."""
        providers = self.list_storage_providers()
        nodes = self.list_replica_nodes()
        backups = self.list_backups(limit=5)

        total_storage_cap = sum(p.capacity_total_bytes for p in providers)
        total_storage_used = sum(p.capacity_used_bytes for p in providers)
        storage_pct = round((total_storage_used / max(1.0, total_storage_cap)) * 100, 1)

        primary_node = next((n for n in nodes if n.is_current_primary), None)
        standby_count = sum(1 for n in nodes if not n.is_current_primary and n.is_active)
        total_backups = self.session.query(func.count(DataCenterBackupArchive.id)).scalar() or 0

        return {
            "total_storage_cap_gb": round(total_storage_cap / (1024 ** 3), 2),
            "total_storage_used_gb": round(total_storage_used / (1024 ** 3), 2),
            "storage_percent": storage_pct,
            "active_providers_count": sum(1 for p in providers if p.is_active),
            "primary_node_name": primary_node.node_name if primary_node else "None",
            "primary_node_host": f"{primary_node.host}:{primary_node.port}" if primary_node else "N/A",
            "primary_latency_ms": primary_node.latency_ms if primary_node else 0.0,
            "standby_nodes_count": standby_count,
            "total_backups_count": total_backups,
            "latest_backup_time": backups[0].created_at.isoformat() if backups else None,
            "security_logs_count": self.session.query(func.count(DataCenterSecurityLog.id)).scalar() or 0,
            "ha_mode": "ACTIVE_AUTO_FAILOVER",
        }


# ==============================================================================
# Autonomous AI Brain Security Vault Repository
# ==============================================================================

class EmergencyVaultRepository:
    """Repository handling AI Brain Emergency Encryption Vault state and recovery."""

    def __init__(self, session: Session):
        self.session = session

    def get_vault_state(self) -> EmergencyVaultState:
        """Fetch or initialize singleton EmergencyVaultState record."""
        state = self.session.query(EmergencyVaultState).first()
        if not state:
            state = EmergencyVaultState(
                is_locked=False,
                auto_lockdown_enabled=True,
                threat_threshold_score=75,
                current_threat_score=12,
                threat_status="NORMAL",
                recipient_email="security-officer@daily-ai-alo.com",
                encryption_algorithm="AES-256-GCM / Fernet",
                email_dispatch_status="IDLE",
            )
            self.session.add(state)
            self.session.flush()
        return state

    def update_settings(
        self,
        auto_lockdown_enabled: bool,
        threat_threshold_score: int,
        recipient_email: str,
    ) -> EmergencyVaultState:
        """Update automated AI threat defense parameters and notification email."""
        state = self.get_vault_state()
        state.auto_lockdown_enabled = auto_lockdown_enabled
        state.threat_threshold_score = max(20, min(100, threat_threshold_score))
        if recipient_email and "@" in recipient_email:
            state.recipient_email = recipient_email.strip()
        self.session.flush()
        return state


class OtpRepository:
    """Repository for one-time verification codes (issue / verify / purge)."""

    def __init__(self, session: Session):
        self.session = session

    def latest_for(self, destination: str, purpose: str) -> Optional[OtpCode]:
        return (
            self.session.query(OtpCode)
            .filter(OtpCode.destination == destination, OtpCode.purpose == purpose)
            .order_by(OtpCode.id.desc())
            .first()
        )

    def add(self, otp: OtpCode) -> OtpCode:
        self.session.add(otp)
        self.session.flush()
        return otp

    def save(self, otp: OtpCode) -> OtpCode:
        self.session.add(otp)
        self.session.flush()
        return otp

    def purge_expired(self) -> int:
        cutoff = datetime.utcnow()
        deleted = (
            self.session.query(OtpCode)
            .filter(OtpCode.expires_at < cutoff)
            .delete(synchronize_session=False)
        )
        return deleted or 0


class MessageLogRepository:
    """Repository for outbound mail / SMS delivery history."""

    def __init__(self, session: Session):
        self.session = session

    def add(self, log: MessageLog) -> MessageLog:
        self.session.add(log)
        self.session.flush()
        return log

    def recent(self, limit: int = 100, channel: Optional[str] = None) -> List[MessageLog]:
        q = self.session.query(MessageLog)
        if channel:
            q = q.filter(MessageLog.channel == channel)
        return q.order_by(MessageLog.id.desc()).limit(limit).all()


class SubscriptionPlanRepository:
    """Repository for sellable subscription plans."""

    DEFAULT_PLANS = [
        {
            "code": "basic",
            "name": "বেসিক প্ল্যান",
            "name_en": "Basic Plan",
            "price": 99.0,
            "duration_days": 30,
            "features": ["স্ট্যান্ডার্ড নিউজ ফিড", "দৈনিক ২০টি আর্টিকেল", "ইমেইল সাপোর্ট"],
            "sort_order": 1,
        },
        {
            "code": "pro",
            "name": "প্রো প্ল্যান",
            "name_en": "Pro Plan",
            "price": 499.0,
            "duration_days": 30,
            "features": ["আনলিমিটেড আর্টিকেল", "AI চ্যাট ও সামথেসাইজার", "অগ্রাধিকার সাপোর্ট"],
            "sort_order": 2,
        },
        {
            "code": "enterprise",
            "name": "এন্টারপ্রাইজ প্ল্যান",
            "name_en": "Enterprise Plan",
            "price": 1999.0,
            "duration_days": 365,
            "features": ["টিম অ্যাকাউন্ট", "API এক্সেস", "ডেডিকেটেড ম্যানেজার"],
            "sort_order": 3,
        },
    ]

    def __init__(self, session: Session):
        self.session = session

    def all(self, active_only: bool = False) -> List[SubscriptionPlan]:
        q = self.session.query(SubscriptionPlan)
        if active_only:
            q = q.filter(SubscriptionPlan.is_active == True)
        return q.order_by(SubscriptionPlan.sort_order.asc(), SubscriptionPlan.id.asc()).all()

    def get_by_id(self, plan_id: int) -> Optional[SubscriptionPlan]:
        return self.session.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()

    def get_by_code(self, code: str) -> Optional[SubscriptionPlan]:
        return self.session.query(SubscriptionPlan).filter(SubscriptionPlan.code == code).first()

    def add(self, plan: SubscriptionPlan) -> SubscriptionPlan:
        self.session.add(plan)
        self.session.flush()
        return plan

    def delete(self, plan: SubscriptionPlan) -> None:
        self.session.delete(plan)
        self.session.flush()

    def ensure_default_plans(self) -> None:
        for spec in self.DEFAULT_PLANS:
            if not self.get_by_code(spec["code"]):
                self.add(SubscriptionPlan(**spec))


class PaymentRepository:
    """Repository for SSLCommerz transactions and user subscriptions."""

    def __init__(self, session: Session):
        self.session = session

    def create_transaction(self, **kwargs) -> PaymentTransaction:
        tx = PaymentTransaction(**kwargs)
        self.session.add(tx)
        self.session.flush()
        return tx

    def get_by_tran_id(self, tran_id: str) -> Optional[PaymentTransaction]:
        return (
            self.session.query(PaymentTransaction)
            .filter(PaymentTransaction.tran_id == tran_id)
            .first()
        )

    def update_transaction(self, tx: PaymentTransaction, **kwargs) -> PaymentTransaction:
        for key, value in kwargs.items():
            setattr(tx, key, value)
        self.session.flush()
        return tx

    def transactions_for_user(self, user_id: int, limit: int = 50) -> List[PaymentTransaction]:
        return (
            self.session.query(PaymentTransaction)
            .filter(PaymentTransaction.user_id == user_id)
            .order_by(PaymentTransaction.id.desc())
            .limit(limit)
            .all()
        )

    def all_transactions(self, limit: int = 100) -> List[PaymentTransaction]:
        return (
            self.session.query(PaymentTransaction)
            .order_by(PaymentTransaction.id.desc())
            .limit(limit)
            .all()
        )

    def activate_subscription(
        self,
        user_id: int,
        plan: SubscriptionPlan,
        transaction: Optional[PaymentTransaction] = None,
        duration_days: Optional[int] = None,
    ) -> UserSubscription:
        from datetime import timedelta

        now = datetime.utcnow()
        days = duration_days or plan.duration_days or 30
        sub = UserSubscription(
            user_id=user_id,
            plan_id=plan.id,
            transaction_id=transaction.id if transaction else None,
            status="active",
            started_at=now,
            expires_at=now + timedelta(days=days),
        )
        self.session.add(sub)
        self.session.flush()
        return sub

    def active_subscription(self, user_id: int) -> Optional[UserSubscription]:
        return (
            self.session.query(UserSubscription)
            .filter(
                UserSubscription.user_id == user_id,
                UserSubscription.status == "active",
                UserSubscription.expires_at > datetime.utcnow(),
            )
            .order_by(UserSubscription.expires_at.desc())
            .first()
        )

    def subscriptions_for_user(self, user_id: int, limit: int = 20) -> List[UserSubscription]:
        return (
            self.session.query(UserSubscription)
            .filter(UserSubscription.user_id == user_id)
            .order_by(UserSubscription.id.desc())
            .limit(limit)
            .all()
        )


class RawNewsItemRepository:
    """Repository for Auto Scroller raw news staging items (scrape -> mine -> rewrite -> publish)."""

    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, item_id: int) -> Optional[RawNewsItem]:
        return self.session.query(RawNewsItem).filter(RawNewsItem.id == item_id).first()

    def get_by_source_url(self, source_url: str) -> Optional[RawNewsItem]:
        return self.session.query(RawNewsItem).filter(RawNewsItem.source_url == source_url).first()

    def create_item(self, **kwargs) -> RawNewsItem:
        item = RawNewsItem(**kwargs)
        self.session.add(item)
        self.session.flush()
        return item

    def update_item(self, item: RawNewsItem, **kwargs) -> RawNewsItem:
        for key, value in kwargs.items():
            setattr(item, key, value)
        self.session.flush()
        return item

    def list_items(self, limit: int = 50, status: Optional[str] = None) -> List[RawNewsItem]:
        q = self.session.query(RawNewsItem).order_by(RawNewsItem.id.desc())
        if status:
            q = q.filter(RawNewsItem.status == status)
        return q.limit(limit).all()

    def queued_items(self) -> List[RawNewsItem]:
        return (
            self.session.query(RawNewsItem)
            .filter(RawNewsItem.status == "queued")
            .order_by(RawNewsItem.id.asc())
            .all()
        )

    def counts_by_status(self) -> Dict[str, int]:
        rows = (
            self.session.query(RawNewsItem.status, func.count(RawNewsItem.id))
            .group_by(RawNewsItem.status)
            .all()
        )
        return {status: count for status, count in rows}
