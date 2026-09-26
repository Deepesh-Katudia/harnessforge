import pytest

from engine import genome as g


def test_seed_is_weak_and_has_locked_guardrails():
    s = g.seed()
    assert s["rules"] == []
    assert s["context"]["include_schema"] is False
    assert set(g.LOCKED_GUARDRAILS) <= set(s["guardrails"])
    assert s["routing"]["generator_model"] == "CHEAP"


def test_apply_patch_returns_new_genome_without_mutating_parent():
    parent = g.seed()
    child = g.apply_patch(parent, {"op": "set", "path": "context.include_schema", "value": True})
    assert child["context"]["include_schema"] is True
    assert parent["context"]["include_schema"] is False


def test_add_and_remove_rule():
    parent = g.seed()
    child = g.apply_patch(parent, {"op": "add_rule", "value": "Sort before limit."})
    assert child["rules"] == ["Sort before limit."]
    grand = g.apply_patch(child, {"op": "remove_rule", "value": 0})
    assert grand["rules"] == []


@pytest.mark.parametrize("patch", [
    {"op": "disable_guardrail", "value": "read_only"},
    {"op": "disable_guardrail", "value": "blocked_stages"},
    {"op": "disable_tool", "value": "run_aggregate"},
    {"op": "set", "path": "context.sample_docs_k", "value": 7},
    {"op": "set", "path": "context.sample_docs_k", "value": True},
    {"op": "set", "path": "routing.temperature", "value": 1},
    {"op": "set", "path": "__class__", "value": 1},
    {"op": "exec", "value": "import os"},
    {"op": "enable_tool", "value": "drop_collection"},
    {"op": "enable_guardrail", "value": "made_up"},
    {"op": "add_rule", "value": ""},
    {"op": "add_rule", "value": "x" * 500},
    {"op": "set", "path": "context.include_schema", "value": False},  # no-op
    "not a dict",
])
def test_invalid_patches_rejected(patch):
    with pytest.raises(g.PatchError):
        g.apply_patch(g.seed(), patch)


def test_enable_tool_and_guardrail():
    child = g.apply_patch(g.seed(), {"op": "enable_tool", "value": "explain_aggregate"})
    child = g.apply_patch(child, {"op": "enable_guardrail", "value": "refuse_write_intent"})
    assert "explain_aggregate" in child["tools"]
    assert "refuse_write_intent" in child["guardrails"]


def test_rule_budget():
    gen = g.seed()
    for i in range(g.MAX_RULES):
        gen = g.apply_patch(gen, {"op": "add_rule", "value": f"rule {i}"})
    with pytest.raises(g.PatchError):
        g.apply_patch(gen, {"op": "add_rule", "value": "one more"})


def test_diff_lists_changes():
    parent = g.seed()
    child = g.apply_patch(parent, {"op": "set", "path": "routing.generator_model", "value": "STRONG"})
    assert g.diff(parent, child) == [{"path": "routing.generator_model", "before": "CHEAP", "after": "STRONG"}]


def test_procedural_guardrail_brings_its_tool_and_protects_it():
    child = g.apply_patch(g.seed(), {"op": "enable_guardrail", "value": "require_explain_before_diagnosis"})
    assert "explain_aggregate" in child["tools"]
    with pytest.raises(g.PatchError):
        g.apply_patch(child, {"op": "disable_tool", "value": "explain_aggregate"})
