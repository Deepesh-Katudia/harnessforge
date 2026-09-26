"""Benchmark domains. HarnessForge is the product; a domain is the proving ground it hardens.

    HF_DOMAIN=support   (default) customer-support operations agent
    HF_DOMAIN=mongodb   MongoDB database-operations agent

A domain supplies the evolvable genome surface, the eval tasks, the task agent,
and a deterministic scorer + failure classifier. The evolution loop, gates,
memory and meta-agent are shared.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

from engine.genome import GenomeSpec

ENGINE_DIR = Path(__file__).parent


@dataclass(frozen=True)
class Domain:
    name: str
    title: str
    agent_description: str          # what the task agent does, for the meta-agent prompt
    spec: GenomeSpec
    evalset_path: Path
    load_gold: Callable[[], dict]
    run_task: Callable[..., dict]
    score: Callable[[dict, dict, object], tuple[bool, str]]
    classify: Callable[[dict, dict], str | None]

    def load_tasks(self, split: str | None = None) -> list[dict]:
        tasks = json.loads(self.evalset_path.read_text(encoding="utf-8"))["tasks"]
        return [t for t in tasks if split is None or t["split"] == split]


def _mongodb() -> Domain:
    from engine import agent, classify, evaluate
    from engine.genome import MONGODB_SPEC
    return Domain(
        name="mongodb",
        title="MongoDB database-operations agent",
        agent_description=("The task agent answers MongoDB database requests (queries, slow-query diagnosis, "
                           "and requests it must refuse because they would write data)."),
        spec=MONGODB_SPEC,
        evalset_path=ENGINE_DIR / "evals" / "evalset.json",
        load_gold=evaluate.load_mongodb_gold,
        run_task=agent.run_task,
        score=evaluate.score,
        classify=classify.classify,
    )


def _support() -> Domain:
    from engine.support import agent, scoring, spec
    return Domain(
        name="support",
        title="Customer-support operations agent",
        agent_description=("The task agent resolves customer-support tickets (duplicate charges, cancellations, "
                           "billing disputes, plan changes, account access) by reading account data through tools "
                           "and taking exactly one operational action (refund, credit, cancel, change plan, reset "
                           "credentials, request approval, escalate, deny, or refuse). It must follow company "
                           "policy and verify evidence before financial or security-sensitive actions."),
        spec=spec.SUPPORT_SPEC,
        evalset_path=ENGINE_DIR / "support" / "evalset.json",
        load_gold=lambda: {},
        run_task=agent.run_task,
        score=scoring.score,
        classify=scoring.classify,
    )


_BUILDERS = {"mongodb": _mongodb, "support": _support}


def name() -> str:
    return os.getenv("HF_DOMAIN", "support")


@lru_cache(maxsize=None)
def get(domain_name: str) -> Domain:
    if domain_name not in _BUILDERS:
        raise ValueError(f"unknown HF_DOMAIN {domain_name!r}; choose from {sorted(_BUILDERS)}")
    return _BUILDERS[domain_name]()


def current() -> Domain:
    return get(name())
