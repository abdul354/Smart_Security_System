import os
import sys

import onnxruntime as ort


def main() -> int:
    model_path = sys.argv[1] if len(sys.argv) > 1 else "backend/models/facenet.onnx"
    model_path = os.path.abspath(model_path)
    print(f"Inspecting: {model_path}", flush=True)

    try:
        sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    except Exception as e:
        print(f"Error loading model: {e}", flush=True)
        return 1

    print("Inputs:", flush=True)
    for i in sess.get_inputs():
        print(f" - Name: {i.name}, Shape: {i.shape}, Type: {i.type}", flush=True)

    print("\nOutputs:", flush=True)
    for o in sess.get_outputs():
        print(f" - Name: {o.name}, Shape: {o.shape}, Type: {o.type}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
