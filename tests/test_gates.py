from engine.gates import cost_change, decide, regression_rate


def metrics(acc, passes, cost=1.0, latency=100):
    return {"accuracy": acc, "pass_map": passes, "cost_usd": cost, "latency_ms": latency}


def test_regression_rate():
    assert regression_rate({"a": True, "b": True, "c": False}, {"a": False, "b": True, "c": True}) == 0.5
    assert regression_rate({"a": False}, {"a": True}) == 0.0


def test_cost_change_handles_zero_parent():
    assert cost_change(0.0, 0.0) == 0.0
    assert cost_change(2.0, 3.0) == 0.5


def test_accepts_clear_improvement():
    parent = metrics(0.4, {"a": True, "b": False, "c": False})
    child = metrics(0.6, {"a": True, "b": True, "c": False}, cost=1.03)
    verdict = decide(parent, child)
    assert verdict["accepted"] and verdict["regression_rate"] == 0.0


def test_rejects_tiny_gain_with_big_cost():
    parent = metrics(0.76, {"a": True}, cost=1.0)
    child = metrics(0.77, {"a": True}, cost=1.45)
    verdict = decide(parent, child)
    assert not verdict["accepted"] and not verdict["checks"]["cost_ok"]


def test_big_gain_excuses_cost_increase():
    parent = metrics(0.4, {"a": False}, cost=1.0)
    child = metrics(0.6, {"a": True}, cost=2.0)
    assert decide(parent, child)["accepted"]


def test_rejects_regressions_and_no_gain():
    parent = metrics(0.5, {"a": True, "b": True, "c": False, "d": False})
    swapped = metrics(0.75, {"a": False, "b": True, "c": True, "d": True})
    assert not decide(parent, swapped)["accepted"]
    assert not decide(parent, metrics(0.5, parent["pass_map"]))["accepted"]
