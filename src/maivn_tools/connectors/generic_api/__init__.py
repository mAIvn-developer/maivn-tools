"""Generic API adapters: HTTP, OpenAPI, GraphQL, webhooks."""

from __future__ import annotations

from .graphql import GraphQLConnector, GraphQLOperation
from .http import GenericHttpConnector, HttpEndpoint
from .openapi import OpenAPIConnector, OpenAPIOperation
from .webhooks import NormalizedWebhookEvent, WebhookListener

__all__ = [
    "GenericHttpConnector",
    "GraphQLConnector",
    "GraphQLOperation",
    "HttpEndpoint",
    "NormalizedWebhookEvent",
    "OpenAPIConnector",
    "OpenAPIOperation",
    "WebhookListener",
]
