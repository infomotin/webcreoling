"""Regression tests for the production security hardening pass.

Covers: persisted secret key, session cookie flags, response security headers,
CSRF origin guard, login rate limiting, open-redirect guard, OTP disclosure,
password handling in registration, IPN status trust, upload filename traversal,
database URL redaction, the ``js_escape`` Jinja filter, and composite indexes.
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

import src.web.routes.auth_bp as auth_bp
from config.settings import settings
from src.storage.database import _redact_url
from src.storage.models import Base, PaymentTransaction
from src.storage.repositories import PaymentRepository
from src.web import ratelimit
from src.web.app import create_app, _load_or_create_secret_key, PROJECT_ROOT


@pytest.fixture
def app():
    ratelimit.clear_all()
    application = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    yield application
    ratelimit.clear_all()


@pytest.fixture
def client(app):
    with app.test_client() as test_client:
        yield test_client


# ---------------------------------------------------------------- secret key

def test_secret_key_is_persisted_and_reused():
    first = _load_or_create_secret_key()
    second = _load_or_create_secret_key()
    assert first == second
    assert len(first) >= 64
    key_file = PROJECT_ROOT / "data" / "instance" / "secret_key"
    assert key_file.exists()
    assert key_file.read_text(encoding="utf-8").strip() == first


# ------------------------------------------------------- session / headers

def test_session_cookie_flags(client):
    response = client.get("/auth/login")
    cookie = response.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_security_headers_present(client):
    response = client.get("/auth/login")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


# -------------------------------------------------------------- csrf guard

def test_csrf_rejects_cross_site_fetch(client):
    response = client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin123"},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert response.status_code == 403


def test_csrf_rejects_origin_mismatch(client):
    response = client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin123"},
        headers={"Origin": "http://evil.example"},
    )
    assert response.status_code == 403


def test_csrf_allows_same_origin_and_headerless_requests(client):
    same_origin = client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin123"},
        headers={"Origin": "http://localhost"},
    )
    assert same_origin.status_code != 403
    headerless = client.post(
        "/auth/login", data={"username": "admin", "password": "admin123"}
    )
    assert headerless.status_code != 403


# ------------------------------------------------------------ rate limiting

def test_login_rate_limit_blocks_brute_force(app):
    with app.test_client() as client:
        for _ in range(10):
            blocked = client.post(
                "/auth/login",
                data={"username": "brute_target", "password": "wrong"},
            )
            assert blocked.status_code != 429
        response = client.post(
            "/auth/login",
            data={"username": "brute_target", "password": "wrong"},
        )
        assert response.status_code == 429


def test_ratelimit_window_unit():
    ratelimit.clear_all()
    try:
        for _ in range(3):
            assert ratelimit.allow("auth.login.failures", "unit-key") is True
        assert ratelimit.blocked("auth.login.failures", "unit-key") is False
        for _ in range(7):
            ratelimit.allow("auth.login.failures", "unit-key")
        assert ratelimit.blocked("auth.login.failures", "unit-key") is True
        ratelimit.reset("auth.login.failures", "unit-key")
        assert ratelimit.blocked("auth.login.failures", "unit-key") is False
    finally:
        ratelimit.clear_all()


# ------------------------------------------------------- open redirect guard

def test_safe_next_only_allows_relative_targets(app):
    with app.app_context():
        assert auth_bp._safe_next("/dashboard") == "/dashboard"
        assert auth_bp._safe_next("/articles?page=2") == "/articles?page=2"
        assert auth_bp._safe_next("https://evil.example/phish") != "https://evil.example/phish"
        assert auth_bp._safe_next("//evil.example/phish") != "//evil.example/phish"
        assert auth_bp._safe_next("javascript:alert(1)") != "javascript:alert(1)"
        assert auth_bp._safe_next("") != "https://evil.example"


def test_login_ignores_external_next(client):
    response = client.post(
        "/auth/login",
        data={"username": "admin", "password": "admin123"},
        query_string={"next": "https://evil.example/steal"},
        follow_redirects=False,
    )
    if response.status_code == 302:
        assert "evil.example" not in response.headers["Location"]


# ----------------------------------------------------- registration / OTP

def test_registration_never_stores_plaintext_password(app, monkeypatch):
    monkeypatch.setattr(
        auth_bp, "deliver_otp", lambda *args, **kwargs: {"ok": True, "simulated": True}
    )
    password = "s3cret-pass"
    with app.test_client() as client:
        response = client.post(
            "/auth/register",
            data={
                "username": "hardening_probe",
                "email": "hardening.probe@example.com",
                "password": password,
                "role": "viewer",
            },
            follow_redirects=False,
        )
        assert response.status_code in (200, 302)
        with client.session_transaction() as sess:
            pending = sess.get("pending_registration")
        if pending is not None:
            assert "password" not in pending
            assert pending.get("password_hash")
            assert password not in pending["password_hash"]
        else:
            # OTP registration disabled in this environment: the account must
            # still only carry a hash.
            from src.storage.database import get_db_session
            from src.storage.repositories import UserRepository

            with get_db_session() as session:
                user = UserRepository(session).get_by_username("hardening_probe")
                if user is not None:
                    assert user.password_hash != password
                    assert user.check_password(password) is True


def test_otp_code_not_flashed_when_not_debug(app, monkeypatch):
    sentinel = "998877"
    app.config["DEBUG"] = False
    monkeypatch.setattr(
        auth_bp, "issue_code", lambda *args, **kwargs: (sentinel, None)
    )
    monkeypatch.setattr(
        auth_bp, "deliver_otp", lambda *args, **kwargs: {"ok": False}
    )
    with app.test_client() as client:
        response = client.post(
            "/auth/register",
            data={
                "username": "otp_leak_probe",
                "email": "otp.leak.probe@example.com",
                "password": "another-secret",
            },
            follow_redirects=True,
        )
        html = response.get_data(as_text=True)
        assert sentinel not in html, "OTP code leaked to the client"


# --------------------------------------------------------------------- IPN

def test_ipn_client_status_cannot_mark_valid(app, monkeypatch):
    import src.web.routes.billing_bp as billing_bp

    class _FakeGateway:
        def ipn_validate(self, **kwargs):
            return {"ok": False, "status": "NO_VAL_ID"}

        def validate_payment(self, val_id):
            return {"ok": False, "status": "INVALID"}

    monkeypatch.setattr(billing_bp, "payment_service", _FakeGateway())

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    tx = PaymentTransaction(
        tran_id="harden-ipn-1", amount=100.0, status="PENDING"
    )
    session.add(tx)
    session.commit()
    session.close()

    real_get_db_session = billing_bp.get_db_session

    def _mem_session():
        class _Ctx:
            def __enter__(self_inner):
                return session

            def __exit__(self_inner, *exc):
                return False

        return _Ctx()

    monkeypatch.setattr(billing_bp, "get_db_session", _mem_session)
    try:
        with app.test_client() as client:
            response = client.post(
                "/billing/ipn",
                data={
                    "tran_id": "harden-ipn-1",
                    "status": "VALID",
                    "val_id": "",
                },
            )
            assert response.status_code == 200
            session.expire_all()
            stored = session.query(PaymentTransaction).filter_by(
                tran_id="harden-ipn-1"
            ).one()
            assert stored.status != "VALID"
    finally:
        monkeypatch.setattr(billing_bp, "get_db_session", real_get_db_session)
        session.close()


# --------------------------------------------------------------- uploads

def test_upload_filename_traversal_is_contained(tmp_path):
    from src.datacenter.storage_manager import CloudStorageManager

    payload_dir = tmp_path / "media"
    payload_dir.mkdir()
    original_images_dir = settings.IMAGES_DIR
    settings.IMAGES_DIR = payload_dir
    try:
        result = CloudStorageManager.upload_media_file(
            b"hello", "../../escaped.txt", mirror=False
        )
        name = result.get("filename") or ""
        assert ".." not in name
        assert "/" not in name and "\\" not in name
        written = list(payload_dir.iterdir())
        assert len(written) == 1
        assert written[0].parent == payload_dir
        assert not (payload_dir.parent / "escaped.txt").exists()
    finally:
        settings.IMAGES_DIR = original_images_dir
        for leftover in payload_dir.iterdir():
            leftover.unlink()


# ------------------------------------------------------- url redaction etc.

def test_database_url_redaction():
    redacted = _redact_url("mysql+pymysql://root:toor@localhost:3306/ai_news")
    assert "toor" not in redacted
    assert "***" in redacted
    assert redacted.startswith("mysql+pymysql://root:***@localhost:3306/")


def test_js_escape_filter_blocks_attribute_breakout(app):
    js_escape = app.jinja_env.filters["js_escape"]
    hostile = '"); alert("xss"); //'
    escaped = js_escape(hostile)
    assert '"' not in escaped.replace('\\"', "")
    assert "'" not in escaped.replace("\\'", "")
    assert "<" not in escaped.replace("\\u003c", "")
    rendered = app.jinja_env.from_string(
        "<button onclick=\"f('{{ value | js_escape }}')\"></button>"
    ).render(value=hostile)
    # The raw payload must never reach the attribute verbatim; quotes come out
    # backslash-escaped (and then HTML-entity encoded by Jinja autoescaping).
    assert '"); alert(' not in rendered
    assert "\&#34;" in rendered


def test_composite_indexes_created():
    engine = create_engine(settings.DATABASE_URL)
    names = {index["name"] for index in inspect(engine).get_indexes("articles")}
    for expected in (
        "ix_articles_status_published",
        "ix_articles_category_status_pubdate",
        "ix_articles_status_scheduled",
        "ix_articles_highlight_order",
    ):
        assert expected in names, f"missing index: {expected}"


def test_ledger_secret_prefers_environment(monkeypatch):
    from src.common import blockchain

    monkeypatch.setenv("LEDGER_SECRET", "env-secret-value")
    resolver = getattr(blockchain, "_resolve_ledger_secret", None)
    if resolver is None:
        pytest.skip("resolver not exposed")
    assert resolver() == "env-secret-value"
