"""Unit tests for User Authentication and RBAC models."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.storage.models import Base, User
from src.storage.repositories import UserRepository


@pytest.fixture
def user_repo():
    """In-memory UserRepository fixture."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    repo = UserRepository(session)
    yield repo
    session.close()


def test_password_hashing(user_repo):
    user = user_repo.create_user("testuser", "test@example.com", "secret123", role="editor")
    assert user.id is not None
    assert user.check_password("secret123") is True
    assert user.check_password("wrongpassword") is False
    assert user.password_hash != "secret123"


def test_user_authentication(user_repo):
    user_repo.create_user("admin_user", "admin@test.com", "admin_pass", role="admin")
    auth_user = user_repo.authenticate("admin_user", "admin_pass")
    assert auth_user is not None
    assert auth_user.role == "admin"

    # Authenticate via email
    auth_email = user_repo.authenticate("admin@test.com", "admin_pass")
    assert auth_email is not None

    # Invalid password
    assert user_repo.authenticate("admin_user", "bad_pass") is None


def test_role_checking(user_repo):
    admin = user_repo.create_user("adm", "adm@test.com", "pass", role="admin")
    editor = user_repo.create_user("ed", "ed@test.com", "pass", role="editor")
    viewer = user_repo.create_user("vw", "vw@test.com", "pass", role="viewer")

    assert admin.has_role("viewer") is True  # Admin has access to all roles
    assert admin.has_role("editor") is True
    assert editor.has_role("editor", "admin") is True
    assert editor.has_role("admin") is False
    assert viewer.has_role("editor") is False


def test_seed_default_users(user_repo):
    seeded = user_repo.seed_default_users()
    assert "admin" in seeded
    assert "editor" in seeded
    assert "analyst" in seeded
    assert "viewer" in seeded

    # Second seed should do nothing
    second_seed = user_repo.seed_default_users()
    assert len(second_seed) == 0
