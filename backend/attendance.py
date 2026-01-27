import time
import threading
from datetime import date, datetime, timezone
from typing import Any, Dict, List

from backend.metrics import record as _record_metric
from backend.supabase_db import log_attendance as _log_attendance_supabase
from backend.supabase_db import read_attendance as _read_attendance_supabase

# In-memory guard to avoid duplicates per day (per process)
SEEN_TODAY = set()
SEEN_DAY = date.today().isoformat()

_CACHE_LOCK = threading.Lock()
_ATTENDANCE_CACHE: List[Dict[str, Any]] = []
_ATTENDANCE_CACHE_AT = 0.0
_ATTENDANCE_CACHE_TTL = 12.0


def _reset_daily_state(day: str) -> None:
    global SEEN_DAY
    if SEEN_DAY != day:
        SEEN_TODAY.clear()
        SEEN_DAY = day


def _cache_entry(entry: Dict[str, Any]) -> None:
    global _ATTENDANCE_CACHE_AT
    with _CACHE_LOCK:
        _ATTENDANCE_CACHE.insert(0, entry)
        if len(_ATTENDANCE_CACHE) > 500:
            del _ATTENDANCE_CACHE[500:]
        _ATTENDANCE_CACHE_AT = time.time()


def log_attendance(person_id: str) -> None:
    today_iso = date.today().isoformat()
    _reset_daily_state(today_iso)
    key = (person_id, today_iso)

    if key in SEEN_TODAY:
        return  # already logged today

    timestamp = datetime.now(timezone.utc)
    payload = {
        "person_id": person_id,
        "timestamp": timestamp.isoformat(),
        "status": "present",
        "source": "webcam",
        "synced": True,
    }

    try:
        _log_attendance_supabase(person_id=person_id, status="present", source="webcam", timestamp=timestamp)
    except Exception:
        payload["synced"] = False
        _record_metric("attendance.supabase_errors", 1.0)
    else:
        _record_metric("attendance.logged", 1.0)

    _cache_entry(payload)
    SEEN_TODAY.add(key)


def read_attendance(today_only: bool = True) -> List[Dict[str, Any]]:
    global _ATTENDANCE_CACHE_AT
    if today_only:
        with _CACHE_LOCK:
            if _ATTENDANCE_CACHE and (time.time() - _ATTENDANCE_CACHE_AT) < _ATTENDANCE_CACHE_TTL:
                return [dict(row) for row in _ATTENDANCE_CACHE]

    try:
        rows = _read_attendance_supabase(today_only=today_only)
    except Exception as e:
        # If Supabase is not available, return empty list
        import logging
        logging.warning(f"Failed to read attendance from Supabase: {e}")
        rows = []
    
    if today_only:
        for row in rows:
            row.setdefault("synced", True)
        with _CACHE_LOCK:
            _ATTENDANCE_CACHE.clear()
            _ATTENDANCE_CACHE.extend(rows)
            _ATTENDANCE_CACHE_AT = time.time()
    return rows
