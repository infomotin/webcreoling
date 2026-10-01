"""
Database Engine & Session Management for SQLite.
Configures WAL mode, Foreign Keys, and FTS5 Full-Text Search indexing.
"""

import urllib.parse
from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine, text, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session
from config.settings import settings
from src.common.logger import get_logger
from src.storage.models import (
    Base,
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
)

logger = get_logger("webcreoling.storage.database")


def _redact_url(url: str) -> str:
    """Hide credentials before a database URL reaches the log."""
    try:
        parts = urllib.parse.urlsplit(url)
        if parts.username or parts.password:
            host = parts.hostname or ""
            if parts.port:
                host = f"{host}:{parts.port}"
            netloc = f"{parts.username}:***@{host}" if parts.username else f"***@{host}"
            return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except ValueError:
        pass
    return url

if not settings.DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not configured. Copy .env.example to .env (or export "
        "DATABASE_URL) — credentials are intentionally not hardcoded."
    )

# Ensure DB directory exists if using SQLite
if "sqlite" in settings.DATABASE_URL:
    settings.DB_DIR.mkdir(parents=True, exist_ok=True)

# Build engine configuration depending on dialect
engine_kwargs = {"echo": settings.SQL_ECHO, "pool_pre_ping": True}
if "sqlite" in settings.DATABASE_URL:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
elif "mysql" in settings.DATABASE_URL:
    engine_kwargs["pool_recycle"] = 3600
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20

# Create Engine
engine: Engine = create_engine(
    settings.DATABASE_URL,
    **engine_kwargs
)


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable WAL mode, foreign keys, and fast busy timeouts on SQLite connections."""
    try:
        # Only execute SQLite pragmas if the DBAPI is sqlite3
        if dbapi_connection.__class__.__module__.startswith("sqlite3"):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.execute("PRAGMA busy_timeout=10000;")  # 10s busy timeout
            cursor.close()
    except Exception as e:
        logger.debug(f"SQLite pragma error ignored: {e}")


SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)


def _ensure_indexes(table_name: str, wanted: dict) -> None:
    """Create any missing index on ``table_name`` (portable SQLite/MySQL/MariaDB).

    ``wanted`` maps index name -> tuple of column names. Indexes are only
    created when absent so this is safe to run on every startup, and it works
    on MySQL, which does not support ``CREATE INDEX IF NOT EXISTS``.
    """
    try:
        from sqlalchemy import inspect

        inspector = inspect(engine)
        if table_name not in inspector.get_table_names():
            return
        existing = {idx["name"] for idx in inspector.get_indexes(table_name)}
        for name, columns in wanted.items():
            if name in existing:
                continue
            cols = ", ".join(columns)
            try:
                with engine.connect() as conn:
                    conn.execute(text(f"CREATE INDEX {name} ON {table_name} ({cols});"))
                    conn.commit()
                logger.info(f"Created index {name} on {table_name}({cols})")
            except Exception as exc:
                logger.debug(f"Index {name} not created (may already exist): {exc}")
    except Exception as exc:
        logger.debug(f"Index check skipped for {table_name}: {exc}")


def init_db() -> None:
    """Initialize relational tables and SQLite FTS5 Full-Text Search index."""
    logger.info(f"Initializing database at {_redact_url(settings.DATABASE_URL)}...")
    Base.metadata.create_all(bind=engine)

    # Database column migration check for articles table (SQLite & MySQL)
    new_columns = [
        "is_featured BOOLEAN DEFAULT 0",
        "is_breaking BOOLEAN DEFAULT 0",
        "views_count INTEGER DEFAULT 0",
        "likes_count INTEGER DEFAULT 0",
        "shares_count INTEGER DEFAULT 0",
        "scheduled_at DATETIME",
        "block_number INTEGER",
        "block_hash VARCHAR(64)",
        "prev_hash VARCHAR(64)",
        "digital_signature VARCHAR(128)",
        "is_ledger_verified BOOLEAN DEFAULT 1",
        "original_source_url VARCHAR(1000)",
        "source_status VARCHAR(50) DEFAULT 'ACTIVE'",
        "source_removed_notice TEXT",
        "source_last_checked_at DATETIME",
        "creation_origin VARCHAR(50) DEFAULT 'AI_SYNTHESIZED'",
        "position_placement VARCHAR(50) DEFAULT 'STANDARD'",
        "display_order INTEGER DEFAULT 0",
        "is_pinned BOOLEAN DEFAULT 0",
        "slug VARCHAR(250)",
        "video_type VARCHAR(20) DEFAULT 'NONE'",
        "video_url VARCHAR(1000)",
        "video_path VARCHAR(1000)",
        "video_caption VARCHAR(255)",
    ]
    try:
        from sqlalchemy import inspect
        inspector = inspect(engine)
        if "articles" in inspector.get_table_names():
            existing_cols = {col["name"].lower() for col in inspector.get_columns("articles")}
            with engine.connect() as conn:
                for col_def in new_columns:
                    col_name = col_def.split()[0].lower()
                    if col_name not in existing_cols:
                        try:
                            conn.execute(text(f"ALTER TABLE articles ADD COLUMN {col_def};"))
                            conn.commit()
                        except Exception:
                            pass
    except Exception as e:
        logger.debug(f"Column migration check note: {e}")

    # Public permalink slug lookup speed-up (safe to run repeatedly)
    _ensure_indexes(
        "articles",
        {
            "idx_articles_slug": ("slug",),
            "ix_articles_status_published": ("scrape_status", "published_at"),
            "ix_articles_category_status_pubdate": ("category", "scrape_status", "published_at"),
            "ix_articles_status_scheduled": ("scrape_status", "scheduled_at"),
            "ix_articles_highlight_order": (
                "scrape_status", "is_pinned", "display_order", "is_featured",
                "likes_count", "views_count", "id",
            ),
        },
    )

    # Users table column migration (OTP / SMS support)
    try:
        from sqlalchemy import inspect
        inspector = inspect(engine)
        user_columns = [
            "phone VARCHAR(30)",
            "is_verified BOOLEAN DEFAULT 1",
        ]
        if "users" in inspector.get_table_names():
            existing_cols = {col["name"].lower() for col in inspector.get_columns("users")}
            with engine.connect() as conn:
                for col_def in user_columns:
                    col_name = col_def.split()[0].lower()
                    if col_name not in existing_cols:
                        try:
                            conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_def};"))
                            conn.commit()
                        except Exception:
                            pass
    except Exception as e:
        logger.debug(f"Users column migration note: {e}")

    if "sqlite" in engine.url.drivername:
        with engine.begin() as conn:
            try:
                # Create FTS5 virtual table if it does not exist
                conn.execute(
                    text(
                        """
                        CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
                            id UNINDEXED,
                            title,
                            content_text,
                            category,
                            author,
                            source UNINDEXED,
                            tokenize = 'unicode61'
                        );
                        """
                    )
                )

                # Create Triggers to keep FTS5 in sync with articles table
                conn.execute(
                    text(
                        """
                        CREATE TRIGGER IF NOT EXISTS articles_ai AFTER INSERT ON articles BEGIN
                            INSERT INTO articles_fts(id, title, content_text, category, author, source)
                            VALUES (new.id, new.title, new.content_text, new.category, new.author, new.source);
                        END;
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        CREATE TRIGGER IF NOT EXISTS articles_ad AFTER DELETE ON articles BEGIN
                            DELETE FROM articles_fts WHERE id = old.id;
                        END;
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        CREATE TRIGGER IF NOT EXISTS articles_au AFTER UPDATE ON articles BEGIN
                            DELETE FROM articles_fts WHERE id = old.id;
                            INSERT INTO articles_fts(id, title, content_text, category, author, source)
                            VALUES (new.id, new.title, new.content_text, new.category, new.author, new.source);
                        END;
                        """
                    )
                )
            except Exception as e:
                logger.warning(f"FTS5 setup skipped or error: {e}")
    logger.info("Database and search index initialized successfully.")


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Context manager for scoped database sessions."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Database session error: {e}", exc_info=True)
        raise
    finally:
        session.close()
