from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import webbrowser


def _maybe_load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        # App can still run if env vars are already set.
        pass


def _ensure_chroma_collection() -> None:
    script_path = os.path.join("backend", "db", "create_chroma_db.py")
    if not os.path.exists(script_path):
        return
    subprocess.run([sys.executable, script_path], check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Smart Security System server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", default=8001, type=int, help="Bind port (default: 8001)")
    parser.add_argument(
        "--lan",
        action="store_true",
        help="Bind to 0.0.0.0 (LAN). Enable auth before using this.",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable autoreload (development only).",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open browser after the server starts.",
    )
    parser.add_argument(
        "--init-chroma",
        action="store_true",
        help="Initialize the local Chroma collection before starting.",
    )

    args = parser.parse_args()

    _maybe_load_dotenv()

    if args.lan:
        args.host = "0.0.0.0"

    if args.init_chroma:
        _ensure_chroma_collection()

    if args.open:
        # Give Uvicorn a moment to start listening.
        def _open() -> None:
            time.sleep(1.0)
            webbrowser.open(f"http://127.0.0.1:{args.port}/")

        import threading

        threading.Thread(target=_open, daemon=True).start()

    try:
        import uvicorn
    except Exception as exc:
        print(f"uvicorn import failed: {exc}", file=sys.stderr)
        return 1

    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
