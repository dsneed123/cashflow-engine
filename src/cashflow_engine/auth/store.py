"""User storage backed by a JSON file at data/users.json."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from cashflow_engine.auth.models import User

_DEFAULT_PATH = "data/users.json"


def _get_path() -> Path:
    return Path(os.environ.get("USERS_DB_PATH", _DEFAULT_PATH))


def _load() -> list[dict]:
    path = _get_path()
    if not path.exists():
        return []
    with path.open() as f:
        return json.load(f)


def _save(users: list[dict]) -> None:
    path = _get_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(users, f, default=str, indent=2)


def get_user_by_email(email: str) -> Optional[User]:
    for u in _load():
        if u["email"] == email:
            return User(**u)
    return None


def get_user_by_id(user_id: str) -> Optional[User]:
    for u in _load():
        if u["id"] == user_id:
            return User(**u)
    return None


def create_user(user: User) -> User:
    users = _load()
    users.append(user.model_dump())
    _save(users)
    return user


def update_user(user: User) -> User:
    users = _load()
    for i, u in enumerate(users):
        if u["id"] == user.id:
            users[i] = user.model_dump()
            _save(users)
            return user
    raise ValueError(f"User {user.id} not found")
