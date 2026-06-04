"""Xero Accounting API connector."""

# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.bearer import BearerTokenAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Helpers


def _format_amount(amount: Any, currency: Any) -> str:
    """Format a Xero numeric amount as ``"12.34 USD"``."""
    if amount is None:
        return ""
    try:
        amount_float = float(amount)
    except (TypeError, ValueError):
        return ""
    code = str(currency or "").upper()
    return f"{amount_float:.2f} {code}".strip()


# MARK: ToolSet


@toolset(prefix="xero")
class XeroToolSet:
    """A connector for the Xero Accounting API.

    Plug into an Agent with ``agent.add_toolset(XeroToolSet(access_token=...,
    tenant_id=...))`` and the agent can answer questions about contacts,
    invoices, bills, payments, and bank transactions.
    """

    metadata = ProviderMetadata(
        name="xero",
        display_name="Xero",
        version="0.1.0",
        description="Contacts, invoices, bills, payments, and bank transactions.",
        auth_modes=(AuthMode.OAUTH2_AUTH_CODE,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developer.xero.com/documentation/api/accounting/",
        homepage_url="https://www.xero.com/",
        tags=("accounting", "finance"),
    )

    def __init__(
        self,
        *,
        access_token: str,
        tenant_id: str,
        base_url: str = "https://api.xero.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not access_token or not tenant_id:
            raise ValueError("access_token and tenant_id are required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=BearerTokenAuth(access_token),
            transport=transport,
            default_headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Xero-Tenant-Id": tenant_id,
            },
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_connections(self) -> dict[str, Any]:
        """List Xero tenants this bearer token has access to.

        Returns a list of ``{"tenantId": ..., "tenantName": ...}``. Use
        this to discover the tenant ID to pass to other toolsets.
        """
        return cast("dict[str, Any]", self._client.get("/connections").json())

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_contacts(
        self,
        *,
        where: str | None = None,
        order: str | None = None,
        page: int = 1,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Xero contacts (customers and suppliers).

        Returns compact summaries with ``contact_ref``, name, email, status,
        and customer/supplier flags. Use ``where`` for Xero's filter syntax
        (e.g. ``'Name="Acme"'``). Raw Xero IDs are omitted unless
        ``include_ids=True``.
        """
        if page < 1:
            raise ValueError("page must be >= 1")
        params: dict[str, Any] = {"page": page}
        if where is not None:
            params["where"] = where
        if order is not None:
            params["order"] = order
        payload = cast(
            "dict[str, Any]",
            self._client.get(
                "/api.xro/2.0/Contacts",
                params=params,
            ).json(),
        )
        contacts_raw: object = payload.get("Contacts", [])
        contacts: list[Any] = (
            cast("list[Any]", contacts_raw) if isinstance(contacts_raw, list) else []
        )
        summaries: list[dict[str, Any]] = []
        for index, contact in enumerate(contacts, start=1):
            if not isinstance(contact, dict):
                continue
            contact = cast("dict[str, Any]", contact)
            summary: dict[str, Any] = {
                "contact_ref": f"contact_{index}",
                "name": contact.get("Name", ""),
                "email": contact.get("EmailAddress", ""),
                "status": contact.get("ContactStatus", ""),
                "is_customer": bool(contact.get("IsCustomer")),
                "is_supplier": bool(contact.get("IsSupplier")),
                "updated_at": contact.get("UpdatedDateUTC"),
            }
            if include_ids:
                summary["contact_id"] = contact.get("ContactID", "")
            summaries.append(summary)
        return {"contacts": summaries, "page": page}

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_contact(self, contact_id: str) -> dict[str, Any]:
        """Return one contact by Xero GUID."""
        if not contact_id:
            raise ValueError("contact_id must be a non-empty string")
        return cast(
            "dict[str, Any]",
            self._client.get(f"/api.xro/2.0/Contacts/{contact_id}").json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def upsert_contacts(self, contacts: list[dict[str, Any]]) -> dict[str, Any]:
        """Create or update one or more Xero contacts.

        Pass a list of Xero contact payloads. Returns the upserted contacts.
        """
        if not contacts:
            raise ValueError("contacts must be non-empty")
        return cast(
            "dict[str, Any]",
            self._client.post(
                "/api.xro/2.0/Contacts",
                json={"Contacts": contacts},
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_invoices(
        self,
        *,
        status: str | None = None,
        where: str | None = None,
        page: int = 1,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Xero invoices.

        Returns compact summaries with ``invoice_ref``, number, contact
        name, total/amount-due (formatted with currency), date, due date,
        and status. ``status`` accepts ``DRAFT``, ``SUBMITTED``,
        ``AUTHORISED``, ``PAID``, ``VOIDED``. Raw IDs are omitted unless
        ``include_ids=True``.
        """
        if page < 1:
            raise ValueError("page must be >= 1")
        params: dict[str, Any] = {"page": page}
        if status is not None:
            params["Statuses"] = status
        if where is not None:
            params["where"] = where
        payload = cast(
            "dict[str, Any]",
            self._client.get(
                "/api.xro/2.0/Invoices",
                params=params,
            ).json(),
        )
        invoices_raw: object = payload.get("Invoices", [])
        invoices: list[Any] = (
            cast("list[Any]", invoices_raw) if isinstance(invoices_raw, list) else []
        )
        summaries: list[dict[str, Any]] = []
        for index, invoice in enumerate(invoices, start=1):
            if not isinstance(invoice, dict):
                continue
            invoice = cast("dict[str, Any]", invoice)
            contact_raw: object = invoice.get("Contact", {})
            contact: dict[str, Any] = (
                cast("dict[str, Any]", contact_raw) if isinstance(contact_raw, dict) else {}
            )
            currency: Any = invoice.get("CurrencyCode") or ""
            summary: dict[str, Any] = {
                "invoice_ref": f"invoice_{index}",
                "number": invoice.get("InvoiceNumber", ""),
                "type": invoice.get("Type", ""),
                "contact_name": contact.get("Name", ""),
                "total": _format_amount(invoice.get("Total"), currency),
                "amount_due": _format_amount(invoice.get("AmountDue"), currency),
                "amount_paid": _format_amount(invoice.get("AmountPaid"), currency),
                "currency": str(currency).upper(),
                "date": invoice.get("DateString") or invoice.get("Date"),
                "due_date": invoice.get("DueDateString") or invoice.get("DueDate"),
                "status": invoice.get("Status", ""),
            }
            if include_ids:
                summary["invoice_id"] = invoice.get("InvoiceID", "")
                summary["contact_id"] = contact.get("ContactID", "")
            summaries.append(summary)
        return {"invoices": summaries, "page": page}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def upsert_invoices(self, invoices: list[dict[str, Any]]) -> dict[str, Any]:
        """Create or update invoices. Returns the upserted invoices."""
        if not invoices:
            raise ValueError("invoices must be non-empty")
        return cast(
            "dict[str, Any]",
            self._client.post(
                "/api.xro/2.0/Invoices",
                json={"Invoices": invoices},
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_payments(
        self,
        *,
        where: str | None = None,
        order: str | None = None,
        page: int = 1,
        include_ids: bool = False,
    ) -> dict[str, Any]:
        """List Xero payments.

        Returns compact summaries with ``payment_ref``, amount (formatted
        with currency), date, status, and references to the related invoice/
        contact. Raw IDs are omitted unless ``include_ids=True``.
        """
        if page < 1:
            raise ValueError("page must be >= 1")
        params: dict[str, Any] = {"page": page}
        if where is not None:
            params["where"] = where
        if order is not None:
            params["order"] = order
        payload = cast(
            "dict[str, Any]",
            self._client.get(
                "/api.xro/2.0/Payments",
                params=params,
            ).json(),
        )
        payments_raw: object = payload.get("Payments", [])
        payments: list[Any] = (
            cast("list[Any]", payments_raw) if isinstance(payments_raw, list) else []
        )
        summaries: list[dict[str, Any]] = []
        for index, payment in enumerate(payments, start=1):
            if not isinstance(payment, dict):
                continue
            payment = cast("dict[str, Any]", payment)
            invoice_raw: object = payment.get("Invoice", {})
            invoice: dict[str, Any] = (
                cast("dict[str, Any]", invoice_raw) if isinstance(invoice_raw, dict) else {}
            )
            account_raw: object = payment.get("Account", {})
            account: dict[str, Any] = (
                cast("dict[str, Any]", account_raw) if isinstance(account_raw, dict) else {}
            )
            currency: Any = invoice.get("CurrencyCode") or ""
            summary: dict[str, Any] = {
                "payment_ref": f"payment_{index}",
                "amount": _format_amount(payment.get("Amount"), currency),
                "date": payment.get("DateString") or payment.get("Date"),
                "status": payment.get("Status", ""),
                "invoice_number": invoice.get("InvoiceNumber", ""),
                "account_name": account.get("Name", ""),
            }
            if include_ids:
                summary["payment_id"] = payment.get("PaymentID", "")
                summary["invoice_id"] = invoice.get("InvoiceID", "")
                summary["account_id"] = account.get("AccountID", "")
            summaries.append(summary)
        return {"payments": summaries, "page": page}

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def upsert_payments(self, payments: list[dict[str, Any]]) -> dict[str, Any]:
        """Create or update payments. Returns the upserted payments."""
        if not payments:
            raise ValueError("payments must be non-empty")
        return cast(
            "dict[str, Any]",
            self._client.post(
                "/api.xro/2.0/Payments",
                json={"Payments": payments},
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_bank_transactions(
        self,
        *,
        where: str | None = None,
        page: int = 1,
    ) -> dict[str, Any]:
        """List bank transactions in the configured Xero tenant.

        Returns the raw Xero response (``BankTransactions``). Use ``where``
        for the standard Xero filter syntax.
        """
        if page < 1:
            raise ValueError("page must be >= 1")
        params: dict[str, Any] = {"page": page}
        if where is not None:
            params["where"] = where
        return cast(
            "dict[str, Any]",
            self._client.get(
                "/api.xro/2.0/BankTransactions",
                params=params,
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_accounts(self, *, where: str | None = None) -> dict[str, Any]:
        """List the chart of accounts. Returns the raw Xero response."""
        params: dict[str, Any] = {}
        if where is not None:
            params["where"] = where
        return cast(
            "dict[str, Any]",
            self._client.get(
                "/api.xro/2.0/Accounts",
                params=params or None,
            ).json(),
        )

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_organisation(self) -> dict[str, Any]:
        """Return the organisation profile (name, currency, country, etc.)."""
        return cast("dict[str, Any]", self._client.get("/api.xro/2.0/Organisation").json())
