"""Seed the support world into Atlas and write the eval set.

    python -m engine.support.build

Data goes to the `hf_support` database (customers, subscriptions, transactions, invoices, policies).
Every third ticket of each kind is HOLDOUT: hidden from evolution, evaluated only after acceptance.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from engine import db
from engine.support import oracle, world
from engine.support.policies import POLICIES

SUPPORT_DB = "hf_support"
EVALSET_PATH = Path(__file__).parent / "evalset.json"


def _records(w: world.World, cid: str) -> tuple[dict, dict, list, list]:
    customer = next(c for c in w.customers if c["_id"] == cid)
    subscription = next(s for s in w.subscriptions if s["customer_id"] == cid)
    txns = [t for t in w.transactions if t["customer_id"] == cid]
    invoices = [i for i in w.invoices if i["customer_id"] == cid]
    return customer, subscription, txns, invoices


def build_tasks(w: world.World) -> list[dict]:
    tasks = []
    for n, ticket in enumerate(w.tickets):
        expected = oracle.resolve(ticket, *_records(w, ticket["customer_id"]))
        tasks.append({
            "id": f"s{n + 1:02d}_{ticket['kind']}",
            "family": world.FAMILY[ticket["kind"]],
            "kind": ticket["kind"],
            "split": "holdout" if ticket["variant"] % 3 == 2 else "train",
            "customer_id": ticket["customer_id"],
            "ticket_email": ticket["ticket_email"],
            "question": ticket["text"],
            "expected": expected,
            "expected_behavior": f"{expected['action']} {expected['args']} after checking {expected['required_evidence']}",
        })
    return tasks


def seed_atlas(w: world.World) -> None:
    sdb = db.client()[SUPPORT_DB]
    for name, docs in (("customers", w.customers), ("subscriptions", w.subscriptions),
                       ("transactions", w.transactions), ("invoices", w.invoices)):
        sdb[name].delete_many({})
        sdb[name].insert_many(docs)
        if name != "customers":
            sdb[name].create_index("customer_id")
    sdb.policies.delete_many({})
    sdb.policies.insert_many([{"_id": topic, "text": text, "version": 1} for topic, text in POLICIES.items()])


def main() -> None:
    w = world.build()
    tasks = build_tasks(w)
    EVALSET_PATH.write_text(json.dumps({"version": 1, "domain": "support", "tasks": tasks}, indent=1),
                            encoding="utf-8")
    seed_atlas(w)
    splits = Counter(t["split"] for t in tasks)
    actions = Counter(t["expected"]["action"] for t in tasks)
    print(f"wrote {len(tasks)} tickets ({splits['train']} train / {splits['holdout']} holdout) -> {EVALSET_PATH}")
    print(f"expected actions: {dict(actions)}")
    print(f"seeded {SUPPORT_DB}: {len(w.customers)} customers, {len(w.transactions)} transactions, "
          f"{len(w.invoices)} invoices, {len(POLICIES)} policies")


if __name__ == "__main__":
    main()
