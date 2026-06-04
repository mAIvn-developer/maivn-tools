# Payments, finance & accounting

Payment processors, accounting systems, and expense / spend management.

All of these connectors follow the same agent-ready pattern: broad
`list_*` tools return compact summaries by default with a stable
ordinal ref (`customer_ref`, `payment_ref`, `invoice_ref`,
`subscription_ref`, `transaction_ref`, etc.) plus user-facing fields
(name / email / amount / status / dates), and raw provider IDs are
omitted unless `include_ids=True`. Amounts are formatted as
`"<value> <CURRENCY>"` strings in summaries. Write tools accept either
the raw provider ID or the dict returned by the matching list/get tool.
Default `limit` / `page_size` for list tools is **10-25** (per connector).

> Tip: register with `add_toolset(..., exclude_tags=["destructive"])`
> to drop the irreversible tools (refunds, cancellations, deletes,
> card terminations).

## StripeToolSet

```python
from maivn_tools import StripeToolSet

connector = StripeToolSet(api_key=secrets["STRIPE_KEY"])
```

Stripe uses repeated-key form encoding (`customer[email]=...`); the
toolset's ``stripe_form_encode`` helper handles nested dicts and lists.

Tools: `list_customers(email, limit, include_ids)`,
`get_customer(customer_id)`, `create_customer(**fields)`,
`update_customer(customer_id, **fields)`,
`delete_customer(customer_id)` (destructive),
`list_subscriptions(customer, status, limit, include_ids)`,
`create_subscription(customer, items, **fields)`,
`cancel_subscription(subscription_id, ...)` (destructive),
`list_invoices(customer, status, limit, include_ids)`,
`create_invoice(customer, **fields)`, `finalize_invoice(invoice_id)`,
`create_payment_intent(amount, currency, ...)`,
`confirm_payment_intent(payment_intent_id, **fields)`,
`refund_charge(charge, payment_intent, amount, ...)` (destructive),
`list_charges(customer, limit, include_ids)`,
`list_disputes(limit)`, `update_dispute(dispute_id, **fields)`,
`create_checkout_session(**fields)`,
`list_products(active, limit)`, `list_prices(product, limit)`,
`get_balance`.

`create_payment_intent` and `refund_charge` accept ``idempotency_key``
which is propagated to the request runtime.

### Agent-ready behavior

- `list_customers`, `list_subscriptions`, `list_invoices`,
  `list_charges`, `list_disputes` return compact summaries with stable
  refs (`customer_ref`, `subscription_ref`, `invoice_ref`, `charge_ref`,
  `dispute_ref`). Amounts (`total`, `amount_due`, `amount_paid`,
  `balance`) are formatted as `"12.34 USD"` strings.
- Raw Stripe IDs (`cus_...`, `sub_...`, `in_...`, `ch_...`,
  `pi_...`) are hidden by default; pass `include_ids=True` to opt in.
- Default `limit` is **10** (Stripe max 100). Pagination via
  `starting_after` / `ending_before`; the list also returns
  `has_more` and a `next_cursor`.
- Write tools accept either the raw ID or the dict from the
  corresponding list/get: `update_customer`, `delete_customer`,
  `cancel_subscription`, `finalize_invoice`, `refund_charge`.
- Destructive tools: `delete_customer`, `cancel_subscription`,
  `refund_charge`.

Example:

```python
customers = connector.list_customers(email="alice@example.com")
# {"customers": [{"customer_ref": "customer_1", "name": "Alice", "email": "alice@example.com", "balance": "0.00 USD", ...}], "has_more": False, "next_cursor": None}
connector.update_customer(customers["customers"][0], description="VIP")  # needs include_ids=True or the customer dict via get_customer
```

## SquareToolSet

```python
from maivn_tools import SquareToolSet

connector = SquareToolSet(access_token=secrets["SQUARE_TOKEN"])
```

Tools: `list_locations`,
`list_customers(limit, include_ids, ...)`, `get_customer(customer_id)`,
`create_customer(fields)`, `update_customer(customer_id, fields)`,
`delete_customer(customer_id)` (destructive),
`search_orders(query)`, `get_order(order_id)`,
`create_order(location_id, order, idempotency_key)`,
`list_payments(begin_time, end_time, location_id, limit, include_ids)`,
`create_payment(source_id, amount_money, idempotency_key, ...)`,
`refund_payment(idempotency_key, amount_money, payment_id, reason)`
(destructive), `search_catalog(query)`,
`upsert_catalog_object(payload)`, `list_inventory_counts(...)`.

### Agent-ready behavior

- `list_customers` and `list_payments` return compact summaries with
  stable refs (`customer_ref`, `payment_ref`). Money fields use Square's
  minor-unit `Money` object formatted as `"12.34 USD"` strings.
- Raw Square IDs hidden by default; pass `include_ids=True` to opt in.
- Default `limit` is **25**.
- `update_customer`, `delete_customer`, and `refund_payment` accept
  either the raw ID or the dict from the matching list/get.
- Destructive tools: `delete_customer`, `refund_payment`.

## PayPalToolSet

```python
from maivn_tools import PayPalToolSet

connector = PayPalToolSet(access_token=secrets["PAYPAL_TOKEN"])
```

Tools: `create_order(intent, purchase_units, ...)`, `get_order(order_id)`,
`capture_order(order_id)`, `authorize_order(order_id)`,
`get_capture(capture_id)`,
`refund_capture(capture_id, amount, ...)` (destructive),
`get_authorization(authorization_id)`,
`void_authorization(authorization_id)` (destructive),
`create_subscription(plan_id, ...)`,
`get_subscription(subscription_id)`,
`cancel_subscription(subscription_id, reason)` (destructive),
`suspend_subscription(subscription_id, reason)`,
`list_disputes(page_size, status, include_ids)`,
`get_dispute(dispute_id)`.

### Agent-ready behavior

- `list_disputes` returns compact summaries with `dispute_ref`,
  amount (formatted with currency), state, reason, and timestamps. Raw
  PayPal IDs hidden by default; pass `include_ids=True` to opt in.
- Default `page_size` is **10** (max 50).
- `refund_capture`, `void_authorization`, and `cancel_subscription`
  accept either the raw ID string or the dict from the corresponding
  `get_*` tool.
- Destructive tools: `refund_capture`, `void_authorization`,
  `cancel_subscription`. `capture_order` and `authorize_order` move
  money - confirm before calling.

## PlaidToolSet

Plaid passes ``client_id`` + ``secret`` in every body; the toolset
handles that automatically.

```python
from maivn_tools import PlaidToolSet

connector = PlaidToolSet(client_id=..., secret=..., environment="production")
```

Tools: `create_link_token(...)`,
`exchange_public_token(public_token)`, `get_accounts(access_token)`,
`get_balance(access_token)`,
`get_transactions(access_token, start_date, end_date, count, offset, include_ids)`,
`sync_transactions(access_token, cursor, count)`,
`get_identity(access_token)`, `get_liabilities(access_token)`,
`get_institution(institution_id, country_codes)`,
`search_institutions(query, products, country_codes)`,
`remove_item(access_token)` (destructive).

### Agent-ready behavior

- `get_transactions` returns compact summaries with `transaction_ref`,
  name, merchant, amount (formatted with currency), date, category,
  and pending flag. Raw Plaid `transaction_id` / `account_id` hidden
  unless `include_ids=True`.
- Default `count` is **25** (max 500 per Plaid's docs).
- `sync_transactions` returns the raw `/transactions/sync` envelope
  (`added` / `modified` / `removed` / `next_cursor` / `has_more`) so
  cursors are always preserved.
- Destructive tools: `remove_item` (revokes the Item / access_token).

## QuickBooksToolSet

```python
from maivn_tools import QuickBooksToolSet

connector = QuickBooksToolSet(
    access_token=secrets["QBO_TOKEN"],
    realm_id="123146...",  # company ID
)
```

Tools: `query(query)` (QBO SQL-like), `get_entity(entity, entity_id)`,
`create_entity(entity, payload)`,
`update_entity(entity, payload)`,
`delete_entity(entity, payload)` (destructive),
`list_customers(max_results, include_ids)`,
`list_invoices(max_results, include_ids)`,
`list_bills(max_results, include_ids)`,
`create_invoice(payload)`, `create_payment(payload)`,
`get_company_info`.

### Agent-ready behavior

- `list_customers`, `list_invoices`, `list_bills` return compact
  summaries with stable refs (`customer_ref`, `invoice_ref`,
  `bill_ref`). Currency amounts (`balance`, `total`) are formatted as
  `"12.34 USD"`.
- Raw QBO IDs and `SyncToken` are hidden by default; pass
  `include_ids=True` to opt in (`SyncToken` is required for
  `update_entity` / `delete_entity`).
- Default `max_results` is **25** (max 1000 per QBO docs).
- `update_entity` and `delete_entity` use sparse updates that require
  `Id` + `SyncToken` in the payload -- call `list_*(include_ids=True)`
  first to pull both.
- Destructive tools: `delete_entity`.

## XeroToolSet

```python
from maivn_tools import XeroToolSet

connector = XeroToolSet(
    access_token=secrets["XERO_TOKEN"],
    tenant_id="abc-123-...",
)
```

Tools: `list_connections`,
`list_contacts(where, order, page, include_ids)`,
`get_contact(contact_id)`, `upsert_contacts(contacts)`,
`list_invoices(status, where, page, include_ids)`,
`upsert_invoices(invoices)`,
`list_payments(where, order, include_ids)`,
`upsert_payments(payments)`,
`list_bank_transactions(where, page)`, `list_accounts(where)`,
`get_organisation`.

### Agent-ready behavior

- `list_contacts`, `list_invoices`, `list_payments` return compact
  summaries with stable refs (`contact_ref`, `invoice_ref`,
  `payment_ref`). Currency amounts (`total`, `amount_due`,
  `amount_paid`, payment `amount`) are formatted as `"12.34 USD"`.
- Raw Xero GUIDs (`ContactID`, `InvoiceID`, `PaymentID`) hidden by
  default; pass `include_ids=True` to opt in.
- Default `page` is **1** (Xero pages contacts and invoices).
- No `destructive=True` tools on this surface -- Xero treats voids as
  invoice status updates (`upsert_invoices` with `Status="VOIDED"`).

## NetSuiteToolSet

NetSuite SuiteTalk REST uses OAuth 1.0 (TBA); pass a custom
``AuthStrategy``.

```python
from maivn_tools import NetSuiteToolSet

connector = NetSuiteToolSet(account_id="123_TST", auth=my_oauth1_strategy)
```

Tools: `suiteql(query, limit, offset)`,
`list_records(record_type, limit, offset, q, include_ids)`,
`get_record(record_type, record_id)`,
`create_record(record_type, payload)`,
`update_record(record_type, record_id, payload)`,
`delete_record(record_type, record_id)` (destructive).

### Agent-ready behavior

- `list_records(record_type)` returns compact summaries with
  ordinal ref `record_ref` (formatted as `{record_type}_{index}` --
  e.g. `customer_1`, `invoice_3`) plus any obvious display fields the
  payload includes (`entityId`, `companyName`, `name`, `email`,
  `subsidiary`). Raw NetSuite `id` values hidden by default; pass
  `include_ids=True` for follow-up `get_record` / `update_record` /
  `delete_record` calls.
- Default `limit` is **25** (max 1000).
- `update_record` and `delete_record` accept either the raw ID or the
  dict from `list_records(include_ids=True)` / `get_record`.
- Destructive tools: `delete_record`.

## RampToolSet

```python
from maivn_tools import RampToolSet

connector = RampToolSet(access_token=secrets["RAMP_TOKEN"])
```

Tools: `list_transactions(from_date, to_date, page_size, start, include_ids)`,
`get_transaction(transaction_id)`, `list_cards(page_size)`,
`create_card(payload)`,
`terminate_card(card_id)` (destructive), `list_users(page_size)`,
`list_reimbursements(page_size)`, `list_vendors(page_size)`,
`list_departments`.

### Agent-ready behavior

- `list_transactions` returns compact summaries with `transaction_ref`,
  merchant, amount (formatted with currency), date, card holder, state,
  and category. Raw transaction / card IDs hidden by default; pass
  `include_ids=True` to opt in.
- Default `page_size` is **25** (max 100).
- `terminate_card` accepts either the raw ID or the dict from
  `list_cards(include_ids=True)`.
- Destructive tools: `terminate_card`.

## BrexToolSet

```python
from maivn_tools import BrexToolSet

connector = BrexToolSet(access_token=secrets["BREX_TOKEN"])
```

Tools: `list_cash_accounts`, `list_card_accounts`,
`list_transactions(cursor, limit, account_id, include_ids)`,
`list_expenses(cursor, limit, include_ids)`,
`get_expense(expense_id)`, `update_expense(expense_id, fields)`,
`list_cards(cursor, limit, include_ids)`, `issue_card(payload)`,
`terminate_card(card_id)` (destructive),
`list_users(cursor, limit)`, `list_vendors(cursor, limit)`.

### Agent-ready behavior

- `list_transactions`, `list_expenses`, `list_cards` return compact
  summaries with stable refs (`transaction_ref`, `expense_ref`,
  `card_ref`). Brex `Money` amounts are formatted as `"12.34 USD"`.
- Raw IDs hidden by default; pass `include_ids=True` to opt in.
- Default `limit` is **25** (max 100). Pagination via `cursor` with
  `next_cursor` returned in the response.
- `update_expense` and `terminate_card` accept either the raw ID or
  the dict from the corresponding list / get.
- Destructive tools: `terminate_card`.

## ChargebeeToolSet

```python
from maivn_tools import ChargebeeToolSet

connector = ChargebeeToolSet(
    site=secrets["CHARGEBEE_SITE"],
    api_key=secrets["CHARGEBEE_API_KEY"],
)
```

Tools: `list_customers(limit, offset, first_name, email, include_ids)`,
`get_customer(customer_id)`, `create_customer(params)`,
`list_subscriptions(limit, status, customer_id, include_ids)`,
`create_subscription_for_customer(customer_id, params)`,
`cancel_subscription(subscription_id, end_of_term)` (destructive),
`list_invoices(limit, status, customer_id, include_ids)`,
`list_plans(limit)`.

### Agent-ready behavior

- `list_customers`, `list_subscriptions`, `list_invoices` return
  compact summaries with stable refs (`customer_ref`,
  `subscription_ref`, `invoice_ref`). Currency amounts (`total_dues`,
  `total`, `amount_due`, `amount_paid`) are formatted as
  `"12.34 USD"`.
- Raw Chargebee IDs hidden by default; pass `include_ids=True` to
  opt in. Pagination via `offset` with `next_offset` returned.
- Default `limit` is **10** (max 100).
- `cancel_subscription` accepts either the raw ID or the dict from
  `list_subscriptions(include_ids=True)`.
- Destructive tools: `cancel_subscription`.

## RecurlyToolSet

```python
from maivn_tools import RecurlyToolSet

connector = RecurlyToolSet(api_key=secrets["RECURLY_API_KEY"])
```

Tools: `list_accounts(limit, sort, order, cursor, include_ids)`,
`get_account(account_id)`, `create_account(payload)`,
`update_account(account_id, payload)`,
`list_subscriptions(limit, state, include_ids)`,
`create_subscription(payload)`,
`cancel_subscription(subscription_id)` (destructive),
`reactivate_subscription(subscription_id)`,
`list_invoices(limit, include_ids)`,
`list_transactions(limit, include_ids)`.

### Agent-ready behavior

- `list_accounts`, `list_subscriptions`, `list_invoices`,
  `list_transactions` return compact summaries with stable refs
  (`account_ref`, `subscription_ref`, `invoice_ref`,
  `transaction_ref`). Currency amounts (`unit_amount`, `total`,
  `balance`, transaction `amount`) are formatted as `"12.34 USD"`.
- Raw Recurly IDs hidden by default; pass `include_ids=True` to opt
  in. Recurly also accepts `code-<account_code>` literals -- those
  human-readable codes are always shown.
- Default `limit` is **20** (max 200). Pagination via `cursor`.
- `update_account`, `cancel_subscription`, `reactivate_subscription`
  accept either the raw ID, a `code-...` literal, or the dict from
  the corresponding list.
- Destructive tools: `cancel_subscription`.

## BillToolSet

Bill.com (Bill) v3 API.

```python
from maivn_tools import BillToolSet

connector = BillToolSet(api_key=secrets["BILL_SESSION"])
```

Tools: `list_vendors(max_results, include_ids)`,
`create_vendor(payload)`, `get_vendor(vendor_id)`,
`list_bills(max_results, include_ids)`, `create_bill(payload)`,
`list_invoices(max_results, include_ids)`,
`create_invoice(payload)`,
`list_payments(max_results, include_ids)`,
`create_payment(payload)`,
`list_customers(max_results, include_ids)`.

### Agent-ready behavior

- `list_vendors`, `list_bills`, `list_invoices`, `list_payments`,
  `list_customers` return compact summaries with stable refs
  (`vendor_ref`, `bill_ref`, `invoice_ref`, `payment_ref`,
  `customer_ref`). Currency amounts are formatted as `"12.34 USD"`.
- Raw Bill IDs hidden by default; pass `include_ids=True` to opt in.
  Pagination via `nextPage` returned in the response.
- Default `max_results` is **25** (max 200).
- No `destructive=True` tools on this surface -- Bill payments and
  invoices are typically voided via status updates handled by the
  caller.

## ExpensifyToolSet

Expensify Integration Server (form-encoded job descriptions).

```python
from maivn_tools import ExpensifyToolSet

connector = ExpensifyToolSet(
    partner_user_id=secrets["EXPENSIFY_PARTNER_ID"],
    partner_user_secret=secrets["EXPENSIFY_PARTNER_SECRET"],
)
```

Tools: `export_report`, `report_export`, `get_policy_list`,
`get_policy`, `update_policy`.

### Agent-ready behavior

- ExpensifyToolSet returns the raw Integration Server response for each
  job -- Expensify's response shape is itself a free-form payload keyed
  by the report / policy fields a customer configured, so summary
  flattening would lose information. There are no list-style tools on
  this surface and no `_ref` ordinals.
- No `destructive=True` tools.
