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
    url = Column(String(1024), unique=True, nullable=False, index=True)
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

    def to_dict(self) -> Dict[str, Any]:
        """Serialize article to Python dictionary."""
        return {
            "id": self.id,
            "url": self.url,
            "source": self.source,
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

    def to_dict(self) -> Dict[str, Any]:
        """Serialize image record to Python dictionary."""
        return {
            "id": self.id,
            "article_id": self.article_id,
            "original_url": self.original_url,
            "local_path": self.local_path,
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


