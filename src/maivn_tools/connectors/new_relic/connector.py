"""New Relic API connector (NerdGraph + REST + Insights)."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Constants

_SUMMARY_MAX = 25


# MARK: Helpers


def _coerce_policy_id(candidate: Any) -> int:
    """Accept an int, a policy dict, or a list of such."""
    if isinstance(candidate, bool):
        raise ValueError("policy_id must be a non-zero int")
    if isinstance(candidate, int):
        if not candidate:
            raise ValueError("policy_id is required")
        return candidate
    if isinstance(candidate, str) and candidate.isdigit():
        value = int(candidate)
        if not value:
            raise ValueError("policy_id is required")
        return value
    if isinstance(candidate, dict):
        candidate_dict = cast(dict[str, Any], candidate)
        for key in ("policy_id", "id"):
            value: Any = candidate_dict.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, int) and value:
                return value
            if isinstance(value, str) and value.isdigit() and int(value):
                return int(value)
    if isinstance(candidate, list) and candidate:
        candidate_list = cast(list[Any], candidate)
        return _coerce_policy_id(candidate_list[0])
    raise ValueError("policy_id must be a non-zero int (or a policy dict)")


# MARK: ToolSet


@toolset(prefix="new_relic")
class NewRelicToolSet:
    """A connector for the New Relic NerdGraph + REST API.

    Args:
        api_key: User API key (used for the NerdGraph + v2 REST APIs).
        account_id: Account ID for NRQL queries via NerdGraph.
        ingest_license_key: Optional License key for log/metric ingest.
        region: ``"US"`` (default) or ``"EU"``.
    """

    metadata = ProviderMetadata(
        name="new_relic",
        display_name="New Relic",
        version="0.1.0",
        description="NRQL queries, alerts, dashboards, log ingest, and event search.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://docs.newrelic.com/docs/apis/",
        homepage_url="https://newrelic.com/",
        tags=("observability", "monitoring"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        account_id: int | None = None,
        ingest_license_key: str | None = None,
        region: str = "US",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        if region not in {"US", "EU"}:
            raise ValueError("region must be US or EU")
        self.connection = connection
        self._account_id = account_id
        nerdgraph_base = (
            "https://api.newrelic.com" if region == "US" else "https://api.eu.newrelic.com"
        )
        log_base = (
            "https://log-api.newrelic.com" if region == "US" else "https://log-api.eu.newrelic.com"
        )
        metric_base = (
            "https://metric-api.newrelic.com"
            if region == "US"
            else "https://metric-api.eu.newrelic.com"
        )
        self._client = HttpClient(
            base_url=nerdgraph_base,
            auth=ApiKeyAuth(api_key, header="API-Key"),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        self._log_client: HttpClient | None = None
        self._metric_client: HttpClient | None = None
        if ingest_license_key:
            ingest_auth = ApiKeyAuth(ingest_license_key, header="Api-Key")
            self._log_client = HttpClient(
                base_url=log_base,
                auth=ingest_auth,
                transport=transport,
                default_headers={"Content-Type": "application/json"},
            )
            self._metric_client = HttpClient(
                base_url=metric_base,
                auth=ingest_auth,
                transport=transport,
                default_headers={"Content-Type": "application/json"},
            )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def nerdgraph_query(
        self,
        query: str,
        *,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a NerdGraph GraphQL operation.

        Returns the raw GraphQL response (``{"data": ..., "errors": ...}``).
        Useful when there is no purpose-built REST endpoint for the
        operation you need.
        """
        if not query:
            raise ValueError("query is required")
        body: dict[str, Any] = {"query": query}
        if variables is not None:
            body["variables"] = variables
        result: dict[str, Any] = self._client.post("/graphql", json=body).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def nrql_query(
        self,
        nrql: str,
        *,
        account_id: int | None = None,
    ) -> dict[str, Any]:
        """Run an NRQL query via NerdGraph.

        Best first tool for ad-hoc telemetry queries (e.g. error rates,
        throughput). Returns the parsed GraphQL response; the actual rows
        are at ``data.actor.account.nrql.results``.
        """
        if not nrql:
            raise ValueError("nrql is required")
        account = account_id or self._account_id
        if not account:
            raise ValueError("account_id is required")
        query = (
            "query($account:Int!,$nrql:Nrql!){actor{account(id:$account)"
            "{nrql(query:$nrql){results metadata}}}}"
        )
        result: dict[str, Any] = self._client.post(
            "/graphql",
            json={
                "query": query,
                "variables": {"account": account, "nrql": nrql},
            },
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def submit_logs(self, logs: list[dict[str, Any]]) -> dict[str, Any]:
        """Submit log records via the Log API.

        Returns the ingest acknowledgement. Requires
        ``ingest_license_key`` on the constructor.
        """
        if self._log_client is None:
            raise ValueError("ingest_license_key must be set in the constructor")
        if not logs:
            raise ValueError("logs must be non-empty")
        response = self._log_client.post("/log/v1", json=logs)
        try:
            result: dict[str, Any] = response.json()
        except ValueError:
            return {"status": response.status}
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def submit_metrics(self, series: list[dict[str, Any]]) -> dict[str, Any]:
        """Submit metric points via the Metric API.

        Returns the ingest acknowledgement. Requires
        ``ingest_license_key`` on the constructor.
        """
        if self._metric_client is None:
            raise ValueError("ingest_license_key must be set in the constructor")
        if not series:
            raise ValueError("series must be non-empty")
        response = self._metric_client.post("/metric/v1", json=[{"metrics": series}])
        try:
            result: dict[str, Any] = response.json()
        except ValueError:
            return {"status": response.status}
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_alert_policies(
        self,
        *,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List alert policies.

        Returns compact summaries: ``alert_ref``, ``name``,
        ``incident_preference``, ``created_at``. Raw numeric policy IDs
        are omitted by default; set ``include_ids=True`` if a follow-up
        call (``delete_alert_policy``) needs them.
        """
        payload: dict[str, Any] = self._client.get("/v2/alerts_policies.json").json()
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("policies") or []
        summaries: list[dict[str, Any]] = []
        for index, raw_policy in enumerate(items[:_SUMMARY_MAX], start=1):
            if not isinstance(raw_policy, dict):
                continue
            policy = cast(dict[str, Any], raw_policy)
            summary: dict[str, Any] = {
                "alert_ref": f"alert_{index}",
                "name": policy.get("name", ""),
                "incident_preference": policy.get("incident_preference", ""),
                "created_at": policy.get("created_at", ""),
            }
            if include_ids:
                summary["policy_id"] = policy.get("id", "")
            summaries.append(summary)
        return {"alerts": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_alert_policy(
        self,
        *,
        name: str,
        incident_preference: str = "PER_POLICY",
    ) -> dict[str, Any]:
        """Create an alert policy.

        Returns the new policy resource. ``incident_preference`` must be
        one of ``PER_POLICY``, ``PER_CONDITION``,
        ``PER_CONDITION_AND_TARGET``.
        """
        if not name:
            raise ValueError("name is required")
        if incident_preference not in {
            "PER_POLICY",
            "PER_CONDITION",
            "PER_CONDITION_AND_TARGET",
        }:
            raise ValueError("invalid incident_preference")
        result: dict[str, Any] = self._client.post(
            "/v2/alerts_policies.json",
            json={
                "policy": {
                    "name": name,
                    "incident_preference": incident_preference,
                }
            },
        ).json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_alert_policy(self, policy_id: Any) -> dict[str, Any]:
        """Delete an alert policy.

        Destructive — confirm with the user first. ``policy_id`` accepts
        an int or a policy dict from ``list_alert_policies(include_ids=True)``.
        """
        pid = _coerce_policy_id(policy_id)
        result: dict[str, Any] = self._client.delete(f"/v2/alerts_policies/{pid}.json").json()
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_applications(
        self,
        *,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List APM applications.

        Returns compact summaries: ``app_ref``, ``name``, ``language``,
        ``health_status``, ``reporting``. Raw application IDs omitted by
        default; set ``include_ids=True`` when needed.
        """
        payload: dict[str, Any] = self._client.get("/v2/applications.json").json()
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("applications") or []
        summaries: list[dict[str, Any]] = []
        for index, raw_app in enumerate(items[:_SUMMARY_MAX], start=1):
            if not isinstance(raw_app, dict):
                continue
            app = cast(dict[str, Any], raw_app)
            summary: dict[str, Any] = {
                "app_ref": f"app_{index}",
                "name": app.get("name", ""),
                "language": app.get("language", ""),
                "health_status": app.get("health_status", ""),
                "reporting": app.get("reporting", False),
            }
            if include_ids:
                summary["application_id"] = app.get("id", "")
            summaries.append(summary)
        return {"applications": summaries}
