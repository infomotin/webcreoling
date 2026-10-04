# AGENTS.md — WebCreoling local session knowledge

Last deep-dive: 2026-10-04. Read this before touching the repo.

## What this is

Bangla news platform: scraper → MySQL storage → CPU LLM training/LoRA → Flask newsroom portal.
~30k LOC Python across `src/` (100 modules). Not the toy pipeline the README describes —
the README is outdated (still documents a Typer-only CLI + SQLite); the real product is a
Flask CMS with RBAC, WAF, blockchain ledger, scheduler and agent approvals.

## Run it

```bash
# prerequisites: Laragon MySQL running (root/toor, db `ai_news`), .venv present
.venv/Scripts/python.exe src/web/app.py          # dev server http://127.0.0.1:8080
.venv/Scripts/python.exe -m src.cli serve-web    # same, via Typer
.venv/Scripts/python.exe -m pytest -q            # 266 tests, ~2 min, green
```

`create_app()` (`src/web/app.py:56`) auto-runs `init_db()` + seeds. Scheduler starts inside
it unless `TESTING`/`PYTEST_CURRENT_TEST`.

Login: `admin/admin123`, `editor/editor123`, `analyst/analyst123`, `viewer/viewer123`.

## Environment

- `config/settings.py` — pydantic-settings over `.env` (`extra="ignore"`). Importing it creates dirs.
- **`DATABASE_URL` is mandatory** — `src/storage/database.py:60` raises without it.
- `.env` → `mysql+pymysql://root:toor@localhost:3306/ai_news`. Tests use in-memory SQLite, not this.
- `FLASK_DEBUG` in `.env` is dead — code reads `settings.DEBUG`.
- `FLASK_SECRET_KEY` setting is unused; secret is generated to `data/instance/secret_key`.
- SQLite fallback: `sqlite:///data/db/webcreoling.db` (CWD-relative). Legacy file
  `data/db/news_pipeline.db` is referenced by telemetry code but is not the active DB.

## Architecture map

| Layer | Location | Notes |
|---|---|---|
| Flask app factory | `src/web/app.py` | 15 blueprints registered at `:257-288`; WAF `:126`, CSRF-origin guard `:135`, headers `:155`, i18n `:171`, scheduler `:298` |
| Auth/RBAC | `src/web/auth.py` | session cookies, no Flask-Login. `login_required`, `roles_required` (admin bypasses all) |
| WAF | `src/web/security.py` | SQLi/XSS/traversal/RCE regex, 3 strikes/15min → 24h auto-ban, IP/country blocklist from DB |
| Rate limit | `src/web/ratelimit.py` | in-process fixed window |
| Routes | `src/web/routes/*.py` | `admin_bp` 2026L, `scraper_bp` 810L, `training_bp` 719L, `portal_bp` public |
| Models | `src/storage/models.py` | 39 tables; custom `DateTime` TypeDecorator → naive-UTC |
| Repos | `src/storage/repositories.py` | 4015L; `ArticleRepository.upsert_article:252`, `search_fts:396` |
| Schema init | `src/storage/database.py:134 init_db()` | create_all + additive ALTERs + indexes + SQLite-only FTS5 (`:220`) |
| Scraper | `src/scraper/` | engine/pipeline/js_renderer/parsers; `social_world_ingestion.py` 1429L; mock portal for offline E2E |
| Scheduler | `src/automation/scheduler.py` | thread singleton, 12 default jobs, 2s tick, per-job daemon thread |
| One-shot tasks | `src/automation/task_manager.py` | ThreadPoolExecutor(4), progress reported over HTTP |
| AI pilot | `src/automation/ai_pilot_brain.py` | ingest → rewrite → credibility → gate → publish |
| Auto-scroller | `src/automation/auto_scroller.py` | 0.98 similarity dedup, 70% truth gate, links (never merges) |
| LLM gateway | `src/integrations/llm_service.py` | Ollama default, degrades to `None` → rule-based, never hard-fails |
| NLP | `src/nlp/` | synthesizer (95% fact retention), fake-news detector, semantic fidelity (0.98) |
| Training | `src/training/`, `src/finetuning/` | CPU-only, LoRA 4 tasks, GGUF manifest |
| Chat/RAG | `src/chat/` | FTS5 retrieval + intent router |
| CLI | `src/cli.py` | 17 Typer commands (`setup-db`, `serve-web`, `run-pipeline`, `run-automation`, …) |
| Pipeline | `src/pipeline.py` | 7-stage E2E; `scripts/run_demo.py` runs it with mock portal |

## Conventions

- DB access only via `with get_db_session() as s:` (commits/rollbacks/closes).
- Logging via `src/common/logger.py get_logger()`; Rich console + rotating file (`logs/webcreoling.log`).
- i18n: `t(key)` / `tr(bn, en)` from `src/common/i18n.py`; default lang `bn`.
- Public content must pass `is_public_article()` / `apply_public_content_filter()`
  (`src/storage/repositories.py:87,99`) — locked/vault rows must never surface.
- Tests: pytest, `tests/` only (`pyproject.toml` `testpaths`), in-memory SQLite fixtures in
  `tests/conftest.py`. `test/test_deployment.py` is NOT collected.

## Known issues (verified, unfixed)

1. `src/web/routes/admin_bp.py:1924` calls `scheduler.update_job_interval()` — method does not
   exist (`update_job()` does) → `POST /admin/automation/update-interval/<id>` 500s.
2. `admin_bp.py:714,769` duplicate URL rules from `:511,:555` — later pair is dead code.
3. `scheduler.get_status():665` success-rate formula can go negative.
4. `apscheduler` in `requirements.txt` but absent from `pyproject.toml` deps.
5. `POST /chat/api/message` is unauthenticated while `/chat` page requires admin/editor.
6. Three different DB filenames in code (`webcreoling.db`, `news_pipeline.db`, `news.db`).
7. No CSP — templates use inline JS (`app.py:151`).

## Docs

`README.md` (outdated pipeline/CLI sections), `DEPLOYMENT.md` + `docs/DEPLOYMENT.md`,
`deployment.sh` (gunicorn/nginx). Site config: `config/sites_config.yaml`.
