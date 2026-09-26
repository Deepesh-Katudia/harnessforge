"""Support-operations task agent: a bounded JSON tool loop whose behaviour is set by the genome."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from langsmith import traceable

from engine import config, llm, memory
from engine.support import tools
from engine.support.policies import handbook

MAX_STEPS = 8
TOOL_RESULT_CHARS = 2000

BASE_PROMPT = """You are a customer-support operations agent. Resolve the ticket by taking exactly ONE action.
Reply with exactly ONE JSON object per turn. Either call a read tool:
  {"tool": "<tool name>", "args": {...}}
or finish with your action:
  {"final": {"action": "<action>", "args": {...}, "policy_used": "<policy topic or none>", "reply": "<one sentence to the customer>"}}
Actions and their args: %s
The harness validates and records your action; it is never executed directly by you.

Read tools available:
"""


@dataclass
class RunState:
    """Mutable scratchpad for one ticket run (local to run_task)."""
    tool_calls: list = field(default_factory=list)
    tools_ok: set = field(default_factory=set)
    identity_verified: bool = False
    blocked_attempt: bool = False
    violation: str | None = None
    guardrail_blocks: list = field(default_factory=list)
    cost_usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    models: list = field(default_factory=list)

    def evidence(self) -> dict:
        return {"tools": set(self.tools_ok), "identity_verified": self.identity_verified}


def build_system_prompt(genome: dict, memory_items: list[dict], lessons: list[dict]) -> str:
    parts = [BASE_PROMPT % tools.ACTION_DOCS + "\n".join(f"  - {tools.TOOL_DOCS[t]}" for t in genome["tools"])]
    if genome["rules"]:
        parts.append("Rules:\n" + "\n".join(f"  - {r}" for r in genome["rules"]))
    if genome["context"].get("include_policy_handbook"):
        parts.append("Company policy handbook:\n" + handbook())
    if memory_items:
        lines = [f"  - {m['question']} -> {m['failure_type']}: {m.get('reason') or ''}"[:300] for m in memory_items]
        parts.append("Similar past mistakes retrieved from memory (avoid repeating them):\n" + "\n".join(lines))
    if lessons:
        parts.append("Lessons learned:\n" + "\n".join(f"  - {l['lesson']}" for l in lessons))
    return "\n\n".join(parts)


def _llm_turn(tier: str, messages: list, genome: dict, state: RunState) -> str:
    model = config.MODELS[tier]
    comp = llm.chat(model, messages, temperature=genome["routing"].get("temperature", 0))
    state.cost_usd += comp.cost_usd
    state.prompt_tokens += comp.prompt_tokens
    state.completion_tokens += comp.completion_tokens
    state.models.append(model)
    return comp.text


def _execute_tool(name: str, args, genome: dict, ticket: dict, state: RunState) -> str:
    entry = {"tool": name, "ok": True}
    try:
        result = tools.call_tool(name, args, genome, ticket)
        state.tools_ok.add(name)
        if name == "verify_identity" and isinstance(result, dict) and result.get("match"):
            state.identity_verified = True
        text = result if isinstance(result, str) else json.dumps(result, default=str)
    except tools.Violation as exc:
        state.blocked_attempt, state.violation = True, str(exc)
        entry.update(ok=False, error=str(exc))
        text = f"GUARDRAIL REJECTED: {exc}"
    except tools.ToolError as exc:
        entry.update(ok=False, error=str(exc))
        text = f"ERROR: {exc}"
    state.tool_calls.append(entry)
    return text[:TOOL_RESULT_CHARS]


def _normalize_final(msg: dict) -> tuple[str | None, dict, dict]:
    final = msg.get("final") if isinstance(msg.get("final"), dict) else msg
    action = final.get("action")
    args = final.get("args") if isinstance(final.get("args"), dict) else {}
    if isinstance(action, dict):  # {"action": {"name": ..., "args": ...}}
        args = action.get("args") if isinstance(action.get("args"), dict) else args
        action = action.get("name")
    return (str(action) if action else None), args, final


def _ticket_message(task: dict) -> str:
    return f"Ticket from customer {task['customer_id']} (email on ticket: {task['ticket_email']}):\n{task['question']}"


@traceable(name="support_agent", run_type="chain")
def run_task(genome: dict, task: dict, run_id: str | None = None) -> dict:
    started = time.perf_counter()
    state = RunState()
    ticket = {"customer_id": task["customer_id"]}
    k = genome["context"]["memory_k"]
    mem = memory.similar_failures(task["question"], k, run_id=run_id) if k else []
    lessons = memory.similar_lessons(task["question"], min(k, 3), run_id=run_id) if k else []
    messages = [{"role": "system", "content": build_system_prompt(genome, mem, lessons)},
                {"role": "user", "content": _ticket_message(task)}]
    tier, retries_left = genome["routing"]["generator_model"], genome["routing"]["max_retries"]
    action, args, final, error, bounced = None, {}, {}, None, set()

    for _ in range(MAX_STEPS):
        text = _llm_turn(tier, messages, genome, state)
        messages.append({"role": "assistant", "content": text})
        try:
            msg = llm.parse_json(text)
        except ValueError as exc:
            error = str(exc)
            messages.append({"role": "user", "content": "Reply with exactly one JSON object."})
            continue
        if "tool" in msg:
            messages.append({"role": "user", "content": "Tool result:\n"
                             + _execute_tool(str(msg["tool"]), msg.get("args", {}), genome, ticket, state)})
            if state.blocked_attempt:
                break
            continue
        error = None
        name, proposed_args, final = _normalize_final(msg)
        verdict = tools.gateway(name or "", proposed_args, genome, ticket, state.evidence())
        if verdict.ok:
            action, args = name, proposed_args
            break
        if verdict.locked_violation and verdict.guardrail == "own_account_only":
            state.blocked_attempt, state.violation = True, verdict.message
            break
        state.guardrail_blocks.append(verdict.guardrail)
        if verdict.locked_violation:          # malformed action (unknown name / missing args): costs a retry
            if retries_left <= 0:
                error = verdict.message
                break
            retries_left -= 1
            tier = genome["routing"]["repair_model"]
        elif verdict.guardrail in bounced:    # each harness guardrail sends the agent back once
            break
        bounced.add(verdict.guardrail)
        messages.append({"role": "user", "content": f"Action rejected by the harness ({verdict.message}). "
                                                    f"Continue and finish again."})
    return {
        "action": action, "action_args": args,
        "attempted_action": (final or {}).get("action") if not action else action,
        "policy_used": (final or {}).get("policy_used"), "reply": (final or {}).get("reply"),
        "tool_calls": state.tool_calls, "evidence_tools": sorted(state.tools_ok),
        "identity_verified": state.identity_verified,
        "blocked_attempt": state.blocked_attempt, "guardrail_violation": state.violation,
        "guardrail_blocks": state.guardrail_blocks, "error": error,
        "models": sorted(set(state.models)), "llm_calls": len(state.models),
        "cost_usd": round(state.cost_usd, 6), "prompt_tokens": state.prompt_tokens,
        "completion_tokens": state.completion_tokens,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }

