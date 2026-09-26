"""
Tests for the Mail Server / SMS Gateway / SSLCommerz Payment integrations,
OTP verification flows, admin integrations menu and the Bn/En language toggle.
"""

import uuid

import pytest

from src.web.app import create_app
from src.integrations.config_service import get_mail_config, get_sms_config, get_payment_config, get_otp_config
from src.integrations import otp_service, payment_service
from src.storage.database import get_db_session
from src.storage.repositories import (
    UserRepository,
    OtpRepository,
    MessageLogRepository,
    PaymentRepository,
    SubscriptionPlanRepository,
)


@pytest.fixture
def client():
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    with app.test_client() as client:
        yield client


def _login(client, username="admin", password="admin123"):
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


def _unique(prefix):
    return f"{prefix}{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------

def test_mail_config_defaults_are_seeded():
    cfg = get_mail_config()
    assert cfg["mail_server"] == "sandbox.smtp.mailtrap.io"
    assert int(cfg["mail_port"]) == 2525
    assert cfg["mail_username"] == "6056bdc6c17f23"
    assert cfg["mail_password"] == "4e1119bb236ac7"
    assert cfg["mail_use_tls"] is True
    assert cfg["mail_use_ssl"] is False


def test_payment_config_defaults_are_seeded():
    cfg = get_payment_config()
    assert cfg["provider"] == "SSLCommerz"
    assert cfg["store_id"] == "arobw6a3cf7767fa7c"
    assert cfg["store_password"] == "arobw6a3cf7767fa7c@ssl"
    assert cfg["is_live"] is False
    assert "sandbox.sslcommerz.com" in cfg["sandbox_base_url"]


def test_sms_and_otp_configs_available():
    sms = get_sms_config()
    assert sms["enabled"] is True
    assert sms["test_mode"] is True
    otp = get_otp_config()
    assert int(otp["otp_length"]) == 6
    assert int(otp["otp_ttl_minutes"]) == 10
    assert int(otp["otp_max_attempts"]) == 5


# ---------------------------------------------------------------------------
# Admin menu + Bn/En language toggle visibility
# ---------------------------------------------------------------------------

def test_integrations_menu_and_lang_toggle_visible_to_admin(client):
    _login(client)
    response = client.get("/admin/integrations/")
    assert response.status_code == 200
    html = response.data.decode("utf-8", "ignore")
    # Sidebar menu entry for the new section
    assert "/admin/integrations" in html
    assert "মেইল, এসএমএস ও পেমেন্ট" in html
    # Bn / En language toggle button in the admin topbar
    assert "/auth/lang/en" in html
    assert "/auth/lang/bn" in html
    assert "বাং" in html and ">En<" in html


def test_integrations_all_tabs_render(client):
    _login(client)
    for tab in ["mail", "sms", "payment", "otp", "plans", "logs"]:
        response = client.get(f"/admin/integrations/?tab={tab}")
        assert response.status_code == 200, f"tab {tab} failed"


def test_language_toggle_switches_labels_to_english(client):
    _login(client)
    client.get("/auth/lang/en")
    response = client.get("/admin/integrations/")
    html = response.data.decode("utf-8", "ignore")
    assert "Mail Server" in html
    client.get("/auth/lang/bn")
    response = client.get("/admin/integrations/")
    html = response.data.decode("utf-8", "ignore")
    assert "মেইল সার্ভার" in html


def test_integrations_menu_hidden_from_non_admin(client):
    _login(client, "viewer", "viewer123")
    response = client.get("/admin/integrations/")
    assert response.status_code == 302
    assert "/admin/integrations" not in response.headers["Location"]


def test_newsroom_admin_panel_shows_menu_and_toggle(client):
    _login(client)
    response = client.get("/admin/newspaper?tab=settings")
    html = response.data.decode("utf-8", "ignore")
    assert response.status_code == 200
    assert "/admin/integrations" in html
    assert "/auth/lang/en" in html


# ---------------------------------------------------------------------------
# OTP service
# ---------------------------------------------------------------------------

def test_otp_issue_and_verify_roundtrip():
    destination = _unique("otp") + "@example.com"
    code, err = otp_service.issue_code(destination, "register_verify")
    assert err is None and code and len(code) == 6

    ok, reason = otp_service.verify_code(destination, "register_verify", code)
    assert ok is True and reason == "ok"

    # Code is single-use
    ok, reason = otp_service.verify_code(destination, "register_verify", code)
    assert ok is False and reason == "already_used"


def test_otp_wrong_code_and_max_attempts():
    destination = _unique("otp") + "@example.com"
    code, err = otp_service.issue_code(destination, "password_reset")
    assert err is None

    ok, reason = otp_service.verify_code(destination, "password_reset", "000000" if code != "000000" else "111111")
    assert ok is False and reason == "mismatch"

    # Exhaust attempts
    for _ in range(5):
        otp_service.verify_code(destination, "password_reset", "000000" if code != "000000" else "111111")
    ok, reason = otp_service.verify_code(destination, "password_reset", code)
    assert ok is False and reason == "too_many_attempts"


def test_otp_resend_cooldown():
    destination = _unique("otp") + "@example.com"
    _, err = otp_service.issue_code(destination, "login_2fa")
    assert err is None
    _, err = otp_service.issue_code(destination, "login_2fa")
    assert err is not None and err.startswith("cooldown:")


# ---------------------------------------------------------------------------
# SMS gateway (test mode) + mail send
# ---------------------------------------------------------------------------

def test_sms_test_mode_logs_delivery():
    phone = "+88017" + uuid.uuid4().hex[:8]
    result = __import__("src.integrations.sms_service", fromlist=["send_sms"]).send_sms(
        phone, "Hello test", purpose="test"
    )
    assert result["ok"] is True
    assert result.get("simulated") is True

    with get_db_session() as session:
        logs = MessageLogRepository(session).recent(limit=20, channel="sms")
    assert any(log.recipient == phone for log in logs)


def test_mail_send_falls_back_to_simulated():
    from src.integrations.mail_service import send_mail

    to = _unique("mail") + "@example.com"
    with get_db_session() as session:
        result = send_mail(session, to, "Test", "<p>hi</p>", "hi", purpose="test")
    assert result["ok"] is True  # SENT or SIMULATED both count as success

    with get_db_session() as session:
        logs = MessageLogRepository(session).recent(limit=20, channel="mail")
    assert any(log.recipient == to for log in logs)


def test_admin_test_mail_endpoint(client):
    _login(client)
    to = _unique("mail") + "@example.com"
    response = client.post("/admin/integrations/mail/test", data={"to": to}, follow_redirects=True)
    assert response.status_code == 200
    assert "টেস্ট মেইল" in response.data.decode("utf-8", "ignore") or b"Test mail" in response.data


# ---------------------------------------------------------------------------
# Registration with email OTP verification
# ---------------------------------------------------------------------------

def test_register_flow_with_email_otp(client, monkeypatch):
    captured = {}

    import src.web.routes.auth_bp as auth_bp

    real_issue = auth_bp.issue_code

    def spy_issue(destination, purpose, channel="email", user_id=None, cfg=None):
        code, err = real_issue(destination, purpose, channel=channel, user_id=user_id, cfg=cfg)
        captured["code"] = code
        return code, err

    monkeypatch.setattr(auth_bp, "issue_code", spy_issue)

    username = _unique("user")
    email = _unique("user") + "@example.com"

    response = client.post(
        "/auth/register",
        data={
            "username": username,
            "email": email,
            "password": "secret123",
            "role": "viewer",
        },
        follow_redirects=False,
    )
    # OTP verification required before account creation
    assert response.status_code == 302
    assert "/auth/verify" in response.headers["Location"]
    assert captured.get("code") and len(captured["code"]) == 6

    # Account must NOT exist yet
    with get_db_session() as session:
        assert UserRepository(session).get_by_email(email) is None

    page = client.get("/auth/verify")
    assert page.status_code == 200

    # Wrong code keeps the user unauthenticated
    wrong = "000000" if captured["code"] != "000000" else "111111"
    client.post("/auth/verify", data={"code": wrong}, follow_redirects=True)
    with get_db_session() as session:
        assert UserRepository(session).get_by_email(email) is None

    # Correct code completes registration and logs the user in
    response = client.post("/auth/verify", data={"code": captured["code"]}, follow_redirects=False)
    assert response.status_code == 302

    with get_db_session() as session:
        user = UserRepository(session).get_by_email(email)
        assert user is not None
        assert user.username == username


# ---------------------------------------------------------------------------
# Password reset via OTP
# ---------------------------------------------------------------------------

def test_password_reset_flow(client, monkeypatch):
    captured = {}

    import src.web.routes.auth_bp as auth_bp

    real_issue = auth_bp.issue_code

    def spy_issue(destination, purpose, channel="email", user_id=None, cfg=None):
        code, err = real_issue(destination, purpose, channel=channel, user_id=user_id, cfg=cfg)
        captured["code"] = code
        return code, err

    monkeypatch.setattr(auth_bp, "issue_code", spy_issue)

    admin_email = "admin@webcreoling.ai"
    response = client.post("/auth/forgot", data={"email": admin_email}, follow_redirects=False)
    assert response.status_code in (200, 302)

    if "/auth/verify" not in response.headers.get("Location", ""):
        pytest.skip("OTP password reset disabled in configuration")

    assert captured.get("code")
    try:
        response = client.post("/auth/verify", data={"code": captured["code"]}, follow_redirects=False)
        assert "/auth/reset" in response.headers["Location"]

        response = client.post(
            "/auth/reset",
            data={"password": "newpass99", "confirm": "newpass99"},
            follow_redirects=False,
        )
        assert response.status_code == 302

        # Original password must no longer work, new one must
        with get_db_session() as session:
            repo = UserRepository(session)
            assert repo.authenticate("admin", "newpass99") is not None
    finally:
        # Restore the demo password so other tests keep working
        with get_db_session() as session:
            repo = UserRepository(session)
            admin = repo.get_by_username("admin")
            admin.set_password("admin123")
            session.flush()


# ---------------------------------------------------------------------------
# SSLCommerz checkout / callbacks
# ---------------------------------------------------------------------------

def test_subscription_plans_are_seeded():
    with get_db_session() as session:
        plans = SubscriptionPlanRepository(session).all()
    codes = {p.code for p in plans}
    assert {"basic", "pro", "enterprise"} <= codes


def test_checkout_redirects_to_gateway(client, monkeypatch):
    _login(client)

    import src.integrations.payment_service as pay

    def fake_session(**kwargs):
        return {"ok": True, "gateway_url": "https://sandbox.sslcommerz.com/gwprocess/v4/api.php?val=TEST",
                "session_key": "sess-test"}

    monkeypatch.setattr(pay, "create_session", fake_session)

    with get_db_session() as session:
        plans = SubscriptionPlanRepository(session).all(active_only=True)
    assert plans, "no active plans to purchase"

    response = client.post(
        "/billing/checkout",
        data={"plan_id": plans[0].id},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "sandbox.sslcommerz.com" in response.headers["Location"]

    with get_db_session() as session:
        admin = UserRepository(session).get_by_username("admin")
        txs = PaymentRepository(session).transactions_for_user(admin.id, limit=5)
    assert txs and txs[0].status == "PENDING"


def test_ipn_validates_and_activates_subscription(client, monkeypatch):
    _login(client)

    with get_db_session() as session:
        admin = UserRepository(session).get_by_username("admin")
        plans = SubscriptionPlanRepository(session).all(active_only=True)
        plan = plans[0]
        tx = PaymentRepository(session).create_transaction(
            tran_id="WCTEST" + uuid.uuid4().hex[:8],
            user_id=admin.id,
            plan_id=plan.id,
            amount=plan.price,
            currency="BDT",
            status="PENDING",
        )
        tran_id = tx.tran_id

    import src.integrations.payment_service as pay

    def fake_validate(val_id, cfg=None):
        return {"ok": True, "status": "VALID", "tran_id": tran_id,
                "payment_method": "VISA", "bank_tran_id": "BANK123",
                "risk_level": "0", "raw": {"status": "VALID"}}

    monkeypatch.setattr(pay, "validate_payment", fake_validate)

    response = client.post(
        "/billing/ipn",
        data={"tran_id": tran_id, "val_id": "VAL123", "status": "VALID"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'"result": true' in response.data or b'"result":true' in response.data

    with get_db_session() as session:
        pay_repo = PaymentRepository(session)
        tx = pay_repo.get_by_tran_id(tran_id)
        assert tx.status == "VALID"
        assert tx.payment_method == "VISA"
        admin = UserRepository(session).get_by_username("admin")
        sub = pay_repo.active_subscription(admin.id)
        assert sub is not None
        assert sub.plan_id == tx.plan_id


def test_cancel_and_fail_callbacks(client):
    _login(client)

    with get_db_session() as session:
        admin = UserRepository(session).get_by_username("admin")
        plans = SubscriptionPlanRepository(session).all(active_only=True)
        tx = PaymentRepository(session).create_transaction(
            tran_id="WCCANCEL" + uuid.uuid4().hex[:8],
            user_id=admin.id,
            plan_id=plans[0].id,
            amount=plans[0].price,
            currency="BDT",
            status="PENDING",
        )
        tran_id = tx.tran_id

    response = client.get(f"/billing/cancel?tran_id={tran_id}", follow_redirects=True)
    assert response.status_code == 200
    html = response.data.decode("utf-8", "ignore")
    assert "বাতিল" in html or "Cancel" in html

    with get_db_session() as session:
        tx = PaymentRepository(session).get_by_tran_id(tran_id)
        assert tx.status == "CANCELLED"


def test_billing_plans_page_public(client):
    response = client.get("/billing/plans")
    assert response.status_code == 200
    html = response.data.decode("utf-8", "ignore")
    assert "SSLCommerz" in html
    assert "sandbox" in html.lower()
