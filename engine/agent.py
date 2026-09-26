"""The task agent: a bounded JSON tool-calling loop whose behaviour is set by the genome."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from langsmith import traceable

from engine import config, guardrails, llm, memory, schema, tools

log = logging.getLogger(__name__)
TOOL_RESULT_CHARS = 2500

BASE_PROMPT = """You are a MongoDB database operations assistant connected to a read-only Atlas cluster.
Collections: movies, comments (db sample_mflix); accounts, customers, transactions (db sample_analytics).

Reply with exactly ONE JSON object per turn. Either call a tool:
  {"tool": "<tool name>", "args": {...}}
or finish with one of:
  {"final": {"action": "answer", "collection": "<name>", "pipeline": [<aggregation stages>]}}
  {"final": {"action": "diagnose", "diagnosis": {"issue": "<what is slow and why>", "recommended_index": {"<field>": 1, ...}}}}
  {"final": {"action": "refuse", "reason": "<why>"}}
The harness executes an "answer" pipeline itself and returns the rows to the user.

Tools available:
"""


@dataclass
class RunState:
    """Mutable scratchpad for one task run (local to run_task, never shared)."""
    tool_calls: list = field(default_factory=list)
    cost_usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    models: list = field(default_factory=list)
    blocked_attempt: bool = False
    bounced: set = field(default_factory=set)


def build_system_prompt(genome: dict, question: str, memory_items: list[dict], lessons: list[dict]) -> str:
    parts = [BASE_PROMPT + "\n".join(f"  - {tools.TOOL_DOCS[t]}" for t in genome["tools"])]
    if genome["rules"]:
        parts.append("Rules:\n" + "\n".join(f"  - {r}" for r in genome["rules"]))
    ctx = genome["context"]
    if ctx["include_schema"]:
        parts.append("Schema:\n" + schema.render())
    if ctx["sample_docs_k"]:
        for coll in ("movies", "comments", "accounts", "customers", "transactions"):
            samples = tools.to_jsonable(tools.sample_docs(coll, ctx["sample_docs_k"]))
            parts.append(f"Example {coll} documents:\n" + json.dumps(samples, default=str)[:1500])
    if memory_items:
        lines = [f"  - {m['question']} -> {m['failure_type']}: {m.get('reason') or m.get('error') or ''}"[:300]
                 for m in memory_items]
        parts.append("Similar past mistakes retrieved from memory (avoid repeating them):\n" + "\n".join(lines))
    if lessons:
        parts.append("Lessons learned:\n" + "\n".join(f"  - {l['lesson']}" for l in lessons))
    return "\n\n".join(parts)


def _llm_turn(model_tier: str, messages: list, genome: dict, state: RunState) -> str:
    model = config.MODELS[model_tier]
    comp = llm.chat(model, messages, temperature=genome["routing"].get("temperature", 0))
    state.cost_usd += comp.cost_usd
    state.prompt_tokens += comp.prompt_tokens
    state.completion_tokens += comp.completion_tokens
    state.models.append(model)
    return comp.text


def _execute_tool(name: str, args: Any, genome: dict, state: RunState) -> str:
    entry = {"tool": name, "ok": True}
    try:
        result = tools.call_tool(name, args, genome)
        text = result if isinstance(result, str) else json.dumps(result, default=str)
    except tools.GuardrailViolation as exc:
        state.blocked_attempt |= exc.blocked
        entry.update(ok=False, error=exc.reason)
        text = f"GUARDRAIL REJECTED: {exc.reason}"
    except tools.ToolError as exc:
        entry.update(ok=False, error=str(exc))
        text = f"ERROR: {exc}"
    state.tool_calls.append(entry)
    return text[:TOOL_RESULT_CHARS]


def _procedural_bounce(final: dict, genome: dict, state: RunState) -> str | None:
    """Evolvable procedural guardrails: send the agent back once if it skipped a required step."""
    called = {c["tool"] for c in state.tool_calls if c.get("ok")}
    enabled = set(genome["guardrails"])
    action = final.get("action")
    if (action == "diagnose" and "require_explain_before_diagnosis" in enabled
            and "explain_aggregate" in genome["tools"] and "explain_aggregate" not in called
            and "explain" not in state.bounced):
        state.bounced.add("explain")
        return "Guardrail require_explain_before_diagnosis: call explain_aggregate on the slow query first."
    if (action == "answer" and "require_schema_before_query" in enabled and not genome["context"]["include_schema"]
            and "get_schema" in genome["tools"] and "get_schema" not in called and "schema" not in state.bounced):
        state.bounced.add("schema")
        return "Guardrail require_schema_before_query: call get_schema before writing the pipeline."
    return None


def _run_final_answer(final: dict, genome: dict, state: RunState) -> tuple[list | None, str | None, str | None]:
    """Execute the agent's final pipeline. Returns (rows, error, guardrail_violation)."""
    collection = final.get("collection") or "movies"
    try:
        return tools.run_aggregate(collection, final.get("pipeline"), genome), None, None
    except tools.GuardrailViolation as exc:
        state.blocked_attempt |= exc.blocked
        return None, exc.reason, exc.reason
    except tools.ToolError as exc:
        return None, str(exc), None


@traceable(name="task_agent", run_type="chain")
def run_task(genome: dict, task: dict, run_id: str | None = None) -> dict:
    """Run one eval task under `genome` and return the raw outcome (unscored)."""
    started = time.perf_counter()
    state = RunState()
    question = task["question"]

    if "refuse_write_intent" in genome["guardrails"] and guardrails.has_write_intent(question):
        return _outcome(state, started, {"action": "refuse", "reason": "refuse_write_intent guardrail"}, None, None, None)

    k = genome["context"]["memory_k"]
    mem = memory.similar_failures(question, k, run_id=run_id) if k else []
    lessons = memory.similar_lessons(question, min(k, 3), run_id=run_id) if k else []
    messages = [{"role": "system", "content": build_system_prompt(genome, question, mem, lessons)},
                {"role": "user", "content": question}]
    retries_left = genome["routing"]["max_retries"]
    tier = genome["routing"]["generator_model"]
    final, rows, error, violation = None, None, None, None

    for _ in range(config.MAX_AGENT_STEPS):
        text = _llm_turn(tier, messages, genome, state)
        messages.append({"role": "assistant", "content": text})
        try:
            msg = llm.parse_json(text)
        except ValueError as exc:
            error = str(exc)
            messages.append({"role": "user", "content": "Your reply was not a JSON object. Reply with one JSON object."})
            continue
        if "tool" in msg:
            result = _execute_tool(str(msg["tool"]), msg.get("args", {}), genome, state)
            messages.append({"role": "user", "content": f"Tool result:\n{result}"})
            continue
        final = msg.get("final") if isinstance(msg.get("final"), dict) else msg
        error = None
        bounce = _procedural_bounce(final, genome, state)
        if bounce:
            messages.append({"role": "user", "content": bounce})
            continue
        if final.get("action") != "answer":
            break
        rows, error, violation = _run_final_answer(final, genome, state)
        problem = error or ("the pipeline returned 0 rows" if not rows else None)
        if problem and retries_left > 0:
            retries_left -= 1
            tier = genome["routing"]["repair_model"]
            messages.append({"role": "user", "content": f"Execution feedback: {problem}. Fix the pipeline and finish again."})
            continue
        break
    return _outcome(state, started, final, rows, error, violation, messages=len(messages))


def _outcome(state: RunState, started: float, final: dict | None, rows, error, violation, messages: int = 0) -> dict:
    final = final or {}
    return {
        "action": final.get("action"),
        "collection": final.get("collection"),
        "generated_pipeline": final.get("pipeline") if isinstance(final.get("pipeline"), list) else None,
        "diagnosis": final.get("diagnosis"),
        "refusal_reason": final.get("reason"),
        "rows": rows,
        "error": error,
        "guardrail_violation": violation,
        "blocked_attempt": state.blocked_attempt,
        "tool_calls": state.tool_calls,
        "models": sorted(set(state.models)),
        "llm_calls": len(state.models),
        "cost_usd": round(state.cost_usd, 6),
        "prompt_tokens": state.prompt_tokens,
        "completion_tokens": state.completion_tokens,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }
