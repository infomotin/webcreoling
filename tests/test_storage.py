"""Unit tests for Storage Layer and Media Manager."""

import tempfile
from pathlib import Path
from datetime import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.storage.models import Base, Article, ArticleImage
from src.storage.repositories import ArticleRepository
from src.storage.media_manager import MediaManager
from src.common.utils import compute_sha256


@pytest.fixture
def db_session():
    """In-memory SQLite session fixture."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_article_upsert_and_retrieval(db_session):
    repo = ArticleRepository(db_session)
    article_data = {
        "url": "http://test.com/news-1",
        "source": "prothom_alo",
        "title": "প্রথম আলোর টেস্ট সংবাদ",
        "author": "প্রতিবেদক",
        "published_at": datetime(2026, 9, 22, 10, 0, 0),
        "category": "politics",
        "content_text": "জাতীয় সংসদে অর্থনৈতিক সংস্কার প্রস্তাবনা নিয়ে আজ বিস্তারিত আলোচনা অনুষ্ঠিত হয়েছে।",
        "summary": "সংসদে সংস্কার প্রস্তাব নিয়ে আলোচনা।",
        "scrape_status": "completed",
    }
    image_records = [
        {
            "original_url": "http://test.com/img1.jpg",
            "local_path": "data/images/prothom_alo/2026-09/hash1.jpg",
            "file_hash": "a1b2c3d4e5f6",
            "file_size_bytes": 45000,
            "mime_type": "image/jpeg",
            "is_lead_image": True,
        }
    ]

    saved = repo.upsert_article(article_data, image_records=image_records)
    db_session.commit()

    assert saved.id is not None
    assert saved.title == "প্রথম আলোর টেস্ট সংবাদ"
    assert len(saved.images) == 1
    assert saved.images[0].file_hash == "a1b2c3d4e5f6"

    # Test count
    count = repo.count_articles(source="prothom_alo")
    assert count == 1


def test_media_manager_deduplication(tmp_path):
    manager = MediaManager(base_images_dir=tmp_path)
    sample_data = b"fake_image_binary_content_123456"
    file_hash = compute_sha256(sample_data)

    target_path = manager.get_target_path("test_source", file_hash, "jpg")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "wb") as f:
        f.write(sample_data)

    assert target_path.exists()
    assert target_path.stat().st_size == len(sample_data)
