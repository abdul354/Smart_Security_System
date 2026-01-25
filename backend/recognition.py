import chromadb
from backend.config import CHROMA_PATH, THRESHOLD
import numpy as np
import cv2
import time

from backend.supabase_db import list_persons as _list_persons_supabase

client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = client.get_collection("face_embeddings")

_PERSON_CACHE = {}
_PERSON_CACHE_AT = 0.0
_PERSON_CACHE_TTL = 60.0


def _load_persons_cached():
    global _PERSON_CACHE, _PERSON_CACHE_AT
    now = time.time()
    if _PERSON_CACHE and (now - _PERSON_CACHE_AT) < _PERSON_CACHE_TTL:
        return _PERSON_CACHE
    rows = _list_persons_supabase()
    _PERSON_CACHE = {row.get("person_id"): row for row in rows if row.get("person_id")}
    _PERSON_CACHE_AT = now
    return _PERSON_CACHE

def recognize_face(embedding):
    persons_lookup = _load_persons_cached()
    res = collection.query(query_embeddings=[embedding], n_results=1)
    if not res["ids"] or not res["metadatas"][0]:
        return None, None
    pid = res["metadatas"][0][0]["person_id"]
    distance = res["distances"][0][0]
    if distance > THRESHOLD:
        return None, distance
    person = persons_lookup.get(pid)
    return person, distance
