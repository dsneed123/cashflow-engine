"""Shared test fixtures."""

import os

import pytest

# Set secure values before any cashflow_engine modules are imported.
# The JWT secret must be ≥32 chars and not equal to the default dev value.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-pytest-thirtytwoplus!")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_cashflow_engine_tests")


@pytest.fixture(autouse=True)
def isolated_users_db(tmp_path, monkeypatch):
    """Point the users store at a fresh temp file for every test."""
    monkeypatch.setenv("USERS_DB_PATH", str(tmp_path / "users.json"))
