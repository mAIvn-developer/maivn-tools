"""Ramp Developer API connector."""

# pyright: strict

from __future__ import annotations

import uuid
from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Helpers


def _format_amount(amount: Any, currency: Any) -> str:
    """Format a Ramp transaction amount as ``"12.34 USD"``."""
    if amount is None:
        return ""
    try:
        amount_float = float(amount)
    except (TypeError, ValueError):
        return ""
    code = str(currency or "").upper()
    return f"{amount_float:.2f} {code}".strip()


def _coerce_id(candidate: Any) -> str:
    """Resolve a raw Ramp ID from a dict/string/list."""
    if isinstance(candidate, str) and candidate:
        return candidate
    if isinstance(candidate, dict):
        candidate_dict = cast("dict[str, Any]", candidate)
        for key in ("card_id", "transaction_id", "id"):
            value: Any = candidate_dict.get(key)
            if isinstance(value, str) and value:
                return value
        for nested in candidate_dict.values():
            if isinstance(nested, dict | list | tuple):
                try:
                    return _coerce_id(nested)
                except ValueError:
                    continue
    if isinstance(candidate, list | tuple):
        candidate_seq = cast("list[Any] | tuple[Any, ...]", candidate)
        for item in candidate_seq:
            try:
                return _coerce_id(item)
            except ValueError:
                continue
    raise ValueError("could not resolve a Ramp ID from the given input")


# MARK: ToolSet


@toolset(prefix="ramp")
class RampToolSet:
    """A connector for the Ramp Developer API v1.

    Plug into an Agent with ``agent.add_toolset(RampToolSet(access_token=...))``
    and the agent can answer questions about transactions, cards,
    reimbursements, vendors, and users.
    """

    metadata = ProviderMetadata(
        name="ramp",
        display_name="Ramp",
        version="0.1.0",
        description="Cards, transactions, reimbursements, vendors, and users.",
        auth_modes=(AuthMode.OAUTH2_CLIENT_CREDENTIALS, AuthMode.BEARER),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://docs.ramp.com/developer-api/v1/",
        homepage_url="https://ramp.com/",
        tags=("finance", "expense", "cards"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        base_url: str = "https://api.ramp.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(access_token),
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
    def list_transactions(
        self,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
        page_size: int = 25,
        start: str | None = None,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Ramp card transactions.

        Returns compact summaries with ``transaction_ref``, merchant name,
        amount (formatted with currency), date, card holder, and state.
        Raw transaction/card IDs are omitted unless ``include_ids=True``.
        """
        if page_size < 2 or page_size > 100:
            raise ValueError("page_size must be between 2 and 100")
        params: dict[str, Any] = {"page_size": page_size}
        if from_date is not None:
            params["from_date"] = from_date
        if to_date is not None:
            params["to_date"] = to_date
        if start is not None:
            params["start"] = start
        payload: object = self._client.get(
            "/developer/v1/transactions",
            params=params,
        ).json()
        payload_dict: dict[str, Any] = (
            cast("dict[str, Any]", payload) if isinstance(payload, dict) else {}
        )
        items: Any = payload_dict.get("data", []) if isinstance(payload, dict) else []
        summaries: list[dict[str, Any]] = []
        for index, txn in enumerate(items, start=1):
            if not isinstance(txn, dict):
                continue
            txn_dict = cast("dict[str, Any]", txn)
            raw_holder = txn_dict.get("card_holder")
            card_holder: dict[str, Any] = (
                cast("dict[str, Any]", raw_holder) if isinstance(raw_holder, dict) else {}
            )
            holder_name = (
                f"{card_holder.get('first_name', '')} {card_holder.get('last_name', '')}".strip()
            )
            summary: dict[str, Any] = {
                "transaction_ref": f"transaction_{index}",
                "merchant": txn_dict.get("merchant_name")
                or txn_dict.get("merchant_descriptor")
                or "",
                "amount": _format_amount(txn_dict.get("amount"), txn_dict.get("currency_code")),
                "date": txn_dict.get("user_transaction_time") or txn_dict.get("settlement_date"),
                "card_holder": holder_name,
                "state": txn_dict.get("state", ""),
                "category": txn_dict.get("sk_category_name", ""),
            }
            if include_ids:
                summary["transaction_id"] = txn_dict.get("id", "")
                summary["card_id"] = txn_dict.get("card_id", "")
            summaries.append(summary)
        return {
            "transactions": summaries,
            "page": payload_dict.get("page") if isinstance(payload, dict) else None,
        }

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_transaction(self, transaction_id: str) -> dict[str, Any]:
        """Return one Ramp transaction by ID."""
        if not transaction_id:
            raise ValueError("transaction_id must be a non-empty string")
        return cast(
            "dict[str, Any]",
            self._client.get(
                f"/developer/v1/transactions/{transaction_id}",
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_cards(self, *, page_size: int = 25) -> dict[str, Any]:
        """List Ramp cards. Returns the raw paginated response."""
        if page_size < 2 or page_size > 100:
            raise ValueError("page_size must be between 2 and 100")
        return cast(
            "dict[str, Any]",
            self._client.get(
                "/developer/v1/cards",
                params={"page_size": page_size},
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_card(self, payload: dict[str, Any], *, card_type: str = "virtual") -> dict[str, Any]:
        """Issue a new Ramp card (deferred / asynchronous).

        Ramp card creation is async: this posts to
        ``/developer/v1/cards/deferred/virtual`` (or ``.../physical`` when
        ``card_type='physical'``) and returns the ``{id}`` of a *deferred
        task*, NOT a card resource. The created card must be fetched via the
        deferred-task result once the task completes.

        ``payload`` is the Ramp card-creation body and must include
        ``user_id`` plus one of ``spending_restrictions`` or
        ``card_program_id``. An ``idempotency_key`` is generated (a random
        UUID) when not supplied by the caller.
        """
        if not payload:
            raise ValueError("payload must be non-empty")
        if card_type not in ("virtual", "physical"):
            raise ValueError("card_type must be 'virtual' or 'physical'")
        body = dict(payload)
        if not body.get("user_id"):
            raise ValueError("payload must include 'user_id'")
        if not body.get("spending_restrictions") and not body.get("card_program_id"):
            raise ValueError(
                "payload must include one of 'spending_restrictions' or 'card_program_id'"
            )
        body.setdefault("idempotency_key", str(uuid.uuid4()))
        return cast(
            "dict[str, Any]",
            self._client.post(f"/developer/v1/cards/deferred/{card_type}", json=body).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def terminate_card(self, card_id: Any) -> dict[str, Any]:
        """Terminate a Ramp card (deferred / asynchronous). Destructive — irreversible.

        ``card_id`` accepts a raw ID or a dict from :meth:`list_cards`
        (with ``include_ids=True``). Confirm with the user before calling.

        Termination is async: this posts to
        ``/developer/v1/cards/{card_id}/deferred/termination`` with a generated
        ``idempotency_key`` and returns the ``{id}`` of a *deferred task*, not a
        synchronous termination confirmation. Poll the deferred task to confirm
        the card was terminated.
        """
        resolved = _coerce_id(card_id)
        return cast(
            "dict[str, Any]",
            self._client.post(
                f"/developer/v1/cards/{resolved}/deferred/termination",
                json={"idempotency_key": str(uuid.uuid4())},
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_users(self, *, page_size: int = 25) -> dict[str, Any]:
        """List Ramp users. Returns the raw paginated response."""
        if page_size < 2 or page_size > 100:
            raise ValueError("page_size must be between 2 and 100")
        return cast(
            "dict[str, Any]",
            self._client.get(
                "/developer/v1/users",
                params={"page_size": page_size},
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_reimbursements(self, *, page_size: int = 25) -> dict[str, Any]:
        """List reimbursement requests. Returns the raw paginated response."""
        if page_size < 2 or page_size > 100:
            raise ValueError("page_size must be between 2 and 100")
        return cast(
            "dict[str, Any]",
            self._client.get(
                "/developer/v1/reimbursements",
                params={"page_size": page_size},
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_vendors(self, *, page_size: int = 25) -> dict[str, Any]:
        """List vendors. Returns the raw paginated response."""
        if page_size < 2 or page_size > 100:
            raise ValueError("page_size must be between 2 and 100")
        return cast(
            "dict[str, Any]",
            self._client.get(
                "/developer/v1/vendors",
                params={"page_size": page_size},
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_departments(self) -> dict[str, Any]:
        """List departments. Returns the raw response."""
        return cast("dict[str, Any]", self._client.get("/developer/v1/departments").json())
