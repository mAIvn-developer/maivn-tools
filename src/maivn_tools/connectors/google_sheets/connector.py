"""Google Sheets API v4 connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from ..google_workspace._shared import TokenSource, make_bearer_auth


def _extract_sheet_id(candidate: Any) -> str:
    """Pull a Google Sheets ``spreadsheetId`` out of a raw string or sheet dict."""
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError("spreadsheet_id must be a non-empty string")
        return candidate
    if isinstance(candidate, dict):
        candidate_dict = cast("dict[str, Any]", candidate)
        for key in ("sheet_ref_id", "spreadsheet_id", "spreadsheetId", "file_id", "id"):
            value: Any = candidate_dict.get(key)
            if isinstance(value, str) and value:
                return value
        raise ValueError("dict candidate has no spreadsheet id")
    raise ValueError("spreadsheet_id must be a string or a spreadsheet dict")


@toolset(prefix="google_sheets")
class GoogleSheetsToolSet:
    """A connector for the Google Sheets API v4.

    Use this for cell/range/sheet operations on existing spreadsheets. To
    find a sheet by name first, use :class:`GoogleDriveToolSet`
    (``search_files``) and pass the returned dict here — most tools
    accept either a raw spreadsheet ID or a Drive file dict.
    """

    metadata = ProviderMetadata(
        name="google_sheets",
        display_name="Google Sheets",
        version="0.1.0",
        description="Read and write ranges, append rows, manage spreadsheets.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        scopes={
            "https://www.googleapis.com/auth/spreadsheets": "Full Sheets access.",
            "https://www.googleapis.com/auth/spreadsheets.readonly": "Read-only Sheets access.",
        },
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developers.google.com/sheets/api/reference/rest",
        homepage_url="https://sheets.google.com/",
        tags=("sheets", "google-workspace"),
    )

    def __init__(
        self,
        *,
        token: TokenSource,
        base_url: str = "https://sheets.googleapis.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=make_bearer_auth(token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_spreadsheet(
        self,
        spreadsheet_id: Any,
        *,
        include_grid_data: bool = False,
        ranges: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return spreadsheet metadata (and optionally grid data).

        Accepts a raw spreadsheet ID or a Drive file dict (from
        ``GoogleDriveToolSet.search_files(include_ids=True)``). Returns
        the full spreadsheet resource — ``properties``, ``sheets[*]``,
        ``namedRanges``. With ``include_grid_data=True`` and ``ranges``
        you get cell-level values too.
        """
        spreadsheet_id = _extract_sheet_id(spreadsheet_id)
        params: dict[str, Any] = {}
        if include_grid_data:
            params["includeGridData"] = "true"
        if ranges is not None:
            params["ranges"] = ranges
        return self._client.get(
            f"/v4/spreadsheets/{spreadsheet_id}",
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_spreadsheet(
        self,
        *,
        title: str,
        sheets: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a new spreadsheet.

        Returns the new spreadsheet resource. Pass ``spreadsheetId`` from
        the result to other tools.
        """
        if not title:
            raise ValueError("title must be a non-empty string")
        body: dict[str, Any] = {"properties": {"title": title}}
        if sheets is not None:
            body["sheets"] = sheets
        return self._client.post("/v4/spreadsheets", json=body).json()

    # MARK: - Values

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_values(
        self,
        spreadsheet_id: Any,
        range: str,
        *,
        major_dimension: str = "ROWS",
        value_render_option: str | None = None,
        date_time_render_option: str | None = None,
    ) -> dict[str, Any]:
        """Read a range of values.

        Accepts a raw spreadsheet ID or a sheet dict. ``range`` is an A1
        notation like ``"Sheet1!A1:B10"``. Returns ``{"range": ...,
        "majorDimension": ..., "values": [[...], ...]}``.
        """
        spreadsheet_id = _extract_sheet_id(spreadsheet_id)
        if not range:
            raise ValueError("range must be non-empty")
        params: dict[str, Any] = {"majorDimension": major_dimension}
        if value_render_option is not None:
            params["valueRenderOption"] = value_render_option
        if date_time_render_option is not None:
            params["dateTimeRenderOption"] = date_time_render_option
        return self._client.get(
            f"/v4/spreadsheets/{spreadsheet_id}/values/{range}",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def batch_get_values(
        self,
        spreadsheet_id: Any,
        ranges: list[str],
        *,
        major_dimension: str = "ROWS",
        value_render_option: str | None = None,
    ) -> dict[str, Any]:
        """Read multiple ranges at once.

        Accepts a raw spreadsheet ID or a sheet dict. Returns
        ``{"spreadsheetId": ..., "valueRanges": [...]}``.
        """
        spreadsheet_id = _extract_sheet_id(spreadsheet_id)
        if not ranges:
            raise ValueError("ranges must be non-empty")
        params: dict[str, Any] = {
            "ranges": ranges,
            "majorDimension": major_dimension,
        }
        if value_render_option is not None:
            params["valueRenderOption"] = value_render_option
        return self._client.get(
            f"/v4/spreadsheets/{spreadsheet_id}/values:batchGet",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_values(
        self,
        spreadsheet_id: Any,
        range: str,
        *,
        values: list[list[Any]],
        value_input_option: str = "USER_ENTERED",
    ) -> dict[str, Any]:
        """Overwrite a range of values.

        Accepts a raw spreadsheet ID or a sheet dict. ``value_input_option``
        is ``USER_ENTERED`` (parse formulas) or ``RAW`` (literal strings).
        Returns the update response with ``updatedRange`` and ``updatedCells``.
        """
        spreadsheet_id = _extract_sheet_id(spreadsheet_id)
        if not range:
            raise ValueError("range must be non-empty")
        if value_input_option not in {"RAW", "USER_ENTERED"}:
            raise ValueError("value_input_option must be RAW or USER_ENTERED")
        return self._client.put(
            f"/v4/spreadsheets/{spreadsheet_id}/values/{range}",
            params={"valueInputOption": value_input_option},
            json={"range": range, "values": values, "majorDimension": "ROWS"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def append_values(
        self,
        spreadsheet_id: Any,
        range: str,
        *,
        values: list[list[Any]],
        value_input_option: str = "USER_ENTERED",
        insert_data_option: str = "INSERT_ROWS",
    ) -> dict[str, Any]:
        """Append rows below the table that covers ``range``.

        Accepts a raw spreadsheet ID or a sheet dict.
        """
        spreadsheet_id = _extract_sheet_id(spreadsheet_id)
        if not range:
            raise ValueError("range must be non-empty")
        return self._client.post(
            f"/v4/spreadsheets/{spreadsheet_id}/values/{range}:append",
            params={
                "valueInputOption": value_input_option,
                "insertDataOption": insert_data_option,
            },
            json={"values": values},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def clear_values(
        self,
        spreadsheet_id: Any,
        range: str,
    ) -> dict[str, Any]:
        """Clear a range (does not delete formatting). Destructive — confirm with user.

        Accepts a raw spreadsheet ID or a sheet dict.
        """
        spreadsheet_id = _extract_sheet_id(spreadsheet_id)
        if not range:
            raise ValueError("range must be non-empty")
        return self._client.post(
            f"/v4/spreadsheets/{spreadsheet_id}/values/{range}:clear",
            json={},
        ).json()

    # MARK: - Spreadsheet-level mutations

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def batch_update(
        self,
        spreadsheet_id: Any,
        requests: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Apply spreadsheet-level update requests (add sheets, format, etc.).

        Accepts a raw spreadsheet ID or a sheet dict. ``requests`` follows
        the Sheets API ``batchUpdate`` schema — prefer ``add_sheet`` /
        ``delete_sheet`` for the common cases.
        """
        spreadsheet_id = _extract_sheet_id(spreadsheet_id)
        if not requests:
            raise ValueError("requests must be non-empty")
        return self._client.post(
            f"/v4/spreadsheets/{spreadsheet_id}:batchUpdate",
            json={"requests": requests},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def add_sheet(
        self,
        spreadsheet_id: Any,
        *,
        title: str,
        row_count: int = 1000,
        column_count: int = 26,
    ) -> dict[str, Any]:
        """Add a new sheet (tab) to a spreadsheet.

        Accepts a raw spreadsheet ID or a sheet dict.
        """
        if not title:
            raise ValueError("title must be a non-empty string")
        return self.batch_update(
            spreadsheet_id,
            [
                {
                    "addSheet": {
                        "properties": {
                            "title": title,
                            "gridProperties": {
                                "rowCount": row_count,
                                "columnCount": column_count,
                            },
                        }
                    }
                }
            ],
        )

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_sheet(self, spreadsheet_id: Any, *, sheet_id: int) -> dict[str, Any]:
        """Delete a sheet (tab) by numeric ``sheet_id``. Destructive — confirm with user.

        Accepts a raw spreadsheet ID or a sheet dict for ``spreadsheet_id``.
        """
        return self.batch_update(
            spreadsheet_id,
            [{"deleteSheet": {"sheetId": sheet_id}}],
        )
