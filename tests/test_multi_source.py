"""
Tests for the Multi-Source scraper (HTML / RSS / NewsAPI / Guardian) with
per-source exponential backoff + skip-and-continue, embedding-based semantic
fidelity scoring, related-article dedup linking (kept separate, never merged),
and the dual-strategy fact-checker.
"""

import pytest

from src.scraper.multi_source import (
    DEFAULT_CONFIG,
    MultiSourceScraper,
    SourceFetchError,
    fetch_with_retry,
)
from src.nlp.semantic_fidelity import SemanticFidelity
from src.automation.fact_checker import FactCheckService
from src.storage.database import get_db_session


# ---------------------------------------------------------------------------
# Retry / backoff / skip-and-continue
# ---------------------------------------------------------------------------

def test_fetch_with_retry_uses_exponential_backoff_then_succeeds():
    attempts = {"n": 0}
    sleeps = []

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise SourceFetchError(f"attempt {attempts['n']} failed")
        return [{"title": "ok"}]

    res = fetch_with_retry(flaky, max_retries=3, backoff_base=2.0,
                           sleep=sleeps.append, label="flaky")
    assert res["ok"] is True
    assert res["attempts"] == 3
    assert sleeps == [2.0, 4.0]  # 2 * 2^0, 2 * 2^1 — exponential backoff


def test_fetch_with_retry_exhausts_and_skips_source():
    attempts = {"n": 0}
    sleeps = []

    def always_fails():
        attempts["n"] += 1
        raise SourceFetchError("down")

    res = fetch_with_retry(always_fails, max_retries=3, backoff_base=1.0,
                           sleep=sleeps.append, label="dead-source")
    assert res["ok"] is False
    assert res["skipped"] is True
    assert res["attempts"] == 3
    assert len(sleeps) == 2  # no sleep after the final attempt


def test_run_cycle_continues_with_remaining_sources_after_skip():
    """A source that exhausts retries is skipped; the healthy source still runs."""
    good_source = {"key": "good", "name": "Good", "type": "rss",
                   "url": "http://good.test/rss", "enabled": True,
                   "max_retries": 3, "backoff_base": 0.0, "max_items": 2}
    bad_source = {"key": "bad", "name": "Bad", "type": "rss",
                  "url": "http://bad.test/rss", "enabled": True,
                  "max_retries": 2, "backoff_base": 0.0, "max_items": 2}

    RSS_XML = b"""<?xml version="1.0"?><rss version="2.0"><channel>
      <title>Good Feed</title>
      <item><title>Story One</title><link>http://good.test/s1</link>
            <description>Body of the first story about the election.</description></item>
      <item><title>Story Two</title><link>http://good.test/s2</link>
            <description>Body of the second story about the budget.</description></item>
    </channel></rss>"""

    class FakeResp:
        ok = True
        status_code = 200
        content = RSS_XML

    def http_get(url, headers=None, timeout=15, params=None):
        if "bad" in url:
            raise ConnectionError("host unreachable")
        return FakeResp()

    ingested = []

    def fake_ingest(**kwargs):
        ingested.append(kwargs["source_url"])
        return {"success": True, "status": "queued"}

    summary = MultiSourceScraper.run_cycle(
        sources=[bad_source, good_source],
        http_get=http_get,
        sleep=lambda s: None,
        ingest=fake_ingest,
        max_items=10,
    )

    assert summary["sources_failed"] == 1
    assert summary["sources_ok"] == 1
    assert summary["skipped_sources"][0]["key"] == "bad"
    assert summary["skipped_sources"][0]["attempts"] == 2
    # Good source continued despite the bad one
    assert summary["fetched"] == 2
    assert len(ingested) == 2


def test_rss_items_are_normalized():
    RSS_XML = b"""<?xml version="1.0"?><rss version="2.0"><channel>
      <title>Wire</title>
      <item><title>Headline A</title><link>http://a.test/1</link>
            <description>&lt;p&gt;Paragraph with &lt;b&gt;html&lt;/b&gt; tags.&lt;/p&gt;</description>
            <author>reporter@wire.test</author></item>
    </channel></rss>"""

    class FakeResp:
        ok = True
        content = RSS_XML

    source = {"key": "x", "name": "Wire", "type": "rss", "url": "http://x/rss",
              "category": "world"}
    items = MultiSourceScraper._fetch_rss(source, lambda *a, **k: FakeResp(), timeout=5)
    assert len(items) == 1
    assert items[0]["title"] == "Headline A"
    assert items[0]["source_url"] == "http://a.test/1"
    assert "html" in items[0]["content"] and "<b>" not in items[0]["content"]
    assert items[0]["source_name"] == "Wire"


def test_newsapi_requires_key_and_parses_articles(monkeypatch):
    source = {"key": "na", "name": "NewsAPI", "type": "newsapi",
              "url": "https://newsapi.org/v2/top-headlines"}

    # No key configured -> SourceFetchError (retry/skip path)
    with pytest.raises(SourceFetchError):
        MultiSourceScraper._fetch_newsapi(
            source, lambda *a, **k: None, timeout=5
        )

    monkeypatch.setattr("config.settings.settings.NEWSAPI_API_KEY", "test-key", raising=False)

    class FakeResp:
        def json(self):
            return {"status": "ok", "articles": [
                {"title": "API Story", "url": "http://api.test/1",
                 "description": "desc", "content": "more",
                 "source": {"name": "WireSvc"}, "author": "Journo",
                 "urlToImage": "http://img/1.jpg", "publishedAt": "2026-01-01T00:00:00Z"}
            ]}

    captured = {}

    def http_get(url, headers=None, timeout=15, params=None):
        captured.update({"url": url, "headers": headers, "params": params})
        return FakeResp()

    items = MultiSourceScraper._fetch_newsapi(source, http_get, timeout=5)
    assert captured["params"]["apiKey"] == "test-key"
    assert items[0]["title"] == "API Story"
    assert items[0]["source_name"] == "WireSvc"


def test_guardian_parses_results(monkeypatch):
    monkeypatch.setattr("config.settings.settings.GUARDIAN_API_KEY", "g-key", raising=False)
    source = {"key": "gu", "name": "Guardian", "type": "guardian",
              "url": "https://content.guardianapis.com/search"}

    class FakeResp:
        def json(self):
            return {"response": {"results": [
                {"webTitle": "World Story", "webUrl": "http://g.test/1",
                 "webPublicationDate": "2026-01-02",
                 "fields": {"body": "<p>Long body</p>", "byline": "By A. Reporter",
                            "thumbnail": "http://img/g.jpg"}}
            ]}}

    items = MultiSourceScraper._fetch_guardian(source, lambda *a, **k: FakeResp(), timeout=5)
    assert items[0]["title"] == "World Story"
    assert items[0]["author"] == "By A. Reporter"
    assert "Long body" in items[0]["content"]


def test_default_sources_seeded_with_types():
    types = {s["type"] for s in DEFAULT_CONFIG["sources"]}
    assert {"rss", "html", "newsapi", "guardian"} <= types
    assert 2 <= DEFAULT_CONFIG["hours_between_runs"] <= 4  # spec: every 2-4 hours


# ---------------------------------------------------------------------------
# Semantic fidelity (embedding-based, 98% target)
# ---------------------------------------------------------------------------

def test_semantic_fidelity_embedding_path_hits_target(monkeypatch):
    vec = [1.0, 0.0, 0.5]
    monkeypatch.setattr("src.nlp.semantic_fidelity.embed_text", lambda t: vec)
    res = SemanticFidelity.measure("original text", "rewritten text")
    assert res["method"] == "embedding"
    assert res["score"] == 1.0
    assert res["passed"] is True
    assert res["embedding_threshold"] == 0.98


def test_semantic_fidelity_embedding_below_target_is_flagged(monkeypatch):
    calls = {"n": 0}

    def fake_embed(t):
        calls["n"] += 1
        return [1.0, 0.0] if calls["n"] == 1 else [0.0, 1.0]  # orthogonal

    monkeypatch.setattr("src.nlp.semantic_fidelity.embed_text", fake_embed)
    res = SemanticFidelity.measure("original", "rewrite")
    assert res["method"] == "embedding"
    assert res["score"] == 0.0
    assert res["passed"] is False


def test_semantic_fidelity_lexical_fallback_when_llm_down(monkeypatch):
    monkeypatch.setattr("src.nlp.semantic_fidelity.embed_text", lambda t: None)
    original = "বাংলাদেশের অর্থনীতি এই বছর দ্রুত প্রসার পেয়েছে অনেক বিশ্লেষকের মতে"
    rewrite = "অনেক বিশ্লেষকের মতে বাংলাদেশের অর্থনীতি এই বছর দ্রুত প্রসার পেয়েছে"
    res = SemanticFidelity.measure(original, rewrite)
    assert res["method"] == "lexical_fallback"
    assert res["score"] >= 0.60
    assert res["passed"] is True


# ---------------------------------------------------------------------------
# Dedup: separate entries + related_articles links (never merged)
# ---------------------------------------------------------------------------

def test_near_duplicate_articles_are_linked_not_merged():
    from src.storage.models import Article
    from src.automation.dedup import link_related_articles, get_article_relations

    base = ("নতুন বাজেট প্রস্তাব সংসদে উপস্থাপন "
            "অর্থমন্ত্রী বলেছেন দেশের অর্থনীতি সুস্থ পথে চলছে এবং কর ব্যবস্থা উন্নত হবে")
    with get_db_session() as session:
        a1 = Article(url="https://dup.test/a1", source="SourceA", title="বাজেট প্রস্তাব",
                     content_text=base, scrape_status="completed")
        a2 = Article(url="https://dup.test/a2", source="SourceB", title="বাজেট প্রস্তাব (সংবাদ)",
                     content_text=base + " সূত্র জানায়।", scrape_status="completed")
        session.add_all([a1, a2])
        session.flush()

        created = link_related_articles(session, a1, threshold=0.90)
        session.flush()
        assert created, "expected a relation link"
        rel = created[0]
        assert 0.90 <= rel.similarity_score <= 1.0
        assert rel.relation_type in ("duplicate", "near_duplicate")
        assert rel.source_metadata["source_b"] == "SourceB"
        assert rel.source_metadata["url_b"] == "https://dup.test/a2"
        assert rel.source_metadata["detected_at"]

        # Both entries still exist separately (never merged)
        assert session.query(Article).filter(Article.url.in_(
            ["https://dup.test/a1", "https://dup.test/a2"])).count() == 2

        rels = get_article_relations(session, a1.id)
        assert any(r["related_article_id"] == a2.id for r in rels)

        # Idempotent: running again creates no duplicate links
        again = link_related_articles(session, a1, threshold=0.90)
        assert again == []
        session.rollback()


def test_raw_duplicate_items_are_kept_and_linked(monkeypatch):
    from src.storage.models import RawNewsItem
    from src.automation.auto_scroller import AutoScroller

    body = "জাতীয় সংসদের বিশেষ অধিবেশনে গুরুত্বপূর্ণ প্রস্তাব উপস্থাপন করা হয়েছে আজ।"
    with get_db_session() as session:
        first = RawNewsItem(source_url="https://rawdup.test/1", title_raw="শিরোনাম এক",
                             content_raw=body, status="queued")
        session.add(first)
        session.flush()

        res = AutoScroller.ingest_raw_item(
            source_url="https://rawdup.test/2",
            title="শিরোনাম এক",
            content=body,
            source_name="Wire",
            session=session,
        )
        assert res["status"] == "duplicate"
        assert res["linked"] is True
        second_id = res["item_id"]

        # Duplicate KEPT as its own row (not merged/deleted)
        dup = session.query(RawNewsItem).filter(RawNewsItem.id == second_id).first()
        assert dup is not None
        assert dup.status == "duplicate"
        assert dup.duplicate_of_url == "https://rawdup.test/1"
        session.rollback()


# ---------------------------------------------------------------------------
# Fact-checking: dual strategy
# ---------------------------------------------------------------------------

def test_cross_source_check_corroborates_known_story():
    from src.storage.models import Article
    claim_title = "ঢাকায় ভয়াবহ অগ্নিকাণ্ড চিকিৎসালয়ে ২০ জন আহত"
    claim_body = ("রাজধানীর মিরপুরে একটি চিকিৎসালয়ে আজ ভোরে ভয়াবহ অগ্নিকাণ্ড হয়েছে। "
                  "অগ্নিনির্বাপকের তথ্যে জানা গেছে ২০ জন আহত হয়েছেন।")
    with get_db_session() as session:
        for i, src in enumerate(["WireA", "WireB", "WireC"]):
            session.add(Article(
                url=f"https://fcsource.test/{i}", source=src,
                title=claim_title,
                content_text=claim_body + f" ({src} প্রতিবেদন)",
                scrape_status="completed",
            ))
        session.flush()
        res = FactCheckService.cross_source_check(claim_title, claim_body, session=session)
        assert res["available"] is True
        assert res["corroborating_count"] >= 2
        assert len(res["distinct_sources"]) >= 2
        assert res["confidence"] >= 60.0
        session.rollback()


def test_dual_strategy_external_disabled_graceful():
    """External API disabled by default -> cross-source only, no crash."""
    res = FactCheckService.full_check("কোনো খবর", "এই খবরের পূর্ণ পাঠ এখানে লেখা হয়েছে।")
    assert res["strategy"] in ("cross_source_only", "error")
    assert res["external"]["available"] is False
    assert isinstance(res["combined_confidence"], (int, float))
    assert isinstance(res["flags"], list)
