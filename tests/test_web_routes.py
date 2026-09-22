"""Integration tests for Flask Web Routes and RBAC access control."""

import pytest
from src.web.app import create_app


@pytest.fixture
def client():
    """Flask test client fixture."""
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    with app.test_client() as client:
        yield client


def test_unauthenticated_redirect(client):
    """Unauthenticated access should redirect to login page."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_login_flow_and_dashboard(client):
    """Test login as admin and access dashboard."""
    # Login as admin
    response = client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"System Overview" in response.data
    assert b"Total Articles" in response.data


def test_rbac_viewer_restrictions(client):
    """Viewer should access articles but be forbidden from admin users and chat."""
    # Login as viewer
    client.post(
        "/auth/login",
        data={"username": "viewer", "password": "viewer123"},
        follow_redirects=True,
    )

    # Viewer can access articles
    res_articles = client.get("/articles", follow_redirects=True)
    assert res_articles.status_code == 200

    # Viewer denied from Admin users management (redirects or flashes warning)
    res_admin = client.get("/admin/users", follow_redirects=True)
    assert b"Access Denied" in res_admin.data or res_admin.status_code == 403

    # Viewer denied from chat
    res_chat = client.get("/chat", follow_redirects=True)
    assert b"Access Denied" in res_chat.data or res_chat.status_code == 403


def test_rbac_admin_full_access(client):
    """Admin should have access to user management and training."""
    client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=True,
    )

    # Admin accesses users management
    res_users = client.get("/admin/users", follow_redirects=True)
    assert res_users.status_code == 200
    assert b"User & Role-Based Access Control" in res_users.data

    # Admin accesses training
    res_training = client.get("/training", follow_redirects=True)
    assert res_training.status_code == 200
    assert b"LLM Training" in res_training.data
