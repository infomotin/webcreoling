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
)

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
        Search articles using SQLite FTS5 index.
        Falls back to LIKE queries if FTS table is unavailable.
        """
        cleaned_query = query_text.strip().replace("'", "''").replace('"', '""')
        if not cleaned_query:
            return []

        try:
            # FTS5 MATCH query with BM25 ranking
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
            # Create FTS5 query token string (OR terms)
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
            # Fallback to standard LIKE
            like_pattern = f"%{cleaned_query}%"
            fallback_res = (
                self.session.query(Article)
                .filter(
                    (Article.title.like(like_pattern)) | (Article.content_text.like(like_pattern))
                )
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

    def seed_default_poll(self) -> None:
        """Seed initial active poll if none exists."""
        active = self.get_active_poll()
        if not active:
            self.create_poll(
                question="২০২৬ সালের বাজেটে প্রযুক্তিতে এআই অটোমেশন ও স্মার্ট বাংলাদেশ অবকাঠামোতে বরাদ্দ কি পর্যাপ্ত?",
                options=["হ্যাঁ, যথেষ্ট", "না, আরও বাড়ানো উচিত", "মন্তব্য নেই"],
                category="জাতীয়",
            )
