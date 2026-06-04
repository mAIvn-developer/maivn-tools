# Email delivery & marketing

Transactional email, marketing email, and notification connectors —
Resend, SendGrid, Mailgun, Postmark, Amazon SES, Brevo, Mandrill,
Customer.io, Loops, Klaviyo, and Mailchimp. Every toolset shares the
standard `@toolset` / `@toolify` shape; the snippets below show only the
constructor.

> **Agent-ready pattern.** Across these connectors, list / search
> tools return compact human-readable summaries by default with a
> stable `_ref` field (`template_ref`, `list_ref`, `contact_ref`,
> `domain_ref`, `identity_ref`, `campaign_ref`, `message_ref`,
> `segment_ref`, `broadcast_ref`, `subscriber_ref`, `flow_ref`,
> `profile_ref`). Raw provider IDs are hidden unless you pass
> `include_ids=True`; the opt-out flag here is `include_raw=True` (not
> `include_metadata=False`), which returns the raw provider payload
> unchanged. Default page size is 10-25 depending on the provider.

> **Send tools are destructive.** Across every connector below,
> `send_email`, `send_batch`, `send_transactional`,
> `send_transactional_email`, `send_template`, `send_broadcast`,
> `send_campaign`, `schedule_campaign`, `send_sms`,
> `trigger_broadcast`, and `send_event` are all tagged
> `destructive=True` because email cannot be unsent. Always confirm
> recipients and subject with the user before invoking, or drop send
> tools at registration with `exclude_tags=["destructive"]`.

## ResendToolSet

```python
from maivn_tools import ResendToolSet

connector = ResendToolSet(api_key=secrets["RESEND_API_KEY"])
```

Tools: `send_email` (destructive), `send_batch` (destructive),
`get_email`, `cancel_email` (destructive), `list_domains`,
`create_domain`, `verify_domain`, `delete_domain` (destructive),
`list_audiences`, `create_audience`, `create_contact`,
`list_contacts(audience_id, include_ids, include_raw)`,
`delete_contact` (destructive), `create_broadcast`, `list_broadcasts`,
`send_broadcast` (destructive), `list_api_keys`.

### Agent-ready behavior

`list_contacts` returns `contact_ref` summaries with name, email,
unsubscribed, created-at. Raw contact IDs are omitted unless
`include_ids=True`; `include_raw=True` returns the raw Resend
payload.

```python
resend.list_contacts(audience_id)
# { "contacts": [{"contact_ref": "contact_1", "name": "Alice",
#                  "email": "alice@example", "unsubscribed": false,
#                  "created_at": "..."}], "count": 17 }
```

### Destructive tools

`send_email`, `send_batch`, `send_broadcast`, `cancel_email`,
`delete_domain`, and `delete_contact` are tagged
`destructive=True`. `send_broadcast` fans out to every contact in
the audience; `cancel_email` only works while a scheduled email is
still queued.

## SendGridToolSet

```python
from maivn_tools import SendGridToolSet

connector = SendGridToolSet(api_key=secrets["SENDGRID_API_KEY"])
```

Tools: `send_email` (destructive), `list_templates(generations,
include_ids, include_raw)`, `get_template`, `create_template`,
`delete_template` (destructive), `get_marketing_contacts`,
`upsert_marketing_contacts`, `list_lists(page_size, include_ids,
include_raw)`, `create_list`, `delete_list` (destructive),
`list_bounces`, `list_blocks`, `delete_bounce` (destructive),
`get_account_scopes`.

### Agent-ready behavior

`list_templates` returns `template_ref` summaries (name, generation,
updated-at). `list_lists` returns `list_ref` summaries (name,
contact_count). Default `page_size` is 25 (templates have no page
size). Raw template / list IDs are omitted unless `include_ids=True`;
`include_raw=True` returns the SendGrid payload unchanged.

```python
sendgrid.list_templates()
# { "templates": [{"template_ref": "template_1",
#                   "name": "Welcome", "generation": "dynamic",
#                   "updated_at": "..."}], "count": 5 }
```

### Destructive tools

`send_email`, `delete_template`, `delete_list`, and `delete_bounce`
are tagged `destructive=True`. `delete_list(delete_contacts=True)`
also removes the contacts from the account.

## MailgunToolSet

```python
from maivn_tools import MailgunToolSet

connector = MailgunToolSet(api_key=secrets["MAILGUN_KEY"], domain="mg.example.com")
```

Tools: `send_email` (destructive), `list_domains(limit, skip,
include_ids, include_raw)`, `create_domain`, `delete_domain`
(destructive), `list_events`, `list_bounces`, `delete_bounce`
(destructive), `list_mailing_lists(limit, include_ids, include_raw)`,
`create_mailing_list`, `add_list_member`.

### Agent-ready behavior

`list_domains` returns `domain_ref` summaries (name, state, type,
created-at). `list_mailing_lists` returns `list_ref` summaries
(address, name, members_count, description). Default `limit` is 25.
`include_ids=True` exposes raw IDs; `include_raw=True` returns the
raw Mailgun payload.

```python
mailgun.list_domains()
# { "domains": [{"domain_ref": "domain_1", "name": "mg.example.com",
#                  "state": "active", "type": "custom"}],
#   "count": 1, "total_count": 1 }
```

### Destructive tools

`send_email`, `delete_domain`, and `delete_bounce` are tagged
`destructive=True`.

## PostmarkToolSet

```python
from maivn_tools import PostmarkToolSet

connector = PostmarkToolSet(server_token=secrets["POSTMARK_SERVER_TOKEN"])
```

Tools: `send_email` (destructive), `send_batch` (destructive),
`list_templates(count, offset, template_type, include_ids, include_raw)`,
`get_template`, `create_template`, `delete_template` (destructive),
`list_outbound_messages(count, offset, recipient, tag, status,
include_ids, include_raw)`, `get_outbound_message`,
`list_message_streams`, `list_servers`, `get_delivery_stats`.

### Agent-ready behavior

`list_templates` returns `template_ref` summaries (name, alias,
template_type). `list_outbound_messages` returns `message_ref`
summaries (from_address, to, subject, status). Default `count` is 25.
Raw template / message IDs are omitted unless `include_ids=True`;
`include_raw=True` returns the raw Postmark payload. Aliases are
user-facing — prefer them over IDs for `get_template` /
`delete_template`.

```python
postmark.list_outbound_messages(status="delivered")
# { "messages": [{"message_ref": "message_1",
#                  "from_address": "ops@example", "to": [...],
#                  "subject": "Welcome", "status": "Delivered"}],
#   "count": 25, "total_count": 142 }
```

### Destructive tools

`send_email`, `send_batch`, and `delete_template` are tagged
`destructive=True`.

## AmazonSESToolSet

SigV4 signing is required for live use; pass a custom
`AuthStrategy`.

```python
from maivn_tools import AmazonSESToolSet

connector = AmazonSESToolSet(region="us-east-1", auth=my_sigv4_strategy)
```

Tools: `send_email` (destructive), `send_template` (destructive),
`list_identities(page_size, next_token, include_ids, include_raw)`,
`get_identity`, `create_identity`, `delete_identity` (destructive),
`list_templates(page_size, next_token, include_raw)`, `create_template`,
`delete_template` (destructive), `list_suppressed_destinations`,
`remove_suppressed_destination` (destructive), `get_account`.

### Agent-ready behavior

`list_identities` returns `identity_ref` summaries (identity name —
the user-facing email/domain, type, sending_enabled). `list_templates`
returns `template_ref` summaries (template_name, created_timestamp);
SES uses `template_name` as the only identifier so there is no
`include_ids` knob there. Default `page_size` is 25. `include_raw=True`
returns the raw SES payload.

```python
ses.list_identities()
# { "identities": [{"identity_ref": "identity_1",
#                    "identity_name": "ops@example.com",
#                    "identity_type": "EMAIL_ADDRESS",
#                    "sending_enabled": true}],
#   "count": 1, "next_token": null }
```

### Destructive tools

`send_email`, `send_template`, `delete_identity`, `delete_template`,
and `remove_suppressed_destination` are tagged `destructive=True`.
`delete_identity` permanently stops the address/domain from sending.

## BrevoToolSet

```python
from maivn_tools import BrevoToolSet

connector = BrevoToolSet(api_key=secrets["BREVO_API_KEY"])
```

Tools: `send_transactional_email` (destructive),
`list_contacts(limit, offset, sort, include_ids, include_raw)`,
`get_contact`, `create_contact`, `update_contact`, `delete_contact`
(destructive), `list_lists(limit, offset, include_ids, include_raw)`,
`create_list`, `list_email_campaigns(type, status, limit, offset,
include_ids, include_raw)`, `send_sms` (destructive), `get_account`.

### Agent-ready behavior

`list_contacts` returns `contact_ref` summaries (name, email,
email_blacklisted, list_ids). `list_lists` returns `list_ref`
summaries (name, total_subscribers). `list_email_campaigns` returns
`campaign_ref` summaries (name, subject, type, status,
scheduled_at). Default `limit` is 25 for contacts / campaigns, 10 for
lists. Raw IDs are omitted unless `include_ids=True`;
`include_raw=True` returns the raw Brevo payload. `get_contact` and
`update_contact` accept either an email or a numeric ID — prefer
the email.

```python
brevo.list_contacts()
# { "contacts": [{"contact_ref": "contact_1", "name": "Alice",
#                  "email": "alice@example", ...}],
#   "count": 25, "total": 142 }
```

### Destructive tools

`send_transactional_email`, `send_sms`, and `delete_contact` are
tagged `destructive=True`.

## MandrillToolSet (Mailchimp Transactional)

```python
from maivn_tools import MandrillToolSet

connector = MandrillToolSet(api_key=secrets["MANDRILL_KEY"])
```

Tools: `ping`, `get_user_info`, `send_email` (destructive),
`send_template` (destructive), `get_message_info`,
`list_templates(include_ids, include_raw)`, `add_template`,
`delete_template` (destructive), `list_webhooks`, `add_webhook`.

### Agent-ready behavior

`list_templates` returns `template_ref` summaries (name, slug,
subject, from_email). Mandrill uses `name` as the primary identifier
so prefer name over raw IDs. `include_ids=True` adds the raw ID;
`include_raw=True` returns the Mandrill payload unchanged.

```python
mandrill.list_templates()
# { "templates": [{"template_ref": "template_1", "name": "welcome",
#                   "slug": "welcome", "subject": "Hi",
#                   "from_email": "ops@example"}] }
```

### Destructive tools

`send_email`, `send_template`, and `delete_template` are tagged
`destructive=True`.

## CustomerIOToolSet

Supports both the Track API (basic auth) and the App API (bearer).

```python
from maivn_tools import CustomerIOToolSet

connector = CustomerIOToolSet(
    track_site_id="sid",
    track_api_key=secrets["CIO_TRACK_KEY"],
    app_api_key=secrets["CIO_APP_KEY"],
    region="us",  # or "eu"
)
```

Tools: `identify`, `delete_customer` (destructive), `track_event`,
`track_anonymous_event`, `send_transactional` (destructive),
`list_segments(include_ids, include_raw)`,
`list_broadcasts(include_ids, include_raw)`, `trigger_broadcast`
(destructive), `list_campaigns(include_ids, include_raw)`,
`get_customer`.

### Agent-ready behavior

`list_segments` returns `segment_ref` summaries (name, type, state).
`list_broadcasts` returns `broadcast_ref` summaries (name, state).
`list_campaigns` returns `campaign_ref` summaries (name, state, type,
created). Raw IDs are omitted unless `include_ids=True`;
`include_raw=True` returns the raw payload.

```python
customer_io.list_broadcasts()
# { "broadcasts": [{"broadcast_ref": "broadcast_1",
#                    "name": "May newsletter", "state": "draft"}],
#   "count": 4 }
```

### Destructive tools

`delete_customer`, `send_transactional`, and `trigger_broadcast` are
tagged `destructive=True`. `delete_customer` removes the person and
all their events. `trigger_broadcast` fans out to every recipient.

## LoopsToolSet

```python
from maivn_tools import LoopsToolSet

connector = LoopsToolSet(api_key=secrets["LOOPS_API_KEY"])
```

Tools: `api_key_info`, `send_transactional` (destructive),
`find_contact`, `create_contact`, `update_contact`, `delete_contact`
(destructive), `list_mailing_lists(include_ids, include_raw)`,
`send_event`.

### Agent-ready behavior

`list_mailing_lists` returns `list_ref` summaries (name, description,
is_public). Raw list IDs are omitted unless `include_ids=True`;
`include_raw=True` returns the raw Loops payload. `find_contact`,
`update_contact`, and `delete_contact` accept email or user ID as
the identifier.

```python
loops.list_mailing_lists()
# { "lists": [{"list_ref": "list_1", "name": "Newsletter",
#               "description": "Monthly updates", "is_public": true}],
#   "count": 2 }
```

### Destructive tools

`send_transactional` and `delete_contact` are tagged
`destructive=True`. `delete_contact` unsubscribes the contact from
future emails.

## KlaviyoToolSet

```python
from maivn_tools import KlaviyoToolSet

connector = KlaviyoToolSet(api_key=secrets["KLAVIYO_API_KEY"])
```

Tools: `list_profiles(filter, sort, page_cursor, page_size,
include_ids, include_raw)`, `get_profile`, `create_profile`,
`update_profile`, `list_lists(page_size, include_ids, include_raw)`,
`create_list`, `add_profiles_to_list`, `remove_profiles_from_list`
(destructive), `track_event`, `list_metrics`,
`list_campaigns(filter, page_size, include_ids, include_raw)`,
`get_campaign`, `list_flows(filter, page_size, include_ids,
include_raw)`.

### Agent-ready behavior

`list_profiles` returns `profile_ref` summaries (name, email, phone,
subscription state). `list_lists` returns `list_ref` summaries
(name). `list_campaigns` returns `campaign_ref` summaries (name,
status, send_time). `list_flows` returns `flow_ref` summaries.
Default `page_size` is 20. Raw IDs are omitted unless
`include_ids=True`; `include_raw=True` returns the raw Klaviyo
payload. `list_campaigns` requires a JSON:API channel filter — e.g.
`filter="any(messages.channel,['email'])"`.

```python
klaviyo.list_profiles(filter="equals(email,'alice@example')")
# { "profiles": [{"profile_ref": "profile_1", "name": "Alice",
#                  "email": "alice@example", ...}],
#   "count": 1, "next_cursor": null }
```

### Destructive tools

`remove_profiles_from_list` is tagged `destructive=True` — it
unsubscribes the profiles from the list's mailings.

## MailchimpToolSet

```python
from maivn_tools import MailchimpToolSet

connector = MailchimpToolSet(api_key=secrets["MAILCHIMP_KEY"])  # data center auto-detected
```

Tools: `ping`, `list_lists(count, offset, include_ids, include_raw)`,
`get_list`, `list_members(list_id, status, count, offset, include_ids,
include_raw)`, `upsert_member`, `archive_member` (destructive),
`list_campaigns(status, count, offset, include_ids, include_raw)`,
`create_campaign`, `send_campaign` (destructive), `schedule_campaign`,
`delete_campaign` (destructive), `list_templates`, `list_reports`,
`get_report`.

### Agent-ready behavior

`list_lists` returns `list_ref` summaries (name, member_count,
unsubscribe_count). `list_members` returns `subscriber_ref` summaries
(name, email, status). `list_campaigns` returns `campaign_ref`
summaries (title, subject_line, type, status). Default `count` is
10. Raw IDs are omitted unless `include_ids=True`; `include_raw=True`
returns the raw Mailchimp payload.

```python
mailchimp.list_lists()
# { "lists": [{"list_ref": "list_1", "name": "Newsletter",
#               "member_count": 5421, "unsubscribe_count": 12}],
#   "count": 3, "total_items": 3 }
```

### Destructive tools

`send_campaign`, `schedule_campaign`, `delete_campaign`, and
`archive_member` are tagged `destructive=True`. `send_campaign` fans
out to every subscriber on the audience; `schedule_campaign` is
likewise irreversible at the scheduled time. `archive_member`
unsubscribes the member.
