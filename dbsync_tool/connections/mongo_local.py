"""
Helpers for MongoDB "localhost dev" ergonomics (optional credentials).

Mirrors the rules in `DatabaseConnectionForm.clean()` so API-style callers
(JSON test endpoint, scripts) behave consistently with the HTML form.
"""

from __future__ import annotations

from typing import Optional, Tuple


LOCAL_MONGO_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def is_local_mongo_host(host: Optional[str]) -> bool:
    h = (host or "").strip().lower()
    return h in LOCAL_MONGO_HOSTS


def normalize_mongo_credentials(
    host: Optional[str], username: Optional[str], password: Optional[str]
) -> Tuple[str, str]:
    """
    Apply MongoDB localhost defaults and validate partial credential input.

    Returns (username, password) suitable for `get_connector(...)`.
    """
    user = (username or "").strip()
    # Treat None as empty; keep password as-is for non-empty values.
    pwd = "" if password is None else password

    if not is_local_mongo_host(host):
        if not user:
            raise ValueError("Username is required.")
        if not pwd:
            raise ValueError("Password is required.")
        return user, pwd

    # Localhost convenience: empty + empty -> root/root (see DatabaseConnectionForm).
    if not user and not pwd:
        return "root", "root"
    if bool(user) != bool(pwd):
        raise ValueError(
            "For MongoDB, provide both Username and Password "
            "(or leave both empty for local root/root default)."
        )
    return user, pwd
