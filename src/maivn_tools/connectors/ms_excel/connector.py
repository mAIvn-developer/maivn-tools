"""Microsoft Excel (Workbook) connector via Microsoft Graph."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from ..microsoft_graph._shared import TokenSource, make_graph_client


def _extract_excel_item_id(candidate: Any) -> str:
    """Pull an Excel workbook item id out of a raw string or Graph item dict."""
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError("item_id must be a non-empty string")
        return candidate
    if isinstance(candidate, dict):
        item: dict[str, Any] = cast(dict[str, Any], candidate)
        for key in ("item_id", "file_id", "workbook_id", "id"):
            value: Any = item.get(key)
            if isinstance(value, str) and value:
                return value
        raise ValueError("dict candidate has no Excel item id")
    raise ValueError("item_id must be a string or an item dict")


@toolset(prefix="excel")
class MicrosoftExcelToolSet:
    """A connector for Excel workbooks via Microsoft Graph v1.0.

    Use this for worksheet/range/table operations on existing workbooks.
    To find a workbook by name first, use :class:`MicrosoftFilesToolSet`
    (``search_files``) and pass the returned dict here — most tools
    accept either a raw item ID or a Graph item dict.
    """

    metadata = ProviderMetadata(
        name="microsoft_excel",
        display_name="Microsoft Excel",
        version="0.1.0",
        description="Read and write Excel workbook ranges, tables, and worksheets.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "Files.Read": "Read user files.",
            "Files.ReadWrite": "Read and write user files.",
            "Sites.ReadWrite.All": "Read and write SharePoint workbooks.",
        },
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://learn.microsoft.com/en-us/graph/api/resources/excel",
        homepage_url="https://www.microsoft.com/microsoft-365/excel",
        tags=("spreadsheet", "microsoft"),
    )

    def __init__(
        self,
        *,
        token: TokenSource,
        drive_id: str | None = None,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        self.connection = connection
        self._drive_root = f"drives/{drive_id}" if drive_id else "me/drive"
        self._client: HttpClient = make_graph_client(token, transport=transport)

    @property
    def client(self) -> HttpClient:
        return self._client

    def _path(self, item_id: Any, suffix: str = "") -> str:
        item_id = _extract_excel_item_id(item_id)
        base = f"/{self._drive_root}/items/{item_id}/workbook"
        return f"{base}{suffix}"

    # MARK: - Worksheets

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_worksheets(self, item_id: Any) -> dict[str, Any]:
        """List worksheets in a workbook.

        Accepts a raw item id or a Graph item dict. Returns the raw
        provider response with ``value[*]`` worksheet resources (each has
        ``id``, ``name``, ``position``).
        """
        return self._client.get(self._path(item_id, "/worksheets")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_worksheet(self, item_id: Any, name: str) -> dict[str, Any]:
        """Return one worksheet by name.

        Accepts a raw item id or a Graph item dict for ``item_id``.
        """
        if not name:
            raise ValueError("name must be a non-empty string")
        return self._client.get(self._path(item_id, f"/worksheets/{name}")).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_worksheet(self, item_id: Any, *, name: str | None = None) -> dict[str, Any]:
        """Add a new worksheet (tab).

        Accepts a raw item id or a Graph item dict. If ``name`` is None,
        Excel assigns one.
        """
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        return self._client.post(
            self._path(item_id, "/worksheets/add"),
            json=body,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_worksheet(self, item_id: Any, name: str) -> dict[str, Any]:
        """Delete a worksheet by name. Destructive — confirm with the user.

        Accepts a raw item id or a Graph item dict for ``item_id``.
        """
        if not name:
            raise ValueError("name must be a non-empty string")
        self._client.delete(self._path(item_id, f"/worksheets/{name}"))
        return {"name": name, "deleted": True}

    # MARK: - Ranges

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_range(
        self,
        item_id: Any,
        *,
        worksheet: str,
        address: str,
    ) -> dict[str, Any]:
        """Return a range by A1 address.

        Accepts a raw item id or a Graph item dict for ``item_id``.
        ``address`` is A1 notation (``"A1:B10"``).
        """
        if not worksheet or not address:
            raise ValueError("worksheet and address must be non-empty")
        return self._client.get(
            self._path(item_id, f"/worksheets/{worksheet}/range(address='{address}')"),
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_used_range(
        self,
        item_id: Any,
        *,
        worksheet: str,
        values_only: bool = False,
    ) -> dict[str, Any]:
        """Return the used range of a worksheet.

        Accepts a raw item id or a Graph item dict for ``item_id``.
        Good first call when you don't know the data extent.
        """
        suffix = f"/worksheets/{worksheet}/usedRange"
        if values_only:
            suffix += "(valuesOnly=true)"
        return self._client.get(self._path(item_id, suffix)).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_range(
        self,
        item_id: Any,
        *,
        worksheet: str,
        address: str,
        values: list[list[Any]],
        formulas: list[list[Any]] | None = None,
        number_format: list[list[Any]] | None = None,
    ) -> dict[str, Any]:
        """Patch a range with new values (and optionally formulas/format).

        Accepts a raw item id or a Graph item dict for ``item_id``.
        ``values`` is a 2D list — rows then columns.
        """
        if not worksheet or not address:
            raise ValueError("worksheet and address must be non-empty")
        body: dict[str, Any] = {"values": values}
        if formulas is not None:
            body["formulas"] = formulas
        if number_format is not None:
            body["numberFormat"] = number_format
        return self._client.patch(
            self._path(item_id, f"/worksheets/{worksheet}/range(address='{address}')"),
            json=body,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def clear_range(
        self,
        item_id: Any,
        *,
        worksheet: str,
        address: str,
        apply_to: str = "All",
    ) -> dict[str, Any]:
        """Clear a range. Destructive — confirm with the user.

        Accepts a raw item id or a Graph item dict for ``item_id``.
        ``apply_to`` is one of ``All`` (default), ``Formats``,
        ``Contents``.
        """
        if apply_to not in {"All", "Formats", "Contents"}:
            raise ValueError("apply_to must be All/Formats/Contents")
        return self._client.post(
            self._path(
                item_id,
                f"/worksheets/{worksheet}/range(address='{address}')/clear",
            ),
            json={"applyTo": apply_to},
        ).json()

    # MARK: - Tables

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_tables(self, item_id: Any, *, worksheet: str | None = None) -> dict[str, Any]:
        """List tables in a workbook or worksheet.

        Accepts a raw item id or a Graph item dict for ``item_id``.
        """
        suffix = "/tables" if worksheet is None else f"/worksheets/{worksheet}/tables"
        return self._client.get(self._path(item_id, suffix)).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_table(
        self,
        item_id: Any,
        *,
        worksheet: str,
        address: str,
        has_headers: bool = True,
    ) -> dict[str, Any]:
        """Create a table from a range.

        Accepts a raw item id or a Graph item dict for ``item_id``.
        Returns the new table resource — its ``name`` is used by
        ``add_table_rows`` / ``get_table_rows`` / ``delete_table``.
        """
        if not worksheet or not address:
            raise ValueError("worksheet and address must be non-empty")
        return self._client.post(
            self._path(item_id, f"/worksheets/{worksheet}/tables/add"),
            json={"address": address, "hasHeaders": has_headers},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_table_rows(
        self,
        item_id: Any,
        *,
        table_name: str,
        values: list[list[Any]],
        index: int | None = None,
    ) -> dict[str, Any]:
        """Append rows to a table.

        Accepts a raw item id or a Graph item dict for ``item_id``.
        Pass ``index`` to insert at a specific row; omit to append at end.
        """
        if not table_name or not values:
            raise ValueError("table_name and values must be non-empty")
        body: dict[str, Any] = {"values": values}
        if index is not None:
            body["index"] = index
        return self._client.post(
            self._path(item_id, f"/tables/{table_name}/rows/add"),
            json=body,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_table_rows(self, item_id: Any, table_name: str) -> dict[str, Any]:
        """Return all rows of a table.

        Accepts a raw item id or a Graph item dict for ``item_id``.
        """
        if not table_name:
            raise ValueError("table_name must be a non-empty string")
        return self._client.get(
            self._path(item_id, f"/tables/{table_name}/rows"),
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_table(self, item_id: Any, table_name: str) -> dict[str, Any]:
        """Delete a table. Destructive — confirm with the user.

        Accepts a raw item id or a Graph item dict for ``item_id``.
        """
        if not table_name:
            raise ValueError("table_name must be a non-empty string")
        self._client.delete(self._path(item_id, f"/tables/{table_name}"))
        return {"name": table_name, "deleted": True}

    # MARK: - Sessions

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_session(self, item_id: Any, *, persist_changes: bool = True) -> dict[str, Any]:
        """Open a workbook session.

        Accepts a raw item id or a Graph item dict for ``item_id``.
        Returns ``{"id": <session_id>, ...}`` — pass that ``id`` to
        subsequent calls via the ``Workbook-Session-Id`` header for
        efficient batch edits.
        """
        return self._client.post(
            self._path(item_id, "/createSession"),
            json={"persistChanges": persist_changes},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def close_session(
        self,
        item_id: Any,
        *,
        workbook_session_id: str,
    ) -> dict[str, Any]:
        """Close a workbook session.

        Accepts a raw item id or a Graph item dict for ``item_id``.
        """
        if not workbook_session_id:
            raise ValueError("workbook_session_id must be a non-empty string")
        response = self._client.post(
            self._path(item_id, "/closeSession"),
            headers={"Workbook-Session-Id": workbook_session_id},
            json={},
        )
        return {"session_id": workbook_session_id, "closed": True, "status": response.status}
