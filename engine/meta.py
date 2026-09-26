"""The meta-agent: reads TRAIN failures + vector-retrieved memory and proposes ONE genome patch.

Isolation rule: this module only ever receives train-split data. Holdout tasks,
gold answers and holdout failures are never passed in.
"""
from __future__ import annotations

import json
import logging
from collections import Counter

from langsmith import traceable

from engine import config, domains, genome as genome_mod, llm, memory

log = logging.getLogger(__name__)

META_PROMPT = """You are the meta-engineer of an AI agent harness. %(agent_description)s
You improve the agent ONLY by editing its harness "genome" with exactly ONE patch per generation.
Every patch is objectively re-evaluated; patches that do not raise accuracy, cause regressions,
or cost too much are rejected. Prefer cheap, targeted fixes for the most common failure type.

Patch ops (JSON):
  {"op": "add_rule", "value": "<concise imperative rule, <=240 chars>"}
  {"op": "remove_rule", "value": "<exact existing rule>"}
  {"op": "set", "path": "<path>", "value": <value>}   allowed: %(settable)s
  {"op": "enable_guardrail" | "disable_guardrail", "value": <one of %(guardrails)s>}
  {"op": "enable_tool" | "disable_tool", "value": <one of %(tools)s>}
Locked (cannot change): guardrails %(locked)s, tools %(locked_tools)s.
Procedural guardrails also enable the tool they enforce: %(requires)s.
Note: the CHEAP model rarely calls optional tools on its own; procedural guardrails force it to.
Model tiers: CHEAP (%(cheap)s, very low cost) and STRONG (%(strong)s, ~15x cost).

Reply with JSON only:
{"patch": {...}, "rationale": "<cite failure counts/examples>", "lesson": "<one generalizable sentence>",
 "target_failure_type": "<failure type you are fixing>"}"""


def _system_prompt() -> str:
    domain = domains.current()
    spec = domain.spec
    return META_PROMPT % {
        "agent_description": domain.agent_description,
        "settable": json.dumps({k: list(v) for k, v in spec.settable_paths.items()}),
        "guardrails": list(spec.evolvable_guardrails),
        "tools": list(spec.all_tools),
        "locked": list(spec.locked_guardrails),
        "locked_tools": list(spec.locked_tools),
        "requires": json.dumps(spec.guardrail_requires),
        "cheap": config.MODELS["CHEAP"], "strong": config.MODELS["STRONG"],
    }


def _compact_failure(f: dict) -> dict:
    return {
        "question": f["question"], "failure_type": f.get("failure_type"), "why": (f.get("reason") or "")[:200],
        "agent_action": f.get("action"),
        "agent_output": json.dumps(f.get("generated_pipeline") or f.get("diagnosis") or f.get("action_args") or {},
                                   default=str)[:300],
        "tools_called": [c["tool"] for c in f.get("tool_calls") or []],
    }


def build_context(genome: dict, train_metrics: dict, retrieved: list[dict], lessons: list[dict],
                  history: list[dict]) -> str:
    failures = train_metrics["failures"]
    return json.dumps({
        "current_genome": genome,
        "train_metrics": {k: train_metrics[k] for k in ("accuracy", "passed", "total", "by_family",
                                                        "failure_counts", "cost_usd", "latency_ms")},
        "recent_train_failures": [_compact_failure(f) for f in failures[:10]],
        "similar_past_failures_from_vector_memory": [_compact_failure(r) for r in retrieved],
        "lessons": [l["lesson"] for l in lessons],
        "previous_patches": history[-8:],
    }, default=str, indent=1)


def memory_query(train_metrics: dict) -> tuple[str, str | None]:
    """Build a vector-search query from the dominant train failure type."""
    counts = Counter(f.get("failure_type") for f in train_metrics["failures"])
    if not counts:
        return "", None
    dominant, _ = counts.most_common(1)[0]
    example = next(f for f in train_metrics["failures"] if f.get("failure_type") == dominant)
    return memory.failure_text({**example, "question": example["question"]}), dominant


@traceable(name="meta_agent", run_type="chain")
def propose(genome: dict, train_metrics: dict, run_id: str, generation: int, history: list[dict]) -> dict:
    query, dominant = memory_query(train_metrics)
    retrieved = memory.similar_failures(query, 5, run_id=run_id, before_generation=generation) if query else []
    lessons = memory.similar_lessons(query, 3, run_id=run_id) if query else []
    messages = [{"role": "system", "content": _system_prompt()},
                {"role": "user", "content": build_context(genome, train_metrics, retrieved, lessons, history)}]
    cost, last_error = 0.0, None
    for json_mode in (True, False, False):  # JSON mode on this route occasionally returns empty content
        comp = llm.chat(config.META_MODEL, messages, temperature=0.3, max_tokens=2500, json_mode=json_mode)
        cost += comp.cost_usd
        try:
            out = llm.parse_json(comp.text)
            genome_mod.validate_patch(genome, out.get("patch"))
            return {**out, "valid": True, "meta_cost_usd": cost, "memory_query": query,
                    "dominant_failure": dominant, "retrieved": retrieved, "lessons_used": lessons}
        except (ValueError, genome_mod.PatchError) as exc:
            last_error = str(exc)
            log.warning("meta-agent proposal invalid (%s); raw output: %s", exc, comp.text[:500])
            messages += [{"role": "assistant", "content": comp.text},
                         {"role": "user", "content": f"Invalid patch: {exc}. Propose a different, valid patch."}]
    return {"patch": None, "valid": False, "error": last_error, "meta_cost_usd": cost, "memory_query": query,
            "dominant_failure": dominant, "retrieved": retrieved, "lessons_used": lessons,
            "rationale": f"invalid proposal: {last_error}"}
