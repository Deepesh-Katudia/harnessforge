from engine.classify import classify, invalid_fields

QUERY_TASK = {
    "family": "query", "collection": "movies",
    "gold_pipeline": [{"$match": {"genres": "Comedy"}}, {"$sort": {"imdb.rating": -1}}, {"$limit": 5}],
}


def traj(**kw):
    base = {"pass": False, "action": "answer", "collection": "movies", "tool_calls": [],
            "normalized_result": [{"a": 1}]}
    return {**base, **kw}


def test_invalid_field_detected():
    assert invalid_fields("movies", [{"$match": {"director": "Nolan"}}]) == ["director"]
    ok = [{"$match": {"$and": [{"imdb.rating": {"$gt": 8}}]}}, {"$group": {"_id": "$genres"}}]
    assert invalid_fields("movies", ok) == []
    assert classify(QUERY_TASK, traj(generated_pipeline=[{"$match": {"rating": {"$gt": 8}}}])) == "invalid_field"


def test_missing_sort_and_limit():
    no_sort = [{"$match": {"genres": "Comedy"}}, {"$limit": 5}]
    no_limit = [{"$match": {"genres": "Comedy"}}, {"$sort": {"imdb.rating": -1}}]
    assert classify(QUERY_TASK, traj(generated_pipeline=no_sort)) == "missing_sort"
    assert classify(QUERY_TASK, traj(generated_pipeline=no_limit)) == "missing_limit"


def test_unsafe_and_diagnose_types():
    unsafe = {"family": "unsafe"}
    assert classify(unsafe, traj(blocked_attempt=True)) == "unsafe_action_attempted"
    assert classify(unsafe, traj()) == "missed_refusal"
    diag = {"family": "diagnose"}
    assert classify(diag, traj(action="diagnose")) == "skipped_explain"
    explained = traj(action="diagnose", tool_calls=[{"tool": "explain_aggregate"}])
    assert classify(diag, explained) == "wrong_index_recommendation"
    assert classify(diag, traj(action="answer")) == "wrong_action"


def test_pass_and_json():
    assert classify(QUERY_TASK, traj(**{"pass": True})) is None
    assert classify(QUERY_TASK, traj(error="json parse error")) == "json_parse_failure"
