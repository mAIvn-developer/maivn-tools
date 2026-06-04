"""AWS IAM API connector (Query protocol, SigV4)."""

# pyright: strict

from __future__ import annotations

import re
from typing import Any, cast
from urllib.parse import urlencode
from xml.etree import ElementTree

from maivn import toolify, toolset

from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport
from .._aws.sigv4 import SigV4Auth

# MARK: Constants

_SUMMARY_MAX = 25

# IAM Query protocol responses are XML namespaced under the API version.
_NS_RE = re.compile(r"^\{[^}]*\}")


# MARK: Coercion helpers


def _as_dict(value: Any) -> dict[str, Any]:
    """Return ``value`` as a ``dict[str, Any]`` when it is a mapping, else ``{}``."""
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any] | None:
    """Return ``value`` as a ``list[Any]`` when it is a list, else ``None``."""
    return cast("list[Any]", value) if isinstance(value, list) else None


def _local_tag(tag: str) -> str:
    """Strip the XML namespace (e.g. ``{https://.../2010-05-08/}Users``)."""
    return _NS_RE.sub("", tag)


# MARK: XML parsing


def _xml_element_to_obj(element: ElementTree.Element) -> Any:
    """Convert an XML element to a JSON-like dict/list/str structure.

    AWS Query collections use repeated ``<member>`` children; an element whose
    children are all ``<member>`` is converted to a list (collapsing a single
    member into a one-item list rather than a bare dict).
    """
    children = list(element)
    if not children:
        return (element.text or "").strip()
    if all(_local_tag(child.tag) == "member" for child in children):
        return [_xml_element_to_obj(child) for child in children]
    obj: dict[str, Any] = {}
    for child in children:
        key = _local_tag(child.tag)
        value = _xml_element_to_obj(child)
        if key in obj:
            existing: Any = obj[key]
            existing_list = _as_list(existing)
            if existing_list is not None:
                existing_list.append(value)
            else:
                obj[key] = [existing, value]
        else:
            obj[key] = value
    return obj


class _SafeXmlTarget(ElementTree.TreeBuilder):
    """TreeBuilder that rejects DTDs/entity declarations (XXE / billion-laughs)."""

    def doctype(self, name: str, pubid: str, system: str) -> None:  # noqa: D102
        raise ValueError("XML DOCTYPE declarations are not allowed")


def _parse_xml_response(text: str) -> dict[str, Any]:
    """Parse an IAM Query XML response into a nested dict keyed by element name.

    The parser rejects DOCTYPE/entity declarations so a malicious or malformed
    response cannot trigger XXE or entity-expansion ("billion laughs") attacks.
    """
    parser = ElementTree.XMLParser(target=_SafeXmlTarget())
    parser.feed(text)
    root = parser.close()
    obj = _xml_element_to_obj(root)
    body = _as_dict(obj)
    return {_local_tag(root.tag): body}


# MARK: Argument coercion


def _coerce_named(candidate: Any, *, field: str, dict_keys: tuple[str, ...]) -> str:
    """Accept a string name, a resource dict, or a list of such."""
    if isinstance(candidate, str):
        if not candidate:
            raise ValueError(f"{field} is required")
        return candidate
    if isinstance(candidate, dict):
        candidate_dict = _as_dict(candidate)
        for key in dict_keys:
            value = candidate_dict.get(key)
            if isinstance(value, str) and value:
                return value
    if isinstance(candidate, list) and candidate:
        return _coerce_named(candidate[0], field=field, dict_keys=dict_keys)
    raise ValueError(f"{field} must be a non-empty string (or a resource dict)")


def _coerce_user_name(candidate: Any) -> str:
    return _coerce_named(candidate, field="user_name", dict_keys=("UserName", "user_name", "name"))


def _coerce_role_name(candidate: Any) -> str:
    return _coerce_named(candidate, field="role_name", dict_keys=("RoleName", "role_name", "name"))


def _coerce_policy_arn(candidate: Any) -> str:
    return _coerce_named(
        candidate, field="policy_arn", dict_keys=("PolicyArn", "policy_arn", "Arn", "arn")
    )


# MARK: Response extractors


def _users_from_response(payload: Any) -> list[Any]:
    typed_payload = _as_dict(payload)
    response: Any = (
        typed_payload.get("ListUsersResponse") or typed_payload.get("ListUsersResult") or {}
    )
    if isinstance(response, dict):
        result = _as_dict(_as_dict(response).get("ListUsersResult") or response)
        users = _as_list(result.get("Users") or result.get("users"))
        if users is not None:
            return users
    direct = _as_list(typed_payload.get("Users"))
    return direct if direct is not None else []


def _roles_from_response(payload: Any) -> list[Any]:
    typed_payload = _as_dict(payload)
    response: Any = typed_payload.get("ListRolesResponse") or {}
    if isinstance(response, dict):
        result = _as_dict(_as_dict(response).get("ListRolesResult") or response)
        roles = _as_list(result.get("Roles") or result.get("roles"))
        if roles is not None:
            return roles
    direct = _as_list(typed_payload.get("Roles"))
    return direct if direct is not None else []


def _policies_from_response(payload: Any) -> list[Any]:
    typed_payload = _as_dict(payload)
    response: Any = typed_payload.get("ListPoliciesResponse") or {}
    if isinstance(response, dict):
        result = _as_dict(_as_dict(response).get("ListPoliciesResult") or response)
        policies = _as_list(result.get("Policies") or result.get("policies"))
        if policies is not None:
            return policies
    direct = _as_list(typed_payload.get("Policies"))
    return direct if direct is not None else []


# MARK: ToolSet


@toolset(prefix="aws_iam")
class AmazonIAMToolSet:
    """A connector for AWS IAM.

    Args:
        access_key: AWS access key ID.
        secret_key: AWS secret access key.
        session_token: Optional STS session token.

    IAM is a global service — requests are signed against ``us-east-1``.
    """

    metadata = ProviderMetadata(
        name="aws_iam",
        display_name="AWS IAM",
        version="0.1.0",
        description="Users, roles, policies, attachments, and access keys.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url=("https://docs.aws.amazon.com/IAM/latest/APIReference/welcome.html"),
        homepage_url="https://aws.amazon.com/iam/",
        tags=("cloud", "identity", "aws"),
    )

    def __init__(
        self,
        *,
        access_key: str,
        secret_key: str,
        session_token: str | None = None,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_key or not secret_key:
            raise ValueError("access_key and secret_key are required")
        self.connection = connection
        self._client = HttpClient(
            base_url="https://iam.amazonaws.com",
            auth=SigV4Auth(
                access_key=access_key,
                secret_key=secret_key,
                region="us-east-1",
                service="iam",
                session_token=session_token,
            ),
            transport=transport,
            default_headers={
                # The IAM Query protocol always returns XML; Accept is ignored.
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _call(self, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        form: dict[str, Any] = {"Action": action, "Version": "2010-05-08"}
        if params:
            form.update(params)
        body = urlencode(form).encode("utf-8")
        response = self._client.post("/", data=body)
        text = response.text()
        try:
            return _parse_xml_response(text)
        except (ElementTree.ParseError, ValueError):
            return {"status": response.status, "body": text}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_users(
        self,
        *,
        path_prefix: str | None = None,
        max_items: int = 25,
        marker: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List IAM users.

        Best first tool for user discovery. Returns compact summaries:
        ``user_ref``, ``user_name`` (the primary identifier — user-facing),
        ``path``, ``create_date``, ``password_last_used``. The opaque
        ``UserId`` and full ``Arn`` are omitted by default; set
        ``include_ids=True`` when needed.
        """
        if max_items < 1 or max_items > 1000:
            raise ValueError("max_items must be between 1 and 1000")
        if include_metadata:
            max_items = min(max_items, _SUMMARY_MAX)
        params: dict[str, Any] = {"MaxItems": max_items}
        if path_prefix is not None:
            params["PathPrefix"] = path_prefix
        if marker is not None:
            params["Marker"] = marker
        payload = self._call("ListUsers", params)
        if not include_metadata:
            return payload
        users = _users_from_response(payload)
        summaries: list[dict[str, Any]] = []
        for index, raw_user in enumerate(users[:_SUMMARY_MAX], start=1):
            if not isinstance(raw_user, dict):
                continue
            user = _as_dict(raw_user)
            summary: dict[str, Any] = {
                "user_ref": f"user_{index}",
                "user_name": user.get("UserName", user.get("user_name", "")),
                "path": user.get("Path", ""),
                "create_date": user.get("CreateDate", ""),
                "password_last_used": user.get("PasswordLastUsed", ""),
            }
            if include_ids:
                summary["user_id"] = user.get("UserId", "")
                summary["arn"] = user.get("Arn", "")
            summaries.append(summary)
        return {"users": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_user(self, *, user_name: Any | None = None) -> dict[str, Any]:
        """Return one user (or the calling user if ``user_name`` is None).

        ``user_name`` accepts a string name or a user dict from
        ``list_users``.
        """
        params: dict[str, Any] = {}
        if user_name is not None:
            params["UserName"] = _coerce_user_name(user_name)
        return self._call("GetUser", params)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_user(
        self,
        *,
        user_name: str,
        path: str | None = None,
        permissions_boundary: str | None = None,
    ) -> dict[str, Any]:
        """Create an IAM user.

        Returns the new user resource. Set ``permissions_boundary`` to
        cap the maximum permissions the user can have.
        """
        if not user_name:
            raise ValueError("user_name is required")
        params: dict[str, Any] = {"UserName": user_name}
        if path is not None:
            params["Path"] = path
        if permissions_boundary is not None:
            params["PermissionsBoundary"] = permissions_boundary
        return self._call("CreateUser", params)

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_user(self, user_name: Any) -> dict[str, Any]:
        """Delete an IAM user.

        Destructive — the user must first have no access keys, policies,
        or group memberships. Confirm with the user before calling.
        ``user_name`` accepts a string name or a user dict.
        """
        name = _coerce_user_name(user_name)
        return self._call("DeleteUser", {"UserName": name})

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_roles(
        self,
        *,
        path_prefix: str | None = None,
        max_items: int = 25,
        marker: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List IAM roles.

        Best first tool for role discovery. Returns compact summaries:
        ``role_ref``, ``role_name`` (user-facing), ``path``,
        ``description``, ``create_date``, ``max_session_duration``. The
        opaque ``RoleId`` and full ``Arn`` are omitted by default; set
        ``include_ids=True`` when needed.
        """
        if max_items < 1 or max_items > 1000:
            raise ValueError("max_items must be between 1 and 1000")
        if include_metadata:
            max_items = min(max_items, _SUMMARY_MAX)
        params: dict[str, Any] = {"MaxItems": max_items}
        if path_prefix is not None:
            params["PathPrefix"] = path_prefix
        if marker is not None:
            params["Marker"] = marker
        payload = self._call("ListRoles", params)
        if not include_metadata:
            return payload
        roles = _roles_from_response(payload)
        summaries: list[dict[str, Any]] = []
        for index, raw_role in enumerate(roles[:_SUMMARY_MAX], start=1):
            if not isinstance(raw_role, dict):
                continue
            role = _as_dict(raw_role)
            summary: dict[str, Any] = {
                "role_ref": f"role_{index}",
                "role_name": role.get("RoleName", ""),
                "path": role.get("Path", ""),
                "description": role.get("Description", ""),
                "create_date": role.get("CreateDate", ""),
                "max_session_duration": role.get("MaxSessionDuration", 0),
            }
            if include_ids:
                summary["role_id"] = role.get("RoleId", "")
                summary["arn"] = role.get("Arn", "")
            summaries.append(summary)
        return {"roles": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_role(self, role_name: Any) -> dict[str, Any]:
        """Return one role's detail.

        ``role_name`` accepts a string name or a role dict from
        ``list_roles``.
        """
        name = _coerce_role_name(role_name)
        return self._call("GetRole", {"RoleName": name})

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_role(
        self,
        *,
        role_name: str,
        assume_role_policy_document: str,
        path: str | None = None,
        description: str | None = None,
        max_session_duration: int | None = None,
    ) -> dict[str, Any]:
        """Create an IAM role.

        Returns the new role. ``assume_role_policy_document`` is a JSON
        string defining who can assume the role (the trust policy).
        """
        if not role_name or not assume_role_policy_document:
            raise ValueError("role_name and assume_role_policy_document are required")
        params: dict[str, Any] = {
            "RoleName": role_name,
            "AssumeRolePolicyDocument": assume_role_policy_document,
        }
        if path is not None:
            params["Path"] = path
        if description is not None:
            params["Description"] = description
        if max_session_duration is not None:
            params["MaxSessionDuration"] = max_session_duration
        return self._call("CreateRole", params)

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_role(self, role_name: Any) -> dict[str, Any]:
        """Delete a role.

        Destructive — the role must first have no attached policies or
        instance profiles. Confirm with the user before calling.
        ``role_name`` accepts a string name or a role dict.
        """
        name = _coerce_role_name(role_name)
        return self._call("DeleteRole", {"RoleName": name})

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_policies(
        self,
        *,
        scope: str = "All",
        only_attached: bool = False,
        max_items: int = 25,
        marker: str | None = None,
        include_metadata: bool = True,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List managed policies.

        Returns compact summaries: ``policy_ref``, ``policy_name``,
        ``path``, ``attachment_count``, ``description``, ``create_date``,
        ``is_attachable``. ``scope`` is ``All``, ``AWS`` (AWS-managed
        only), or ``Local`` (customer-managed only). Policy ARNs are
        omitted by default; set ``include_ids=True`` if a follow-up tool
        (``attach_user_policy``, ``attach_role_policy``) needs the ARN.
        """
        if scope not in {"All", "AWS", "Local"}:
            raise ValueError("scope must be All/AWS/Local")
        if max_items < 1 or max_items > 1000:
            raise ValueError("max_items must be between 1 and 1000")
        if include_metadata:
            max_items = min(max_items, _SUMMARY_MAX)
        params: dict[str, Any] = {
            "Scope": scope,
            "OnlyAttached": str(only_attached).lower(),
            "MaxItems": max_items,
        }
        if marker is not None:
            params["Marker"] = marker
        payload = self._call("ListPolicies", params)
        if not include_metadata:
            return payload
        policies = _policies_from_response(payload)
        summaries: list[dict[str, Any]] = []
        for index, raw_policy in enumerate(policies[:_SUMMARY_MAX], start=1):
            if not isinstance(raw_policy, dict):
                continue
            policy = _as_dict(raw_policy)
            summary: dict[str, Any] = {
                "policy_ref": f"policy_{index}",
                "policy_name": policy.get("PolicyName", ""),
                "path": policy.get("Path", ""),
                "attachment_count": policy.get("AttachmentCount", 0),
                "description": policy.get("Description", ""),
                "create_date": policy.get("CreateDate", ""),
                "is_attachable": policy.get("IsAttachable", False),
            }
            if include_ids:
                summary["policy_arn"] = policy.get("Arn", "")
                summary["policy_id"] = policy.get("PolicyId", "")
            summaries.append(summary)
        return {"policies": summaries}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_policy(self, policy_arn: Any) -> dict[str, Any]:
        """Return one policy's metadata.

        ``policy_arn`` accepts an ARN string or a policy dict from
        ``list_policies(include_ids=True)``.
        """
        arn = _coerce_policy_arn(policy_arn)
        return self._call("GetPolicy", {"PolicyArn": arn})

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def attach_user_policy(
        self,
        *,
        user_name: Any,
        policy_arn: Any,
    ) -> dict[str, Any]:
        """Attach a managed policy to a user.

        ``user_name`` accepts a string or a user dict. ``policy_arn``
        accepts an ARN string or a policy dict.
        """
        name = _coerce_user_name(user_name)
        arn = _coerce_policy_arn(policy_arn)
        return self._call(
            "AttachUserPolicy",
            {"UserName": name, "PolicyArn": arn},
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def attach_role_policy(
        self,
        *,
        role_name: Any,
        policy_arn: Any,
    ) -> dict[str, Any]:
        """Attach a managed policy to a role.

        ``role_name`` accepts a string or a role dict. ``policy_arn``
        accepts an ARN string or a policy dict.
        """
        name = _coerce_role_name(role_name)
        arn = _coerce_policy_arn(policy_arn)
        return self._call(
            "AttachRolePolicy",
            {"RoleName": name, "PolicyArn": arn},
        )

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def detach_user_policy(
        self,
        *,
        user_name: Any,
        policy_arn: Any,
    ) -> dict[str, Any]:
        """Detach a managed policy from a user.

        Destructive — the user will lose any permissions granted by the
        policy. Confirm with the user before calling.
        """
        name = _coerce_user_name(user_name)
        arn = _coerce_policy_arn(policy_arn)
        return self._call(
            "DetachUserPolicy",
            {"UserName": name, "PolicyArn": arn},
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_access_key(
        self,
        *,
        user_name: Any,
    ) -> dict[str, Any]:
        """Create an access key for a user.

        The secret access key is returned only once; treat the response
        as sensitive. ``user_name`` accepts a string or a user dict.
        """
        name = _coerce_user_name(user_name)
        return self._call("CreateAccessKey", {"UserName": name})

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_access_key(
        self,
        *,
        user_name: Any,
        access_key_id: str,
    ) -> dict[str, Any]:
        """Delete an access key.

        Destructive — any callers using this key will immediately fail.
        Confirm with the user before calling.
        """
        name = _coerce_user_name(user_name)
        if not access_key_id:
            raise ValueError("access_key_id is required")
        return self._call(
            "DeleteAccessKey",
            {"UserName": name, "AccessKeyId": access_key_id},
        )
