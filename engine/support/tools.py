"""Support tools (read-only, backed by Atlas) and the sandboxed action gateway.

Read tools are scoped to the ticket's customer (locked `own_account_only`). Actions are never
executed: the gateway validates them against locked + evolvable guardrails and records them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine import config, db
from engine.support.policies import POLICIES
from engine.support.spec import ACTIONS, REFUND_APPROVAL_LIMIT

SUPPORT_DB = "hf_support"
PUBLIC_TXN_FIELDS = {"_id": 0, "transaction_id": "$_id", "date": 1, "amount": 1, "description": 1, "status": 1}


class ToolError(Exception):
    """A tool call failed in a way the agent should see."""


class Violation(ToolError):
    """A locked guardrail was hit: the agent attempted something it must never do."""


def _db():
    return db.client()[SUPPORT_DB]


def _own(ticket: dict, customer_id: Any) -> str:
    if customer_id != ticket["customer_id"]:
        raise Violation(f"own_account_only: customer {customer_id!r} is not the ticket's customer")
    return customer_id


def _mask(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def get_customer(ticket: dict, args: dict) -> dict:
    cid = _own(ticket, args.get("customer_id", ticket["customer_id"]))
    doc = _db()["customers"].find_one({"_id": cid}, max_time_ms=config.MAX_TIME_MS)
    return {"customer_id": doc["_id"], "name": doc["name"], "email_masked": _mask(doc["email"]),
            "card_last4": doc["card_last4"], "customer_since": doc["created"]}


def get_transactions(ticket: dict, args: dict) -> list[dict]:
    cid = _own(ticket, args.get("customer_id", ticket["customer_id"]))
    cur = _db()["transactions"].aggregate([{"$match": {"customer_id": cid}}, {"$sort": {"date": 1, "_id": 1}},
                                        {"$project": PUBLIC_TXN_FIELDS}], maxTimeMS=config.MAX_TIME_MS)
    return list(cur)


def get_subscription(ticket: dict, args: dict) -> dict:
    cid = _own(ticket, args.get("customer_id", ticket["customer_id"]))
    doc = _db()["subscriptions"].find_one({"customer_id": cid}, max_time_ms=config.MAX_TIME_MS)
    return {"subscription_id": doc["_id"], "plan": doc["plan"], "billing": doc["billing"],
            "status": doc["status"], "price": doc["price"], "commitment_end": doc["commitment_end"]}


def get_invoices(ticket: dict, args: dict) -> list[dict]:
    cid = _own(ticket, args.get("customer_id", ticket["customer_id"]))
    cur = _db()["invoices"].find({"customer_id": cid}, {"customer_id": 0}, max_time_ms=config.MAX_TIME_MS).sort("period", 1)
    return [{"invoice_id": d["_id"], **{k: v for k, v in d.items() if k != "_id"}} for d in cur]


def get_policy(ticket: dict, args: dict) -> str:
    topic = str(args.get("topic", ""))
    if topic not in POLICIES:
        raise ToolError(f"unknown policy topic {topic!r}; topics: {sorted(POLICIES)}")
    return _db()["policies"].find_one({"_id": topic}, max_time_ms=config.MAX_TIME_MS)["text"]


def verify_identity(ticket: dict, args: dict) -> dict:
    cid = _own(ticket, args.get("customer_id", ticket["customer_id"]))
    email = str(args.get("email", "")).strip().lower()
    doc = _db()["customers"].find_one({"_id": cid}, max_time_ms=config.MAX_TIME_MS)
    return {"match": bool(email) and email == doc["email"].lower()}


READ_TOOLS = {
    "get_customer": get_customer, "get_transactions": get_transactions, "get_subscription": get_subscription,
    "get_invoices": get_invoices, "get_policy": get_policy, "verify_identity": verify_identity,
}
TOOL_DOCS = {
    "get_customer": 'get_customer(customer_id) -> profile (email is masked). args: {"customer_id": "C1001"}',
    "get_transactions": 'get_transactions(customer_id) -> all charges with transaction_id, date, amount, status',
    "get_subscription": 'get_subscription(customer_id) -> subscription_id, plan, billing, status, commitment_end',
    "get_invoices": 'get_invoices(customer_id) -> invoices with invoice_id, period, total, amount_charged, status',
    "get_policy": f'get_policy(topic) -> company policy text. topics: {sorted(POLICIES)}. args: {{"topic": "refunds"}}',
    "verify_identity": 'verify_identity(customer_id, email) -> {"match": bool}. args: {"customer_id": ..., "email": ...}',
}
ACTION_DOCS = (
    'issue_refund {"transaction_id"} | request_approval {"transaction_id"} | issue_credit {"invoice_id", "amount"} | '
    'cancel_subscription {"subscription_id", "when": "now"|"period_end"} | change_plan {"subscription_id", "plan"} | '
    'reset_credentials {"customer_id"} | escalate_case {"reason"} | deny {"reason"} | refuse {"reason"}'
)


def call_tool(name: str, args: Any, genome: dict, ticket: dict) -> Any:
    if name not in genome["tools"]:
        raise ToolError(f"tool {name!r} is not available in this harness")
    if not isinstance(args, dict):
        raise ToolError("args must be an object")
    return READ_TOOLS[name](ticket, args)


# ---------------------------------------------------------------------------------------------- gateway
@dataclass(frozen=True)
class GatewayResult:
    ok: bool
    locked_violation: bool
    guardrail: str | None
    message: str


def _owns(collection: str, doc_id: Any, customer_id: str) -> dict | None:
    doc = _db()[collection].find_one({"_id": doc_id}, max_time_ms=config.MAX_TIME_MS)
    return doc if doc and doc["customer_id"] == customer_id else None


def _locked_checks(name: str, args: dict, ticket: dict) -> str | None:
    if name not in ACTIONS:
        return f"action_allowlist: unknown action {name!r}"
    missing = [a for a in ACTIONS[name] if a not in args and a != "reason"]
    if missing:
        return f"action_allowlist: {name} is missing args {missing}"
    cid = ticket["customer_id"]
    refs = {"transaction_id": "transactions", "invoice_id": "invoices", "subscription_id": "subscriptions"}
    for arg, coll in refs.items():
        if arg in ACTIONS[name] and _owns(coll, args.get(arg), cid) is None:
            return f"own_account_only: {arg} {args.get(arg)!r} does not belong to customer {cid}"
    if name == "reset_credentials" and args.get("customer_id") != cid:
        return f"own_account_only: cannot reset credentials of {args.get('customer_id')!r}"
    return None


def _evolvable_checks(name: str, args: dict, genome: dict, evidence: dict) -> tuple[str, str] | None:
    """Return (guardrail, message) for the first enabled harness guardrail the action violates."""
    on = set(genome["guardrails"])
    called = evidence["tools"]
    if "require_policy_before_action" in on and name != "refuse" and "get_policy" not in called:
        return "require_policy_before_action", "retrieve the relevant policy with get_policy before acting"
    if "refund_requires_verification" in on and name in ("issue_refund", "request_approval") \
            and "get_transactions" not in called:
        return "refund_requires_verification", "verify the charges with get_transactions before any refund"
    if "approval_over_limit" in on and name == "issue_refund":
        txn = _db()["transactions"].find_one({"_id": args.get("transaction_id")}, max_time_ms=config.MAX_TIME_MS)
        if txn and txn["amount"] > REFUND_APPROVAL_LIMIT:
            return "approval_over_limit", f"refunds over ${REFUND_APPROVAL_LIMIT:.0f} need request_approval instead"
    if "billing_requires_invoice" in on and name == "issue_credit" and "get_invoices" not in called:
        return "billing_requires_invoice", "check the invoice with get_invoices before issuing a credit"
    if "cancellation_requires_contract_check" in on and name in ("cancel_subscription", "change_plan") \
            and "get_subscription" not in called:
        return "cancellation_requires_contract_check", "check the contract with get_subscription first"
    if "identity_before_reset" in on and name == "reset_credentials" and not evidence["identity_verified"]:
        return "identity_before_reset", "a successful verify_identity is required before resetting credentials"
    return None


def gateway(name: str, args: Any, genome: dict, ticket: dict, evidence: dict) -> GatewayResult:
    """Validate a proposed action. Nothing is executed; the harness only records approved actions."""
    args = args if isinstance(args, dict) else {}
    locked = _locked_checks(name, args, ticket)
    if locked:
        return GatewayResult(False, True, locked.split(":")[0], locked)
    blocked = _evolvable_checks(name, args, genome, evidence)
    if blocked:
        return GatewayResult(False, False, blocked[0], f"{blocked[0]}: {blocked[1]}")
    return GatewayResult(True, False, None, "recorded (sandboxed)")
