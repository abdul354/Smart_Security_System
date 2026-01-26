import os
import shutil
import sys
import urllib.request


def download(url: str, dest_path: str) -> None:
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    tmp_path = dest_path + ".tmp"

    with urllib.request.urlopen(url) as r, open(tmp_path, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        read = 0
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
            read += len(chunk)
            if total:
                pct = read * 100 // total
                print(f"Downloading... {pct}%", end="\r", flush=True)

    os.replace(tmp_path, dest_path)
    print(f"Downloaded: {dest_path}")


def main() -> int:
    # ArcFace ResNet100 (512-D embedding), Apache-2.0.
    # This validated artifact is known to expose: input `data` (1,3,112,112) and output `fc1` (1,512).
    url = "https://github.com/onnx/models/raw/main/validated/vision/body_analysis/arcface/model/arcfaceresnet100-8.onnx"

    root = os.path.dirname(os.path.abspath(__file__))
    model_dir = os.path.join(root, "backend", "models")
    target = os.path.join(model_dir, "facenet.onnx")

    # Backup existing model if present.
    if os.path.exists(target):
        backup = os.path.join(model_dir, "facenet.previous.onnx")
        try:
            if os.path.exists(backup):
                os.remove(backup)
            shutil.move(target, backup)
            print(f"Backed up existing model to: {backup}")
        except Exception as exc:
            print(f"Failed to backup existing model: {exc}")

    try:
        download(url, target)
    except Exception as exc:
        print(f"Download failed: {exc}")
        return 1

    print("\nVerify shapes by running: python inspect_onnx.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
