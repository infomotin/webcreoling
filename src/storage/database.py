"""
Database Engine & Session Management for SQLite.
Configures WAL mode, Foreign Keys, and FTS5 Full-Text Search indexing.
"""

from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine, text, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session
from config.settings import settings
from src.common.logger import get_logger
from src.storage.models import Base

logger = get_logger("webcreoling.storage.database")

# Ensure DB directory exists
settings.DB_DIR.mkdir(parents=True, exist_ok=True)

# Create Engine
engine: Engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.SQL_ECHO,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
    pool_pre_ping=True,
)


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable WAL mode, foreign keys, and fast busy timeouts on SQLite connections."""
    if "sqlite" in settings.DATABASE_URL:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA busy_timeout=10000;")  # 10s busy timeout
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Initialize relational tables and SQLite FTS5 Full-Text Search index."""
    logger.info(f"Initializing database at {settings.DATABASE_URL}...")
    Base.metadata.create_all(bind=engine)

    # SQLite column migration check for articles table
    if "sqlite" in settings.DATABASE_URL:
        with engine.connect() as conn:
            for col_def in [
                "is_featured BOOLEAN DEFAULT 0",
                "is_breaking BOOLEAN DEFAULT 0",
                "views_count INTEGER DEFAULT 0",
                "likes_count INTEGER DEFAULT 0",
                "shares_count INTEGER DEFAULT 0",
            ]:
                try:
                    conn.execute(text(f"ALTER TABLE articles ADD COLUMN {col_def};"))
                    conn.commit()
                except Exception:
                    # Column already exists or table freshly created
                    pass

        with engine.begin() as conn:
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
    logger.info("Database and FTS5 search index initialized successfully.")


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
