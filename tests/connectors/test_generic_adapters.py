# pyright: strict
from __future__ import annotations

from typing import Any, cast

import pytest

from maivn_tools.connectors.generic_api import (
    GenericHttpConnector,
    GraphQLConnector,
    GraphQLOperation,
    HttpEndpoint,
    OpenAPIConnector,
    WebhookListener,
)
from maivn_tools.core import AuthMode, PermissionFlag, PermissionSet, ProviderMetadata
from maivn_tools.events import (
    SignatureAlgorithm,
    SignatureMismatchError,
    WebhookVerifier,
)
from maivn_tools.runtime import ProviderError
from maivn_tools.testing import MockResponse, MockTransport, json_response


def _metadata(name: str = "example") -> ProviderMetadata:
    return ProviderMetadata(
        name=name,
        display_name=name,
        version="0.1.0",
        auth_modes=(AuthMode.NONE,),
    )


def test_http_endpoint_path_params_extracted() -> None:
    endpoint = HttpEndpoint(name="get", method="GET", path="/users/{user_id}/posts/{post_id}")
    assert endpoint.path_params == ("user_id", "post_id")


def test_http_endpoint_validates_required_fields() -> None:
    with pytest.raises(ValueError):
        HttpEndpoint(name="", method="GET", path="/x")
    with pytest.raises(ValueError):
        HttpEndpoint(name="x", method="", path="/x")
    with pytest.raises(ValueError):
        HttpEndpoint(name="x", method="GET", path="")


def test_http_endpoint_rejects_body_params_on_safe_methods() -> None:
    with pytest.raises(ValueError):
        HttpEndpoint(name="x", method="GET", path="/x", body_params=("a",))


def test_generic_http_connector_dispatches_path_query_body() -> None:
    transport = MockTransport()
    transport.enqueue(json_response({"id": "u-1"}))
    transport.enqueue(json_response({"created": True}))

    connector = GenericHttpConnector(
        metadata=_metadata(),
        base_url="https://api.example.test",
        transport=transport,
        endpoints=[
            HttpEndpoint(
                name="get_user",
                method="GET",
                path="/users/{user_id}",
                query_params=("expand",),
            ),
            HttpEndpoint(
                name="create_post",
                method="POST",
                path="/users/{user_id}/posts",
                body_params=("title", "body"),
                permissions=PermissionSet(PermissionFlag.WRITE),
            ),
        ],
    )
    get_user, create_post = connector.tools()
    assert get_user(user_id="u-1", expand="profile") == {"id": "u-1"}
    assert create_post(user_id="u-1", title="hi", body="there") == {"created": True}

    get_req, post_req = transport.requests
    assert get_req.url.endswith("/users/u-1")
    assert get_req.params == {"expand": "profile"}
    assert post_req.url.endswith("/users/u-1/posts")
    assert post_req.json_body == {"title": "hi", "body": "there"}
    create_post_permissions = cast(PermissionSet, cast(Any, create_post).permissions)
    assert create_post_permissions.includes(PermissionFlag.WRITE)


def test_generic_http_connector_rejects_unknown_kwargs() -> None:
    transport = MockTransport([MockResponse(response=json_response({}))])
    connector = GenericHttpConnector(
        metadata=_metadata(),
        base_url="https://api.example.test",
        transport=transport,
        endpoints=[HttpEndpoint(name="ping", method="GET", path="/ping")],
    )
    tool = connector.tools()[0]
    with pytest.raises(TypeError):
        tool(unknown="value")


def test_generic_http_connector_requires_endpoints() -> None:
    with pytest.raises(ValueError):
        GenericHttpConnector(
            metadata=_metadata(),
            base_url="https://api.example.test",
            endpoints=[],
        )


def test_openapi_connector_imports_operations() -> None:
    document = {
        "openapi": "3.0.0",
        "paths": {
            "/users": {
                "get": {
                    "operationId": "listUsers",
                    "summary": "List users",
                    "parameters": [
                        {"in": "query", "name": "limit"},
                        {"in": "query", "name": "offset"},
                    ],
                },
                "post": {
                    "operationId": "createUser",
                    "summary": "Create user",
                    "requestBody": {"required": True},
                },
            },
            "/users/{user_id}": {
                "delete": {
                    "operationId": "deleteUser",
                    "summary": "Delete user",
                    "parameters": [{"in": "path", "name": "user_id"}],
                },
                "patch": {
                    "operationId": "patchUser",
                    "summary": "Patch user",
                    "requestBody": {"required": True},
                },
                "get": {
                    "summary": "Missing operationId is skipped",
                },
            },
        },
    }
    importer = OpenAPIConnector(
        document,
        operation_denylist={"patchUser"},
        permission_overrides={"listUsers": PermissionSet(PermissionFlag.READ)},
        destructive_overrides={"createUser"},
    )
    endpoints = {ep.name: ep for ep in importer.endpoints()}
    assert set(endpoints) == {"listUsers", "createUser", "deleteUser"}
    assert endpoints["listUsers"].query_params == ("limit", "offset")
    assert endpoints["createUser"].destructive is True
    assert endpoints["deleteUser"].destructive is True
    assert endpoints["deleteUser"].permissions.includes(PermissionFlag.DELETE)


def test_openapi_connector_rejects_non_v3_documents() -> None:
    with pytest.raises(ValueError):
        OpenAPIConnector({"openapi": "2.0"})


def test_openapi_connector_validates_mapping_input() -> None:
    with pytest.raises(TypeError):
        OpenAPIConnector("not-a-mapping")  # type: ignore[arg-type]


def test_graphql_connector_executes_and_passes_variables() -> None:
    transport = MockTransport()
    transport.enqueue(json_response({"data": {"viewer": {"id": "u-1"}}}))
    connector = GraphQLConnector(
        metadata=_metadata(),
        endpoint="https://api.example.test/graphql",
        transport=transport,
        operations=[
            GraphQLOperation(
                name="get_viewer",
                query="query GetViewer { viewer { id } }",
                operation_name="GetViewer",
            )
        ],
    )
    result = connector.tools()[0]()
    assert result == {"viewer": {"id": "u-1"}}
    request = transport.requests[0]
    assert request.json_body["query"].startswith("query GetViewer")
    assert request.json_body["operationName"] == "GetViewer"


def test_graphql_connector_surfaces_errors_as_provider_error() -> None:
    transport = MockTransport(
        [MockResponse(response=json_response({"errors": [{"message": "nope"}]}))]
    )
    connector = GraphQLConnector(
        metadata=_metadata(),
        endpoint="https://api.example.test/graphql",
        transport=transport,
        operations=[GraphQLOperation(name="failing", query="query { x }")],
    )
    with pytest.raises(ProviderError):
        connector.tools()[0]()


def test_graphql_connector_enforces_variable_allowlist() -> None:
    transport = MockTransport([MockResponse(response=json_response({"data": None}))])
    connector = GraphQLConnector(
        metadata=_metadata(),
        endpoint="https://api.example.test/graphql",
        transport=transport,
        operations=[
            GraphQLOperation(
                name="op",
                query="mutation Op($title: String!) { op(title: $title) { id } }",
                variables_allowlist=("title",),
            )
        ],
    )
    op = connector.tools()[0]
    with pytest.raises(TypeError):
        op(variables={"bogus": 1})


def test_graphql_operation_validates_fields() -> None:
    with pytest.raises(ValueError):
        GraphQLOperation(name="", query="x")
    with pytest.raises(ValueError):
        GraphQLOperation(name="x", query="")


def _signed_headers(secret: str, payload: bytes) -> dict[str, str]:
    import hashlib
    import hmac as _hmac

    sig = _hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return {"X-Signature": sig}


def test_webhook_listener_verifies_and_normalizes() -> None:
    payload = b'{"event":"x"}'
    verifier = WebhookVerifier(
        secret="s",
        signature_header="X-Signature",
        algorithm=SignatureAlgorithm.HMAC_SHA256,
    )
    listener = WebhookListener(
        provider="example",
        verifier=verifier,
        event_type_header="X-Event-Type",
    )
    headers = _signed_headers("s", payload)
    headers["X-Event-Type"] = "x"
    event = listener.handle(headers, payload)
    assert event.provider == "example"
    assert event.event_type == "x"
    assert event.payload == {"event": "x"}


def test_webhook_listener_raises_on_bad_signature() -> None:
    listener = WebhookListener(
        provider="example",
        verifier=WebhookVerifier(secret="s", signature_header="X-Signature"),
    )
    with pytest.raises(SignatureMismatchError):
        listener.handle({"X-Signature": "deadbeef"}, b"data")
    assert listener.try_handle({"X-Signature": "deadbeef"}, b"data") is None


def test_webhook_listener_falls_back_to_text_for_non_json() -> None:
    payload = b"not json"
    listener = WebhookListener(
        provider="example",
        verifier=WebhookVerifier(secret="s", signature_header="X-Signature"),
    )
    headers = _signed_headers("s", payload)
    event = listener.handle(headers, payload)
    assert event.payload == "not json"
