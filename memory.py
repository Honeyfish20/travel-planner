"""Traveller-profile memory (local stand-in for AgentCore Memory).

Each profile id is its own namespace (e.g. one family). After a successful
plan the members' ages, allergies, mobility and diet are saved, and the next
plan with the same id carries them over automatically.

Stored locally in memory/profiles.json. It contains children's ages and health
information, so keep the folder private and use only demo data.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

MEMORY_DIR = Path(os.environ.get("MEMORY_DIR", Path(__file__).resolve().parent / "memory"))
_ID_RE = re.compile(r"^[\w\-]{1,32}$")  # \w covers CJK characters for str patterns
_MEMBER_KEYS = ("role", "age", "mobility", "max_walk_km", "allergies", "diet", "group")
_lock = threading.Lock()


def valid_id(profile_id) -> bool:
    return isinstance(profile_id, str) and bool(_ID_RE.match(profile_id))


def _file() -> Path:
    return MEMORY_DIR / "profiles.json"


def _load_all() -> dict:
    try:
        return json.loads(_file().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return {}


def _write_all(profiles: dict) -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _file().with_suffix(".tmp")
    tmp.write_text(json.dumps(profiles, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, _file())


def get_profile(profile_id: str) -> Optional[dict]:
    if not valid_id(profile_id):
        return None
    with _lock:
        return _load_all().get(profile_id)


def save_profile(profile_id: str, req: dict) -> dict:
    if not valid_id(profile_id):
        raise ValueError("invalid profile id")
    profile = {
        "members": [{k: m[k] for k in _MEMBER_KEYS} for m in req["members"]],
        "nationality": req["nationality"],
        "language": req["language"],
        "home_currency": req["home_currency"],
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    with _lock:
        profiles = _load_all()
        profiles[profile_id] = profile
        _write_all(profiles)
    return profile


def delete_profile(profile_id: str) -> bool:
    if not valid_id(profile_id):
        return False
    with _lock:
        profiles = _load_all()
        if profile_id not in profiles:
            return False
        del profiles[profile_id]
        _write_all(profiles)
        return True
