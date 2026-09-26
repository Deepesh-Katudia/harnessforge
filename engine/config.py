"""Central configuration: env vars, model routing, pricing, gates."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "")
HF_DB = os.getenv("HF_DB", "harnessforge")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")
VOYAGE_MODEL = os.getenv("VOYAGE_MODEL", "voyage-3.5")
EMBED_DIM = 1024

# Logical model tiers the genome can route to -> concrete OpenRouter ids.
MODELS = {
    "CHEAP": os.getenv("CHEAP_MODEL", "meta-llama/llama-3.1-8b-instruct"),
    "STRONG": os.getenv("STRONG_MODEL", "openai/gpt-5.4-mini"),
}
META_MODEL = os.getenv("META_MODEL", "anthropic/claude-sonnet-5")

# USD per token (prompt, completion). Fallback when OpenRouter doesn't report cost.
PRICING = {
    "meta-llama/llama-3.1-8b-instruct": (0.05e-6, 0.08e-6),
    "openai/gpt-5.4-mini": (0.75e-6, 4.5e-6),
    "openai/gpt-5.4-nano": (0.2e-6, 1.25e-6),
    "anthropic/claude-sonnet-5": (2e-6, 10e-6),
}

# Collections the task agent may touch (db, collection). Locked, not evolvable.
ALLOWED_COLLECTIONS = {
    "movies": ("sample_mflix", "movies"),
    "comments": ("sample_mflix", "comments"),
    "sales": ("sample_supplies", "sales"),
}

MAX_TIME_MS = 5000
RESULT_CAP = 50          # hard cap on rows returned to the agent / scorer
LIMIT_CAP = 20           # evolvable limit_cap guardrail value
PIPELINE_LENGTH_CAP = 10
MAX_AGENT_STEPS = 6
EVAL_WORKERS = int(os.getenv("EVAL_WORKERS", "8"))


@dataclass(frozen=True)
class Gates:
    max_regression_rate: float = 0.10
    max_cost_increase: float = 0.10       # relative
    big_gain_override: float = 0.10       # absolute accuracy gain that excuses cost increase
    max_cost_increase_hard: float = 3.0   # never accept > +300% cost


GATES = Gates()
MAX_RUN_USD = float(os.getenv("MAX_RUN_USD", "5.0"))
