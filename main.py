from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from backend.camera import VideoCamera
from backend.detection import detect_faces
from backend.embedding import get_embedding, get_embeddings
from backend.recognition import recognize_face
from backend.enrollment import generate_person_id, add_embedding, finalize_enrollment, CURRENT_SESSION
from backend.attendance import log_attendance, read_attendance
from backend.quality import face_quality, face_quality_details
from backend.config import (
    DETECTION_ENHANCE,
    DETECTION_UPSCALE,
    DETECTION_FRAME_SKIP,
    DETECTION_HOLD_FRAMES,
    SAMPLES_REQUIRED,
    ENROLL_BURST_FRAMES,
    ENROLL_BURST_DELAY_SECONDS,
    ENROLL_BURST_MIN_ACCEPTED,
    ENROLL_DUPLICATE_DISTANCE,
)
from backend.admin import list_persons, delete_person
from backend.pose_validation import analyze_pose_and_draw, validate_expected_pose, POSES
from backend.chatbot import answer_chat
from backend.security import basic_auth_middleware
from backend.rate_limit import rate_limit_middleware
from backend.metrics import record as record_metric, snapshot as metrics_snapshot

import cv2
import numpy as np
import time
import atexit
import threading
import uuid
import logging
from collections import deque
import traceback

app = FastAPI(title="Smart Security System Backend")

logger = logging.getLogger("smart_security")


@app.middleware("http")
async def _basic_auth(request: Request, call_next):
    return await basic_auth_middleware(request, call_next)


@app.middleware("http")
async def _rate_limit(request: Request, call_next):
    return await rate_limit_middleware(request, call_next)

SESSION_TTL_SECONDS = 30 * 60
SESSION_MAX_TURNS = 8
SESSION_STORE = {}
SESSION_LOCK = threading.Lock()

# Serve static frontend files
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/")
def home():
    return FileResponse("frontend/home.html")

@app.get("/dashboard")
def dashboard():
    return FileResponse("frontend/index.html")

@app.get("/chatbot")
def chatbot():
    return FileResponse("frontend/chatbot.html")

# Global Camera Singleton
camera = None
SYSTEM_MODE = "recognition"  # or "enrollment"
OVERLAY_MESSAGE = ""
OVERLAY_COLOR = (0, 0, 255)  # red by default

LAST_BOXES = []
LAST_BOXES_AGE = 0

LAST_FRAME = None

LAST_RECOGNITIONS = []
LAST_RECOGNITION_TIME = 0
STATE_LOCK = threading.Lock()

RECENT_RECOGNITION_CACHE = []
RECENT_RECOGNITION_WINDOW = 1.5  # seconds
SMOOTHING_DISTANCE_PX = 80

# Camera streaming coordination
CAMERA_STOP_EVENT = threading.Event()
ACTIVE_STREAMS = 0
STREAMS_LOCK = threading.Lock()

RECOGNITION_COOLDOWN = 0.5  # seconds
LAST_RECOGNITION_RUN = 0

FACE_TRACKERS = {}  # key: tracker_id, value: tracker object
TRACKER_ID_COUNTER = 0
TRACKER_RECOGNITIONS = {}  # key: tracker_id, value: recognition info

POSE_ACCEPT_STREAK = 1
POSE_ACCEPT_STREAK_BASELINE = 2

# Ensure camera released on exit
def cleanup():
    release_camera()

atexit.register(cleanup)

def get_camera():
    global camera
    if camera is None:
        camera = VideoCamera()
    return camera

def release_camera():
    global camera
    if camera is not None:
        camera.release()
        camera = None


def _match_recent_recognition(center):
    now = time.time()
    cx, cy = center
    keep = []
    best = None
    for entry in RECENT_RECOGNITION_CACHE:
        age = now - entry["timestamp"]
        if age > RECENT_RECOGNITION_WINDOW:
            continue
        keep.append(entry)
        ex, ey = entry["center"]
        if best is not None:
            continue
        if abs(cx - ex) <= SMOOTHING_DISTANCE_PX and abs(cy - ey) <= SMOOTHING_DISTANCE_PX:
            best = entry["data"].copy()
    RECENT_RECOGNITION_CACHE[:] = keep
    return best


def _remember_recognition(center, data):
    RECENT_RECOGNITION_CACHE.append({
        "center": center,
        "timestamp": time.time(),
        "data": data.copy(),
    })


# MJPEG Video Stream
def gen_frames():
    frame_count = 0
    global LAST_FRAME, LAST_RECOGNITIONS, LAST_RECOGNITION_TIME, LAST_BOXES, LAST_BOXES_AGE, ACTIVE_STREAMS

    with STREAMS_LOCK:
        ACTIVE_STREAMS += 1

    try:
        while not CAMERA_STOP_EVENT.is_set():
            try:
                cam = get_camera()
            except Exception as exc:
                logger.warning("Camera open failed; retrying: %s", exc)
                time.sleep(0.5)
                continue

            frame = cam.get_frame()
            if frame is None:
                time.sleep(0.02)
                continue

            try:
                loop_start = time.perf_counter()
                with STATE_LOCK:
                    LAST_FRAME = frame.copy()

                frame_count += 1

                # Detect faces every N frames; keep last boxes briefly if detection misses.
                if frame_count % DETECTION_FRAME_SKIP == 0:
                    detect_start = time.perf_counter()
                    detected = detect_faces(
                        frame,
                        enhance=DETECTION_ENHANCE,
                        upscale=DETECTION_UPSCALE,
                    )
                    record_metric("detection.latency_ms", (time.perf_counter() - detect_start) * 1000.0)
                    with STATE_LOCK:
                        if detected:
                            LAST_BOXES = detected
                            LAST_BOXES_AGE = 0
                        else:
                            LAST_BOXES_AGE += 1
                            if LAST_BOXES_AGE > DETECTION_HOLD_FRAMES:
                                LAST_BOXES = []

                boxes = LAST_BOXES
                current_recognitions = []

                recognition_results = [None] * len(boxes)
                if SYSTEM_MODE == "recognition" and boxes:
                    faces_payload = []
                    for idx, (x, y, w, h) in enumerate(boxes):
                        x1, y1 = max(0, x), max(0, y)
                        x2, y2 = min(frame.shape[1], x + w), min(frame.shape[0], y + h)
                        if x2 <= x1 or y2 <= y1:
                            continue
                        face = frame[y1:y2, x1:x2]
                        if face.size == 0:
                            continue
                        faces_payload.append((idx, (x + w / 2.0, y + h / 2.0), face))

                    if faces_payload:
                        emb_start = time.perf_counter()
                        embeddings = get_embeddings([fp[2] for fp in faces_payload])
                        record_metric("embedding.latency_ms", (time.perf_counter() - emb_start) * 1000.0)
                        for (idx, center, _face), emb in zip(faces_payload, embeddings):
                            entry_data = {
                                "person_id": None,
                                "display_name": "Unknown",
                                "role": "",
                                "access_status": "",
                                "distance": None,
                            }
                            label = "Unknown"
                            color = (0, 0, 255)

                            if emb is None:
                                label = "Embedding model error"
                                color = (0, 165, 255)
                            else:
                                person, dist = recognize_face(emb)
                                if person:
                                    entry_data.update(
                                        {
                                            "person_id": person["person_id"],
                                            "display_name": person["display_name"],
                                            "role": person["role"],
                                            "access_status": person["access_status"],
                                            "distance": float(dist) if dist is not None else None,
                                        }
                                    )
                                    label = person["display_name"]
                                    color = (0, 255, 0)
                                    _remember_recognition(center, entry_data)
                                else:
                                    if dist is not None:
                                        entry_data["distance"] = float(dist)
                                    cached = _match_recent_recognition(center)
                                    if cached:
                                        entry_data = cached
                                        label = cached["display_name"]
                                        color = (0, 200, 0)

                            recognition_results[idx] = {
                                "label": label,
                                "color": color,
                                "info": entry_data,
                            }

                for idx, (x, y, w, h) in enumerate(boxes):
                    color = (0, 0, 255)
                    label = "Unknown"

                    if SYSTEM_MODE == "recognition":
                        result = recognition_results[idx]
                        if result is not None:
                            label = result["label"]
                            color = result["color"]
                            current_recognitions.append(result["info"])
                        else:
                            current_recognitions.append(
                                {
                                    "person_id": None,
                                    "display_name": "Unknown",
                                    "role": "",
                                    "access_status": "",
                                    "distance": None,
                                }
                            )

                    elif SYSTEM_MODE == "enrollment":
                        pose_index = CURRENT_SESSION.get("count", 0)
                        expected_pose = POSES[min(pose_index, len(POSES) - 1)]

                        ok, _, pose_deg, smile_ratio = analyze_pose_and_draw(frame_bgr=frame, draw=True)

                        label = (
                            f"{expected_pose} ({pose_index + 1}/{SAMPLES_REQUIRED})"
                            if pose_index < SAMPLES_REQUIRED
                            else "Capture complete"
                        )
                        color = (255, 255, 0)

                        if pose_deg:
                            pitch, yaw, roll = pose_deg
                            pitch = fold_angle(pitch)
                            yaw = fold_angle(yaw)
                            roll = fold_angle(roll)
                            cv2.putText(
                                frame,
                                f"pitch={pitch:.1f} yaw={yaw:.1f} roll={roll:.1f}",
                                (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.7,
                                (255, 255, 0),
                                2,
                            )

                    # Draw box and label
                    cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                    cv2.putText(
                        frame,
                        label,
                        (x, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        color,
                        2,
                    )

                if current_recognitions:
                    with STATE_LOCK:
                        LAST_RECOGNITIONS = current_recognitions
                        LAST_RECOGNITION_TIME = time.time()

                ok, buffer = cv2.imencode(".jpg", frame)
                if not ok or buffer is None:
                    logger.warning("cv2.imencode failed; skipping frame")
                    time.sleep(0.01)
                    continue

                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
                )
                record_metric("frame.loop_ms", (time.perf_counter() - loop_start) * 1000.0)
            except Exception:
                logger.exception("Frame loop error; continuing")
                time.sleep(0.05)
                continue
    finally:
        should_release = False
        with STREAMS_LOCK:
            ACTIVE_STREAMS = max(0, ACTIVE_STREAMS - 1)
            should_release = ACTIVE_STREAMS == 0
        if should_release:
            release_camera()


def expand_box(x, y, w, h, frame_w, frame_h, margin=0.35):
    cx, cy = x + w / 2, y + h / 2
    nw, nh = w * (1 + margin), h * (1 + margin)

    x1 = int(max(0, cx - nw / 2))
    y1 = int(max(0, cy - nh / 2))
    x2 = int(min(frame_w, cx + nw / 2))
    y2 = int(min(frame_h, cy + nh / 2))
    return x1, y1, x2, y2


def norm180(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


def fold_angle(a: float) -> float:
    """Fold a pose angle into a stable range around 0.

    Head pose estimates can occasionally flip and report values near +/-180 for a
    forward-facing head. This makes straight-pose checks fail. Folding maps those
    cases back near 0.
    """
    a = norm180(float(a))
    if abs(a) > 90.0:
        a = norm180(a - 180.0)
    return float(a)


@app.post("/camera/stop")
async def camera_stop():
    CAMERA_STOP_EVENT.set()
    release_camera()

    return {"status": "stopped"}

@app.post("/system/mode/{mode}")
async def set_system_mode(mode: str):
    global SYSTEM_MODE, OVERLAY_MESSAGE

    if mode in ["recognition", "enrollment"]:
        SYSTEM_MODE = mode

    # Clear enrollment messages when leaving enrollment
    if SYSTEM_MODE == "recognition":
        OVERLAY_MESSAGE = ""

    return {"mode": SYSTEM_MODE}



@app.get("/video_feed")
def video_feed():
    CAMERA_STOP_EVENT.clear()
    return StreamingResponse(
        gen_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


# Recognition Info Endpoint
@app.get("/recognition/live")
async def recognition_live():
    now = time.time()

    with STATE_LOCK:
        if now - LAST_RECOGNITION_TIME > 3:
            faces = []
        else:
            faces = LAST_RECOGNITIONS.copy()

        for f in faces:
            if f["display_name"] != "Unknown":
                log_attendance(f["person_id"])

    attendance = read_attendance()
    return JSONResponse({
        "faces": faces,
        "attendance": attendance,
        "metrics": metrics_snapshot(),
    })


# Enrollment Start
@app.post("/enroll/start")
async def enroll_start():
    """
    Generate new person_id for enrollment session
    """
    global SYSTEM_MODE
    SYSTEM_MODE = "enrollment"
    pid = generate_person_id()
    return {"person_id": pid}


@app.post("/enroll/capture")
async def enroll_capture():
    """
    Captures one valid sample per call during enrollment:
    - Requires exactly 1 face
    - Requires minimum face quality
    - Calibrates "Look straight" baseline
    - Validates expected pose for current step
    - Requires pose to be valid (single stable call)
    """
    try:
        return _enroll_capture_impl()
    except Exception as exc:
        logger.exception("enroll_capture failed")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": "Internal server error",
                "detail": str(exc),
                "trace": traceback.format_exc(),
            },
        )


def _enroll_capture_impl():
    global OVERLAY_MESSAGE, OVERLAY_COLOR

    with STATE_LOCK:
        frame = None if LAST_FRAME is None else LAST_FRAME.copy()
    if frame is None:
        OVERLAY_MESSAGE = "Camera not ready"
        return {"status": "error", "message": OVERLAY_MESSAGE, "samples_required": SAMPLES_REQUIRED}

    boxes = detect_faces(
        frame,
        enhance=DETECTION_ENHANCE,
        upscale=DETECTION_UPSCALE
    )
    if len(boxes) != 1:
        OVERLAY_MESSAGE = "Ensure exactly ONE face"
        CURRENT_SESSION["valid_streak"] = 0
        return {"status": "error", "message": OVERLAY_MESSAGE, "samples_required": SAMPLES_REQUIRED}

    x, y, w, h = boxes[0]

    fh, fw = frame.shape[:2]
    # FaceMesh needs more context than embedding crop; use a larger margin.
    ex1, ey1, ex2, ey2 = expand_box(x, y, w, h, fw, fh, margin=0.75)
    face_for_mesh = frame[ey1:ey2, ex1:ex2]

    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(fw, x + w), min(fh, y + h)
    face = frame[y1:y2, x1:x2]

    if face.size == 0 or face_for_mesh.size == 0:
        OVERLAY_MESSAGE = "Invalid face crop"
        CURRENT_SESSION["valid_streak"] = 0
        return {"status": "error", "message": OVERLAY_MESSAGE, "samples_required": SAMPLES_REQUIRED}

    # Ensure mediapipe gets a contiguous uint8 image.
    face_for_mesh = np.ascontiguousarray(face_for_mesh)
    face_for_mesh = cv2.resize(face_for_mesh, (320, 320))

    q = face_quality_details(face)
    quality = int(q["score"])
    if quality < 2:
        OVERLAY_MESSAGE = "Low Face Quality"
        CURRENT_SESSION["valid_streak"] = 0
        return {
            "status": "error",
            "message": OVERLAY_MESSAGE,
            "quality": quality,
            "quality_details": q,
            "samples_required": SAMPLES_REQUIRED,
        }

    pose_index = int(CURRENT_SESSION.get("count", 0))
    expected_pose = POSES[min(pose_index, len(POSES) - 1)]

    ok, _, pose_deg, smile_ratio = analyze_pose_and_draw(frame_bgr=face_for_mesh, draw=False)
    if not ok or pose_deg is None:
        # Fallback: sometimes FaceMesh fails on tight crops; try the full frame.
        ok2, _, pose_deg2, smile_ratio2 = analyze_pose_and_draw(frame_bgr=frame, draw=False)
        if not ok2 or pose_deg2 is None:
            return {
                "status": "error",
                "message": "Align face (mesh not detected)",
                "mesh_crop_shape": list(face_for_mesh.shape),
                "det_crop_shape": list(face.shape),
                "quality": quality,
                "samples_required": SAMPLES_REQUIRED,
            }
        pose_deg = pose_deg2
        smile_ratio = smile_ratio2

    pitch, yaw, roll = pose_deg
    pitch = fold_angle(pitch)
    yaw = fold_angle(yaw)
    roll = fold_angle(roll)

    baseline_notice = None

    if "pose_center" not in CURRENT_SESSION:
        CURRENT_SESSION["pose_center"] = None
    if "pose_center_samples" not in CURRENT_SESSION:
        CURRENT_SESSION["pose_center_samples"] = []
    if "valid_streak" not in CURRENT_SESSION:
        CURRENT_SESSION["valid_streak"] = 0
    if "pose_history" not in CURRENT_SESSION or CURRENT_SESSION["pose_history"] is None:
        CURRENT_SESSION["pose_history"] = deque(maxlen=6)
    elif not isinstance(CURRENT_SESSION["pose_history"], deque):
        CURRENT_SESSION["pose_history"] = deque(list(CURRENT_SESSION["pose_history"] or []), maxlen=6)

    if CURRENT_SESSION["pose_center"] is None and CURRENT_SESSION["count"] == 0:
        # Robust baseline calibration: collect a small window and require low variance.
        # This avoids setting a bad baseline that prevents step 1 from ever passing.
        samples = CURRENT_SESSION.get("pose_center_samples")
        if samples is None:
            samples = []
            CURRENT_SESSION["pose_center_samples"] = samples

        samples.append((float(pitch), float(yaw), float(roll)))
        # Keep a rolling window (last 10 frames)
        if len(samples) > 10:
            del samples[0 : len(samples) - 10]

        # Need a few frames before we can judge stability.
        if len(samples) < 5:
            OVERLAY_MESSAGE = "Hold still - calibrating (look straight)"
            return {
                "status": "calibrating",
                "message": OVERLAY_MESSAGE,
                "quality": quality,
                "pose_deg": (pitch, yaw, roll),
                "smile_ratio": float(smile_ratio),
                "samples_required": SAMPLES_REQUIRED,
                "calibrating": True,
                "calib_count": len(samples),
            }

        arr = np.array(samples, dtype=np.float64)
        std = np.std(arr, axis=0)
        # If the head is moving, keep calibrating.
        if float(np.max(std)) > 7.0:
            OVERLAY_MESSAGE = "Hold still - calibrating"
            return {
                "status": "calibrating",
                "message": OVERLAY_MESSAGE,
                "quality": quality,
                "pose_deg": (pitch, yaw, roll),
                "smile_ratio": float(smile_ratio),
                "samples_required": SAMPLES_REQUIRED,
                "calibrating": True,
                "calib_count": len(samples),
                "pose_std": (float(std[0]), float(std[1]), float(std[2])),
            }

        center = tuple(np.mean(arr, axis=0).tolist())
        CURRENT_SESSION["pose_center"] = center
        CURRENT_SESSION["pose_center_samples"] = []
        CURRENT_SESSION["valid_streak"] = 0
        CURRENT_SESSION["pose_history"] = deque(maxlen=6)

        # Baseline is set; continue in this same request to validate and capture the
        # first ("look straight") sample. This prevents getting stuck showing the
        # baseline message while never incrementing the sample count.
        baseline_notice = "Baseline set. Keep looking straight."

    center = CURRENT_SESSION.get("pose_center")
    if center is not None:
        pitch -= center[0]
        yaw -= center[1]
        roll -= center[2]

    pitch = fold_angle(pitch)
    yaw = fold_angle(yaw)
    roll = fold_angle(roll)

    pose_deg_centered = (float(pitch), float(yaw), float(roll))

    pose_history = CURRENT_SESSION.get("pose_history")
    if not isinstance(pose_history, deque):
        pose_history = deque(pose_history or [], maxlen=6)
        CURRENT_SESSION["pose_history"] = pose_history
    pose_history.append(pose_deg_centered)
    if len(pose_history) >= 2:
        arr_hist = np.array(pose_history, dtype=np.float32)
        pose_deg_centered = tuple(float(v) for v in np.median(arr_hist, axis=0))

    face_area = w * h
    frame_area = frame.shape[0] * frame.shape[1]

    tolerance = min(8.0, 1.5 * float(CURRENT_SESSION.get("valid_streak", 0)))

    is_valid, msg = validate_expected_pose(
        expected_pose=expected_pose,
        pose_deg=pose_deg_centered,
        smile_ratio=float(smile_ratio),
        face_box_area=face_area,
        frame_area=frame_area,
        tolerance=tolerance,
    )

    if not is_valid:
        OVERLAY_MESSAGE = msg
        CURRENT_SESSION["valid_streak"] = 0
        return {
            "status": "error",
            "message": msg,
            "expected_pose": expected_pose,
            "quality": quality,
            "pose_deg": pose_deg_centered,
            "smile_ratio": float(smile_ratio),
            "samples_required": SAMPLES_REQUIRED,
        }

    CURRENT_SESSION["valid_streak"] = int(CURRENT_SESSION.get("valid_streak", 0)) + 1
    required_streak = POSE_ACCEPT_STREAK_BASELINE if (
        CURRENT_SESSION.get("count", 0) == 0 and expected_pose.lower() == "look straight"
    ) else POSE_ACCEPT_STREAK

    if CURRENT_SESSION["valid_streak"] < required_streak:
        OVERLAY_MESSAGE = "Hold steady - locking pose"
        return {
            "status": "steady",
            "message": OVERLAY_MESSAGE,
            "expected_pose": expected_pose,
            "quality": quality,
            "pose_deg": pose_deg_centered,
            "smile_ratio": float(smile_ratio),
            "samples_required": SAMPLES_REQUIRED,
            "streak": CURRENT_SESSION["valid_streak"],
            "streak_required": required_streak,
        }

    # Capture a short burst and average embeddings for stability.
    probe = get_embedding(face)
    if probe is None:
        OVERLAY_MESSAGE = "Embedding model not ready/invalid"
        CURRENT_SESSION["valid_streak"] = 0
        return {
            "status": "error",
            "message": OVERLAY_MESSAGE,
            "hint": "Check backend/models/facenet.onnx is an embedding model (output should be (1,128) or similar).",
            "samples_required": SAMPLES_REQUIRED,
        }

    embeddings = [probe]
    for i in range(1, int(ENROLL_BURST_FRAMES)):
        with STATE_LOCK:
            frame_i = None if LAST_FRAME is None else LAST_FRAME.copy()
        if frame_i is None:
            break

        fh_i, fw_i = frame_i.shape[:2]
        x1_i, y1_i = max(0, x), max(0, y)
        x2_i, y2_i = min(fw_i, x + w), min(fh_i, y + h)
        face_i = frame_i[y1_i:y2_i, x1_i:x2_i]
        if face_i.size == 0:
            continue

        q_i = face_quality_details(face_i)
        if int(q_i["score"]) < 2:
            continue

        emb_i = get_embedding(face_i)
        if emb_i is None:
            continue
        embeddings.append(emb_i)

        if i < int(ENROLL_BURST_FRAMES) - 1:
            time.sleep(float(ENROLL_BURST_DELAY_SECONDS))

    if len(embeddings) < int(ENROLL_BURST_MIN_ACCEPTED):
        OVERLAY_MESSAGE = "Hold still (capture too noisy)"
        CURRENT_SESSION["valid_streak"] = 0
        return {
            "status": "error",
            "message": OVERLAY_MESSAGE,
            "quality": quality,
            "quality_details": q,
            "samples_required": SAMPLES_REQUIRED,
            "burst_collected": len(embeddings),
            "burst_required": int(ENROLL_BURST_MIN_ACCEPTED),
        }

    emb = np.mean(np.stack(embeddings, axis=0), axis=0)
    norm = float(np.linalg.norm(emb))
    if not np.isfinite(norm) or norm <= 0:
        OVERLAY_MESSAGE = "Embedding failed"
        CURRENT_SESSION["valid_streak"] = 0
        return {"status": "error", "message": OVERLAY_MESSAGE, "samples_required": SAMPLES_REQUIRED}
    emb = emb / norm

    person, dist = recognize_face(emb)
    if person and dist is not None and dist < float(ENROLL_DUPLICATE_DISTANCE):
        OVERLAY_MESSAGE = "Person already exists. Restarting."
        generate_person_id()
        CURRENT_SESSION["pose_center"] = None
        CURRENT_SESSION["pose_center_samples"] = []
        CURRENT_SESSION["valid_streak"] = 0
        return {"status": "duplicate", "message": OVERLAY_MESSAGE, "samples_required": SAMPLES_REQUIRED}

    OVERLAY_MESSAGE = ""
    try:
        done, count = add_embedding(emb)
    except Exception as exc:
        OVERLAY_MESSAGE = f"Enrollment failed: {exc}"
        return {"status": "error", "message": OVERLAY_MESSAGE, "samples_required": SAMPLES_REQUIRED}

    CURRENT_SESSION["valid_streak"] = 0
    CURRENT_SESSION["pose_history"] = deque(maxlen=6)

    return {
        "status": "ok",
        "done": done,
        "count": count,
        "quality": quality,
        "quality_details": q,
        "expected_pose": expected_pose,
        "pose_deg": pose_deg_centered,
        "smile_ratio": float(smile_ratio),
        "samples_required": SAMPLES_REQUIRED,
        "burst_collected": len(embeddings),
        "notice": baseline_notice,
    }


# Enrollment Confirm
@app.post("/enroll/confirm")
async def enroll_confirm(request: Request):
    """
    Finalize enrollment using embeddings captured during session
    """
    global SYSTEM_MODE
    data = await request.json()

    display_name = data["display_name"]
    role = data["role"]
    department = data.get("department", "")
    access_status = data.get("access_status", "active")

    finalize_enrollment(
        display_name=display_name,
        role=role,
        department=department,
        access_status=access_status
    )
    SYSTEM_MODE = "recognition"  # return to normal mode

    return {"status": "success"}


# Attendance Today
@app.get("/attendance/today")
async def attendance_today():
    """
    Return all logged attendance entries
    """
    return JSONResponse(read_attendance(today_only=True))


@app.post("/chat")
async def chat(request: Request):
    data = await request.json()
    message = (data.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "Message is required."}, status_code=400)

    now = time.time()
    new_session = False
    with SESSION_LOCK:
        sid = request.cookies.get("chat_session_id")
        if sid in SESSION_STORE and now - SESSION_STORE[sid]["updated"] > SESSION_TTL_SECONDS:
            SESSION_STORE.pop(sid, None)
            sid = None
        if not sid:
            sid = uuid.uuid4().hex
            SESSION_STORE[sid] = {"updated": now, "history": [], "memory": {}}
            new_session = True

        session = SESSION_STORE[sid]
        session["updated"] = now
        history = list(session.get("history", []))
        memory = dict(session.get("memory", {}))

    try:
        answer_data = answer_chat(message, memory, history)
    except Exception:
        answer_data = {"answer": "I am having trouble right now. Please try again.", "meta": {}}

    with SESSION_LOCK:
        session = SESSION_STORE.get(sid)
        if session is not None:
            session["updated"] = now
            session["history"].append({"role": "user", "content": message})
            session["history"].append({"role": "assistant", "content": answer_data.get("answer", "")})
            if len(session["history"]) > SESSION_MAX_TURNS * 2:
                session["history"] = session["history"][-SESSION_MAX_TURNS * 2 :]

            meta = answer_data.get("meta") or {}
            if meta.get("matched_person_id"):
                session["memory"]["last_person_id"] = meta["matched_person_id"]
            if meta.get("matched_display_name"):
                session["memory"]["last_person_name"] = meta["matched_display_name"]

    response = JSONResponse(answer_data)
    if new_session:
        response.set_cookie("chat_session_id", sid, httponly=True, samesite="lax")
    return response


@app.post("/chat/clear")
async def chat_clear(request: Request):
    sid = request.cookies.get("chat_session_id")
    if not sid:
        return {"status": "cleared"}
    with SESSION_LOCK:
        SESSION_STORE.pop(sid, None)
    return {"status": "cleared"}


# admin panel endpoints
@app.get("/admin/persons")
async def get_persons():
    persons = list_persons()
    return {
        "count": len(persons),
        "persons": persons
    }

@app.delete("/admin/person/{person_id}")
async def remove_person(person_id: str):
    delete_person(person_id)
    return {"status": "deleted"}
