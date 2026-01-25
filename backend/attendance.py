from datetime import date

from backend.supabase_db import log_attendance as _log_attendance_supabase
from backend.supabase_db import read_attendance as _read_attendance_supabase

# In-memory guard to avoid duplicates per day (per process)
SEEN_TODAY = set()
SEEN_DAY = date.today().isoformat()

def log_attendance(person_id):
    global SEEN_DAY
    today = date.today().isoformat()
    if SEEN_DAY != today:
        SEEN_TODAY.clear()
        SEEN_DAY = today
    key = (person_id, today)

    if key in SEEN_TODAY:
        return  # already logged today

    _log_attendance_supabase(person_id=person_id, status="present", source="webcam")

    SEEN_TODAY.add(key)


def read_attendance(today_only=True):
    return _read_attendance_supabase(today_only=today_only)
