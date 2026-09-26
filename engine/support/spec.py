"""Evolvable surface of the support-operations agent."""
from __future__ import annotations

from engine.genome import ROUTING_PATHS, GenomeSpec

# Always enforced by the action gateway / tools; a mutation can never remove them.
LOCKED_GUARDRAILS = ("own_account_only", "action_allowlist", "sandboxed_actions")

# Harness-level controls the meta-agent may switch on or off.
EVOLVABLE_GUARDRAILS = (
    "require_policy_before_action",          # any action needs a get_policy call first
    "refund_requires_verification",          # refunds need transaction evidence
    "approval_over_limit",                   # refunds > $200 are blocked unless routed to request_approval
    "billing_requires_invoice",              # credits need invoice evidence
    "cancellation_requires_contract_check",  # cancel/change plan need the subscription contract
    "identity_before_reset",                 # credential resets need a successful identity check
)

READ_TOOLS = ("get_customer", "get_transactions", "get_subscription", "get_invoices", "get_policy", "verify_identity")
LOCKED_TOOLS = ("get_customer",)

GUARDRAIL_REQUIRES = {
    "require_policy_before_action": "get_policy",
    "refund_requires_verification": "get_transactions",
    "billing_requires_invoice": "get_invoices",
    "cancellation_requires_contract_check": "get_subscription",
    "identity_before_reset": "verify_identity",
}

SETTABLE_PATHS = {
    "context.include_policy_handbook": (True, False),   # static policy injection (costs tokens every call)
    "context.memory_k": (0, 1, 2, 3, 5),                # similar past failures injected via $vectorSearch
    **ROUTING_PATHS,
}

# Gen 0: a deliberately weak harness. It can see some account data and can take any action,
# but has no policy access, no verification discipline and no memory.
SEED = {
    "rules": [],
    "context": {"include_policy_handbook": False, "memory_k": 0},
    "guardrails": list(LOCKED_GUARDRAILS),
    "tools": ["get_customer", "get_transactions", "get_subscription"],
    "routing": {"generator_model": "CHEAP", "repair_model": "CHEAP", "max_retries": 0, "temperature": 0},
}

SUPPORT_SPEC = GenomeSpec(LOCKED_GUARDRAILS, EVOLVABLE_GUARDRAILS, READ_TOOLS, LOCKED_TOOLS,
                          GUARDRAIL_REQUIRES, SETTABLE_PATHS, SEED)

# Operational actions the agent can finish with. They are sandboxed: recorded and validated, never executed.
ACTIONS = {
    "issue_refund": ("transaction_id",),
    "request_approval": ("transaction_id",),
    "issue_credit": ("invoice_id", "amount"),
    "cancel_subscription": ("subscription_id", "when"),
    "change_plan": ("subscription_id", "plan"),
    "reset_credentials": ("customer_id",),
    "escalate_case": ("reason",),
    "deny": ("reason",),
    "refuse": ("reason",),
}
MONEY_ACTIONS = ("issue_refund", "issue_credit", "request_approval")
REFUND_APPROVAL_LIMIT = 200.0
