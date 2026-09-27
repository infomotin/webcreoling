"""
Test Suite for:
1. Heavy DataHub & High Capacity Storage Operations
2. Admin DataHub Web Endpoints
"""

import pytest
from src.storage.database import get_db_session, init_db
from src.datacenter.heavy_data_manager import (
    HeavyDataCapacityManager,
    get_heavy_data_manager,
)
from src.web.app import create_app


@pytest.fixture(scope="module", autouse=True)
def setup_database_schema():
    """Ensure database tables are initialized and created."""
    init_db()


@pytest.fixture(scope="module")
def app_instance():
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    return app


@pytest.fixture(scope="module")
def client(app_instance):
    return app_instance.test_client()


def test_heavy_data_capacity_metrics_and_operations():
    """Test heavy data storage metrics, vacuuming, and indexing operations."""
    heavy_mgr = get_heavy_data_manager()

    with get_db_session() as session:
        metrics = heavy_mgr.get_heavy_data_metrics(session)
        assert "total_articles" in metrics
        assert "total_images" in metrics
        assert "db_size_mb" in metrics
        assert "media_size_mb" in metrics
        assert "capacity_gb_limit" in metrics
        assert "category_breakdown" in metrics

        # Test Database Optimization / Vacuum
        opt_res = heavy_mgr.optimize_database(session, actor="test_admin")
        assert opt_res["success"] is True

        # Test Search Index Rebuild
        idx_res = heavy_mgr.rebuild_search_index(session, actor="test_admin")
        assert idx_res["success"] is True

        # Test Bulk Archive
        arch_res = heavy_mgr.bulk_archive_stale_articles(session, days_old=180, actor="test_admin")
        assert arch_res["success"] is True

        # Test Media Cloud Sync
        sync_res = heavy_mgr.sync_media_to_cloud(session, actor="test_admin")
        assert sync_res["success"] is True


def test_admin_datahub_web_routes(client):
    """Test admin web endpoints for heavy datahub operations."""
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = "admin"
        sess["role"] = "admin"

    opt_res = client.post("/admin/newspaper/datahub/optimize", follow_redirects=True)
    assert opt_res.status_code == 200

    arch_res = client.post("/admin/newspaper/datahub/bulk-archive", data={"days_old": "180"}, follow_redirects=True)
    assert arch_res.status_code == 200

    idx_res = client.post("/admin/newspaper/datahub/rebuild-index", follow_redirects=True)
    assert idx_res.status_code == 200

    sync_res = client.post("/admin/newspaper/datahub/media-sync", follow_redirects=True)
    assert sync_res.status_code == 200


def test_removed_vault_routes_are_gone(client):
    """All emergency-vault endpoints must no longer exist."""
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = "admin"
        sess["role"] = "admin"

    gone = [
        ("POST", "/admin/newspaper/security/vault/settings"),
        ("POST", "/admin/newspaper/security/vault/lockdown"),
        ("POST", "/admin/newspaper/security/vault/simulate-attack"),
        ("POST", "/admin/newspaper/security/vault/decrypt"),
        ("GET", "/admin/newspaper/security/vault/status"),
        ("POST", "/update_vault_settings"),
        ("POST", "/trigger_emergency_lockdown_route"),
        ("POST", "/decrypt_and_restore_vault_route"),
        ("POST", "/force_restore_all_news_route"),
        ("POST", "/simulate_attack_route"),
    ]
    for method, url in gone:
        res = client.open(url, method=method, follow_redirects=True)
        assert res.status_code == 404, f"{method} {url} should be gone, got {res.status_code}"
