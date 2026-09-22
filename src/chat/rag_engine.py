"""
Retrieval-Augmented Generation (RAG) Engine over SQLite Articles.
Performs FTS5 search, extracts top-k relevant article contexts, and builds grounded prompts.
"""

from typing import List, Dict, Any, Optional
from src.common.logger import get_logger
from src.storage.database import get_db_session
from src.storage.repositories import ArticleRepository

logger = get_logger("webcreoling.chat.rag")


class RAGEngine:
    """Retrieves relevant article records from SQLite database to augment LLM answers."""

    def __init__(self, top_k: int = 3):
        self.top_k = top_k

    def search_relevant_articles(self, query: str, top_k: Optional[int] = None) -> List[Dict[str, Any]]:
        """Query SQLite FTS5 index for articles matching the user query with fallback."""
        k = top_k or self.top_k
        with get_db_session() as session:
            repo = ArticleRepository(session)
            results = repo.search_fts(query, top_k=k)
            
            # Fallback if no direct keyword match: try individual tokens or recent articles
            if not results:
                tokens = [t.strip() for t in query.split() if len(t.strip()) > 2]
                for tok in tokens:
                    results = repo.search_fts(tok, top_k=k)
                    if results:
                        break
            
            if not results:
                # Retrieve latest articles as general relevant context
                recent = repo.get_highlighted_articles(limit=k)
                results = [a.to_dict() for a in recent]

            # Attach rich metadata and image paths
            for item in results:
                article = repo.get_by_id(item["id"])
                if article and article.images:
                    item["images"] = [img.local_path for img in article.images]
                    item["lead_image"] = article.images[0].local_path
                else:
                    item["images"] = []
                    item["lead_image"] = None
                
                content = item.get("content_text") or ""
                item["snippet"] = (content[:160] + "...") if len(content) > 160 else content
                item["category"] = item.get("category") or "general"
                item["author"] = item.get("author") or "ডেস্ক রিপোর্ট"
        return results

    def build_rag_prompt(self, user_question: str, retrieved_articles: List[Dict[str, Any]]) -> str:
        """
        Construct grounded RAG prompt containing context from retrieved articles.
        """
        if not retrieved_articles:
            return f"প্রশ্ন: {user_question}\nউত্তর: ডেটাবেসে এই প্রশ্নের সম্পর্কিত কোনো সংবাদ পাওয়া যায়নি।"

        context_blocks = []
        for i, art in enumerate(retrieved_articles, 1):
            title = art.get("title", "")
            source = art.get("source", "")
            date = art.get("published_at", "")
            body = (art.get("content_text") or "")[:400]
            context_blocks.append(
                f"[সূত্র {i}] শিরোনাম: {title} ({source}, {date})\nবিবরণ: {body}"
            )

        joined_context = "\n\n".join(context_blocks)
        prompt = (
            f"তথ্যসূত্র:\n{joined_context}\n\n"
            f"উপরোক্ত সংবাদ তথ্যের ভিত্তিতে নিচের প্রশ্নের সঠিক ও সংক্ষিপ্ত উত্তর দিন:\n"
            f"প্রশ্ন: {user_question}\n-> উত্তর:"
        )
        return prompt
