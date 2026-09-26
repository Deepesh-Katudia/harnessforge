"""MongoDB Atlas handles and index bootstrap."""
from __future__ import annotations

import time
from functools import lru_cache

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.database import Database
from pymongo.operations import SearchIndexModel

from engine import config

TRAJ_VECTOR_INDEX = "traj_vec"
LESSON_VECTOR_INDEX = "lesson_vec"
HF_COLLECTIONS = ("genomes", "trajectories", "lessons", "events", "runs")


@lru_cache(maxsize=1)
def client() -> MongoClient:
    if not config.MONGODB_URI:
        raise RuntimeError("MONGODB_URI is not set (copy .env.example to .env)")
    return MongoClient(config.MONGODB_URI, appname="harnessforge", serverSelectionTimeoutMS=15000)


def hf() -> Database:
    return client()[config.HF_DB]


def source(collection: str):
    """Handle to an allowlisted task collection (caller must have run guardrails)."""
    db_name, coll_name = config.ALLOWED_COLLECTIONS[collection]
    return client()[db_name][coll_name]


def _vector_definition(filters: list[str]) -> dict:
    fields = [{"type": "vector", "path": "embedding", "numDimensions": config.EMBED_DIM, "similarity": "cosine"}]
    fields += [{"type": "filter", "path": f} for f in filters]
    return {"fields": fields}


def _ensure_vector_index(coll, name: str, filters: list[str]) -> None:
    existing = {ix["name"] for ix in coll.list_search_indexes()}
    if name not in existing:
        coll.create_search_index(SearchIndexModel(definition=_vector_definition(filters), name=name, type="vectorSearch"))


def wait_for_vector_indexes(timeout_s: int = 180) -> None:
    deadline = time.time() + timeout_s
    targets = [(hf().trajectories, TRAJ_VECTOR_INDEX), (hf().lessons, LESSON_VECTOR_INDEX)]
    while time.time() < deadline:
        ready = all(
            any(ix["name"] == name and ix.get("queryable") for ix in coll.list_search_indexes())
            for coll, name in targets
        )
        if ready:
            return
        time.sleep(3)
    raise TimeoutError("vector search indexes not queryable yet")


def bootstrap() -> None:
    db = hf()
    for name in HF_COLLECTIONS:
        if name not in db.list_collection_names():
            db.create_collection(name)
    db.genomes.create_index([("run_id", ASCENDING), ("version", ASCENDING)])
    db.trajectories.create_index([("run_id", ASCENDING), ("generation", ASCENDING)])
    db.events.create_index([("run_id", ASCENDING), ("ts", DESCENDING)])
    db.runs.create_index([("started_at", DESCENDING)])
    _ensure_vector_index(db.trajectories, TRAJ_VECTOR_INDEX, ["split", "pass", "run_id"])
    _ensure_vector_index(db.lessons, LESSON_VECTOR_INDEX, ["run_id"])


def reset_run_data() -> None:
    """Clear HarnessForge records but keep collections (and their vector indexes)."""
    db = hf()
    for name in HF_COLLECTIONS:
        db[name].delete_many({})
