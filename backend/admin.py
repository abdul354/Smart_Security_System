from backend.enrollment import _get_collection  # chroma collection getter
from backend.supabase_db import delete_person as _delete_person_supabase
from backend.supabase_db import list_persons as _list_persons_supabase

def list_persons():
    return _list_persons_supabase()


def delete_person(person_id: str):
    # 1. Delete from ChromaDB
    collection = _get_collection()
    collection.delete(where={"person_id": person_id})

    # 2. Delete from Supabase (attendance cascades)
    _delete_person_supabase(person_id)
