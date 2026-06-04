"""QuickBooks Online v3 connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: - Helpers


def _format_amount(amount: object, currency: object) -> str:
    """Format a QBO amount (float) as ``"12.34 USD"``."""
    if amount is None:
        return ""
    try:
        amount_float = float(cast("Any", amount))
    except (TypeError, ValueError):
        return ""
    code = str(currency or "").upper()
    return f"{amount_float:.2f} {code}".strip()


def _query_rows(payload: object, entity: str) -> list[Any]:
    """Pull the rows for ``entity`` from a QBO QueryResponse payload."""
    if not isinstance(payload, dict):
        return []
    qr: object = cast("dict[str, Any]", payload).get("QueryResponse")
    if not isinstance(qr, dict):
        return []
    rows: object = cast("dict[str, Any]", qr).get(entity)
    if isinstance(rows, list):
        return cast("list[Any]", rows)
    return []


def _entity_currency(row: dict[str, Any]) -> str:
    raw_ref: object = row.get("CurrencyRef")
    currency_ref: dict[str, Any] = (
        cast("dict[str, Any]", raw_ref) if isinstance(raw_ref, dict) else {}
    )
    return cast("str", currency_ref.get("value", "") if currency_ref else "")


@toolset(prefix="qbo")
class QuickBooksToolSet:
    """A connector for the QuickBooks Online v3 API.

    Plug into an Agent with ``agent.add_toolset(QuickBooksToolSet(
    access_token=..., realm_id=...))`` and the agent can answer
    questions about customers, invoices, bills, and payments.

    Args:
        access_token: OAuth bearer token.
        realm_id: QuickBooks company ID.
        base_url: Production (default) or sandbox URL.
        minor_version: Optional ``minorversion`` query parameter.
    """

    metadata = ProviderMetadata(
        name="quickbooks_online",
        display_name="QuickBooks Online",
        version="0.1.0",
        description="Customers, invoices, bills, vendors, items, payments, and queries.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developer.intuit.com/app/developer/qbo/docs/api/accounting",
        homepage_url="https://quickbooks.intuit.com/online/",
        tags=("accounting", "finance"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        realm_id: str,
        base_url: str = "https://quickbooks.api.intuit.com",
        minor_version: int | None = None,
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_token or not realm_id:
            raise ValueError("access_token and realm_id are required")
        self.connection = connection
        self._realm_id = realm_id
        self._minor_version = minor_version
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

    def _path(self, suffix: str) -> str:
        return f"/v3/company/{self._realm_id}{suffix}"

    def _params(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if self._minor_version is not None:
            params["minorversion"] = self._minor_version
        if extra:
            params.update(extra)
        return params

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def query(self, query: str) -> dict[str, Any]:
        """Run a SQL-like QBO query (read-only).

        Returns the raw QBO response. ``query`` follows the QBO syntax
        (e.g. ``"SELECT * FROM Customer WHERE DisplayName LIKE 'Acme%'"``).
        Use the convenience ``list_*`` tools first when you can.
        """
        if not query:
            raise ValueError("query must be a non-empty string")
        return self._client.get(
            self._path("/query"),
            params=self._params({"query": query}),
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_entity(self, entity: str, entity_id: str) -> dict[str, Any]:
        """Return one entity by ID. ``entity`` is e.g. ``"customer"``."""
        if not entity or not entity_id:
            raise ValueError("entity and entity_id must be non-empty")
        return self._client.get(
            self._path(f"/{entity.lower()}/{entity_id}"),
            params=self._params(),
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_entity(self, entity: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Create an entity. Returns the new entity wrapped in QBO envelope."""
        if not entity or not payload:
            raise ValueError("entity and payload must be non-empty")
        return self._client.post(
            self._path(f"/{entity.lower()}"),
            params=self._params(),
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def update_entity(self, entity: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Update an entity (sparse update; payload must include Id+SyncToken).

        Pass ``{"Id": "1", "SyncToken": "0", ...fields}``. QBO requires
        the latest ``SyncToken`` to detect conflicts.
        """
        if not entity or not payload.get("Id") or not payload.get("SyncToken"):
            raise ValueError("entity and payload Id+SyncToken are required")
        return self._client.post(
            self._path(f"/{entity.lower()}"),
            params=self._params({"operation": "update"}),
            json=payload,
        ).json()

    @toolify(permissions=PermissionSet(PermissionFlag.DELETE), destructive=True)
    def delete_entity(self, entity: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Delete or void an entity. Destructive — confirm with the user.

        Payload must include ``Id`` and ``SyncToken``.
        """
        if not entity or not payload.get("Id") or not payload.get("SyncToken"):
            raise ValueError("entity and payload Id+SyncToken are required")
        return self._client.post(
            self._path(f"/{entity.lower()}"),
            params=self._params({"operation": "delete"}),
            json=payload,
        ).json()

    # MARK: - Convenience shortcuts

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_customers(
        self,
        *,
        max_results: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List QuickBooks customers via a QBO query.

        Returns compact summaries with ``customer_ref``, display name,
        company name, email, balance (formatted with currency), and
        active flag. Raw QBO IDs and SyncTokens are omitted unless
        ``include_ids=True`` (needed for follow-up updates).
        """
        if max_results < 1 or max_results > 1000:
            raise ValueError("max_results must be between 1 and 1000")
        payload = self.query(f"SELECT * FROM Customer MAXRESULTS {max_results}")
        rows = _query_rows(payload, "Customer")
        summaries: list[dict[str, Any]] = []
        for index, raw_customer in enumerate(rows, start=1):
            if not isinstance(raw_customer, dict):
                continue
            customer = cast("dict[str, Any]", raw_customer)
            raw_email: object = customer.get("PrimaryEmailAddr")
            email: dict[str, Any] = (
                cast("dict[str, Any]", raw_email) if isinstance(raw_email, dict) else {}
            )
            raw_phone: object = customer.get("PrimaryPhone")
            phone: dict[str, Any] = (
                cast("dict[str, Any]", raw_phone) if isinstance(raw_phone, dict) else {}
            )
            currency = _entity_currency(customer)
            summary: dict[str, Any] = {
                "customer_ref": f"customer_{index}",
                "display_name": customer.get("DisplayName", ""),
                "company": customer.get("CompanyName", ""),
                "email": email.get("Address", ""),
                "phone": phone.get("FreeFormNumber", ""),
                "balance": _format_amount(customer.get("Balance"), currency),
                "active": bool(customer.get("Active", True)),
            }
            if include_ids:
                summary["customer_id"] = customer.get("Id", "")
                summary["sync_token"] = customer.get("SyncToken", "")
            summaries.append(summary)
        return {"customers": summaries, "max_results": max_results}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_invoices(
        self,
        *,
        max_results: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List QuickBooks invoices via query.

        Returns compact summaries with ``invoice_ref``, doc number,
        customer name, total/balance (formatted with currency), due date,
        and status. Raw IDs and SyncTokens are omitted unless
        ``include_ids=True``.
        """
        if max_results < 1 or max_results > 1000:
            raise ValueError("max_results must be between 1 and 1000")
        payload = self.query(f"SELECT * FROM Invoice MAXRESULTS {max_results}")
        rows = _query_rows(payload, "Invoice")
        summaries: list[dict[str, Any]] = []
        for index, raw_invoice in enumerate(rows, start=1):
            if not isinstance(raw_invoice, dict):
                continue
            invoice = cast("dict[str, Any]", raw_invoice)
            raw_customer_ref: object = invoice.get("CustomerRef")
            customer_ref: dict[str, Any] = (
                cast("dict[str, Any]", raw_customer_ref)
                if isinstance(raw_customer_ref, dict)
                else {}
            )
            currency = _entity_currency(invoice)
            balance: object = invoice.get("Balance")
            paid = balance is not None and float(cast("Any", balance) or 0) == 0.0
            summary: dict[str, Any] = {
                "invoice_ref": f"invoice_{index}",
                "doc_number": invoice.get("DocNumber", ""),
                "customer_name": customer_ref.get("name", ""),
                "total": _format_amount(invoice.get("TotalAmt"), currency),
                "balance": _format_amount(balance, currency),
                "txn_date": invoice.get("TxnDate"),
                "due_date": invoice.get("DueDate"),
                "status": "paid" if paid else "open",
            }
            if include_ids:
                summary["invoice_id"] = invoice.get("Id", "")
                summary["sync_token"] = invoice.get("SyncToken", "")
                summary["customer_id"] = customer_ref.get("value", "")
            summaries.append(summary)
        return {"invoices": summaries, "max_results": max_results}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_bills(
        self,
        *,
        max_results: int = 25,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List QuickBooks bills via query.

        Returns compact summaries with ``bill_ref``, vendor name, total/
        balance (formatted with currency), txn/due dates, and status. Raw
        IDs and SyncTokens are omitted unless ``include_ids=True``.
        """
        if max_results < 1 or max_results > 1000:
            raise ValueError("max_results must be between 1 and 1000")
        payload = self.query(f"SELECT * FROM Bill MAXRESULTS {max_results}")
        rows = _query_rows(payload, "Bill")
        summaries: list[dict[str, Any]] = []
        for index, raw_bill in enumerate(rows, start=1):
            if not isinstance(raw_bill, dict):
                continue
            bill = cast("dict[str, Any]", raw_bill)
            raw_vendor_ref: object = bill.get("VendorRef")
            vendor_ref: dict[str, Any] = (
                cast("dict[str, Any]", raw_vendor_ref) if isinstance(raw_vendor_ref, dict) else {}
            )
            currency = _entity_currency(bill)
            balance: object = bill.get("Balance")
            paid = balance is not None and float(cast("Any", balance) or 0) == 0.0
            summary: dict[str, Any] = {
                "bill_ref": f"bill_{index}",
                "doc_number": bill.get("DocNumber", ""),
                "vendor_name": vendor_ref.get("name", ""),
                "total": _format_amount(bill.get("TotalAmt"), currency),
                "balance": _format_amount(balance, currency),
                "txn_date": bill.get("TxnDate"),
                "due_date": bill.get("DueDate"),
                "status": "paid" if paid else "open",
            }
            if include_ids:
                summary["bill_id"] = bill.get("Id", "")
                summary["sync_token"] = bill.get("SyncToken", "")
                summary["vendor_id"] = vendor_ref.get("value", "")
            summaries.append(summary)
        return {"bills": summaries, "max_results": max_results}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_invoice(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a QuickBooks invoice. Returns the new invoice envelope."""
        return self.create_entity("invoice", payload)

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_payment(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a QuickBooks payment record. Returns the new payment envelope."""
        return self.create_entity("payment", payload)

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_company_info(self) -> dict[str, Any]:
        """Return the QuickBooks company profile."""
        return self._client.get(
            self._path(f"/companyinfo/{self._realm_id}"),
            params=self._params(),
        ).json()
