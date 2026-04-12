"""
Helpers for opt-in Postgres → ClickHouse E2E sync tests.

See test_e2e_postgres_clickhouse_sync.py for environment variables.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from django.contrib.auth.models import User

from connections.models import DatabaseConnection
from core.encryption import encrypt_password


def create_e2e_pg_ch_connections(
    user: User,
    *,
    pg: Dict[str, Any],
    ch: Dict[str, Any],
) -> Tuple[DatabaseConnection, DatabaseConnection]:
    """
    Create DatabaseConnection rows for live E2E (passwords encrypted on save).

    pg keys: host, port, database_name, username, password
    ch keys: host, port, database_name, username, password
    """
    tenant = user
    pg_conn = DatabaseConnection.objects.create(
        name="E2E PostgreSQL (PG→CH)",
        db_type="postgres",
        host=pg["host"],
        port=int(pg["port"]),
        username=pg["username"],
        password=encrypt_password(pg["password"]),
        database_name=pg["database_name"],
        created_by=user,
        tenant=tenant,
        is_active=True,
    )
    ch_conn = DatabaseConnection.objects.create(
        name="E2E ClickHouse (PG→CH)",
        db_type="clickhouse",
        host=ch["host"],
        port=int(ch["port"]),
        username=ch["username"],
        password=encrypt_password(ch["password"]),
        database_name=ch["database_name"],
        created_by=user,
        tenant=tenant,
        is_active=True,
    )
    return pg_conn, ch_conn
