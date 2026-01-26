# Smart Security System

A webcam-based smart security and attendance system built with FastAPI.
It supports enrolling people, recognizing faces in real time, and logging attendance events, while keeping face embeddings stored locally.

## Key Features
- Real-time face detection + recognition from a live webcam feed
- Guided enrollment flow with pose/quality checks to capture better samples
- ONNX face-embedding inference (FaceNet/ArcFace-style vectors)
- Local vector database (ChromaDB) for fast nearest-neighbor matching
- Optional Supabase (Postgres) for person/attendance metadata syncing
- Optional HTTP Basic Auth + simple per-IP rate limiting

## High-Level Architecture
- **Frontend:** static HTML/CSS/JS pages (dashboard, enrollment, management, chatbot)
- **Backend API:** FastAPI (streaming `/video_feed`, JSON endpoints for enrollment/recognition)
- **Embeddings:** ONNX Runtime loads the model from `backend/models/*.onnx`
- **Vector Search:** ChromaDB persists embeddings under `backend/db/chromadb_data`
- **Metadata (optional):** Supabase stores person details + attendance records

## Prerequisites
- Python 3.10+ (tested on Windows)
- A webcam (for `/video_feed`)
- Supabase project (URL + Service Role key)
- (Optional) Groq API key for the chatbot

## Setup

### 1) Install dependencies
```bash
pip install -r requirements.txt
```

### 2) Configure environment variables
Create a `.env` file in the project root (it is ignored by git).

Start from the template:
```bash
copy .env.example .env
```

Required (Supabase):
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

Optional (Chatbot):
- `GROQ_API_KEY`

Optional (Security):
- `BASIC_AUTH_USER`
- `BASIC_AUTH_PASSWORD`

Optional (Rate limiting):
- `RATE_LIMIT_CHAT_PER_MIN` (default `20`, set `0` to disable)
- `RATE_LIMIT_VIDEO_PER_MIN` (default `30`, set `0` to disable)
- `TRUST_PROXY` (default `0`; set `1` only if behind a reverse proxy that sets `X-Forwarded-For`)

Note: localhost (127.0.0.1 / ::1) is not rate-limited by default.

See `.env.example` in the repo for all fields.

### 3) Create Supabase tables
Run the SQL in:
- [supabase_schema.sql](supabase_schema.sql)

Use Supabase Dashboard → SQL Editor.

### 4) Ensure Chroma collection exists
If needed, you can create the local Chroma collection:
```bash
python backend/db/create_chroma_db.py
```

## Run

### One-file launcher (recommended)
```bash
python run_server.py --open --init-chroma
```

### Development server
```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8001
```

Open:
- http://127.0.0.1:8001/

## Notes
- Embeddings remain local on disk (ChromaDB). Only metadata (persons/attendance) is stored in Supabase.
- If you bind to LAN (`--host 0.0.0.0`), enable auth (`BASIC_AUTH_USER`/`BASIC_AUTH_PASSWORD`) and rotate keys if they’ve been shared.

## Face Embedding Model (Important)
The file `backend/models/facenet.onnx` must be a *face embedding* model (FaceNet/ArcFace-style) that outputs a vector like `(1, 128)` or `(1, 512)`.

This repo is configured to work with the validated ONNX Model Zoo ArcFace model:
- Input: `data` with shape `(1, 3, 112, 112)`
- Output: `fc1` with shape `(1, 512)`

To verify the model outputs an embedding vector:
```bash
python inspect_onnx.py
```

To download a working model into place:
```bash
python download_models.py
```

If the output shapes look like a detector (for example `regressors` / `classificators`), enrollment will refuse to store embeddings to avoid corrupting your database.

## Security
- HTTP Basic Auth is applied to all routes when credentials are set.
- Basic per-IP rate limiting is applied to `/chat` and `/video_feed` (configurable via `.env`).

## Troubleshooting
- If the server starts and then exits immediately when run in some terminals, start it detached or in a dedicated terminal window.
- Chroma telemetry warnings like `capture() takes 1 positional argument but 3 were given` are noisy but non-blocking.
