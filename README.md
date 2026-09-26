# WebCreoling: End-to-End Bangla News Scraping & CPU-Optimized AI Pipeline

A production-grade, modular system engineered for scraping Bangla-language newspaper portals, storing structured records & deduplicated images in SQLite, training lightweight language models on CPU, applying hybrid multi-task LoRA fine-tuning (Categorization, Headline Generation, Summarization, NER), and providing an interactive RAG-powered chat interface.

---

## Architecture Overview

```mermaid
flowchart TD
    subgraph Scraper ["1. Web Scraper Module (Bangla Portals)"]
        Config[sites_config.yaml\nProthom Alo, Daily Star, BBC Bangla, etc.] --> Crawler[Async / Selenium Crawler Engine]
        Crawler --> JSStrat{JS Rendering Strategy\n(Static BS4 / Selenium / Hybrid / Skip)}
        JSStrat --> MultiSelector[Multi-Selector Fallback:\nCSS -> JSON-LD -> OpenGraph -> Heuristics]
        MultiSelector --> RetryLoop[3-Attempt Exponential Backoff Retry]
        RetryLoop --> MediaMgr[Media Downloader & SHA-256 Deduplication]
    end

    subgraph Storage ["2. Data Storage Layer (SQLite + FTS5)"]
        MultiSelector --> SQLiteDB[(SQLite Database\narticles, article_images, scrape_logs)]
        MediaMgr --> LocalImages[(Local Media Store:\ndata/images/source/YYYY-MM/hash.ext)]
        SQLiteDB --- FTS5[SQLite FTS5 Full-Text Search Virtual Index]
    end

    subgraph Training ["3. Text Preprocessing & Base Training (CPU)"]
        SQLiteDB --> Normalizer[Bangla Unicode Normalizer & Boilerplate Stripper]
        Normalizer --> DatasetBuilder[Train / Validation / Test Dataset Splits]
        DatasetBuilder --> BaseTrainer[CPU Causal LM Trainer (distilgpt2 / SmolLM / Qwen)]
        BaseTrainer --> BaseCheckpoint[Base Checkpoint]
    end

    subgraph FineTuning ["4. Hybrid Multi-Task Fine-Tuning"]
        BaseCheckpoint --> LoRATuner[Single Base Model + Multi-Task LoRA Adapters]
        LoRATuner --> T1[Skill 1: Article Categorization]
        LoRATuner --> T2[Skill 2: Headline Generation]
        LoRATuner --> T3[Skill 3: Content Summarization]
        LoRATuner --> T4[Skill 4: Named Entity Recognition]
        LoRATuner --> Evaluator[Multi-Task Evaluator (ROUGE, BLEU, F1, Accuracy)]
        LoRATuner --> FinalModel[Final Specialized Checkpoint & llama.cpp GGUF Manifest]
    end

    subgraph Chat ["5. Hybrid RAG & Task Chat Interface"]
        UserMsg[User Message] --> IntentRouter{Intent Classifier}
        IntentRouter -->|Conversational Q&A| RAGRetriever[FTS5 SQLite Search -> Top-K Context]
        RAGRetriever --> RAGPrompt[Grounded RAG Prompt]
        IntentRouter -->|Explicit Command| TaskPrompt[Specialized Task Prefix]
        RAGPrompt --> InferenceEngine[CPU Inference Engine (LoRA / llama.cpp)]
        TaskPrompt --> InferenceEngine
        InferenceEngine --> AuditLog[(Audit Log: data/chat_history.jsonl)]
        InferenceEngine --> UI[Rich Formatted Terminal Output with Citations]
    end
```

---

## Key Features

1. **Bangla Web Scraper Module**:
   - Supports major portals: **Prothom Alo, The Daily Star (Bangla), BBC Bangla, Dhaka Post**, and arbitrary news sites.
   - **Per-Site JavaScript Rendering**: Configurable modes (`bs4_only`, `selenium_only`, `hybrid`, `skip`).
   - **Exclusion & CAPTCHA Rules**: Skips paywalled, login-required, or CAPTCHA-protected sites automatically based on configuration.
   - **3-Attempt Exponential Backoff Retry**: If text or images are missing, retries with alternative selectors and Selenium rendering before persisting available fields with null/empty placeholders (ensuring zero data loss).
   - **Polite Rate Limiting**: Per-domain token bucket delays with randomized jitter and robots.txt compliance.

2. **Data Storage & Media Management**:
   - **SQLite Database with WAL mode**: Configured with `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL` for high-throughput concurrency.
   - **SQLite FTS5 Full-Text Search**: Automatic triggers maintain real-time full-text indexing for rapid RAG article retrieval.
   - **Image Deduplication**: Downloads, verifies, and stores images in `data/images/<source>/<YYYY-MM>/<sha256>.<ext>`, deduplicating identical files by SHA-256 byte hash.

3. **CPU-Optimized LLM Pipeline**:
   - **Bangla Text Normalizer**: Handles Unicode NFC normalization, zero-width spaces/non-joiners (`\u200c`, `\u200d`, `\u200b`), Bengali digits, and boilerplate removal.
   - **CPU-Friendly Base Models**: Default architectures (`distilgpt2`, `HuggingFaceTB/SmolLM2-135M`, `Qwen/Qwen2.5-0.5B`) configured for fast multi-threaded execution without CUDA dependencies.
   - **llama.cpp / GGUF Export**: Generates export manifests and quantization commands for native C++ inference.

4. **Hybrid Multi-Task Fine-Tuning (4 Specialized Skills)**:
   - Utilizes **one single base model** with low-rank parameter-efficient adapters (**LoRA**) covering:
     1. **Article Categorization**: Classifies news into politics, sports, business, technology, international, etc.
     2. **Headline Generation**: Generates punchy, relevant Bangla headlines from body text.
     3. **Content Summarization**: Creates concise summaries from full articles.
     4. **Named Entity Recognition (NER)**: Extracts Person, Location, and Organization entities into structured JSON/text.
   - Evaluates performance across ROUGE-1/2/L, BLEU, Categorization Accuracy, and NER F1.

5. **Hybrid Chat Interface (RAG + Explicit Tasks)**:
   - **Conversational RAG Q&A**: Users can ask natural language questions (e.g., *'সংসদে কী আলোচনা হয়েছে?'*); the system retrieves matching article records via FTS5 and grounds model answers with citations and image previews.
   - **Explicit Task Commands**: Direct commands (`categorize this article: ...`, `generate a headline for this: ...`, `summarize this: ...`, `extract entities from this: ...`).
   - **Audit Logging**: Persists all user queries, retrieved IDs, model completions, and latencies into `data/chat_history.jsonl`.

---

## Directory Structure

```
webcreoling/
├── pyproject.toml              # Project metadata & dependency definitions
├── requirements.txt            # Dependency lock / installation list
├── config/
│   ├── settings.py             # Pydantic v2 application settings
│   └── sites_config.yaml       # Per-site rules, selectors, JS modes, exclusions
├── data/
│   ├── db/                     # SQLite database file (news_pipeline.db)
│   ├── images/                 # SHA-256 deduplicated image storage (data/images/<source>/<YYYY-MM>/...)
│   ├── processed/              # Tokenized Hugging Face dataset splits
│   ├── checkpoints/            # Base checkpoints, LoRA adapters, evaluation reports
│   └── chat_history.jsonl      # Audit trail for all chat interactions
├── src/
│   ├── common/
│   │   ├── logger.py           # Structured logger (Rich console + rotating file log)
│   │   ├── normalizer.py       # Bangla Unicode normalizer & text sanitizer
│   │   └── utils.py            # SHA-256 calculation, date parsing, filesystem helpers
│   ├── storage/
│   │   ├── database.py         # SQLAlchemy 2.0 SQLite engine, WAL mode, FTS5 triggers
│   │   ├── models.py           # Article, ArticleImage, ScrapeLog ORM models
│   │   ├── repositories.py     # ArticleRepository, FTS5 queries, batch dataset exports
│   │   └── media_manager.py    # Image downloading, validation & SHA-256 deduplication
│   ├── scraper/
│   │   ├── engine.py           # Crawler engine with rate limiting & pagination
│   │   ├── js_renderer.py      # JS Rendering Manager (bs4_only, selenium_only, hybrid, skip)
│   │   ├── parsers/
│   │   │   ├── base.py         # Abstract parser contract
│   │   │   ├── bangla_portal.py# Multi-selector fallback parser for Bangla portals
│   │   │   └── generic_news.py # Schema.org & OpenGraph generic news parser
│   │   ├── pipeline.py         # Scrape pipeline with 3-attempt exponential backoff
│   │   └── mock_bangla_portal.py # Hermetic mock portal HTTP server for offline testing
│   ├── training/
│   │   ├── preprocessor.py     # Text cleaning & Causal LM formatting
│   │   ├── dataset_builder.py  # SQLite to Hugging Face DatasetDict & Tokenization
│   │   ├── base_trainer.py     # CPU Causal LM trainer with checkpoint saving
│   │   └── llama_cpp_exporter.py # GGUF export & quantization manifest generator
│   ├── finetuning/
│   │   ├── tasks.py            # 4 Task definitions & prompt templates
│   │   ├── hybrid_trainer.py   # Hybrid multi-task LoRA fine-tuning trainer
│   │   └── evaluator.py        # Multi-task evaluator (ROUGE, BLEU, F1, Accuracy)
│   ├── chat/
│   │   ├── rag_engine.py       # SQLite FTS5 context retriever
│   │   ├── task_handlers.py    # Intent classifier & prompt builder
│   │   ├── interface.py        # Interactive CLI & programmatic chat interface
│   │   └── audit_logger.py     # JSONL interaction logger
│   ├── pipeline.py             # One-command sequential pipeline orchestrator
│   └── cli.py                  # Typer CLI application
├── scripts/
│   └── run_demo.py             # Automated end-to-end demo script
└── tests/                      # Pytest unit & integration test suite
```

---

## Installation & Setup

### 1. Environment Setup

```bash
# Clone the repository
cd d:/laragon/www/webcreoling

# Create virtual environment using uv or python venv
uv venv .venv
# Activate virtual environment
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Install dependencies
uv pip install -r requirements.txt
```

### 2. Database Initialization

Initialize the SQLite database with WAL mode and the FTS5 virtual table:

```bash
python -m src.cli setup-db
```

### 3. Web Portal & Background Services

Copy `.env.example` to `.env` and adjust (database, SMTP, LLM, API keys — see below), then:

```bash
# Start the portal (dev server, http://127.0.0.1:8080)
.venv\Scripts\python.exe src\web\app.py

# Run the test suite (unit + integration)
.venv\Scripts\python.exe -m pytest -q
```

The web app creates all missing tables on startup (`init_db`) and starts the built-in
**Automation background scheduler** automatically (thread-based; auto-skipped under
`TESTING` config or pytest). An optional standalone APScheduler runner is
available for deployments that prefer a separate process:

```bash
.venv\Scripts\python.exe -m src.tasks.apscheduler_runner
```

### 4. Scheduled Task Configuration

All jobs live in the `AutomationScheduler` (`src/automation/scheduler.py`) and are
manageable under **অটোমেশন ও শিডিউলার** (`/admin/automation`) — enable/disable, trigger
now, edit interval, batch actions. Defaults:

| Job id | Interval | What it does |
|---|---|---|
| `auto_scroller_cycle` | 900 s (15 min) | Ingest → classify → 0.98 mine → translate → rewrite → AI gate → publish/queue |
| `multi_source_scrape` | 10800 s (3 h) | RSS/HTML/NewsAPI/Guardian fetch with per-source exponential backoff, skip-and-continue |
| `approval_escalation_sweep` | 3600 s | Escalate overdue approval requests to the next senior role; auto-approve by silence when enabled |
| `fact_check_reaudit` | 21600 s (6 h) | Re-run cross-source fact-check on recent articles |

Intervals can be tuned per job in the scheduler config; no cron setup is required.

### 5. Self-Hosted LLM, News APIs & Fact-Checking

* **LLM (local only)** — `LLM_*` env vars (see `.env.example`). Provider `ollama`
  (default, `http://127.0.0.1:11434`) or `openai_compat` for TGI/vLLM. Used for
  rewriting, ad-reply drafting, embeddings and semantic fidelity (0.98 threshold with
  lexical fallback). If the endpoint is down the pipeline degrades gracefully to
  template/rule-based output — never a hard failure.
* **News APIs** — `NEWSAPI_API_KEY`, `GUARDIAN_API_KEY` enable those source types in the
  multi-source scraper (kept disabled when empty). RSS/HTML sources need no key.
* **Fact-checking** — dual strategy: cross-source corroboration against the local DB
  corpus (always on) plus optional external API (`FACTCHECK_*`). External calls stay off
  until a key/URL is configured.

### 6. Agent Workflow Roles & Approval Policy

Public intake routes: `/submissions/ad` (advertiser), `/submissions/news` (external news
tip), `/submissions/reporter` (application), `/reporter` (reporter dashboard posts).
Each intake creates a row in `approval_requests` routed to a senior role:

| Intake | Required role (final say) | Escalates to |
|---|---|---|
| Ad inquiry | `ad_manager` | `admin` |
| News submission / reporter post | `editorial_lead` | `admin` |
| Reporter application | `onboarding_officer` | `admin` |

* Junior reviewers (`editor`, `analyst`) may only **flag** — requests stay pending for
  the senior role; only the required role or `admin` can approve/reject. Rejections by
  juniors never finalize automatically.
* Timeout escalation (default 6 h) and optional approval-by-silence (default 24 h, off)
  are configured in `/agent/policy` (admin) or the `APPROVAL_*` env vars. Every
  decision, escalation, notification and auto-approval is recorded in
  `agent_audit_logs` plus the inline audit trail on the request.
* Creating users with roles `editorial_lead` / `ad_manager` / `onboarding_officer` /
  `reporter` is done by an admin in **Users**; approve a reporter application to
  auto-create a `reporter` account. Inbox UI: `/agent/`.

---

## Configuration Guide (`config/sites_config.yaml`)

You can customize scraping behavior, JS rendering mode, selectors, and rate limits for each site:

```yaml
global_settings:
  user_agent: "Mozilla/5.0 ... WebCreolingNewsBot/1.0"
  default_rate_limit_delay: 1.0
  rate_limit_jitter: 0.5
  max_retries: 3
  backoff_factor: 2.0

sites:
  prothom_alo:
    name: "Prothom Alo"
    domain: "prothomalo.com"
    base_url: "https://www.prothomalo.com"
    js_mode: "hybrid" # 'bs4_only', 'selenium_only', 'hybrid', or 'skip'
    requires_login: false
    has_captcha: false
    enabled: true
    categories:
      - name: "politics"
        url: "https://www.prothomalo.com/politics"
        pagination_pattern: "https://www.prothomalo.com/politics?page={page}"
    selectors:
      article_links: ["a.headline-title", "h2 a", "h3 a"]
      title: ["h1.headline", "h1[itemprop='headline']", "meta[property='og:title']"]
      author: ["span.author-name", "meta[name='author']"]
      published_at: ["time[itemprop='datePublished']", "meta[property='article:published_time']"]
      content: ["div.story-element-text p", "div[itemprop='articleBody'] p", "article p"]
      lead_image: ["meta[property='og:image']", "figure img"]
      article_images: ["article img", "div.content-details img"]

  # Excluded / paywalled site example
  paywalled_site:
    name: "Sample Paywalled Site"
    domain: "example.com"
    js_mode: "skip"
    requires_login: true
    has_captcha: true
    enabled: false
    reason: "Requires subscription login"
```

---

## Execution Guide & CLI Commands

### 1. Run Complete End-to-End Pipeline (One Command)

Executes all stages sequentially: Scrape $\to$ Store $\to$ Base Train $\to$ LoRA Fine-Tune $\to$ Evaluate $\to$ Verify:

```bash
python scripts/run_demo.py
# Or via CLI:
python -m src.cli run-pipeline --use-mock
```

### 2. Scraping Commands

```bash
# Scrape a single article URL with 3-attempt exponential retry:
python -m src.cli scrape-url "https://www.prothomalo.com/politics/article/12345"

# Crawl an entire portal across all configured categories:
python -m src.cli scrape-site prothom_alo --max-pages 3

# View database ingestion statistics:
python -m src.cli db-stats

# Search articles using SQLite FTS5:
python -m src.cli search-db "সংসদ বাজেট" --top-k 3
```

### 3. Training & Fine-Tuning Commands

```bash
# Train lightweight base Causal LM on CPU:
python -m src.cli train-base --epochs 1 --batch-size 2

# Fine-tune base model with hybrid LoRA adapters across all 4 tasks:
python -m src.cli finetune --epochs 2 --batch-size 2

# Run evaluation metrics (ROUGE, BLEU, F1, Accuracy):
python -m src.cli evaluate
```

### 4. Interactive Chat Interface

Launch the interactive terminal chat:

```bash
python -m src.cli chat
```

Inside the chat:
- **Conversational RAG Q&A**: Ask any question in Bengali or English:
  ```
  User > জাতীয় সংসদে কী আলোচনা হয়েছে?
  ```
- **Explicit Task 1: Categorization**:
  ```
  User > categorize this article: মিরপুর শেরেবাংলা স্টেডিয়ামে বাংলাদেশ ৫ উইকেটে জয়ী হয়েছে।
  ```
- **Explicit Task 2: Headline Generation**:
  ```
  User > generate a headline for this: চলতি অর্থবছরে পোশাক শিল্পে রেকর্ড রপ্তানি আয় হয়েছে।
  ```
- **Explicit Task 3: Summarization**:
  ```
  User > summarize this: জাতিসংঘ সাধারণ অধিবেশনে বিশ্বনেতারা জলবায়ু পরিবর্তনের ক্ষয়ক্ষতি কাটিয়ে উঠতে ক্ষতিগ্রস্ত দেশগুলোকে জরুরি সহায়তা প্রদানের প্রস্তাব দিয়েছেন।
  ```
- **Explicit Task 4: Named Entity Recognition**:
  ```
  User > extract entities from this: ঢাকায় প্রধানমন্ত্রী ও স্পিকার জাতীয় সংসদে আলোচনায় অংশ নিয়েছেন।
  ```

---

## Testing

Run the full automated test suite covering scraper, parsers, SQLite schema, FTS5 search, normalizer, training, fine-tuning, and RAG chat:

```bash
python -m pytest -v
```
