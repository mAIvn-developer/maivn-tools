"""Supabase Platform connector (PostgREST + Auth + Storage + Edge Functions + Vector)."""

# pyright: strict

from __future__ import annotations

import re
from typing import Any, cast

from maivn import toolify, toolset

from ...auth.base import AuthStrategy
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

_VALID_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Smaller defaults keep agent context windows tidy. Callers can override.
_DEFAULT_LIST_LIMIT = 25
_DEFAULT_SELECT_LIMIT = 100


def _validate_ident(name: str, kind: str) -> None:
    if not name:
        raise ValueError(f"{kind} must be a non-empty string")
    if not _VALID_IDENT.match(name):
        raise ValueError(f"{kind} must match ^[A-Za-z_][A-Za-z0-9_]*$")


def _user_summary(user: dict[str, Any], *, index: int) -> dict[str, Any]:
    """Build a compact summary of one auth user."""
    return {
        "user_ref": f"user_{index}",
        "user_id": user.get("id", ""),
        "email": user.get("email", ""),
        "phone": user.get("phone", ""),
        "role": user.get("role", ""),
        "created_at": user.get("created_at", ""),
        "last_sign_in_at": user.get("last_sign_in_at", ""),
        "confirmed_at": user.get("email_confirmed_at") or user.get("confirmed_at", ""),
    }


def _bucket_summary(bucket: dict[str, Any], *, index: int) -> dict[str, Any]:
    """Build a compact summary of one storage bucket."""
    return {
        "bucket_ref": f"bucket_{index}",
        "bucket_id": bucket.get("id", ""),
        "name": bucket.get("name", bucket.get("id", "")),
        "public": bucket.get("public", False),
        "file_size_limit": bucket.get("file_size_limit"),
        "allowed_mime_types": bucket.get("allowed_mime_types") or [],
        "created_at": bucket.get("created_at", ""),
    }


def _object_summary(obj: dict[str, Any], *, index: int) -> dict[str, Any]:
    """Build a compact summary of one storage object."""
    metadata_raw: Any = obj.get("metadata")
    metadata: dict[str, Any] = (
        cast("dict[str, Any]", metadata_raw) if isinstance(metadata_raw, dict) else {}
    )
    return {
        "object_ref": f"object_{index}",
        "name": obj.get("name", ""),
        "size": metadata.get("size"),
        "content_type": metadata.get("mimetype", ""),
        "updated_at": obj.get("updated_at", ""),
        "created_at": obj.get("created_at", ""),
    }


def _extract_id(candidate: Any, *, keys: tuple[str, ...]) -> str:
    """Pull an identifier from an arbitrary value.

    Accepts a raw string ID, a dict containing one of ``keys`` (e.g.
    ``user_id``, ``id``), a list with one such item, or a nested dict.
    Returns the first usable ID found. Mirrors the tolerant pattern used
    by Airtable / Fleet Ops so list_* outputs can be piped back into
    follow-up tools without remapping.
    """
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError("identifier must be a non-empty string")
        return candidate
    if isinstance(candidate, dict):
        candidate_dict = cast("dict[str, Any]", candidate)
        for key in keys:
            value = candidate_dict.get(key)
            if isinstance(value, str) and value:
                return value
        for nested in candidate_dict.values():
            if isinstance(nested, dict):
                try:
                    return _extract_id(cast("dict[str, Any]", nested), keys=keys)
                except ValueError:
                    continue
    if isinstance(candidate, list | tuple):
        candidate_seq = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in candidate_seq:
            try:
                return _extract_id(item, keys=keys)
            except ValueError:
                continue
    raise ValueError(f"could not extract identifier from: {candidate!r}")


class _SupabaseAuth(AuthStrategy):
    """Attach Supabase ``apikey`` header plus an Authorization Bearer."""

    mode = AuthMode.API_KEY

    def __init__(self, api_key: str, *, access_token: str | None = None) -> None:
        if not api_key:
            raise ValueError("api_key must be a non-empty string")
        self._api_key = api_key
        self._access_token = access_token or api_key

    def apply(self, request: dict[str, Any]) -> dict[str, Any]:
        headers = dict(request.get("headers") or {})
        headers["apikey"] = self._api_key
        headers["Authorization"] = f"Bearer {self._access_token}"
        request["headers"] = headers
        return request

    def describe(self) -> dict[str, Any]:
        return {"mode": self.mode.value, "headers": ["apikey", "Authorization"]}


@toolset(prefix="supabase")
class SupabaseToolSet:
    """A connector for Supabase Platform APIs.

    Covers PostgREST data access (incl. RPC and pgvector matching),
    GoTrue auth admin, Storage object operations, and Edge Function
    invocation — all under one ``api_key``/``access_token`` pair.

    Args:
        project_url: Supabase project URL, e.g.
            ``https://abcd.supabase.co``.
        api_key: ``anon`` or ``service_role`` key. Both are passed via the
            ``apikey`` header. Service-role keys grant unrestricted access
            and should be treated as destructive credentials.
        access_token: Optional separate JWT for end-user impersonation.
            Defaults to the ``api_key`` value.
        transport: Optional :class:`HttpTransport` override.
    """

    metadata = ProviderMetadata(
        name="supabase",
        display_name="Supabase",
        version="0.1.0",
        description="PostgREST, Auth admin, Storage, Edge Functions, pgvector matching.",
        auth_modes=(AuthMode.API_KEY, AuthMode.OAUTH2_AUTH_CODE),
        scopes={
            "anon": "Run anonymous queries scoped by Row-Level Security.",
            "service_role": "Unrestricted admin access; treat as destructive.",
        },
        capabilities=frozenset(
            {
                ProviderCapability.READ,
                ProviderCapability.WRITE,
                ProviderCapability.SEARCH,
                ProviderCapability.PAGINATION,
            }
        ),
        documentation_url="https://supabase.com/docs/reference",
        homepage_url="https://supabase.com/",
        tags=("database", "auth", "storage", "vector"),
    )

    def __init__(
        self,
        *,
        project_url: str,
        api_key: str,
        access_token: str | None = None,
        schema: str = "public",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not project_url or not api_key:
            raise ValueError("project_url and api_key are required")
        self.connection = connection
        self._schema = schema
        self._client = HttpClient(
            base_url=project_url.rstrip("/"),
            auth=_SupabaseAuth(api_key, access_token=access_token),
            transport=transport,
            default_headers={"Accept": "application/json"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    # MARK: - PostgREST data

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def select(
        self,
        table: str,
        *,
        select: str = "*",
        filter: dict[str, str] | None = None,
        order: str | None = None,
        limit: int | None = _DEFAULT_SELECT_LIMIT,
        offset: int | None = None,
        range_start: int | None = None,
        range_end: int | None = None,
        schema: str | None = None,
        head: bool = False,
        count: str | None = None,
    ) -> dict[str, Any]:
        """Select rows from a PostgREST table.

        Best primary read tool. Returns ``{"status", "headers",
        "body"}``. ``body`` is the raw PostgREST array of column-keyed
        row dicts (or ``None`` when ``head=True``). The user-facing
        ``table`` name is preserved in the path; the chosen ``schema``
        appears as the ``Accept-Profile`` request header.

        Args:
            table: PostgREST table or view name (validated as a SQL
                identifier).
            select: PostgREST ``select`` clause, e.g. ``"id,name"`` or
                ``"id,profile(*)"`` for embedded resources.
            filter: Column -> PostgREST operator expression, e.g.
                ``{"id": "eq.1"}``, ``{"created_at": "gte.2024-01-01"}``.
            order: PostgREST ``order`` clause, e.g. ``"id.desc"``.
            limit: Per-call row cap. Defaults to 100 to keep responses
                tidy; pass ``None`` to defer to PostgREST's own ceiling.
            offset: Numeric offset.
            range_start / range_end: ``Range`` header pair for
                content-range pagination.
            schema: PostgREST schema (defaults to the connector's
                ``schema``).
            head: Issue ``HEAD`` instead of ``GET`` — useful with
                ``count`` to fetch just the row count.
            count: Request a count header (``"exact"``, ``"planned"``,
                ``"estimated"``).
        """
        _validate_ident(table, "table")
        params: dict[str, Any] = {"select": select}
        if filter is not None:
            for col, expr in filter.items():
                _validate_ident(col, "filter column")
                params[col] = expr
        if order is not None:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(limit)
        if offset is not None:
            params["offset"] = str(offset)
        headers: dict[str, str] = {"Accept-Profile": schema or self._schema}
        if range_start is not None and range_end is not None:
            headers["Range"] = f"{range_start}-{range_end}"
            headers["Range-Unit"] = "items"
        if count is not None:
            if count not in {"exact", "planned", "estimated"}:
                raise ValueError("count must be exact/planned/estimated")
            headers["Prefer"] = f"count={count}"
        method = "HEAD" if head else "GET"
        response = self._client.request(
            method,
            f"/rest/v1/{table}",
            params=params,
            headers=headers,
        )
        body: Any
        if not response.body:
            body = None
        else:
            try:
                body = response.json()
            except ValueError:
                body = None
        return {
            "status": response.status,
            "headers": dict(response.headers),
            "body": body,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def insert(
        self,
        table: str,
        rows: list[dict[str, Any]] | dict[str, Any],
        *,
        upsert: bool = False,
        on_conflict: str | None = None,
        return_representation: bool = True,
        schema: str | None = None,
    ) -> dict[str, Any]:
        """Insert (or upsert) one or more rows.

        Returns the inserted rows when ``return_representation=True``
        (the default), or an empty response otherwise. Set ``upsert=True``
        with ``on_conflict=<unique-column>`` to merge duplicates.
        """
        _validate_ident(table, "table")
        if not rows:
            raise ValueError("rows must be non-empty")
        prefer = ["return=representation"] if return_representation else []
        if upsert:
            prefer.append("resolution=merge-duplicates")
        headers: dict[str, str] = {
            "Content-Profile": schema or self._schema,
        }
        if prefer:
            headers["Prefer"] = ",".join(prefer)
        params: dict[str, Any] = {}
        if on_conflict is not None:
            params["on_conflict"] = on_conflict
        return self._client.post(
            f"/rest/v1/{table}",
            params=params or None,
            headers=headers,
            json=rows,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update(
        self,
        table: str,
        *,
        filter: dict[str, str],
        values: dict[str, Any],
        return_representation: bool = True,
        schema: str | None = None,
    ) -> dict[str, Any]:
        """Update rows matching ``filter``.

        ``filter`` is required so an accidental full-table update is
        impossible. Returns the updated rows when
        ``return_representation=True``.
        """
        _validate_ident(table, "table")
        if not filter:
            raise ValueError("filter is required for update; refuse to update all rows")
        if not values:
            raise ValueError("values must be non-empty")
        params: dict[str, Any] = {}
        for col, expr in filter.items():
            _validate_ident(col, "filter column")
            params[col] = expr
        headers: dict[str, str] = {"Content-Profile": schema or self._schema}
        if return_representation:
            headers["Prefer"] = "return=representation"
        return self._client.patch(
            f"/rest/v1/{table}",
            params=params,
            headers=headers,
            json=values,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete(
        self,
        table: str,
        *,
        filter: dict[str, str],
        schema: str | None = None,
    ) -> dict[str, Any]:
        """Delete rows matching ``filter``. Refuses to delete all rows.

        Destructive: deletes the matching rows and cannot be undone.
        ``filter`` is required so an accidental full-table delete is
        impossible. Confirm with the user before calling.
        """
        _validate_ident(table, "table")
        if not filter:
            raise ValueError("filter is required; refuse to delete all rows")
        params: dict[str, Any] = {}
        for col, expr in filter.items():
            _validate_ident(col, "filter column")
            params[col] = expr
        response = self._client.delete(
            f"/rest/v1/{table}",
            params=params,
            headers={"Content-Profile": schema or self._schema},
        )
        return {"table": table, "deleted": True, "status": response.status}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def rpc(
        self,
        function_name: str,
        *,
        args: dict[str, Any] | None = None,
        schema: str | None = None,
    ) -> dict[str, Any]:
        """Call a PostgREST RPC function.

        Returns the JSON body that the function produced. The
        ``Content-Profile`` header carries the schema so RPCs outside
        ``public`` can be routed correctly.
        """
        _validate_ident(function_name, "function_name")
        return self._client.post(
            f"/rest/v1/rpc/{function_name}",
            json=args or {},
            headers={"Content-Profile": schema or self._schema},
        ).json()

    # MARK: - pgvector matching helper

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def match_vectors(
        self,
        *,
        function_name: str,
        embedding: list[float],
        match_count: int = 10,
        match_threshold: float | None = None,
        extra_args: dict[str, Any] | None = None,
        schema: str | None = None,
    ) -> dict[str, Any]:
        """Call a vector-match RPC (e.g. ``match_documents``).

        Wraps :meth:`rpc` with the conventional pgvector arguments
        (``query_embedding``, ``match_count``, optional
        ``match_threshold``) plus any ``extra_args`` your RPC expects.
        """
        if not embedding:
            raise ValueError("embedding must be a non-empty list")
        args: dict[str, Any] = {
            "query_embedding": embedding,
            "match_count": match_count,
        }
        if match_threshold is not None:
            args["match_threshold"] = match_threshold
        if extra_args is not None:
            args.update(extra_args)
        return self.rpc(function_name, args=args, schema=schema)

    # MARK: - Auth admin

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_users(
        self,
        *,
        page: int = 1,
        per_page: int = _DEFAULT_LIST_LIMIT,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List auth users (service-role only).

        Best first tool for user triage. By default returns ``{"users":
        [...], "page", "per_page", "total"}`` where each user is a
        compact summary with ``user_ref`` (``user_1``, ``user_2``, ...)
        plus user-facing ``email``, ``phone``, ``role``, ``created_at``,
        ``last_sign_in_at``, and ``confirmed_at``. The raw user UUID is
        omitted by default because it is an internal handle. Set
        ``include_ids=True`` only when a follow-up tool
        (:meth:`update_user`, :meth:`delete_user`) needs the raw
        ``user_id``.

        Set ``include_metadata=False`` to receive the raw GoTrue
        response untouched.
        """
        payload: dict[str, Any] = self._client.get(
            "/auth/v1/admin/users",
            params={"page": page, "per_page": per_page},
        ).json()
        if not include_metadata:
            return payload
        raw_users: Any = payload.get("users") or []
        summaries: list[dict[str, Any]] = []
        for index, user in enumerate(raw_users, start=1):
            if not isinstance(user, dict):
                continue
            summary = _user_summary(cast("dict[str, Any]", user), index=index)
            if not include_ids:
                summary.pop("user_id", None)
            summaries.append(summary)
        result: dict[str, Any] = {
            "users": summaries,
            "page": page,
            "per_page": per_page,
        }
        if "total" in payload:
            result["total"] = payload["total"]
        # Raw GoTrue REST returns snake_case pagination metadata
        # (next_page / last_page); the camelCase nextPage key only
        # exists in the auth-js SDK wrapper, not the raw REST body.
        if "next_page" in payload:
            result["next_page"] = payload["next_page"]
        if "last_page" in payload:
            result["last_page"] = payload["last_page"]
        return result

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user(self, user_id: str) -> dict[str, Any]:
        """Return one auth user (service-role only).

        ``user_id`` accepts the raw UUID string or a dict from
        :meth:`list_users` (``include_ids=True``). Returns the full
        GoTrue user resource.
        """
        resolved = _extract_id(user_id, keys=("user_id", "id"))
        return self._client.get(f"/auth/v1/admin/users/{resolved}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_user(
        self,
        *,
        email: str | None = None,
        phone: str | None = None,
        password: str | None = None,
        email_confirm: bool = False,
        phone_confirm: bool = False,
        user_metadata: dict[str, Any] | None = None,
        app_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create an auth user.

        Returns the new user resource (with the server-assigned ``id``).
        Provide ``email_confirm=True`` / ``phone_confirm=True`` to skip
        the magic-link confirmation step.
        """
        if not email and not phone:
            raise ValueError("email or phone is required")
        body: dict[str, Any] = {}
        if email is not None:
            body["email"] = email
        if phone is not None:
            body["phone"] = phone
        if password is not None:
            body["password"] = password
        if email_confirm:
            body["email_confirm"] = True
        if phone_confirm:
            body["phone_confirm"] = True
        if user_metadata is not None:
            body["user_metadata"] = user_metadata
        if app_metadata is not None:
            body["app_metadata"] = app_metadata
        return self._client.post("/auth/v1/admin/users", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_user(self, user_id: Any, fields: dict[str, Any]) -> dict[str, Any]:
        """Update an auth user.

        ``user_id`` accepts the raw UUID string or a dict from
        :meth:`list_users` (``include_ids=True``). ``fields`` must be
        non-empty.
        """
        resolved = _extract_id(user_id, keys=("user_id", "id"))
        if not fields:
            raise ValueError("fields must be a non-empty dict")
        return self._client.put(f"/auth/v1/admin/users/{resolved}", json=fields).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_user(self, user_id: Any) -> dict[str, Any]:
        """Delete an auth user.

        Destructive: removes the user and cannot be undone. ``user_id``
        accepts the raw UUID string or a dict from :meth:`list_users`
        (``include_ids=True``). Confirm with the user before calling.
        """
        resolved = _extract_id(user_id, keys=("user_id", "id"))
        self._client.delete(f"/auth/v1/admin/users/{resolved}")
        return {"id": resolved, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def invite_user(self, email: str, *, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a magic-link invite to a user.

        Returns the invite metadata. ``data`` is forwarded as the
        custom ``data`` claim attached to the invite.
        """
        if not email:
            raise ValueError("email must be a non-empty string")
        body: dict[str, Any] = {"email": email}
        if data is not None:
            body["data"] = data
        return self._client.post("/auth/v1/invite", json=body).json()

    # MARK: - Storage

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_buckets(
        self,
        *,
        include_metadata: bool = True,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """List storage buckets.

        By default returns ``{"buckets": [...]}`` where each entry is a
        compact summary with ``bucket_ref``, the user-facing
        ``bucket_id`` / ``name``, ``public``, ``file_size_limit``,
        ``allowed_mime_types``, and ``created_at``. Pass ``bucket_id``
        to :meth:`list_objects` or :meth:`delete_bucket`.

        Set ``include_metadata=False`` to receive the raw Supabase array
        untouched.
        """
        payload: Any = self._client.get("/storage/v1/bucket").json()
        if not include_metadata:
            return payload
        items: list[Any] = cast("list[Any]", payload) if isinstance(payload, list) else []
        summaries: list[dict[str, Any]] = [
            _bucket_summary(cast("dict[str, Any]", item), index=index)
            for index, item in enumerate(items, start=1)
            if isinstance(item, dict)
        ]
        return {"buckets": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_bucket(
        self,
        *,
        bucket_id: str,
        name: str | None = None,
        public: bool = False,
        file_size_limit: int | None = None,
        allowed_mime_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a storage bucket.

        Returns ``{"name": <bucket_id>}`` on success. Set
        ``public=True`` to make objects readable without a signed URL.
        """
        if not bucket_id:
            raise ValueError("bucket_id must be a non-empty string")
        body: dict[str, Any] = {"id": bucket_id, "name": name or bucket_id, "public": public}
        if file_size_limit is not None:
            body["file_size_limit"] = file_size_limit
        if allowed_mime_types is not None:
            body["allowed_mime_types"] = allowed_mime_types
        return self._client.post("/storage/v1/bucket", json=body).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_bucket(self, bucket_id: Any) -> dict[str, Any]:
        """Delete a bucket. Bucket must be empty.

        Destructive: removes the bucket and cannot be undone.
        ``bucket_id`` accepts the raw ID string or a dict returned by
        :meth:`list_buckets` (under ``bucket_id`` / ``id`` / ``name``).
        Confirm with the user before calling.
        """
        resolved = _extract_id(bucket_id, keys=("bucket_id", "id", "name"))
        self._client.delete(f"/storage/v1/bucket/{resolved}")
        return {"id": resolved, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_objects(
        self,
        bucket_id: Any,
        *,
        prefix: str = "",
        limit: int = _DEFAULT_LIST_LIMIT,
        offset: int = 0,
        sort_by: str = "name",
        include_metadata: bool = True,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """List objects in a bucket.

        By default returns ``{"objects": [...], "bucket_id"}`` where
        each entry is a compact summary with ``object_ref``, the
        user-facing ``name`` (path within the bucket), ``size``,
        ``content_type``, ``updated_at``, ``created_at``. Pass
        ``name`` + ``bucket_id`` to :meth:`create_signed_url` or
        :meth:`delete_object`.

        Set ``include_metadata=False`` to receive the raw Supabase
        array untouched.
        """
        resolved = _extract_id(bucket_id, keys=("bucket_id", "id", "name"))
        body: dict[str, Any] = {
            "prefix": prefix,
            "limit": limit,
            "offset": offset,
            "sortBy": {"column": sort_by, "order": "asc"},
        }
        payload: Any = self._client.post(f"/storage/v1/object/list/{resolved}", json=body).json()
        if not include_metadata:
            return payload
        items: list[Any] = cast("list[Any]", payload) if isinstance(payload, list) else []
        summaries: list[dict[str, Any]] = [
            _object_summary(cast("dict[str, Any]", item), index=index)
            for index, item in enumerate(items, start=1)
            if isinstance(item, dict)
        ]
        return {"objects": summaries, "bucket_id": resolved}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_signed_url(
        self,
        bucket_id: Any,
        path: str,
        *,
        expires_in: int = 3600,
        download: bool = False,
    ) -> dict[str, Any]:
        """Generate a signed URL for an object.

        Returns ``{"signedURL": <url>}``. ``bucket_id`` accepts the raw
        ID string or a dict from :meth:`list_buckets`. ``path`` is the
        object path inside the bucket (as returned by
        :meth:`list_objects`).
        """
        resolved = _extract_id(bucket_id, keys=("bucket_id", "id", "name"))
        if not path:
            raise ValueError("path must be a non-empty string")
        body: dict[str, Any] = {"expiresIn": expires_in}
        if download:
            body["download"] = True
        return self._client.post(
            f"/storage/v1/object/sign/{resolved}/{path}",
            json=body,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_object(self, bucket_id: Any, path: str) -> dict[str, Any]:
        """Delete one object from a bucket.

        Destructive: removes the object and cannot be undone.
        ``bucket_id`` accepts the raw ID string or a dict from
        :meth:`list_buckets`. ``path`` is the object path inside the
        bucket (as returned by :meth:`list_objects`). Confirm with the
        user before calling.
        """
        resolved = _extract_id(bucket_id, keys=("bucket_id", "id", "name"))
        if not path:
            raise ValueError("path must be a non-empty string")
        self._client.delete(f"/storage/v1/object/{resolved}/{path}")
        return {"bucket": resolved, "path": path, "deleted": True}

    # MARK: - Edge functions

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def invoke_function(
        self,
        function_name: str,
        *,
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Invoke a Supabase Edge Function and return the JSON response.

        Returns ``{"status", "body"}``. ``body`` is the parsed JSON if
        the function returned JSON, otherwise the raw text. Pass extra
        ``headers`` to control content type or forward user context.
        """
        if not function_name:
            raise ValueError("function_name must be a non-empty string")
        response = self._client.post(
            f"/functions/v1/{function_name}",
            json=body if body is not None else {},
            headers=headers or None,
        )
        try:
            payload: Any = response.json()
        except ValueError:
            payload = response.text()
        return {"status": response.status, "body": payload}
