"""AWS CloudWatch Logs API connector (JSON-RPC over HTTP, SigV4)."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .._aws.sigv4 import SigV4Auth

_SUMMARY_MAX = 25


def _coerce_log_group_name(candidate: Any) -> str:
    """Accept a log group name string or a log-group dict."""
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError("log_group_name is required")
        return candidate
    if isinstance(candidate, dict):
        candidate_dict = cast("dict[str, Any]", candidate)
        for key in ("logGroupName", "log_group_name", "name", "arn"):
            value: Any = candidate_dict.get(key)
            if isinstance(value, str) and value:
                return value
    if isinstance(candidate, list) and candidate:
        return _coerce_log_group_name(candidate[0])
    raise ValueError("log_group_name must be a non-empty string (or a log-group dict)")


@toolset(prefix="aws_cloudwatch_logs")
class AmazonCloudWatchLogsToolSet:
    """A connector for Amazon CloudWatch Logs.

    Args:
        access_key: AWS access key ID.
        secret_key: AWS secret access key.
        region: AWS region.
        session_token: Optional STS session token.
    """

    metadata = ProviderMetadata(
        name="aws_cloudwatch_logs",
        display_name="Amazon CloudWatch Logs",
        version="0.1.0",
        description="Log groups, streams, events, queries, and subscriptions.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url=(
            "https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/Welcome.html"
        ),
        homepage_url="https://aws.amazon.com/cloudwatch/",
        tags=("cloud", "observability", "aws"),
    )

    def __init__(
        self,
        *,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        session_token: str | None = None,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_key or not secret_key:
            raise ValueError("access_key and secret_key are required")
        self.connection = connection
        self._client = HttpClient(
            base_url=f"https://logs.{region}.amazonaws.com",
            auth=SigV4Auth(
                access_key=access_key,
                secret_key=secret_key,
                region=region,
                service="logs",
                session_token=session_token,
            ),
            transport=transport,
            default_headers={
                "Accept": "application/x-amz-json-1.1",
                "Content-Type": "application/x-amz-json-1.1",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _call(self, target: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._client.post(
            "/",
            json=body,
            headers={"X-Amz-Target": f"Logs_20140328.{target}"},
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def describe_log_groups(
        self,
        *,
        log_group_name_prefix: str | None = None,
        limit: int = 25,
        next_token: str | None = None,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """List log groups.

        Best first tool for log-group discovery. Returns compact
        summaries: ``log_group_ref``, ``name`` (log group name —
        user-facing), ``retention_in_days``, ``stored_bytes``,
        ``creation_time``, ``metric_filter_count``. Log group names are
        the primary identifier; ARNs are included only when
        ``include_metadata=False`` returns the raw response.
        """
        if limit < 1 or limit > 50:
            raise ValueError("limit must be between 1 and 50")
        body: dict[str, Any] = {"limit": limit}
        if log_group_name_prefix is not None:
            body["logGroupNamePrefix"] = log_group_name_prefix
        if next_token is not None:
            body["nextToken"] = next_token
        payload = self._call("DescribeLogGroups", body)
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("logGroups") or []
        summaries: list[dict[str, Any]] = []
        for index, group in enumerate(items[:_SUMMARY_MAX], start=1):
            if not isinstance(group, dict):
                continue
            group_dict = cast("dict[str, Any]", group)
            summaries.append(
                {
                    "log_group_ref": f"log_group_{index}",
                    "name": group_dict.get("logGroupName", ""),
                    "retention_in_days": group_dict.get("retentionInDays", 0),
                    "stored_bytes": group_dict.get("storedBytes", 0),
                    "creation_time": group_dict.get("creationTime", 0),
                    "metric_filter_count": group_dict.get("metricFilterCount", 0),
                }
            )
        return {"log_groups": summaries, "next_token": payload.get("nextToken", "")}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_log_group(
        self,
        *,
        log_group_name: str,
        tags: dict[str, str] | None = None,
        kms_key_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a log group.

        Returns the provider acknowledgement. Use ``put_retention_policy``
        after creation to set retention (default is "never expire").
        """
        if not log_group_name:
            raise ValueError("log_group_name is required")
        body: dict[str, Any] = {"logGroupName": log_group_name}
        if tags is not None:
            body["tags"] = tags
        if kms_key_id is not None:
            body["kmsKeyId"] = kms_key_id
        return self._call("CreateLogGroup", body)

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_log_group(
        self,
        *,
        log_group_name: Any,
    ) -> dict[str, Any]:
        """Delete a log group (and all its streams).

        Destructive and not reversible. Confirm with the user before
        calling. ``log_group_name`` accepts a name string or a log-group
        dict from ``describe_log_groups``.
        """
        name = _coerce_log_group_name(log_group_name)
        return self._call("DeleteLogGroup", {"logGroupName": name})

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def put_retention_policy(
        self,
        *,
        log_group_name: Any,
        retention_in_days: int,
    ) -> dict[str, Any]:
        """Set a log group's retention.

        ``retention_in_days`` must be one of the AWS-allowed values
        (1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731,
        1827, 3653).
        """
        name = _coerce_log_group_name(log_group_name)
        if not retention_in_days:
            raise ValueError("retention_in_days is required")
        return self._call(
            "PutRetentionPolicy",
            {
                "logGroupName": name,
                "retentionInDays": retention_in_days,
            },
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def describe_log_streams(
        self,
        *,
        log_group_name: Any,
        log_stream_name_prefix: str | None = None,
        order_by: str = "LogStreamName",
        descending: bool = True,
        limit: int = 25,
        next_token: str | None = None,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """List streams in a log group.

        Returns compact summaries: ``log_stream_ref``, ``name`` (stream
        name — user-facing), ``first_event_timestamp``,
        ``last_event_timestamp``, ``stored_bytes``. ``order_by`` must be
        ``LogStreamName`` or ``LastEventTime``.
        """
        name = _coerce_log_group_name(log_group_name)
        if order_by not in {"LogStreamName", "LastEventTime"}:
            raise ValueError("order_by must be LogStreamName or LastEventTime")
        if limit < 1 or limit > 50:
            raise ValueError("limit must be between 1 and 50")
        body: dict[str, Any] = {
            "logGroupName": name,
            "orderBy": order_by,
            "descending": descending,
            "limit": limit,
        }
        if log_stream_name_prefix is not None:
            body["logStreamNamePrefix"] = log_stream_name_prefix
        if next_token is not None:
            body["nextToken"] = next_token
        payload = self._call("DescribeLogStreams", body)
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("logStreams") or []
        summaries: list[dict[str, Any]] = []
        for index, stream in enumerate(items[:_SUMMARY_MAX], start=1):
            if not isinstance(stream, dict):
                continue
            stream_dict = cast("dict[str, Any]", stream)
            summaries.append(
                {
                    "log_stream_ref": f"log_stream_{index}",
                    "name": stream_dict.get("logStreamName", ""),
                    "first_event_timestamp": stream_dict.get("firstEventTimestamp", 0),
                    "last_event_timestamp": stream_dict.get("lastEventTimestamp", 0),
                    "stored_bytes": stream_dict.get("storedBytes", 0),
                }
            )
        return {"log_streams": summaries, "next_token": payload.get("nextToken", "")}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_log_events(
        self,
        *,
        log_group_name: Any,
        log_stream_name: str,
        start_time: int | None = None,
        end_time: int | None = None,
        next_token: str | None = None,
        limit: int = 100,
        start_from_head: bool = True,
    ) -> dict[str, Any]:
        """Read events from a log stream.

        Returns ``{"events": [...], "nextForwardToken": ...,
        "nextBackwardToken": ...}``. Each event has ``timestamp``,
        ``message``, ``ingestionTime``.
        """
        name = _coerce_log_group_name(log_group_name)
        if not log_stream_name:
            raise ValueError("log_stream_name is required")
        body: dict[str, Any] = {
            "logGroupName": name,
            "logStreamName": log_stream_name,
            "limit": limit,
            "startFromHead": start_from_head,
        }
        if start_time is not None:
            body["startTime"] = start_time
        if end_time is not None:
            body["endTime"] = end_time
        if next_token is not None:
            body["nextToken"] = next_token
        return self._call("GetLogEvents", body)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def filter_log_events(
        self,
        *,
        log_group_name: Any,
        filter_pattern: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        next_token: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Search log events across streams.

        Returns ``{"events": [{"logStreamName": ..., "timestamp": ...,
        "message": ..., "ingestionTime": ...}], "nextToken": ...}``.
        ``filter_pattern`` follows the CloudWatch Logs filter syntax
        (e.g. ``"ERROR"``, ``"[error]"``, JSON patterns).
        """
        name = _coerce_log_group_name(log_group_name)
        body: dict[str, Any] = {
            "logGroupName": name,
            "limit": limit,
        }
        if filter_pattern is not None:
            body["filterPattern"] = filter_pattern
        if start_time is not None:
            body["startTime"] = start_time
        if end_time is not None:
            body["endTime"] = end_time
        if next_token is not None:
            body["nextToken"] = next_token
        return self._call("FilterLogEvents", body)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def put_log_events(
        self,
        *,
        log_group_name: Any,
        log_stream_name: str,
        log_events: list[dict[str, Any]],
        sequence_token: str | None = None,
    ) -> dict[str, Any]:
        """Append log events to a stream.

        Each entry must have ``timestamp`` (Unix epoch ms) and
        ``message``. The sequence token, if any, comes from the previous
        PutLogEvents response.
        """
        name = _coerce_log_group_name(log_group_name)
        if not log_stream_name or not log_events:
            raise ValueError("log_stream_name and log_events are required")
        body: dict[str, Any] = {
            "logGroupName": name,
            "logStreamName": log_stream_name,
            "logEvents": log_events,
        }
        if sequence_token is not None:
            body["sequenceToken"] = sequence_token
        return self._call("PutLogEvents", body)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def start_query(
        self,
        *,
        query_string: str,
        start_time: int,
        end_time: int,
        log_group_names: list[str] | None = None,
        log_group_name: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Start a CloudWatch Logs Insights query.

        Returns ``{"queryId": ...}``. Pass the ``queryId`` to
        ``get_query_results`` to fetch the rows. Queries are asynchronous.
        """
        if not query_string or not start_time or not end_time:
            raise ValueError("query_string, start_time, and end_time are required")
        if not log_group_names and not log_group_name:
            raise ValueError("log_group_names or log_group_name is required")
        body: dict[str, Any] = {
            "queryString": query_string,
            "startTime": start_time,
            "endTime": end_time,
        }
        if log_group_names is not None:
            body["logGroupNames"] = log_group_names
        if log_group_name is not None:
            body["logGroupName"] = log_group_name
        if limit is not None:
            body["limit"] = limit
        return self._call("StartQuery", body)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_query_results(self, *, query_id: str) -> dict[str, Any]:
        """Fetch results of a Logs Insights query.

        Returns ``{"results": [...], "statistics": ..., "status":
        "Running"|"Complete"|"Failed"|"Cancelled"|"Timeout"}``. Poll
        until ``status == "Complete"``.
        """
        if not query_id:
            raise ValueError("query_id is required")
        return self._call("GetQueryResults", {"queryId": query_id})
