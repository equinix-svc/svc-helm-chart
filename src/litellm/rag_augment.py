"""rag_augment.py - LiteLLM pre-call guardrail: retrieve top-k chunks from the in-cluster rag-service and prepend
them as a system message. Opt-in per request ("guardrails": ["rag-augment"]). Retrieval failure never blocks the call.
"""
import os

import httpx

from litellm._logging import verbose_proxy_logger
from litellm.integrations.custom_guardrail import CustomGuardrail

URL = os.environ.get("RAG_URL", "http://rag-service:8000")
TOP_K = int(os.environ.get("RAG_TOP_K", "3"))
MAX_CHARS = int(os.environ.get("RAG_MAX_CONTEXT_CHARS", "6000"))


class RagAugmentGuardrail(CustomGuardrail):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type):
        messages = list(data.get("messages") or [])
        query = next((m["content"] for m in reversed(messages)
                      if m.get("role") == "user" and isinstance(m.get("content"), str)), "")
        if not query:
            return data
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(f"{URL}/retrieve", json={"query": query, "top_k": TOP_K})
                r.raise_for_status()
                chunks = r.json().get("chunks", [])
        except Exception as exc:
            verbose_proxy_logger.warning("RAG retrieval failed, continuing without context: %s", exc)
            return data
        parts, total = [], 0
        for i, c in enumerate(chunks):
            if total + len(c["text"]) > MAX_CHARS:
                break
            parts.append(f"[Context {i + 1}] ({c['source']}): {c['text']}")
            total += len(c["text"])
        if parts:
            data["messages"] = [{"role": "system", "content": "Retrieved context:\n\n" + "\n\n".join(parts)}, *messages]
        return data
