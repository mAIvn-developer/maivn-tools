"""Pagination helpers covering the styles common across REST APIs.

The helpers iterate over a callable that fetches one page at a time. Each
helper handles a different provider convention:

* :class:`CursorPaginator` for opaque ``next_cursor`` continuations.
* :class:`OffsetPaginator` for ``offset``/``limit`` pagination.
* :class:`PageTokenPaginator` for ``page_token`` continuations.
* :class:`DeltaTokenPaginator` for change-feeds that yield a final delta
  token and may not include a paginating cursor at all.

Each paginator is generic in the page and item types. Tools can yield
individual items via ``iter_items`` or full pages via ``iter_pages``.
"""

# pyright: strict

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Sequence
from typing import Any, Generic, TypeVar

# MARK: Type variables

Page = TypeVar("Page")
Item = TypeVar("Item")

# MARK: Base paginator


class Paginator(ABC, Generic[Page, Item]):
    """Base class for paginators.

    Subclasses fetch one page at a time. The base class provides
    :meth:`iter_pages` and :meth:`iter_items` for callers.
    """

    @abstractmethod
    def fetch(self, state: Any) -> tuple[Page, Any]:
        """Fetch a page given a paginator-specific ``state``.

        Returns a tuple of ``(page, next_state)``. When ``next_state`` is
        ``None``, iteration stops after yielding ``page``.
        """

    @abstractmethod
    def initial_state(self) -> Any:
        """Return the state used for the first call to :meth:`fetch`."""

    @abstractmethod
    def items_of(self, page: Page) -> Sequence[Item]:
        """Return the items contained in ``page``."""

    def iter_pages(self) -> Iterator[Page]:
        """Yield raw pages until the provider signals completion."""
        state = self.initial_state()
        while True:
            page, next_state = self.fetch(state)
            yield page
            if next_state is None:
                return
            state = next_state

    def iter_items(self) -> Iterator[Item]:
        """Yield each item across every page."""
        for page in self.iter_pages():
            yield from self.items_of(page)


# MARK: Concrete paginators


class CursorPaginator(Paginator[dict[str, Any], Any]):
    """Cursor-style paginator.

    Args:
        fetch_page: Callable that accepts a cursor (``None`` on first call)
            and returns a ``(page_dict, next_cursor)`` tuple. Pagination ends
            when ``next_cursor`` is ``None``.
        items_key: Dictionary key under which the page list lives. Defaults
            to ``"items"``.
    """

    def __init__(
        self,
        fetch_page: Callable[[Any], tuple[dict[str, Any], Any]],
        *,
        items_key: str = "items",
    ) -> None:
        self._fetch = fetch_page
        self._items_key = items_key

    def initial_state(self) -> Any:
        return None

    def fetch(self, state: Any) -> tuple[dict[str, Any], Any]:
        page, next_cursor = self._fetch(state)
        return page, next_cursor

    def items_of(self, page: dict[str, Any]) -> Sequence[Any]:
        return list(page.get(self._items_key, []))


class OffsetPaginator(Paginator[dict[str, Any], Any]):
    """Offset/limit-style paginator.

    Args:
        fetch_page: Callable accepting ``(offset, limit)`` returning a page.
        page_size: Number of records to request per page.
        items_key: Dictionary key under which the page list lives. Defaults
            to ``"items"``.
        total_key: Optional key whose value is the total record count. When
            absent, iteration stops once a page returns fewer than
            ``page_size`` items.
    """

    def __init__(
        self,
        fetch_page: Callable[[int, int], dict[str, Any]],
        *,
        page_size: int,
        items_key: str = "items",
        total_key: str | None = None,
    ) -> None:
        if page_size < 1:
            raise ValueError("page_size must be at least 1")
        self._fetch = fetch_page
        self._page_size = page_size
        self._items_key = items_key
        self._total_key = total_key

    def initial_state(self) -> Any:
        return 0

    def fetch(self, state: Any) -> tuple[dict[str, Any], Any]:
        offset = int(state)
        page = self._fetch(offset, self._page_size)
        items: list[Any] = list(page.get(self._items_key) or [])
        if self._total_key is not None and self._total_key in page:
            total = int(page[self._total_key])
            next_offset = offset + len(items)
            if next_offset >= total or not items:
                return page, None
            return page, next_offset
        if len(items) < self._page_size:
            return page, None
        return page, offset + len(items)

    def items_of(self, page: dict[str, Any]) -> Sequence[Any]:
        return list(page.get(self._items_key, []))


class PageTokenPaginator(Paginator[dict[str, Any], Any]):
    """Page-token style paginator (Google-style ``next_page_token``).

    Args:
        fetch_page: Callable accepting a page token (``None`` on first call)
            and returning the page dict. The page should expose the next
            token under ``token_key``.
        token_key: Dictionary key holding the next page token. Defaults to
            ``"next_page_token"``.
        items_key: Dictionary key holding the page items. Defaults to
            ``"items"``.
    """

    def __init__(
        self,
        fetch_page: Callable[[str | None], dict[str, Any]],
        *,
        token_key: str = "next_page_token",
        items_key: str = "items",
    ) -> None:
        self._fetch = fetch_page
        self._token_key = token_key
        self._items_key = items_key

    def initial_state(self) -> Any:
        return None

    def fetch(self, state: Any) -> tuple[dict[str, Any], Any]:
        page = self._fetch(state)
        token = page.get(self._token_key)
        return page, token or None

    def items_of(self, page: dict[str, Any]) -> Sequence[Any]:
        return list(page.get(self._items_key, []))


class DeltaTokenPaginator(Paginator[dict[str, Any], Any]):
    """Delta-token style paginator for change-feeds.

    The change feed advances using ``next_link``-style cursors and terminates
    by returning a ``delta_token`` instead. Callers can retrieve the final
    delta token via :attr:`final_delta_token` after iteration completes.

    Args:
        fetch_page: Callable accepting a cursor (``None`` on first call) and
            returning the page dict.
        next_key: Key holding the cursor for the following page.
        delta_key: Key holding the final delta token.
        items_key: Key holding the page items.
    """

    def __init__(
        self,
        fetch_page: Callable[[str | None], dict[str, Any]],
        *,
        next_key: str = "next_link",
        delta_key: str = "delta_token",
        items_key: str = "items",
    ) -> None:
        self._fetch = fetch_page
        self._next_key = next_key
        self._delta_key = delta_key
        self._items_key = items_key
        self.final_delta_token: str | None = None

    def initial_state(self) -> Any:
        return None

    def fetch(self, state: Any) -> tuple[dict[str, Any], Any]:
        page = self._fetch(state)
        next_link = page.get(self._next_key)
        if next_link:
            return page, next_link
        self.final_delta_token = page.get(self._delta_key)
        return page, None

    def items_of(self, page: dict[str, Any]) -> Sequence[Any]:
        return list(page.get(self._items_key, []))
