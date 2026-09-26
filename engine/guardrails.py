"""Guardrail registry.

Locked guardrails always run regardless of the genome; evolvable ones run only
when enabled in the genome. Every check is deterministic and side-effect free.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

from engine import config

BLOCKED_STAGES = frozenset({
    "$out", "$merge", "$function", "$accumulator", "$where",
    "$currentOp", "$listSessions", "$listLocalSessions", "$planCacheStats",
    # not real aggregation stages, but a model emitting them is attempting a write
    "$delete", "$deleteOne", "$deleteMany", "$remove", "$update", "$updateOne", "$updateMany",
    "$insert", "$insertOne", "$insertMany", "$drop", "$dropCollection", "$createIndex", "$rename",
})
SUBPIPELINE_KEYS = ("pipeline",)

WRITE_INTENT_RE = re.compile(
    r"\b(delete|drop|remove|truncate|wipe|purge|erase|insert|update|upsert|rename|"
    r"overwrite|modify|replace|set\s+\w+\s+to|create\s+(an?\s+)?(index|collection)|"
    r"(write|save|store|copy|export)\b.*\b(in)?to\s+(a\s+|the\s+)?(new\s+)?collection)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    reason: str | None
    pipeline: list | None


def _walk_keys(node: Any):
    """Yield every dict key anywhere inside node."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield k, v
            yield from _walk_keys(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_keys(item)


def find_blocked_operator(pipeline: Any) -> str | None:
    for key, _ in _walk_keys(pipeline):
        if key in BLOCKED_STAGES:
            return key
    return None


def find_foreign_collections(pipeline: Any) -> list[str]:
    """Collections referenced via $lookup / $unionWith / $graphLookup."""
    found: list[str] = []
    for key, value in _walk_keys(pipeline):
        if key in ("$lookup", "$graphLookup") and isinstance(value, dict) and "from" in value:
            found.append(value["from"])
        elif key == "$unionWith":
            found.append(value if isinstance(value, str) else (value or {}).get("coll"))
    return found


def check_pipeline(collection: str, pipeline: Any, genome: dict) -> CheckResult:
    """Run locked + enabled guardrails. Returns a (possibly rewritten) pipeline copy."""
    # locked: allowed_collections
    if collection not in config.ALLOWED_COLLECTIONS:
        return CheckResult(False, f"allowed_collections: {collection!r} is not allowlisted", None)
    if not isinstance(pipeline, list) or not all(isinstance(s, dict) and len(s) == 1 for s in pipeline):
        return CheckResult(False, "pipeline must be a list of single-key stage objects", None)
    # locked: read_only + blocked_stages
    blocked = find_blocked_operator(pipeline)
    if blocked:
        return CheckResult(False, f"blocked_stages: {blocked} is not permitted (read-only harness)", None)
    home_db = config.ALLOWED_COLLECTIONS[collection][0]
    for foreign in find_foreign_collections(pipeline):
        target = config.ALLOWED_COLLECTIONS.get(foreign)
        if target is None or target[0] != home_db:
            return CheckResult(False, f"allowed_collections: lookup into {foreign!r} is not allowlisted", None)

    out = copy.deepcopy(pipeline)
    enabled = set(genome.get("guardrails", []))
    if "pipeline_length_cap" in enabled and len(out) > config.PIPELINE_LENGTH_CAP:
        return CheckResult(False, f"pipeline_length_cap: {len(out)} stages > {config.PIPELINE_LENGTH_CAP}", None)
    if "limit_cap" in enabled:
        out = enforce_limit(out, config.LIMIT_CAP)
    return CheckResult(True, None, out)


def enforce_limit(pipeline: list, cap: int) -> list:
    """Clamp an existing trailing $limit to cap, or append one."""
    if pipeline and "$limit" in pipeline[-1]:
        current = pipeline[-1]["$limit"]
        if isinstance(current, int) and current <= cap:
            return pipeline
        return [*pipeline[:-1], {"$limit": cap}]
    if pipeline and any(k in pipeline[-1] for k in ("$count", "$group")) and _is_scalar_tail(pipeline):
        return pipeline
    return [*pipeline, {"$limit": cap}]


def _is_scalar_tail(pipeline: list) -> bool:
    last = pipeline[-1]
    return "$count" in last or ("$group" in last and last["$group"].get("_id") is None)


def has_write_intent(request: str) -> bool:
    return bool(WRITE_INTENT_RE.search(request or ""))
