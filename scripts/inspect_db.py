import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymysql

from config.settings import settings

print('--- SQLITE TABLES & ROW COUNTS ---')
s_conn = sqlite3.connect('data/db/news_pipeline.db')
s_cur = s_conn.cursor()
s_cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = [r[0] for r in s_cur.fetchall()]
for t in tables:
    try:
        s_cur.execute(f'SELECT COUNT(*) FROM "{t}"')
        print(f"{t}: {s_cur.fetchone()[0]} rows")
    except Exception as e:
        print(f"{t}: error {e}")
s_conn.close()

print('\n--- MYSQL ai_news TABLES ---')
m_conn = pymysql.connect(
    host=settings.DB_HOST,
    user=settings.DB_USER,
    password=settings.DB_PASSWORD,
    database=settings.DB_NAME,
    port=settings.DB_PORT,
)
m_cur = m_conn.cursor()
m_cur.execute('SHOW TABLES;')
m_tables = [r[0] for r in m_cur.fetchall()]
print('Existing tables in ai_news:', m_tables)
for t in m_tables:
    m_cur.execute(f'SELECT COUNT(*) FROM `{t}`')
    print(f"{t}: {m_cur.fetchone()[0]} rows")
m_conn.close()
