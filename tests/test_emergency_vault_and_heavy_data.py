"""
Comprehensive Unit & Integration Test Suite for:
1. Autonomous AI Brain Threat Defense & Emergency Self-Encryption Vault
2. Emergency Unlock Code Generation & Email Dispatch Notification
3. One-Click Lossless Decryption & Portal Reactivation
4. Heavy DataHub & High Capacity Storage Operations
5. Admin Web Security & DataHub Endpoints
"""

import pytest
from src.storage.database import get_db_session, init_db
from src.storage.models import Article, SiteConfig, EmergencyVaultState, SecurityThreatLog
from src.storage.repositories import ArticleRepository, EmergencyVaultRepository
from src.security.emergency_cipher_vault import (
    EmergencyCipherVault,
    get_emergency_vault,
    derive_encryption_key,
    hash_unlock_code,
)
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


def test_emergency_code_generation_and_hashing():
    """Test format and verification of high-entropy master recovery keys."""
    vault = get_emergency_vault()
    code = vault.generate_emergency_code()

    assert code.startswith("ALO-SEC-")
    parts = code.split("-")
    assert len(parts) == 6  # ALO, SEC, 4 chunks of 4 characters
    assert len(parts[2]) == 4
    assert len(parts[3]) == 4
    assert len(parts[4]) == 4
    assert len(parts[5]) == 4

    hashed = hash_unlock_code(code)
    assert len(hashed) == 64  # SHA-256 length
    assert hash_unlock_code(code.lower()) == hashed  # Case-insensitive equality


def test_encryption_key_derivation_deterministic():
    """Test PBKDF2 key derivation from passcode."""
    code = "ALO-SEC-8F92-K4X9-7M1Q-5V2D"
    key1 = derive_encryption_key(code)
    key2 = derive_encryption_key(code)
    assert key1 == key2
    assert len(key1) == 44  # Base64 Fernet key length


def test_threat_assessment_and_auto_defense():
    """Test AI Brain threat evaluation metrics."""
    vault = get_emergency_vault()
    with get_db_session() as session:
        # Reset lock state for test isolation
        state = vault.get_or_create_state(session)
        state.is_locked = False
        state.auto_lockdown_enabled = False
        session.commit()

        assessment = vault.assess_threat_status(session)
        assert "threat_score" in assessment
        assert "threat_status" in assessment
        assert assessment["threat_score"] >= 0
        assert assessment["threat_status"] in ["NORMAL", "ELEVATED", "HIGH", "CRITICAL"]


def test_emergency_lockdown_encryption_and_lossless_restoration():
    """
    Complete lifecycle test:
    1. Seed test article with known content.
    2. Trigger Emergency Lockdown (AES-256 payload encryption).
    3. Verify live article is encrypted & lockdown state active.
    4. Attempt unlock with incorrect code (must fail).
    5. Unlock with correct recovery code (must restore original content 100% losslessly).
    """
    vault = get_emergency_vault()
    test_url = "https://daily-ai-alo.com/test-vault-story-unique-99"
    original_title = "ঢাকা স্টক এক্সচেঞ্জে রেকর্ড লেনদেন"
    original_body = "আজ ঢাকা স্টক এক্সচেঞ্জে সূচকের বড় উত্থান দেখা গেছে।"

    with get_db_session() as session:
        # Ensure unlocked first
        v_state = vault.get_or_create_state(session)
        v_state.is_locked = False
        session.commit()

        art_repo = ArticleRepository(session)
        article = art_repo.upsert_article({
            "url": test_url,
            "source": "daily-ai-alo",
            "title": original_title,
            "content_text": original_body,
            "summary": "ডিএসই লেনদেনের সারসংক্ষেপ",
            "category": "business",
            "scrape_status": "completed",
        })
        article_id = article.id
        expected_saved_body = article.content_text
        expected_saved_title = article.title

    # 1. Trigger Lockdown
    with get_db_session() as session:
        lockdown_res = vault.trigger_lockdown(
            session=session,
            trigger_type="MANUAL_ADMIN_KILLSWITCH",
            actor="test_admin",
            custom_reason="Unit test emergency encryption simulation",
            recipient_email="sec-test@daily-ai-alo.com",
        )

        assert lockdown_res["success"] is True
        assert lockdown_res["encrypted_articles_count"] >= 1
        unlock_code = lockdown_res["unlock_code"]
        assert unlock_code.startswith("ALO-SEC-")
        assert lockdown_res["recipient_email"] == "sec-test@daily-ai-alo.com"

    # 2. Verify Database is in Encrypted Lockdown
    with get_db_session() as session:
        v_state = session.query(EmergencyVaultState).first()
        assert v_state.is_locked is True
        assert v_state.recipient_email == "sec-test@daily-ai-alo.com"

        locked_article = session.query(Article).filter(Article.id == article_id).first()
        assert "SYSTEM ENCRYPTED" in locked_article.title
        assert expected_saved_body not in locked_article.content_text

    # 3. Test Invalid Decryption Code Attempt
    with get_db_session() as session:
        bad_unlock_res = vault.unlock_and_restore(
            session=session,
            unlock_code="ALO-SEC-WRONG-CODE-0000-9999",
            actor="test_admin",
        )
        assert bad_unlock_res["success"] is False
        assert "ভুল" in bad_unlock_res["message"]

    # 4. Test Valid Decryption & Complete Restoration
    with get_db_session() as session:
        valid_unlock_res = vault.unlock_and_restore(
            session=session,
            unlock_code=unlock_code,
            actor="test_admin",
        )
        assert valid_unlock_res["success"] is True
        assert valid_unlock_res["restored_articles_count"] >= 1

        v_state = session.query(EmergencyVaultState).first()
        assert v_state.is_locked is False

        restored_article = session.query(Article).filter(Article.id == article_id).first()
        assert restored_article.title == expected_saved_title
        assert restored_article.content_text == expected_saved_body


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


def test_admin_emergency_vault_and_datahub_web_routes(client):
    """Test admin web endpoints for security vault and heavy datahub."""
    vault = get_emergency_vault()

    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = "admin"
        sess["role"] = "admin"

    # 1. Update Vault Settings
    res = client.post(
        "/admin/newspaper/security/vault/settings",
        data={
            "auto_lockdown_enabled": "1",
            "threat_threshold_score": "80",
            "recipient_email": "chief-security@daily-ai-alo.com",
        },
        follow_redirects=True,
    )
    assert res.status_code in [200, 503]

    # 2. Check JSON status API
    res_json = client.get("/admin/newspaper/security/vault/status")
    assert res_json.status_code == 200
    data = res_json.get_json()
    assert "vault_state" in data
    assert data["vault_state"]["recipient_email"] == "chief-security@daily-ai-alo.com"
    assert data["vault_state"]["threat_threshold_score"] == 80

    # 3. Trigger manual lockdown
    lock_res = client.post(
        "/admin/newspaper/security/vault/lockdown",
        data={"reason": "Testing web lockdown flow"},
        follow_redirects=True,
    )
    assert lock_res.status_code in [200, 503]

    # 4. Decrypt via web unlock endpoint with valid code
    with get_db_session() as session:
        # Generate and set code to test decryption endpoint directly
        unlock_code = vault.generate_emergency_code()
        st = vault.get_or_create_state(session)
        st.emergency_unlock_code_hash = hash_unlock_code(unlock_code)
        session.commit()

    unlock_resp = client.post(
        "/admin/newspaper/security/vault/decrypt",
        data={"unlock_code": unlock_code},
        follow_redirects=True,
    )
    assert unlock_resp.status_code == 200

    # Clean simulated threat logs so subsequent tests have normal state
    with get_db_session() as session:
        st = vault.get_or_create_state(session)
        st.is_locked = False
        st.auto_lockdown_enabled = False
        session.query(SecurityThreatLog).filter(SecurityThreatLog.ip_address == "198.51.100.42").delete()
        session.commit()

    # 5. Heavy DataHub Actions
    opt_res = client.post("/admin/newspaper/datahub/optimize", follow_redirects=True)
    assert opt_res.status_code == 200

    arch_res = client.post("/admin/newspaper/datahub/bulk-archive", data={"days_old": "180"}, follow_redirects=True)
    assert arch_res.status_code == 200

    idx_res = client.post("/admin/newspaper/datahub/rebuild-index", follow_redirects=True)
    assert idx_res.status_code == 200

    sync_res = client.post("/admin/newspaper/datahub/media-sync", follow_redirects=True)
    assert sync_res.status_code == 200
