import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional
import pymysql
from rich.console import Console
from rich.table import Table

from config.settings import settings
from src.storage.database import init_db

console = Console()

TABLE_ORDER = [
    "users",
    "site_configs",
    "polls",
    "poll_options",
    "poll_votes",
    "newsletter_subscribers",
    "blocked_ips",
    "blocked_countries",
    "security_threat_logs",
    "advertisements",
    "scrape_logs",
    "articles",
    "article_images",
    "article_likes",
    "article_block_ledger",
    "editorial_audit_logs",
]

JSON_COLUMNS = {
    "site_configs": ["value"],
    "articles": ["extracted_entities", "missing_fields"],
    "editorial_audit_logs": ["details"],
}

DATETIME_COLUMNS = {
    "users": ["created_at"],
    "site_configs": ["updated_at"],
    "polls": ["created_at"],
    "poll_votes": ["created_at"],
    "newsletter_subscribers": ["subscribed_at"],
    "blocked_ips": ["expires_at", "created_at"],
    "blocked_countries": ["created_at"],
    "security_threat_logs": ["created_at"],
    "advertisements": ["start_date", "end_date", "created_at"],
    "scrape_logs": ["start_time", "end_time"],
    "articles": ["published_at", "scheduled_at", "created_at", "updated_at"],
    "article_images": ["created_at"],
    "article_likes": ["created_at"],
    "article_block_ledger": ["timestamp", "created_at"],
    "editorial_audit_logs": ["created_at"],
}

BOOLEAN_COLUMNS = {
    "users": ["is_active"],
    "polls": ["is_active"],
    "newsletter_subscribers": ["is_active"],
    "blocked_countries": ["is_active"],
    "advertisements": ["is_active"],
    "articles": ["js_rendered", "is_featured", "is_breaking", "is_ledger_verified"],
    "article_images": ["is_lead_image"],
}


def parse_datetime(val: Any) -> Optional[datetime]:
    """Parse string or timestamp into Python datetime."""
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, (int, float)):
        return datetime.utcfromtimestamp(val)
    if isinstance(val, str):
        val = val.strip()
        # Try standard formats
        for fmt in (
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
    return None


def transform_value(table_name: str, col_name: str, val: Any) -> Any:
    """Clean and normalize value for MySQL insertion."""
    if val is None:
        return None

    # Handle JSON columns
    if col_name in JSON_COLUMNS.get(table_name, []):
        if isinstance(val, (dict, list)):
            return json.dumps(val, ensure_ascii=False)
        if isinstance(val, str):
            val = val.strip()
            if not val:
                return None
            try:
                # Validate it parses as JSON and re-dump
                parsed = json.loads(val)
                return json.dumps(parsed, ensure_ascii=False)
            except Exception:
                return json.dumps(val, ensure_ascii=False)
        return json.dumps(val, ensure_ascii=False)

    # Handle Datetime columns
    if col_name in DATETIME_COLUMNS.get(table_name, []):
        return parse_datetime(val)

    # Handle Boolean columns
    if col_name in BOOLEAN_COLUMNS.get(table_name, []):
        if isinstance(val, bool):
            return 1 if val else 0
        if isinstance(val, (int, float)):
            return 1 if val != 0 else 0
        if isinstance(val, str):
            return 1 if val.lower() in ("1", "true", "yes", "t") else 0
        return 0

    return val


def migrate(sqlite_db_path: Path) -> bool:
    """Perform full data migration from SQLite to MySQL."""
    console.print(f"[bold cyan]> Step 1: Initializing MySQL Database ({settings.DB_NAME})...[/bold cyan]")
    init_db()

    if not sqlite_db_path.exists():
        console.print(f"[bold red]SQLite database not found at {sqlite_db_path}![/bold red]")
        return False

    console.print(f"[bold cyan]> Step 2: Connecting to SQLite ({sqlite_db_path}) & MySQL ({settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME})...[/bold cyan]")
    
    sqlite_conn = sqlite3.connect(str(sqlite_db_path))
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cur = sqlite_conn.cursor()

    mysql_conn = pymysql.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
        charset="utf8mb4",
        autocommit=False,
    )
    mysql_cur = mysql_conn.cursor()

    try:
        console.print("[yellow]Disabling MySQL Foreign Key Checks for migration...[/yellow]")
        mysql_cur.execute("SET FOREIGN_KEY_CHECKS = 0;")
        mysql_cur.execute("SET SQL_MODE = 'NO_AUTO_VALUE_ON_ZERO';")

        report_rows = []

        for table in TABLE_ORDER:
            # Check if table exists in SQLite
            sqlite_cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            )
            if not sqlite_cur.fetchone():
                console.print(f"[dim]Skipping {table} (not in SQLite)[/dim]")
                continue

            # Fetch columns and data from SQLite
            sqlite_cur.execute(f"PRAGMA table_info({table})")
            cols_info = sqlite_cur.fetchall()
            col_names = [r["name"] for r in cols_info]

            sqlite_cur.execute(f"SELECT * FROM `{table}`")
            rows = sqlite_cur.fetchall()
            src_count = len(rows)

            # Clear destination table in MySQL
            mysql_cur.execute(f"TRUNCATE TABLE `{table}`;")

            if src_count > 0:
                cols_joined = ", ".join(f"`{c}`" for c in col_names)
                placeholders = ", ".join(["%s"] * len(col_names))
                insert_sql = f"INSERT INTO `{table}` ({cols_joined}) VALUES ({placeholders})"

                batch_data = []
                for row in rows:
                    row_dict = dict(row)
                    transformed_row = [
                        transform_value(table, col, row_dict.get(col))
                        for col in col_names
                    ]
                    batch_data.append(transformed_row)

                # Batch insert into MySQL
                mysql_cur.executemany(insert_sql, batch_data)

            mysql_conn.commit()

            # Verify count in MySQL
            mysql_cur.execute(f"SELECT COUNT(*) FROM `{table}`;")
            dst_count = mysql_cur.fetchone()[0]

            status = "[OK] MATCH" if src_count == dst_count else "[FAIL] MISMATCH"
            report_rows.append((table, src_count, dst_count, status))
            console.print(f"  [green][OK][/green] Migrated [bold]{table}[/bold]: {dst_count}/{src_count} records transferred.")

        console.print("[yellow]Re-enabling MySQL Foreign Key Checks...[/yellow]")
        mysql_cur.execute("SET FOREIGN_KEY_CHECKS = 1;")
        mysql_conn.commit()

        # Display Final Summary Table
        table_summary = Table(title="SQLite to MySQL Migration Verification", border_style="cyan")
        table_summary.add_column("Table Name", style="bold white")
        table_summary.add_column("SQLite Rows", style="yellow", justify="right")
        table_summary.add_column("MySQL Rows", style="green", justify="right")
        table_summary.add_column("Status", style="bold cyan")

        all_ok = True
        for tbl, s_cnt, m_cnt, stat in report_rows:
            table_summary.add_row(tbl, str(s_cnt), str(m_cnt), stat)
            if s_cnt != m_cnt:
                all_ok = False

        console.print("\n", table_summary)

        if all_ok:
            console.print("\n[bold green]Full Data Migration completed successfully with 100% integrity![/bold green]\n")
            return True
        else:
            console.print("\n[bold red]Some tables had row count mismatches. Please verify.[/bold red]\n")
            return False

    except Exception as e:
        mysql_conn.rollback()
        console.print(f"[bold red]Migration error: {e}[/bold red]")
        import traceback
        traceback.print_exc()
        return False
    finally:
        sqlite_conn.close()
        mysql_conn.close()


if __name__ == "__main__":
    db_path = settings.DB_DIR / "news_pipeline.db"
    if len(sys.argv) > 1:
        db_path = Path(sys.argv[1])
    success = migrate(db_path)
    if not success:
        sys.exit(1)
