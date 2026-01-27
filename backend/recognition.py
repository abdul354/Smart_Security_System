import chromadb
from chromadb.config import Settings
from backend.config import CHROMA_PATH, THRESHOLD
import numpy as np
import cv2
import time
import logging

from backend.supabase_db import list_persons as _list_persons_supabase

client = chromadb.PersistentClient(
    path=CHROMA_PATH,
    settings=Settings(anonymized_telemetry=False),
)

logger = logging.getLogger("smart_security.recognition")

_collection = None

def _get_collection():
    """Get or create the face_embeddings collection."""
    global _collection
    if _collection is not None:
        return _collection
    try:
        _collection = client.get_collection("face_embeddings")
    except ValueError:
        # Collection doesn't exist, create it
        _collection = client.create_collection("face_embeddings")
        logger.info("Created face_embeddings collection")
    return _collection

_PERSON_CACHE = {}
_PERSON_CACHE_AT = 0.0
_PERSON_CACHE_TTL = 60.0

_PERSON_CACHE_ERROR_LOGGED = False


def _load_persons_cached():
    global _PERSON_CACHE, _PERSON_CACHE_AT, _PERSON_CACHE_ERROR_LOGGED
    now = time.time()
    if _PERSON_CACHE and (now - _PERSON_CACHE_AT) < _PERSON_CACHE_TTL:
        return _PERSON_CACHE
    try:
        rows = _list_persons_supabase()
    except Exception as exc:
        if not _PERSON_CACHE_ERROR_LOGGED:
            logger.warning("Supabase persons fetch failed: %s", exc)
            _PERSON_CACHE_ERROR_LOGGED = True
        rows = []
    else:
        _PERSON_CACHE_ERROR_LOGGED = False

    _PERSON_CACHE = {row.get("person_id"): row for row in rows if row.get("person_id")}
    _PERSON_CACHE_AT = now
    return _PERSON_CACHE

def recognize_face(embedding):
    persons_lookup = _load_persons_cached()
    if embedding is None:
        return None, None

    # Chroma expects plain Python lists for embeddings.
    if isinstance(embedding, np.ndarray):
        embedding = embedding.astype(np.float32).ravel().tolist()
    elif not isinstance(embedding, list):
        try:
            embedding = list(embedding)
        except Exception:
            return None, None

    try:
        collection = _get_collection()
        res = collection.query(query_embeddings=[embedding], n_results=1)
    except Exception as exc:
        logger.warning("Chroma query failed: %s", exc)
        return None, None
    if not res["ids"] or not res["metadatas"][0]:
        return None, None
    meta = res["metadatas"][0][0] or {}
    pid = meta.get("person_id")
    if not pid:
        return None, None
    distance = res["distances"][0][0]
    if distance > THRESHOLD:
        logger.info(
            "Recognition below threshold: pid=%s distance=%.3f threshold=%.3f",
            pid,
            distance,
            THRESHOLD,
        )
        return None, distance
    person = persons_lookup.get(pid) or {
        "person_id": pid,
        "display_name": meta.get("display_name", pid),
        "role": meta.get("role", ""),
        "department": meta.get("department", ""),
        "access_status": meta.get("access_status", ""),
    }
    return person, distance
