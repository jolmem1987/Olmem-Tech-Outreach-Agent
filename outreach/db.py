from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

from outreach.config import get_settings


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    settings = get_settings()
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        yield conn


def init_db() -> None:
    schema_path = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"
    statements = [part.strip() for part in schema_path.read_text(encoding="utf-8").split(";") if part.strip()]
    with connection() as conn:
        for statement in statements:
            conn.execute(statement)
        conn.commit()


@contextmanager
def job_lock(lock_id: int) -> Iterator[bool]:
    """Prevent duplicate cron executions across Vercel instances."""
    with connection() as conn:
        row = conn.execute("SELECT pg_try_advisory_lock(%s) AS locked", (lock_id,)).fetchone()
        locked = bool(row and row["locked"])
        try:
            yield locked
        finally:
            if locked:
                conn.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
                conn.commit()


def json_dumps(value: Any) -> str:
    return json.dumps(value, default=str, separators=(",", ":"))
