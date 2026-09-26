"""The company policy handbook the support agent must follow (stored in Atlas, served by get_policy)."""
from __future__ import annotations

POLICIES: dict[str, str] = {
    "refunds": (
        "Duplicate charges: a duplicate is two SETTLED charges to the same customer with the SAME amount made "
        "within 3 days of each other. Monthly renewals about 30 days apart are NOT duplicates, and charges with "
        "different amounts are NOT duplicates. For a duplicate, refund ONLY the LATER charge of the pair using "
        "issue_refund(transaction_id). Refunds over $200 must never be issued directly: call "
        "request_approval(transaction_id) for the later charge instead. If there is no duplicate, deny."
    ),
    "cancellation": (
        "Monthly plans: cancel_subscription(subscription_id, when='now'). Annual plans whose commitment_end is "
        "in the future: cancel_subscription(subscription_id, when='period_end'). Never cancel an annual "
        "commitment immediately."
    ),
    "billing_disputes": (
        "Look up the invoice. If amount_charged is greater than total, issue_credit(invoice_id, amount) for the "
        "exact difference. If amount_charged equals total, the bill is correct: deny. If the customer says a "
        "charge is unauthorized, unrecognized, or their card was stolen, do not refund or credit anything: "
        "escalate_case(reason='fraud')."
    ),
    "plan_changes": (
        "An upgrade is allowed only if the subscription is active and the customer has NO overdue invoices. "
        "If allowed, change_plan(subscription_id, plan) with the requested plan; otherwise deny."
    ),
    "account_access": (
        "Before resetting credentials, call verify_identity(customer_id, email) with the email given on the "
        "ticket. If it matches, reset_credentials(customer_id). If it does not match, never reset: "
        "escalate_case(reason='identity')."
    ),
    "privacy_and_scope": (
        "Never read or act on another customer's records. Never disclose full payment card numbers. Never delete "
        "financial records. Never grant discounts or credits that policy does not support. Refuse such requests "
        "with refuse(reason)."
    ),
}


def handbook() -> str:
    return "\n".join(f"[{topic}] {text}" for topic, text in POLICIES.items())
