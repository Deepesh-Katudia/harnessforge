"""Read-only database tools exposed to the task agent.

Every tool validates its inputs; anything that executes a pipeline goes through
the guardrail registry first and always runs with maxTimeMS and a result cap.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any

from bson import ObjectId, json_util
from pymongo.errors import PyMongoError

from engine import config, db, guardrails, schema

HIDDEN_FIELDS = {"plot": 0, "fullplot": 0, "poster": 0, "plot_embedding": 0, "plot_embedding_voyage_3_large": 0}


class ToolError(Exception):
    """A tool call failed in a way the agent should see."""


class GuardrailViolation(ToolError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason
        self.blocked = reason.startswith("blocked_stages")


def to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if hasattr(value, "to_decimal"):
        return float(value.to_decimal())
    return value


def parse_pipeline(pipeline: Any) -> Any:
    """Accept Extended JSON ({'$date': ...}, {'$oid': ...}) from the model."""
    try:
        return json_util.loads(json.dumps(pipeline))
    except (TypeError, ValueError) as exc:
        raise ToolError(f"pipeline is not valid JSON: {exc}") from exc


def _checked(collection: str, pipeline: Any, genome: dict) -> list:
    result = guardrails.check_pipeline(collection, pipeline, genome)
    if not result.ok:
        raise GuardrailViolation(result.reason)
    return result.pipeline


def run_aggregate(collection: str, pipeline: Any, genome: dict) -> list[dict]:
    safe = _checked(collection, parse_pipeline(pipeline), genome)
    try:
        cursor = db.source(collection).aggregate(safe, maxTimeMS=config.MAX_TIME_MS, batchSize=config.RESULT_CAP)
        rows = []
        for doc in cursor:
            rows.append(doc)
            if len(rows) >= config.RESULT_CAP:
                break
        cursor.close()
        return rows
    except PyMongoError as exc:
        raise ToolError(f"aggregation error: {exc}") from exc


def explain_aggregate(collection: str, pipeline: Any, genome: dict) -> dict:
    safe = _checked(collection, parse_pipeline(pipeline), genome)
    db_name, coll_name = config.ALLOWED_COLLECTIONS[collection]
    try:
        raw = db.client()[db_name].command(
            "explain",
            {"aggregate": coll_name, "pipeline": safe, "cursor": {}},
            verbosity="queryPlanner",
            maxTimeMS=config.MAX_TIME_MS,
        )
    except PyMongoError as exc:
        raise ToolError(f"explain error: {exc}") from exc
    return summarize_explain(raw)


def summarize_explain(raw: dict) -> dict:
    """Reduce a verbose explain document to the plan stages and index names."""
    stages: list[str] = []
    indexes: list[str] = []

    def walk(node: Any):
        if isinstance(node, dict):
            if "stage" in node and isinstance(node["stage"], str):
                stages.append(node["stage"])
            if "indexName" in node:
                indexes.append(node["indexName"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    planner = raw.get("queryPlanner") or next(
        (s.get("$cursor", {}).get("queryPlanner") for s in raw.get("stages", []) if "$cursor" in s), None
    ) or raw
    walk(planner.get("winningPlan", planner))
    return {
        "winning_plan_stages": stages,
        "indexes_used": sorted(set(indexes)),
        "collection_scan": "COLLSCAN" in stages,
        "in_memory_sort": "SORT" in stages,
    }


def list_indexes(collection: str) -> list[dict]:
    if collection not in config.ALLOWED_COLLECTIONS:
        raise GuardrailViolation(f"allowed_collections: {collection!r} is not allowlisted")
    return [{"name": ix["name"], "key": dict(ix["key"])} for ix in db.source(collection).list_indexes()]


def sample_docs(collection: str, k: int) -> list[dict]:
    if collection not in config.ALLOWED_COLLECTIONS:
        raise GuardrailViolation(f"allowed_collections: {collection!r} is not allowlisted")
    k = max(0, min(int(k), 3))
    query = {"imdb.rating": {"$type": "double"}} if collection == "movies" else {}
    projection = HIDDEN_FIELDS if collection == "movies" else None
    return list(db.source(collection).find(query, projection, max_time_ms=config.MAX_TIME_MS).limit(k))


def collection_stats(collection: str) -> dict:
    if collection not in config.ALLOWED_COLLECTIONS:
        raise GuardrailViolation(f"allowed_collections: {collection!r} is not allowlisted")
    coll = db.source(collection)
    return {"collection": collection, "estimated_documents": coll.estimated_document_count(),
            "index_count": len(list(coll.list_indexes()))}


def get_schema(collection: str | None = None) -> str:
    if collection and collection not in schema.SCHEMAS:
        raise GuardrailViolation(f"allowed_collections: {collection!r} is not allowlisted")
    return schema.render(collection)


TOOL_DOCS = {
    "get_schema": 'get_schema(collection?) -> field list and types. args: {"collection": "movies"}',
    "sample_docs": 'sample_docs(collection, k) -> up to 3 example documents. args: {"collection": "movies", "k": 2}',
    "list_indexes": 'list_indexes(collection) -> existing indexes. args: {"collection": "movies"}',
    "explain_aggregate": 'explain_aggregate(collection, pipeline) -> query plan summary (COLLSCAN/IXSCAN/SORT). '
                         'args: {"collection": "movies", "pipeline": [...]}',
    "run_aggregate": 'run_aggregate(collection, pipeline) -> result rows (read-only). '
                     'args: {"collection": "movies", "pipeline": [...]}',
    "collection_stats": 'collection_stats(collection) -> document and index counts. args: {"collection": "movies"}',
}


def call_tool(name: str, args: dict, genome: dict) -> Any:
    """Dispatch a tool call if the genome allows it."""
    if name not in genome["tools"]:
        raise ToolError(f"tool {name!r} is not available in this harness")
    if not isinstance(args, dict):
        raise ToolError("args must be an object")
    coll = args.get("collection", "movies")
    if name == "get_schema":
        return get_schema(args.get("collection"))
    if name == "sample_docs":
        return to_jsonable(sample_docs(coll, args.get("k", 2)))
    if name == "list_indexes":
        return list_indexes(coll)
    if name == "explain_aggregate":
        return explain_aggregate(coll, args.get("pipeline", []), genome)
    if name == "run_aggregate":
        return to_jsonable(run_aggregate(coll, args.get("pipeline", []), genome)[:10])
    if name == "collection_stats":
        return collection_stats(coll)
    raise ToolError(f"unknown tool {name!r}")
