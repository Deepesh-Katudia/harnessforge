import pytest

from engine import config, genome, tools


class FakeCursor(list):
    def close(self):
        pass


class FakeColl:
    def __init__(self):
        self.calls = []

    def aggregate(self, pipeline, **kwargs):
        self.calls.append((pipeline, kwargs))
        return FakeCursor([{"n": i} for i in range(200)])


def test_run_aggregate_always_sets_max_time_and_caps_rows(monkeypatch):
    fake = FakeColl()
    monkeypatch.setattr(tools.db, "source", lambda name: fake)
    rows = tools.run_aggregate("movies", [{"$match": {}}], genome.seed())
    assert fake.calls[0][1]["maxTimeMS"] == config.MAX_TIME_MS
    assert len(rows) == config.RESULT_CAP


def test_write_stage_never_reaches_database(monkeypatch):
    fake = FakeColl()
    monkeypatch.setattr(tools.db, "source", lambda name: fake)
    with pytest.raises(tools.GuardrailViolation) as exc:
        tools.run_aggregate("movies", [{"$out": "x"}], genome.seed())
    assert exc.value.blocked and fake.calls == []


def test_tool_not_in_genome_is_unavailable():
    with pytest.raises(tools.ToolError):
        tools.call_tool("explain_aggregate", {"collection": "movies", "pipeline": []}, genome.seed())


def test_extended_json_dates_parsed():
    out = tools.parse_pipeline([{"$match": {"saleDate": {"$gte": {"$date": "2016-01-01T00:00:00Z"}}}}])
    assert out[0]["$match"]["saleDate"]["$gte"].year == 2016
