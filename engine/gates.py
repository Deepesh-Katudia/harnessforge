"""Explicit acceptance gates: metrics decide, not the LLM."""
from __future__ import annotations

from engine.config import GATES, Gates


def regression_rate(parent_pass: dict[str, bool], child_pass: dict[str, bool]) -> float:
    parent_ok = [tid for tid, ok in parent_pass.items() if ok]
    if not parent_ok:
        return 0.0
    broken = sum(1 for tid in parent_ok if not child_pass.get(tid, False))
    return round(broken / len(parent_ok), 4)


def cost_change(parent_cost: float, child_cost: float) -> float:
    """Relative cost change; +0.10 == 10% more expensive."""
    if parent_cost <= 0:
        return 0.0 if child_cost <= 0 else 1.0
    return round((child_cost - parent_cost) / parent_cost, 4)


def decide(parent: dict, child: dict, gates: Gates = GATES) -> dict:
    """Return the gate breakdown and final verdict for a parent/child metric pair."""
    gain = round(child["accuracy"] - parent["accuracy"], 4)
    reg = regression_rate(parent["pass_map"], child["pass_map"])
    dcost = cost_change(parent["cost_usd"], child["cost_usd"])
    checks = {
        "accuracy_improved": gain > 0,
        "regression_ok": reg <= gates.max_regression_rate,
        "cost_ok": (dcost <= gates.max_cost_increase
                    or (gain >= gates.big_gain_override and dcost <= gates.max_cost_increase_hard)),
    }
    return {
        "accepted": all(checks.values()),
        "checks": checks,
        "accuracy_gain": gain,
        "regression_rate": reg,
        "cost_change": dcost,
        "latency_change_ms": child["latency_ms"] - parent["latency_ms"],
    }
