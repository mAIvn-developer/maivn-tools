# Marketing & ads

Marketing-automation, lifecycle-messaging, and paid-media connectors.
Every connector follows the standard `@toolset` / `@toolify` shape and
the agent-ready toolset pattern (compact summaries by default, opt-in
raw IDs, tolerant write inputs).

## Agent-ready behavior (overview)

List tools across this category return compact summaries with stable
display refs (`campaign_ref`, `list_ref`, `template_ref`,
`canvas_ref`, `account_ref`, `ad_set_ref`, `ad_ref`, `creative_ref`,
`segment_ref`, `audience_ref`, `ad_group_ref`). Raw provider IDs
(numeric Marketo IDs, Iterable list IDs, Braze campaign UUIDs, Meta
`act_...`/campaign IDs, LinkedIn account URNs, TikTok numeric IDs,
Google Ads resource names) are hidden by default and exposed via
`include_ids=True` when a follow-up tool (`get_*`, `update_*`,
`delete_*`, `trigger_campaign`, `add_*`, `remove_*`) needs them.

Write tools that take an identifier accept either the raw ID or the
dict from the matching list tool. This includes Marketo
`trigger_campaign` / `add_leads_to_list` / `remove_leads_from_list`,
Iterable `add_subscribers` / `remove_subscribers`, Braze
`trigger_campaign` / `trigger_canvas`, Meta `update_campaign` /
`delete_campaign`, LinkedIn `get_campaign` / `update_campaign`,
TikTok `update_campaign` / `update_campaign_status`.

Destructive tools across this group (require user confirmation):
`delete_leads`, `remove_leads_from_list` (Marketo); `delete_user`,
`remove_subscribers` (Iterable); `delete_users` (Braze);
`delete_campaign` (Meta). The TikTok `update_campaign_status` tool
(used to pause / archive campaigns) is a regular write -- agents
should still confirm pause / archive intent with the user before
flipping the status of a running campaign.

## MarketoToolSet

```python
from maivn_tools import MarketoToolSet

connector = MarketoToolSet(
    munchkin_id="123-ABC-456",
    access_token=secrets["MARKETO_TOKEN"],
)
```

Token exchange against the Marketo Identity service is left to the
caller. Tools: `get_lead_by_filter`, `create_or_update_leads`,
`delete_leads` (destructive), `list_programs`, `list_campaigns`,
`trigger_campaign`, `list_static_lists`, `add_leads_to_list`,
`remove_leads_from_list` (destructive), `create_bulk_lead_export`.

**Agent-ready behavior**

- `list_campaigns`: summary with `campaign_ref`, name, type, program
  name, active state, workspace. Raw numeric campaign IDs hidden;
  opt in with `include_ids=True` (needed by `trigger_campaign`).
- `list_static_lists`: summary with `list_ref`, name, program name,
  workspace, created/updated. Opt in for the raw list ID (needed by
  `add_leads_to_list` / `remove_leads_from_list`).
- Tolerant inputs: `trigger_campaign`, `add_leads_to_list`,
  `remove_leads_from_list` accept a numeric ID, a campaign/list dict
  from the matching list tool, or a list of such.
- Destructive: `delete_leads`, `remove_leads_from_list`. Confirm
  before invoking.

## IterableToolSet

```python
from maivn_tools import IterableToolSet

connector = IterableToolSet(api_key=secrets["ITERABLE_KEY"])
```

Tools: `update_user`, `get_user`, `delete_user` (destructive),
`track_event`, `track_purchase`, `list_lists`, `add_subscribers`,
`remove_subscribers` (destructive), `list_campaigns`, `list_templates`.

**Agent-ready behavior**

- `list_lists`: summary with `list_ref`, name, list type, size,
  created. Opt in with `include_ids=True` for the numeric `list_id`
  (needed by `add_subscribers` / `remove_subscribers`).
- `list_campaigns`: summary with `campaign_ref`, name, type, status,
  send size, created. Opt in for `campaign_id`.
- `list_templates`: summary with `template_ref`, name, type,
  created. Opt in for `template_id`.
- Tolerant inputs: `add_subscribers`, `remove_subscribers` accept a
  numeric list ID or a list dict from `list_lists(include_ids=True)`.
- Destructive: `delete_user`, `remove_subscribers`. Confirm before
  invoking.

## BrazeToolSet

```python
from maivn_tools import BrazeToolSet

connector = BrazeToolSet(
    rest_endpoint="https://rest.iad-01.braze.com",
    api_key=secrets["BRAZE_KEY"],
)
```

Tools: `track_users`, `export_user_ids`, `delete_users` (destructive),
`send_messages`, `trigger_campaign`, `trigger_canvas`,
`list_campaigns`, `list_canvases`, `subscribe_users`, `export_segment`.

**Agent-ready behavior**

- `list_campaigns`: summary with `campaign_ref`, name, tags, created,
  last edited. Raw `campaign_id` hidden; opt in with
  `include_ids=True` (needed by `trigger_campaign`).
- `list_canvases`: summary with `canvas_ref`, name, tags, created,
  last edited. Opt in for `canvas_id` (needed by `trigger_canvas`).
- Tolerant inputs: `trigger_campaign` and `trigger_canvas` accept a
  raw UUID or the dict from the matching list tool.
- Destructive: `delete_users`. Confirm before invoking.

## GoogleAdsToolSet

```python
from maivn_tools import GoogleAdsToolSet

connector = GoogleAdsToolSet(
    access_token=token,
    developer_token=secrets["GADS_DEVELOPER_TOKEN"],
    login_customer_id="111-222-3333",
    api_version="v17",
)
```

Tools: `list_accessible_customers`, `search` (GAQL), `search_stream`,
`mutate_campaigns`, `mutate_ad_groups`, `mutate_ad_group_ads`,
`mutate_campaign_budgets`, `upload_click_conversions`,
`upload_offline_user_data`.

**Agent-ready behavior**

- Google Ads is GAQL-first -- there are no fixed list tools, so no
  `_ref` summaries. `search` / `search_stream` return the raw Google
  Ads response (rows of resource names + selected fields). Resource
  names (e.g. `customers/.../campaigns/...`) are the canonical
  identifier the mutate tools take, so they are kept in results.

## MetaAdsToolSet

```python
from maivn_tools import MetaAdsToolSet

connector = MetaAdsToolSet(access_token=secrets["FB_AD_TOKEN"])
```

Tools: `list_ad_accounts`, `get_ad_account`, `list_campaigns`,
`create_campaign`, `update_campaign`, `delete_campaign` (destructive),
`list_ad_sets`, `list_ads`, `get_insights`, `list_custom_audiences`.

**Agent-ready behavior**

- `list_ad_accounts`: summary with `account_ref`, name, account
  status, currency, timezone, business name. Raw `act_...` IDs hidden;
  opt in with `include_ids=True`.
- `list_campaigns`: summary with `campaign_ref`, name, objective,
  status, daily/lifetime budget, `updated_time`. Opt in for
  `campaign_id` (needed by `update_campaign`, `delete_campaign`,
  `get_insights`).
- `list_ad_sets`: summary with `ad_set_ref`, name, status,
  optimization goal, billing event, `updated_time`. Opt in for the
  raw ID.
- `list_ads`: summary with `ad_ref`, name, status, creative name,
  `updated_time`. Opt in for the raw ID.
- `list_custom_audiences`: summary with `audience_ref`, name,
  approximate count, subtype, retention days. Opt in for the raw ID.
- Tolerant inputs: `update_campaign`, `delete_campaign`,
  `get_insights` accept a raw ID or a resource dict from the matching
  list tool.
- Destructive: `delete_campaign`. Confirm before invoking (also
  removes ad sets and ads).

```python
camps = connector.list_campaigns(account_id="act_123", include_ids=True)
connector.update_campaign(camps["campaigns"][0], status="PAUSED")
```

## LinkedInAdsToolSet

```python
from maivn_tools import LinkedInAdsToolSet

connector = LinkedInAdsToolSet(access_token=secrets["LI_ADS_TOKEN"])
```

Tools: `list_ad_accounts`, `get_ad_account`, `list_campaigns`,
`get_campaign`, `update_campaign`, `list_creatives`, `ad_analytics`,
`list_dmp_segments`, `add_users_to_dmp_segment`.

**Agent-ready behavior**

- `list_ad_accounts`: summary with `account_ref`, name, status,
  currency, type. Raw account URN hidden; opt in with
  `include_ids=True`.
- `list_campaigns`: summary with `campaign_ref`, name, status, type,
  cost type, daily budget. Opt in for the raw campaign ID (needed by
  `get_campaign`, `update_campaign`, `ad_analytics`).
- `list_creatives`: summary with `creative_ref`, status, intended
  status, last modified. Opt in for the raw ID.
- `list_dmp_segments`: summary with `segment_ref`, name, audience
  count, source platform. Opt in for the raw ID (needed by
  `add_users_to_dmp_segment`).

## TikTokAdsToolSet

```python
from maivn_tools import TikTokAdsToolSet

connector = TikTokAdsToolSet(access_token=secrets["TTAD_TOKEN"])
```

Tools: `list_advertisers`, `get_advertiser_info`, `list_campaigns`,
`create_campaign`, `update_campaign`, `update_campaign_status`,
`list_ad_groups`, `list_ads`, `get_reports`, `list_audiences`.

**Agent-ready behavior**

- `list_campaigns`: summary with `campaign_ref`, name, objective,
  status, budget, `modify_time`. Raw numeric campaign IDs hidden;
  opt in with `include_ids=True` (needed by `update_campaign`,
  `update_campaign_status`).
- `list_ad_groups`: summary with `ad_group_ref`, ad group name,
  status, optimization goal, budget. Opt in for the raw ID.
- `list_ads`: summary with `ad_ref`, ad name, status, creative
  material. Opt in for the raw ID.
- `list_audiences`: summary with `audience_ref`, audience name, type,
  approximate count. Opt in for the raw ID.
- Tolerant inputs: `update_campaign`, `update_campaign_status` accept
  raw IDs or campaign dicts from `list_campaigns(include_ids=True)`.
- `update_campaign_status` is the pause / archive control -- it is
  not flagged `destructive=True` because TikTok allows reactivation,
  but pausing or archiving a live campaign has billing / pacing
  implications. Confirm with the user before flipping the status of
  an active campaign.
