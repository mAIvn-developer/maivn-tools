"""Bill.com (Bill) API v3 connector."""
# pyright: strict

from __future__ import annotations

from typing import Any, cast

from maivn import toolify, toolset

from ...auth.api_key import ApiKeyAuth
from ...core.connections import ConnectionMetadata
from ...core.metadata import AuthMode, ProviderCapability, ProviderMetadata
from ...core.permissions import PermissionFlag, PermissionSet
from ...runtime.http import HttpClient, HttpTransport

# MARK: Constants

_API_PREFIX = "/connect/v3"


# MARK: Helpers


def _format_amount(amount: Any, currency: Any) -> str:
    """Format a Bill amount as ``"12.34 USD"``."""
    if amount is None:
        return ""
    try:
        amount_float = float(amount)
    except (TypeError, ValueError):
        return ""
    code = str(currency or "USD").upper()
    return f"{amount_float:.2f} {code}".strip()


# MARK: ToolSet


@toolset(prefix="bill")
class BillToolSet:
    """A connector for the Bill (Bill.com) API v3.

    Plug into an Agent with ``agent.add_toolset(BillToolSet(api_key=...))``
    and the agent can answer questions about vendors, bills, invoices,
    payments, and customers.

    Args:
        api_key: Session token (``sessionId``) issued after authenticating to
            the ``/connect/v3/login`` endpoint. This toolset assumes the caller
            already has a valid session token. Sent in the ``sessionId`` header.
        dev_key: Developer key from your BILL developer account. Required on
            every request and sent in the ``devKey`` header alongside the
            session token.
        base_url: Gateway host. Defaults to the production gateway
            (``https://gateway.prod.bill.com``). For sandbox testing use
            ``https://gateway.stage.bill.com``.
    """

    metadata = ProviderMetadata(
        name="bill",
        display_name="Bill (Bill.com)",
        version="0.1.0",
        description="Vendors, bills, invoices, payments, and customers.",
        auth_modes=(AuthMode.API_KEY,),
        capabilities=frozenset({ProviderCapability.READ, ProviderCapability.WRITE}),
        documentation_url="https://developer.bill.com/reference/intro",
        homepage_url="https://www.bill.com/",
        tags=("payments", "ap", "ar"),
    )

    def __init__(
        self,
        *,
        api_key: str,
        dev_key: str,
        base_url: str = "https://gateway.prod.bill.com",
        transport: HttpTransport | None = None,
        connection: ConnectionMetadata | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        if not dev_key:
            raise ValueError("dev_key is required")
        self.connection = connection
        self._client = HttpClient(
            base_url=base_url.rstrip("/"),
            auth=ApiKeyAuth(api_key, header="sessionId"),
            transport=transport,
            default_headers={"Accept": "application/json", "devKey": dev_key},
        )

    @property
    def client(self) -> HttpClient:
        return self._client

    def _results(self, payload: Any) -> list[Any]:
        if not isinstance(payload, dict):
            return []
        mapping = cast(dict[str, Any], payload)
        for key in ("results", "data"):
            value: Any = mapping.get(key)
            if isinstance(value, list):
                return cast(list[Any], value)
        return []

    @staticmethod
    def _next_page(payload: Any) -> Any:
        if not isinstance(payload, dict):
            return None
        return cast(dict[str, Any], payload).get("nextPage")

    @staticmethod
    def _list_params(max_results: int, page: str | None) -> dict[str, Any]:
        params: dict[str, Any] = {"max": max_results}
        if page:
            params["page"] = page
        return params

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_vendors(
        self,
        *,
        max_results: int = 25,
        include_ids: bool = False,
        page: str | None = None,
    ) -> dict[str, Any]:
        """List Bill vendors.

        Returns compact summaries with ``vendor_ref``, name, email, phone,
        and active flag. Raw Bill IDs are omitted unless
        ``include_ids=True``. Pass the ``next_page`` cursor from a prior
        response as ``page`` to fetch the following page.
        """
        if max_results < 1 or max_results > 200:
            raise ValueError("max_results must be between 1 and 200")
        payload = self._client.get(
            f"{_API_PREFIX}/vendors",
            params=self._list_params(max_results, page),
        ).json()
        rows = self._results(payload)
        summaries: list[dict[str, Any]] = []
        for index, vendor in enumerate(rows, start=1):
            if not isinstance(vendor, dict):
                continue
            row = cast(dict[str, Any], vendor)
            summary: dict[str, Any] = {
                "vendor_ref": f"vendor_{index}",
                "name": row.get("name", ""),
                "email": row.get("email", ""),
                "phone": row.get("phone", ""),
                "active": row.get("isActive", True),
            }
            if include_ids:
                summary["vendor_id"] = row.get("id", "")
            summaries.append(summary)
        return {
            "vendors": summaries,
            "next_page": self._next_page(payload),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_vendor(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a Bill vendor. Returns the new vendor resource."""
        if not payload:
            raise ValueError("payload must be non-empty")
        return self._client.post(f"{_API_PREFIX}/vendors", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def get_vendor(self, vendor_id: str) -> dict[str, Any]:
        """Return one Bill vendor by ID."""
        if not vendor_id:
            raise ValueError("vendor_id must be a non-empty string")
        return self._client.get(f"{_API_PREFIX}/vendors/{vendor_id}").json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_bills(
        self,
        *,
        max_results: int = 25,
        include_ids: bool = False,
        page: str | None = None,
    ) -> dict[str, Any]:
        """List Bill AP bills.

        Returns compact summaries with ``bill_ref``, vendor reference,
        amount/balance (formatted with currency), invoice number, due
        date, and status. Raw Bill IDs are omitted unless
        ``include_ids=True``. Pass the ``next_page`` cursor from a prior
        response as ``page`` to fetch the following page.
        """
        if max_results < 1 or max_results > 200:
            raise ValueError("max_results must be between 1 and 200")
        payload = self._client.get(
            f"{_API_PREFIX}/bills",
            params=self._list_params(max_results, page),
        ).json()
        rows = self._results(payload)
        summaries: list[dict[str, Any]] = []
        for index, bill in enumerate(rows, start=1):
            if not isinstance(bill, dict):
                continue
            row = cast(dict[str, Any], bill)
            summary: dict[str, Any] = {
                "bill_ref": f"bill_{index}",
                "invoice_number": row.get("invoiceNumber", ""),
                "amount": _format_amount(row.get("amount"), row.get("currency")),
                "balance": _format_amount(row.get("balance"), row.get("currency")),
                "due_date": row.get("dueDate"),
                "invoice_date": row.get("invoiceDate"),
                "approval_status": row.get("approvalStatus", ""),
                "payment_status": row.get("paymentStatus", ""),
            }
            if include_ids:
                summary["bill_id"] = row.get("id", "")
                summary["vendor_id"] = row.get("vendorId", "")
            summaries.append(summary)
        return {
            "bills": summaries,
            "next_page": self._next_page(payload),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_bill(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a Bill AP bill. Returns the new bill resource."""
        if not payload:
            raise ValueError("payload must be non-empty")
        return self._client.post(f"{_API_PREFIX}/bills", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_invoices(
        self,
        *,
        max_results: int = 25,
        include_ids: bool = False,
        page: str | None = None,
    ) -> dict[str, Any]:
        """List Bill AR invoices.

        Returns compact summaries with ``invoice_ref``, customer reference,
        amount (formatted with currency), invoice number, due date, and
        status. Raw Bill IDs are omitted unless ``include_ids=True``. Pass
        the ``next_page`` cursor from a prior response as ``page`` to fetch
        the following page.
        """
        if max_results < 1 or max_results > 200:
            raise ValueError("max_results must be between 1 and 200")
        payload = self._client.get(
            f"{_API_PREFIX}/invoices",
            params=self._list_params(max_results, page),
        ).json()
        rows = self._results(payload)
        summaries: list[dict[str, Any]] = []
        for index, invoice in enumerate(rows, start=1):
            if not isinstance(invoice, dict):
                continue
            row = cast(dict[str, Any], invoice)
            summary: dict[str, Any] = {
                "invoice_ref": f"invoice_{index}",
                "invoice_number": row.get("invoiceNumber", ""),
                "amount": _format_amount(row.get("amount"), row.get("currency")),
                "balance": _format_amount(row.get("amountDue"), row.get("currency")),
                "invoice_date": row.get("invoiceDate"),
                "due_date": row.get("dueDate"),
                "status": row.get("status", ""),
            }
            if include_ids:
                summary["invoice_id"] = row.get("id", "")
                summary["customer_id"] = row.get("customerId", "")
            summaries.append(summary)
        return {
            "invoices": summaries,
            "next_page": self._next_page(payload),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_invoice(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a Bill AR invoice. Returns the new invoice resource."""
        if not payload:
            raise ValueError("payload must be non-empty")
        return self._client.post(f"{_API_PREFIX}/invoices", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_payments(
        self,
        *,
        max_results: int = 25,
        include_ids: bool = False,
        page: str | None = None,
    ) -> dict[str, Any]:
        """List sent payments.

        Returns compact summaries with ``payment_ref``, amount (formatted
        with currency), payment date, status, and the related bill/vendor
        references. Raw Bill IDs are omitted unless ``include_ids=True``.
        Pass the ``next_page`` cursor from a prior response as ``page`` to
        fetch the following page.
        """
        if max_results < 1 or max_results > 200:
            raise ValueError("max_results must be between 1 and 200")
        payload = self._client.get(
            f"{_API_PREFIX}/payments",
            params=self._list_params(max_results, page),
        ).json()
        rows = self._results(payload)
        summaries: list[dict[str, Any]] = []
        for index, payment in enumerate(rows, start=1):
            if not isinstance(payment, dict):
                continue
            row = cast(dict[str, Any], payment)
            summary: dict[str, Any] = {
                "payment_ref": f"payment_{index}",
                "amount": _format_amount(row.get("amount"), row.get("currency")),
                "payment_date": row.get("processDate") or row.get("paymentDate"),
                "status": row.get("status", ""),
                "method": row.get("paymentMethod") or row.get("method", ""),
            }
            if include_ids:
                summary["payment_id"] = row.get("id", "")
                summary["vendor_id"] = row.get("vendorId", "")
                summary["bill_id"] = row.get("billId", "")
            summaries.append(summary)
        return {
            "payments": summaries,
            "next_page": self._next_page(payload),
        }

    @toolify(permissions=PermissionSet(PermissionFlag.WRITE))
    def create_payment(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a payment. Returns the new payment resource."""
        if not payload:
            raise ValueError("payload must be non-empty")
        return self._client.post(f"{_API_PREFIX}/payments", json=payload).json()

    @toolify(permissions=PermissionSet(PermissionFlag.READ))
    def list_customers(
        self,
        *,
        max_results: int = 25,
        include_ids: bool = False,
        page: str | None = None,
    ) -> dict[str, Any]:
        """List Bill customers.

        Returns compact summaries with ``customer_ref``, name, email,
        balance, and active flag. Raw Bill IDs are omitted unless
        ``include_ids=True``. Pass the ``next_page`` cursor from a prior
        response as ``page`` to fetch the following page.
        """
        if max_results < 1 or max_results > 200:
            raise ValueError("max_results must be between 1 and 200")
        payload = self._client.get(
            f"{_API_PREFIX}/customers",
            params=self._list_params(max_results, page),
        ).json()
        rows = self._results(payload)
        summaries: list[dict[str, Any]] = []
        for index, customer in enumerate(rows, start=1):
            if not isinstance(customer, dict):
                continue
            row = cast(dict[str, Any], customer)
            summary: dict[str, Any] = {
                "customer_ref": f"customer_{index}",
                "name": row.get("name", ""),
                "email": row.get("email", ""),
                "phone": row.get("phone", ""),
                "balance": _format_amount(row.get("balance"), row.get("currency")),
                "active": row.get("isActive", True),
            }
            if include_ids:
                summary["customer_id"] = row.get("id", "")
            summaries.append(summary)
        return {
            "customers": summaries,
            "next_page": self._next_page(payload),
        }
