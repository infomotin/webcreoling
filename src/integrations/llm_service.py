"""Abstracted self-hosted LLM client (Ollama / Hugging Face inference server).

All AI-agent generation & embedding calls go through this module — NEVER through
external paid APIs. The endpoint URL, model name and provider are configurable
(site_configs["llm_config"] overrides environment defaults).

Graceful degradation: every network failure returns None instead of raising, so
callers can fall back to the built-in rule-based pipeline.
"""

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import requests

from src.common.logger import get_logger

logger = get_logger("webcreoling.integrations.llm")

DEFAULT_LLM_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "provider": "ollama",           # 'ollama' | 'openai_compat' | 'none'
    "base_url": "http://127.0.0.1:11434",
    "model": "llama3.2",
    "embed_model": "nomic-embed-text",
    "timeout": 60,
    "updated_at": None,
}


def get_llm_config() -> Dict[str, Any]:
    """LLM config: env (settings) -> site_configs override -> defaults."""
    cfg = dict(DEFAULT_LLM_CONFIG)
    try:
        from config.settings import settings
        cfg.update({
            "enabled": bool(getattr(settings, "LLM_ENABLED", True)),
            "provider": str(getattr(settings, "LLM_PROVIDER", "ollama")),
            "base_url": str(getattr(settings, "LLM_BASE_URL", cfg["base_url"])),
            "model": str(getattr(settings, "LLM_MODEL", cfg["model"])),
            "embed_model": str(getattr(settings, "LLM_EMBED_MODEL", cfg["embed_model"])),
            "timeout": int(getattr(settings, "LLM_TIMEOUT", cfg["timeout"])),
        })
    except Exception as exc:  # pragma: no cover
        logger.debug(f"Settings load note for LLM config: {exc}")

    try:
        from src.storage.database import get_db_session
        from src.storage.repositories import SiteConfigRepository
        with get_db_session() as session:
            db_cfg = SiteConfigRepository(session).get_config("llm_config", None)
        if isinstance(db_cfg, dict):
            cfg.update({k: v for k, v in db_cfg.items() if v is not None})
    except Exception as exc:
        logger.debug(f"DB LLM config load note: {exc}")
    return cfg


def save_llm_config(data: Dict[str, Any]) -> Dict[str, Any]:
    """Persist LLM config overrides into site_configs."""
    from src.storage.database import get_db_session
    from src.storage.repositories import SiteConfigRepository
    current = get_llm_config()
    current.update(data)
    from datetime import datetime
    current["updated_at"] = datetime.utcnow().isoformat()
    with get_db_session() as session:
        SiteConfigRepository(session).set_config("llm_config", current)
    return current


class BaseLLMClient(ABC):
    """Provider-agnostic LLM interface (text generation + embeddings)."""

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.base_url = str(cfg.get("base_url", "")).rstrip("/")
        self.model = cfg.get("model") or ""
        self.embed_model = cfg.get("embed_model") or cfg.get("model") or ""
        self.timeout = int(cfg.get("timeout", 60))

    @abstractmethod
    def generate(self, prompt: str, system: Optional[str] = None,
                 max_tokens: int = 512, temperature: float = 0.3) -> Optional[str]:
        ...

    @abstractmethod
    def embed(self, text: str) -> Optional[List[float]]:
        ...

    def healthy(self) -> bool:
        """Cheap reachability probe; False means callers should degrade gracefully."""
        raise NotImplementedError


class OllamaClient(BaseLLMClient):
    """Self-hosted Ollama server (POST /api/chat, POST /api/embeddings)."""

    def generate(self, prompt: str, system: Optional[str] = None,
                 max_tokens: int = 512, temperature: float = 0.3) -> Optional[str]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [],
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": temperature},
        }
        if system:
            payload["messages"].append({"role": "system", "content": system})
        payload["messages"].append({"role": "user", "content": prompt})
        try:
            resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return (data.get("message") or {}).get("content")
        except Exception as exc:
            logger.warning(f"Ollama generate failed ({self.model}): {exc}")
            return None

    def embed(self, text: str) -> Optional[List[float]]:
        try:
            resp = requests.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.embed_model, "prompt": text},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            vec = resp.json().get("embedding")
            return vec if isinstance(vec, list) and vec else None
        except Exception as exc:
            logger.warning(f"Ollama embeddings failed ({self.embed_model}): {exc}")
            return None

    def healthy(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=min(5, self.timeout))
            return resp.ok
        except Exception:
            return False


class OpenAICompatClient(BaseLLMClient):
    """OpenAI-compatible endpoint — covers Hugging Face TGI / vLLM / llama.cpp server."""

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        api_key = self.cfg.get("api_key")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def generate(self, prompt: str, system: Optional[str] = None,
                 max_tokens: int = 512, temperature: float = 0.3) -> Optional[str]:
        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        try:
            resp = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload, headers=self._headers(), timeout=self.timeout,
            )
            resp.raise_for_status()
            choices = resp.json().get("choices") or []
            if choices:
                return (choices[0].get("message") or {}).get("content")
            return None
        except Exception as exc:
            logger.warning(f"OpenAI-compatible generate failed ({self.model}): {exc}")
            return None

    def embed(self, text: str) -> Optional[List[float]]:
        try:
            resp = requests.post(
                f"{self.base_url}/v1/embeddings",
                json={"model": self.embed_model, "input": text},
                headers=self._headers(), timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json().get("data") or []
            if data:
                vec = data[0].get("embedding")
                return vec if isinstance(vec, list) and vec else None
            return None
        except Exception as exc:
            logger.warning(f"OpenAI-compatible embeddings failed: {exc}")
            return None

    def healthy(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/v1/models",
                                headers=self._headers(), timeout=min(5, self.timeout))
            return resp.ok
        except Exception:
            return False


def get_llm_client() -> Optional[BaseLLMClient]:
    """Return a configured client, or None when LLM support is disabled/unavailable."""
    try:
        cfg = get_llm_config()
        if not cfg.get("enabled", True):
            return None
        provider = str(cfg.get("provider", "ollama")).lower()
        if provider in ("none", "", "off", "disabled"):
            return None
        if provider == "openai_compat":
            return OpenAICompatClient(cfg)
        return OllamaClient(cfg)
    except Exception as exc:
        logger.warning(f"LLM client init failed, degrading to rule-based fallback: {exc}")
        return None


def generate_text(prompt: str, system: Optional[str] = None,
                  max_tokens: int = 512, temperature: float = 0.3) -> Optional[str]:
    """Convenience wrapper: returns None (not raise) when the local LLM is unreachable."""
    client = get_llm_client()
    if client is None:
        return None
    return client.generate(prompt, system=system, max_tokens=max_tokens, temperature=temperature)


def embed_text(text: str) -> Optional[List[float]]:
    """Convenience wrapper for embeddings; None when unavailable (callers degrade)."""
    client = get_llm_client()
    if client is None:
        return None
    return client.embed(text)


def llm_health() -> Dict[str, Any]:
    """Health probe surfaced in admin UI."""
    cfg = get_llm_config()
    client = get_llm_client()
    if client is None:
        return {"enabled": False, "provider": cfg.get("provider"), "healthy": False,
                "model": cfg.get("model"), "base_url": cfg.get("base_url"),
                "note": "LLM disabled — rule-based fallback in use."}
    ok = False
    try:
        ok = client.healthy()
    except Exception:
        ok = False
    return {"enabled": True, "provider": cfg.get("provider"), "healthy": ok,
            "model": cfg.get("model"), "embed_model": cfg.get("embed_model"),
            "base_url": cfg.get("base_url"),
            "note": None if ok else "Endpoint unreachable — rule-based fallback in use."}
