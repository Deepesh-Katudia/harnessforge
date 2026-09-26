"""Explicit acceptance gates: metrics decide, not the LLM."""
from __future__ import annotations

from engine.config import GATES, Gates


def regressions(parent_pass: dict[str, float], child_pass: dict[str, float]) -> tuple[list[str], int]:
    """Tasks the parent passed on EVERY repeat that the child now fails on most repeats.

    Only stable passes are protected: a task the parent passed 2/3 times is a coin flip, not a capability.
    """
    parent_ok = [tid for tid, score in parent_pass.items() if float(score) >= 0.999]
    broken = [tid for tid in parent_ok if float(child_pass.get(tid, 0)) < 0.5]
    return broken, len(parent_ok)


def regression_rate(parent_pass: dict[str, float], child_pass: dict[str, float]) -> float:
    broken, base = regressions(parent_pass, child_pass)
    return round(len(broken) / base, 4) if base else 0.0


def cost_change(parent_cost: float, child_cost: float) -> float:
    """Relative cost change; +0.10 == 10% more expensive."""
    if parent_cost <= 0:
        return 0.0 if child_cost <= 0 else 1.0
    return round((child_cost - parent_cost) / parent_cost, 4)


def decide(parent: dict, child: dict, gates: Gates = GATES) -> dict:
    """Return the gate breakdown and final verdict for a parent/child metric pair."""
    gain = round(child["accuracy"] - parent["accuracy"], 4)
    broken, base = regressions(parent["pass_map"], child["pass_map"])
    reg = round(len(broken) / base, 4) if base else 0.0
    allowed = max(gates.regression_task_floor, int(gates.max_regression_rate * base))
    dcost = cost_change(parent["cost_usd"], child["cost_usd"])
    checks = {
        "accuracy_improved": gain > 0,
        "regression_ok": len(broken) <= allowed,
        "cost_ok": dcost <= min(gates.max_cost_increase_hard,
                                gates.max_cost_increase + gates.cost_per_accuracy_point * max(0.0, gain) * 100),
    }
    return {
        "accepted": all(checks.values()),
        "checks": checks,
        "accuracy_gain": gain,
        "regression_rate": reg,
        "regressed_tasks": broken,
        "cost_change": dcost,
        "latency_change_ms": child["latency_ms"] - parent["latency_ms"],
    }
