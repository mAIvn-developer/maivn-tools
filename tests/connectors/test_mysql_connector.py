# pyright: strict
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from maivn_tools.connectors.databases import MySQLToolSet


class _Cursor:
    def __init__(self, plan: list[dict[str, Any]]) -> None:
        self._plan = plan
        self.description: Any = None
        self._rows: list[tuple[Any, ...]] = []
        self.executed: list[tuple[str, Any]] = []

    def execute(self, query: str, params: Any = None) -> None:
        self.executed.append((query, params))
        # The connector issues a session-level read-only SET before the real
        # query; skip it so it does not consume a planned response.
        if query.lstrip().upper().startswith("SET "):
            return
        if not self._plan:
            self.description = None
            self._rows = []
            return
        match = self._plan.pop(0)
        self.description = [(name,) for name in match["columns"]]
        self._rows = list(match["rows"])

    def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
        head = self._rows[:size]
        self._rows = self._rows[size:]
        return head

    def close(self) -> None:
        pass


class _Connection:
    def __init__(self, plan: list[dict[str, Any]]) -> None:
        self._plan = plan
        self.closed = False

    def cursor(self) -> _Cursor:
        return _Cursor(self._plan)

    def close(self) -> None:
        self.closed = True


def make_factory(plan: list[dict[str, Any]]) -> Callable[[], _Connection]:
    return lambda: _Connection(plan)


def test_mysql_count_rows_returns_count() -> None:
    plan = [{"columns": ["row_count"], "rows": [(42,)]}]
    connector = MySQLToolSet(connection_factory=make_factory(plan), row_limit=10)
    info = connector.count_rows(name="users")
    assert info["row_count"] == 42
    assert info["name"] == "users"


def test_mysql_sample_table_runs_for_valid_identifier() -> None:
    """Regression: legitimate identifiers must still pass validation and run."""
    plan = [{"columns": ["id"], "rows": [(1,), (2,)]}]
    connector = MySQLToolSet(connection_factory=make_factory(plan), row_limit=10)
    result = connector.sample_table(name="users", schema="shop", limit=2)
    assert result["row_count"] == 2


def test_mysql_sample_table_rejects_identifier_injection() -> None:
    connector = MySQLToolSet(connection_factory=make_factory([]), row_limit=10)
    backtick_breakout = "users` UNION SELECT schema_name, 1 FROM information_schema.schemata -- "
    with pytest.raises(ValueError):
        connector.sample_table(name=backtick_breakout)
    with pytest.raises(ValueError):
        connector.sample_table(name="users", schema="shop`.`secret")


def test_mysql_count_rows_rejects_identifier_injection() -> None:
    connector = MySQLToolSet(connection_factory=make_factory([]), row_limit=10)
    with pytest.raises(ValueError):
        connector.count_rows(name="users` UNION SELECT user(), 1 -- ")
    with pytest.raises(ValueError):
        connector.count_rows(name="users", schema="a`.`b")
