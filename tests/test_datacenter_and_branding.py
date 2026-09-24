"""
Unit and Integration Tests for Website Data Center, Parallel Cloud Media Storage,
Database High-Availability (HA) Auto-Failover, Automated Backups, and "The Daily AI Alo" Branding.
"""

import os
import json
import pytest
from pathlib import Path
from src.storage.database import get_db_session, init_db
from src.storage.repositories import (
    DataCenterRepository,
    SiteConfigRepository,
    UserRepository,
)
from src.datacenter.storage_manager import CloudStorageManager
from src.datacenter.database_failover_manager import DatabaseFailoverManager
from src.datacenter.backup_restore_manager import BackupRestoreManager
from src.web.app import create_app


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    init_db()


@pytest.fixture(scope="module")
def app_client():
    init_db()
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    with app.test_client() as client:
        yield client, app


def test_site_branding_daily_ai_alo():
    """Verify site branding is seeded as 'The Daily AI Alo' (দি ডেইলি এআই আলো) with Bengali tagline & slogan."""
    with get_db_session() as session:
        cfg_repo = SiteConfigRepository(session)
        cfg_repo.seed_default_configs(force=True)
        branding = cfg_repo.get_config("branding", {})

        assert branding.get("site_title") == "দি ডেইলি এআই আলো"
        assert branding.get("site_title_en") == "The Daily AI Alo"
        assert branding.get("site_tagline") == "পুরোপুরি এআই ভিত্তিক সংবাদ পোর্টাল"
        assert branding.get("site_motto") == "বিশ্বের সব সংবাদ একই জায়গায় ও বাংলায়"
        assert "The Daily AI Alo" in branding.get("logo_subtitle", "")


def test_cloud_storage_manager():
    """Verify cloud storage connection testing, CDN URL generation, and media uploading."""
    gdrive_conf = {
        "provider_type": "google_drive",
        "name": "Google Drive Media Hub",
        "credentials": {"api_key": "AIzaSyD_TEST_KEY", "folder_id": "root_folder_123"},
        "capacity_total_gb": 100.0,
        "capacity_used_gb": 12.5,
    }
    gdrive_res = CloudStorageManager.test_provider_connection(gdrive_conf)
    assert gdrive_res["success"] is True
    assert gdrive_res["status"] == "ONLINE"

    mega_conf = {
        "provider_type": "mega",
        "name": "Mega Encrypted Vault",
        "credentials": {"user_email": "admin@daily-ai-alo.com", "api_key": "sec_key"},
    }
    mega_res = CloudStorageManager.test_provider_connection(mega_conf)
    assert mega_res["success"] is True

    # Test CDN URL generator
    gdrive_cdn = CloudStorageManager.generate_public_cdn_url("google_drive", "sample_image.jpg")
    assert "drive.google.com" in gdrive_cdn
    assert "sample_image.jpg" in gdrive_cdn

    s3_cdn = CloudStorageManager.generate_public_cdn_url("s3", "news_lead.png")
    assert "wasabisys.com" in s3_cdn or "s3" in s3_cdn

    # Test file upload
    test_bytes = b"FAKE_IMAGE_BYTES_FOR_DAILY_AI_ALO"
    upload_res = CloudStorageManager.upload_media_file(
        file_data=test_bytes,
        filename="test_upload.jpg",
        mirror=True,
    )
    assert upload_res["success"] is True
    assert len(upload_res["sha256"]) == 64
    assert Path(upload_res["local_path"]).exists()


def test_database_failover_manager():
    """Verify database HA cluster ping, health audit, and failover promotion."""
    with get_db_session() as session:
        dc_repo = DataCenterRepository(session)
        dc_repo.seed_default_replica_nodes()
        nodes = dc_repo.list_replica_nodes()

        assert len(nodes) >= 2
        primary_node = next((n for n in nodes if n.is_current_primary), None)
        assert primary_node is not None

        # Audit cluster health
        health = DatabaseFailoverManager.audit_cluster_health(nodes)
        assert health["cluster_status"] in ["HEALTHY", "FAILOVER_NEEDED"]
        assert len(health["nodes"]) >= 2

        # Standby node promotion
        standby_node = next((n for n in nodes if not n.is_current_primary), None)
        assert standby_node is not None

        failover_res = DatabaseFailoverManager.execute_failover_promotion(
            target_replica_node=standby_node,
            previous_primary_node=primary_node,
            reason="Integration Test Promotion",
        )
        assert failover_res["success"] is True
        assert failover_res["new_primary_id"] == standby_node.id

        # Update in repository
        dc_repo.set_primary_node(standby_node.id)
        current = dc_repo.get_current_primary_node()
        assert current.id == standby_node.id

        # Revert back to node 1
        dc_repo.set_primary_node(primary_node.id)


def test_backup_restore_manager():
    """Verify database SQL dump, media zip packing, full system backup, and one-click restore."""
    with get_db_session() as session:
        # 1. SQL Dump
        sql_res = BackupRestoreManager.generate_database_dump(session, "test_db_dump.sql")
        assert sql_res["backup_type"] == "DATABASE_SQL"
        assert Path(sql_res["file_path"]).exists()
        assert len(sql_res["sha256_checksum"]) == 64

        # 2. Media Backup
        media_res = BackupRestoreManager.generate_media_backup("test_media_bundle.zip")
        assert media_res["backup_type"] == "MEDIA_ASSETS"
        assert Path(media_res["file_path"]).exists()

        # 3. Full System Backup
        full_res = BackupRestoreManager.generate_full_system_backup(session, "test_full_backup.zip")
        assert full_res["backup_type"] == "FULL_SYSTEM"
        assert Path(full_res["file_path"]).exists()

        # 4. Restore
        restore_res = BackupRestoreManager.restore_from_backup_file(full_res["file_path"], session)
        assert restore_res["success"] is True
        assert restore_res["sha256_checksum"] == full_res["sha256_checksum"]


def test_datacenter_http_routes(app_client):
    """Test Flask DataCenter blueprint endpoints, authentication, and actions."""
    client, app = app_client

    # Login as admin
    login_resp = client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=True,
    )
    assert login_resp.status_code == 200

    # 1. GET /admin/datacenter dashboard
    resp = client.get("/admin/datacenter")
    assert resp.status_code == 200
    assert "দি ডেইলি এআই আলো" in resp.get_data(as_text=True)
    assert "Google Drive" in resp.get_data(as_text=True)
    assert "HA AUTO-FAILOVER ACTIVE" in resp.get_data(as_text=True)

    # 2. GET /admin/datacenter/api/status
    status_resp = client.get("/admin/datacenter/api/status")
    assert status_resp.status_code == 200
    status_data = json.loads(status_resp.data)
    assert "summary" in status_data
    assert "nodes" in status_data
    assert "providers" in status_data

    # 3. POST /admin/datacenter/backup/create
    backup_post = client.post(
        "/admin/datacenter/backup/create",
        data={"backup_type": "DATABASE_SQL", "auto_cloud_sync": "1"},
        follow_redirects=True,
    )
    assert backup_post.status_code == 200
    assert "সফলভাবে তৈরি হয়েছে" in backup_post.get_data(as_text=True)

    # 4. Test Public Newspaper Portal Branding
    portal_resp = client.get("/news")
    assert portal_resp.status_code == 200
    portal_text = portal_resp.get_data(as_text=True)
    assert "দি ডেইলি এআই আলো" in portal_text
    assert "The Daily AI Alo" in portal_text
    assert "বিশ্বের সব সংবাদ একই জায়গায় ও বাংলায়" in portal_text
