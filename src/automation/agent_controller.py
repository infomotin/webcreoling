"""Agentic AI Operation Controller (কেন্দ্রীয় AI এজেন্ট কন্ট্রোলার).

Centralized AI agent that automates backend administrative workflows with
HUMAN-IN-THE-LOOP approval for every critical decision:

  * Ad Management        -> draft reply email, route to Ad Manager before sending
  * News Submissions     -> cross-source + external fact-check, route to Editorial Lead
  * Reporter Onboarding  -> credential verification, route to Onboarding Officer
  * Editorial Workflow   -> screen reporter posts, flag concerns to Editorial Lead

Role-based approval routing with hierarchical review (junior reviewers FLAG,
senior roles give the final verdict), timeout-based escalation to the next
senior role, optional auto-approval by silence, and a full audit trail of every
AI decision and human intervention (AgentAuditLog + inline audit_trail).
"""

import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

from src.common.logger import get_logger
from src.storage.database import get_db_session
from src.storage.models import (
    AdInquiry,
    AgentAuditLog,
    ApprovalRequest,
    NewsSubmission,
    ReporterApplication,
)

logger = get_logger("webcreoling.automation.agent_controller")

# Final decision authority per workflow type (senior roles)
REQUEST_ROUTES: Dict[str, str] = {
    "ad_inquiry": "ad_manager",
    "news_submission": "editorial_lead",
    "editorial_review": "editorial_lead",
    "reporter_onboarding": "onboarding_officer",
}

# Escalation ladder: when a role times out, hand over to the next senior role.
# Reaching 'admin' is the last escalation level (configurable max_escalation_level).
SENIORITY: Dict[str, Optional[str]] = {
    "editor": "editorial_lead",
    "analyst": "editorial_lead",
    "editorial_lead": "admin",
    "ad_manager": "admin",
    "onboarding_officer": "admin",
    "admin": None,
}

DEFAULT_POLICY: Dict[str, Any] = {
    "enabled": True,
    "escalation_hours": 6,
    "auto_approve_enabled": False,
    "auto_approve_hours": 24,
    "max_escalation_level": 1,     # initial assigned role -> admin
    "notify_on_create": True,
    "role_recipients": {
        "editorial_lead": "editorial-lead@daily-ai-alo.com",
        "ad_manager": "ad-manager@daily-ai-alo.com",
        "onboarding_officer": "onboarding@daily-ai-alo.com",
        "admin": "admin@daily-ai-alo.com",
    },
    "updated_at": None,
}

OPEN_STATUSES = (
    ApprovalRequest.STATUS_PENDING,
    ApprovalRequest.STATUS_FLAGGED,
    ApprovalRequest.STATUS_ESCALATED,
)

UserLike = Union[Any, str]


def _role_of(user: UserLike) -> str:
    return getattr(user, "role", None) or str(user or "")


def _name_of(user: UserLike) -> str:
    return getattr(user, "username", None) or str(user or "system")


def _user_id(user: UserLike) -> Optional[int]:
    uid = getattr(user, "id", None)
    return int(uid) if isinstance(uid, int) else None


def _flag_bool(values: Optional[List[str]]) -> bool:
    return bool(values)


class AgenticController:
    """Autonomous workflow intake, role routing, escalation & final decisions."""

    # ==================================================================
    # Policy configuration
    # ==================================================================
    @classmethod
    def get_policy(cls, session=None) -> Dict[str, Any]:
        policy = dict(DEFAULT_POLICY)
        try:
            from config.settings import settings
            policy["escalation_hours"] = int(getattr(settings, "APPROVAL_ESCALATION_HOURS", 6))
            policy["auto_approve_hours"] = int(getattr(settings, "APPROVAL_AUTO_APPROVE_HOURS", 24))
            policy["auto_approve_enabled"] = bool(
                getattr(settings, "APPROVAL_AUTO_APPROVE_ENABLED", False)
            )
        except Exception as exc:
            logger.debug(f"Approval policy env defaults note: {exc}")

        owns = session is None
        ctx = None
        try:
            if owns:
                ctx = get_db_session()
                session = ctx.__enter__()
            from src.storage.repositories import SiteConfigRepository
            stored = SiteConfigRepository(session).get_config("agent_policy", None)
            if isinstance(stored, dict):
                policy.update(stored)
        except Exception as exc:
            logger.debug(f"Agent policy load note: {exc}")
        finally:
            if owns and ctx is not None:
                try:
                    ctx.__exit__(None, None, None)
                except Exception:
                    pass
        return policy

    @classmethod
    def save_policy(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        from src.storage.repositories import SiteConfigRepository
        with get_db_session() as session:
            policy = cls.get_policy(session)
            policy.update(data)
            policy["updated_at"] = datetime.utcnow().isoformat()
            SiteConfigRepository(session).set_config("agent_policy", policy)
            return policy

    # ==================================================================
    # Audit helpers (DB log + inline trail on the request)
    # ==================================================================
    @classmethod
    def _audit(
        cls,
        session,
        event_type: str,
        *,
        actor: str = "ai_agent",
        actor_user: Optional[UserLike] = None,
        request_type: Optional[str] = None,
        subject_id: Optional[int] = None,
        approval_request_id: Optional[int] = None,
        message: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> AgentAuditLog:
        log = AgentAuditLog(
            event_type=event_type,
            actor=actor,
            actor_user_id=_user_id(actor_user) if actor_user is not None else None,
            actor_role=_role_of(actor_user) if actor_user is not None else None,
            request_type=request_type,
            subject_id=subject_id,
            approval_request_id=approval_request_id,
            message=message,
            details=details or {},
        )
        session.add(log)
        return log

    @staticmethod
    def _trail(req: ApprovalRequest, event_type: str, message: str,
               actor: str = "ai_agent") -> None:
        trail = list(req.audit_trail or [])
        trail.append({
            "event": event_type,
            "message": message,
            "actor": actor,
            "at": datetime.utcnow().isoformat(),
        })
        req.audit_trail = trail

    # ==================================================================
    # Notifications (SMTP via integrations.mail_service — sandbox-safe)
    # ==================================================================
    @classmethod
    def _notify_role(cls, session, policy: Dict[str, Any], role: str,
                     subject_label: str, request: ApprovalRequest) -> bool:
        if not policy.get("notify_on_create", True):
            return False
        recipients = policy.get("role_recipients") or {}
        to = recipients.get(role) or recipients.get("admin")
        if not to:
            return False
        from src.integrations.mail_service import send_mail
        due = request.due_at.strftime("%Y-%m-%d %H:%M UTC") if request.due_at else "—"
        html = f"""
        <div style="font-family:Arial,sans-serif;background:#f1f5f9;padding:20px;">
          <div style="max-width:560px;margin:auto;background:#fff;border-radius:12px;padding:24px;border:1px solid #e2e8f0;">
            <h3 style="margin:0 0 8px;color:#0f172a;">অনুমোদনের অপেক্ষায় / Awaiting your approval</h3>
            <p style="color:#334155;"><b>{subject_label}</b></p>
            <p style="color:#64748b;font-size:13px;">Type: {request.request_type} · Status: {request.status}<br>
            Escalation deadline: {due}</p>
            <p style="color:#64748b;font-size:12px;">Role: {role} · সিদ্ধান্ত নিন: /agent (AI Agent Controller)</p>
          </div>
        </div>"""
        try:
            res = send_mail(session, to, f"[Approval #{request.id}] {subject_label[:80]}",
                            html, purpose="approval_request")
            return bool(res.get("ok"))
        except Exception as exc:
            logger.warning(f"Approval notify mail failed: {exc}")
            return False

    @classmethod
    def _notify_user(cls, session, to: str, subject: str, html: str,
                     purpose: str = "agent_workflow") -> bool:
        if not to or "@" not in to:
            return False
        from src.integrations.mail_service import send_mail
        try:
            res = send_mail(session, to, subject, html, purpose=purpose)
            return bool(res.get("ok"))
        except Exception as exc:
            logger.warning(f"Agent notify mail to {to} failed: {exc}")
            return False

    # ==================================================================
    # Approval request creation (role routing)
    # ==================================================================
    @classmethod
    def _create_request(
        cls,
        session,
        policy: Dict[str, Any],
        request_type: str,
        subject,
        label: str,
        payload: Dict[str, Any],
        flags: Optional[List[str]] = None,
    ) -> ApprovalRequest:
        required_role = REQUEST_ROUTES.get(request_type, "editorial_lead")
        now = datetime.utcnow()
        escalation_hours = max(1, int(policy.get("escalation_hours", 6)))
        flags = flags or []

        req = ApprovalRequest(
            request_type=request_type,
            subject_id=subject.id,
            subject_label=label[:255],
            payload=payload,
            required_role=required_role,
            assigned_role=required_role,
            status=ApprovalRequest.STATUS_FLAGGED if flags else ApprovalRequest.STATUS_PENDING,
            priority="high" if flags else "normal",
            flags=flags,
            audit_trail=[],
            escalation_level=0,
            max_escalation_level=max(0, int(policy.get("max_escalation_level", 1))),
            created_at=now,
            due_at=now + timedelta(hours=escalation_hours),
            auto_approve_at=(now + timedelta(hours=max(1, int(policy.get("auto_approve_hours", 24)))))
            if policy.get("auto_approve_enabled") else None,
        )
        session.add(req)
        session.flush()

        subject.approval_request_id = req.id
        cls._trail(req, "INTAKE", f"Routed to {required_role} (flags: {flags or 'none'})")
        cls._audit(
            session, "INTAKE",
            request_type=request_type, subject_id=subject.id,
            approval_request_id=req.id,
            message=f"AI Agent screened '{label}' and routed to {required_role}",
            details={"flags": flags, "payload_keys": sorted(payload.keys())},
        )
        if policy.get("notify_on_create", True):
            if cls._notify_role(session, policy, required_role, label, req):
                cls._audit(session, "NOTIFY",
                           request_type=request_type, subject_id=subject.id,
                           approval_request_id=req.id,
                           message=f"Approval request emailed to {required_role} recipient")
        return req

    # ==================================================================
    # Intake 1: Advertising inquiry (draft reply -> Ad Manager approval)
    # ==================================================================
    @classmethod
    def _draft_ad_reply(cls, inquiry: AdInquiry) -> Dict[str, Any]:
        """Draft a reply email; LLM (self-hosted) first, template fallback."""
        subject = f"বিজ্ঞাপন সম্পর্কে / Re: Your advertising inquiry — The Daily AI Alo"
        rate_lines = (
            "• হোমপেজ ব্যানার (Homepage Banner): ৳ ১৫,০০০ / মাস\n"
            "• স্পনসরড কন্টেন্ট (Sponsored Article): ৳ ১২,০০০ / প্রতি প্রবন্ধ\n"
            "• নিউজলেটার প্লেসমেন্ট (Newsletter): ৳ ৮,০০০ / প্রতি সংখ্যা\n"
            "• সোশ্যাল ক্রস-পোস্ট (Social Boost): ৳ ৫,০০০ / ক্যাম্পেইন"
        )
        body_template = f"""প্রিয় {inquiry.name or 'Client'},

আপনার বিজ্ঞাপন সংক্রান্ত অনুসন্ধানের জন্য ধন্যবাদ। দি ডেইলি এআই আলো-তে
আপনার ব্র্যান্ডকে আমাদের পাঠকদের সামনে তুলে ধরার সুযোগ রয়েছে।

আমাদের রেট কার্ড / Our rate card:
{rate_lines}

{'আগ্রহী প্যাকেজ: ' + str(inquiry.package_interest) + chr(10) if inquiry.package_interest else ''}{'বাজেট নোট: ' + str(inquiry.budget_note) + chr(10) if inquiry.budget_note else ''}
বিস্তারিত আলোচনার জন্য আমাদের বিজ্ঞাপন বিভাগে উত্তর দিন। আমরা ২৪ ঘণ্টার মধ্যে
যোগাযোগ করব।

ধন্যবাদ,
বিজ্ঞাপন বিভাগ, দি ডেইলি এআই আলো (The Daily AI Alo)
(প্রকাশক: The Daily AI Alo Media & Tech Labs)"""

        generated_by = "template"
        body = body_template
        try:
            from src.integrations.llm_service import generate_text
            prompt = (
                f"Write a professional Bengali+English advertising inquiry reply email for "
                f"The Daily AI Alo news portal. Client: {inquiry.name}, Company: "
                f"{inquiry.company or 'N/A'}, Interested in: {inquiry.package_interest or 'general advertising'}, "
                f"Budget note: {inquiry.budget_note or 'unstated'}. Include these rates:\n{rate_lines}\n"
                f"End with a call to action to reply for a meeting. Keep under 200 words."
            )
            text = generate_text(prompt, system="You are the ad sales desk of a Bangla news portal.",
                                 max_tokens=400, temperature=0.4)
            if text and len(text.strip()) > 80:
                body = text.strip()
                generated_by = "llm"
        except Exception as exc:
            logger.debug(f"LLM ad draft fallback note: {exc}")
        return {"subject": subject, "body": body, "generated_by": generated_by}

    @classmethod
    def submit_ad_inquiry(
        cls,
        name: str,
        email: str,
        message: str = "",
        company: Optional[str] = None,
        phone: Optional[str] = None,
        package_interest: Optional[str] = None,
        budget_note: Optional[str] = None,
        session=None,
    ) -> Dict[str, Any]:
        """AI agent drafts a reply; the Ad Manager must approve before it is sent."""
        owns = session is None
        ctx = None
        try:
            if owns:
                ctx = get_db_session()
                session = ctx.__enter__()
            policy = cls.get_policy(session)

            inquiry = AdInquiry(
                name=(name or "Unknown").strip()[:200],
                company=(company or "").strip()[:200] or None,
                email=(email or "").strip().lower(),
                phone=(phone or "").strip()[:50] or None,
                package_interest=(package_interest or "").strip()[:120] or None,
                budget_note=(budget_note or "").strip()[:255] or None,
                message=(message or "").strip(),
                status="drafted",
            )
            session.add(inquiry)
            session.flush()

            draft = cls._draft_ad_reply(inquiry)
            inquiry.draft_subject = draft["subject"]
            inquiry.draft_body = draft["body"]
            inquiry.draft_generated_by = draft["generated_by"]
            inquiry.status = "pending_approval"
            session.flush()

            req = cls._create_request(
                session, policy, "ad_inquiry", inquiry,
                label=f"Ad inquiry: {inquiry.name} ({inquiry.company or inquiry.email})",
                payload={
                    "name": inquiry.name, "company": inquiry.company, "email": inquiry.email,
                    "phone": inquiry.phone, "package_interest": inquiry.package_interest,
                    "budget_note": inquiry.budget_note, "message": inquiry.message,
                    "draft_subject": inquiry.draft_subject, "draft_body": inquiry.draft_body,
                    "draft_generated_by": draft["generated_by"],
                },
            )
            if owns:
                session.commit()
            return {
                "success": True, "inquiry_id": inquiry.id,
                "approval_request_id": req.id, "assigned_role": req.required_role,
                "status": inquiry.status, "draft_generated_by": draft["generated_by"],
            }
        except Exception as exc:
            if owns and ctx is not None:
                session.rollback()
            logger.error(f"Ad inquiry intake failed: {exc}", exc_info=True)
            return {"success": False, "error": str(exc)}
        finally:
            if owns and ctx is not None:
                try:
                    ctx.__exit__(None, None, None)
                except Exception:
                    pass

    # ==================================================================
    # Intake 2: News submission (fact-check -> Editorial Lead approval)
    # ==================================================================
    @classmethod
    def submit_news_submission(
        cls,
        title: str,
        content: str,
        submitter_email: str,
        author_name: Optional[str] = None,
        source_url: Optional[str] = None,
        kind: str = "external",   # external | reporter_post
        session=None,
    ) -> Dict[str, Any]:
        """Dual-strategy fact-check, then route to the Editorial Lead (never auto-reject)."""
        owns = session is None
        ctx = None
        try:
            if owns:
                ctx = get_db_session()
                session = ctx.__enter__()
            policy = cls.get_policy(session)

            from src.automation.fact_checker import FactCheckService
            fact = FactCheckService.full_check(title, content, session=session)
            flags = list(fact.get("flags") or [])
            low_confidence = "low_confidence" in flags

            submission = NewsSubmission(
                title=(title or "").strip(),
                content_text=(content or "").strip(),
                author_name=(author_name or "").strip()[:200] or None,
                submitter_email=(submitter_email or "").strip().lower(),
                source_url=(source_url or "").strip()[:1000] or None,
                language="bn" if any("\u0980" <= ch <= "\u09ff" for ch in (title or "")) else "en",
                kind=kind,
                fact_check=fact,
                flags=flags,
                status="screened",
            )
            session.add(submission)
            session.flush()

            request_type = "editorial_review" if kind == "reporter_post" else "news_submission"
            req = cls._create_request(
                session, policy, request_type, submission,
                label=f"{'Reporter post' if kind == 'reporter_post' else 'News submission'}: {(title or '')[:160]}",
                payload={
                    "title": submission.title,
                    "author_name": submission.author_name,
                    "submitter_email": submission.submitter_email,
                    "source_url": submission.source_url,
                    "kind": submission.kind,
                    "combined_confidence": fact.get("combined_confidence"),
                    "strategy": fact.get("strategy"),
                    "cross_source": fact.get("cross_source"),
                    "external": fact.get("external"),
                    "flags": flags,
                    "excerpt": (content or "")[:600],
                },
                flags=flags,
            )
            submission.status = "flagged" if low_confidence else "pending_approval"
            session.flush()

            if owns:
                session.commit()
            return {
                "success": True, "submission_id": submission.id,
                "approval_request_id": req.id, "assigned_role": req.required_role,
                "status": submission.status,
                "combined_confidence": fact.get("combined_confidence"),
                "flags": flags,
            }
        except Exception as exc:
            if owns and ctx is not None:
                session.rollback()
            logger.error(f"News submission intake failed: {exc}", exc_info=True)
            return {"success": False, "error": str(exc)}
        finally:
            if owns and ctx is not None:
                try:
                    ctx.__exit__(None, None, None)
                except Exception:
                    pass

    # ==================================================================
    # Intake 3: Reporter onboarding (verification -> Onboarding Officer)
    # ==================================================================
    @classmethod
    def _verify_reporter(
        cls,
        email: str,
        credentials: Dict[str, Any],
        portfolio_links: List[str],
        sample_text: str,
    ) -> Dict[str, Any]:
        """Automated credential & sample-quality screening (concerns are FLAGGED)."""
        checks: Dict[str, bool] = {}
        concerns: List[str] = []

        checks["valid_email"] = bool(email) and "@" in email and "." in email.split("@")[-1]
        if not checks["valid_email"]:
            concerns.append("invalid_email")

        words = (sample_text or "").split()
        checks["sample_present"] = len(words) >= 20
        if not checks["sample_present"]:
            concerns.append("sample_missing_or_too_short")

        checks["portfolio_present"] = bool(portfolio_links)
        if not checks["portfolio_present"]:
            concerns.append("no_portfolio_links")

        checks["experience_declared"] = bool(
            credentials.get("experience_years") or credentials.get("outlet") or credentials.get("beat")
        )
        if not checks["experience_declared"]:
            concerns.append("experience_not_declared")

        # Quality heuristic (0-100): length + structure + clarity signals
        quality = 15 if checks["valid_email"] else 0
        quality += min(35, len(words) * 0.35)          # up to ~100 words -> 35
        sentences = [s for s in (sample_text or "").replace("।", ".").split(".") if s.strip()]
        quality += 20 if len(sentences) >= 5 else max(0, len(sentences) * 3)
        quality += 15 if checks["portfolio_present"] else 0
        quality += 15 if checks["experience_declared"] else 0
        quality = round(min(99.0, quality), 1)
        if quality < 60:
            concerns.append("sample_quality_below_60")

        return {
            "checks": checks,
            "quality_score": quality,
            "concerns": concerns,
            "verified_at": datetime.utcnow().isoformat(),
            "verdict": "flagged" if concerns else "verified",
        }

    @classmethod
    def submit_reporter_application(
        cls,
        full_name: str,
        email: str,
        phone: Optional[str] = None,
        credentials: Optional[Dict[str, Any]] = None,
        portfolio_links: Optional[List[str]] = None,
        sample_text: str = "",
        session=None,
    ) -> Dict[str, Any]:
        """Verify credentials & sample quality, then route to the Onboarding Officer."""
        owns = session is None
        ctx = None
        try:
            if owns:
                ctx = get_db_session()
                session = ctx.__enter__()
            policy = cls.get_policy(session)

            credentials = dict(credentials or {})
            portfolio_links = list(portfolio_links or [])
            verification = cls._verify_reporter(email, credentials, portfolio_links, sample_text)
            flags = list(verification["concerns"])

            application = ReporterApplication(
                full_name=(full_name or "Unknown").strip()[:200],
                email=(email or "").strip().lower(),
                phone=(phone or "").strip()[:50] or None,
                credentials=credentials,
                portfolio_links=portfolio_links,
                sample_text=(sample_text or "").strip()[:20000] or None,
                verification=verification,
                status="flagged" if flags else "verified",
            )
            session.add(application)
            session.flush()

            req = cls._create_request(
                session, policy, "reporter_onboarding", application,
                label=f"Reporter application: {application.full_name} ({application.email})",
                payload={
                    "full_name": application.full_name,
                    "email": application.email,
                    "phone": application.phone,
                    "credentials": credentials,
                    "portfolio_links": portfolio_links,
                    "verification": verification,
                },
                flags=flags,
            )
            session.flush()

            if owns:
                session.commit()
            return {
                "success": True, "application_id": application.id,
                "approval_request_id": req.id, "assigned_role": req.required_role,
                "status": application.status, "verification": verification,
            }
        except Exception as exc:
            if owns and ctx is not None:
                session.rollback()
            logger.error(f"Reporter application intake failed: {exc}", exc_info=True)
            return {"success": False, "error": str(exc)}
        finally:
            if owns and ctx is not None:
                try:
                    ctx.__exit__(None, None, None)
                except Exception:
                    pass

    # ==================================================================
    # Final approval side effects (per workflow type)
    # ==================================================================
    @classmethod
    def _apply_approval(cls, session, policy: Dict[str, Any], req: ApprovalRequest,
                        actor_label: str) -> Dict[str, Any]:
        effects: Dict[str, Any] = {}

        if req.request_type == "ad_inquiry":
            inquiry = session.query(AdInquiry).filter(AdInquiry.id == req.subject_id).first()
            if inquiry:
                inquiry.status = "approved"
                session.flush()
                # Send the (approved) drafted reply to the advertiser
                sent = cls._notify_user(
                    session, inquiry.email,
                    inquiry.draft_subject or "Re: Your advertising inquiry",
                    f"<div style='font-family:Arial;white-space:pre-wrap;'>{inquiry.draft_body or ''}</div>",
                    purpose="ad_inquiry_reply",
                )
                if sent:
                    inquiry.status = "sent"
                    inquiry.sent_at = datetime.utcnow()
                    cls._audit(session, "EMAIL_SENT", actor="user",
                               request_type=req.request_type, subject_id=inquiry.id,
                               approval_request_id=req.id,
                               message=f"Approved ad reply sent to {inquiry.email} (approved by {actor_label})")
                effects["email_sent"] = sent
                effects["inquiry_status"] = inquiry.status

        elif req.request_type in ("news_submission", "editorial_review"):
            submission = session.query(NewsSubmission).filter(NewsSubmission.id == req.subject_id).first()
            if submission:
                from src.storage.repositories import ArticleRepository
                credit = (f"\n\nপ্রকাশক: The Daily AI Alo · জমাদাতা (Submitter): "
                          f"{submission.author_name or submission.submitter_email}")
                article = ArticleRepository(session).create_editorial_article(
                    title=submission.title,
                    category="general",
                    content_text=(submission.content_text or "").strip(),
                    author=submission.author_name or "Guest Correspondent",
                    summary=(submission.content_text or "")[:400],
                    status="completed",
                    source=f"Submission ({submission.kind})",
                    original_source_url=submission.source_url or None,
                    creation_origin="HYBRID",
                    position_placement="STANDARD",
                )
                if submission.source_url and submission.source_url not in article.content_text:
                    article.content_text = f"{article.content_text.rstrip()}{credit}"
                submission.status = "published"
                submission.article_id = article.id
                session.flush()
                # Keep duplicates linked (spec: separate entries + related_articles)
                try:
                    from src.automation.dedup import link_related_articles
                    link_related_articles(session, article)
                except Exception as dedup_exc:
                    logger.warning(f"Related-link on submission publish failed: {dedup_exc}")
                effects["article_id"] = article.id
                effects["submission_status"] = "published"
                cls._audit(session, "APPROVED", actor="user",
                           request_type=req.request_type, subject_id=submission.id,
                           approval_request_id=req.id,
                           message=f"Approved submission published as article #{article.id}")

        elif req.request_type == "reporter_onboarding":
            application = session.query(ReporterApplication).filter(
                ReporterApplication.id == req.subject_id
            ).first()
            if application:
                from src.storage.repositories import UserRepository
                users = UserRepository(session)
                base = (application.email.split("@")[0] or "reporter").replace(".", "_")[:40]
                username = base
                suffix = 1
                while users.get_by_username(username):
                    suffix += 1
                    username = f"{base}{suffix}"
                password = secrets.token_urlsafe(10)
                new_user = users.create_user(
                    username=username,
                    email=application.email,
                    password=password,
                    role="reporter",
                )
                application.status = "approved"
                application.user_id = new_user.id if new_user else None
                session.flush()
                effects["username"] = username
                effects["user_id"] = application.user_id
                effects["application_status"] = "approved"
                cls._notify_user(
                    session, application.email,
                    "রিপোর্টার অনুমোদিত / Reporter Account Approved — The Daily AI Alo",
                    f"<div style='font-family:Arial;white-space:pre-wrap;'>"
                    f"প্রিয় {application.full_name},\n\n"
                    f"আপনার রিপোর্টার আবেদন অনুমোদিত হয়েছে।\n"
                    f"Username: {username}\nPassword: {password}\n"
                    f"ড্যাশবোর্ড: /reporter\n\n— দি ডেইলি এআই আলো"
                    f"</div>",
                    purpose="reporter_onboard",
                )
                cls._audit(session, "EMAIL_SENT", actor="user",
                           request_type=req.request_type, subject_id=application.id,
                           approval_request_id=req.id,
                           message=f"Onboarding credentials emailed to {application.email}")

        return effects

    @classmethod
    def _apply_rejection(cls, session, req: ApprovalRequest, actor_label: str) -> Dict[str, Any]:
        effects: Dict[str, Any] = {}
        if req.request_type == "ad_inquiry":
            inquiry = session.query(AdInquiry).filter(AdInquiry.id == req.subject_id).first()
            if inquiry:
                inquiry.status = "rejected"
                effects["inquiry_status"] = "rejected"
        elif req.request_type in ("news_submission", "editorial_review"):
            submission = session.query(NewsSubmission).filter(NewsSubmission.id == req.subject_id).first()
            if submission:
                submission.status = "rejected"
                effects["submission_status"] = "rejected"
        elif req.request_type == "reporter_onboarding":
            application = session.query(ReporterApplication).filter(
                ReporterApplication.id == req.subject_id
            ).first()
            if application:
                application.status = "rejected"
                effects["application_status"] = "rejected"
        return effects

    # ==================================================================
    # Human decisions (role-checked; juniors only FLAG)
    # ==================================================================
    @classmethod
    def decide(
        cls,
        request_id: int,
        decision: str,          # 'approve' | 'reject' | 'flag'
        user: UserLike,
        note: str = "",
        session=None,
    ) -> Dict[str, Any]:
        """Final verdict only for the required senior role (or admin).

        Junior reviewers may FLAG — the request then REMAINS PENDING for the
        senior role (rejected items stay open until final disposition).
        """
        decision = (decision or "").lower().strip()
        if decision not in ("approve", "reject", "flag"):
            return {"success": False, "error": f"Unknown decision '{decision}'"}

        owns = session is None
        ctx = None
        try:
            if owns:
                ctx = get_db_session()
                session = ctx.__enter__()

            req = session.query(ApprovalRequest).filter(
                ApprovalRequest.id == request_id
            ).first()
            if not req:
                return {"success": False, "error": f"Approval request #{request_id} not found"}
            if not req.is_open():
                return {"success": False, "error": f"Request already {req.status}",
                        "status": req.status}

            policy = cls.get_policy(session)
            role = _role_of(user)
            actor_name = _name_of(user)
            is_admin = role == "admin"
            is_senior = is_admin or role == req.required_role
            has_authority = is_senior or role in ("admin", req.required_role, "editor")

            if not has_authority:
                return {"success": False, "error": f"Role '{role}' cannot act on this request"}

            # Junior reviewer flag (or explicit flag by anyone with authority):
            if decision == "flag" or (not is_senior and decision in ("approve", "reject")):
                flags = list(req.flags or [])
                tag = note.strip() or f"{decision} by junior reviewer ({role})"
                if tag not in flags:
                    flags.append(tag[:250])
                req.flags = flags
                req.status = ApprovalRequest.STATUS_FLAGGED
                cls._trail(req, "JUNIOR_REVIEW",
                           f"{actor_name} ({role}) recorded '{decision}' — flagged for "
                           f"{req.required_role} final judgment", actor=actor_name)
                cls._audit(
                    session, "FLAGGED", actor="user", actor_user=user,
                    request_type=req.request_type, subject_id=req.subject_id,
                    approval_request_id=req.id,
                    message=f"Junior reviewer {actor_name} ({role}) flagged for {req.required_role}",
                    details={"decision": decision, "note": note},
                )
                # Keep subject pending — no autonomous rejection by juniors
                cls._set_subject_pending(session, req)
                if owns:
                    session.commit()
                return {"success": True, "status": "flagged",
                        "assigned_role": req.required_role,
                        "message": f"Flagged for {req.required_role} final judgment"}

            now = datetime.utcnow()
            effects: Dict[str, Any] = {}
            if decision == "approve":
                req.status = ApprovalRequest.STATUS_APPROVED
                effects = cls._apply_approval(session, policy, req, actor_name)
                event = "APPROVED"
                subject_word = "approved"
            else:
                req.status = ApprovalRequest.STATUS_REJECTED
                effects = cls._apply_rejection(session, req, actor_name)
                event = "REJECTED"
                subject_word = "rejected"

            req.decided_at = now
            req.decided_by = actor_name
            req.decision_note = note.strip() or f"{subject_word} by {actor_name}"
            req.due_at = None
            cls._trail(req, event, req.decision_note, actor=actor_name)
            cls._audit(
                session, event, actor="user", actor_user=user,
                request_type=req.request_type, subject_id=req.subject_id,
                approval_request_id=req.id,
                message=f"{subject_word.capitalize()} by {actor_name} ({role})",
                details={"note": note, "effects": effects},
            )
            if owns:
                session.commit()
            return {"success": True, "status": req.status, "effects": effects,
                    "decision": decision}
        except Exception as exc:
            if owns and ctx is not None:
                session.rollback()
            logger.error(f"Decision on request #{request_id} failed: {exc}", exc_info=True)
            return {"success": False, "error": str(exc)}
        finally:
            if owns and ctx is not None:
                try:
                    ctx.__exit__(None, None, None)
                except Exception:
                    pass

    @classmethod
    def _set_subject_pending(cls, session, req: ApprovalRequest) -> None:
        """A flagged request keeps its subject in 'flagged' (never auto-rejected)."""
        try:
            if req.request_type == "ad_inquiry":
                subj = session.query(AdInquiry).filter(AdInquiry.id == req.subject_id).first()
                if subj and subj.status not in ("sent", "rejected"):
                    subj.status = "flagged"
            elif req.request_type in ("news_submission", "editorial_review"):
                subj = session.query(NewsSubmission).filter(NewsSubmission.id == req.subject_id).first()
                if subj and subj.status not in ("published", "rejected"):
                    subj.status = "flagged"
            elif req.request_type == "reporter_onboarding":
                subj = session.query(ReporterApplication).filter(
                    ReporterApplication.id == req.subject_id).first()
                if subj and subj.status not in ("approved", "rejected"):
                    subj.status = "flagged"
        except Exception as exc:
            logger.debug(f"Subject pending update note: {exc}")

    # ==================================================================
    # Timeout escalation & auto-approval (scheduler-driven sweep)
    # ==================================================================
    @classmethod
    def escalate(
        cls,
        request_id: int,
        reason: str = "Timeout — no response before deadline",
        actor: str = "system",
        session=None,
    ) -> Dict[str, Any]:
        owns = session is None
        ctx = None
        try:
            if owns:
                ctx = get_db_session()
                session = ctx.__enter__()
            req = session.query(ApprovalRequest).filter(
                ApprovalRequest.id == request_id
            ).first()
            if not req or not req.is_open():
                return {"success": False, "error": "Request not open"}

            policy = cls.get_policy(session)
            current_role = req.assigned_role or req.required_role
            next_role = SENIORITY.get(current_role) or "admin"
            if req.escalation_level >= req.max_escalation_level and current_role == "admin":
                return {"success": False, "error": "Already at highest escalation level"}

            now = datetime.utcnow()
            req.escalation_level += 1
            req.assigned_role = next_role
            req.status = ApprovalRequest.STATUS_ESCALATED
            req.escalated_at = now
            req.due_at = now + timedelta(hours=max(1, int(policy.get("escalation_hours", 6))))
            cls._trail(req, "ESCALATED", f"{current_role} -> {next_role}: {reason}", actor=actor)
            cls._audit(
                session, "ESCALATED", actor=actor,
                request_type=req.request_type, subject_id=req.subject_id,
                approval_request_id=req.id,
                message=f"Escalated {current_role} -> {next_role}: {reason}",
                details={"level": req.escalation_level, "due_at": req.due_at.isoformat()},
            )
            if cls._notify_role(session, policy, next_role, req.subject_label or "", req):
                cls._audit(session, "NOTIFY", actor=actor,
                           request_type=req.request_type, subject_id=req.subject_id,
                           approval_request_id=req.id,
                           message=f"Escalation notice sent to {next_role}")
            if owns:
                session.commit()
            return {"success": True, "assigned_role": next_role,
                    "escalation_level": req.escalation_level,
                    "due_at": req.due_at.isoformat() if req.due_at else None}
        except Exception as exc:
            if owns and ctx is not None:
                session.rollback()
            logger.error(f"Escalation of request #{request_id} failed: {exc}")
            return {"success": False, "error": str(exc)}
        finally:
            if owns and ctx is not None:
                try:
                    ctx.__exit__(None, None, None)
                except Exception:
                    pass

    @classmethod
    def sweep_timeouts(cls, now: Optional[datetime] = None, session=None) -> Dict[str, Any]:
        """Hourly sweep: escalate overdue requests (next senior role) or auto-approve
        (if configured — approval by silence). Every action is audited."""
        now = now or datetime.utcnow()
        summary = {"checked": 0, "escalated": 0, "auto_approved": 0, "waiting": 0,
                   "swept_at": now.isoformat()}
        owns = session is None
        ctx = None
        try:
            if owns:
                ctx = get_db_session()
                session = ctx.__enter__()
            policy = cls.get_policy(session)
            if not policy.get("enabled", True):
                summary["note"] = "Agent workflow disabled — sweep skipped."
                return summary

            open_requests = (
                session.query(ApprovalRequest)
                .filter(ApprovalRequest.status.in_(OPEN_STATUSES))
                .filter(ApprovalRequest.due_at.isnot(None))
                .order_by(ApprovalRequest.id.asc())
                .all()
            )

            for req in open_requests:
                if req.due_at and req.due_at > now:
                    continue
                summary["checked"] += 1
                can_escalate = req.escalation_level < req.max_escalation_level or \
                    (req.assigned_role or req.required_role) != "admin"

                if can_escalate and req.due_at and req.due_at <= now:
                    res = cls.escalate(req.id, actor="system:timeout", session=session)
                    if res.get("success"):
                        summary["escalated"] += 1
                        continue

                # Final level: auto-approve by silence if configured
                if policy.get("auto_approve_enabled", False) and req.auto_approve_at \
                        and now >= req.auto_approve_at:
                    req.status = ApprovalRequest.STATUS_AUTO_APPROVED
                    req.decided_at = now
                    req.decided_by = "system:auto_approval"
                    req.decision_note = (f"Auto-approved by silence after "
                                         f"{policy.get('auto_approve_hours', 24)}h with no response")
                    req.due_at = None
                    effects = cls._apply_approval(session, policy, req, "system:auto_approval")
                    cls._trail(req, "AUTO_APPROVED", req.decision_note, actor="system")
                    cls._audit(
                        session, "AUTO_APPROVED", actor="system",
                        request_type=req.request_type, subject_id=req.subject_id,
                        approval_request_id=req.id,
                        message=req.decision_note, details={"effects": effects},
                    )
                    summary["auto_approved"] += 1
                    continue

                # Nothing left to do automatically — wait for a human at the top level
                summary["waiting"] += 1
                req.status = ApprovalRequest.STATUS_ESCALATED if req.escalation_level else req.status

            if owns:
                session.commit()
            if summary["checked"]:
                logger.info(f"[Agent Sweep] {summary}")
            return summary
        except Exception as exc:
            if owns and ctx is not None:
                session.rollback()
            logger.error(f"Approval timeout sweep failed: {exc}")
            summary["error"] = str(exc)
            return summary
        finally:
            if owns and ctx is not None:
                try:
                    ctx.__exit__(None, None, None)
                except Exception:
                    pass

    # ==================================================================
    # Inbox / audit views
    # ==================================================================
    @classmethod
    def list_inbox(
        cls,
        session,
        request_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        q = session.query(ApprovalRequest).order_by(ApprovalRequest.id.desc())
        if request_type:
            q = q.filter(ApprovalRequest.request_type == request_type)
        if status:
            if status == "open":
                q = q.filter(ApprovalRequest.status.in_(OPEN_STATUSES))
            else:
                q = q.filter(ApprovalRequest.status == status)
        return [r.to_dict() for r in q.limit(limit).all()]

    @classmethod
    def get_audit_log(cls, session, limit: int = 50) -> List[Dict[str, Any]]:
        rows = (
            session.query(AgentAuditLog)
            .order_by(AgentAuditLog.id.desc())
            .limit(limit)
            .all()
        )
        return [r.to_dict() for r in rows]

    @classmethod
    def inbox_view_data(
        cls,
        request_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        audit_limit: int = 40,
        run_sweep: bool = True,
    ) -> Dict[str, Any]:
        """Lazy timeout sweep + inbox payload for the admin UI."""
        sweep = {"checked": 0, "escalated": 0, "auto_approved": 0, "waiting": 0}
        if run_sweep:
            try:
                sweep = cls.sweep_timeouts()
            except Exception as exc:
                logger.warning(f"Inbox sweep note: {exc}")
        with get_db_session() as session:
            requests_list = cls.list_inbox(session, request_type, status, limit)
            audit = cls.get_audit_log(session, audit_limit)
            policy = cls.get_policy(session)
            open_count = session.query(ApprovalRequest).filter(
                ApprovalRequest.status.in_(OPEN_STATUSES)
            ).count()
            return {
                "requests": requests_list,
                "audit": audit,
                "policy": policy,
                "open_count": open_count,
                "sweep": sweep,
            }

    @classmethod
    def get_request_detail(cls, request_id: int) -> Optional[Dict[str, Any]]:
        with get_db_session() as session:
            req = session.query(ApprovalRequest).filter(
                ApprovalRequest.id == request_id
            ).first()
            return req.to_dict() if req else None
