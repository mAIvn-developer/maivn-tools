"""Pinterest API v5 connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import (
    LIST_BOARD_PINS_OUTPUT,
    LIST_BOARDS_OUTPUT,
    LIST_PINS_OUTPUT,
)


@toolset(prefix="pinterest")
class PinterestToolSet:
    """A connector for the Pinterest v5 REST API.

    Args:
        access_token: OAuth 2.0 access token.
    """

    metadata = ProviderMetadata(
        name="pinterest",
        display_name="Pinterest",
        version="0.1.0",
        description="Boards, pins, and analytics for the authenticated user.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "user_accounts:read": "Read account metadata.",
            "boards:read": "Read boards.",
            "boards:write": "Create / update boards.",
            "pins:read": "Read pins.",
            "pins:write": "Create / update pins.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://developers.pinterest.com/docs/api/v5/",
        homepage_url="https://www.pinterest.com/",
        tags=("social-media", "visual"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        base_url: str = "https://api.pinterest.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(access_token),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - Internal helpers

    @staticmethod
    def _select_pin_id(candidate: Any) -> str:
        """Resolve a pin ID from a string or a pin dict from listings."""
        if isinstance(candidate, str):
            if not candidate:
                raise ValueError("pin_id must be a non-empty string")
            return candidate
        if isinstance(candidate, dict):
            mapping = cast(dict[str, Any], candidate)
            for key in ("pin_id", "id"):
                value = mapping.get(key)
                if isinstance(value, str) and value:
                    return value
        if isinstance(candidate, list) and candidate:
            items = cast(list[Any], candidate)
            return PinterestToolSet._select_pin_id(items[0])
        raise ValueError("could not resolve pin_id from input")

    @classmethod
    def _board_summary(
        cls,
        board: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        owner: object = board.get("owner") or {}
        username = (
            cast(dict[str, Any], owner).get("username", "") if isinstance(owner, dict) else ""
        )
        summary: dict[str, Any] = {
            "board_ref": f"board_{index}",
            "name": board.get("name", ""),
            "description": board.get("description", ""),
            "privacy": board.get("privacy", ""),
            "owner": username,
            "pin_count": board.get("pin_count", 0),
            "follower_count": board.get("follower_count", 0),
            "created_at": board.get("created_at", ""),
        }
        if include_ids:
            summary["board_id"] = board.get("id", "")
        return summary

    @classmethod
    def _pin_summary(
        cls,
        pin: dict[str, Any],
        *,
        index: int,
        include_ids: bool,
    ) -> dict[str, Any]:
        pin_id = pin.get("id", "")
        summary: dict[str, Any] = {
            "pin_ref": f"pin_{index}",
            "title": pin.get("title", ""),
            "description": pin.get("description", ""),
            "alt_text": pin.get("alt_text", ""),
            "link": pin.get("link", ""),
            "created_at": pin.get("created_at", ""),
            "url": f"https://www.pinterest.com/pin/{pin_id}/" if pin_id else "",
        }
        if include_ids:
            summary["pin_id"] = pin_id
            board_id = pin.get("board_id", "")
            if board_id:
                summary["board_id"] = board_id
        return summary

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user_account(self) -> dict[str, Any]:
        """Return the authenticated user's account.

        Returns the raw Pinterest user account resource (``username``,
        ``account_type``, ``board_count``, ``pin_count``, ``followers``).
        """
        return self._client.get("/v5/user_account").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_BOARDS_OUTPUT)
    def list_boards(
        self,
        *,
        bookmark: str | None = None,
        page_size: int = 25,
        privacy: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List boards owned by the authenticated user.

        Best first tool for Pinterest board triage. Default returns
        compact summaries: ``board_ref`` (stable ``board_1`` ...),
        ``name``, ``description``, ``privacy``, ``owner`` (username),
        pin/follower counts, ``created_at``. Raw Pinterest board IDs are
        omitted unless ``include_ids=True``. Set ``include_metadata=False``
        for the raw Pinterest response.
        """
        params: dict[str, Any] = {"page_size": page_size}
        if bookmark is not None:
            params["bookmark"] = bookmark
        if privacy is not None:
            params["privacy"] = privacy
        payload: dict[str, Any] = self._client.get("/v5/boards", params=params).json()
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("items", [])
        summaries: list[dict[str, Any]] = []
        for index, board in enumerate(items, start=1):
            if not isinstance(board, dict):
                continue
            summaries.append(
                self._board_summary(
                    cast(dict[str, Any], board), index=index, include_ids=include_ids
                )
            )
        return {
            "boards": summaries,
            "bookmark": payload.get("bookmark"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_board(self, board_id: str) -> dict[str, Any]:
        """Fetch one board by its Pinterest internal ID.

        Returns the raw Pinterest board resource. Use after
        ``list_boards(include_ids=True)`` when you need the full board
        details.
        """
        if not board_id:
            raise ValueError("board_id is required")
        return self._client.get(f"/v5/boards/{board_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_board(
        self,
        *,
        name: str,
        description: str | None = None,
        privacy: str = "PUBLIC",
    ) -> dict[str, Any]:
        """Create a new board.

        Returns the new board resource (``id``, ``name``, ``privacy``).
        ``privacy`` must be ``PUBLIC``, ``SECRET``, or ``PROTECTED``.
        """
        if not name:
            raise ValueError("name is required")
        if privacy not in {"PUBLIC", "SECRET", "PROTECTED"}:
            raise ValueError("privacy must be PUBLIC/SECRET/PROTECTED")
        body: dict[str, Any] = {"name": name, "privacy": privacy}
        if description is not None:
            body["description"] = description
        return self._client.post("/v5/boards", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_board(self, board_id: str) -> dict[str, Any]:
        """Permanently delete a board (and all its pins).

        Destructive and not reversible — confirm with the user.
        """
        if not board_id:
            raise ValueError("board_id is required")
        response = self._client.delete(f"/v5/boards/{board_id}")
        return {"board_id": board_id, "deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_BOARD_PINS_OUTPUT)
    def list_board_pins(
        self,
        board_id: str,
        *,
        bookmark: str | None = None,
        page_size: int = 25,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List pins on a board.

        Default returns compact summaries: ``pin_ref`` (stable
        ``pin_1`` ...), ``title``, ``description``, ``alt_text``,
        ``link``, ``created_at``, and ``url``. Raw Pinterest pin IDs are
        omitted unless ``include_ids=True``.
        """
        if not board_id:
            raise ValueError("board_id is required")
        params: dict[str, Any] = {"page_size": page_size}
        if bookmark is not None:
            params["bookmark"] = bookmark
        payload: dict[str, Any] = self._client.get(
            f"/v5/boards/{board_id}/pins", params=params
        ).json()
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("items", [])
        summaries: list[dict[str, Any]] = []
        for index, pin in enumerate(items, start=1):
            if not isinstance(pin, dict):
                continue
            summaries.append(
                self._pin_summary(cast(dict[str, Any], pin), index=index, include_ids=include_ids)
            )
        return {
            "pins": summaries,
            "bookmark": payload.get("bookmark"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_PINS_OUTPUT)
    def list_pins(
        self,
        *,
        bookmark: str | None = None,
        page_size: int = 25,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List pins owned by the authenticated user across all boards.

        Default returns compact summaries (same shape as
        ``list_board_pins``). Set ``include_ids=True`` to expose raw pin
        IDs.
        """
        params: dict[str, Any] = {"page_size": page_size}
        if bookmark is not None:
            params["bookmark"] = bookmark
        payload: dict[str, Any] = self._client.get("/v5/pins", params=params).json()
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("items", [])
        summaries: list[dict[str, Any]] = []
        for index, pin in enumerate(items, start=1):
            if not isinstance(pin, dict):
                continue
            summaries.append(
                self._pin_summary(cast(dict[str, Any], pin), index=index, include_ids=include_ids)
            )
        return {
            "pins": summaries,
            "bookmark": payload.get("bookmark"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_pin(self, pin_id: str) -> dict[str, Any]:
        """Fetch one pin by Pinterest internal ID.

        Returns the raw Pinterest pin resource. Use after
        ``list_pins(include_ids=True)`` when you need full pin details.
        """
        if not pin_id:
            raise ValueError("pin_id is required")
        return self._client.get(f"/v5/pins/{pin_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_pin(
        self,
        *,
        board_id: str,
        media_source: dict[str, Any],
        title: str | None = None,
        description: str | None = None,
        link: str | None = None,
        alt_text: str | None = None,
    ) -> dict[str, Any]:
        """Create a new pin on a board.

        Returns the new pin resource. ``media_source`` is a Pinterest
        media-source dict (e.g. ``{"source_type": "image_url", "url":
        "https://..."}``).
        """
        if not board_id or not media_source:
            raise ValueError("board_id and media_source are required")
        body: dict[str, Any] = {"board_id": board_id, "media_source": media_source}
        if title is not None:
            body["title"] = title
        if description is not None:
            body["description"] = description
        if link is not None:
            body["link"] = link
        if alt_text is not None:
            body["alt_text"] = alt_text
        return self._client.post("/v5/pins", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_pin(self, pin: str | dict[str, Any]) -> dict[str, Any]:
        """Permanently delete a pin.

        Accepts a raw ``pin_id`` string OR a pin dict from ``list_pins``
        (looks up ``pin_id`` / ``id``). Destructive and not reversible —
        confirm with the user.
        """
        pin_id = self._select_pin_id(pin)
        response = self._client.delete(f"/v5/pins/{pin_id}")
        return {"pin_id": pin_id, "deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_pin_analytics(
        self,
        pin_id: str,
        *,
        start_date: str,
        end_date: str,
        metric_types: list[str],
    ) -> dict[str, Any]:
        """Return analytics for one pin.

        Returns the raw Pinterest analytics response. Dates are
        ``YYYY-MM-DD``; ``metric_types`` is the list of Pinterest metric
        names (e.g. ``["IMPRESSION", "CLICKTHROUGH"]``).
        """
        if not pin_id or not start_date or not end_date or not metric_types:
            raise ValueError("pin_id, start_date, end_date, and metric_types are required")
        return self._client.get(
            f"/v5/pins/{pin_id}/analytics",
            params={
                "start_date": start_date,
                "end_date": end_date,
                "metric_types": ",".join(metric_types),
            },
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user_analytics(
        self,
        *,
        start_date: str,
        end_date: str,
        metric_types: list[str],
    ) -> dict[str, Any]:
        """Return account-level analytics.

        Returns the raw Pinterest analytics response.
        """
        if not start_date or not end_date or not metric_types:
            raise ValueError("start_date, end_date, and metric_types are required")
        return self._client.get(
            "/v5/user_account/analytics",
            params={
                "start_date": start_date,
                "end_date": end_date,
                "metric_types": ",".join(metric_types),
            },
        ).json()
