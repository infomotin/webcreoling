"""
Comprehensive Test Suite for Enterprise Security, WAF Firewall, and Cryptographic Blockchain Ledger.
Tests SHA-256 Merkle proofs, HMAC digital signatures, tampering detection, IP blacklists,
Country Geo-Firewall, and WAF deep payload inspection.
"""

import pytest
from datetime import datetime, timedelta
from flask import Flask
from src.common.blockchain import BlockchainLedgerEngine, GENESIS_PREV_HASH
from src.storage.database import get_db_session, init_db
from src.storage.models import Article, BlockedIP, BlockedCountry, SecurityThreatLog, ArticleBlockLedger
from src.storage.repositories import (
    ArticleRepository,
    SecurityRepository,
    BlockchainLedgerRepository,
    UserRepository,
)
from src.web.app import create_app


# ==============================================================================
# 1. Cryptographic Blockchain Engine Unit Tests
# ==============================================================================

def test_blockchain_engine_sha256_and_merkle_root():
    """Verify SHA-256 and 4-leaf Merkle root calculations."""
    h1 = BlockchainLedgerEngine.sha256_text("প্রথম আলো সংবাদ")
    h2 = BlockchainLedgerEngine.sha256_text("প্রথম আলো সংবাদ")
    assert h1 == h2
    assert len(h1) == 64

    # Merkle tree root calculation
    title_hash = BlockchainLedgerEngine.sha256_text("জরুরি সংবাদ শিরোনাম")
    content_hash = BlockchainLedgerEngine.sha256_text("বাংলাদেশ এআই অবকাঠামো ২০২৬")
    author_hash = BlockchainLedgerEngine.sha256_text("নিজস্ব প্রতিবেদক")
    ts_hash = BlockchainLedgerEngine.sha256_text("2026-09-22T12:00:00")

    merkle_root = BlockchainLedgerEngine.compute_merkle_root(title_hash, content_hash, author_hash, ts_hash)
    assert len(merkle_root) == 64
    assert merkle_root != title_hash


def test_blockchain_engine_genesis_block():
    """Verify Genesis Block #0 structure, hashes, and digital signature."""
    genesis = BlockchainLedgerEngine.create_genesis_block_data()
    assert genesis["block_number"] == 0
    assert genesis["prev_block_hash"] == GENESIS_PREV_HASH
    assert genesis["verification_status"] == "VALID"
    assert len(genesis["block_hash"]) == 64
    assert len(genesis["digital_signature"]) == 64

    # Verify signature
    is_sig_valid = BlockchainLedgerEngine.verify_digital_signature(
        genesis["block_hash"], genesis["digital_signature"]
    )
    assert is_sig_valid is True


def test_blockchain_engine_mint_and_verify_valid_block():
    """Verify minting and validating a new cryptographic article block."""
    title = "বাংলাদেশের প্রযুক্তি ক্ষেত্রে এআই বিপ্লব"
    content = "২০২৬ সালে বাংলাদেশে এআই প্রযুক্তির ব্যবহার বহুগুণ বৃদ্ধি পেয়েছে।"
    author = "প্রথম আলো প্রযুক্তি ডেস্ক"
    prev_hash = "0" * 64

    minted = BlockchainLedgerEngine.mint_article_block(
        block_number=1,
        article_id=101,
        title=title,
        content_text=content,
        author=author,
        prev_block_hash=prev_hash,
    )

    assert minted["block_number"] == 1
    assert minted["article_id"] == 101

    # Verify integrity
    is_valid, msg, details = BlockchainLedgerEngine.verify_article_block(
        block=minted,
        title=title,
        content_text=content,
        author=author,
    )
    assert is_valid is True
    assert "100% verified" in msg


def test_blockchain_engine_detects_tampering():
    """Verify tamper detection when article content or title is maliciously altered."""
    title = "মূল সংবাদ শিরোনাম"
    content = "মূল খবরের বিবরণ যা পরিবর্তন করা নিষিদ্ধ।"
    author = "সম্পাদক"
    prev_hash = "a" * 64

    minted = BlockchainLedgerEngine.mint_article_block(
        block_number=2,
        article_id=102,
        title=title,
        content_text=content,
        author=author,
        prev_block_hash=prev_hash,
    )

    # 1. Tamper title
    is_valid, msg, _ = BlockchainLedgerEngine.verify_article_block(
        block=minted,
        title="ভুয়া পরিবর্তিত সংবাদ শিরোনাম",
        content_text=content,
        author=author,
    )
    assert is_valid is False
    assert "Title content has been tampered" in msg

    # 2. Tamper body content
    is_valid, msg, _ = BlockchainLedgerEngine.verify_article_block(
        block=minted,
        title=title,
        content_text="ভুয়া পরিবর্তিত বিস্তারিত বিবরণ",
        author=author,
    )
    assert is_valid is False
    assert "Article body content has been altered" in msg

    # 3. Forged digital signature
    forged_block = dict(minted)
    forged_block["digital_signature"] = "0" * 64
    is_valid, msg, _ = BlockchainLedgerEngine.verify_article_block(
        block=forged_block,
        title=title,
        content_text=content,
        author=author,
    )
    assert is_valid is False
    assert "digital signature invalid" in msg


def test_blockchain_engine_full_chain_audit():
    """Verify chain audit scanner detects broken hashes across blocks."""
    # Create valid chain of 3 blocks
    g = BlockchainLedgerEngine.create_genesis_block_data()
    b1 = BlockchainLedgerEngine.mint_article_block(
        1, 1, "সংবাদ ১", "টেক্সট ১", "লেখক ১", g["block_hash"]
    )
    b2 = BlockchainLedgerEngine.mint_article_block(
        2, 2, "সংবাদ ২", "টেক্সট ২", "লেখক ২", b1["block_hash"]
    )

    chain = [g, b1, b2]
    audit = BlockchainLedgerEngine.audit_entire_chain(chain)
    assert audit["chain_valid"] is True
    assert audit["status"] == "HEALTHY"
    assert audit["total_blocks"] == 3

    # Introduce broken chain link in block 2
    broken_b2 = dict(b2)
    broken_b2["prev_block_hash"] = "f" * 64
    broken_chain = [g, b1, broken_b2]
    audit_broken = BlockchainLedgerEngine.audit_entire_chain(broken_chain)
    assert audit_broken["chain_valid"] is False
    assert audit_broken["status"] == "COMPROMISED"
    assert len(audit_broken["tampered_blocks"]) == 1


# ==============================================================================
# 2. Security Repository & Blacklist Management Tests
# ==============================================================================

def test_security_repository_ip_and_country_firewall():
    """Verify IP banning, expiration, and country geo-blocking in database."""
    init_db()
    with get_db_session() as session:
        sec_repo = SecurityRepository(session)

        # 1. IP Ban
        test_ip = "198.51.100.99"
        sec_repo.block_ip(ip_address=test_ip, reason="DDoS Flooding", blocked_by="SOC_TEST", duration_hours=1)
        assert sec_repo.is_ip_blocked(test_ip) is True

        # Check metrics
        metrics = sec_repo.get_security_metrics()
        assert metrics["total_blocked_ips"] >= 1

        # Unblock IP
        ip_rec = session.query(BlockedIP).filter(BlockedIP.ip_address == test_ip).first()
        assert ip_rec is not None
        assert sec_repo.unblock_ip(ip_rec.id) is True
        assert sec_repo.is_ip_blocked(test_ip) is False

        # 2. Country Geo-Firewall
        sec_repo.block_country(country_code="KP", country_name="North Korea", reason="Cyber Threat Policy")
        assert sec_repo.is_country_blocked("KP") is True
        assert sec_repo.is_country_blocked("kp") is True
        assert sec_repo.is_country_blocked("BD") is False

        # Toggle Country
        c_rec = session.query(BlockedCountry).filter(BlockedCountry.country_code == "KP").first()
        sec_repo.toggle_country(c_rec.id)
        assert sec_repo.is_country_blocked("KP") is False


def test_security_repository_threat_logging():
    """Verify threat logging and metric aggregation."""
    init_db()
    with get_db_session() as session:
        sec_repo = SecurityRepository(session)

        sec_repo.log_threat(
            threat_type="SQL_INJECTION",
            ip_address="203.0.113.5",
            request_path="/articles/search?q=' OR 1=1 --",
            request_method="GET",
            payload_sample="' OR 1=1 --",
            country_code="US",
            action_taken="BLOCKED_403",
        )

        logs = sec_repo.get_threat_logs(limit=5, threat_type="SQL_INJECTION")
        assert len(logs) >= 1
        assert logs[0].threat_type == "SQL_INJECTION"
        assert logs[0].ip_address == "203.0.113.5"


# ==============================================================================
# 3. Blockchain Ledger Repository & Article Integration Tests
# ==============================================================================

def test_blockchain_repository_minting_and_audit():
    """Verify article creation automatically mints blockchain block and validates."""
    init_db()
    with get_db_session() as session:
        art_repo = ArticleRepository(session)
        ledger_repo = BlockchainLedgerRepository(session)

        # Create article
        article = art_repo.create_editorial_article(
            title="স্মার্ট বাংলাদেশের জন্য এআই নিরাপত্তা ২০২৬",
            category="technology",
            content_text="জাতীয় সাইবার নিরাপত্তা ও ব্লকচেইন প্রযুক্তি এআই সিস্টেমে নতুন মাত্রা যোগ করেছে।",
            author="প্রথম আলো টেক টিম",
        )

        assert article.id is not None
        assert article.block_number is not None
        assert article.block_hash is not None
        assert article.is_ledger_verified is True

        # Verify through ledger repository
        is_valid, reason, details = ledger_repo.verify_article_ledger(article.id)
        assert is_valid is True
        assert details["block_number"] == article.block_number
        assert details["status"] == "VALID"

        # Full chain audit
        ledger_repo.recalculate_and_seal_chain()
        audit = ledger_repo.audit_full_chain()
        assert audit["chain_valid"] is True


# ==============================================================================
# 4. Web Application Firewall (WAF) & Endpoint Integration Tests
# ==============================================================================

@pytest.fixture
def client():
    """Create test client for Flask application."""
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    with app.test_client() as client:
        yield client


def test_waf_blocks_sqli_payloads(client):
    """Verify WAF intercepts SQL injection attempts with 403 Forbidden."""
    # Attack via Query Param
    resp = client.get("/news/?q=' UNION SELECT null, username, password FROM users --")
    assert resp.status_code == 403
    assert b"403 Forbidden" in resp.data
    assert b"SQL_INJECTION" in resp.data


def test_waf_blocks_xss_payloads(client):
    """Verify WAF intercepts Cross-Site Scripting attempts with 403 Forbidden."""
    resp = client.get("/news/?q=<script>alert('xss')</script>")
    assert resp.status_code == 403
    assert b"403 Forbidden" in resp.data
    assert b"XSS_ATTACK" in resp.data


def test_waf_blocks_path_traversal(client):
    """Verify WAF intercepts path traversal attempts."""
    resp = client.get("/news/?category=../../etc/passwd")
    assert resp.status_code == 403
    assert b"PATH_TRAVERSAL" in resp.data


def test_waf_blocks_rce_payloads(client):
    """Verify WAF intercepts command injection attempts."""
    resp = client.get("/news/?q=test; whoami")
    assert resp.status_code == 403
    assert b"RCE_COMMAND" in resp.data


def test_waf_blocks_blacklisted_ip(client):
    """Verify WAF drops requests from blacklisted IPs."""
    # Register blocked IP
    blocked_test_ip = "192.0.2.100"
    with get_db_session() as session:
        sec_repo = SecurityRepository(session)
        sec_repo.block_ip(ip_address=blocked_test_ip, reason="Automated Exploit Bot")

    resp = client.get("/news/", headers={"X-Forwarded-For": blocked_test_ip})
    assert resp.status_code == 403
    assert b"403 Forbidden" in resp.data
    assert b"Blacklisted" in resp.data


def test_public_verification_certificate_endpoint(client):
    """Verify public cryptographic verification certificate view `/news/verify/<id>`."""
    # Create article to verify
    with get_db_session() as session:
        art_repo = ArticleRepository(session)
        art = art_repo.create_editorial_article(
            title="ব্লকচেইন ভেরিফিকেশন টেস্ট আর্টিকেল",
            category="national",
            content_text="এই আর্টিকেলের ক্রিপ্টোগ্রাফিক সনদপত্র পাবলিকলি ভেরিফাই করা যাবে।",
            author="প্রথম আলো",
        )
        art_id = art.id

    # Test HTML view
    resp = client.get(f"/news/verify/{art_id}")
    assert resp.status_code == 200
    assert "ব্লকচেইন ভেরিফিকেশন টেস্ট আর্টিকেল".encode("utf-8") in resp.data
    assert "ক্রিপ্টোগ্রাফিক লেজার সনদ".encode("utf-8") in resp.data
    assert "SHA-256".encode("utf-8") in resp.data

    # Test JSON API format
    resp_json = client.get(f"/news/verify/{art_id}?format=json")
    assert resp_json.status_code == 200
    data = resp_json.get_json()
    assert data["is_valid"] is True
    assert data["article_id"] == art_id
    assert "proof" in data
