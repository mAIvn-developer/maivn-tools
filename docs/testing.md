# Testing connectors

A connector you can't trust offline is a connector you can't ship. The goal
here is simple: every connector must be fully exercisable without touching a
live API, so the test suite runs in milliseconds, in CI, on any machine, with
no credentials. The `MockTransport` makes that possible by standing in for the
network and recording exactly what each tool sent.

This package ships with two layers of tests:

1. **Unit tests** drive every connector with `MockTransport` (or a fake
   client factory) so they run offline in milliseconds. These tests are
   the default `pytest` run and form the contract every connector must
   satisfy.

2. **Live tests** exercise real provider APIs. They are opt-in, gated on
   environment variables, and skipped automatically when those variables
   are absent.

## Unit tests

Every connector test follows the same pattern:

```python
from maivn_tools.testing import MockTransport, json_response

transport = MockTransport()
transport.enqueue(json_response({"ok": True}))
connector = MyConnector(token="dummy", transport=transport)

result = connector.tools()[0]()
assert result == {"ok": True}
assert transport.requests[0].method == "GET"
```

The `maivn_tools.testing` helpers cover the common cases:

- `MockTransport.enqueue(...)` queues canned `HttpResponse` objects, returned
  in order; `enqueue_error(...)` queues an exception to raise instead.
- `json_response(body, status=...)` and `text_response(body, status=...)`
  build responses without hand-rolling headers.
- `transport.requests` returns an ordered list of `RecordedRequest`
  snapshots, so you can assert on `method`, `url`, `params`, and `json_body`.

## Live tests

Live tests cover the provider behaviors that unit tests cannot — auth
rejections, real pagination, response shape drift, rate-limit headers.
They live next to the unit tests but follow these rules:

- File name suffix: `_live.py` (e.g. `test_github_live.py`).
- Each test is wrapped in `pytest.mark.skipif` keyed on the relevant
  environment variable(s). Tests are skipped (not failed) when the
  variables are missing.
- Live tests must never mutate shared production data. Use a sandbox
  account, a throwaway repository / channel / mailbox, or a connector
  fixture that creates the target on setup and tears it down on
  teardown.
- Live tests run on demand only. CI does not invoke them as part of the
  default test job.

### Running live tests

Set the required environment variables and pass the marker explicitly:

```bash
export MAIVN_TOOLS_GITHUB_LIVE_TOKEN=ghp_...
export MAIVN_TOOLS_GITHUB_LIVE_REPO=octocat/sandbox
pytest tests/test_github_live.py
```

### Required environment variables per connector

| Connector | Variables |
| --- | --- |
| GitHub | `MAIVN_TOOLS_GITHUB_LIVE_TOKEN`, `MAIVN_TOOLS_GITHUB_LIVE_REPO` |
| Slack | `MAIVN_TOOLS_SLACK_LIVE_TOKEN`, `MAIVN_TOOLS_SLACK_LIVE_CHANNEL` |
| PostgreSQL | `MAIVN_TOOLS_POSTGRES_LIVE_DSN` |
| IMAP | `MAIVN_TOOLS_IMAP_LIVE_HOST`, `MAIVN_TOOLS_IMAP_LIVE_USER`, `MAIVN_TOOLS_IMAP_LIVE_PASSWORD` |
| SMTP | `MAIVN_TOOLS_SMTP_LIVE_HOST`, `MAIVN_TOOLS_SMTP_LIVE_USER`, `MAIVN_TOOLS_SMTP_LIVE_PASSWORD`, `MAIVN_TOOLS_SMTP_LIVE_SENDER` |
| Gmail | `MAIVN_TOOLS_GMAIL_LIVE_TOKEN` |
| Outlook | `MAIVN_TOOLS_OUTLOOK_LIVE_TOKEN` |
| Jira | `MAIVN_TOOLS_JIRA_LIVE_BASE_URL`, `MAIVN_TOOLS_JIRA_LIVE_EMAIL`, `MAIVN_TOOLS_JIRA_LIVE_TOKEN` |
| Zendesk | `MAIVN_TOOLS_ZENDESK_LIVE_SUBDOMAIN`, `MAIVN_TOOLS_ZENDESK_LIVE_EMAIL`, `MAIVN_TOOLS_ZENDESK_LIVE_TOKEN` |
| HubSpot | `MAIVN_TOOLS_HUBSPOT_LIVE_TOKEN` |
| Salesforce | `MAIVN_TOOLS_SF_LIVE_INSTANCE_URL`, `MAIVN_TOOLS_SF_LIVE_TOKEN` |

If a connector needs additional variables (e.g. impersonation scope or a
specific recipient), add them to the table when the live test ships.

## Adding tests for a new connector

The release checklist requires:

1. Unit tests covering each public tool, including:
   - happy path,
   - input validation,
   - permission flag exposure,
   - error mapping (where the connector translates provider errors).
2. A signature-verification unit test for any connector that processes
   webhooks.
3. A live-test file when the provider supports a sandbox or scratch
   account, gated as above.

Aim for at least one happy-path test per public tool. Tools that take
many keyword arguments should additionally cover the request-shape
serialization with assertions on the recorded `MockTransport` request.
