"""
Shared fixtures for Oracle E2E tests (Day 6).

Canonical cross-DB test schema and boundary-value rows for Oracle ↔ Postgres/MySQL/ClickHouse.
"""
from decimal import Decimal
from datetime import datetime, timezone
from connections.connectors.base import ColumnInfo

# Canonical schema: id, name, description, amount, created_at, is_active
# Oracle types (source) -> same logical types for other DBs
ORACLE_CANONICAL_COLUMNS = [
    ColumnInfo("id", "NUMBER", False, True),
    ColumnInfo("name", "VARCHAR2(255)", True, False),
    ColumnInfo("description", "CLOB", True, False),
    ColumnInfo("amount", "NUMBER(38,10)", True, False),
    ColumnInfo("created_at", "TIMESTAMP WITH TIME ZONE", True, False),
    ColumnInfo("is_active", "NUMBER(1)", True, False),
]
CANONICAL_COLUMN_NAMES = [c.name for c in ORACLE_CANONICAL_COLUMNS]


def get_canonical_boundary_rows():
    """
    Boundary-value rows for canonical schema: min/mid/max numerics, timezones, long text, boolean.
    Returns list of tuples (id, name, description, amount, created_at, is_active).
    """
    ts_utc = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    ts_other = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    long_text = "x" * 2000  # Multi-KB CLOB
    return [
        (1, "min", "short", Decimal("0.0000000001"), ts_utc, 0),
        (2, "mid", long_text, Decimal("1234567890.1234567890"), ts_other, 1),
        (3, "max", "tail", Decimal("99999999999999999999.9999999999"), ts_utc, 1),
    ]


def get_canonical_boundary_rows_no_decimal():
    """Same as get_canonical_boundary_rows but amount as float for DBs that don't return Decimal."""
    rows = get_canonical_boundary_rows()
    out = []
    for r in rows:
        amount = r[3]
        if isinstance(amount, Decimal):
            amount = float(amount)
        out.append((r[0], r[1], r[2], amount, r[4], r[5]))
    return out
