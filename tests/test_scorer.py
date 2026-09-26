import datetime as dt

from bson import Decimal128, ObjectId

from engine import scorer as s

GOLD = [{"title": "A", "rating": 9.1}, {"title": "B", "rating": 8.8}, {"title": "C", "rating": 8.8}]
ORDERED = {"mode": "ordered", "key": "title", "value": "rating"}


def test_ordered_accepts_differently_shaped_docs():
    result = [{"_id": ObjectId(), "name": "a", "imdb": {"rating": 9.1}}, {"movie": "B"}, {"movie": "C"}]
    assert s.compare(result, GOLD, ORDERED)[0]


def test_ordered_rejects_wrong_order_but_allows_ties():
    assert not s.compare([{"t": "B"}, {"t": "A"}, {"t": "C"}], GOLD, ORDERED)[0]
    assert s.compare([{"t": "A"}, {"t": "C", "r": 8.8}, {"t": "B", "r": 8.8}], GOLD, ORDERED)[0]


def test_unordered_and_row_count():
    shuffled = [{"t": "C"}, {"t": "A"}, {"t": "B"}]
    assert s.compare(shuffled, GOLD, {"mode": "unordered", "key": "title"})[0]
    assert not s.compare(shuffled[:2], GOLD, {"mode": "unordered", "key": "title"})[0]


def test_scalar_with_numeric_tolerance_and_decimal():
    gold = [{"_id": None, "avg": 6.6634}]
    cmp = {"mode": "scalar", "value": "avg"}
    assert s.compare([{"x": 6.66}], gold, cmp)[0]
    assert s.compare([{"x": Decimal128("6.6634")}], gold, cmp)[0]
    assert not s.compare([{"x": 7.1}], gold, cmp)[0]
    assert not s.compare([{"x": 6.66}, {"y": 1}], gold, cmp)[0]


def test_normalize_handles_bson():
    oid = ObjectId()
    assert s.normalize(oid) == str(oid)
    assert s.normalize(dt.datetime(2020, 1, 1)) == "2020-01-01T00:00:00"
    assert s.normalize(" Comedy ") == "comedy"
    assert s.normalize(3) == 3.0


def test_index_keys_formats():
    assert s.index_keys({"directors": 1, "year": -1}) == ["directors", "year"]
    assert s.index_keys([["directors", 1], ["year", -1]]) == ["directors", "year"]
    assert s.index_keys({"keys": {"a": 1}}) == ["a"]
    assert s.index_keys("genres_1_year_-1") == ["genres", "year"]


def test_score_diagnosis():
    gold = {"index_keys": [["directors", "year"]]}
    assert s.score_diagnosis({"recommended_index": {"directors": 1, "year": -1}}, gold)[0]
    assert not s.score_diagnosis({"recommended_index": {"year": -1, "directors": 1}}, gold)[0]
    assert not s.score_diagnosis(None, gold)[0]
