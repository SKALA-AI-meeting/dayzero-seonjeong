"""Thin psycopg helpers. Each business transaction runs inside `tx()`."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

_pools: dict[str, ConnectionPool] = {}


def pool(dsn: str) -> ConnectionPool:
    if dsn not in _pools:
        _pools[dsn] = ConnectionPool(dsn, min_size=1, max_size=10, kwargs={"row_factory": dict_row}, open=True)
    return _pools[dsn]


@contextmanager
def tx(dsn: str) -> Iterator[Any]:
    with pool(dsn).connection() as conn:
        with conn.transaction():
            yield conn


def one(conn, sql: str, params: Any = None) -> dict | None:
    return conn.execute(sql, params).fetchone()


def all_(conn, sql: str, params: Any = None) -> list[dict]:
    return conn.execute(sql, params).fetchall()


J = Jsonb
