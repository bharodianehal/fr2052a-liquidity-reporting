"""The checker's controls: a decision is made once, on an item that exists, with its evidence - and refused requests write nothing."""
import pytest
from fastapi import HTTPException

from conftest import Request, wb, agents

OPEN = {"rule_id": "PSV-14", "item_key": "ENT001|O.D.1", "record_key": "rk1", "position_id": "P1", "state": "open"}


# ─── Validate: resolve an exception ───────────────────────────────────────
def resolve(deps, monkeypatch, body, queue=(OPEN,), answers=None):
    d = deps(answers)
    monkeypatch.setattr(wb, "validate_queue", lambda date: list(queue))
    try:
        wb.validate_resolve("2026-02-27", {"rule_id": "PSV-14", "item_key": "ENT001|O.D.1", **body}, Request())
    finally:
        pass
    return d


@pytest.mark.parametrize("body, queue, code", [
    ({"action": "bogus", "note": "x"}, (OPEN,), 400),
    ({"action": "explain", "note": "x", "item_key": "not-on-this-date"}, (OPEN,), 404),
    ({"action": "explain", "note": "x"}, ({**OPEN, "state": "explained"},), 409),
    ({"action": "explain"}, (OPEN,), 400),                       # an explanation needs the explanation
    ({"action": "manual"}, (OPEN,), 400),                        # a manual fix needs a note
    ({"action": "manual", "note": "fixed the maturity"}, (OPEN,), 409),   # ... and the correction behind it
])
def test_validate_resolve_refuses_and_writes_nothing(deps, monkeypatch, body, queue, code):
    d = deps()
    monkeypatch.setattr(wb, "validate_queue", lambda date: list(queue))
    with pytest.raises(HTTPException) as e:
        wb.validate_resolve("2026-02-27", {"rule_id": "PSV-14", "item_key": "ENT001|O.D.1", **body}, Request())
    assert e.value.status_code == code
    assert not d.conn.sql, "a refused decision wrote to Lakebase"


def test_validate_manual_with_its_correction_is_recorded(deps, monkeypatch):
    d = deps({"FROM position_corrections": [{"?column?": 1}]})
    monkeypatch.setattr(wb, "validate_queue", lambda date: [OPEN])
    wb.validate_resolve("2026-02-27", {"rule_id": "PSV-14", "item_key": "ENT001|O.D.1", "action": "manual", "note": "fixed"}, Request())
    assert any(s.startswith("INSERT INTO validation_decisions") for s in d.conn.sql) and d.conn.commits == 1


# ─── AI suggestions: one decision each, never overwritten ──────────────────
SUG = {"suggestion_id": "s1", "as_of_date": "2026-02-27", "suggestion_type": "COMMENT_DRAFT", "subject_key": "S.B", "subject": "S.B", "suggestion": "{}"}


def test_ai_decision_is_insert_only(deps):
    d = deps({"FROM ai_suggestions": [SUG]}, fetch=[("s1",)])
    wb.ai_decide("s1", {"decision": "ACCEPTED"}, Request())
    ins = [s for s in d.conn.sql if s.startswith("INSERT INTO ai_decisions")]
    assert ins and "DO NOTHING" in ins[0] and "DO UPDATE" not in ins[0]


def test_second_ai_decision_is_refused(deps):
    d = deps({"FROM ai_suggestions": [SUG]}, fetch=[None])      # the INSERT ... DO NOTHING returned no row: already decided
    with pytest.raises(HTTPException) as e:
        wb.ai_decide("s1", {"decision": "REJECTED", "note": "changed my mind"}, Request())
    assert e.value.status_code == 409 and d.conn.rollbacks == 1 and d.conn.commits == 0


@pytest.mark.parametrize("data, code", [({"decision": "MAYBE"}, 400), ({"decision": "REJECTED"}, 400)])
def test_ai_decision_input(deps, data, code):
    deps({"FROM ai_suggestions": [SUG]})
    with pytest.raises(HTTPException) as e:
        wb.ai_decide("s1", data, Request())
    assert e.value.status_code == code


# ─── the checker on an agent's proposal ────────────────────────────────────
BRK = {"break_id": "BRK-0227-001", "as_of_date": "2026-02-27", "status": "PROPOSED"}
PR = {"proposal_id": "PR-0227-001-v1", "action": {"kind": "validate"}, "sources": []}


def decide(deps, monkeypatch, data, fetch, brk=BRK):
    d = deps({"FROM breaks WHERE break_id": [brk]}, fetch=fetch)
    monkeypatch.setattr(agents, "_latest", lambda m, ids: {ids[0]: PR})
    applied = []
    monkeypatch.setattr(agents, "_apply", lambda *a: applied.append(a))
    monkeypatch.setattr(agents, "_event", lambda *a, **k: None)
    return d, applied


def test_decision_claims_the_break_before_applying(deps, monkeypatch):
    d, applied = decide(deps, monkeypatch, None, fetch=[("BRK-0227-001",)])
    agents._decide("BRK-0227-001", {"action": "approve", "reason_code": "RC-05"}, Request())
    assert applied and "AND status = %s RETURNING" in d.conn.sql[0]
    assert any(s.startswith("INSERT INTO break_decisions") for s in d.conn.sql)


def test_two_checkers_at_once_only_one_decides(deps, monkeypatch):
    d, applied = decide(deps, monkeypatch, None, fetch=[None])   # the other checker claimed it first
    with pytest.raises(HTTPException) as e:
        agents._decide("BRK-0227-001", {"action": "approve", "reason_code": "RC-05"}, Request())
    assert e.value.status_code == 409 and not applied
    assert not any(s.startswith("INSERT INTO break_decisions") for s in d.conn.sql)


def test_failed_apply_puts_the_break_back(deps, monkeypatch):
    d, _ = decide(deps, monkeypatch, None, fetch=[("BRK-0227-001",), ("BRK-0227-001",)])
    monkeypatch.setattr(agents, "_apply", lambda *a: (_ for _ in ()).throw(HTTPException(400, "bad fix")))
    with pytest.raises(HTTPException):
        agents._decide("BRK-0227-001", {"action": "approve", "reason_code": "RC-05"}, Request())
    assert len([s for s in d.conn.sql if s.startswith("UPDATE breaks")]) == 2   # claimed, then released
    assert not any(s.startswith("INSERT INTO break_decisions") for s in d.conn.sql)


@pytest.mark.parametrize("data, brk, code", [
    ({"action": "approve", "reason_code": "NOPE"}, BRK, 400),
    ({"action": "return", "reason_code": "RT-04"}, BRK, 400),             # a return needs the reason in words
    ({"action": "approve", "reason_code": "RC-05"}, {**BRK, "status": "APPROVED"}, 409),
])
def test_decision_input(deps, monkeypatch, data, brk, code):
    d, applied = decide(deps, monkeypatch, None, fetch=[], brk=brk)
    with pytest.raises(HTTPException) as e:
        agents._decide("BRK-0227-001", data, Request())
    assert e.value.status_code == code and not applied and not d.conn.sql


def test_identifiers_are_whitelisted():
    for bad in ("x' OR '1'='1", "a;DROP TABLE x", "", None):
        with pytest.raises(HTTPException):
            wb._safe_id(bad)
    assert wb._safe_id("DEP-2026-02-27-BAD02") == "DEP-2026-02-27-BAD02"


# ─── straight-through processing and the checker's spot check ──────────────
def test_only_the_agents_use_the_straight_through_code(deps, monkeypatch):
    d, applied = decide(deps, monkeypatch, None, fetch=[("BRK-0227-001",)])
    with pytest.raises(HTTPException) as e:   # a person cannot approve "straight through"
        agents._decide("BRK-0227-001", {"action": "approve", "reason_code": agents.STP_CODE}, Request())
    assert e.value.status_code == 400 and not applied
    agents._decide("BRK-0227-001", {"action": "approve", "reason_code": agents.STP_CODE, "note": agents.STP_NOTE}, agents._AgentRequest())
    assert applied


def test_straight_through_applies_only_qualifying_proposals(monkeypatch):
    done = []
    monkeypatch.setattr(agents, "breaks", lambda date, sync=True: [
        {"break_id": "A", "status": "PROPOSED", "bulk_ok": True}, {"break_id": "B", "status": "PROPOSED", "bulk_ok": False},
        {"break_id": "C", "status": "APPROVED", "bulk_ok": True}])
    monkeypatch.setattr(agents, "_decide", lambda bid, data, req: done.append((bid, data["reason_code"], wb._user(req))))
    assert agents.straight_through("2026-02-27")["applied"] == ["A"]
    assert done == [("A", agents.STP_CODE, agents.AGENT_ACTOR)]


STP_DEC = {"break_id": "BRK-0227-001", "proposal_id": "PR-0227-001-v1", "action": "APPROVE", "reason_code": "STP", "decided_by": "fr2052a agents (straight-through)"}


@pytest.mark.parametrize("decisions, data, user, code", [
    ([], {"verdict": "confirm"}, "checker@bank.com", 409),                                             # not applied straight through
    ([STP_DEC, {**STP_DEC, "action": "SPOT_CHECK_CONFIRM"}], {"verdict": "confirm"}, "checker@bank.com", 409),   # already spot-checked
    ([STP_DEC], {"verdict": "maybe"}, "checker@bank.com", 400),
    ([STP_DEC], {"verdict": "disagree"}, "checker@bank.com", 400),                                     # disagreeing needs the reason
    ([STP_DEC], {"verdict": "confirm"}, "fr2052a agents (straight-through)", 403),                    # the agents cannot check themselves
])
def test_spot_check_refuses(deps, monkeypatch, decisions, data, user, code):
    d = deps({"FROM breaks WHERE break_id": [BRK], "FROM break_decisions": decisions})
    with pytest.raises(HTTPException) as e:
        agents.spot_check("BRK-0227-001", data, Request(user=user))
    assert e.value.status_code == code and not d.conn.sql


def test_spot_check_is_recorded(deps, monkeypatch):
    d = deps({"FROM breaks WHERE break_id": [BRK], "FROM break_decisions": [STP_DEC]})
    monkeypatch.setattr(agents, "_event", lambda *a, **k: None)
    r = agents.spot_check("BRK-0227-001", {"verdict": "disagree", "note": "wrong counterparty"}, Request())
    assert r["verdict"] == "disagree" and any("INSERT INTO break_decisions" in s for s in d.conn.sql)


# ─── checker feedback goes on the trace of the proposal the checker saw ────
def test_feedback_goes_on_the_trace_before_the_decision(monkeypatch):
    import datetime as dt
    import types
    import agent_tracing as at
    t = lambda tid, ms: types.SimpleNamespace(info=types.SimpleNamespace(trace_id=tid, request_time=ms, assessments=[],
                                              tags={"fr2052a.as_of_date": "2026-02-23", "fr2052a.source_kind": "validate", "fr2052a.source_ref": "R|K"}))
    utc = lambda h, mi: dt.datetime(2026, 11, 2, h, mi)
    ms = lambda h, mi: int(utc(h, mi).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    traces = [t("v1", ms(18, 0)), t("v2", ms(20, 10))]          # the pipeline's proposal, then the one made after the return
    monkeypatch.setattr(at.mlflow, "search_traces", lambda **k: traces)
    logged = []
    monkeypatch.setattr(at.mlflow, "log_feedback", lambda **k: logged.append((k["trace_id"], k["value"])))
    rows = [{"source_kind": "validate", "source_ref": "R|K", "decision_id": "d1", "action": "RETURN", "reason_code": "RT-04", "note": "", "decided_by": "c", "edits": None, "decided_at": utc(20, 5)},
            {"source_kind": "validate", "source_ref": "R|K", "decision_id": "d2", "action": "APPROVE", "reason_code": "RC-05", "note": "", "decided_by": "c", "edits": None, "decided_at": utc(20, 15)}]
    m = types.SimpleNamespace(run_pg=lambda sql, p=None: rows)
    at.log_checker_feedback(m, "2026-02-23", "1")
    assert [x[0] for x in logged] == ["v1", "v2"]   # the return on the first proposal, the approval on the second


# ─── Collect: ask the source to re-send a short feed ───────────────────────
class _Ws:
    def __init__(self):
        self.calls = []
        self.api_client = self

    def do(self, method, path, body=None, query=None):
        self.calls.append((method, path, body))
        return {"run_id": 42}


def resend(deps, feed, status):
    d = deps({"FROM feed_monitor": [{"feed": "funding", "status": status}, {"feed": "comments", "status": "FAIL"}]})
    d.ws, d.DAILY_JOB_ID = _Ws(), "1"
    d.get_ws, d._no_active_run = (lambda: d.ws), (lambda date: None)
    return d, wb.collect_resend("2026-02-23", feed, Request())


@pytest.mark.parametrize("feed, status, code", [("funding", "PASS", 409), ("comments", "FAIL", 404), ("nosuch", "FAIL", 404)])
def test_resend_only_a_short_position_feed(deps, feed, status, code):
    with pytest.raises(HTTPException) as e:
        resend(deps, feed, status)
    assert e.value.status_code == code


def test_resend_reruns_the_day_with_the_feed(deps):
    d, out = resend(deps, "funding", "FAIL")
    params = d.ws.calls[0][2]["job_parameters"]
    assert out == {"run_id": "42"} and params["resend_feed"] == "funding" and params["ingest"] == "true" and params["as_of_date"] == "2026-02-23"
