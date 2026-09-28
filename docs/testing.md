# Testing connectors

A connector you can't trust offline is a connector you can't ship. The goal
here is simple: every connector must be fully exercisable without touching a
live API, so the test suite runs in milliseconds, in CI, on any machine, with
no credentials. The `MockTransport` makes that possible by standing in for the
network and recording exactly what each tool sent.

The checked-in suite uses mock transports and fake clients. Passing it verifies
local request construction and behavior, not current live-provider compatibility.

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

## Live provider validation

No provider live-test files are shipped in the current suite. There is no
supported command or environment-variable matrix for a bundled live suite.
Before relying on a connector, validate its requests and pagination against your
provider's current API in an account you control. Record the provider/API version
and tested operations separately from mock-test results.

New live tests should require an explicit opt-in, use isolated test data, and
stay outside the default offline run. Do not enable writes merely by detecting
a credential in the environment.

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
