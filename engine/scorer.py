"""Deterministic scoring. No LLM judges.

Result sets are compared by *key values* rather than exact document shape, so
two different pipelines that return the same answer both pass even if they
name their output fields differently.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any

NUM_ABS_TOL = 0.01
NUM_REL_TOL = 1e-3


def normalize(value: Any) -> Any:
    """Make BSON-ish values comparable: ObjectId/datetime -> str, Decimal128 -> float."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return value.strip().casefold()
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(v) for v in value]
    if hasattr(value, "to_decimal"):  # Decimal128
        return float(value.to_decimal())
    return str(value)


def leaves(doc: Any) -> list:
    """All scalar leaf values (normalized) inside a document."""
    out: list = []
    norm = normalize(doc)

    def walk(n):
        if isinstance(n, dict):
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
        elif n is not None:
            out.append(n)

    walk(norm)
    return out


def num_close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=NUM_REL_TOL, abs_tol=NUM_ABS_TOL)


def value_in(target: Any, doc: Any) -> bool:
    t = normalize(target)
    for leaf in leaves(doc):
        if isinstance(t, float) and isinstance(leaf, float):
            if num_close(t, leaf):
                return True
        elif leaf == t:
            return True
    return False


def _gold_column(gold: list[dict], field: str | None) -> list:
    if field is None:
        return []
    col = []
    for d in gold:
        cur: Any = d
        for part in field.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        col.append(cur)
    return col


def compare(result: list[dict], gold: list[dict], comparison: dict) -> tuple[bool, str]:
    """Return (passed, reason)."""
    mode = comparison.get("mode", "unordered")
    if not isinstance(result, list):
        return False, "result is not a list"

    if mode == "scalar":
        field = comparison.get("value")
        target = _gold_column(gold, field)[0] if field else (leaves(gold[0])[0] if gold else None)
        if target is None:
            return (len(result) == 0 or all(not leaves(d) for d in result)), "empty scalar"
        if len(result) != 1:
            return False, f"expected 1 row for scalar, got {len(result)}"
        return (value_in(target, result[0]), "scalar mismatch")

    keys = _gold_column(gold, comparison.get("key"))
    vals = _gold_column(gold, comparison.get("value"))
    if len(result) != len(gold):
        return False, f"row count {len(result)} != expected {len(gold)}"

    if mode == "ordered":
        for i, doc in enumerate(result):
            if value_in(keys[i], doc):
                continue
            if vals and vals[i] is not None and value_in(vals[i], doc):
                continue  # tie on the ranking metric: an equally-ranked item is acceptable
            return False, f"row {i} does not match expected {keys[i]!r}"
        return True, "ok"

    # unordered / set: every gold key matched by a distinct row
    remaining = list(result)
    for k in keys:
        hit = next((d for d in remaining if value_in(k, d)), None)
        if hit is None:
            return False, f"expected {k!r} missing from result"
        remaining.remove(hit)
    return True, "ok"


def index_keys(recommended: Any) -> list[str]:
    """Extract ordered field names from {'a':1,'b':-1}, [['a',1]], ['a','b'] or 'a_1_b_-1'."""
    if isinstance(recommended, dict):
        inner = recommended.get("keys") or recommended.get("key")
        if isinstance(inner, (dict, list)):
            return index_keys(inner)
        return [str(k) for k in recommended.keys()]
    if isinstance(recommended, list):
        out = []
        for item in recommended:
            if isinstance(item, (list, tuple)) and item:
                out.append(str(item[0]))
            elif isinstance(item, dict):
                out.extend(str(k) for k in item.keys())
            else:
                out.append(str(item))
        return out
    if isinstance(recommended, str):
        parts = recommended.split("_")
        return [p for p in parts[::2] if p]
    return []


def score_diagnosis(diagnosis: Any, gold: dict) -> tuple[bool, str]:
    if not isinstance(diagnosis, dict):
        return False, "missing diagnosis"
    got = index_keys(diagnosis.get("recommended_index"))
    for acceptable in gold["index_keys"]:
        if got == acceptable:
            return True, "ok"
    return False, f"recommended index {got} not in {gold['index_keys']}"
