"""Shared test fixtures."""

import pytest


@pytest.fixture(autouse=True)
def isolated_users_db(tmp_path, monkeypatch):
    """Point the users store at a fresh temp file for every test."""
    monkeypatch.setenv("USERS_DB_PATH", str(tmp_path / "users.json"))
