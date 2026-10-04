"""Purge demo/seed content from the portal, keeping users + master configuration.

Master data (NEVER touched):
  users, site_configs, subscription_plans, blocked_ips, blocked_countries,
  datacenter_storage_providers, database_replica_nodes, emergency_vault_states,
  ai_brain_custom_rules, social_channel_configs, encrypted_vault_backup_records,
  article_block_ledger row 0 (genesis block).

Demo / content / history data (removed):
  articles and everything hanging off them, raw news staging, social broadcast
  logs, seeded polls + advertisements, newsletter signups, audit & threat logs,
  message/OTP logs, payment + subscription transactions, scrape logs.

Usage:
    .venv/Scripts/python.exe scripts/purge_demo_data.py --dry-run
    .venv/Scripts/python.exe scripts/purge_demo_data.py --yes
    .venv/Scripts/python.exe scripts/purge_demo_data.py --yes --include-images
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text  # noqa: E402

# (table, sql predicate) — children before parents; None == delete every row.
PURGE_PLAN: list[tuple[str, str | None]] = [
    ("article_images", None),
    ("article_comments", None),
    ("article_likes", None),
    ("related_articles", None),
    ("article_block_ledger", "block_number <> 0"),  # keep genesis block
    ("articles", None),
    ("raw_news_item_relations", None),
    ("raw_news_items", None),
    ("social_broadcast_logs", None),
    ("poll_votes", None),
    ("poll_options", None),
    ("polls", None),
    ("advertisements", None),
    ("newsletter_subscribers", None),
    ("approval_requests", None),
    ("agent_audit_logs", None),
    ("ad_inquiries", None),
    ("news_submissions", None),
    ("reporter_applications", None),
    ("editorial_audit_logs", None),
    ("security_threat_logs", None),
    ("message_logs", None),
    ("otp_codes", None),
    ("user_subscriptions", None),
    ("payment_transactions", None),
    ("scrape_logs", None),
    ("datacenter_security_logs", None),
]

# Never in the purge plan — asserted as a safety net.
PROTECTED_TABLES = {
    "users",
    "site_configs",
    "subscription_plans",
    "blocked_ips",
    "blocked_countries",
    "datacenter_storage_providers",
    "database_replica_nodes",
    "emergency_vault_states",
    "ai_brain_custom_rules",
    "social_channel_configs",
    "encrypted_vault_backup_records",
}

PURGE_FILES = [
    "data/chat_history.jsonl",
    "data/notification_history.json",
]


def _count(conn, table: str) -> int:
    return conn.execute(text(f"SELECT COUNT(*) FROM `{table}`")).scalar() or 0


def _table_exists(conn, table: str) -> bool:
    rows = conn.execute(text("SHOW TABLES")).fetchall()
    return table in {r[0] for r in rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="actually delete (otherwise dry run)")
    parser.add_argument("--include-images", action="store_true",
                        help="also wipe data/images/ (files belonging to deleted articles)")
    args = parser.parse_args()

    plan_tables = {t for t, _ in PURGE_PLAN}
    leaked = plan_tables & PROTECTED_TABLES
    if leaked:
        print(f"ABORT: protected tables in purge plan: {sorted(leaked)}")
        return 2

    from config.settings import settings
    from src.storage.database import engine

    print(f"Target: {settings.DATABASE_URL.split('@')[-1]}")
    print(f"Mode:   {'PURGE' if args.yes else 'DRY RUN (pass --yes to delete)'}\n")

    header = f"{'table':34s} {'before':>8s} {'deleted':>8s} {'after':>8s}"
    print(header)
    print("-" * len(header))

    total_deleted = 0
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for table, predicate in PURGE_PLAN:
            if not _table_exists(conn, table):
                print(f"{table:34s} {'(absent)':>8s}")
                continue
            before = _count(conn, table)
            where = f" WHERE {predicate}" if predicate else ""
            sql = f"DELETE FROM `{table}`{where}"
            deleted = 0
            if args.yes and before:
                deleted = conn.execute(text(sql)).rowcount or 0
            after = _count(conn, table)
            total_deleted += deleted
            print(f"{table:34s} {before:>8d} {deleted:>8d} {after:>8d}")
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))

    # Runtime files holding demo content.
    print()
    for rel in PURGE_FILES:
        path = PROJECT_ROOT / rel
        if not path.exists():
            continue
        size = path.stat().st_size
        if args.yes:
            path.unlink()
            print(f"removed file  {rel} ({size} bytes)")
        else:
            print(f"would remove  {rel} ({size} bytes)")

    # Derived media belonging to the deleted articles.
    images_dir = Path(settings.IMAGES_DIR)
    if images_dir.exists():
        entries = list(images_dir.iterdir())
        if args.include_images and args.yes:
            for entry in entries:
                if entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink(missing_ok=True)
            print(f"removed media  data/images/ ({len(entries)} top-level entries)")
        else:
            print(f"would remove  data/images/ ({len(entries)} top-level entries) "
                  f"{'(use --include-images)' if args.yes else ''}")

    print(f"\nTotal rows deleted: {total_deleted}")
    if not args.yes:
        print("Dry run only — nothing was changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
