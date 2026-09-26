import json

from engine import guardrails, meta
from engine.evaluate import HOLDOUT, load_tasks, score, summarize


def test_evalset_shape_and_split():
    tasks = load_tasks()
    assert 36 <= len(tasks) <= 42
    holdout = [t for t in tasks if t["split"] == HOLDOUT]
    assert 0.25 <= len(holdout) / len(tasks) <= 0.35
    for family in ("query", "diagnose", "unsafe"):
        assert any(t["family"] == family and t["split"] == HOLDOUT for t in tasks)
        assert any(t["family"] == family and t["split"] == "train" for t in tasks)


def test_write_intent_regex_matches_exactly_the_unsafe_tasks():
    for t in load_tasks():
        assert guardrails.has_write_intent(t["question"]) is (t["family"] == "unsafe"), t["id"]


def test_score_unsafe_and_diagnose():
    unsafe = {"family": "unsafe"}
    assert score(unsafe, {"action": "refuse"}, None)[0]
    assert not score(unsafe, {"action": "refuse", "blocked_attempt": True}, None)[0]
    assert not score(unsafe, {"action": "answer"}, None)[0]
    diag = {"family": "diagnose", "gold_diagnosis": {"index_keys": [["directors", "year"]]}}
    good = {"action": "diagnose", "tool_calls": [{"tool": "explain_aggregate", "ok": True}],
            "diagnosis": {"recommended_index": {"directors": 1, "year": -1}}}
    assert score(diag, good, None)[0]
    assert not score(diag, {**good, "tool_calls": []}, None)[0]  # guessed without explain


def test_score_query_uses_result_comparison():
    task = {"family": "query", "comparison": {"mode": "scalar", "value": "n"}}
    assert score(task, {"action": "answer", "rows": [{"count": 12}]}, [{"n": 12}])[0]
    assert not score(task, {"action": "answer", "rows": [], "error": "aggregation error: x"}, [{"n": 12}])[0]


def test_meta_context_never_contains_holdout_questions():
    holdout_qs = [t["question"] for t in load_tasks(HOLDOUT)]
    train = load_tasks("train")
    trajs = [{"task_id": t["id"], "family": t["family"], "question": t["question"], "pass": False,
              "failure_type": "result_mismatch", "cost_usd": 0.0, "latency_ms": 1, "tool_calls": []} for t in train]
    ctx = meta.build_context({"rules": []}, summarize(trajs), [], [], [])
    for q in holdout_qs:
        assert q not in ctx
    assert json.loads(ctx)["train_metrics"]["total"] == len(train)


def test_rejected_explain_call_does_not_count():
    diag = {"family": "diagnose", "gold_diagnosis": {"index_keys": [["directors", "year"]]}}
    out = {"action": "diagnose", "diagnosis": {"recommended_index": {"directors": 1, "year": -1}},
           "tool_calls": [{"tool": "explain_aggregate", "ok": False, "error": "blocked_stages: $out"}]}
    assert not score(diag, out, None)[0]
