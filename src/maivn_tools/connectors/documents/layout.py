"""Deterministic text-table proportions shared by document renderers."""

from __future__ import annotations


def table_column_widths(rows: list[list[str]], available_width: float) -> list[float]:
    """Allocate more room to prose while bounding each column's content weight.

    The floor leaves short fields readable; the cap prevents a single long cell
    from starving the other columns. Units follow the supplied available width.
    """
    weights = [
        max(12, min(64, max(len(row[index]) for row in rows))) for index in range(len(rows[0]))
    ]
    total = sum(weights)
    return [available_width * weight / total for weight in weights]
