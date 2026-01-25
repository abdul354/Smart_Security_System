from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional

from supabase import Client, create_client


class SupabaseConfigError(RuntimeError):
    pass


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SupabaseConfigError(f"Missing required environment variable: {name}")
    return value


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    url = _require_env("SUPABASE_URL")
    key = _require_env("SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key)


def upsert_person(*, person_id: str, display_name: str, role: str, department: str, access_status: str,
                  enrolled_at: Optional[datetime] = None) -> None:
    payload: Dict[str, Any] = {
        "person_id": person_id,
        "display_name": display_name,
        "role": role,
        "department": department,
        "access_status": access_status,
    }
    if enrolled_at is not None:
        if enrolled_at.tzinfo is None:
            enrolled_at = enrolled_at.replace(tzinfo=timezone.utc)
        payload["enrolled_at"] = enrolled_at.isoformat()

    get_supabase().table("persons").upsert(payload).execute()


def get_person(person_id: str) -> Optional[Dict[str, Any]]:
    res = (
        get_supabase()
        .table("persons")
        .select("person_id,display_name,role,department,access_status,enrolled_at")
        .eq("person_id", person_id)
        .limit(1)
        .execute()
    )
    rows = getattr(res, "data", None) or []
    return rows[0] if rows else None


def list_persons() -> List[Dict[str, Any]]:
    res = (
        get_supabase()
        .table("persons")
        .select("person_id,display_name,role,department,access_status,enrolled_at")
        .order("enrolled_at", desc=True)
        .execute()
    )
    return getattr(res, "data", None) or []


def delete_person(person_id: str) -> None:
    get_supabase().table("persons").delete().eq("person_id", person_id).execute()


def log_attendance(*, person_id: str, status: str = "present", source: str = "webcam",
                   timestamp: Optional[datetime] = None) -> None:
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    elif timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    payload: Dict[str, Any] = {
        "person_id": person_id,
        "timestamp": timestamp.isoformat(),
        "status": status,
        "source": source,
    }

    # Schema enforces one attendance row per person per day via unique(person_id, attendance_day)
    get_supabase().table("attendance").upsert(payload, on_conflict="person_id,attendance_day").execute()


def read_attendance(*, today_only: bool = True, limit: int = 5000) -> List[Dict[str, Any]]:
    q = (
        get_supabase()
        .table("attendance")
        .select("timestamp,person_id,status,source")
        .order("timestamp", desc=True)
        .limit(limit)
    )

    if today_only:
        today = datetime.now(timezone.utc).date()
        start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        q = q.gte("timestamp", start.isoformat()).lt("timestamp", end.isoformat())

    res = q.execute()
    return getattr(res, "data", None) or []
