# pyright: strict
"""AWS Lambda REST API connector."""

from __future__ import annotations

import base64
import json as _json
from typing import Any, cast

from maivn import toolify, toolset

from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .._aws.sigv4 import SigV4Auth

# MARK: Constants

_SUMMARY_MAX = 25


# MARK: Helpers


def _coerce_function_name(candidate: Any) -> str:
    """Accept a function name string, a function dict, or a list of such."""
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError("function_name is required")
        return candidate
    if isinstance(candidate, dict):
        candidate_dict = cast(dict[str, Any], candidate)
        for key in ("FunctionName", "function_name", "name", "FunctionArn"):
            value = candidate_dict.get(key)
            if isinstance(value, str) and value:
                return value
    if isinstance(candidate, list) and candidate:
        return _coerce_function_name(candidate[0])
    raise ValueError("function_name must be a non-empty string (or a function dict)")


# MARK: Tool set


@toolset(prefix="aws_lambda")
class AmazonLambdaToolSet:
    """A connector for AWS Lambda.

    Args:
        access_key: AWS access key ID.
        secret_key: AWS secret access key.
        region: AWS region.
        session_token: Optional STS session token.
    """

    metadata = ProviderMetadata(
        name="aws_lambda",
        display_name="AWS Lambda",
        version="0.1.0",
        description="Functions, invocations, aliases, versions, and concurrency.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://docs.aws.amazon.com/lambda/latest/api/welcome.html",
        homepage_url="https://aws.amazon.com/lambda/",
        tags=("cloud", "compute", "aws"),
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
            base_url=f"https://lambda.{region}.amazonaws.com",
            auth=SigV4Auth(
                access_key=access_key,
                secret_key=secret_key,
                region=region,
                service="lambda",
                session_token=session_token,
            ),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_functions(
        self,
        *,
        max_items: int = 25,
        marker: str | None = None,
        function_version: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Lambda functions.

        Best first tool for function discovery. Returns compact summaries:
        ``function_ref``, ``name`` (function name — the primary
        identifier, user-facing), ``runtime`` (e.g. ``python3.12``),
        ``memory_size``, ``timeout``, ``last_modified``, ``handler``. The
        function ARN is omitted by default; set ``include_ids=True`` if a
        downstream tool needs it (most Lambda tools accept the name
        directly).
        """
        if max_items < 1 or max_items > 10000:
            raise ValueError("max_items must be between 1 and 10000")
        if include_metadata:
            max_items = min(max_items, _SUMMARY_MAX)
        params: dict[str, Any] = {"MaxItems": max_items}
        if marker is not None:
            params["Marker"] = marker
        if function_version is not None:
            params["FunctionVersion"] = function_version
        payload: dict[str, Any] = self._client.get("/2015-03-31/functions/", params=params).json()
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("Functions") or []
        summaries: list[dict[str, Any]] = []
        for index, raw_function in enumerate(items, start=1):
            if not isinstance(raw_function, dict):
                continue
            function = cast(dict[str, Any], raw_function)
            summary: dict[str, Any] = {
                "function_ref": f"function_{index}",
                "name": function.get("FunctionName", ""),
                "runtime": function.get("Runtime", ""),
                "memory_size": function.get("MemorySize", 0),
                "timeout": function.get("Timeout", 0),
                "last_modified": function.get("LastModified", ""),
                "handler": function.get("Handler", ""),
            }
            if include_ids:
                summary["function_arn"] = function.get("FunctionArn", "")
            summaries.append(summary)
        return {"functions": summaries, "next_marker": payload.get("NextMarker", "")}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_function(
        self,
        function_name: Any,
        *,
        qualifier: str | None = None,
    ) -> dict[str, Any]:
        """Return one function's configuration + code location.

        ``function_name`` accepts a name string, an ARN, or a function
        dict from ``list_functions``.
        """
        name = _coerce_function_name(function_name)
        params: dict[str, Any] = {}
        if qualifier is not None:
            params["Qualifier"] = qualifier
        return self._client.get(
            f"/2015-03-31/functions/{name}",
            params=params or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def invoke_function(
        self,
        function_name: Any,
        *,
        payload: dict[str, Any] | None = None,
        invocation_type: str = "RequestResponse",
        log_type: str = "None",
        qualifier: str | None = None,
    ) -> dict[str, Any]:
        """Invoke a function.

        Returns ``{"status": ..., "function_error": ..., "log_result":
        ..., "body": ...}``. ``invocation_type`` must be one of:
        ``Event`` (async), ``RequestResponse`` (sync), ``DryRun``
        (permission/validation check only).
        """
        name = _coerce_function_name(function_name)
        if invocation_type not in {
            "Event",
            "RequestResponse",
            "DryRun",
        }:
            raise ValueError("invocation_type must be Event/RequestResponse/DryRun")
        params: dict[str, Any] = {}
        if qualifier is not None:
            params["Qualifier"] = qualifier
        headers = {
            "X-Amz-Invocation-Type": invocation_type,
            "X-Amz-Log-Type": log_type,
        }
        body = _json.dumps(payload).encode("utf-8") if payload is not None else b""
        response = self._client.post(
            f"/2015-03-31/functions/{name}/invocations",
            params=params or None,
            data=body,
            headers=headers,
        )
        log_header = response.headers.get("X-Amz-Log-Result")
        decoded_log: str | None = None
        if log_header:
            try:
                decoded_log = base64.b64decode(log_header).decode("utf-8", errors="replace")
            except (ValueError, UnicodeDecodeError):
                decoded_log = log_header
        return {
            "status": response.status,
            "function_error": response.headers.get("X-Amz-Function-Error"),
            "log_result": decoded_log,
            "body": response.text(),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_function_configuration(
        self,
        function_name: Any,
        *,
        environment: dict[str, Any] | None = None,
        timeout: int | None = None,
        memory_size: int | None = None,
        handler: str | None = None,
        role: str | None = None,
    ) -> dict[str, Any]:
        """Patch a function's configuration.

        ``function_name`` accepts a name string or a function dict.
        Returns the updated function configuration.
        """
        name = _coerce_function_name(function_name)
        body: dict[str, Any] = {}
        if environment is not None:
            body["Environment"] = environment
        if timeout is not None:
            body["Timeout"] = timeout
        if memory_size is not None:
            body["MemorySize"] = memory_size
        if handler is not None:
            body["Handler"] = handler
        if role is not None:
            body["Role"] = role
        if not body:
            raise ValueError("at least one update field is required")
        return self._client.put(
            f"/2015-03-31/functions/{name}/configuration",
            json=body,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_function_code(
        self,
        function_name: Any,
        *,
        zip_file: bytes | None = None,
        s3_bucket: str | None = None,
        s3_key: str | None = None,
        s3_object_version: str | None = None,
        image_uri: str | None = None,
        publish: bool = False,
    ) -> dict[str, Any]:
        """Update function code (ZIP, S3, or container image).

        Exactly one of ``zip_file``, ``s3_bucket`` (+ ``s3_key``), or
        ``image_uri`` must be supplied. Set ``publish=True`` to also
        publish a new version.
        """
        name = _coerce_function_name(function_name)
        if not zip_file and not s3_bucket and not image_uri:
            raise ValueError("Provide zip_file, s3_bucket/s3_key, or image_uri")
        body: dict[str, Any] = {"Publish": publish}
        if zip_file is not None:
            body["ZipFile"] = base64.b64encode(zip_file).decode("ascii")
        if s3_bucket is not None and s3_key is not None:
            body["S3Bucket"] = s3_bucket
            body["S3Key"] = s3_key
            if s3_object_version is not None:
                body["S3ObjectVersion"] = s3_object_version
        if image_uri is not None:
            body["ImageUri"] = image_uri
        return self._client.put(f"/2015-03-31/functions/{name}/code", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_function(
        self,
        function_name: Any,
        *,
        qualifier: str | None = None,
    ) -> dict[str, Any]:
        """Delete a function (or a specific qualifier).

        Destructive — confirm with the user first. ``function_name``
        accepts a name string or a function dict from ``list_functions``.
        """
        name = _coerce_function_name(function_name)
        params: dict[str, Any] = {}
        if qualifier is not None:
            params["Qualifier"] = qualifier
        response = self._client.delete(
            f"/2015-03-31/functions/{name}",
            params=params or None,
        )
        return {"status": response.status, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_versions(
        self,
        function_name: Any,
        *,
        max_items: int = 25,
        marker: str | None = None,
    ) -> dict[str, Any]:
        """List versions of a function.

        Returns the raw provider response (with ``Versions`` array and
        ``NextMarker``).
        """
        name = _coerce_function_name(function_name)
        if max_items < 1 or max_items > 10000:
            raise ValueError("max_items must be between 1 and 10000")
        params: dict[str, Any] = {"MaxItems": max_items}
        if marker is not None:
            params["Marker"] = marker
        return self._client.get(
            f"/2015-03-31/functions/{name}/versions",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def publish_version(
        self,
        function_name: Any,
        *,
        description: str | None = None,
        code_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Publish a new version of a function.

        Returns the new version's configuration. Use ``code_sha256`` to
        require the published code match a specific SHA.
        """
        name = _coerce_function_name(function_name)
        body: dict[str, Any] = {}
        if description is not None:
            body["Description"] = description
        if code_sha256 is not None:
            body["CodeSha256"] = code_sha256
        return self._client.post(
            f"/2015-03-31/functions/{name}/versions",
            json=body or None,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_aliases(
        self,
        function_name: Any,
        *,
        max_items: int = 25,
        marker: str | None = None,
    ) -> dict[str, Any]:
        """List aliases of a function.

        Returns the raw provider response (``Aliases`` array,
        ``NextMarker``).
        """
        name = _coerce_function_name(function_name)
        if max_items < 1 or max_items > 10000:
            raise ValueError("max_items must be between 1 and 10000")
        params: dict[str, Any] = {"MaxItems": max_items}
        if marker is not None:
            params["Marker"] = marker
        return self._client.get(
            f"/2015-03-31/functions/{name}/aliases",
            params=params,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def put_function_concurrency(
        self,
        function_name: Any,
        *,
        reserved_concurrent_executions: int,
    ) -> dict[str, Any]:
        """Set reserved concurrent executions for a function.

        Setting reserved concurrency too low may cause throttling.
        """
        name = _coerce_function_name(function_name)
        return self._client.put(
            f"/2017-10-31/functions/{name}/concurrency",
            json={"ReservedConcurrentExecutions": reserved_concurrent_executions},
        ).json()
