"""The Genome: a versioned, JSON-serialisable description of the agent harness.

Genomes are treated as immutable values: every function here returns a new dict
and never mutates its input. Mutations arrive as structured patches from the
meta-agent and must pass `validate_patch` before `apply_patch`.
"""
from __future__ import annotations

import copy
from typing import Any

LOCKED_GUARDRAILS = ("read_only", "allowed_collections", "blocked_stages", "max_time_ms")
EVOLVABLE_GUARDRAILS = (
    "limit_cap",
    "pipeline_length_cap",
    "require_explain_before_diagnosis",
    "require_schema_before_query",
    "refuse_write_intent",
)
ALL_TOOLS = ("get_schema", "sample_docs", "list_indexes", "explain_aggregate", "run_aggregate", "collection_stats")
LOCKED_TOOLS = ("run_aggregate",)

SETTABLE_PATHS: dict[str, tuple] = {
    "context.include_schema": (True, False),
    "context.sample_docs_k": (0, 1, 2, 3),
    "context.memory_k": (0, 1, 2, 3, 5),
    "routing.generator_model": ("CHEAP", "STRONG"),
    "routing.repair_model": ("CHEAP", "STRONG"),
    "routing.max_retries": (0, 1, 2),
}

MAX_RULES = 12
MAX_RULE_CHARS = 240

PATCH_OPS = (
    "add_rule", "remove_rule", "set",
    "enable_guardrail", "disable_guardrail",
    "enable_tool", "disable_tool",
)

SEED_GENOME: dict[str, Any] = {
    "rules": [],
    "context": {"include_schema": False, "sample_docs_k": 0, "memory_k": 0},
    "guardrails": list(LOCKED_GUARDRAILS),
    "tools": ["run_aggregate"],
    "routing": {"generator_model": "CHEAP", "repair_model": "CHEAP", "max_retries": 0, "temperature": 0},
}


class PatchError(ValueError):
    """Raised when a proposed patch is not allowed."""


def seed() -> dict[str, Any]:
    return copy.deepcopy(SEED_GENOME)


def _get_path(genome: dict, path: str) -> Any:
    section, key = path.split(".", 1)
    return genome[section][key]


def validate_patch(genome: dict, patch: Any) -> None:
    """Raise PatchError if `patch` is not a legal single mutation of `genome`."""
    if not isinstance(patch, dict):
        raise PatchError("patch must be an object")
    op = patch.get("op")
    if op not in PATCH_OPS:
        raise PatchError(f"unknown op {op!r}")
    value = patch.get("value")

    if op == "add_rule":
        if not isinstance(value, str) or not value.strip():
            raise PatchError("add_rule needs a non-empty string value")
        if len(value) > MAX_RULE_CHARS:
            raise PatchError(f"rule longer than {MAX_RULE_CHARS} chars")
        if len(genome["rules"]) >= MAX_RULES:
            raise PatchError("rule budget exhausted; remove a rule first")
        if value.strip() in genome["rules"]:
            raise PatchError("rule already present")
    elif op == "remove_rule":
        if value not in genome["rules"] and not (isinstance(value, int) and 0 <= value < len(genome["rules"])):
            raise PatchError("remove_rule value must be an existing rule or index")
    elif op == "set":
        path = patch.get("path")
        if path not in SETTABLE_PATHS:
            raise PatchError(f"path {path!r} is not settable")
        if value not in SETTABLE_PATHS[path] or type(value) is not type(SETTABLE_PATHS[path][0]):
            raise PatchError(f"value {value!r} not allowed for {path}")
        if _get_path(genome, path) == value:
            raise PatchError(f"{path} already {value!r}")
    elif op in ("enable_guardrail", "disable_guardrail"):
        if value in LOCKED_GUARDRAILS:
            raise PatchError(f"guardrail {value!r} is locked")
        if value not in EVOLVABLE_GUARDRAILS:
            raise PatchError(f"unknown guardrail {value!r}")
        enabled = value in genome["guardrails"]
        if (op == "enable_guardrail") == enabled:
            raise PatchError(f"guardrail {value!r} already {'enabled' if enabled else 'disabled'}")
    elif op in ("enable_tool", "disable_tool"):
        if value not in ALL_TOOLS:
            raise PatchError(f"unknown tool {value!r}")
        if op == "disable_tool" and value in LOCKED_TOOLS:
            raise PatchError(f"tool {value!r} is locked")
        present = value in genome["tools"]
        if (op == "enable_tool") == present:
            raise PatchError(f"tool {value!r} already {'enabled' if present else 'disabled'}")


def apply_patch(genome: dict, patch: dict) -> dict:
    """Validate and apply `patch`, returning a new genome."""
    validate_patch(genome, patch)
    child = copy.deepcopy(genome)
    op, value = patch["op"], patch.get("value")
    if op == "add_rule":
        child["rules"] = [*child["rules"], value.strip()]
    elif op == "remove_rule":
        target = child["rules"][value] if isinstance(value, int) else value
        child["rules"] = [r for r in child["rules"] if r != target]
    elif op == "set":
        section, key = patch["path"].split(".", 1)
        child[section] = {**child[section], key: value}
    elif op == "enable_guardrail":
        child["guardrails"] = [*child["guardrails"], value]
    elif op == "disable_guardrail":
        child["guardrails"] = [g for g in child["guardrails"] if g != value]
    elif op == "enable_tool":
        child["tools"] = [*child["tools"], value]
    elif op == "disable_tool":
        child["tools"] = [t for t in child["tools"] if t != value]
    return child


def diff(parent: dict, child: dict) -> list[dict]:
    """Flat list of {path, before, after} changes for display."""
    changes: list[dict] = []
    for section in ("context", "routing"):
        for key in sorted(set(parent[section]) | set(child[section])):
            a, b = parent[section].get(key), child[section].get(key)
            if a != b:
                changes.append({"path": f"{section}.{key}", "before": a, "after": b})
    for section in ("rules", "guardrails", "tools"):
        for item in child[section]:
            if item not in parent[section]:
                changes.append({"path": section, "before": None, "after": item})
        for item in parent[section]:
            if item not in child[section]:
                changes.append({"path": section, "before": item, "after": None})
    return changes


def describe_patch(patch: dict) -> str:
    op = patch.get("op")
    if op == "set":
        return f"set {patch.get('path')} = {patch.get('value')!r}"
    return f"{op} {patch.get('value')!r}"
