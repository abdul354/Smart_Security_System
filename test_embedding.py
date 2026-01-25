
import numpy as np
import cv2
from backend.embedding import get_embedding, load_embedding_model

print("Testing ONNX Embedding...")

# 1. Test Model Loading
sess = load_embedding_model()
if sess is None:
    print("Failed to load model session")
    exit(1)
print("Model loaded")

# 2. Test Embedding Generation
dummy_face = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
emb = get_embedding(dummy_face)

print(f"Embedding shape: {emb.shape}")
print(f"Embedding norm: {np.linalg.norm(emb)}")
print(f"Sample values: {emb[:5]}")

if emb.shape == (128,) and np.abs(np.linalg.norm(emb) - 1.0) < 1e-5:
    print("Embedding generation SUCCESS")
else:
    print("Embedding generation FAILED")
