"""Kubernetes API server connector.

This toolset talks directly to a Kubernetes API server via REST. It is
intentionally narrow: it covers the resource families an agent needs to
read or change cluster state without trying to reproduce the entire
``kubectl`` surface.
"""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import tool_output, toolify, toolset

from ...auth.base import NoAuth
from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .output_schemas import (
    LIST_DEPLOYMENTS_OUTPUT,
    LIST_NAMESPACES_OUTPUT,
    LIST_PODS_OUTPUT,
    LIST_SERVICES_OUTPUT,
)

# MARK: Constants

_SUMMARY_MAX = 25


# MARK: Summary helpers


def _pod_summary(pod: dict[str, Any], *, index: int, include_ids: bool) -> dict[str, Any]:
    metadata: dict[str, Any] = pod.get("metadata") or {}
    status: dict[str, Any] = pod.get("status") or {}
    container_statuses: list[Any] = status.get("containerStatuses") or []
    ready = sum(1 for cs in container_statuses if cs.get("ready"))
    spec: dict[str, Any] = pod.get("spec") or {}
    summary: dict[str, Any] = {
        "pod_ref": f"pod_{index}",
        "name": metadata.get("name", ""),
        "namespace": metadata.get("namespace", ""),
        "phase": status.get("phase", ""),
        "ready": f"{ready}/{len(container_statuses)}" if container_statuses else "",
        "node": spec.get("nodeName", ""),
        "start_time": status.get("startTime", ""),
    }
    if include_ids:
        summary["uid"] = metadata.get("uid", "")
        summary["resource_version"] = metadata.get("resourceVersion", "")
    return summary


def _deployment_summary(
    deployment: dict[str, Any], *, index: int, include_ids: bool
) -> dict[str, Any]:
    metadata: dict[str, Any] = deployment.get("metadata") or {}
    spec: dict[str, Any] = deployment.get("spec") or {}
    status: dict[str, Any] = deployment.get("status") or {}
    summary: dict[str, Any] = {
        "deployment_ref": f"deployment_{index}",
        "name": metadata.get("name", ""),
        "namespace": metadata.get("namespace", ""),
        "replicas": spec.get("replicas", 0),
        "ready_replicas": status.get("readyReplicas", 0),
        "available_replicas": status.get("availableReplicas", 0),
    }
    if include_ids:
        summary["uid"] = metadata.get("uid", "")
        summary["resource_version"] = metadata.get("resourceVersion", "")
    return summary


def _service_summary(service: dict[str, Any], *, index: int, include_ids: bool) -> dict[str, Any]:
    metadata: dict[str, Any] = service.get("metadata") or {}
    spec: dict[str, Any] = service.get("spec") or {}
    ports: list[Any] = spec.get("ports") or []
    summary: dict[str, Any] = {
        "service_ref": f"service_{index}",
        "name": metadata.get("name", ""),
        "namespace": metadata.get("namespace", ""),
        "type": spec.get("type", ""),
        "cluster_ip": spec.get("clusterIP", ""),
        "ports": [
            {
                "name": port.get("name", ""),
                "port": port.get("port", 0),
                "target_port": port.get("targetPort", 0),
                "protocol": port.get("protocol", ""),
            }
            for port in (cast(dict[str, Any], p) for p in ports if isinstance(p, dict))
        ],
    }
    if include_ids:
        summary["uid"] = metadata.get("uid", "")
    return summary


def _namespace_summary(
    namespace: dict[str, Any], *, index: int, include_ids: bool
) -> dict[str, Any]:
    metadata: dict[str, Any] = namespace.get("metadata") or {}
    status: dict[str, Any] = namespace.get("status") or {}
    summary: dict[str, Any] = {
        "namespace_ref": f"namespace_{index}",
        "name": metadata.get("name", ""),
        "phase": status.get("phase", ""),
        "created_at": metadata.get("creationTimestamp", ""),
    }
    if include_ids:
        summary["uid"] = metadata.get("uid", "")
    return summary


# MARK: Tool set


@toolset(prefix="k8s")
class KubernetesToolSet:
    """A connector for a Kubernetes API server.

    Args:
        api_server: Cluster API server URL, e.g.
            ``https://my-cluster.example.com``.
        token: Bearer token (typically a ServiceAccount token).
    """

    metadata = ProviderMetadata(
        name="kubernetes",
        display_name="Kubernetes",
        version="0.1.0",
        description="Namespaces, pods, deployments, services, jobs, and events.",
        auth_modes=(AuthMode.BEARER, AuthMode.NONE),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://kubernetes.io/docs/reference/generated/kubernetes-api/",
        homepage_url="https://kubernetes.io/",
        tags=("cloud", "orchestration"),
    )

    def __init__(
        self,
        *,
        api_server: str,
        token: str | None = None,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_server:
            raise ValueError("api_server is required")
        self.connection = connection
        auth = BearerTokenAuth(token) if token else NoAuth()
        self._client = HttpClient(
            base_url=api_server.rstrip("/"),
            auth=auth,
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
    def get_version(self) -> dict[str, Any]:
        """Return the API server's version info.

        Returns ``{"major": ..., "minor": ..., "gitVersion": ..., ...}``.
        Quick sanity check that the client can reach the cluster.
        """
        version_info: dict[str, Any] = self._client.get("/version").json()
        return version_info

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_NAMESPACES_OUTPUT)
    def list_namespaces(
        self,
        *,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List namespaces.

        Returns compact summaries: ``namespace_ref``, ``name`` (the
        namespace — user-facing identifier), ``phase`` (``Active``,
        ``Terminating``), ``created_at``. Namespace names are the primary
        identifier in Kubernetes; the internal UID is opt-in via
        ``include_ids=True``.
        """
        payload: dict[str, Any] = self._client.get("/api/v1/namespaces").json()
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("items") or []
        summaries: list[dict[str, Any]] = []
        for index, ns in enumerate(items[:_SUMMARY_MAX], start=1):
            if not isinstance(ns, dict):
                continue
            summaries.append(
                _namespace_summary(cast(dict[str, Any], ns), index=index, include_ids=include_ids)
            )
        return {"namespaces": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_PODS_OUTPUT)
    def list_pods(
        self,
        *,
        namespace: str | None = None,
        label_selector: str | None = None,
        field_selector: str | None = None,
        limit: int = 25,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List pods (all namespaces if not provided).

        Best first tool for pod triage. Returns compact summaries:
        ``pod_ref``, ``name`` (user-facing), ``namespace``, ``phase``
        (``Running``/``Pending``/``Failed``), ``ready`` (e.g. ``2/3``),
        ``node``, ``start_time``. Pod names plus namespace are the
        primary identifier; UIDs are opt-in via ``include_ids=True``.
        """
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if include_metadata:
            limit = min(limit, _SUMMARY_MAX)
        path = f"/api/v1/namespaces/{namespace}/pods" if namespace else "/api/v1/pods"
        params: dict[str, Any] = {"limit": limit}
        if label_selector is not None:
            params["labelSelector"] = label_selector
        if field_selector is not None:
            params["fieldSelector"] = field_selector
        payload: dict[str, Any] = self._client.get(path, params=params).json()
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("items") or []
        summaries: list[dict[str, Any]] = [
            _pod_summary(cast(dict[str, Any], pod), index=index, include_ids=include_ids)
            for index, pod in enumerate(items, start=1)
            if isinstance(pod, dict)
        ]
        metadata: dict[str, Any] = payload.get("metadata") or {}
        return {
            "pods": summaries,
            "continue": metadata.get("continue", ""),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_pod(self, *, namespace: str, name: str) -> dict[str, Any]:
        """Return a single pod's full spec and status.

        ``namespace`` and ``name`` are the user-facing pod identifiers
        (e.g. from ``list_pods``).
        """
        if not namespace or not name:
            raise ValueError("namespace and name are required")
        pod: dict[str, Any] = self._client.get(f"/api/v1/namespaces/{namespace}/pods/{name}").json()
        return pod

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_pod_logs(
        self,
        *,
        namespace: str,
        name: str,
        container: str | None = None,
        tail_lines: int | None = None,
        since_seconds: int | None = None,
        previous: bool = False,
    ) -> dict[str, Any]:
        """Return pod logs as text.

        Returns ``{"status": ..., "logs": "..."}``. Pass ``container`` for
        a specific container in a multi-container pod, ``previous=True``
        to read the previous instance's logs (useful after a crash).
        """
        if not namespace or not name:
            raise ValueError("namespace and name are required")
        params: dict[str, Any] = {}
        if container is not None:
            params["container"] = container
        if tail_lines is not None:
            params["tailLines"] = tail_lines
        if since_seconds is not None:
            params["sinceSeconds"] = since_seconds
        if previous:
            params["previous"] = "true"
        response = self._client.get(
            f"/api/v1/namespaces/{namespace}/pods/{name}/log",
            params=params or None,
        )
        return {"status": response.status, "logs": response.text()}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_DEPLOYMENTS_OUTPUT)
    def list_deployments(
        self,
        *,
        namespace: str | None = None,
        label_selector: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List deployments.

        Returns compact summaries: ``deployment_ref``, ``name``,
        ``namespace``, ``replicas`` (desired), ``ready_replicas``,
        ``available_replicas``. Deployment names plus namespace are the
        primary identifier; UIDs are opt-in via ``include_ids=True``.
        """
        path = (
            f"/apis/apps/v1/namespaces/{namespace}/deployments"
            if namespace
            else "/apis/apps/v1/deployments"
        )
        params: dict[str, Any] = {}
        if label_selector is not None:
            params["labelSelector"] = label_selector
        payload: dict[str, Any] = self._client.get(path, params=params or None).json()
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("items") or []
        summaries: list[dict[str, Any]] = [
            _deployment_summary(cast(dict[str, Any], dep), index=index, include_ids=include_ids)
            for index, dep in enumerate(items[:_SUMMARY_MAX], start=1)
            if isinstance(dep, dict)
        ]
        return {"deployments": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def scale_deployment(
        self,
        *,
        namespace: str,
        name: str,
        replicas: int,
    ) -> dict[str, Any]:
        """Set a deployment's replica count.

        Returns the updated scale subresource. ``replicas=0`` is allowed
        and effectively pauses the deployment.
        """
        if not namespace or not name:
            raise ValueError("namespace and name are required")
        if replicas < 0:
            raise ValueError("replicas must be non-negative")
        scaled: dict[str, Any] = self._client.patch(
            f"/apis/apps/v1/namespaces/{namespace}/deployments/{name}/scale",
            json={"spec": {"replicas": replicas}},
            headers={"Content-Type": "application/strategic-merge-patch+json"},
        ).json()
        return scaled

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_pod(
        self,
        *,
        namespace: str,
        name: str,
        grace_period_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Delete a pod.

        Destructive — confirm with the user first. With a Deployment, the
        ReplicaSet will respawn the pod; for one-off pods, deletion is
        permanent.
        """
        if not namespace or not name:
            raise ValueError("namespace and name are required")
        params: dict[str, Any] = {}
        if grace_period_seconds is not None:
            params["gracePeriodSeconds"] = grace_period_seconds
        deleted: dict[str, Any] = self._client.delete(
            f"/api/v1/namespaces/{namespace}/pods/{name}",
            params=params or None,
        ).json()
        return deleted

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    @tool_output(LIST_SERVICES_OUTPUT)
    def list_services(
        self,
        namespace: str | None = None,
        *,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List services.

        Returns compact summaries: ``service_ref``, ``name``,
        ``namespace``, ``type`` (``ClusterIP``/``LoadBalancer``/etc.),
        ``cluster_ip``, ``ports`` (each with port/target_port/protocol).
        """
        path = f"/api/v1/namespaces/{namespace}/services" if namespace else "/api/v1/services"
        payload: dict[str, Any] = self._client.get(path).json()
        if not include_metadata:
            return payload
        items: list[Any] = payload.get("items") or []
        summaries: list[dict[str, Any]] = [
            _service_summary(cast(dict[str, Any], svc), index=index, include_ids=include_ids)
            for index, svc in enumerate(items[:_SUMMARY_MAX], start=1)
            if isinstance(svc, dict)
        ]
        return {"services": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_events(
        self,
        *,
        namespace: str | None = None,
        field_selector: str | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        """List events (recent cluster activity).

        Returns the raw event list. Useful for diagnosing why pods are
        Pending/Failed. ``field_selector="type=Warning"`` filters to
        warnings only.
        """
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        path = f"/api/v1/namespaces/{namespace}/events" if namespace else "/api/v1/events"
        params: dict[str, Any] = {"limit": limit}
        if field_selector is not None:
            params["fieldSelector"] = field_selector
        events: dict[str, Any] = self._client.get(path, params=params).json()
        return events

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_nodes(self) -> dict[str, Any]:
        """List cluster nodes.

        Returns the raw node list. Each node has ``metadata.name``,
        ``status.conditions``, ``status.allocatable`` (CPU/memory).
        """
        nodes: dict[str, Any] = self._client.get("/api/v1/nodes").json()
        return nodes

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def apply_manifest(
        self,
        manifest: dict[str, Any],
        *,
        namespace: str | None = None,
        field_manager: str = "maivn-tools",
    ) -> dict[str, Any]:
        """Server-side apply (``PATCH`` with ``apply``) for any resource.

        Returns the applied resource. ``manifest`` must include
        ``apiVersion``, ``kind``, and ``metadata.name``. ``namespace`` is
        taken from ``manifest.metadata.namespace`` if not provided.
        """
        if not manifest:
            raise ValueError("manifest is required")
        api_version: Any = manifest.get("apiVersion")
        kind: Any = manifest.get("kind")
        metadata: dict[str, Any] = manifest.get("metadata") or {}
        name: Any = metadata.get("name")
        ns: Any = namespace or metadata.get("namespace")
        if not api_version or not kind or not name:
            raise ValueError("manifest must include apiVersion, kind, and metadata.name")
        plural: str = (kind + "s").lower()
        prefix: str = "/api/v1" if api_version == "v1" else f"/apis/{api_version}"
        path = f"{prefix}/namespaces/{ns}/{plural}/{name}" if ns else f"{prefix}/{plural}/{name}"
        applied: dict[str, Any] = self._client.patch(
            path,
            json=manifest,
            params={"fieldManager": field_manager, "force": "true"},
            headers={"Content-Type": "application/apply-patch+yaml"},
        ).json()
        return applied
