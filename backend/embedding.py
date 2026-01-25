import numpy as np
import cv2
import onnxruntime as ort
import os

# Global ONNX Session
session = None

def load_embedding_model():
    global session
    model_path = os.path.join("backend", "models", "facenet.onnx")
    if not os.path.exists(model_path):
        # Silent return or print once? 
        # Printing here might spam logs if called in loop, 
        # but session check handles it.
        return None
    
    if session is None:
        try:
            session = ort.InferenceSession(model_path)
            print(f"ONNX FaceNet model loaded from {model_path}")
        except Exception as e:
            print(f"Failed to load ONNX model: {e}")
            return None
    return session

def get_embedding(face_image):
    """
    Generate 128-d embedding for a given face image (BGR).
    Pre-processing: Resize to 160x160, whiten (standardize), NCHW format.
    """
    sess = load_embedding_model()
    if sess is None:
        # Return zeros if model not found yet (so server doesn't crash)
        return np.zeros(128, dtype=np.float32)

    # 1. Resize
    face = cv2.resize(face_image, (128, 128))

    # 2. Standardize (Whitening) -> (x - mean) / std
    face = face.astype(np.float32)
    mean, std = face.mean(), face.std()
    if std < 1e-6:
        std = 1.0  # avoid divide by zero
    face = (face - mean) / std

    # 3. HWC to NCHW (1, 3, 128, 128)
    face = np.transpose(face, (2, 0, 1))
    face = np.expand_dims(face, axis=0)

    # 4. Inference
    try:
        inputs = {sess.get_inputs()[0].name: face}
        embeddings = sess.run(None, inputs)[0]  # shape (1, 128)
        
        # 5. Normalize embedding to unit length (L2 norm)
        embedding = embeddings[0]
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm

        return embedding
    except Exception as e:
        print(f"Inference error: {e}")
        return np.zeros(128, dtype=np.float32)
