# Smart Security System

FastAPI-based smart security system with:
- Face embedding/recognition (ONNX FaceNet)
- Local vector DB (ChromaDB) for embeddings
- Supabase (Postgres) for persons + attendance metadata (no CSV)
- Optional HTTP Basic Auth + simple per-IP rate limiting

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
- `RATE_LIMIT_VIDEO_PER_MIN` (default `5`, set `0` to disable)
- `TRUST_PROXY` (default `0`; set `1` only if behind a reverse proxy that sets `X-Forwarded-For`)

See the `.env` template in the repo for all fields.

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

### Development server
```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8001
```

Open:
- http://127.0.0.1:8001/

## Notes
- Embeddings remain local on disk (ChromaDB). Only metadata (persons/attendance) is stored in Supabase.
- If you bind to LAN (`--host 0.0.0.0`), enable auth (`BASIC_AUTH_USER`/`BASIC_AUTH_PASSWORD`) and rotate keys if they’ve been shared.

## Security
- HTTP Basic Auth is applied to all routes when credentials are set.
- Basic per-IP rate limiting is applied to `/chat` and `/video_feed` (configurable via `.env`).

## Troubleshooting
- If the server starts and then exits immediately when run in some terminals, start it detached or in a dedicated terminal window.
- Chroma telemetry warnings like `capture() takes 1 positional argument but 3 were given` are noisy but non-blocking.
