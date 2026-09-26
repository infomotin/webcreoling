"""Duplicate & near-duplicate linking (never merge).

Keeps duplicate/near-duplicate stories as SEPARATE entries and links them with:
  * similarity_score (0..1)
  * source_metadata (per-side source name, URL, byline, detection method/time)

Applied at two layers:
  * raw staging items  -> RawItemRelation  (pre-publication mining)
  * published articles -> ArticleRelation  (table `related_articles`)
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from src.common.logger import get_logger
from src.storage.models import Article, ArticleRelation, RawItemRelation, RawNewsItem

logger = get_logger("webcreoling.automation.dedup")

DUPLICATE_THRESHOLD = 0.98
NEAR_DUPLICATE_THRESHOLD = 0.90
LINK_SAMPLE_SIZE = 250


def _relation_exists(session, article_id: int, related_id: int) -> bool:
    return (
        session.query(ArticleRelation)
        .filter(
            ArticleRelation.article_id == article_id,
            ArticleRelation.related_article_id == related_id,
        )
        .first()
        is not None
    )


def link_related_articles(
    session,
    article: Article,
    threshold: float = NEAR_DUPLICATE_THRESHOLD,
    sample: int = LINK_SAMPLE_SIZE,
) -> List[ArticleRelation]:
    """Link a (new) article to similar existing articles — both entries are kept."""
    from src.automation.auto_scroller import AutoScroller

    created: List[ArticleRelation] = []
    if not article or not article.id:
        return created

    candidate_text = f"{article.title} {article.content_text or ''}"
    existing = (
        session.query(Article)
        .filter(Article.id != article.id)
        .order_by(Article.id.desc())
        .limit(sample)
        .all()
    )
    for other in existing:
        score = AutoScroller.text_similarity(candidate_text, f"{other.title} {other.content_text or ''}")
        if score < threshold:
            continue
        if _relation_exists(session, article.id, other.id):
            continue
        relation_type = "duplicate" if score >= DUPLICATE_THRESHOLD else "near_duplicate"
        rel = ArticleRelation(
            article_id=article.id,
            related_article_id=other.id,
            similarity_score=round(score, 4),
            relation_type=relation_type,
            source_metadata={
                "source_a": article.source,
                "url_a": article.original_source_url or article.url,
                "byline_a": article.author,
                "origin_a": article.creation_origin,
                "source_b": other.source,
                "url_b": other.original_source_url or other.url,
                "byline_b": other.author,
                "origin_b": other.creation_origin,
                "method": "sequence+shingle similarity",
                "detected_at": datetime.utcnow().isoformat(),
            },
            detected_at=datetime.utcnow(),
        )
        session.add(rel)
        created.append(rel)
        logger.info(
            f"[Dedup] article #{article.id} linked -> #{other.id} "
            f"({relation_type}, score={score:.4f})"
        )
    if created:
        session.flush()
    return created


def get_article_relations(session, article_id: int) -> List[Dict[str, Any]]:
    """Outgoing + incoming relations for an article (both directions)."""
    outgoing = (
        session.query(ArticleRelation)
        .filter(ArticleRelation.article_id == article_id)
        .order_by(ArticleRelation.similarity_score.desc())
        .all()
    )
    incoming = (
        session.query(ArticleRelation)
        .filter(ArticleRelation.related_article_id == article_id)
        .order_by(ArticleRelation.similarity_score.desc())
        .all()
    )
    return [r.to_dict() for r in outgoing] + [
        {**r.to_dict(), "article_id": r.related_article_id,
         "related_article_id": r.article_id}
        for r in incoming
    ]


def link_raw_items(
    session,
    item: RawNewsItem,
    dup_url: str,
    score: float,
    relation_type: Optional[str] = None,
) -> Optional[RawItemRelation]:
    """Link a raw staging item to its duplicate counterpart (kept separate)."""
    if not item or not dup_url:
        return None
    related = (
        session.query(RawNewsItem)
        .filter(RawNewsItem.source_url == dup_url)
        .filter(RawNewsItem.id != item.id)
        .first()
    )
    existing = None
    if related:
        existing = (
            session.query(RawItemRelation)
            .filter(
                RawItemRelation.item_id == item.id,
                RawItemRelation.related_item_id == related.id,
            )
            .first()
        )
    if existing:
        return existing

    rel = RawItemRelation(
        item_id=item.id,
        related_item_id=related.id if related else 0,
        similarity_score=round(float(score), 4),
        relation_type=relation_type or ("duplicate" if score >= DUPLICATE_THRESHOLD else "near_duplicate"),
        source_metadata={
            "url_a": item.source_url,
            "source_a": item.source_name,
            "url_b": dup_url,
            "source_b": related.source_name if related else None,
            "related_article": not related,
            "detected_at": datetime.utcnow().isoformat(),
        },
        detected_at=datetime.utcnow(),
    )
    session.add(rel)
    session.flush()
    logger.info(
        f"[Dedup] raw item #{item.id} linked -> "
        f"{'raw#' + str(rel.related_item_id) if related else 'article'} "
        f"(score={score:.4f})"
    )
    return rel


def list_raw_relations(session, item_id: int) -> List[Dict[str, Any]]:
    rows = (
        session.query(RawItemRelation)
        .filter(
            (RawItemRelation.item_id == item_id)
            | (RawItemRelation.related_item_id == item_id)
        )
        .all()
    )
    return [r.to_dict() for r in rows]
