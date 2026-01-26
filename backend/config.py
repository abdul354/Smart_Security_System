import os

BASE_DB = "backend/db"
CHROMA_PATH = os.path.join(BASE_DB, "chromadb_data")

THRESHOLD = 0.82
# Enrollment speed/UX: fewer samples makes enrollment significantly faster.
SAMPLES_REQUIRED = 5

# Enrollment capture tuning (accuracy/stability)
# Capture multiple frames per sample and average their embeddings to reduce noise.
ENROLL_BURST_FRAMES = 3
ENROLL_BURST_DELAY_SECONDS = 0.05
# Require at least this many embeddings from the burst to accept a sample.
ENROLL_BURST_MIN_ACCEPTED = 2

# Duplicate guard during enrollment (distance returned by Chroma).
# Keep aligned with THRESHOLD unless you explicitly want stricter duplicate checks.
ENROLL_DUPLICATE_DISTANCE = 0.7

# Detection tuning (safe defaults for CPU webcams).
DETECTION_MODEL_SELECTION = 1  # 0=short range, 1=long range
DETECTION_MIN_CONFIDENCE = 0.5
DETECTION_ENHANCE = True
DETECTION_UPSCALE = 1.2
DETECTION_FRAME_SKIP = 3
DETECTION_HOLD_FRAMES = 2
