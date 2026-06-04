"""Amazon S3 REST API connector (SigV4)."""

# pyright: strict

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from maivn import toolify, toolset

from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .._aws.sigv4 import SigV4Auth

# MARK: Constants

_SUMMARY_MAX = 25


# MARK: XML parsing helpers


def _extract_text(xml: str, tag: str) -> list[str]:
    """Extract text content for all occurrences of ``<tag>...</tag>`` (handles namespaces)."""
    pattern = re.compile(rf"<(?:\w+:)?{tag}\b[^>]*>([\s\S]*?)</(?:\w+:)?{tag}>", re.IGNORECASE)
    return [match.group(1).strip() for match in pattern.finditer(xml)]


def _extract_buckets(xml: str) -> list[dict[str, str]]:
    """Pull bucket name + creation date out of the ListBuckets XML."""
    block = re.compile(
        r"<(?:\w+:)?Bucket\b[^>]*>([\s\S]*?)</(?:\w+:)?Bucket>",
        re.IGNORECASE,
    )
    buckets: list[dict[str, str]] = []
    for match in block.finditer(xml):
        chunk = match.group(1)
        names = _extract_text(chunk, "Name")
        dates = _extract_text(chunk, "CreationDate")
        buckets.append(
            {
                "name": names[0] if names else "",
                "creation_date": dates[0] if dates else "",
            }
        )
    return buckets


def _extract_objects(xml: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Pull object key/size/etag out of the ListObjectsV2 XML."""
    block = re.compile(
        r"<(?:\w+:)?Contents\b[^>]*>([\s\S]*?)</(?:\w+:)?Contents>",
        re.IGNORECASE,
    )
    objects: list[dict[str, Any]] = []
    for match in block.finditer(xml):
        chunk = match.group(1)
        keys = _extract_text(chunk, "Key")
        sizes = _extract_text(chunk, "Size")
        last_modified = _extract_text(chunk, "LastModified")
        etags = _extract_text(chunk, "ETag")
        storage_class = _extract_text(chunk, "StorageClass")
        size_str = sizes[0] if sizes else ""
        try:
            size_int: int | str = int(size_str) if size_str else 0
        except ValueError:
            size_int = size_str
        objects.append(
            {
                "key": keys[0] if keys else "",
                "size": size_int,
                "last_modified": last_modified[0] if last_modified else "",
                "etag": (etags[0].strip('"') if etags else ""),
                "storage_class": storage_class[0] if storage_class else "",
            }
        )
    paging: dict[str, Any] = {}
    truncated = _extract_text(xml, "IsTruncated")
    if truncated:
        paging["is_truncated"] = truncated[0].lower() == "true"
    next_token = _extract_text(xml, "NextContinuationToken")
    if next_token:
        paging["next_continuation_token"] = next_token[0]
    return objects, paging


# MARK: ToolSet


@toolset(prefix="aws_s3")
class AmazonS3ToolSet:
    """A connector for Amazon S3 (REST + SigV4).

    Args:
        access_key: AWS access key ID.
        secret_key: AWS secret access key.
        region: AWS region (e.g. ``"us-east-1"``).
        session_token: Optional STS session token.
    """

    metadata = ProviderMetadata(
        name="aws_s3",
        display_name="Amazon S3",
        version="0.1.0",
        description="Buckets, objects, listings, multipart uploads, and policies.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://docs.aws.amazon.com/AmazonS3/latest/API/Welcome.html",
        homepage_url="https://aws.amazon.com/s3/",
        tags=("cloud", "storage", "aws"),
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
        self._region = region
        self._client = HttpClient(
            base_url=f"https://s3.{region}.amazonaws.com",
            auth=SigV4Auth(
                access_key=access_key,
                secret_key=secret_key,
                region=region,
                service="s3",
                session_token=session_token,
            ),
            transport=transport,
            default_headers={"Accept": "application/xml"},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_buckets(
        self,
        *,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """List buckets owned by the caller.

        Best first tool for bucket discovery. Returns compact summaries
        by default: ``bucket_ref``, ``name`` (bucket name — the primary
        S3 identifier, user-facing), ``creation_date``. Set
        ``include_metadata=False`` to get the raw XML body.
        """
        response = self._client.get("/")
        if not include_metadata:
            return {"status": response.status, "body": response.text()}
        body = response.text()
        buckets = _extract_buckets(body)
        summaries = [
            {
                "bucket_ref": f"bucket_{index}",
                "name": bucket["name"],
                "creation_date": bucket["creation_date"],
            }
            for index, bucket in enumerate(buckets[:_SUMMARY_MAX], start=1)
        ]
        return {"status": response.status, "buckets": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_bucket(
        self,
        bucket: str,
        *,
        location_constraint: str | None = None,
    ) -> dict[str, Any]:
        """Create a bucket.

        Returns ``{"status": ..., "bucket": <name>}``. Outside
        ``us-east-1`` you must pass ``location_constraint`` matching the
        region of this connector.
        """
        if not bucket:
            raise ValueError("bucket is required")
        body = b""
        headers: dict[str, str] = {}
        if location_constraint:
            body = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                "<CreateBucketConfiguration "
                'xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                f"<LocationConstraint>{location_constraint}</LocationConstraint>"
                "</CreateBucketConfiguration>"
            ).encode()
            headers["Content-Type"] = "application/xml"
        response = self._client.put(f"/{bucket}", data=body, headers=headers)
        return {"status": response.status, "bucket": bucket}

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_bucket(self, bucket: str) -> dict[str, Any]:
        """Delete an empty bucket.

        Destructive — the bucket must already be empty, and once
        deleted the name becomes available for any AWS account.
        """
        if not bucket:
            raise ValueError("bucket is required")
        response = self._client.delete(f"/{bucket}")
        return {"status": response.status, "bucket": bucket, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_objects_v2(
        self,
        bucket: str,
        *,
        prefix: str | None = None,
        delimiter: str | None = None,
        max_keys: int = 25,
        continuation_token: str | None = None,
        start_after: str | None = None,
        include_metadata: bool = True,
    ) -> dict[str, Any]:
        """List objects in a bucket (V2 API).

        Best first tool for browsing a bucket. Returns compact summaries:
        ``object_ref``, ``key`` (object key — user-facing path),
        ``size``, ``last_modified``, ``etag``, ``storage_class``. Use
        ``prefix`` to scope to a "folder" and ``delimiter="/"`` to
        collapse subprefixes. Set ``include_metadata=False`` to get the
        raw XML body.
        """
        if not bucket:
            raise ValueError("bucket is required")
        if max_keys < 1 or max_keys > 1000:
            raise ValueError("max_keys must be between 1 and 1000")
        if include_metadata:
            max_keys = min(max_keys, _SUMMARY_MAX)
        params: dict[str, Any] = {
            "list-type": "2",
            "max-keys": max_keys,
        }
        if prefix is not None:
            params["prefix"] = prefix
        if delimiter is not None:
            params["delimiter"] = delimiter
        if continuation_token is not None:
            params["continuation-token"] = continuation_token
        if start_after is not None:
            params["start-after"] = start_after
        response = self._client.get(f"/{bucket}", params=params)
        if not include_metadata:
            return {"status": response.status, "body": response.text()}
        body = response.text()
        objects, paging = _extract_objects(body)
        summaries = [
            {
                "object_ref": f"object_{index}",
                **obj,
            }
            for index, obj in enumerate(objects[:_SUMMARY_MAX], start=1)
        ]
        return {
            "status": response.status,
            "bucket": bucket,
            "objects": summaries,
            **paging,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def head_object(
        self,
        *,
        bucket: str,
        key: str,
        version_id: str | None = None,
    ) -> dict[str, Any]:
        """Return an object's metadata (HEAD).

        Returns ``{"status": ..., "headers": {...}}``. Useful for
        checking existence and size without downloading bytes.
        """
        if not bucket or not key:
            raise ValueError("bucket and key are required")
        params: dict[str, Any] = {}
        if version_id is not None:
            params["versionId"] = version_id
        response = self._client.request(
            "HEAD",
            f"/{bucket}/{quote(key, safe='/')}",
            params=params or None,
        )
        return {
            "status": response.status,
            "headers": dict(response.headers),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_object(
        self,
        *,
        bucket: str,
        key: str,
        version_id: str | None = None,
        range_header: str | None = None,
    ) -> dict[str, Any]:
        """GET an object (returns the body as text).

        Returns ``{"status": ..., "body": ...}``. For binary content
        consider ``range_header`` to fetch a slice; large binary objects
        should be downloaded directly rather than via this tool.
        """
        if not bucket or not key:
            raise ValueError("bucket and key are required")
        params: dict[str, Any] = {}
        if version_id is not None:
            params["versionId"] = version_id
        headers: dict[str, str] = {}
        if range_header is not None:
            headers["Range"] = range_header
        response = self._client.get(
            f"/{bucket}/{quote(key, safe='/')}",
            params=params or None,
            headers=headers or None,
        )
        return {
            "status": response.status,
            "body": response.text(),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def put_object(
        self,
        *,
        bucket: str,
        key: str,
        body: bytes,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
        acl: str | None = None,
        cache_control: str | None = None,
    ) -> dict[str, Any]:
        """PUT an object.

        Returns ``{"status": ..., "etag": ...}``. ``metadata`` keys are
        sent as ``x-amz-meta-<key>`` headers (custom user metadata).
        """
        if not bucket or not key:
            raise ValueError("bucket and key are required")
        headers: dict[str, str] = {}
        if content_type is not None:
            headers["Content-Type"] = content_type
        if cache_control is not None:
            headers["Cache-Control"] = cache_control
        if acl is not None:
            headers["x-amz-acl"] = acl
        if metadata is not None:
            for k, v in metadata.items():
                headers[f"x-amz-meta-{k}"] = v
        response = self._client.put(
            f"/{bucket}/{quote(key, safe='/')}",
            data=body,
            headers=headers or None,
        )
        return {
            "status": response.status,
            "etag": response.headers.get("ETag"),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_object(
        self,
        *,
        bucket: str,
        key: str,
        version_id: str | None = None,
    ) -> dict[str, Any]:
        """Delete an object.

        Destructive — without versioning enabled the object cannot be
        recovered. Confirm with the user before calling.
        """
        if not bucket or not key:
            raise ValueError("bucket and key are required")
        params: dict[str, Any] = {}
        if version_id is not None:
            params["versionId"] = version_id
        response = self._client.delete(
            f"/{bucket}/{quote(key, safe='/')}",
            params=params or None,
        )
        return {"status": response.status, "deleted": True}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def copy_object(
        self,
        *,
        source_bucket: str,
        source_key: str,
        dest_bucket: str,
        dest_key: str,
        metadata_directive: str = "COPY",
    ) -> dict[str, Any]:
        """Server-side copy an object.

        Returns ``{"status": ..., "body": ...}``. With
        ``metadata_directive="REPLACE"``, custom metadata on the source
        is dropped and the destination starts fresh.
        """
        if not source_bucket or not source_key or not dest_bucket or not dest_key:
            raise ValueError("source_bucket, source_key, dest_bucket, and dest_key are required")
        headers = {
            "x-amz-copy-source": f"/{source_bucket}/{quote(source_key, safe='/')}",
            "x-amz-metadata-directive": metadata_directive,
        }
        response = self._client.put(
            f"/{dest_bucket}/{quote(dest_key, safe='/')}",
            headers=headers,
        )
        return {"status": response.status, "body": response.text()}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_bucket_location(self, bucket: str) -> dict[str, Any]:
        """Return a bucket's region constraint.

        Returns ``{"status": ..., "body": <XML>}`` where the body
        contains ``<LocationConstraint>``.
        """
        if not bucket:
            raise ValueError("bucket is required")
        response = self._client.get(f"/{bucket}", params={"location": ""})
        return {"status": response.status, "body": response.text()}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_bucket_policy(self, bucket: str) -> dict[str, Any]:
        """Return the bucket's IAM policy (JSON in body).

        Returns ``{"status": ..., "body": <JSON-as-string>}``.
        """
        if not bucket:
            raise ValueError("bucket is required")
        response = self._client.get(f"/{bucket}", params={"policy": ""})
        return {"status": response.status, "body": response.text()}
