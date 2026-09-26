"""Execute gold pipelines against Atlas and cache the expected results.

    python -m engine.evals.build_gold

Also sanity-checks diagnose tasks: their slow pipelines must currently COLLSCAN.
"""
from __future__ import annotations

import json

from engine import genome, tools
from engine.evaluate import GOLD_CACHE_PATH, load_tasks


def main() -> None:
    permissive = genome.seed()  # locked guardrails only
    gold: dict[str, list] = {}
    problems: list[str] = []
    for task in load_tasks():
        if task["family"] == "query":
            rows = tools.to_jsonable(tools.run_aggregate(task["collection"], task["gold_pipeline"], permissive))
            if not rows:
                problems.append(f"{task['id']}: gold returned 0 rows")
            gold[task["id"]] = rows
            print(f"{task['id']:4} {len(rows):3} rows  {json.dumps(rows[:3], default=str)[:150]}")
        elif task["family"] == "diagnose":
            plan = tools.explain_aggregate(task["collection"], task["slow_pipeline"], permissive)
            print(f"{task['id']:4} plan={plan}")
            if not plan["collection_scan"]:
                problems.append(f"{task['id']}: slow pipeline does not COLLSCAN ({plan})")
    GOLD_CACHE_PATH.write_text(json.dumps(gold, indent=1, default=str), encoding="utf-8")
    print(f"\ncached {len(gold)} gold result sets -> {GOLD_CACHE_PATH}")
    if problems:
        print("PROBLEMS:\n  " + "\n  ".join(problems))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
