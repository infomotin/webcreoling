"""
Tests for the Agentic AI Operation Controller:
  * role-routed approval intake (Ad Manager / Editorial Lead / Onboarding Officer)
  * junior reviewers FLAG (never autonomous rejection); senior roles decide
  * timeout escalation to the next senior role + optional auto-approve by silence
  * audit trails for escalations & auto-decisions
  * public submission routes, agent inbox authz, reporter dashboard
  * LLM abstraction graceful degradation (self-hosted endpoint only)
"""

import uuid
from datetime import datetime, timedelta

import pytest

from src.web.app import create_app
from src.automation.agent_controller import AgenticController, REQUEST_ROUTES
from src.storage.database import get_db_session
from src.storage.models import (
    AdInquiry,
    AgentAuditLog,
    ApprovalRequest,
    NewsSubmission,
    RawNewsItem,
    ReporterApplication,
)
from src.storage.repositories import UserRepository


@pytest.fixture
def client():
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    with app.test_client() as client:
        yield client


def _login(client, username="admin", password="admin123"):
    return client.post("/auth/login", data={"username": username, "password": password},
                       follow_redirects=False)


def _unique(prefix):
    return f"{prefix}{uuid.uuid4().hex[:10]}"


@pytest.fixture(autouse=True)
def purge_agent_tables():
    """Fresh approval/agent tables per test (test data only — these tables are new)."""
    def _purge():
        with get_db_session() as session:
            for model in (ApprovalRequest, AgentAuditLog, AdInquiry, NewsSubmission,
                          ReporterApplication):
                session.query(model).delete()
            session.commit()
    _purge()
    yield
    _purge()


@pytest.fixture(autouse=True)
def offline_services(monkeypatch):
    """No real SMTP / Ollama calls in tests (sandbox rate-limits + latency)."""
    monkeypatch.setattr(
        "src.integrations.mail_service.send_mail",
        lambda *args, **kw: {"ok": True, "status": "SIMULATED", "simulated": True},
    )
    monkeypatch.setattr(
        "src.integrations.llm_service.get_llm_config",
        lambda: {"enabled": False, "provider": "none",
                 "base_url": "http://127.0.0.1:59999", "model": "test",
                 "embed_model": "test", "timeout": 1},
    )
    yield


class _User:
    """Minimal user stand-in for controller-level tests."""
    def __init__(self, username, role, uid=1):
        self.username = username
        self.role = role
        self.id = uid


# ---------------------------------------------------------------------------
# Intake & role routing
# ---------------------------------------------------------------------------

def test_ad_inquiry_routed_to_ad_manager_with_draft():
    res = AgenticController.submit_ad_inquiry(
        name="Rahim Uddin", email="client@adtest.test",
        message="Interested in banner ads", company="ACME Ltd",
        package_interest="homepage_banner", budget_note="BDT 20000",
    )
    assert res["success"] is True
    assert res["assigned_role"] == REQUEST_ROUTES["ad_inquiry"] == "ad_manager"
    with get_db_session() as session:
        inquiry = session.query(AdInquiry).filter(AdInquiry.id == res["inquiry_id"]).first()
        assert inquiry.status == "pending_approval"
        assert inquiry.draft_subject and inquiry.draft_body
        assert inquiry.draft_generated_by in ("template", "llm")
        req = session.query(ApprovalRequest).filter(
            ApprovalRequest.id == res["approval_request_id"]).first()
        assert req.required_role == "ad_manager"
        assert req.status in ("pending", "flagged")
        assert req.due_at is not None  # escalation deadline set
        # Audit: INTAKE recorded
        audits = session.query(AgentAuditLog).filter(
            AgentAuditLog.event_type == "INTAKE",
            AgentAuditLog.approval_request_id == req.id).all()
        assert audits


def test_news_submission_routed_to_editorial_lead_with_factcheck():
    res = AgenticController.submit_news_submission(
        title="নির্বাচনের তারিখ ঘোষণা আজ",
        content="আজ নির্বাচন কমিশন সাধারণ নির্বাচনের তারিখ ঘোষণা করেছে। "
                "তারিখ সম্পর্কে পুরো খবর এখানে বিস্তারিত লেখা হয়েছে যাতে পাঠকরা জানতে পারেন।",
        submitter_email="tips@newstest.test",
        author_name="Staff Reporter",
        kind="external",
    )
    assert res["success"] is True
    assert res["assigned_role"] == "editorial_lead"
    with get_db_session() as session:
        sub = session.query(NewsSubmission).filter(
            NewsSubmission.id == res["submission_id"]).first()
        assert sub.status in ("pending_approval", "flagged")
        assert sub.fact_check and "combined_confidence" in sub.fact_check
        assert sub.fact_check["strategy"] in ("cross_source_only", "dual", "error")
        req = session.query(ApprovalRequest).filter(
            ApprovalRequest.id == res["approval_request_id"]).first()
        assert req.required_role == "editorial_lead"
        assert req.request_type == "news_submission"


def test_reporter_application_routed_to_onboarding_officer():
    res = AgenticController.submit_reporter_application(
        full_name="Fake Reporter",
        email=_unique("reporter") + "@apply.test",
        credentials={"experience_years": "5", "outlet": "Daily X", "beat": "politics"},
        portfolio_links=["https://portfolio.test/story1"],
        sample_text=("আমি একজন অভিজ্ঞ সাংবাদিক। " * 30) +
                    "অর্থনীতি ও রাজনীতি নিয়ে দীর্ঘ প্রতিবেদন লিখেছি। " * 5,
    )
    assert res["success"] is True
    assert res["assigned_role"] == "onboarding_officer"
    assert res["verification"]["quality_score"] >= 60
    with get_db_session() as session:
        app = session.query(ReporterApplication).filter(
            ReporterApplication.id == res["application_id"]).first()
        assert app.status in ("verified", "flagged")
        req = session.query(ApprovalRequest).filter(
            ApprovalRequest.id == res["approval_request_id"]).first()
        assert req.required_role == "onboarding_officer"


def test_low_quality_reporter_application_is_flagged_with_concerns():
    res = AgenticController.submit_reporter_application(
        full_name="Weak Candidate",
        email=_unique("weak") + "@apply.test",
        credentials={},
        portfolio_links=[],
        sample_text="short",
    )
    assert res["success"] is True
    assert res["verification"]["concerns"]
    with get_db_session() as session:
        req = session.query(ApprovalRequest).filter(
            ApprovalRequest.id == res["approval_request_id"]).first()
        assert req.status == "flagged"
        assert req.priority == "high"
        assert req.flags  # concerns surfaced for human review


# ---------------------------------------------------------------------------
# Junior flags, senior decides (hierarchical review)
# ---------------------------------------------------------------------------

def test_junior_editor_cannot_finalize_approve_only_flag():
    res = AgenticController.submit_ad_inquiry(
        name="Junior Test", email=_unique("jun") + "@adtest.test", message="hi")
    req_id = res["approval_request_id"]

    out = AgenticController.decide(req_id, "approve", _User("editor1", "editor"), note="looks fine")
    assert out["success"] is True
    assert out["status"] == "flagged"  # NOT approved
    with get_db_session() as session:
        req = session.query(ApprovalRequest).filter(ApprovalRequest.id == req_id).first()
        assert req.is_open()  # remains pending for the senior role
        assert req.required_role == "ad_manager"
        sub = session.query(AdInquiry).filter(AdInquiry.id == req.subject_id).first()
        assert sub.status == "flagged"  # never auto-rejected by junior


def test_junior_rejection_keeps_request_pending_for_senior():
    res = AgenticController.submit_news_submission(
        title="সন্দেহজনক খবর", content="পুরো খসড়া পাঠ " * 20,
        submitter_email=_unique("sus") + "@news.test")
    req_id = res["approval_request_id"]

    out = AgenticController.decide(req_id, "reject", _User("editor1", "editor"),
                                   note="claims look doubtful")
    assert out["success"] is True
    assert out["status"] == "flagged"  # stays open until final disposition
    with get_db_session() as session:
        req = session.query(ApprovalRequest).filter(ApprovalRequest.id == req_id).first()
        assert req.is_open()
        sub = session.query(NewsSubmission).filter(NewsSubmission.id == req.subject_id).first()
        assert sub.status != "rejected"  # NOT rejected autonomously


def test_senior_ad_manager_final_approval_sends_ad_reply():
    res = AgenticController.submit_ad_inquiry(
        name="Final Test", email=_unique("final") + "@adtest.test",
        message="want banner", package_interest="homepage_banner")
    out = AgenticController.decide(res["approval_request_id"], "approve",
                                   _User("ads1", "ad_manager"), note="approved rates")
    assert out["success"] is True
    assert out["status"] == "approved"
    with get_db_session() as session:
        req = session.query(ApprovalRequest).filter(
            ApprovalRequest.id == res["approval_request_id"]).first()
        assert req.decided_by == "ads1"
        assert req.decided_at is not None
        inquiry = session.query(AdInquiry).filter(AdInquiry.id == res["inquiry_id"]).first()
        # Approved reply was dispatched to the advertiser (SENT or SIMULATED in sandbox)
        assert inquiry.status == "sent"
        assert inquiry.sent_at is not None


def test_editorial_lead_approval_publishes_submission():
    res = AgenticController.submit_news_submission(
        title="অনুমোদিত প্রতিবেদন " + _unique("x"),
        content="এই প্রতিবেদনে বলা হয়েছে দেশের অর্থনীতি সম্পর্কে বিস্তারিত তথ্য " * 10,
        submitter_email=_unique("pub") + "@news.test",
        author_name="Guest Writer")
    out = AgenticController.decide(res["approval_request_id"], "approve",
                                   _User("lead1", "editorial_lead"))
    assert out["success"] is True
    assert out["status"] == "approved"
    assert out["effects"].get("article_id")
    with get_db_session() as session:
        sub = session.query(NewsSubmission).filter(
            NewsSubmission.id == res["submission_id"]).first()
        assert sub.status == "published"
        assert sub.article_id == out["effects"]["article_id"]
        from src.storage.models import Article
        art = session.query(Article).filter(Article.id == sub.article_id).first()
        assert art is not None
        ents = art.extracted_entities or {}
        sub_meta = ents.get("submission") or {}
        assert sub_meta.get("publisher", "").startswith("The Daily AI Alo")
        assert sub_meta.get("approval_request_id") == res["approval_request_id"]
        assert sub_meta.get("submitter") == "Guest Writer"
        # Publisher + submitter credit present in the body (appended post-creation)
        assert "প্রকাশক: The Daily AI Alo" in (art.content_text or "")
        assert "জমাদাতা" in (art.content_text or "")


def test_onboarding_officer_approval_creates_reporter_user():
    email = _unique("hire") + "@apply.test"
    res = AgenticController.submit_reporter_application(
        full_name="Hired Reporter", email=email,
        credentials={"experience_years": "4", "outlet": "Daily Y"},
        portfolio_links=["https://p.test/one"],
        sample_text=("সাংবাদিকতায় আমার দীর্ঘ অভিজ্ঞতা রয়েছে। " * 25))
    out = AgenticController.decide(res["approval_request_id"], "approve",
                                   _User("hr1", "onboarding_officer"))
    assert out["success"] is True
    assert out["effects"].get("username")
    with get_db_session() as session:
        app = session.query(ReporterApplication).filter(
            ReporterApplication.id == res["application_id"]).first()
        assert app.status == "approved"
        assert app.user_id
        user = session.query(__import__("src.storage.models", fromlist=["User"]).User).filter(
            __import__("src.storage.models", fromlist=["User"]).User.id == app.user_id).first()
        assert user is not None
        assert user.role == "reporter"
        assert user.email == email


def test_admin_can_decide_any_request_and_wrong_role_cannot():
    res = AgenticController.submit_ad_inquiry(
        name="Admin Case", email=_unique("adm") + "@adtest.test")
    # editorial_lead is not in the ad chain (ad_manager -> admin): no authority
    out = AgenticController.decide(res["approval_request_id"], "approve",
                                   _User("lead", "editorial_lead"))
    assert out["success"] is False
    assert "cannot act" in out["error"].lower()
    with get_db_session() as session:
        req = session.query(ApprovalRequest).filter(
            ApprovalRequest.id == res["approval_request_id"]).first()
        assert req.is_open()  # untouched by the unrelated role
        assert req.status == "pending"

    out2 = AgenticController.decide(res["approval_request_id"], "approve",
                                    _User("root", "admin"))
    assert out2["success"] is True
    assert out2["status"] == "approved"

    # Closed requests cannot be decided again
    out3 = AgenticController.decide(res["approval_request_id"], "reject",
                                    _User("root", "admin"))
    assert out3["success"] is False


def test_viewer_role_cannot_act_on_requests():
    res = AgenticController.submit_ad_inquiry(
        name="Viewer Case", email=_unique("view") + "@adtest.test")
    out = AgenticController.decide(res["approval_request_id"], "approve",
                                   _User("viewer1", "viewer"))
    assert out["success"] is False
    assert "permission" in out["error"].lower() or "cannot" in out["error"].lower()


# ---------------------------------------------------------------------------
# Timeout escalation & auto-approval
# ---------------------------------------------------------------------------

def test_sweep_escalates_overdue_request_to_next_senior_role():
    res = AgenticController.submit_ad_inquiry(
        name="Overdue", email=_unique("od") + "@adtest.test")
    with get_db_session() as session:
        req = session.query(ApprovalRequest).filter(
            ApprovalRequest.id == res["approval_request_id"]).first()
        req.due_at = datetime.utcnow() - timedelta(hours=1)  # overdue
        session.commit()

    summary = AgenticController.sweep_timeouts()
    assert summary["escalated"] == 1

    with get_db_session() as session:
        req = session.query(ApprovalRequest).filter(
            ApprovalRequest.id == res["approval_request_id"]).first()
        assert req.status == ApprovalRequest.STATUS_ESCALATED
        assert req.assigned_role == "admin"          # next senior role
        assert req.escalation_level == 1
        assert req.escalated_at is not None
        assert req.due_at is not None                # new deadline for the admin
        # Audit trail for the escalation
        audits = session.query(AgentAuditLog).filter(
            AgentAuditLog.event_type == "ESCALATED",
            AgentAuditLog.approval_request_id == req.id).all()
        assert audits
        assert req.audit_trail and req.audit_trail[-1]["event"] in ("ESCALATED", "INTAKE", "NOTIFY")


def test_sweep_auto_approves_by_silence_when_configured():
    original = AgenticController.get_policy()
    try:
        AgenticController.save_policy({
            "auto_approve_enabled": True,
            "auto_approve_hours": 1,
        })
        res = AgenticController.submit_ad_inquiry(
            name="Silent", email=_unique("sil") + "@adtest.test")
        with get_db_session() as session:
            req = session.query(ApprovalRequest).filter(
                ApprovalRequest.id == res["approval_request_id"]).first()
            # Request has climbed to the top of the ladder (admin) and BOTH
            # deadlines passed with nobody acting:
            req.assigned_role = "admin"
            req.escalation_level = req.max_escalation_level
            req.due_at = datetime.utcnow() - timedelta(hours=2)
            req.auto_approve_at = datetime.utcnow() - timedelta(hours=1)
            session.commit()

        summary = AgenticController.sweep_timeouts()
        assert summary["auto_approved"] == 1

        with get_db_session() as session:
            req = session.query(ApprovalRequest).filter(
                ApprovalRequest.id == res["approval_request_id"]).first()
            assert req.status == ApprovalRequest.STATUS_AUTO_APPROVED
            assert req.decided_by == "system:auto_approval"
            assert "auto-approved" in (req.decision_note or "").lower()
            audits = session.query(AgentAuditLog).filter(
                AgentAuditLog.event_type == "AUTO_APPROVED",
                AgentAuditLog.approval_request_id == req.id).all()
            assert audits  # audit trail for auto-decision
            sub = session.query(AdInquiry).filter(AdInquiry.id == req.subject_id).first()
            assert sub.status == "sent"  # approval side effect applied
    finally:
        AgenticController.save_policy(original)


def test_sweep_leaves_open_request_waiting_when_not_due():
    res = AgenticController.submit_ad_inquiry(
        name="Fresh", email=_unique("fr") + "@adtest.test")
    summary = AgenticController.sweep_timeouts()
    assert summary["escalated"] == 0 and summary["auto_approved"] == 0
    with get_db_session() as session:
        req = session.query(ApprovalRequest).filter(
            ApprovalRequest.id == res["approval_request_id"]).first()
        assert req.is_open()


# ---------------------------------------------------------------------------
# HTTP routes: public intake, agent inbox authz, reporter dashboard
# ---------------------------------------------------------------------------

def test_public_ad_inquiry_form_creates_request(client):
    resp = client.post("/submissions/ad", data={
        "name": "Web Client", "email": "web@client.test",
        "company": "WebCo", "package_interest": "newsletter",
        "message": "Please send rates",
    }, follow_redirects=False)
    assert resp.status_code == 302
    with get_db_session() as session:
        assert session.query(AdInquiry).filter(
            AdInquiry.email == "web@client.test").count() == 1


def test_public_news_submission_and_reporter_forms(client):
    resp = client.post("/submissions/news", data={
        "title": "ওয়েব থেকে খবর",
        "content": "পুরো খবরের পাঠ এখানে লেখা হয়েছে। " * 15,
        "email": "web@submit.test", "author": "Web Author",
    }, follow_redirects=False)
    assert resp.status_code == 302
    resp2 = client.post("/submissions/reporter", data={
        "full_name": "Web Reporter", "email": "web@apply.test",
        "experience_years": "2", "outlet": "WebMag",
        "portfolio_links": "https://p.test/a",
        "sample_text": "দীর্ঘ লেখার নমুনা এখানে লেখা হয়েছে পর্যাপ্ত পরিমাণে। " * 10,
    }, follow_redirects=False)
    assert resp2.status_code == 302
    with get_db_session() as session:
        assert session.query(NewsSubmission).filter(
            NewsSubmission.submitter_email == "web@submit.test").count() == 1
        assert session.query(ReporterApplication).filter(
            ReporterApplication.email == "web@apply.test").count() == 1


def test_agent_inbox_requires_approval_role(client):
    _login(client)
    resp = client.get("/agent/")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8", "ignore")
    assert "অনুমোদন ইনবক্স" in html or "Approval Inbox" in html
    assert "এস্কেলেশন" in html or "Escalation" in html


def test_agent_inbox_denied_for_viewer(client):
    from src.storage.repositories import UserRepository as _U
    import uuid as _uuid
    uname = "vw" + _uuid.uuid4().hex[:8]
    with get_db_session() as session:
        _U(session).create_user(username=uname, email=uname + "@t.test",
                                password="pass1234", role="viewer")
        session.commit()
    _login(client, uname, "pass1234")
    resp = client.get("/agent/", follow_redirects=False)
    assert resp.status_code in (302, 403)


def test_agent_decision_endpoint_approves_as_admin(client):
    res = AgenticController.submit_ad_inquiry(
        name="HTTP Decide", email=_unique("http") + "@adtest.test")
    _login(client)
    resp = client.post(f"/agent/decision/{res['approval_request_id']}",
                       data={"decision": "approve", "note": "ok"},
                       follow_redirects=False)
    assert resp.status_code == 302
    with get_db_session() as session:
        req = session.query(ApprovalRequest).filter(
            ApprovalRequest.id == res["approval_request_id"]).first()
        assert req.status == "approved"
        assert req.decided_by == "admin"


def test_agent_policy_save_admin_only(client):
    _login(client)
    resp = client.post("/agent/policy", data={
        "escalation_hours": "5", "auto_approve_hours": "12",
        "auto_approve_enabled": "on", "max_escalation_level": "1",
        "notify_on_create": "on", "enabled": "on",
        "recipient_editorial_lead": "lead@t.test",
        "recipient_ad_manager": "ads@t.test",
        "recipient_onboarding_officer": "hr@t.test",
        "recipient_admin": "root@t.test",
    }, follow_redirects=False)
    assert resp.status_code == 302
    policy = AgenticController.get_policy()
    assert policy["escalation_hours"] == 5
    assert policy["auto_approve_enabled"] is True
    assert policy["role_recipients"]["ad_manager"] == "ads@t.test"
    # restore defaults for other tests
    AgenticController.save_policy({
        "escalation_hours": 6, "auto_approve_enabled": False, "auto_approve_hours": 24,
        "role_recipients": {
            "editorial_lead": "editorial-lead@daily-ai-alo.com",
            "ad_manager": "ad-manager@daily-ai-alo.com",
            "onboarding_officer": "onboarding@daily-ai-alo.com",
            "admin": "admin@daily-ai-alo.com",
        },
    })


def test_reporter_dashboard_accessible_to_reporter_role(client):
    uname = "rep" + uuid.uuid4().hex[:8]
    with get_db_session() as session:
        UserRepository(session).create_user(
            username=uname, email=uname + "@reporter.test",
            password="rep1234", role="reporter")
        session.commit()
    _login(client, uname, "rep1234")
    resp = client.get("/reporter/")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8", "ignore")
    assert "রিপোর্টার ড্যাশবোর্ড" in html or "Reporter Dashboard" in html


def test_reporter_post_submission_routes_to_editorial_review(client):
    uname = "rep" + uuid.uuid4().hex[:8]
    with get_db_session() as session:
        UserRepository(session).create_user(
            username=uname, email=uname + "@reporter.test",
            password="rep1234", role="reporter")
        session.commit()
    _login(client, uname, "rep1234")
    resp = client.post("/reporter/submit", data={
        "title": "রিপোর্টার পোস্ট",
        "content": "পুরো পোস্টের খসড়া এখানে লেখা হয়েছে পর্যাপ্ত দৈর্ঘ্যে। " * 12,
        "email": uname + "@reporter.test",
    }, follow_redirects=False)
    assert resp.status_code == 302
    with get_db_session() as session:
        sub = session.query(NewsSubmission).filter(
            NewsSubmission.submitter_email == uname + "@reporter.test").first()
        assert sub is not None
        assert sub.kind == "reporter_post"
        req = session.query(ApprovalRequest).filter(
            ApprovalRequest.id == sub.approval_request_id).first()
        assert req.request_type == "editorial_review"
        assert req.required_role == "editorial_lead"


# ---------------------------------------------------------------------------
# LLM abstraction (self-hosted only, graceful degradation)
# ---------------------------------------------------------------------------

def test_llm_config_defaults_and_disabled_provider(monkeypatch):
    from src.integrations import llm_service
    cfg = llm_service.get_llm_config()
    assert cfg["provider"] in ("ollama", "openai_compat", "none")
    assert cfg["base_url"].startswith("http")

    monkeypatch.setattr(llm_service, "get_llm_config",
                        lambda: {"enabled": True, "provider": "none",
                                 "base_url": "http://127.0.0.1:1", "model": "x",
                                 "embed_model": "x", "timeout": 1})
    assert llm_service.get_llm_client() is None
    assert llm_service.generate_text("hi") is None
    assert llm_service.embed_text("hi") is None


def test_llm_unreachable_endpoint_returns_none_not_raise(monkeypatch):
    from src.integrations import llm_service
    monkeypatch.setattr(llm_service, "get_llm_config",
                        lambda: {"enabled": True, "provider": "ollama",
                                 "base_url": "http://127.0.0.1:59999", "model": "nope",
                                 "embed_model": "nope", "timeout": 1})
    assert llm_service.generate_text("hello") is None      # graceful, no exception
    assert llm_service.embed_text("hello") is None
    health = llm_service.llm_health()
    assert health["healthy"] is False
    assert "fallback" in (health.get("note") or "").lower()


# ---------------------------------------------------------------------------
# Scheduler jobs registered for the new background tasks
# ---------------------------------------------------------------------------

def test_scheduler_has_agent_and_multisource_jobs():
    from src.automation.scheduler import get_scheduler
    sched = get_scheduler()
    status = sched.get_status()
    ids = {j["job_id"] for j in status["jobs"]}
    assert "multi_source_scrape" in ids
    assert "approval_escalation_sweep" in ids
    scrape_job = next(j for j in status["jobs"] if j["job_id"] == "multi_source_scrape")
    assert 2 * 3600 <= scrape_job["interval_seconds"] <= 4 * 3600  # every 2-4 hours
    sweep_job = next(j for j in status["jobs"] if j["job_id"] == "approval_escalation_sweep")
    assert sweep_job["interval_seconds"] == 3600


def test_tasks_module_imports_and_job_functions():
    from src.tasks import approval_sweep_task, multi_source_scrape_task, fact_check_reaudit_task
    # Empty-source cycle must not raise (graceful no-op)
    out = multi_source_scrape_task(sources=[])
    assert "Multi-Source scrape" in out
    sweep = approval_sweep_task()
    assert "Approval sweep" in sweep
