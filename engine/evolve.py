"""Evolution loop CLI.

    python -m engine.evolve --generations 6 [--reset]

evaluate parent (train) -> retrieve failures -> meta-agent proposes one patch -> validate ->
evaluate child (train) -> gates -> if accepted: evaluate hidden holdout -> persist.
"""
from __future__ import annotations

import argparse
import json
import datetime as dt
import logging
import uuid

from engine import config, db, domains, gates, genome as genome_mod, memory, meta
from engine.evaluate import HOLDOUT, evaluate

log = logging.getLogger("harnessforge")
PUBLIC_METRICS = ("accuracy", "passed", "total", "runs", "by_family", "failure_counts", "cost_usd", "latency_ms")


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def emit(run_id: str, kind: str, generation: int | None, message: str, **data) -> None:
    log.info("[gen %s] %s: %s", generation, kind, message)
    db.hf().events.insert_one({"run_id": run_id, "type": kind, "generation": generation,
                               "message": message, "data": data, "ts": now()})


def public(metrics: dict) -> dict:
    return {k: metrics[k] for k in PUBLIC_METRICS}


def _evaluate_holdout(run_id: str, genome: dict, version: int) -> dict:
    emit(run_id, "evaluation_started", version, "evaluating hidden holdout (never shown to meta-agent)")
    holdout = public(evaluate(genome, HOLDOUT, run_id, version, role="holdout"))
    emit(run_id, "holdout_evaluated", version, f"holdout accuracy {holdout['accuracy']:.0%}",
         accuracy=holdout["accuracy"])
    return holdout


def _record_genome(run_id: str, version: int, parent_version: int | None, genome: dict, **fields) -> None:
    db.hf().genomes.insert_one({"run_id": run_id, "version": version, "parent_version": parent_version,
                                "genome": genome, "created_at": now(), **fields})


def _baseline(run_id: str) -> tuple[dict, dict, float]:
    seed = genome_mod.seed()
    emit(run_id, "generation_started", 0, "Gen 0: blank harness on the cheap model")
    train = evaluate(seed, "train", run_id, 0, role="parent")
    holdout = _evaluate_holdout(run_id, seed, 0)
    _record_genome(run_id, 0, None, seed, patch=None, rationale="seed genome", accepted=True,
                   train=public(train), holdout=holdout, train_accuracy=train["accuracy"],
                   holdout_accuracy=holdout["accuracy"], cost_usd=train["cost_usd"], latency_ms=train["latency_ms"])
    emit(run_id, "child_evaluation_complete", 0, f"Gen 0 train accuracy {train['accuracy']:.0%}",
         accuracy=train["accuracy"])
    return seed, train, train["cost_usd"] + holdout["cost_usd"]


def _regression_evidence(verdict: dict, child_train: dict) -> list[dict]:
    """What the child did wrong on TRAIN tasks the parent used to pass (lets the meta-agent learn from rejections)."""
    by_task = {f["task_id"]: f for f in child_train["failures"]}
    evidence = []
    for tid in verdict.get("regressed_tasks", []):
        f = by_task.get(tid)
        if f:
            output = f.get("generated_pipeline") or f.get("diagnosis") or f.get("action")
            evidence.append({"question": f["question"], "failure_type": f.get("failure_type"),
                             "why": (f.get("reason") or "")[:160], "child_output": json.dumps(output, default=str)[:240]})
    return evidence


def _generation(run_id: str, version: int, parent: dict, parent_version: int, parent_train: dict,
                history: list[dict]) -> tuple[dict, dict, int, float]:
    """Run one generation. Returns (new_parent, new_parent_train, new_parent_version, cost)."""
    emit(run_id, "generation_started", version, f"proposing mutation of Gen {parent_version}")
    proposal = meta.propose(parent, parent_train, run_id, version, history)
    evidence = {"query": proposal["memory_query"], "dominant_failure": proposal["dominant_failure"],
                "retrieved": proposal["retrieved"], "lessons": [l["lesson"] for l in proposal["lessons_used"]]}
    emit(run_id, "memory_retrieved", version, f"{len(proposal['retrieved'])} similar failures via $vectorSearch",
         dominant_failure=proposal["dominant_failure"])
    cost = proposal["meta_cost_usd"]
    if not proposal["valid"]:
        emit(run_id, "mutation_rejected", version, proposal["rationale"])
        _record_genome(run_id, version, parent_version, parent, patch=None, rationale=proposal["rationale"],
                       accepted=False, verdict={"accepted": False, "checks": {"valid_patch": False}},
                       memory_evidence=evidence)
        history.append({"patch": None, "accepted": False, "why": proposal["rationale"]})
        return parent, parent_train, parent_version, cost

    patch = proposal["patch"]
    child = genome_mod.apply_patch(parent, patch)
    emit(run_id, "mutation_proposed", version, genome_mod.describe_patch(patch),
         patch=patch, rationale=proposal.get("rationale"))
    child_train = evaluate(child, "train", run_id, version, role="candidate")
    cost += child_train["cost_usd"]
    verdict = gates.decide(parent_train, child_train)
    emit(run_id, "child_evaluation_complete", version,
         f"parent {parent_train['accuracy']:.0%} -> child {child_train['accuracy']:.0%}", verdict=verdict)

    fields = dict(patch=patch, rationale=proposal.get("rationale"), lesson=proposal.get("lesson"),
                  target_failure_type=proposal.get("target_failure_type"), diff=genome_mod.diff(parent, child),
                  accepted=verdict["accepted"], verdict=verdict, train=public(child_train),
                  parent_train=public(parent_train), train_accuracy=child_train["accuracy"],
                  regression_rate=verdict["regression_rate"], cost_usd=child_train["cost_usd"],
                  latency_ms=child_train["latency_ms"], memory_evidence=evidence)
    history.append({"patch": patch, "accepted": verdict["accepted"],
                    "train_accuracy": child_train["accuracy"], "checks": verdict["checks"],
                    "regressions": _regression_evidence(verdict, child_train)})
    if not verdict["accepted"]:
        _record_genome(run_id, version, parent_version, child, **fields)
        emit(run_id, "genome_rejected", version, f"REJECTED {genome_mod.describe_patch(patch)}", verdict=verdict)
        return parent, parent_train, parent_version, cost

    holdout = _evaluate_holdout(run_id, child, version)
    cost += holdout["cost_usd"]
    _record_genome(run_id, version, parent_version, child, holdout=holdout,
                   holdout_accuracy=holdout["accuracy"], **fields)
    if proposal.get("lesson"):
        memory.store_lesson(run_id, proposal["lesson"], version)
    emit(run_id, "genome_accepted", version, f"ACCEPTED {genome_mod.describe_patch(patch)}", verdict=verdict)
    return child, child_train, version, cost


def _start_run(generations: int) -> tuple[str, dict, dict, int, int, float, list[dict]]:
    run_id = uuid.uuid4().hex[:10]
    domain = domains.current()
    db.hf().runs.insert_one({"run_id": run_id, "started_at": now(), "status": "running",
                             "domain": domain.name, "domain_title": domain.title,
                             "generations": generations, "models": config.MODELS, "meta_model": config.META_MODEL,
                             "gates": config.GATES.__dict__})
    parent, parent_train, spent = _baseline(run_id)
    return run_id, parent, parent_train, 0, 1, spent, []


def _resume_run(run_id: str, generations: int) -> tuple[str, dict, dict, int, int, float, list[dict]]:
    """Rebuild evolution state from Atlas after a crash: MongoDB is the durable memory of the run."""
    docs = list(db.hf().genomes.find({"run_id": run_id}, {"_id": 0}).sort("version", 1))
    if not docs:
        raise SystemExit(f"no genomes recorded for run {run_id}")
    champion = [d for d in docs if d["accepted"]][-1]
    spent = sum(d.get("cost_usd", 0.0) + (d.get("holdout") or {}).get("cost_usd", 0.0) for d in docs)
    history = [{"patch": d.get("patch"), "accepted": d["accepted"], "train_accuracy": d.get("train_accuracy"),
                "checks": (d.get("verdict") or {}).get("checks")} for d in docs if d["version"] > 0]
    db.hf().runs.update_one({"run_id": run_id}, {"$set": {"status": "running", "generations": generations}})
    emit(run_id, "run_resumed", champion["version"],
         f"resumed from Atlas at Gen {champion['version']} after {len(docs) - 1} recorded candidates")
    # pass maps and failure details aren't persisted on genome docs, so re-measure the champion on train
    parent_train = evaluate(champion["genome"], "train", run_id, champion["version"], role="parent_reeval")
    return run_id, champion["genome"], parent_train, champion["version"], docs[-1]["version"] + 1, spent, history


def run(generations: int, reset: bool, resume: str | None = None) -> str:
    db.bootstrap()
    if reset and not resume:
        db.reset_run_data()
    db.wait_for_vector_indexes()
    from engine.evaluate import load_tasks
    memory.warm_queries([t["question"] for t in load_tasks()])
    state = _resume_run(resume, generations) if resume else _start_run(generations)
    run_id, parent, parent_train, parent_version, first_version, spent, history = state
    for version in range(first_version, generations + 1):
        if spent >= config.MAX_RUN_USD:
            emit(run_id, "budget_exhausted", version, f"spent ${spent:.2f} >= ${config.MAX_RUN_USD:.2f}")
            break
        parent, parent_train, parent_version, cost = _generation(
            run_id, version, parent, parent_version, parent_train, history)
        spent += cost
    db.hf().runs.update_one({"run_id": run_id}, {"$set": {"status": "complete", "finished_at": now(),
                                                         "best_version": parent_version, "spent_usd": spent}})
    emit(run_id, "evolution_complete", parent_version,
         f"best genome Gen {parent_version}: train {parent_train['accuracy']:.0%}, spent ${spent:.3f}")
    return run_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Evolve the HarnessForge agent harness")
    parser.add_argument("--generations", type=int, default=6)
    parser.add_argument("--reset", action="store_true", help="clear previous HarnessForge records first")
    parser.add_argument("--resume", metavar="RUN_ID", help="continue a crashed run from its last accepted genome")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    print(f"run_id={run(args.generations, args.reset, args.resume)}")


if __name__ == "__main__":
    main()
