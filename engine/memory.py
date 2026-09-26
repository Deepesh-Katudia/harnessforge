"""Long-term memory: Voyage embeddings + Atlas Vector Search over failures and lessons.

Only TRAIN failures are ever embedded, so holdout details can never be
retrieved by the task agent or the meta-agent.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import threading
import time
from functools import lru_cache

from pymongo.errors import BulkWriteError

from engine import config, db

log = logging.getLogger(__name__)
_cache: dict[tuple[str, str], list[float]] = {}
_lock = threading.Lock()        # guards _cache
_api_lock = threading.Lock()    # serialises Voyage calls so parallel workers don't burst the rate limit
RATE_LIMIT_RETRIES = 6
RATE_LIMIT_SLEEP_S = 21         # free tier without billing is 3 requests/minute


class EmbeddingUnavailable(RuntimeError):
    """Voyage could not be reached; callers degrade to running without memory."""


@lru_cache(maxsize=1)
def _voyage():
    import voyageai  # heavy import; load lazily

    if not config.VOYAGE_API_KEY:
        raise RuntimeError("VOYAGE_API_KEY is not set")
    return voyageai.Client(api_key=config.VOYAGE_API_KEY, max_retries=3)


def _key(text: str, input_type: str) -> str:
    return hashlib.sha1(f"{config.VOYAGE_MODEL}|{input_type}|{text}".encode()).hexdigest()


def _load_persisted(texts: list[str], input_type: str) -> None:
    """Pull previously computed embeddings from Atlas into the in-process cache."""
    keys = {_key(t, input_type): t for t in texts}
    for doc in db.hf().embedding_cache.find({"_id": {"$in": list(keys)}}):
        with _lock:
            _cache[(keys[doc["_id"]], input_type)] = doc["v"]


def _call_voyage(texts: list[str], input_type: str) -> list[list[float]]:
    import voyageai

    for attempt in range(RATE_LIMIT_RETRIES):
        try:
            with _api_lock:
                return _voyage().embed(texts, model=config.VOYAGE_MODEL, input_type=input_type,
                                       output_dimension=config.EMBED_DIM).embeddings
        except voyageai.error.RateLimitError:
            log.warning("Voyage rate limited; backing off %ss (attempt %d)", RATE_LIMIT_SLEEP_S, attempt + 1)
            time.sleep(RATE_LIMIT_SLEEP_S)
        except voyageai.error.VoyageError as exc:
            raise EmbeddingUnavailable(str(exc)) from exc
    raise EmbeddingUnavailable("Voyage rate limit persisted after retries")


def embed(texts: list[str], input_type: str = "document") -> list[list[float]]:
    """Embed with an in-process + Atlas-persisted cache; raises EmbeddingUnavailable on failure."""
    missing = [t for t in dict.fromkeys(texts) if (t, input_type) not in _cache]
    if missing:
        _load_persisted(missing, input_type)
        missing = [t for t in missing if (t, input_type) not in _cache]
    if missing:
        vectors = _call_voyage(missing, input_type)
        now = dt.datetime.now(dt.timezone.utc)
        with _lock:
            for text, vec in zip(missing, vectors):
                _cache[(text, input_type)] = vec
        try:
            db.hf().embedding_cache.insert_many(
                [{"_id": _key(t, input_type), "v": v, "created_at": now} for t, v in zip(missing, vectors)],
                ordered=False)
        except BulkWriteError:
            pass  # another worker cached the same text first; duplicates are harmless
    return [_cache[(t, input_type)] for t in texts]


def warm_queries(questions: list[str]) -> None:
    """Embed all task questions in one batch so parallel workers never call Voyage for them."""
    try:
        embed(questions, "query")
    except EmbeddingUnavailable as exc:
        log.warning("could not pre-embed questions: %s", exc)


def failure_text(traj: dict) -> str:
    output = traj.get("generated_pipeline") or traj.get("diagnosis") or traj.get("action_args") or {}
    pipeline = json.dumps(output, default=str)[:400]
    return (f"Request: {traj['question']}\n"
            f"Failure type: {traj.get('failure_type')}\n"
            f"Why: {traj.get('reason') or traj.get('error') or ''}\n"
            f"Agent output: {traj.get('action')} {pipeline}")


def attach_embeddings(trajectories: list[dict]) -> list[dict]:
    """Return copies of trajectories with embeddings added to failed TRAIN runs."""
    targets = [i for i, t in enumerate(trajectories) if t["split"] == "train" and not t["pass"]]
    if not targets:
        return trajectories
    texts = [failure_text(trajectories[i]) for i in targets]
    try:
        vectors = embed(texts, "document")
    except EmbeddingUnavailable as exc:
        log.warning("failures stored without embeddings (memory degraded): %s", exc)
        return trajectories
    out = list(trajectories)
    for i, text, vec in zip(targets, texts, vectors):
        out[i] = {**trajectories[i], "failure_text": text, "embedding": vec}
    return out


_PROJECTION = {"_id": 0, "task_id": 1, "question": 1, "failure_type": 1, "reason": 1, "error": 1,
               "generated_pipeline": 1, "diagnosis": 1, "action": 1, "generation": 1,
               "score": {"$meta": "vectorSearchScore"}}


def similar_failures(query: str, k: int, run_id: str | None = None, before_generation: int | None = None) -> list[dict]:
    if k <= 0:
        return []
    try:
        vector = embed([query], "query")[0]
    except EmbeddingUnavailable as exc:
        log.warning("memory retrieval skipped: %s", exc)
        return []
    filt: dict = {"split": "train", "pass": False}
    if run_id:
        filt["run_id"] = run_id
    pipeline = [
        {"$vectorSearch": {"index": db.TRAJ_VECTOR_INDEX, "path": "embedding", "queryVector": vector,
                           "numCandidates": max(50, k * 20), "limit": k * 4, "filter": filt}},
        {"$project": _PROJECTION},
    ]
    rows = list(db.hf().trajectories.aggregate(pipeline, maxTimeMS=config.MAX_TIME_MS))
    if before_generation is not None:
        rows = [r for r in rows if r.get("generation", 0) < before_generation]
    # de-duplicate by question so memory isn't k copies of the same task
    seen, unique = set(), []
    for r in rows:
        if r["question"] not in seen:
            seen.add(r["question"])
            unique.append(r)
    return unique[:k]


def store_lesson(run_id: str, lesson: str, generation: int) -> None:
    try:
        vec = embed([lesson], "document")[0]
    except EmbeddingUnavailable as exc:
        log.warning("lesson not stored: %s", exc)
        return
    db.hf().lessons.insert_one({"run_id": run_id, "lesson": lesson, "source_generation": generation,
                                "embedding": vec, "created_at": dt.datetime.now(dt.timezone.utc)})


def similar_lessons(query: str, k: int, run_id: str | None = None) -> list[dict]:
    if k <= 0:
        return []
    try:
        vector = embed([query], "query")[0]
    except EmbeddingUnavailable as exc:
        log.warning("lesson retrieval skipped: %s", exc)
        return []
    stage: dict = {"index": db.LESSON_VECTOR_INDEX, "path": "embedding", "queryVector": vector,
                   "numCandidates": 50, "limit": k}
    if run_id:
        stage["filter"] = {"run_id": run_id}
    pipeline = [{"$vectorSearch": stage},
                {"$project": {"_id": 0, "lesson": 1, "source_generation": 1, "score": {"$meta": "vectorSearchScore"}}}]
    return list(db.hf().lessons.aggregate(pipeline, maxTimeMS=config.MAX_TIME_MS))
