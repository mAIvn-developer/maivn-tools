"""Workato connector.

Exposes the most useful Workato REST endpoints: list recipes, list jobs
(per recipe), and run an on-demand recipe via its callable trigger URL.
"""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

WORKATO_API_URL = "https://www.workato.com/api"

_JOB_STATUSES = ("succeeded", "failed", "pending")


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
        mapping = cast(dict[Any, Any], candidate)
        for key in keys:
            value: Any = mapping.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, str):
                try:
                    return int(value)
                except ValueError:
                    continue
        for nested_value in mapping.values():
            if isinstance(nested_value, dict | list):
                try:
                    return _coerce_int_id(nested_value, *keys)
                except ValueError:
                    continue
    if isinstance(candidate, list | tuple):
        sequence = cast("list[Any] | tuple[Any, ...]", candidate)
        for item_value in sequence:
            try:
                return _coerce_int_id(item_value, *keys)
            except ValueError:
                continue
    type_name: str = type(cast(object, candidate)).__name__
    raise ValueError(f"could not extract an int ID from {type_name}")


def _summarize_recipe(recipe: dict[str, Any], *, index: int, include_ids: bool) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "recipe_ref": f"recipe_{index}",
        "name": recipe.get("name", ""),
        "running": recipe.get("running"),
        "stopped_cause": recipe.get("stopped_cause"),
        "last_run_at": recipe.get("last_run_at", ""),
        "created_at": recipe.get("created_at", ""),
    }
    if include_ids:
        summary["recipe_id"] = recipe.get("id", "")
    return summary


def _summarize_job(job: dict[str, Any], *, index: int, include_ids: bool) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "job_ref": f"job_{index}",
        "status": job.get("status", ""),
        "started_at": job.get("created_at") or job.get("started_at", ""),
        "completed_at": job.get("completed_at", ""),
        "error": job.get("error", ""),
    }
    if include_ids:
        summary["job_id"] = job.get("id", "")
        summary["job_handle"] = job.get("job_handle", "")
    return summary


@toolset(prefix="workato")
class WorkatoToolSet:
    """A connector for Workato's REST API."""

    metadata = ProviderMetadata(
        name="workato",
        display_name="Workato",
        version="0.1.0",
        description="List recipes, inspect job runs, and trigger on-demand recipes.",
        auth_modes=(AuthMode.BEARER,),
        scopes={"recipes": "Read recipe definitions and runs."},
        capabilities=frozenset(
            {ProviderCapability.READ, ProviderCapability.WRITE, ProviderCapability.PAGINATION}
        ),
        documentation_url="https://docs.workato.com/workato-api.html",
        homepage_url="https://workato.com",
        tags=("partner", "automation"),
    )

    def __init__(
        self,
        *,
        api_token: str,
        transport: HttpTransport | None = None,
        base_url: str = WORKATO_API_URL,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_token:
            raise ValueError("api_token must be a non-empty string")
        self.connection = connection
        self._transport = transport
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(api_token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    # MARK: - Tools

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_recipes(
        self,
        *,
        page: int = 1,
        per_page: int = 25,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List recipes accessible to the API token.

        Best first tool for recipe discovery. Returns compact summaries
        with a stable ``recipe_ref`` (``recipe_1``, ``recipe_2``, ...),
        name, running flag, stopped cause, and last-run timestamp. Raw
        recipe IDs are omitted by default because they are internal
        handles. Set ``include_ids=True`` only when a follow-up tool like
        :meth:`list_jobs` needs the raw ``recipe_id``. Pass ``raw=True`` to
        bypass the summary view and receive the unfiltered API response.
        Use ``page`` to paginate.
        """
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        payload: Any = self._client.get(
            "/recipes",
            params={"page": page, "per_page": per_page},
        ).json()
        if raw:
            return payload
        items: list[Any] = cast(
            "list[Any]",
            payload
            if isinstance(payload, list)
            else (payload.get("items") or payload.get("data") or []),
        )
        summaries: list[dict[str, Any]] = []
        for index, recipe_value in enumerate(items, start=1):
            if isinstance(recipe_value, dict):
                recipe_dict = cast(dict[str, Any], recipe_value)
                summaries.append(
                    _summarize_recipe(recipe_dict, index=index, include_ids=include_ids)
                )
        return {"recipes": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_jobs(
        self,
        recipe_id: Any,
        *,
        offset_job_id: str | None = None,
        prev: bool = False,
        status: str | None = None,
        include_ids: bool = False,
        raw: bool = False,
    ) -> dict[str, Any]:
        """List jobs for a recipe.

        Returns compact summaries with ``job_ref``, status, start/end
        timestamps, and error message. ``recipe_id`` may be a raw integer
        ID or a recipe dict from :meth:`list_recipes`
        (``include_ids=True``). Raw job IDs are omitted by default — set
        ``include_ids=True`` if a follow-up tool needs the raw ``job_id``.
        Pass ``raw=True`` for the unfiltered API response.

        The jobs endpoint uses cursor pagination: pass the ``job_id`` of an
        edge job as ``offset_job_id`` to page from that cursor, and set
        ``prev=True`` to page backwards. ``status`` filters by job state and
        must be one of ``succeeded``, ``failed``, or ``pending``.
        """
        if status is not None and status not in _JOB_STATUSES:
            raise ValueError(f"status must be one of {', '.join(_JOB_STATUSES)}")
        resolved_id = _coerce_int_id(recipe_id, "recipe_id", "id")
        params: dict[str, Any] = {}
        if offset_job_id is not None:
            params["offset_job_id"] = offset_job_id
        if prev:
            params["prev"] = prev
        if status is not None:
            params["status"] = status
        payload: Any = self._client.get(f"/recipes/{resolved_id}/jobs", params=params).json()
        if raw:
            return payload
        items: list[Any] = cast(
            "list[Any]",
            payload
            if isinstance(payload, list)
            else (payload.get("items") or payload.get("data") or []),
        )
        summaries: list[dict[str, Any]] = []
        for index, job_value in enumerate(items, start=1):
            if isinstance(job_value, dict):
                job_dict = cast(dict[str, Any], job_value)
                summaries.append(_summarize_job(job_dict, index=index, include_ids=include_ids))
        return {"jobs": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def run_recipe_trigger(
        self,
        trigger_url: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST ``payload`` to a Workato recipe's on-demand trigger URL.

        Returns ``{"status": <http_status>, "delivered": True}``.
        ``trigger_url`` is the callable trigger URL configured on the
        recipe in Workato — it is the entire URL, not a recipe ID.
        """
        if not trigger_url:
            raise ValueError("trigger_url must be a non-empty string")
        response = HttpClient(transport=self._transport).post(trigger_url, json=payload or {})
        return {"status": response.status, "delivered": True}
