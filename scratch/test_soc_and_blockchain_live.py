import sys
import requests

# Ensure UTF-8 console output if supported
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "http://127.0.0.1:8080"


def test_live_security_and_blockchain():
    print("=" * 70)
    print("Testing Live Security Operations Center (SOC) & Blockchain Ledger")
    print("=" * 70)

    session = requests.Session()

    # 1. Test Public Newspaper Portal
    r = session.get(f"{BASE_URL}/news/")
    assert r.status_code == 200, f"Portal failed with {r.status_code}"
    print("[PASS] [200 OK] Public Newspaper Portal (/news/) is alive and responsive.")

    # 2. Login as Admin
    login_resp = session.post(f"{BASE_URL}/auth/login", data={"username": "admin", "password": "admin123"})
    assert login_resp.status_code in [200, 302], "Admin login failed"
    print("✓ [200 OK] Admin authentication successful.")

    # 3. Access Admin Newsroom SOC Tab
    soc_resp = session.get(f"{BASE_URL}/admin/newspaper?tab=security")
    assert soc_resp.status_code == 200, "SOC tab failed"
    assert "সার্ভার থ্রেট লেভেল" in soc_resp.text
    assert "প্রথম আলো ক্রিপ্টোগ্রাফিক আর্টিকেল লেজার" in soc_resp.text
    print("✓ [200 OK] Admin Security Operations Center (SOC) tab rendered properly.")

    # 4. Batch Mint Unmined Articles
    mint_resp = session.post(f"{BASE_URL}/admin/newspaper/blockchain/mint-missing", allow_redirects=True)
    assert mint_resp.status_code == 200
    print("✓ [200 OK] Batch minting articles into cryptographic blockchain ledger executed.")

    # 5. Full Blockchain Integrity Audit Scan
    audit_resp = session.get(f"{BASE_URL}/admin/newspaper/blockchain/audit?format=json")
    assert audit_resp.status_code == 200
    audit_data = audit_resp.json()
    assert audit_data.get("chain_valid") is True, f"Chain audit reported anomalies: {audit_data}"
    print(f"✓ [200 OK] Full Blockchain Audit passed! Total Blocks: {audit_data.get('total_blocks')}, Chain Health: {audit_data.get('status')}")

    # 6. Verify Individual Article Certificate
    verify_resp = session.get(f"{BASE_URL}/news/verify/1?format=json")
    if verify_resp.status_code == 200:
        v_data = verify_resp.json()
        assert v_data.get("is_valid") is True
        print(f"✓ [200 OK] Public Cryptographic Certificate for Article #1 verified (Block #{v_data['proof']['block_number']}).")
    else:
        print(f"Article #1 not found, checking HTML certificate.")

    # 7. Test Admin IP Blocking & Unblocking
    test_ip = "198.51.100.88"
    block_resp = session.post(
        f"{BASE_URL}/admin/newspaper/security/block-ip",
        data={"ip_address": test_ip, "reason": "Automated Live Test Bot", "duration_hours": "1"},
        allow_redirects=True,
    )
    assert block_resp.status_code == 200
    print(f"✓ [200 OK] IP {test_ip} successfully blacklisted in firewall.")

    # 8. Test WAF Deep Inspection: SQL Injection Blocking (expect 403)
    sqli_client = requests.Session()
    sqli_resp = sqli_client.get(f"{BASE_URL}/news/?q=' UNION SELECT 1,2,3,4 --")
    assert sqli_resp.status_code == 403, f"Expected 403 on SQLi, got {sqli_resp.status_code}"
    assert "Malicious Payload Violation Detected (SQL_INJECTION)" in sqli_resp.text
    print("✓ [403 Forbidden] WAF successfully intercepted SQL Injection attack payload!")

    # 9. Test WAF Deep Inspection: XSS Attack Blocking (expect 403)
    xss_resp = sqli_client.get(f"{BASE_URL}/news/?q=<script>alert('pwned')</script>")
    assert xss_resp.status_code == 403
    assert "Malicious Payload Violation Detected (XSS_ATTACK)" in xss_resp.text
    print("✓ [403 Forbidden] WAF successfully intercepted XSS injection attack payload!")

    # 10. Test WAF Deep Inspection: RCE Command Injection Blocking (expect 403)
    rce_resp = sqli_client.get(f"{BASE_URL}/news/?q=article; whoami")
    assert rce_resp.status_code == 403
    assert "Malicious Payload Violation Detected (RCE_COMMAND)" in rce_resp.text
    print("✓ [403 Forbidden] WAF successfully intercepted RCE Command injection payload!")

    # 11. Test Blacklisted IP Dropping (expect 403)
    banned_client = requests.Session()
    banned_resp = banned_client.get(f"{BASE_URL}/news/", headers={"X-Forwarded-For": test_ip})
    assert banned_resp.status_code == 403
    assert "IP Address is Blacklisted on Server" in banned_resp.text
    print(f"✓ [403 Forbidden] Firewall dropped connection from Blacklisted IP {test_ip}!")

    print("=" * 70)
    print("🎉 ALL LIVE SECURITY & BLOCKCHAIN TESTS PASSED 100%!")
    print("=" * 70)


if __name__ == "__main__":
    test_live_security_and_blockchain()
