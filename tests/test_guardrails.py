import pytest

from engine import genome as g
from engine import guardrails as gr


@pytest.mark.parametrize("pipeline", [
    [{"$match": {}}, {"$out": "hacked"}],
    [{"$merge": {"into": "x"}}],
    [{"$match": {"$expr": {"$function": {"body": "1", "args": [], "lang": "js"}}}}],
    [{"$group": {"_id": None, "x": {"$accumulator": {}}}}],
    [{"$match": {"$where": "true"}}],
    [{"$facet": {"a": [{"$out": "x"}]}}],
    [{"$lookup": {"from": "movies", "pipeline": [{"$merge": {"into": "y"}}], "as": "z"}}],
])
def test_blocked_stages_rejected_even_when_nested(pipeline):
    res = gr.check_pipeline("movies", pipeline, g.seed())
    assert not res.ok and "blocked_stages" in res.reason


def test_non_allowlisted_collection_rejected():
    assert not gr.check_pipeline("users", [{"$match": {}}], g.seed()).ok
    lookup = [{"$lookup": {"from": "users", "localField": "a", "foreignField": "b", "as": "c"}}]
    assert not gr.check_pipeline("movies", lookup, g.seed()).ok
    assert not gr.check_pipeline("movies", [{"$unionWith": "accounts"}], g.seed()).ok  # cross-db


def test_lookup_into_allowlisted_same_db_ok():
    lookup = [{"$lookup": {"from": "movies", "localField": "movie_id", "foreignField": "_id", "as": "m"}}]
    assert gr.check_pipeline("comments", lookup, g.seed()).ok


def test_malformed_pipeline_rejected():
    assert not gr.check_pipeline("movies", {"$match": {}}, g.seed()).ok
    assert not gr.check_pipeline("movies", [{"$match": {}, "$limit": 1}], g.seed()).ok


def test_limit_cap_only_when_enabled():
    base = [{"$sort": {"year": -1}}, {"$limit": 500}]
    assert gr.check_pipeline("movies", base, g.seed()).pipeline == base
    genome = g.apply_patch(g.seed(), {"op": "enable_guardrail", "value": "limit_cap"})
    assert gr.check_pipeline("movies", base, genome).pipeline[-1] == {"$limit": 20}
    assert base[-1] == {"$limit": 500}  # input not mutated
    assert gr.check_pipeline("movies", [{"$count": "n"}], genome).pipeline == [{"$count": "n"}]
    assert gr.check_pipeline("movies", [{"$match": {}}], genome).pipeline[-1] == {"$limit": 20}


def test_pipeline_length_cap():
    genome = g.apply_patch(g.seed(), {"op": "enable_guardrail", "value": "pipeline_length_cap"})
    assert not gr.check_pipeline("movies", [{"$match": {}}] * 11, genome).ok


@pytest.mark.parametrize("text,expected", [
    ("Delete all movies released before 1950.", True),
    ("Drop the comments collection, it is too big.", True),
    ("Update every movie rated 'R' to 'NC-17'.", True),
    ("Write the top 10 movies into a new collection called best_movies.", True),
    ("Create an index on directors and year.", True),
    ("Show the five highest-rated comedies after 2015.", False),
    ("Why is the query filtering movies by director and sorting by year slow? Recommend an index.", False),
])
def test_write_intent(text, expected):
    assert gr.has_write_intent(text) is expected
