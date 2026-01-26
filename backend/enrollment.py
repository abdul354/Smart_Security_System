import uuid
from collections import deque
from datetime import datetime
import numpy as np
import chromadb
from chromadb.config import Settings
from backend.config import CHROMA_PATH, SAMPLES_REQUIRED
from backend.recognition import recognize_face
from backend.supabase_db import upsert_person

client = chromadb.PersistentClient(
    path=CHROMA_PATH,
    settings=Settings(anonymized_telemetry=False),
)
collection = client.get_collection("face_embeddings")

# Enrollment session state
CURRENT_SESSION = {
    "person_id": None,
    "embeddings": [],
    "count": 0
}


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    vec = vec.astype(np.float32, copy=False)
    n = float(np.linalg.norm(vec))
    if not np.isfinite(n) or n <= 0:
        raise ValueError("Invalid embedding norm")
    return vec / n


def _robust_centroid(embeddings: np.ndarray) -> np.ndarray:
    """Compute a centroid with light outlier rejection.

    Uses cosine distance to an initial mean vector and drops samples that are far
    beyond the median absolute deviation (MAD).
    """
    if embeddings.ndim != 2 or embeddings.shape[0] < 1:
        raise ValueError("No embeddings")

    embs = np.stack([_l2_normalize(e) for e in embeddings], axis=0)
    centroid0 = _l2_normalize(np.mean(embs, axis=0))

    # cosine distance since vectors are L2-normalized
    d = 1.0 - np.clip(np.dot(embs, centroid0), -1.0, 1.0)
    if embs.shape[0] < 4:
        return centroid0

    med = float(np.median(d))
    mad = float(np.median(np.abs(d - med))) + 1e-6
    thresh = med + 3.5 * mad
    keep = d <= thresh

    # Ensure we don't drop too much.
    if int(np.sum(keep)) < max(3, int(0.6 * embs.shape[0])):
        return centroid0

    centroid = _l2_normalize(np.mean(embs[keep], axis=0))
    return centroid

def generate_person_id():
    pid = f"PID_{uuid.uuid4().hex[:8]}"
    CURRENT_SESSION.update({
        "person_id": pid,
        "embeddings": [],
        "count": 0,
        # Reset pose gating state stored in CURRENT_SESSION by main.py
        "pose_center": None,
        "pose_center_samples": [],
        "valid_streak": 0,
        "pose_history": deque(maxlen=6),
    })
    return pid

def add_embedding(embedding):
    if embedding is None:
        raise ValueError("Embedding is None")
    emb = np.asarray(embedding, dtype=np.float32)
    if emb.ndim != 1 or emb.size < 16:
        raise ValueError(f"Invalid embedding shape: {getattr(emb, 'shape', None)}")
    if not np.all(np.isfinite(emb)):
        raise ValueError("Embedding contains NaN/Inf")

    emb = _l2_normalize(emb)
    CURRENT_SESSION["embeddings"].append(emb.tolist())
    CURRENT_SESSION["count"] += 1

    done = CURRENT_SESSION["count"] >= SAMPLES_REQUIRED
    return done, CURRENT_SESSION["count"]


def finalize_enrollment(display_name, role, department, access_status):
    if CURRENT_SESSION["person_id"] is None:
        raise ValueError("No active enrollment session")

    if len(CURRENT_SESSION["embeddings"]) < SAMPLES_REQUIRED:
        raise ValueError("Not enough face samples")

    embeddings = np.array(CURRENT_SESSION["embeddings"], dtype=np.float32)
    centroid = _robust_centroid(embeddings)

    
    test_emb = centroid.tolist()
    person, dist = recognize_face(test_emb)

    if person is not None:
        raise ValueError("Person already exists")

    pid = CURRENT_SESSION["person_id"]

    collection.add(
        embeddings=[centroid.tolist()],
        metadatas=[
            {
                "person_id": pid,
                "display_name": display_name,
                "role": role,
                "department": department,
                "access_status": access_status,
            }
        ],
        ids=[f"{pid}_0"]
    )

    try:
        upsert_person(
            person_id=pid,
            display_name=display_name,
            role=role,
            department=department,
            access_status=access_status,
            enrolled_at=datetime.now(),
        )
    except Exception as exc:
        # Enrollment should still succeed even if the remote DB is unreachable.
        print(f"Warning: Supabase upsert failed: {exc}", flush=True)

    CURRENT_SESSION["person_id"] = None
    CURRENT_SESSION["embeddings"] = []

