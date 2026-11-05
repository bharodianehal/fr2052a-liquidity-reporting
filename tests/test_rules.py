"""The business rules: calendar and due dates, dates accepted by the API, sign-off transitions, step 5 gating, wording."""
import datetime

import pytest
from fastapi import HTTPException

from conftest import Request, main, wb, agents


# ─── calendar ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("as_of, primary", [
    ("2026-02-27", "2026-03-03"),   # Friday -> Tuesday (weekend skipped)
    ("2026-02-24", "2026-02-26"),   # Tuesday -> Thursday
    ("2026-02-12", "2026-02-17"),   # Thursday -> Tuesday: Friday 13, then Presidents Day (Mon 16) is a Fed holiday
    ("2026-12-23", "2026-12-28"),   # Wednesday -> Monday: Christmas (Fri 25) and the weekend skipped
])
def test_primary_due_is_t_plus_2_business_days(as_of, primary):
    assert main._due_dates(as_of)["primary"] == primary


def test_reduced_due_is_t_plus_15_calendar_days():
    assert main._due_dates("2026-02-27")["reduced"] == "2026-03-14"


def test_source_fix_due_dates_skip_fed_holidays(deps):
    deps()
    assert agents._bdays("2026-02-13", 1) == datetime.date(2026, 2, 17)   # Friday + 1 business day, over Presidents Day
    assert agents._bdays("2026-02-23", 5) == datetime.date(2026, 3, 2)


# ─── dates the API accepts ────────────────────────────────────────────────
@pytest.mark.parametrize("path, query, code", [
    ({"date": "abc"}, {}, 400),
    ({"date": "2026-02-30"}, {}, 400),
    ({"date": "2025-01-01"}, {}, 404),          # not a reporting date of this deployment
    ({"date": "2026-02-22"}, {}, 404),          # a Sunday
    ({}, {"start": "x", "end": "2026-02-27"}, 400),
])
def test_check_dates_refuses(path, query, code):
    with pytest.raises(HTTPException) as e:
        main.check_dates(Request(path, query))
    assert e.value.status_code == code


def test_check_dates_accepts_a_reporting_date_and_routes_without_dates():
    main.check_dates(Request({"date": "2026-02-27"}, {"start": "2026-02-23", "end": "2026-02-27"}))
    main.check_dates(Request({"break_id": "BRK-0227-001"}))


def test_workbench_check_date_is_a_400_not_a_500():
    with pytest.raises(HTTPException) as e:
        wb._check_date("27/02/2026")
    assert e.value.status_code == 400


def test_pipeline_run_only_for_reporting_dates(monkeypatch):
    monkeypatch.setattr(main, "DAILY_JOB_ID", "1")
    monkeypatch.setattr(main, "get_ws", lambda: pytest.fail("a job was started"))
    for date, code in (("2030-01-01", 404), ("2026-02-22", 404), ("nope", 400)):
        with pytest.raises(HTTPException) as e:
            main.run_pipeline({"date": date, "scope": "both"}, Request())
        assert e.value.status_code == code


# ─── sign-off ─────────────────────────────────────────────────────────────
def test_submitted_only_from_approved_and_final():
    assert main.TRANSITIONS["SUBMITTED"] == {"APPROVED"}
    assert all("SUBMITTED" not in allowed for allowed in main.TRANSITIONS.values())   # nothing leaves SUBMITTED


def test_approval_only_from_ready_or_override():
    assert main.TRANSITIONS["APPROVED"] == {"READY_FOR_REVIEW", "OVERRIDE_REQUESTED"}
    assert "BLOCKED" not in main.TRANSITIONS["APPROVED"]


@pytest.mark.parametrize("data, code", [({"action": "XYZ"}, 400), ({"action": "REJECTED"}, 400), ({"action": "OVERRIDE_REQUESTED"}, 400)])
def test_review_submission_input(data, code):
    with pytest.raises(HTTPException) as e:
        main.review_submission("2026-02-27", data, Request())
    assert e.value.status_code == code


# ─── step 5 gating ────────────────────────────────────────────────────────
def test_generate_waits_for_steps_1_to_4(monkeypatch):
    monkeypatch.setattr(wb, "GENERATE_JOB_ID", "1")
    steps = [{"title": t, "open": 0, "open_label": "", "waiting": 0, "waiting_label": ""} for t in ("Collect", "Data quality", "PID enrichment", "Validate", "Release")]
    steps[3].update(open=2, open_label="2 comments to review")
    monkeypatch.setattr(agents, "review_state", lambda d: {"steps": steps})
    with pytest.raises(HTTPException) as e:
        wb.generate("2026-02-27", Request())
    assert e.value.status_code == 409 and "Validate: 2 comments to review" in e.value.detail


# ─── wording ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("n, word, out", [(1, "approved fix", "1 approved fix"), (2, "approved fix", "2 approved fixes"),
                                          (0, "comment", "0 comments"), (3, "exception", "3 exceptions"), (2, "class", "2 classes")])
def test_plural(n, word, out):
    assert agents.plural(n, word) == out
