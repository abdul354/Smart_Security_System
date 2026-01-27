import numpy as np
import cv2
import onnxruntime as ort
import os
from typing import Iterable, List, Optional

_WARNED_BAD_MODEL = False

# Global ONNX Session
session = None

def load_embedding_model():
    global session

    env_path = os.getenv("EMBEDDING_MODEL_PATH")
    candidates = [
        env_path,
        os.path.join("backend", "models", "arcfaceresnet100-8.onnx"),
        os.path.join("backend", "models", "facenet.onnx"),
    ]
    model_path = next((p for p in candidates if p and os.path.exists(p)), None)
    if not model_path:
        return None
    
    if session is None:
        try:
            opts = ort.SessionOptions()
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            session = ort.InferenceSession(
                model_path,
                sess_options=opts,
                providers=["CPUExecutionProvider"],
            )

            # Basic validation: ensure the graph exposes something that looks like an embedding.
            output_shapes = [o.shape for o in session.get_outputs()]
            has_embedding_like = False
            for shape in output_shapes:
                if not shape:
                    continue
                # Accept [1, D] or [D] style shapes.
                if len(shape) == 2 and isinstance(shape[1], int) and int(shape[1]) >= 16:
                    has_embedding_like = True
                    break
                if len(shape) == 1 and isinstance(shape[0], int) and int(shape[0]) >= 16:
                    has_embedding_like = True
                    break

            if not has_embedding_like:
                print(
                    "Embedding model looks invalid for embeddings. "
                    f"Path: {model_path}. Outputs: {output_shapes}."
                )
                session = None
                return None

            print(f"ONNX embedding model loaded from {model_path}")
        except Exception as e:
            print(f"Failed to load ONNX model: {e}")
            return None
    return session


def _pick_embedding_output(outputs: list[np.ndarray]) -> np.ndarray | None:
    """Pick the most likely embedding tensor from ONNX outputs."""
    candidates = []
    for out in outputs:
        if not isinstance(out, np.ndarray):
            continue

        # Allow squeezing singleton dims (e.g. (1,512,1,1) -> (512,)).
        try:
            squeezed = np.squeeze(out)
        except Exception:
            squeezed = out

        if isinstance(squeezed, np.ndarray):
            out = squeezed

        # Accept [D] embeddings.
        if out.ndim == 1 and out.shape[0] >= 16:
            candidates.append(out.reshape(1, -1))
            continue

        # Accept any (N, D) style tensor where D looks like an embedding length.
        if out.ndim == 2 and out.shape[0] >= 1 and out.shape[1] >= 16:
            candidates.append(out)

    if not candidates:
        return None

    # Prefer common embedding dims if present.
    for preferred in (512, 256, 160, 128):
        for c in candidates:
            if c.shape[1] == preferred:
                return c

    # Otherwise pick the largest vector dimension.
    return max(candidates, key=lambda a: int(a.shape[1]))


def _preprocess_face(face_bgr: np.ndarray, input_shape) -> np.ndarray:
    """Preprocess face crop to match common face-embedding ONNX models.

    Supports:
    - ArcFace (common): NCHW float32, 112x112, RGB, (x-127.5)/128
    - Facenet-like: NCHW float32, any square size, per-image standardization
    """
    # input_shape is something like [1, 3, 112, 112] (may include None/"None")
    h = 0
    w = 0
    if input_shape and len(input_shape) >= 4:
        if isinstance(input_shape[2], (int, np.integer)):
            h = int(input_shape[2])
        if isinstance(input_shape[3], (int, np.integer)):
            w = int(input_shape[3])
    if h <= 0 or w <= 0:
        # Fallback to previous default.
        h = w = 128

    face = cv2.resize(face_bgr, (w, h))
    face = face.astype(np.float32)

    # Heuristic: ArcFace models typically use 112x112.
    if h == 112 and w == 112:
        face = cv2.cvtColor(face, cv2.COLOR_BGR2RGB)
        face = (face - 127.5) / 128.0
    else:
        # Facenet-style "prewhiten"
        mean, std = face.mean(), face.std()
        if std < 1e-6:
            std = 1.0
        face = (face - mean) / std

    face = np.transpose(face, (2, 0, 1))
    return face


def _normalize_vectors(vectors: np.ndarray) -> List[Optional[np.ndarray]]:
    """Return a list of L2-normalized vectors (or None when invalid)."""
    results: List[Optional[np.ndarray]] = []
    if vectors.ndim != 2:
        try:
            count = int(vectors.shape[0])
        except Exception:
            count = 0
        return [None for _ in range(count)]

    norms = np.linalg.norm(vectors, axis=1)
    for vec, norm in zip(vectors, norms):
        if not np.isfinite(norm) or norm <= 0:
            results.append(None)
            continue
        results.append((vec / norm).astype(np.float32, copy=False))
    return results


def get_embeddings(faces: Iterable[np.ndarray]) -> List[Optional[np.ndarray]]:
    """Batch inference helper returning one embedding per face.

    Faces that fail preprocessing or inference yield ``None`` in-place, keeping
    the list aligned with the provided iterable.
    """
    sess = load_embedding_model()
    faces = list(faces)
    if sess is None or not faces:
        return [None for _ in faces]

    input_meta = sess.get_inputs()[0]
    preprocessed: List[np.ndarray] = []
    keep: List[int] = []
    for idx, face in enumerate(faces):
        if face is None or face.size == 0:
            continue
        try:
            tensor = _preprocess_face(face, input_meta.shape)
        except Exception:
            continue
        preprocessed.append(np.expand_dims(tensor, axis=0))
        keep.append(idx)

    if not preprocessed:
        return [None for _ in faces]

    inputs = {input_meta.name: np.concatenate(preprocessed, axis=0)}
    try:
        outputs = sess.run(None, inputs)
    except Exception as exc:
        print(f"Embedding batch inference error: {exc}")
        return [None for _ in faces]

    emb2d = _pick_embedding_output(outputs)
    if emb2d is None:
        return [None for _ in faces]

    if emb2d.shape[0] != inputs[input_meta.name].shape[0]:
        print(
            "Embedding model returned mismatched batch size."
            f" Expected {inputs[input_meta.name].shape[0]}, got {emb2d.shape[0]}."
        )
        return [None for _ in faces]

    normalized = _normalize_vectors(emb2d)
    results: List[Optional[np.ndarray]] = [None for _ in faces]
    for idx, vec in zip(keep, normalized):
        results[idx] = vec
    return results

def get_embedding(face_image):
    """
    Generate an embedding vector for a given face image (BGR).
    Output dimensionality depends on the loaded model (commonly 128 or 512).
    """
    global _WARNED_BAD_MODEL
    sess = load_embedding_model()
    if sess is None:
        return None

    # Preprocess based on the model input shape.
    input_meta = sess.get_inputs()[0]
    face = _preprocess_face(face_image, input_meta.shape)

    # 4. Inference
    try:
        inputs = {sess.get_inputs()[0].name: np.expand_dims(face, axis=0)}
        outputs = sess.run(None, inputs)

        emb2d = _pick_embedding_output(outputs)
        if emb2d is None:
            global _WARNED_BAD_MODEL
            if not _WARNED_BAD_MODEL:
                shapes = [getattr(o, "shape", None) for o in outputs]
                print(
                    "Embedding model output not recognized. "
                    "Expected something like (N, 128)/(N, 512). "
                    f"Got outputs: {shapes}."
                )
                _WARNED_BAD_MODEL = True
            return None

        # Guard against selecting a non-embedding tensor (e.g. detector head) that doesn't match batch size.
        expected_batch = int(inputs[sess.get_inputs()[0].name].shape[0])
        if emb2d.shape[0] != expected_batch:
            if not _WARNED_BAD_MODEL:
                shapes = [getattr(o, "shape", None) for o in outputs]
                print(
                    "Embedding output batch mismatch. "
                    f"Expected batch {expected_batch}, got {emb2d.shape[0]}. Outputs: {shapes}."
                )
                _WARNED_BAD_MODEL = True
            return None

        normalized = _normalize_vectors(emb2d)
        if not normalized:
            return None
        return normalized[0]
    except Exception as e:
        print(f"Inference error: {e}")
        return None
