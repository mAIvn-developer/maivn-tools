"""Make (formerly Integromat) connector.

Wraps the Make REST API for scenario inspection and the public webhook /
mailhook endpoints for invoking scenarios.
"""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: - Helpers


def _coerce_int_id(candidate: Any, *keys: str) -> int:
    """Coerce a value to an integer ID, accepting raw values, dicts, or lists."""
    if isinstance(candidate, int):
        return candidate
    if isinstance(candidate, str):
        try:
            return int(candidate)
        except ValueError as exc:
            raise ValueError(f"could not coerce {candidate!r} to int") from exc
    if isinstance(candidate, dict):
        candidate_dict = cast("dict[Any, Any]", candidate)
        for key in keys:
            value: Any = candidate_dict.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, str):
                try:
                    return int(value)
                except ValueError:
                    continue
        for nested in candidate_dict.values():
            nested_value: Any = nested
            if isinstance(nested_value, dict | list):
                try:
                    return _coerce_int_id(nested_value, *keys)
                except ValueError:
                    continue
    if isinstance(candidate, list | tuple):
        candidate_seq = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in candidate_seq:
            item_value: Any = item
            try:
                return _coerce_int_id(item_value, *keys)
            except ValueError:
                continue
    candidate_type = type(cast("object", candidate))
    raise ValueError(f"could not extract an int ID from {candidate_type.__name__}")


def _summarize_scenario(
    scenario: dict[str, Any], *, index: int, include_ids: bool
) -> dict[str, Any]:
    scheduling: Any = scenario.get("scheduling")
    scheduling_type: Any = (
        cast("dict[str, Any]", scheduling).get("type", "") if isinstance(scheduling, dict) else ""
    )
    summary: dict[str, Any] = {
        "scenario_ref": f"scenario_{index}",
        "name": scenario.get("name", ""),
        "is_active": scenario.get("isActive"),
        "scheduling": scheduling_type,
        "last_edit": scenario.get("lastEdit", ""),
    }
    if include_ids:
        summary["scenario_id"] = scenario.get("id", "")
        summary["team_id"] = scenario.get("teamId", "")
    return summary


def _summarize_execution(
    execution: dict[str, Any], *, index: int, include_ids: bool
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "execution_ref": f"execution_{index}",
        "status": execution.get("status", ""),
        "started_at": execution.get("timestamp"),
        "operations": execution.get("operations"),
        "data_transfer": execution.get("transfer"),
    }
    if include_ids:
        summary["execution_id"] = execution.get("id", "")
        summary["team_id"] = execution.get("teamId", "")
    return summary


@toolset(prefix="make")
class MakeToolSet:
    """A connector for Make (Integromat).

    Args:
        api_token: Make API token.
        base_url: Region-specific Make REST API base URL, e.g.
            ``https://us1.make.com/api/v2`` or
            ``https://eu1.make.com/api/v2``.
        transport: Optional :class:`HttpTransport` override.
    """

    metadata = ProviderMetadata(
        name="make",
        display_name="Make",
        version="0.1.0",
        description="List Make scenarios, inspect executions, and trigger scenario webhooks.",
        auth_modes=(AuthMode.API_KEY,),
        scopes={"scenarios:read": "Read scenarios and executions."},
        capabilities=frozenset(
            {ProviderCapability.READ, ProviderCapability.WRITE, ProviderCapability.PAGINATION}
        ),
        documentation_url="https://www.make.com/en/api-documentation",
        homepage_url="https://www.make.com",
        tags=("partner", "automation"),
    )

    def __init__(
        self,
        *,
        api_token: str,
        base_url: str,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_token:
            raise ValueError("api_token must be a non-empty string")
        if not base_url:
            raise ValueError("base_url must be a non-empty string")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(api_token, header="Authorization", prefix="Token"),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )
        self._webhook_client = HttpClient(transport=transport)

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_scenarios(
        self,
        *,
        team_id: int | None = None,
        organization_id: int | None = None,
        limit: int = 25,
        offset: int = 0,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List scenarios accessible to the API token.

        Best first tool for scenario discovery. Returns compact summaries
        with a stable ``scenario_ref`` (``scenario_1``, ``scenario_2``,
        ...), name, active flag, scheduling type, and last-edit timestamp.
        Raw scenario IDs are omitted by default — set ``include_ids=True``
        only when a follow-up tool like :meth:`list_executions` needs the
        raw ``scenario_id``. Pass ``raw=True`` for the unfiltered API
        response. Use ``offset`` to page forward.

        The Make API requires exactly one of ``team_id`` or
        ``organization_id`` to scope the request; supplying neither raises
        ``ValueError``.
        """
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if team_id is None and organization_id is None:
            raise ValueError("either team_id or organization_id must be provided")
        params: dict[str, Any] = {"pg[limit]": limit, "pg[offset]": offset}
        if team_id is not None:
            params["teamId"] = int(team_id)
        if organization_id is not None:
            params["organizationId"] = int(organization_id)
        payload: dict[str, Any] = self._client.get("/scenarios", params=params).json()
        if raw:
            return payload
        items: list[Any] = payload.get("scenarios") or payload.get("data") or []
        summaries: list[dict[str, Any]] = []
        for index, scenario in enumerate(items, start=1):
            if isinstance(scenario, dict):
                scenario_dict = cast("dict[str, Any]", scenario)
                summaries.append(
                    _summarize_scenario(scenario_dict, index=index, include_ids=include_ids)
                )
        return {"scenarios": summaries, "pg": payload.get("pg")}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_scenario(self, scenario_id: Any) -> dict[str, Any]:
        """Return one scenario by ID.

        Returns the Make scenario resource. ``GET /scenarios/{id}`` wraps the
        resource under a top-level ``scenario`` key; this method unwraps it so
        callers receive the scenario fields directly, consistent with the
        summaries from :meth:`list_scenarios`. ``scenario_id`` may be a raw
        integer ID or a scenario dict from :meth:`list_scenarios`
        (``include_ids=True``).
        """
        resolved_id = _coerce_int_id(scenario_id, "scenario_id", "id")
        scenario_payload: dict[str, Any] = self._client.get(f"/scenarios/{resolved_id}").json()
        unwrapped: Any = scenario_payload.get("scenario", scenario_payload)
        if isinstance(unwrapped, dict):
            return cast("dict[str, Any]", unwrapped)
        return scenario_payload

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_executions(
        self,
        scenario_id: Any,
        *,
        limit: int = 25,
        offset: int = 0,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List executions for a scenario.

        Reads the scenario's execution history from the Make
        ``GET /scenarios/{id}/logs`` endpoint. Returns compact summaries
        with ``execution_ref``, status, ``started_at``, operations count,
        and data transfer. ``scenario_id`` may be a raw integer ID or a
        scenario dict from :meth:`list_scenarios` (``include_ids=True``).
        Raw execution IDs are omitted by default — set ``include_ids=True``
        when a follow-up tool needs the raw ``execution_id``. Pass
        ``raw=True`` for the unfiltered API response.
        """
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        resolved_id = _coerce_int_id(scenario_id, "scenario_id", "id")
        payload: dict[str, Any] = self._client.get(
            f"/scenarios/{resolved_id}/logs",
            params={"pg[limit]": limit, "pg[offset]": offset},
        ).json()
        if raw:
            return payload
        items: list[Any] = payload.get("scenarioLogs") or []
        summaries: list[dict[str, Any]] = []
        for index, execution in enumerate(items, start=1):
            if isinstance(execution, dict):
                execution_dict = cast("dict[str, Any]", execution)
                summaries.append(
                    _summarize_execution(execution_dict, index=index, include_ids=include_ids)
                )
        return {"executions": summaries, "pg": payload.get("pg")}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def trigger_webhook(
        self,
        webhook_url: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST ``payload`` to a scenario's webhook URL.

        Returns ``{"status": <http_status>, "delivered": True}``.
        ``webhook_url`` is the full webhook URL configured on the scenario
        in Make — it is the entire URL, not a scenario ID.
        """
        if not webhook_url:
            raise ValueError("webhook_url must be a non-empty string")
        response = self._webhook_client.post(webhook_url, json=payload or {})
        return {"status": response.status, "delivered": True}
