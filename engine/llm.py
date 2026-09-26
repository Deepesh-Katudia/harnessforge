"""OpenRouter chat client with cost accounting, bounded retries and LangSmith tracing."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from openai import OpenAI, OpenAIError

from engine import config

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: int


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    if not config.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    client = OpenAI(base_url=config.OPENROUTER_BASE_URL, api_key=config.OPENROUTER_API_KEY, timeout=90)
    if os.getenv("LANGSMITH_API_KEY"):
        from langsmith.wrappers import wrap_openai
        client = wrap_openai(client)
    return client


def _cost(model: str, usage: Any) -> float:
    reported = getattr(usage, "cost", None)
    if reported is None and isinstance(getattr(usage, "model_extra", None), dict):
        reported = usage.model_extra.get("cost")
    if isinstance(reported, (int, float)):
        return float(reported)
    p_in, p_out = config.PRICING.get(model, (1e-6, 4e-6))
    return usage.prompt_tokens * p_in + usage.completion_tokens * p_out


def chat(model: str, messages: list[dict], temperature: float = 0.0, json_mode: bool = True,
         max_tokens: int = 1200) -> Completion:
    kwargs: dict[str, Any] = {
        "model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens,
        "seed": 7,
        "extra_body": {"usage": {"include": True}},
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    last_exc: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        start = time.perf_counter()
        try:
            resp = _client().chat.completions.create(**kwargs)
            usage = resp.usage
            text = (resp.choices[0].message.content or "") if resp.choices else ""
            return Completion(
                text=text, model=model,
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                cost_usd=_cost(model, usage) if usage else 0.0,
                latency_ms=int((time.perf_counter() - start) * 1000),
            )
        except OpenAIError as exc:
            last_exc = exc
            log.warning("openrouter call failed (attempt %d/%d): %s", attempt + 1, MAX_ATTEMPTS, exc)
            time.sleep(1.5 * 2 ** attempt)
    raise RuntimeError(f"OpenRouter call failed after {MAX_ATTEMPTS} attempts: {last_exc}")


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json(text: str) -> dict:
    """Extract the first JSON object from a model response."""
    candidates = [m.group(1) for m in _FENCE.finditer(text or "")] + [text or ""]
    for cand in candidates:
        start = cand.find("{")
        while start != -1:
            depth = 0
            in_str = esc = False
            for i in range(start, len(cand)):
                ch = cand[i]
                if in_str:
                    esc = (ch == "\\") and not esc
                    if ch == '"' and not esc:
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            obj = json.loads(cand[start:i + 1])
                            if isinstance(obj, dict):
                                return obj
                        except json.JSONDecodeError:
                            pass
                        break
            start = cand.find("{", start + 1)
    raise ValueError("json parse failure: no JSON object in model output")
