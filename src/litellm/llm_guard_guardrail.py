"""llm_guard_guardrail.py - LiteLLM guardrail backed by the in-cluster llm-guard service.

pre_call : prompt-injection check on the last user message (blocks with HTTP 400) and secrets redaction on every
           string message.
post_call: secrets redaction on the model reply.
If the llm-guard service is unreachable the request passes unchanged (fail open, logged).
"""
import os

import httpx
from fastapi import HTTPException

from litellm._logging import verbose_proxy_logger
from litellm.integrations.custom_guardrail import CustomGuardrail

URL = os.environ.get("LLM_GUARD_URL", "http://llm-guard:8000")
TIMEOUT = float(os.environ.get("LLM_GUARD_TIMEOUT", "10"))


async def _post(path: str, text: str) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(f"{URL}{path}", json={"text": text})
        r.raise_for_status()
        return r.json()


class LlmGuardGuardrail(CustomGuardrail):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type):
        messages = data.get("messages") or []
        try:
            last = next((m for m in reversed(messages)
                         if m.get("role") == "user" and isinstance(m.get("content"), str)), None)
            if last:
                verdict = await _post("/scan/prompt", last["content"])
                if verdict.get("block"):
                    raise HTTPException(status_code=400, detail=f"llm-guard BLOCKED: {verdict.get('reason')}")
            for m in messages:
                if isinstance(m.get("content"), str):
                    res = await _post("/scan/secrets", m["content"])
                    if res.get("found"):
                        m["content"] = res["text"]
        except HTTPException:
            raise
        except Exception as exc:
            verbose_proxy_logger.warning("llm-guard unavailable, request passed unchecked: %s", exc)
        return data

    async def async_post_call_success_hook(self, data: dict, user_api_key_dict, response):
        try:
            for choice in getattr(response, "choices", None) or []:
                msg = getattr(choice, "message", None)
                if msg is not None and isinstance(msg.content, str):
                    res = await _post("/scan/secrets", msg.content)
                    if res.get("found"):
                        msg.content = res["text"]
        except Exception as exc:
            verbose_proxy_logger.warning("llm-guard unavailable, reply passed unchecked: %s", exc)
        return response
