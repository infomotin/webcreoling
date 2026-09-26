"""One-time recovery: restore articles destroyed by Emergency Vault auto-lockdown.

Strategy:
  1. Snapshot currently-encrypted rows (safety, revertable).
  2. Scan all SQL dumps newest->oldest; first non-marker version of each article wins.
  3. UPDATE only rows whose title still shows the encryption marker.
  4. Reset EmergencyVaultState and delete useless marker-payload backup records.
"""

import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymysql

from config.settings import settings
from src.storage.database import SessionLocal
from src.storage.models import EmergencyVaultState, EncryptedVaultBackupRecord

BACKUP_DIR = Path(settings.BASE_DIR) / "data" / "backups"
SNAPSHOT_FILE = BACKUP_DIR / "encrypted_articles_snapshot_before_restore.json"

MARKER_TITLE = "SYSTEM ENCRYPTED DATA"
MARKER_PREFIX = "\U0001f512"  # 🔒
PLACEHOLDER_CONTENT_START = "\U0001f512 এই সংবাদের সম্পূর্ণ ডাটাবেস"


def is_clean_record(rec: dict) -> bool:
    title = rec.get("title") or ""
    content = rec.get("content_text") or ""
    if MARKER_TITLE in title or title.startswith(MARKER_PREFIX):
        return False
    if content.startswith(PLACEHOLDER_CONTENT_START):
        return False
    return True


def load_dump_origins() -> dict:
    """id -> cleanest (newest non-marker) article record found across dumps."""
    dumps = sorted(BACKUP_DIR.glob("ai_news_db_dump_*.sql"), reverse=True)
    origins: dict = {}
    for dump in dumps:
        try:
            with io.open(dump, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if "RESTORE_RECORD:articles" not in line or "*/" not in line:
                        continue
                    try:
                        rec = json.loads(line.split("*/", 1)[1].strip())
                    except (ValueError, IndexError):
                        continue
                    aid = rec.get("id")
                    if aid is None or aid in origins:
                        continue
                    if is_clean_record(rec):
                        origins[aid] = rec
        except OSError as exc:
            print(f"  ! cannot read {dump.name}: {exc}")
    return origins


def main() -> None:
    m = re.match(
        r"mysql\+pymysql://([^:]+):([^@]+)@([^:/]+):(\d+)/([^?]+)", settings.DATABASE_URL
    )
    if not m:
        raise RuntimeError(f"Unexpected DATABASE_URL: {settings.DATABASE_URL}")
    conn = pymysql.connect(
        user=m.group(1),
        password=m.group(2),
        host=m.group(3),
        port=int(m.group(4)),
        database=m.group(5),
        charset="utf8mb4",
        autocommit=False,
    )

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            "SELECT id, title, content_text, summary, author FROM articles "
            "WHERE title LIKE %s",
            (f"%{MARKER_TITLE}%",),
        )
        marked = cur.fetchall()
        print(f"Currently encrypted articles: {len(marked)}")

        SNAPSHOT_FILE.write_text(
            json.dumps(marked, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"Snapshot saved: {SNAPSHOT_FILE}")

        print("Scanning dumps for original versions...")
        origins = load_dump_origins()
        print(f"Clean versions found in dumps: {len(origins)}")

        restored, missing = 0, []
        for row in marked:
            aid = row["id"]
            rec = origins.get(aid)
            if not rec:
                missing.append(aid)
                continue
            cur.execute(
                "UPDATE articles SET title=%s, content_text=%s, summary=%s, author=%s "
                "WHERE id=%s AND title LIKE %s",
                (
                    rec.get("title") or row["title"],
                    rec.get("content_text") or "",
                    rec.get("summary"),
                    rec.get("author"),
                    aid,
                    f"%{MARKER_TITLE}%",
                ),
            )
            restored += 1
        conn.commit()
        print(f"Restored: {restored}  Missing original: {len(missing)}")
        if missing:
            print("Missing ids:", missing[:50], "..." if len(missing) > 50 else "")

    # Reset vault state + drop useless backup records
    session = SessionLocal()
    try:
        state = session.query(EmergencyVaultState).first()
        if state:
            state.is_locked = False
            state.auto_lockdown_enabled = False
            state.emergency_unlock_code_hash = None
            state.emergency_unlock_code_hint = None
            state.threat_status = "NORMAL"
            state.current_threat_score = 12
            state.threat_summary = (
                "স্বাভাবিক: সকল ডাটা পুনরুদ্ধার করা হয়েছে এবং এনক্রিপশন ফিচার বাতিল করা হয়েছে।"
            )
            state.encrypted_articles_count = 0
            state.encrypted_configs_count = 0
            state.locked_at = None
            state.failed_unlock_attempts = 0
        n = session.query(EncryptedVaultBackupRecord).delete()
        session.commit()
        print(f"Vault state reset; {n} stale backup records deleted.")
    finally:
        session.close()
    conn.close()


if __name__ == "__main__":
    main()
