"""
Pytest Fixtures — Shared test infrastructure for WebCreoling pipeline tests.
Provides isolated in-memory SQLite sessions with FTS5 triggers, mock article data,
and scraper engine fixtures.
"""

import pytest
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from src.storage.models import Base, Article, ArticleImage
from src.storage.repositories import ArticleRepository


# ---------------------------------------------------------------------------
# In-memory SQLite DB with FTS5 support
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def db_engine():
    """Create a fresh in-memory SQLite engine per test function."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    # Enable SQLite pragmas
    with engine.begin() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL;"))
        conn.execute(text("PRAGMA foreign_keys=ON;"))

    Base.metadata.create_all(bind=engine)

    # Create FTS5 virtual table and sync triggers (mirrors database.py init_db)
    with engine.begin() as conn:
        try:
            conn.execute(text("""
                CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
                    id UNINDEXED,
                    title,
                    content_text,
                    category,
                    author,
                    source UNINDEXED,
                    tokenize = 'unicode61'
                );
            """))
            conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS articles_ai AFTER INSERT ON articles BEGIN
                    INSERT INTO articles_fts(id, title, content_text, category, author, source)
                    VALUES (new.id, new.title, new.content_text, new.category, new.author, new.source);
                END;
            """))
            conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS articles_ad AFTER DELETE ON articles BEGIN
                    DELETE FROM articles_fts WHERE id = old.id;
                END;
            """))
            conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS articles_au AFTER UPDATE ON articles BEGIN
                    DELETE FROM articles_fts WHERE id = old.id;
                    INSERT INTO articles_fts(id, title, content_text, category, author, source)
                    VALUES (new.id, new.title, new.content_text, new.category, new.author, new.source);
                END;
            """))
        except Exception:
            pass  # FTS5 may not be available in some SQLite builds

    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    """Provide a transactional session for each test — rolls back on test end."""
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="function")
def article_repo(db_session):
    """Convenience fixture for ArticleRepository."""
    return ArticleRepository(db_session)


# ---------------------------------------------------------------------------
# Sample article data factory
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_article_data():
    """Return a dict suitable for ArticleRepository.upsert_article()."""
    return {
        "url": "http://test-portal.bd/news/test-article-001",
        "source": "test_portal",
        "title": "সংসদে গুরুত্বপূর্ণ বিল পাস হয়েছে",
        "author": "নিজস্ব প্রতিবেদক",
        "published_at": datetime(2026, 9, 22, 10, 0, 0),
        "category": "politics",
        "content_text": (
            "জাতীয় সংসদে আজ একটি গুরুত্বপূর্ণ বিল পাস হয়েছে। "
            "সরকারের পক্ষ থেকে দ্রুত কাজ সম্পন্ন করার নির্দেশ দেওয়া হয়েছে। "
            "বিরোধী দল এই বিলের বিরোধিতা করেছে।"
        ),
        "summary": "সংসদে বিল পাস নিয়ে আলোচনা।",
        "scrape_status": "completed",
        "extracted_entities": {
            "Person": ["প্রধানমন্ত্রী"],
            "Location": ["ঢাকা", "বাংলাদেশ"],
            "Organization": ["সংসদ"],
        },
    }


@pytest.fixture
def sample_image_records():
    """Return image metadata records for upsert_article()."""
    return [
        {
            "original_url": "http://test-portal.bd/images/news1.jpg",
            "local_path": "data/images/test_portal/2026-09/abc123def456.jpg",
            "file_hash": "abc123def456abc123def456",
            "file_size_bytes": 55000,
            "mime_type": "image/jpeg",
            "width": 800,
            "height": 600,
            "is_lead_image": True,
        }
    ]


@pytest.fixture
def populated_db(db_session, article_repo, sample_article_data, sample_image_records):
    """Fixture that inserts several articles into the DB for retrieval/search tests."""
    articles_data = [
        {**sample_article_data, "url": f"http://test-portal.bd/news/{i}", "title": f"খবর {i}: {sample_article_data['title']}"}
        for i in range(1, 6)
    ]
    for adata in articles_data:
        article_repo.upsert_article(adata, image_records=sample_image_records)
    db_session.commit()
    return db_session
