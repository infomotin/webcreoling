"""
Database Models for SQLite / SQLAlchemy 2.0.
Includes Articles, ArticleImages, ScrapeLogs, and SiteConfigs.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Boolean,
    ForeignKey,
    JSON,
    Index,
    Float,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Article(Base):
    """Stores scraped news article text, metadata, and relations to media."""
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(500), unique=True, nullable=False, index=True)
    source = Column(String(100), nullable=False, index=True)
    title = Column(Text, nullable=False)
    author = Column(String(255), nullable=True)
    published_at = Column(DateTime, nullable=True, index=True)
    category = Column(String(100), nullable=True, index=True)
    content_text = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)
    extracted_entities = Column(JSON, nullable=True)  # {"Person": [], "Location": [], ...}
    
    # Retry and Status Tracking
    scrape_status = Column(String(50), default="completed", index=True)  # 'completed', 'partial', 'failed'
    missing_fields = Column(JSON, nullable=True)  # e.g., ["lead_image", "author"]
    retry_count = Column(Integer, default=0)
    js_rendered = Column(Boolean, default=False)
    
    # Interactive Newspaper Frontend & Engagement
    is_featured = Column(Boolean, default=False, index=True)  # Highlighted Lead/Hero story
    is_breaking = Column(Boolean, default=False, index=True)  # Breaking News Ticker
    views_count = Column(Integer, default=0)
    likes_count = Column(Integer, default=0)
    shares_count = Column(Integer, default=0)
    scheduled_at = Column(DateTime, nullable=True, index=True)  # Future publishing release timestamp

    # Source provenance & status tracking
    original_source_url = Column(String(1000), nullable=True)
    source_status = Column(String(50), default="ACTIVE", index=True)  # 'ACTIVE', 'REMOVED_AT_SOURCE', 'UNAVAILABLE', 'ARCHIVED'
    source_removed_notice = Column(Text, nullable=True)
    source_last_checked_at = Column(DateTime, nullable=True)

    # Creation origin & Editorial attribution
    creation_origin = Column(String(50), default="AI_SYNTHESIZED", index=True)  # 'MANUAL', 'AI_SYNTHESIZED', 'SCRAPED', 'HYBRID'

    # Editorial layout & placement ordering
    position_placement = Column(String(50), default="STANDARD", index=True)  # 'LEAD', 'FEATURED', 'SUB_LEAD', 'BREAKING', 'CATEGORY_TOP', 'STANDARD'
    display_order = Column(Integer, default=0, index=True)  # Priority: 1 = Top, 2, 3...
    is_pinned = Column(Boolean, default=False, index=True)

    # Blockchain Cryptographic Ledger Verification
    block_number = Column(Integer, nullable=True, index=True)
    block_hash = Column(String(64), nullable=True, index=True)
    prev_hash = Column(String(64), nullable=True)
    digital_signature = Column(String(128), nullable=True)
    is_ledger_verified = Column(Boolean, default=True)

    # Audit timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    images = relationship("ArticleImage", back_populates="article", cascade="all, delete-orphan")

    @property
    def lead_image_url(self) -> str:
        """Return lead image URL or category-based default fallback SVG."""
        if self.images:
            for img in self.images:
                path = img.local_path or img.original_url
                if img.is_lead_image and path:
                    if path.startswith(("http://", "https://")):
                        return path
                    return f"/{path.lstrip('/')}"
            if self.images[0]:
                path = self.images[0].local_path or self.images[0].original_url
                if path:
                    if path.startswith(("http://", "https://")):
                        return path
                    return f"/{path.lstrip('/')}"
        cat = (self.category or "general").lower()
        valid_cats = ["politics", "bangladesh", "international", "business", "sports", "technology", "news", "entertainment", "general"]
        chosen_cat = cat if cat in valid_cats else "general"
        return f"/static/img/placeholders/{chosen_cat}.svg"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize article to Python dictionary."""
        return {
            "id": self.id,
            "url": self.url,
            "original_source_url": self.original_source_url or self.url,
            "source": self.source,
            "source_status": self.source_status or "ACTIVE",
            "source_removed_notice": self.source_removed_notice,
            "source_last_checked_at": self.source_last_checked_at.isoformat() if self.source_last_checked_at else None,
            "creation_origin": self.creation_origin or "AI_SYNTHESIZED",
            "position_placement": self.position_placement or "STANDARD",
            "display_order": self.display_order or 0,
            "is_pinned": self.is_pinned or False,
            "title": self.title,
            "author": self.author,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "category": self.category,
            "content_text": self.content_text,
            "summary": self.summary,
            "extracted_entities": self.extracted_entities or {},
            "scrape_status": self.scrape_status,
            "missing_fields": self.missing_fields or [],
            "retry_count": self.retry_count,
            "is_featured": self.is_featured,
            "is_breaking": self.is_breaking,
            "views_count": self.views_count,
            "likes_count": self.likes_count,
            "shares_count": self.shares_count,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "block_number": self.block_number,
            "block_hash": self.block_hash,
            "prev_hash": self.prev_hash,
            "digital_signature": self.digital_signature,
            "is_ledger_verified": self.is_ledger_verified,
            "images": [img.to_dict() for img in self.images] if self.images else [],
            "lead_image_url": self.lead_image_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ArticleImage(Base):
    """Stores image metadata, local filesystem paths, and SHA-256 hashes for deduplication."""
    __tablename__ = "article_images"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True)
    original_url = Column(String(1024), nullable=False)
    local_path = Column(String(1024), nullable=False)
    file_hash = Column(String(64), nullable=False, index=True)  # SHA-256
    file_size_bytes = Column(Integer, nullable=True)
    mime_type = Column(String(100), nullable=True)
    caption = Column(Text, nullable=True)
    is_lead_image = Column(Boolean, default=False, index=True)
    download_status = Column(String(50), default="downloaded")  # 'downloaded', 'failed', 'cached'
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    article = relationship("Article", back_populates="images")

    @property
    def url(self) -> str:
        """Return safe web URL for the image."""
        if self.local_path:
            if self.local_path.startswith(("http://", "https://")):
                return self.local_path
            return f"/{self.local_path.lstrip('/')}"
        if self.original_url and self.original_url.startswith(("http://", "https://")):
            return self.original_url
        return "/static/img/placeholders/general.svg"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize image record to Python dictionary."""
        return {
            "id": self.id,
            "article_id": self.article_id,
            "original_url": self.original_url,
            "local_path": self.local_path,
            "url": self.url,
            "file_hash": self.file_hash,
            "file_size_bytes": self.file_size_bytes,
            "mime_type": self.mime_type,
            "caption": self.caption,
            "is_lead_image": self.is_lead_image,
            "download_status": self.download_status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Poll(Base):
    """Interactive Reader Opinion Poll."""
    __tablename__ = "polls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    question = Column(Text, nullable=False)
    category = Column(String(100), default="national")
    is_active = Column(Boolean, default=True, index=True)
    total_votes = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    options = relationship("PollOption", back_populates="poll", cascade="all, delete-orphan")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "category": self.category,
            "is_active": self.is_active,
            "total_votes": self.total_votes,
            "options": [opt.to_dict(self.total_votes) for opt in self.options],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class PollOption(Base):
    """Options for an Opinion Poll."""
    __tablename__ = "poll_options"

    id = Column(Integer, primary_key=True, autoincrement=True)
    poll_id = Column(Integer, ForeignKey("polls.id", ondelete="CASCADE"), nullable=False, index=True)
    option_text = Column(String(255), nullable=False)
    votes_count = Column(Integer, default=0)

    # Relationships
    poll = relationship("Poll", back_populates="options")

    def to_dict(self, total_votes: int = 0) -> Dict[str, Any]:
        percentage = (self.votes_count / total_votes * 100) if total_votes > 0 else 0
        return {
            "id": self.id,
            "poll_id": self.poll_id,
            "option_text": self.option_text,
            "votes_count": self.votes_count,
            "percentage": round(percentage, 1),
        }


class PollVote(Base):
    """Tracks individual IP votes to prevent duplicate voting."""
    __tablename__ = "poll_votes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    poll_id = Column(Integer, ForeignKey("polls.id", ondelete="CASCADE"), nullable=False, index=True)
    option_id = Column(Integer, ForeignKey("poll_options.id", ondelete="CASCADE"), nullable=False)
    voter_ip = Column(String(100), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class NewsletterSubscriber(Base):
    """Reader newsletter and breaking news subscribers."""
    __tablename__ = "newsletter_subscribers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(150), unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    subscribed_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "is_active": self.is_active,
            "subscribed_at": self.subscribed_at.isoformat() if self.subscribed_at else None,
        }


class ArticleLike(Base):
    """Tracks unique article likes by reader IP."""
    __tablename__ = "article_likes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True)
    voter_ip = Column(String(100), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ScrapeLog(Base):
    """Audit log tracking scraper runs, rates, counts, and errors."""
    __tablename__ = "scrape_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(100), nullable=False, index=True)
    job_type = Column(String(50), default="crawl")
    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    articles_found = Column(Integer, default=0)
    articles_saved = Column(Integer, default=0)
    images_downloaded = Column(Integer, default=0)
    errors_count = Column(Integer, default=0)
    status = Column(String(50), default="in_progress")  # 'in_progress', 'completed', 'failed'
    error_details = Column(Text, nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "job_type": self.job_type,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "articles_found": self.articles_found,
            "articles_saved": self.articles_saved,
            "images_downloaded": self.images_downloaded,
            "errors_count": self.errors_count,
            "status": self.status,
            "error_details": self.error_details,
        }


from werkzeug.security import generate_password_hash, check_password_hash


class User(Base):
    """User account for Role-Based Access Control (RBAC) authentication."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(80), unique=True, nullable=False, index=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(30), default="viewer", nullable=False, index=True)  # 'admin', 'editor', 'analyst', 'viewer'
    is_active = Column(Boolean, default=True)
    phone = Column(String(30), nullable=True)  # optional, enables SMS OTP
    is_verified = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def set_password(self, password: str) -> None:
        """Hash and set user password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Verify password against stored hash."""
        return check_password_hash(self.password_hash, password)

    def has_role(self, *roles: str) -> bool:
        """Check if user belongs to one of the specified roles or is admin."""
        if self.role == "admin":
            return True
        return self.role in roles

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "is_active": self.is_active,
            "phone": self.phone,
            "is_verified": self.is_verified,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# Composite Indexes for optimal batch querying during training and date filtering
Index("idx_articles_source_pubdate", Article.source, Article.published_at)
Index("idx_articles_category_pubdate", Article.category, Article.published_at)
Index("idx_articles_featured", Article.is_featured, Article.published_at)


class SiteConfig(Base):
    """Stores key-value site configurations, settings, footer, branding, rates, weather, and AI pilot mode."""
    __tablename__ = "site_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(JSON, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "key": self.key,
            "value": self.value,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Advertisement(Base):
    """Stores dynamic advertisement banners for newspaper slots."""
    __tablename__ = "advertisements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    slot = Column(String(50), nullable=False, index=True)  # 'header_top', 'sidebar_square', 'article_mid', 'footer_sticky'
    image_url = Column(String(1024), nullable=False)
    target_url = Column(String(1024), nullable=False)
    is_active = Column(Boolean, default=True, index=True)
    views_count = Column(Integer, default=0)
    clicks_count = Column(Integer, default=0)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        ctr = (self.clicks_count / self.views_count * 100) if self.views_count > 0 else 0.0
        return {
            "id": self.id,
            "title": self.title,
            "slot": self.slot,
            "image_url": self.image_url,
            "target_url": self.target_url,
            "is_active": self.is_active,
            "views_count": self.views_count,
            "clicks_count": self.clicks_count,
            "ctr": round(ctr, 2),
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class EditorialAuditLog(Base):
    """Audit log trail tracking all editorial and administrative actions in the Newsroom."""
    __tablename__ = "editorial_audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=True, index=True)
    username = Column(String(80), nullable=False, index=True)
    action = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(String(100), nullable=True)
    details = Column(JSON, nullable=True)
    ip_address = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.username,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "details": self.details or {},
            "ip_address": self.ip_address,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ==============================================================================
# Enterprise Security & Cryptographic Blockchain Models
# ==============================================================================

class BlockedIP(Base):
    """Stores blacklisted IP addresses, ban reasons, strike scores, and expiration."""
    __tablename__ = "blocked_ips"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ip_address = Column(String(100), unique=True, nullable=False, index=True)
    reason = Column(String(255), default="Suspicious automated traffic")
    blocked_by = Column(String(80), default="WAF_AUTO")  # 'WAF_AUTO' or admin username
    threat_score = Column(Integer, default=100)
    expires_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "ip_address": self.ip_address,
            "reason": self.reason,
            "blocked_by": self.blocked_by,
            "threat_score": self.threat_score,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class BlockedCountry(Base):
    """Geographic firewall country blacklist with activation state."""
    __tablename__ = "blocked_countries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    country_code = Column(String(10), unique=True, nullable=False, index=True)  # ISO-2 e.g. "RU", "KP"
    country_name = Column(String(100), nullable=False)
    reason = Column(String(255), default="Geographic firewall policy")
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "country_code": self.country_code,
            "country_name": self.country_name,
            "reason": self.reason,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SecurityThreatLog(Base):
    """Live audit trail of detected web attacks, malicious payloads, and defensive actions."""
    __tablename__ = "security_threat_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    threat_type = Column(String(50), nullable=False, index=True)  # 'SQL_INJECTION', 'XSS_ATTACK', 'PATH_TRAVERSAL', 'RCE_COMMAND', 'GEO_BLOCKED', 'IP_BLACKLIST'
    ip_address = Column(String(100), nullable=False, index=True)
    request_path = Column(String(1024), nullable=False)
    request_method = Column(String(10), default="GET")
    payload_sample = Column(Text, nullable=True)
    country_code = Column(String(10), nullable=True)
    user_agent = Column(String(500), nullable=True)
    action_taken = Column(String(50), default="BLOCKED_403")  # 'BLOCKED_403', 'LOGGED_ONLY', 'AUTO_BANNED_IP'
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "threat_type": self.threat_type,
            "ip_address": self.ip_address,
            "request_path": self.request_path,
            "request_method": self.request_method,
            "payload_sample": self.payload_sample,
            "country_code": self.country_code,
            "user_agent": self.user_agent,
            "action_taken": self.action_taken,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ArticleBlockLedger(Base):
    """Cryptographic Blockchain-Style Immutable Ledger for News Article Verification."""
    __tablename__ = "article_block_ledger"

    block_number = Column(Integer, primary_key=True, autoincrement=False)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="SET NULL"), nullable=True, index=True)
    title_hash = Column(String(64), nullable=False)
    content_hash = Column(String(64), nullable=False)
    author_hash = Column(String(64), nullable=False)
    merkle_root = Column(String(64), nullable=False)
    prev_block_hash = Column(String(64), nullable=False, index=True)
    block_hash = Column(String(64), unique=True, nullable=False, index=True)
    digital_signature = Column(String(128), nullable=False)
    nonce = Column(Integer, default=0)
    timestamp = Column(DateTime, default=datetime.utcnow)
    verification_status = Column(String(50), default="VALID")  # 'VALID', 'TAMPERED', 'ORPHANED'
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "block_number": self.block_number,
            "article_id": self.article_id,
            "title_hash": self.title_hash,
            "content_hash": self.content_hash,
            "author_hash": self.author_hash,
            "merkle_root": self.merkle_root,
            "prev_block_hash": self.prev_block_hash,
            "block_hash": self.block_hash,
            "digital_signature": self.digital_signature,
            "nonce": self.nonce,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "verification_status": self.verification_status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ==============================================================================
# AI Brain Custom Rule Engine & Social Outbound Integration Models
# ==============================================================================

class AIBrainCustomRule(Base):
    """Custom Targeting Rules, Geo-Filters, Keywords, and Publishing Directives for the AI Brain."""
    __tablename__ = "ai_brain_custom_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(150), nullable=False)
    is_active = Column(Boolean, default=True, index=True)
    target_regions = Column(JSON, nullable=True)  # ["bangladesh", "south_asia", "middle_east", "global", "usa", "europe"]
    target_countries = Column(JSON, nullable=True)  # ["BD", "IN", "PK", "US", "UK", "SA", "AE", "CN"]
    target_languages = Column(JSON, nullable=True)  # ["en", "bn", "hi", "ar", "ur"]
    target_categories = Column(JSON, nullable=True)  # ["politics", "technology", "business", "international", "sports", "science"]
    required_keywords = Column(JSON, nullable=True)  # e.g., ["AI", "নির্বাচন", "বাজেট"]
    excluded_keywords = Column(JSON, nullable=True)  # e.g., ["ক্যাসিনো", "প্রাপ্তবয়স্ক", "জুয়া"]
    allowed_portal_sources = Column(JSON, nullable=True)  # e.g., ["prothomalo.com", "reuters.com", "youtube/jamunatv"]
    min_credibility_score = Column(Float, default=70.0)
    auto_translate_to_bangla = Column(Boolean, default=True)
    auto_publish = Column(Boolean, default=True)
    auto_broadcast_social = Column(Boolean, default=True)
    custom_prompt_rules = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "is_active": self.is_active,
            "target_regions": self.target_regions or [],
            "target_countries": self.target_countries or [],
            "target_languages": self.target_languages or [],
            "target_categories": self.target_categories or [],
            "required_keywords": self.required_keywords or [],
            "excluded_keywords": self.excluded_keywords or [],
            "allowed_portal_sources": self.allowed_portal_sources or [],
            "min_credibility_score": self.min_credibility_score,
            "auto_translate_to_bangla": self.auto_translate_to_bangla,
            "auto_publish": self.auto_publish,
            "auto_broadcast_social": self.auto_broadcast_social,
            "custom_prompt_rules": self.custom_prompt_rules or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SocialChannelConfig(Base):
    """Configuration for Connected Social Media Pages / Channels with Failover Support."""
    __tablename__ = "social_channel_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String(50), nullable=False, index=True)  # 'facebook', 'youtube', 'tiktok', 'telegram', 'twitter'
    account_name = Column(String(150), nullable=False)
    page_id_or_channel_id = Column(String(255), nullable=False)
    app_id = Column(String(255), nullable=True)
    app_secret = Column(String(255), nullable=True)
    access_token = Column(Text, nullable=True)
    webhook_verify_token = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    is_primary = Column(Boolean, default=True)
    status = Column(String(50), default="HEALTHY", index=True)  # 'HEALTHY', 'RESTRICTED', 'TOKEN_EXPIRED', 'BACKUP_ACTIVE'
    failover_account_id = Column(Integer, ForeignKey("social_channel_configs.id", ondelete="SET NULL"), nullable=True)
    total_posts_dispatched = Column(Integer, default=0)
    last_post_at = Column(DateTime, nullable=True)
    last_error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Self-referential relationship for failover
    failover_account = relationship("SocialChannelConfig", remote_side=[id], foreign_keys=[failover_account_id])

    def to_dict(self) -> Dict[str, Any]:
        failover_name = None
        if "failover_account" in self.__dict__ and self.failover_account:
            failover_name = self.failover_account.account_name

        return {
            "id": self.id,
            "platform": self.platform,
            "account_name": self.account_name,
            "page_id_or_channel_id": self.page_id_or_channel_id,
            "app_id": self.app_id,
            "app_secret": ("*" * 8) if self.app_secret else None,
            "access_token": (self.access_token[:10] + "..." + self.access_token[-6:]) if self.access_token and len(self.access_token) > 16 else self.access_token,
            "is_active": self.is_active,
            "is_primary": self.is_primary,
            "status": self.status,
            "failover_account_id": self.failover_account_id,
            "failover_account_name": failover_name,
            "total_posts_dispatched": self.total_posts_dispatched,
            "last_post_at": self.last_post_at.isoformat() if self.last_post_at else None,
            "last_error_message": self.last_error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SocialBroadcastLog(Base):
    """Audit log trail tracking all outbound social media cross-postings and failover dispatches."""
    __tablename__ = "social_broadcast_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="SET NULL"), nullable=True, index=True)
    channel_id = Column(Integer, ForeignKey("social_channel_configs.id", ondelete="SET NULL"), nullable=True, index=True)
    platform = Column(String(50), nullable=False, index=True)
    target_account = Column(String(150), nullable=False)
    post_payload = Column(JSON, nullable=True)
    external_post_id = Column(String(255), nullable=True)
    dispatch_status = Column(String(50), default="SUCCESS", index=True)  # 'SUCCESS', 'FAILED', 'FALLBACK_SWITCHED'
    response_data = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "article_id": self.article_id,
            "channel_id": self.channel_id,
            "platform": self.platform,
            "target_account": self.target_account,
            "post_payload": self.post_payload or {},
            "external_post_id": self.external_post_id,
            "dispatch_status": self.dispatch_status,
            "response_data": self.response_data or {},
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ==============================================================================
# Website Data Center, Cloud Storage & Database Failover Models
# ==============================================================================

class DataCenterStorageProvider(Base):
    """Stores credentials, endpoints, capacity, and CDN routing for cloud media storage (Google Drive, Mega, S3, FTP)."""
    __tablename__ = "datacenter_storage_providers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider_type = Column(String(50), nullable=False, index=True)  # 'google_drive', 'mega', 's3', 'cloudinary', 'imgur', 'ftp'
    name = Column(String(150), nullable=False)
    credentials_json = Column(JSON, nullable=True)  # {'api_key', 'client_id', 'folder_id', 'user', 'password', 'bucket', etc.}
    is_active = Column(Boolean, default=True, index=True)
    is_primary = Column(Boolean, default=False)
    cdn_base_url = Column(String(255), nullable=True)
    capacity_total_bytes = Column(Float, default=16106127360.0)  # default 15GB
    capacity_used_bytes = Column(Float, default=1073741824.0)   # default 1GB
    status = Column(String(50), default="ONLINE", index=True)   # 'ONLINE', 'SYNCING', 'DEGRADED', 'OFFLINE'
    sync_mode = Column(String(50), default="PRIMARY_CDN")       # 'PRIMARY_CDN', 'AUTO_MIRROR', 'BACKUP_ONLY'
    last_health_check = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        creds = self.credentials_json or {}
        masked_creds = {}
        for k, v in creds.items():
            if any(secret_term in k.lower() for secret_term in ["pass", "secret", "token", "key"]):
                masked_creds[k] = ("*" * 8) if v else ""
            else:
                masked_creds[k] = v

        used_gb = round(self.capacity_used_bytes / (1024 ** 3), 2)
        total_gb = round(self.capacity_total_bytes / (1024 ** 3), 2)
        used_pct = round((self.capacity_used_bytes / max(1.0, self.capacity_total_bytes)) * 100, 1)

        return {
            "id": self.id,
            "provider_type": self.provider_type,
            "name": self.name,
            "credentials": masked_creds,
            "is_active": self.is_active,
            "is_primary": self.is_primary,
            "cdn_base_url": self.cdn_base_url,
            "capacity_total_gb": total_gb,
            "capacity_used_gb": used_gb,
            "capacity_used_pct": used_pct,
            "status": self.status,
            "sync_mode": self.sync_mode,
            "last_health_check": self.last_health_check.isoformat() if self.last_health_check else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class DatabaseReplicaNode(Base):
    """Tracks primary and remote standby database replica nodes for high-availability auto-failover."""
    __tablename__ = "database_replica_nodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    node_name = Column(String(150), nullable=False)
    host = Column(String(255), nullable=False)
    port = Column(Integer, default=3306)
    database_name = Column(String(100), default="ai_news")
    username = Column(String(100), default="root")
    password_masked = Column(String(255), default="••••••••")
    is_active = Column(Boolean, default=True, index=True)
    is_current_primary = Column(Boolean, default=False, index=True)
    replication_status = Column(String(50), default="SYNCED", index=True)  # 'SYNCED', 'REPLICATING', 'STANDBY_READY', 'FAILOVER_ACTIVE', 'DISCONNECTED'
    latency_ms = Column(Float, default=1.2)
    auto_failover_priority = Column(Integer, default=1)
    last_heartbeat = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "node_name": self.node_name,
            "host": self.host,
            "port": self.port,
            "database_name": self.database_name,
            "username": self.username,
            "is_active": self.is_active,
            "is_current_primary": self.is_current_primary,
            "replication_status": self.replication_status,
            "latency_ms": self.latency_ms,
            "auto_failover_priority": self.auto_failover_priority,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class DataCenterBackupArchive(Base):
    """Tracks local and remote cloud backup archives (SQL dumps, Media Zips, Blockchain Ledgers)."""
    __tablename__ = "datacenter_backup_archives"

    id = Column(Integer, primary_key=True, autoincrement=True)
    backup_name = Column(String(255), nullable=False)
    backup_type = Column(String(50), default="DATABASE_SQL", index=True)  # 'DATABASE_SQL', 'MEDIA_ASSETS', 'FULL_SYSTEM', 'BLOCKCHAIN_LEDGER'
    file_path = Column(String(500), nullable=False)
    file_size_bytes = Column(Float, default=0.0)
    sha256_checksum = Column(String(64), nullable=True)
    target_cloud_destinations = Column(JSON, nullable=True)  # ['google_drive', 'mega', 'ftp']
    cloud_upload_status = Column(JSON, nullable=True)        # {'google_drive': 'UPLOADED', 'mega': 'UPLOADED'}
    is_encrypted = Column(Boolean, default=True)
    encryption_algorithm = Column(String(50), default="AES-256-GCM")
    status = Column(String(50), default="COMPLETED", index=True)  # 'COMPLETED', 'IN_PROGRESS', 'FAILED'
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self) -> Dict[str, Any]:
        size_mb = round(self.file_size_bytes / (1024 ** 2), 2)
        return {
            "id": self.id,
            "backup_name": self.backup_name,
            "backup_type": self.backup_type,
            "file_path": self.file_path,
            "file_size_mb": size_mb,
            "sha256_checksum": self.sha256_checksum,
            "target_cloud_destinations": self.target_cloud_destinations or [],
            "cloud_upload_status": self.cloud_upload_status or {},
            "is_encrypted": self.is_encrypted,
            "encryption_algorithm": self.encryption_algorithm,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class DataCenterSecurityLog(Base):
    """Audit logs for data center activities, failover events, backups, and cloud syncs."""
    __tablename__ = "datacenter_security_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(50), nullable=False, index=True)  # 'FAILOVER', 'BACKUP_CREATED', 'CLOUD_SYNC', 'RESTORE_EXECUTED', 'STORAGE_AUTH'
    severity = Column(String(20), default="INFO", index=True)    # 'INFO', 'WARNING', 'CRITICAL', 'SUCCESS'
    actor = Column(String(100), default="AI DataCenter Engine")
    description = Column(Text, nullable=False)
    metadata_json = Column(JSON, nullable=True)
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "severity": self.severity,
            "actor": self.actor,
            "description": self.description,
            "metadata": self.metadata_json or {},
            "ip_address": self.ip_address,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class EmergencyVaultState(Base):
    """
    State tracking for Autonomous AI Brain Self-Encryption Vault & Emergency Lockdown.
    When a critical cyberattack or tamper risk is detected (or manually triggered by Admin),
    the AI Brain encrypts all sensitive data with an AES-256 master key, puts the portal into
    Lockdown mode, and dispatches the high-entropy Emergency Decryption Code to the Security Email.
    """
    __tablename__ = "emergency_vault_states"

    id = Column(Integer, primary_key=True, autoincrement=True)
    is_locked = Column(Boolean, default=False, index=True)
    auto_lockdown_enabled = Column(Boolean, default=True, index=True)
    threat_threshold_score = Column(Integer, default=75)
    current_threat_score = Column(Integer, default=12)
    threat_status = Column(String(50), default="NORMAL", index=True)  # 'NORMAL', 'ELEVATED', 'HIGH', 'CRITICAL'
    lockdown_trigger = Column(String(100), nullable=True)             # 'AUTO_AI_BRAIN_BREACH_DETECTED', 'MANUAL_ADMIN_KILLSWITCH', 'SIMULATED_TEST'
    threat_summary = Column(Text, nullable=True)

    # Cryptographic recovery & encryption metadata
    emergency_unlock_code_hash = Column(String(128), nullable=True)
    emergency_unlock_code_hint = Column(String(100), nullable=True)   # 'ALO-SEC-9X4F-****-****'
    encryption_algorithm = Column(String(50), default="AES-256-GCM")
    encrypted_articles_count = Column(Integer, default=0)
    encrypted_users_count = Column(Integer, default=0)
    encrypted_configs_count = Column(Integer, default=0)

    # Emergency Email Dispatch
    recipient_email = Column(String(255), default="security-officer@daily-ai-alo.com")
    email_dispatch_status = Column(String(50), default="IDLE")       # 'SENT', 'SIMULATED_SUCCESS', 'FAILED'
    email_dispatch_log = Column(Text, nullable=True)

    # Recovery and Audit
    failed_unlock_attempts = Column(Integer, default=0)
    locked_at = Column(DateTime, nullable=True)
    unlocked_at = Column(DateTime, nullable=True)
    unlocked_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "is_locked": self.is_locked,
            "auto_lockdown_enabled": self.auto_lockdown_enabled,
            "threat_threshold_score": self.threat_threshold_score,
            "current_threat_score": self.current_threat_score,
            "threat_status": self.threat_status,
            "lockdown_trigger": self.lockdown_trigger,
            "threat_summary": self.threat_summary,
            "emergency_unlock_code_hint": self.emergency_unlock_code_hint,
            "encryption_algorithm": self.encryption_algorithm,
            "encrypted_articles_count": self.encrypted_articles_count,
            "encrypted_users_count": self.encrypted_users_count,
            "encrypted_configs_count": self.encrypted_configs_count,
            "recipient_email": self.recipient_email,
            "email_dispatch_status": self.email_dispatch_status,
            "email_dispatch_log": self.email_dispatch_log,
            "failed_unlock_attempts": self.failed_unlock_attempts,
            "locked_at": self.locked_at.isoformat() if self.locked_at else None,
            "unlocked_at": self.unlocked_at.isoformat() if self.unlocked_at else None,
            "unlocked_by": self.unlocked_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class EncryptedVaultBackupRecord(Base):
    """Stores encrypted table snapshots during emergency lockdown for flawless zero-loss restoration."""
    __tablename__ = "encrypted_vault_backup_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    table_name = Column(String(100), nullable=False, index=True)
    record_id = Column(String(100), nullable=False, index=True)
    encrypted_payload = Column(Text, nullable=False)
    iv_nonce = Column(String(64), nullable=False)
    auth_tag = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class OtpCode(Base):
    """Stores hashed one-time verification codes (email / SMS) for auth flows."""
    __tablename__ = "otp_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel = Column(String(20), nullable=False, default="email")  # 'email' | 'sms'
    destination = Column(String(255), nullable=False, index=True)
    purpose = Column(String(50), nullable=False, index=True)  # register_verify | login_2fa | password_reset | test
    code_hash = Column(String(255), nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=5, nullable=False)
    user_id = Column(Integer, nullable=True, index=True)
    is_used = Column(Boolean, default=False, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "channel": self.channel,
            "destination": self.destination,
            "purpose": self.purpose,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "is_used": self.is_used,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class MessageLog(Base):
    """Outbound mail / SMS delivery log for system-generated messages."""
    __tablename__ = "message_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel = Column(String(20), nullable=False, index=True)  # 'mail' | 'sms'
    recipient = Column(String(255), nullable=False, index=True)
    subject = Column(String(255), nullable=True)
    body = Column(Text, nullable=True)
    purpose = Column(String(50), nullable=True, default="general")
    status = Column(String(30), nullable=False, default="SENT")  # SENT | SIMULATED | FAILED
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "channel": self.channel,
            "recipient": self.recipient,
            "subject": self.subject,
            "purpose": self.purpose,
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SubscriptionPlan(Base):
    """Sellable subscription plans checked out via SSLCommerz."""
    __tablename__ = "subscription_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(120), nullable=False)
    name_en = Column(String(120), nullable=True)
    price = Column(Float, nullable=False, default=0.0)
    currency = Column(String(10), nullable=False, default="BDT")
    duration_days = Column(Integer, nullable=False, default=30)
    features = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "name_en": self.name_en,
            "price": self.price,
            "currency": self.currency,
            "duration_days": self.duration_days,
            "features": self.features or [],
            "is_active": self.is_active,
            "sort_order": self.sort_order,
        }


class PaymentTransaction(Base):
    """SSLCommerz checkout sessions and validation results."""
    __tablename__ = "payment_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tran_id = Column(String(80), unique=True, nullable=False, index=True)
    session_key = Column(String(255), nullable=True)
    user_id = Column(Integer, nullable=True, index=True)
    plan_id = Column(Integer, nullable=True, index=True)
    amount = Column(Float, nullable=False, default=0.0)
    currency = Column(String(10), nullable=False, default="BDT")
    status = Column(String(30), nullable=False, default="PENDING", index=True)  # PENDING|VALID|FAILED|CANCELLED
    payment_method = Column(String(50), nullable=True)
    bank_tran_id = Column(String(80), nullable=True)
    risk_level = Column(String(20), nullable=True)
    raw_response = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tran_id": self.tran_id,
            "user_id": self.user_id,
            "plan_id": self.plan_id,
            "amount": self.amount,
            "currency": self.currency,
            "status": self.status,
            "payment_method": self.payment_method,
            "bank_tran_id": self.bank_tran_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class UserSubscription(Base):
    """Active entitlement granted after a validated payment."""
    __tablename__ = "user_subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    plan_id = Column(Integer, nullable=False, index=True)
    transaction_id = Column(Integer, nullable=True)
    status = Column(String(30), nullable=False, default="active")  # active | expired | cancelled
    started_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "plan_id": self.plan_id,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }
