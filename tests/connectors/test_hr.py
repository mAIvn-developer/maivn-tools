# pyright: strict
"""Tests for HR / people-ops connectors.

Workday, BambooHR, Rippling, Gusto, Greenhouse, Lever, Deel.
"""

from __future__ import annotations

import pytest

from maivn_tools.connectors.bamboohr import BambooHRToolSet
from maivn_tools.connectors.deel import DeelToolSet
from maivn_tools.connectors.greenhouse import GreenhouseToolSet
from maivn_tools.connectors.gusto import GustoToolSet
from maivn_tools.connectors.lever import LeverToolSet
from maivn_tools.connectors.rippling import RipplingToolSet
from maivn_tools.connectors.workday import WorkdayToolSet
from maivn_tools.testing import MockTransport, json_response

# MARK: - Workday


def _workday() -> tuple[WorkdayToolSet, MockTransport]:
    transport = MockTransport()
    return (
        WorkdayToolSet(
            tenant_url="https://wd.example/ccx",
            tenant="acme",
            access_token="t",
            transport=transport,
        ),
        transport,
    )


def test_workday_requires_args() -> None:
    with pytest.raises(ValueError):
        WorkdayToolSet(tenant_url="", tenant="t", access_token="x")
    with pytest.raises(ValueError):
        WorkdayToolSet(tenant_url="u", tenant="", access_token="x")
    with pytest.raises(ValueError):
        WorkdayToolSet(tenant_url="u", tenant="t", access_token="")


def test_workday_endpoints() -> None:
    connector, transport = _workday()
    for _ in range(9):
        transport.enqueue(json_response({"data": []}))
    connector.list_workers(limit=10, offset=0, search="alice")
    connector.get_worker("w1")
    connector.list_organizations(limit=10, offset=0)
    connector.list_job_changes(worker_id="w1", limit=10, offset=0)
    connector.list_time_off_balances("w1")
    connector.submit_time_off("w1", entries=[{"date": "2026-01-01"}])
    connector.list_positions(limit=10, offset=0)
    connector.list_job_postings(limit=10, offset=0)
    connector.list_candidates(limit=10, offset=0)
    assert transport.requests[0].headers["Authorization"] == "Bearer t"
    with pytest.raises(ValueError):
        connector.get_worker("")
    with pytest.raises(ValueError):
        connector.list_job_changes(worker_id="")
    with pytest.raises(ValueError):
        connector.list_time_off_balances("")
    with pytest.raises(ValueError):
        connector.submit_time_off("", entries=[{"x": 1}])
    with pytest.raises(ValueError):
        connector.submit_time_off("w", entries=[])


# MARK: - BambooHR


def _bamboo() -> tuple[BambooHRToolSet, MockTransport]:
    transport = MockTransport()
    return (
        BambooHRToolSet(
            subdomain="acme",
            api_key="k",
            transport=transport,
        ),
        transport,
    )


def test_bamboo_requires_args() -> None:
    with pytest.raises(ValueError):
        BambooHRToolSet(subdomain="", api_key="k")
    with pytest.raises(ValueError):
        BambooHRToolSet(subdomain="x", api_key="")


def test_bamboo_endpoints() -> None:
    connector, transport = _bamboo()
    for _ in range(9):
        transport.enqueue(json_response({"data": []}))
    connector.list_employees()
    connector.get_employee(1, fields=["firstName", "lastName"])
    connector.create_employee({"firstName": "A", "lastName": "B"})
    connector.update_employee(1, fields={"firstName": "C"})
    connector.get_who_is_out(start="2026-01-01", end="2026-01-31")
    connector.list_time_off_requests(
        action="view",
        employee_id=1,
        start="2026-01-01",
        end="2026-01-31",
        status="approved",
    )
    connector.create_time_off_request(
        employee_id=1,
        time_off_type_id=1,
        start="2026-01-01",
        end="2026-01-02",
        amount=1.0,
    )
    connector.list_meta_fields()
    connector.list_meta_time_off_types()
    with pytest.raises(ValueError):
        connector.get_employee(0, fields=["x"])
    with pytest.raises(ValueError):
        connector.get_employee(1, fields=[])
    with pytest.raises(ValueError):
        connector.create_employee({})
    with pytest.raises(ValueError):
        connector.update_employee(0, fields={"x": 1})
    with pytest.raises(ValueError):
        connector.update_employee(1, fields={})
    with pytest.raises(ValueError):
        connector.create_time_off_request(
            employee_id=0,
            time_off_type_id=1,
            start="a",
            end="b",
            amount=1.0,
        )


def test_bamboo_custom_report() -> None:
    connector, transport = _bamboo()
    transport.enqueue(json_response({"rows": []}))
    connector.get_custom_report(1, format="JSON")
    with pytest.raises(ValueError):
        connector.get_custom_report(0)
    with pytest.raises(ValueError):
        connector.get_custom_report(1, format="bogus")


# MARK: - Rippling


def _rippling() -> tuple[RipplingToolSet, MockTransport]:
    transport = MockTransport()
    return RipplingToolSet(access_token="t", transport=transport), transport


def test_rippling_requires_token() -> None:
    with pytest.raises(ValueError):
        RipplingToolSet(access_token="")


def test_rippling_endpoints() -> None:
    connector, transport = _rippling()
    for _ in range(9):
        transport.enqueue(json_response({"data": []}))
    connector.get_current_company()
    connector.list_employees(
        limit=10,
        offset=0,
        status="ACTIVE",
        employment_type="FULL_TIME",
    )
    connector.get_employee("e1")
    connector.list_departments(limit=10, offset=0)
    connector.list_work_locations(limit=10, offset=0)
    connector.list_groups(limit=10, offset=0)
    connector.list_leave_requests(
        employee_id="e1",
        status="PENDING",
        limit=10,
        offset=0,
    )
    connector.list_compensations(employee_id="e1")
    connector.list_teams(limit=10, offset=0)
    with pytest.raises(ValueError):
        connector.get_employee("")


# MARK: - Gusto


def _gusto() -> tuple[GustoToolSet, MockTransport]:
    transport = MockTransport()
    return GustoToolSet(access_token="t", transport=transport), transport


def test_gusto_requires_token() -> None:
    with pytest.raises(ValueError):
        GustoToolSet(access_token="")


def test_gusto_endpoints() -> None:
    connector, transport = _gusto()
    for _ in range(10):
        transport.enqueue(json_response({"data": []}))
    connector.list_companies()
    connector.get_company("c1")
    connector.list_employees("c1", terminated=False, page=1, per=10)
    connector.get_employee("e1")
    connector.create_employee(
        "c1",
        first_name="A",
        last_name="B",
        email="a@b",
    )
    connector.list_payrolls(
        "c1",
        processing_statuses=["paid"],
        page=1,
        per=10,
    )
    connector.get_payroll(company_uuid="c1", payroll_uuid="p1")
    connector.list_pay_schedules("c1")
    connector.list_time_off_requests("c1", status="approved", page=1, per=10)
    connector.list_jobs("e1")
    with pytest.raises(ValueError):
        connector.get_company("")
    with pytest.raises(ValueError):
        connector.list_employees("")
    with pytest.raises(ValueError):
        connector.get_employee("")
    with pytest.raises(ValueError):
        connector.create_employee("c1", first_name="", last_name="b", email="x")
    with pytest.raises(ValueError):
        connector.create_employee("", first_name="a", last_name="b", email="x")
    with pytest.raises(ValueError):
        connector.list_payrolls("")
    with pytest.raises(ValueError):
        connector.get_payroll(company_uuid="", payroll_uuid="p")
    with pytest.raises(ValueError):
        connector.list_pay_schedules("")
    with pytest.raises(ValueError):
        connector.list_time_off_requests("")
    with pytest.raises(ValueError):
        connector.list_jobs("")


# MARK: - Greenhouse


def _greenhouse() -> tuple[GreenhouseToolSet, MockTransport]:
    transport = MockTransport()
    return (
        GreenhouseToolSet(
            api_key="k",
            on_behalf_of="123",
            transport=transport,
        ),
        transport,
    )


def test_greenhouse_requires_key() -> None:
    with pytest.raises(ValueError):
        GreenhouseToolSet(api_key="")


def test_greenhouse_endpoints() -> None:
    connector, transport = _greenhouse()
    for _ in range(10):
        transport.enqueue(json_response({"id": 1}))
    connector.list_jobs(status="open", per_page=10, page=1)
    connector.get_job(1)
    connector.list_candidates(
        email="a@b",
        updated_after="2026-01-01",
        job_id=1,
        per_page=10,
        page=1,
    )
    connector.get_candidate(1)
    connector.create_candidate({"first_name": "A", "last_name": "B"})
    connector.list_applications(job_id=1, status="active", per_page=10, page=1)
    connector.advance_application(1, from_stage_id=10)
    connector.reject_application(1, rejection_reason_id=5, notes="not a fit")
    connector.list_scorecards(application_id=1, per_page=10, page=1)
    connector.list_offers(application_id=1, per_page=10, page=1)
    assert transport.requests[4].headers["On-Behalf-Of"] == "123"
    with pytest.raises(ValueError):
        connector.get_job(0)
    with pytest.raises(ValueError):
        connector.get_candidate(0)
    with pytest.raises(ValueError):
        connector.create_candidate({})
    with pytest.raises(ValueError):
        connector.advance_application(0, from_stage_id=1)
    with pytest.raises(ValueError):
        connector.advance_application(1, from_stage_id=0)
    with pytest.raises(ValueError):
        connector.reject_application(0, rejection_reason_id=1)
    with pytest.raises(ValueError):
        connector.reject_application(1, rejection_reason_id=0)


def test_greenhouse_writes_require_on_behalf_of() -> None:
    transport = MockTransport()
    no_obo = GreenhouseToolSet(api_key="k", transport=transport)
    with pytest.raises(ValueError):
        no_obo.create_candidate({"first_name": "A"})


# MARK: - Lever


def _lever() -> tuple[LeverToolSet, MockTransport]:
    transport = MockTransport()
    return LeverToolSet(api_key="k", transport=transport), transport


def test_lever_requires_key() -> None:
    with pytest.raises(ValueError):
        LeverToolSet(api_key="")


def test_lever_endpoints() -> None:
    connector, transport = _lever()
    for _ in range(10):
        transport.enqueue(json_response({"data": []}))
    connector.list_opportunities(
        contact_id="c",
        email="a@b",
        posting_id="p",
        stage_id="s",
        archived=True,
        limit=10,
        offset="cur",
    )
    connector.get_opportunity("o1")
    connector.create_opportunity(
        perform_as="u1",
        opportunity={"name": "Alice"},
    )
    connector.update_opportunity_stage(
        "o1",
        perform_as="u1",
        stage_id="s2",
    )
    connector.list_postings(
        state="published",
        location="SF",
        limit=10,
        offset="cur",
    )
    connector.get_posting("p1")
    connector.list_stages()
    connector.list_users(access_role="admin", limit=10, offset="cur")
    connector.list_feedback("o1", limit=10, offset="cur")
    connector.archive_opportunity(
        "o1",
        perform_as="u1",
        archive_reason_id="r1",
    )
    with pytest.raises(ValueError):
        connector.get_opportunity("")
    with pytest.raises(ValueError):
        connector.create_opportunity(perform_as="", opportunity={"x": 1})
    with pytest.raises(ValueError):
        connector.update_opportunity_stage("", perform_as="u", stage_id="s")
    with pytest.raises(ValueError):
        connector.get_posting("")
    with pytest.raises(ValueError):
        connector.list_feedback("")
    with pytest.raises(ValueError):
        connector.archive_opportunity("", perform_as="u", archive_reason_id="r")


# MARK: - Deel


def _deel() -> tuple[DeelToolSet, MockTransport]:
    transport = MockTransport()
    return DeelToolSet(api_token="t", transport=transport), transport


def test_deel_requires_token() -> None:
    with pytest.raises(ValueError):
        DeelToolSet(api_token="")


def test_deel_endpoints() -> None:
    connector, transport = _deel()
    for _ in range(10):
        transport.enqueue(json_response({"data": []}))
    connector.list_people(limit=10, offset=0, hiring_types=["contractor"])
    connector.get_person("p1")
    connector.list_contracts(
        types=["payg"],
        statuses=["in_progress"],
        limit=10,
        offset=0,
    )
    connector.get_contract("c1")
    connector.create_invoice_adjustment(
        contract_id="c1",
        amount=100.0,
        date_submission="2026-01-01",
        description="Bonus",
        adjustment_type="bonus",
    )
    connector.list_invoice_adjustments(
        contract_id="c1",
        limit=10,
        offset=0,
    )
    connector.list_time_off(
        "hp1",
        limit=10,
        offset=0,
    )
    connector.review_time_off("t1", approve=True)
    connector.list_payroll_events("le1", limit=10, offset=0)
    connector.list_legal_entities()
    with pytest.raises(ValueError):
        connector.get_person("")
    with pytest.raises(ValueError):
        connector.get_contract("")
    with pytest.raises(ValueError):
        connector.create_invoice_adjustment(
            contract_id="",
            amount=10.0,
            date_submission="a",
            description="x",
        )
    with pytest.raises(ValueError):
        connector.review_time_off("", approve=True)


# MARK: - Agent-ready summary tests


def _destructive_method_names(toolset: object) -> set[str]:
    """Return the names of @toolify methods on ``toolset`` flagged destructive."""
    names: set[str] = set()
    for name in dir(toolset):
        attr = getattr(toolset.__class__, name, None)
        spec = getattr(attr, "__maivn_toolify__", None) if attr is not None else None
        if spec is not None and getattr(spec, "destructive", False):
            names.add(name)
    return names


def test_workday_list_workers_returns_summaries_without_ids() -> None:
    connector, transport = _workday()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "wid-1",
                        "descriptor": "Alice Smith",
                        "primaryWorkEmail": "alice@example.com",
                        "primaryJob": {"descriptor": "Engineer"},
                        "hireDate": "2025-01-15",
                        "active": True,
                    }
                ],
                "total": 1,
            }
        )
    )
    result = connector.list_workers()
    assert result["workers"] == [
        {
            "worker_ref": "worker_1",
            "name": "Alice Smith",
            "email": "alice@example.com",
            "title": "Engineer",
            "hire_date": "2025-01-15",
            "is_active": True,
        }
    ]
    assert "worker_id" not in result["workers"][0]


def test_workday_list_workers_include_ids() -> None:
    connector, transport = _workday()
    transport.enqueue(
        json_response(
            {
                "data": [{"id": "wid-1", "descriptor": "Alice Smith"}],
                "total": 1,
            }
        )
    )
    result = connector.list_workers(include_ids=True)
    assert result["workers"][0]["worker_id"] == "wid-1"


def test_workday_list_candidates_returns_summaries() -> None:
    connector, transport = _workday()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "c1",
                        "descriptor": "Bob Jones",
                        "email": "bob@example.com",
                        "status": "Active",
                        "applicationDate": "2026-05-01",
                    }
                ]
            }
        )
    )
    result = connector.list_candidates()
    assert result["candidates"][0]["candidate_ref"] == "candidate_1"
    assert result["candidates"][0]["name"] == "Bob Jones"
    assert "candidate_id" not in result["candidates"][0]


def test_bamboo_list_employees_returns_summaries_without_ids() -> None:
    connector, transport = _bamboo()
    transport.enqueue(
        json_response(
            {
                "employees": [
                    {
                        "id": "42",
                        "firstName": "Alice",
                        "lastName": "Smith",
                        "displayName": "Alice S.",
                        "workEmail": "alice@example.com",
                        "jobTitle": "Engineer",
                        "department": "R&D",
                        "hireDate": "2024-03-01",
                        "status": "Active",
                    }
                ],
                "fields": [],
            }
        )
    )
    result = connector.list_employees()
    assert result["employees"] == [
        {
            "employee_ref": "employee_1",
            "name": "Alice S.",
            "email": "alice@example.com",
            "title": "Engineer",
            "department": "R&D",
            "hire_date": "2024-03-01",
            "status": "Active",
        }
    ]
    assert "employee_id" not in result["employees"][0]


def test_bamboo_list_employees_include_ids() -> None:
    connector, transport = _bamboo()
    transport.enqueue(
        json_response(
            {
                "employees": [
                    {"id": "42", "firstName": "Alice", "lastName": "Smith"},
                ],
            }
        )
    )
    result = connector.list_employees(include_ids=True)
    assert result["employees"][0]["employee_id"] == "42"


def test_bamboo_update_employee_accepts_summary_dict() -> None:
    connector, transport = _bamboo()
    transport.enqueue(json_response({"ok": True}))
    employee_from_list = {"employee_id": "42", "name": "Alice S."}
    connector.update_employee(employee_from_list, fields={"jobTitle": "Senior Engineer"})
    assert transport.requests[0].url.endswith("/v1/employees/42")


def test_rippling_list_employees_returns_summaries_without_ids() -> None:
    connector, transport = _rippling()
    transport.enqueue(
        json_response(
            [
                {
                    "id": "emp_1",
                    "firstName": "Alice",
                    "lastName": "Smith",
                    "workEmail": "alice@example.com",
                    "title": "Engineer",
                    "department": {"name": "R&D"},
                    "startDate": "2024-03-01",
                    "status": "ACTIVE",
                }
            ]
        )
    )
    result = connector.list_employees()
    assert result["employees"] == [
        {
            "employee_ref": "employee_1",
            "name": "Alice Smith",
            "email": "alice@example.com",
            "title": "Engineer",
            "department": "R&D",
            "hire_date": "2024-03-01",
            "status": "ACTIVE",
        }
    ]
    assert "employee_id" not in result["employees"][0]


def test_rippling_list_employees_include_ids() -> None:
    connector, transport = _rippling()
    transport.enqueue(
        json_response(
            [
                {
                    "id": "emp_1",
                    "firstName": "Alice",
                    "lastName": "Smith",
                }
            ]
        )
    )
    result = connector.list_employees(include_ids=True)
    assert result["employees"][0]["employee_id"] == "emp_1"


def test_gusto_list_employees_returns_summaries_without_ids() -> None:
    connector, transport = _gusto()
    transport.enqueue(
        json_response(
            [
                {
                    "uuid": "u1",
                    "first_name": "Alice",
                    "last_name": "Smith",
                    "email": "alice@example.com",
                    "jobs": [{"title": "Engineer"}],
                    "department": "R&D",
                    "current_employment_status_date": "2024-03-01",
                    "terminated": False,
                }
            ]
        )
    )
    result = connector.list_employees("c1")
    assert result["employees"][0]["name"] == "Alice Smith"
    assert result["employees"][0]["email"] == "alice@example.com"
    assert result["employees"][0]["title"] == "Engineer"
    assert result["employees"][0]["is_terminated"] is False
    assert "employee_id" not in result["employees"][0]


def test_gusto_list_employees_include_ids() -> None:
    connector, transport = _gusto()
    transport.enqueue(
        json_response(
            [{"uuid": "u1", "first_name": "Alice", "last_name": "Smith"}],
        )
    )
    result = connector.list_employees("c1", include_ids=True)
    assert result["employees"][0]["employee_id"] == "u1"


def test_greenhouse_list_candidates_returns_summaries_without_ids() -> None:
    connector, transport = _greenhouse()
    transport.enqueue(
        json_response(
            [
                {
                    "id": 11,
                    "first_name": "Bob",
                    "last_name": "Jones",
                    "email_addresses": [{"value": "bob@example.com", "type": "personal"}],
                    "title": "Senior Engineer",
                    "company": "Acme",
                    "application_date": "2026-05-01",
                }
            ]
        )
    )
    result = connector.list_candidates()
    assert result["candidates"] == [
        {
            "candidate_ref": "candidate_1",
            "name": "Bob Jones",
            "email": "bob@example.com",
            "title": "Senior Engineer",
            "company": "Acme",
            "application_date": "2026-05-01",
        }
    ]
    assert "candidate_id" not in result["candidates"][0]


def test_greenhouse_list_candidates_include_ids() -> None:
    connector, transport = _greenhouse()
    transport.enqueue(json_response([{"id": 11, "first_name": "Bob", "last_name": "Jones"}]))
    result = connector.list_candidates(include_ids=True)
    assert result["candidates"][0]["candidate_id"] == 11


def test_greenhouse_list_jobs_returns_summaries_without_ids() -> None:
    connector, transport = _greenhouse()
    transport.enqueue(
        json_response(
            [
                {
                    "id": 7,
                    "name": "Engineer",
                    "status": "open",
                    "offices": [{"name": "SF"}, {"name": "Remote"}],
                    "opened_at": "2026-01-01",
                    "closed_at": None,
                }
            ]
        )
    )
    result = connector.list_jobs()
    assert result["jobs"][0]["job_ref"] == "job_1"
    assert result["jobs"][0]["name"] == "Engineer"
    assert result["jobs"][0]["office_names"] == ["SF", "Remote"]
    assert "job_id" not in result["jobs"][0]


def test_greenhouse_reject_application_accepts_summary_dict() -> None:
    connector, transport = _greenhouse()
    transport.enqueue(json_response({"ok": True}))
    application_from_list = {"application_id": 42, "candidate_name": "Bob"}
    connector.reject_application(application_from_list, rejection_reason_id=5)
    assert transport.requests[0].url.endswith("/v1/applications/42/reject")


def test_lever_list_opportunities_returns_summaries_without_ids() -> None:
    connector, transport = _lever()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "opp-1",
                        "name": "Bob Jones",
                        "emails": ["bob@example.com"],
                        "headline": "Senior Engineer at Acme",
                        "stage": {"text": "Phone Screen"},
                        "createdAt": 1700000000,
                    }
                ],
                "hasNext": True,
                "next": "cur-2",
            }
        )
    )
    result = connector.list_opportunities()
    assert result["candidates"][0]["candidate_ref"] == "candidate_1"
    assert result["candidates"][0]["name"] == "Bob Jones"
    assert result["candidates"][0]["email"] == "bob@example.com"
    assert result["candidates"][0]["stage"] == "Phone Screen"
    assert "opportunity_id" not in result["candidates"][0]
    assert result["hasNext"] is True
    assert result["next"] == "cur-2"


def test_lever_list_opportunities_include_ids() -> None:
    connector, transport = _lever()
    transport.enqueue(
        json_response(
            {
                "data": [{"id": "opp-1", "name": "Bob Jones"}],
                "hasNext": False,
            }
        )
    )
    result = connector.list_opportunities(include_ids=True)
    assert result["candidates"][0]["opportunity_id"] == "opp-1"


def test_lever_list_postings_returns_summaries_without_ids() -> None:
    connector, transport = _lever()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "p1",
                        "text": "Senior Engineer",
                        "state": "published",
                        "categories": {
                            "team": "Platform",
                            "department": "Engineering",
                            "location": "SF",
                            "commitment": "Full-time",
                        },
                        "createdAt": 1700000000,
                    }
                ],
                "hasNext": False,
            }
        )
    )
    result = connector.list_postings()
    assert result["jobs"][0]["job_ref"] == "job_1"
    assert result["jobs"][0]["title"] == "Senior Engineer"
    assert result["jobs"][0]["team"] == "Platform"
    assert "posting_id" not in result["jobs"][0]


def test_deel_list_people_returns_summaries_without_ids() -> None:
    connector, transport = _deel()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "person-1",
                        "first_name": "Alice",
                        "last_name": "Smith",
                        "emails": [{"value": "alice@example.com"}],
                        "job_title": "Engineer",
                        "department": "R&D",
                        "hiring_status": "active",
                        "hiring_type": "employee",
                        "start_date": "2024-03-01",
                    }
                ]
            }
        )
    )
    result = connector.list_people()
    assert result["employees"][0]["employee_ref"] == "employee_1"
    assert result["employees"][0]["name"] == "Alice Smith"
    assert result["employees"][0]["email"] == "alice@example.com"
    assert result["employees"][0]["title"] == "Engineer"
    assert "person_id" not in result["employees"][0]


def test_deel_list_people_include_ids() -> None:
    connector, transport = _deel()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {"id": "person-1", "first_name": "Alice", "last_name": "Smith"},
                ]
            }
        )
    )
    result = connector.list_people(include_ids=True)
    assert result["employees"][0]["person_id"] == "person-1"


def test_deel_list_contracts_returns_summaries() -> None:
    connector, transport = _deel()
    transport.enqueue(
        json_response(
            {
                "data": [
                    {
                        "id": "ctr-1",
                        "title": "Contractor",
                        "type": "payg",
                        "status": "in_progress",
                        "worker": {"full_name": "Alice Smith"},
                        "country": "US",
                        "start_date": "2025-01-01",
                    }
                ]
            }
        )
    )
    result = connector.list_contracts()
    assert result["contracts"][0]["contract_ref"] == "contract_1"
    assert result["contracts"][0]["title"] == "Contractor"
    assert result["contracts"][0]["worker_name"] == "Alice Smith"
    assert "contract_id" not in result["contracts"][0]


# MARK: - Destructive tool tagging


def test_greenhouse_reject_application_is_tagged_destructive() -> None:
    connector, _ = _greenhouse()
    assert "reject_application" in _destructive_method_names(connector)


def test_lever_archive_opportunity_is_tagged_destructive() -> None:
    connector, _ = _lever()
    assert "archive_opportunity" in _destructive_method_names(connector)
