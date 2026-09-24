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

        if existing:
            # Update fields
            existing.title = normalized_title
            existing.content_text = normalized_content
            existing.author = article_data.get("author") or existing.author
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
                author=article_data.get("author"),
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
        # Check explicit featured first
        hero = (
            self.session.query(Article)
            .options(joinedload(Article.images))
            .filter(Article.is_featured == True)
            .order_by(Article.published_at.desc(), Article.id.desc())
            .first()
        )
        if not hero:
            # Fallback to the latest article that has an image
            hero = (
                self.session.query(Article)
                .options(joinedload(Article.images))
                .join(ArticleImage)
                .order_by(Article.published_at.desc(), Article.id.desc())
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
            .filter(func.length(Article.content_text) > 80)
        )
        if exclude_id:
            query = query.filter(Article.id != exclude_id)

        # Order by featured first, then likes, views, and recency
        query = query.order_by(
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
            .filter(Article.is_breaking == True)
            .order_by(Article.published_at.desc(), Article.id.desc())
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
            .order_by((Article.views_count * 2 + Article.likes_count * 5).desc(), Article.id.desc())
            .limit(limit)
            .all()
        )

    def get_articles_by_category(self, category: str, limit: int = 4, exclude_id: Optional[int] = None) -> List[Article]:
        """Fetch articles belonging to a specific news category."""
        query = (
            self.session.query(Article)
            .options(joinedload(Article.images))
            .filter(Article.category == category)
        )
        if exclude_id:
            query = query.filter(Article.id != exclude_id)
        return query.order_by(Article.id.desc()).limit(limit).all()

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
    ) -> Article:
        """Create and publish a new article directly from the editorial desk."""
        import uuid
        import hashlib

        normalized_title = BanglaTextNormalizer.normalize_article_text(title.strip())
        normalized_content = BanglaTextNormalizer.normalize_article_text(content_text.strip())
        slug = uuid.uuid4().hex[:10]
        url = f"https://prothomalo.com/editorial/{slug}"

        # Determine published_at vs scheduled_at
        pub_at = None
        if scheduled_at and scheduled_at > datetime.utcnow():
            status = "scheduled"
        elif status == "completed":
            pub_at = datetime.utcnow()

        article = Article(
            url=url,
            source="প্রথম আলো সম্পাদকীয় ডেস্ক",
            title=normalized_title,
            author=author.strip() if author else "প্রথম আলো নিজস্ব প্রতিবেদক",
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
        if summary is not None:
            article.summary = summary.strip()
        if content_text is not None:
            article.content_text = BanglaTextNormalizer.normalize_article_text(content_text.strip())
        if is_featured is not None:
            article.is_featured = is_featured
        if is_breaking is not None:
            article.is_breaking = is_breaking
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
            query.order_by(Article.published_at.desc(), Article.id.desc())
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

    def seed_default_users(self) -> Dict[str, str]:
        """Seed default accounts for each role if no users exist."""
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

    def seed_default_configs(self) -> None:
        defaults = {
            "branding": {
                "site_title": "প্রথম আলো",
                "site_tagline": "অনলাইন বাংলা দৈনিক ও এআই সংবাদ প্ল্যাটফর্ম",
                "logo_text": "প্রথম আলো",
                "logo_image": "",
                "edition": "বাংলাদেশ সংস্করণ",
                "usd_rate": "১২১.৫০",
                "eur_rate": "১৩২.২০",
                "weather_city": "ঢাকা",
                "weather_temp": "২৮° সে.",
                "weather_desc": "আংশিক মেঘলা",
            },
            "footer": {
                "publisher": "প্রথম আলো এআই ও মিডিয়া ল্যাব",
                "editor_in_chief": "সম্পাদক ও প্রকাশক: মোঃ মতিউর রহমান (ভারপ্রাপ্ত)",
                "office_address": "প্রগতি ইনস্যুরেন্স ভবন, ২০–২১ কারওয়ান বাজার, ঢাকা ১২১৫।",
                "contact_email": "newsroom@prothomalo.com",
                "contact_phone": "+৮৮০ ২ ৮১৮০০৭৮",
                "copyright_text": "© ২০২৬ প্রথম আলো অনলাইন সংস্করণ। সর্বস্বত্ব সংরক্ষিত।",
                "facebook_url": "https://facebook.com/DailyProthomAlo",
                "youtube_url": "https://youtube.com/c/ProthomAlo",
                "twitter_url": "https://twitter.com/ProthomAlo",
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
        }
        for key, val in defaults.items():
            if not self.session.query(SiteConfig).filter(SiteConfig.key == key).first():
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
        if self.session.query(Advertisement).count() == 0:
            default_ads = [
                (
                    "বিকাশ ডিজিটাল পেমেন্ট অফার",
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
                    "দারাজ বৈশাখী সুপার সেল ২০২৬",
                    "article_mid",
                    "https://images.unsplash.com/photo-1607082348824-0a96f2a4b9da?w=900&auto=format&fit=crop&q=80",
                    "https://daraz.com.bd",
                ),
            ]
            for title, slot, img, url in default_ads:
                self.create_ad(title=title, slot=slot, image_url=img, target_url=url, is_active=True)


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


