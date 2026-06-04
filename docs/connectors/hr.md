# HR & people ops

HRIS, payroll, and applicant-tracking connectors. Every connector
follows the standard `@toolset` / `@toolify` shape and the agent-ready
toolset pattern (compact summaries by default, opt-in raw IDs, tolerant
write inputs).

## Agent-ready behavior (overview)

All list tools across this category return compact summaries with
stable display refs (`worker_ref`, `employee_ref`, `candidate_ref`,
`job_ref`, `opportunity_ref`, `contract_ref`, `user_ref`). Raw
provider IDs (Workday WIDs, BambooHR numeric IDs, Rippling employee
UUIDs, Gusto employee UUIDs, Greenhouse numeric job/candidate IDs,
Lever opportunity IDs, Deel person IDs) are hidden by default and
exposed via `include_ids=True` when a follow-up tool needs them.
Default page size is 25 unless otherwise noted.

Write tools that take an identifier (`get_worker`, `get_employee`,
`update_employee`, `advance_application`, `reject_application`,
`update_opportunity_stage`, `archive_opportunity`,
`create_time_off_request`, etc.) accept a raw ID string or the dict
from the corresponding list tool.

Destructive tools across this group (require user confirmation):
`reject_application` (Greenhouse), `archive_opportunity` (Lever).

## WorkdayToolSet

```python
from maivn_tools import WorkdayToolSet

connector = WorkdayToolSet(
    tenant_url="https://wd2-impl-services1.workday.com/ccx",
    tenant="acme",
    access_token=token,
)
```

OAuth exchange against Workday Identity is left to the caller. Tools:
`list_workers`, `get_worker`, `list_organizations`, `list_job_changes`,
`list_time_off_balances`, `submit_time_off`, `list_positions`,
`list_job_postings`, `list_candidates`.

**Agent-ready behavior**

- `list_workers`: summary with `worker_ref`, name, primary email, job
  title, manager name, hire date, status. Raw WID hidden; opt in with
  `include_ids=True` (needed by `get_worker`,
  `list_time_off_balances`, `submit_time_off`).
- `list_job_postings`: summary with `job_ref`, title, location,
  department, posted date. Opt in for the raw posting ID.
- `list_candidates`: summary with `candidate_ref`, name, email, stage,
  posting title. Opt in for the raw candidate ID.

```python
workers = connector.list_workers(include_ids=True)
balance = connector.list_time_off_balances(workers["workers"][0]["worker_id"])
```

## BambooHRToolSet

```python
from maivn_tools import BambooHRToolSet

connector = BambooHRToolSet(
    subdomain="acme",
    api_key=secrets["BAMBOOHR_KEY"],
)
```

Tools: `list_employees`, `get_employee`, `create_employee`,
`update_employee`, `get_who_is_out`, `list_time_off_requests`,
`create_time_off_request`, `get_custom_report`, `list_meta_fields`,
`list_meta_time_off_types`.

**Agent-ready behavior**

- `list_employees`: summary with `employee_ref`, name, work email,
  job title, department, status, location. Raw numeric employee IDs
  hidden; opt in with `include_ids=True` (needed by `get_employee`,
  `update_employee`, `create_time_off_request`).
- Tolerant inputs: `get_employee` and `update_employee` accept a
  numeric employee ID or the employee dict from
  `list_employees(include_ids=True)`.

## RipplingToolSet

```python
from maivn_tools import RipplingToolSet

connector = RipplingToolSet(access_token=secrets["RIPPLING_TOKEN"])
```

Tools: `get_current_company`, `list_employees`, `get_employee`,
`list_departments`, `list_work_locations`, `list_groups`,
`list_leave_requests`, `list_compensations`, `list_teams`.

**Agent-ready behavior**

- `list_employees`: summary with `employee_ref`, name, work email,
  job title, manager name, hire date, status. Rippling employee UUIDs
  hidden; opt in with `include_ids=True` (needed by `get_employee`).

## GustoToolSet

```python
from maivn_tools import GustoToolSet

connector = GustoToolSet(access_token=secrets["GUSTO_TOKEN"])
```

For Gusto Demo, override `base_url="https://api.gusto-demo.com"`.
Tools: `list_companies`, `get_company`, `list_employees`,
`get_employee`, `create_employee`, `list_payrolls`, `get_payroll`,
`list_pay_schedules`, `list_time_off_requests`, `list_jobs`.

**Agent-ready behavior**

- `list_employees`: summary with `employee_ref`, name, work email,
  job title, department, terminated state. Raw Gusto employee UUIDs
  hidden; opt in with `include_ids=True` (needed by `get_employee`,
  `list_jobs`). `per` controls per-page size and pagination is
  forwarded as standard Gusto headers.

## GreenhouseToolSet

```python
from maivn_tools import GreenhouseToolSet

connector = GreenhouseToolSet(
    api_key=secrets["GREENHOUSE_KEY"],
    on_behalf_of="123",   # required for writes
)
```

Tools: `list_jobs`, `get_job`, `list_candidates`, `get_candidate`,
`create_candidate`, `list_applications`, `advance_application`,
`reject_application` (destructive), `list_scorecards`, `list_offers`.

**Agent-ready behavior**

- `list_jobs`: summary with `job_ref`, name, status, office, opened
  date. Raw numeric job IDs hidden; opt in with `include_ids=True`
  (needed by `get_job`).
- `list_candidates`: summary with `candidate_ref`, name, primary
  email, last activity, source. Opt in for `candidate_id`.
- Destructive: `reject_application`. Confirm with the user before
  invoking (rejection emails the candidate and closes the
  application).

## LeverToolSet

```python
from maivn_tools import LeverToolSet

connector = LeverToolSet(api_key=secrets["LEVER_KEY"])
```

Pass `sandbox=True` to target the Lever sandbox. Tools:
`list_opportunities`, `get_opportunity`, `create_opportunity`,
`update_opportunity_stage`, `list_postings`, `get_posting`,
`list_stages`, `list_users`, `list_feedback`, `archive_opportunity`
(destructive).

**Agent-ready behavior**

- `list_opportunities`: summary with `candidate_ref`, name, headline,
  stage, owner, last interaction. Raw opportunity IDs hidden; opt in
  with `include_ids=True` (needed by `get_opportunity`,
  `update_opportunity_stage`, `archive_opportunity`).
- `list_postings`: summary with `job_ref`, text, state, team,
  location. Opt in for `posting_id`.
- `list_users`: summary with `user_ref`, name, email, access role.
  Opt in for `user_id`.
- Destructive: `archive_opportunity`. Confirm with the user before
  invoking.

## DeelToolSet

```python
from maivn_tools import DeelToolSet

connector = DeelToolSet(api_token=secrets["DEEL_TOKEN"])
```

Tools: `list_people`, `get_person`, `list_contracts`, `get_contract`,
`create_invoice_adjustment`, `list_invoice_adjustments`,
`list_time_off`, `review_time_off`, `list_payroll_events`,
`list_legal_entities`.

**Agent-ready behavior**

- `list_people`: summary with `employee_ref`, name, work email, hiring
  status, employment type, country. Raw Deel person IDs hidden; opt
  in with `include_ids=True` (needed by `get_person`).
- `list_contracts`: summary with `contract_ref`, title, status, type,
  worker name, start date. Opt in for `contract_id` (needed by
  `get_contract`, `create_invoice_adjustment`).
