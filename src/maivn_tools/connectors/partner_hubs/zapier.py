"""Zapier connector.

Zapier exposes one supported programmatic interface relevant here:

* The classic webhook trigger / catch URL that customers can configure in
  a Zap. This connector lets an agent POST arbitrary payloads to such a
  webhook URL, which is the most common integration pattern.

The former Natural Language Actions / AI Actions REST API
(``nla.zapier.com/api/v1/exposed/``) has been **sunset** by Zapier as of
May 29, 2026 — after that date API requests no longer go through, and the
first-party docs pages now 404. Its documented successor for programmatic
action discovery and execution is Zapier MCP (``mcp.zapier.com`` /
``github.com/zapier/zapier-mcp``), which is a Model Context Protocol
server rather than a REST surface this connector can shim. The dead
``run_action`` / ``list_actions`` REST tools and the NLA client have
therefore been removed; only the unaffected webhook tools remain. See
https://nla.zapier.com/sunset/ for the vendor sunset notice.

Unlike the other partner-hub connectors, Zapier is a **builder-style**
connector because the tool names are dynamic (one ``trigger_<name>`` per
configured webhook URL). It exposes a classic ``tools()`` method rather
than being decorated with ``@toolset``; ``register_connector`` dispatches
to that path automatically.
"""

# pyright: strict

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Connector


class ZapierConnector:
    """A connector that posts payloads to Zapier webhook catch URLs.

    Args:
        webhook_urls: Mapping of logical name to Zapier webhook URL. Each
            entry becomes a callable ``trigger_<name>`` tool.
        transport: Optional :class:`HttpTransport` override.
    """

    metadata = ProviderMetadata(
        name="zapier",
        display_name="Zapier",
        version="0.1.0",
        description="Trigger Zapier webhooks.",
        auth_modes=(AuthMode.NONE,),
        scopes={},
        capabilities=frozenset({ProviderCapability.WRITE}),
        documentation_url="https://platform.zapier.com",
        homepage_url="https://zapier.com",
        tags=("partner", "automation"),
    )

    def __init__(
        self,
        *,
        webhook_urls: dict[str, str] | None = None,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        self.connection = connection
        self._webhook_urls = dict(webhook_urls or {})
        self._webhook_client = HttpClient(transport=transport)

    def tools(self) -> list[Any]:
        out: list[Any] = []
        for name in self._webhook_urls:
            out.append(self._build_webhook_tool(name))
        return out

    def _build_webhook_tool(self, name: str) -> Callable[..., dict[str, Any]]:
        url = self._webhook_urls[name]

        def trigger(payload: dict[str, Any] | None = None) -> dict[str, Any]:
            # Real docstring is set below via ``trigger.__doc__`` so it can
            # interpolate the per-webhook ``name`` without using an f-string
            # docstring (which Python treats as a joined string, not a real
            # ``__doc__``).
            body = payload or {}
            response = self._webhook_client.post(url, json=body)
            return {"status": response.status, "url": url, "delivered": True}

        trigger.__name__ = f"trigger_{name}"
        trigger.__qualname__ = trigger.__name__
        trigger.__doc__ = (
            f"Trigger the {name!r} Zapier webhook by POSTing the payload.\n\n"
            f'Returns ``{{"status": <http_status>, "url": <webhook_url>, '
            f'"delivered": True}}``. ``payload`` is the JSON body sent to '
            f"the Zap; pass ``None`` to send an empty object. Use this when "
            f"the user asks to fire the {name!r} Zap. The Zap definition "
            f"itself lives in Zapier — this tool just delivers the payload."
        )
        _mark_tool(trigger, PermissionFlag.WRITE)
        return trigger


# MARK: Helpers


def _mark_tool(tool: Callable[..., Any], flag: PermissionFlag) -> None:
    """Attach permission metadata to a dynamically built tool callable.

    Used only by the builder-style Zapier connector; toolset-based
    connectors use ``@toolify`` instead and don't need this.
    """
    setattr(tool, "permissions", PermissionSet(flag))  # noqa: B010
    setattr(tool, "destructive", False)  # noqa: B010
