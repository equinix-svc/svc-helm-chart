"""LLM Guard service for the LiteLLM guardrail (litellm/llm_guard_guardrail.py).

POST /scan/prompt   {"text": ...} -> {"block": bool, "risk": float, "reason": str}
POST /scan/secrets  {"text": ...} -> {"found": bool, "text": <redacted text>}

Scanner logic is carried over unchanged from the earlier lab's llm-guard adapter: DeBERTa v3 must flag the text AND
explicit injection vocabulary must be present, because DeBERTa alone scores many benign instruction-shaped phrases
near 1.0. Only the Portkey webhook contract and the metrics hook were dropped.
"""
import os
import re

import torch
from fastapi import FastAPI
from llm_guard.input_scanners import PromptInjection, Secrets
from llm_guard.input_scanners.prompt_injection import MatchType

app = FastAPI()

# One thread per vCPU stalls at the thread barrier when another process holds a core; leave headroom.
torch.set_num_threads(int(os.environ.get("TORCH_NUM_THREADS", "4")))

# SENTENCE: a small payload hidden in a long legitimate document is diluted when the whole text is scored at once.
injection_scanner = PromptInjection(match_type=MatchType.SENTENCE)
secrets_scanner = Secrets()

INJECTION_SIGNALS = [
    'ignore previous instructions', 'ignore all previous', 'ignore your instructions',
    'disregard your', 'forget your instructions', 'forget your previous',
    'override your instructions', 'system prompt', 'you are now',
    'act as a ', 'act as an ', 'pretend you have', 'pretend to be',
    'jailbreak', 'no restrictions', 'no rules', 'uncensored', 'unrestricted ai',
    'system override', 'developer mode', 'admin override',
    'bypass your', 'break character', 'reveal your system', 'new instructions:',
]
INJECTION_PATTERNS = [
    re.compile(p, re.I | re.S) for p in (
        r"\bignore\b[^.\n]{0,40}\b(task|tasks|instruction|instructions|rules?|prompt|guidelines?|previous|above|everything)\b",
        r"\b(note|message|instruction|comment)s?\s+(for|to)\s+(the\s+)?(ai|llm|assistant|model|chatbot)\b",
        r"\b(ai|llm)\s+assistant\s*[:,]",
        r"\b(print|output|reveal|show|send|email|leak|dump|exfiltrate|list)\b[^.\n]{0,60}\b(env(ironment)?\s+variables?|api\s+keys?|secrets?|credentials?|passwords?|\.env|tokens?)\b",
        r"\binstead,?\s+(output|print|reveal|show|say|send)\b",
    )
]


def has_signals(text: str) -> bool:
    lower = text.lower()
    return any(s in lower for s in INJECTION_SIGNALS) or any(p.search(text) for p in INJECTION_PATTERNS)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/scan/prompt")
def scan_prompt(payload: dict):
    text = payload.get("text") or ""
    if not text:
        return {"block": False, "risk": 0.0, "reason": ""}
    _, is_valid, risk = injection_scanner.scan(text)
    block = (not is_valid) and has_signals(text)
    return {"block": block, "risk": risk, "reason": f"prompt injection (risk {round(risk * 100)}%)" if block else ""}


@app.post("/scan/secrets")
def scan_secrets(payload: dict):
    text = payload.get("text") or ""
    if not text:
        return {"found": False, "text": text}
    sanitized, is_valid, _ = secrets_scanner.scan(text)
    return {"found": not is_valid, "text": sanitized}
