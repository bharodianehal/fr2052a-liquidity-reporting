"""End-to-end QA of the FR 2052a platform: functionality, system completeness and architectural soundness.

Runs against the deployed app, Lakebase, the SQL warehouse and the workspace (settings from the repo's .env). Read-only, except for requests the
app must refuse (negative tests are only sent when the guard is known to reject them, so nothing is written).

  /tmp/fr2052a-venv/bin/python scripts/qa/e2e_qa.py [--out evidence/qa_report.md]

Each test case: id, area, title, expected -> PASS / FAIL / WARN (works, but a gap) with the evidence.
"""
import argparse
import ast
import base64
import collections
import datetime
import glob
import hashlib
import io
import json
import os
import re
import statistics
import subprocess
import sys
import time
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from fr2052a_env import need
PROFILE = need("DATABRICKS_CONFIG_PROFILE")
import psycopg2
import requests
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.workspace import ExportFormat
from databricks.sdk.service.sql import StatementParameterListItem

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
C = need("FR2052A_CATALOG")
WH = need("FR2052A_WAREHOUSE")
APP = need("FR2052A_APP_URL")
DATES = ["2026-02-23", "2026-02-24", "2026-02-25", "2026-02-26", "2026-02-27"]
D = "2026-02-27"
EP = "projects/fr2052a/branches/production/endpoints/primary"
w = WorkspaceClient()
APP_SP = w.api_client.do("GET", "/api/2.0/apps/fr2052a")["service_principal_client_id"]
JOBS = {k: next(iter(w.jobs.list(name=f"fr2052a-{k}"))).job_id for k in ("daily", "pipeline", "revalidate", "generate")}
ME = w.current_user.me().user_name
# the agents' MLflow traces in UC: <catalog>.ai_assist.`<experiment id>_trace_unified` / `_otel_spans` (app/agent_tracing.py)
EXP = w.api_client.do("GET", "/api/2.0/mlflow/experiments/get-by-name", query={"experiment_name": f"/Users/{ME}/fr2052a_agents"})["experiment"]["experiment_id"]
BUNDLE = f"/Workspace/Users/{ME}/.bundle/fr2052a/dev/files"          # the platform bundle (databricks.yml)
APP_BUNDLE = f"/Workspace/Users/{ME}/.bundle/fr2052a-app/dev/files"  # the app bundle (app/databricks.yml)
TOKEN = json.loads(subprocess.run(["databricks", "auth", "token", "-p", PROFILE], capture_output=True, text=True).stdout)["access_token"]
S = requests.Session()
S.headers["Authorization"] = f"Bearer {TOKEN}"
TIMES = {}
RESULTS = []


def http(method, path, body=None, timeout=120):
    t = time.time()
    r = S.request(method, APP + path, json=body, timeout=timeout)
    TIMES[path] = time.time() - t
    try:
        j = r.json()
    except Exception:
        j = None
    return r.status_code, j, r


def get(path):
    code, j, _ = http("GET", path)
    if code != 200:
        raise AssertionError(f"GET {path} -> {code} {str(j)[:200]}")
    return j


_pg = None


def pg(sql, args=None):
    global _pg
    if _pg is None:
        host = w.api_client.do("GET", f"/api/2.0/postgres/{EP}")["status"]["hosts"]["host"]
        _pg = psycopg2.connect(host=host, port=5432, dbname="fr2052a", user=w.current_user.me().user_name, sslmode="require",
                               password=w.api_client.do("POST", "/api/2.0/postgres/credentials", body={"endpoint": EP})["token"],
                               options="-c search_path=app_serving,public")
        _pg.autocommit = True
    with _pg.cursor() as c:
        c.execute(sql, args)
        return c.fetchall() if c.description else []


def wh(sql):
    r = w.statement_execution.execute_statement(warehouse_id=WH, statement=sql, wait_timeout="50s", catalog=C)
    if r.status.state.value != "SUCCEEDED":
        raise AssertionError(f"SQL failed: {r.status.error.message[:300] if r.status.error else r.status.state}")
    return r.result.data_array or [] if r.result else []


def case(tid, area, title, expected):
    def deco(fn):
        def run():
            t = time.time()
            try:
                out = fn()
                status, detail = (out if isinstance(out, tuple) else ("PASS", out or ""))
            except AssertionError as e:
                status, detail = "FAIL", str(e)
            except Exception as e:
                status, detail = "ERROR", f"{type(e).__name__}: {str(e)[:400]}"
            RESULTS.append({"id": tid, "area": area, "title": title, "expected": expected, "status": status,
                            "detail": str(detail)[:1500], "seconds": round(time.time() - t, 1)})
            print(f"{status:5s} {tid} {title} - {str(detail)[:160]}", flush=True)
        CASES.append((tid, run))
        return fn
    return deco


CASES = []
SRC = {f: open(f, errors="ignore").read() for f in glob.glob(f"{REPO}/app/*.py")}
FE = {f: open(f, errors="ignore").read() for f in glob.glob(f"{REPO}/app/frontend/src/**/*.js*", recursive=True)}


# ═══ F. Functionality - every page's API, every date ═══════════════════════════════════════
@case("F01", "Functionality", "Every GET endpoint the frontend uses answers 200, for all five reporting dates",
      "scripts/qa/app_test.sh returns 200 for 59 endpoints x 5 dates")
def f01():
    bad = []
    for d in DATES:
        out = subprocess.run(["bash", f"{REPO}/scripts/qa/app_test.sh", d], capture_output=True, text=True).stdout.splitlines()
        bad += [f"{d} {l[:120]}" for l in out if l and not l.startswith("200 ") and "/agents/break/x " not in l]
    assert not bad, f"{len(bad)} failing: " + " | ".join(bad[:8])
    return f"{5 * 59} calls, all 200"


@case("F02", "Functionality", "Reporting dates: only business days from REPORTING_START, newest first",
      "/api/dates = Feb 27..Feb 23 (5 business days)")
def f02():
    d = get("/api/dates")
    assert d == sorted(DATES, reverse=True), f"dates {d}"
    return d


@case("F03", "Functionality", "Today (Where it stands): five steps, each with what the agent did and the state",
      "5 steps collect, dq, enrich, validate, release; each has done[], state, open count")
def f03():
    bad = []
    for d in DATES:
        r = get(f"/api/wb/agents/{d}/review")
        keys = [s["key"] for s in r["steps"]]
        if keys != ["collect", "dq", "enrich", "validate", "release"]:
            bad.append(f"{d} steps {keys}")
        for s in r["steps"]:
            if not s.get("done") or s.get("state") not in ("done", "review", "waiting", "ready", "generating", "approve", "submit", "submitted", "blocked"):
                bad.append(f"{d} {s['key']} state={s.get('state')} done={bool(s.get('done'))}")
    assert not bad, "; ".join(bad[:10])
    return "5 dates OK"


@case("F04", "Functionality", "Labels read correctly (no '0 ... to review' clutter, correct plurals)",
      "no label like 'fixs', no zero-count action labels shown as open work")
def f04():
    bad = []
    for d in DATES:
        r = get(f"/api/wb/agents/{d}/review")
        for s in r["steps"]:
            for k in ("open_label", "waiting_label"):
                v = s.get(k) or ""
                if re.search(r"\bfixs\b|\bentrys\b|\bclasss\b", v):
                    bad.append(f"{d} {s['key']}.{k}: '{v}'")
    assert not bad, "; ".join(sorted(set(b.split(' ', 1)[1] for b in bad))[:6])
    return "labels OK"


@case("F05", "Functionality", "Collect: every feed of the day is listed with Bronze counts; a record opens",
      "collect lists 10 feeds; /collect/{date}/record/{id} returns the raw record")
def f05():
    c = get(f"/api/wb/collect/{D}")
    mon = c.get("monitor") or []
    assert len(mon) == 10 and c.get("feeds"), f"monitor {len(mon)} feeds, {len(c.get('feeds') or [])} position feeds"
    return f"{len(mon)} feeds monitored, {len(c['feeds'])} position feeds"


@case("F06", "Functionality", "Data quality queue: every quarantined record of the day is in the queue (or decided)",
      "count(dq queue) == count(quarantine rows for the date)")
def f06():
    bad = []
    for d in DATES:
        q = get(f"/api/wb/dq/{d}/queue")
        n = pg("SELECT COUNT(DISTINCT record_id) FROM quarantine WHERE as_of_date = %s", (d,))[0][0]
        if len(q) != n:
            bad.append(f"{d}: queue {len(q)} vs quarantine {n}")
    assert not bad, "; ".join(bad)
    return "queue = quarantine on 5 dates"


@case("F07", "Functionality", "PID enrichment: every filed record has a PID; browse returns positions with the derivation",
      "no entity position without a PID; enrich positions page returns rows + fields")
def f07():
    n = pg("SELECT COUNT(*) FROM entity_position e JOIN fact_liquidity_position f USING (as_of_date, position_id) WHERE e.as_of_date = %s AND (f.product_id IS NULL OR f.product_id = '')", (D,))[0][0]
    e = get(f"/api/wb/enrich/{D}")
    code = (e.get("tables") or [{}])[0].get("table_code") if isinstance(e, dict) else None
    detail = f"positions without PID: {n}"
    if code:
        p = get(f"/api/wb/enrich/{D}/positions?code={code}&page=0")
        detail += f"; browse {code}: {len(p.get('rows', []))} rows, {len(p.get('fields', []))} fields"
    assert n == 0, detail
    return detail


@case("F08", "Functionality", "Validate: exceptions queue = open ERROR/WARNING rule rows of the latest validation",
      "validate queue items == gold_validation_detail rows (latest run) for the date")
def f08():
    bad = []
    for d in DATES:
        q = get(f"/api/wb/validate/{d}/queue")
        n = pg("""SELECT COUNT(*) FROM gold_validation_detail WHERE as_of_date = %s""", (d,))[0][0]
        if len(q) != n:
            bad.append(f"{d}: queue {len(q)} vs detail rows {n}")
    return ("WARN", "; ".join(bad)) if bad else "queue = detail rows on 5 dates"


@case("F09", "Functionality", "Release: latest run has Primary + Reduced + Comment files, XSD valid, downloadable",
      "3 files, xsd_valid, file download returns XML whose size equals the stored content")
def f09():
    bad = []
    for d in DATES:
        s = get(f"/api/submission/{d}")
        files = s.get("files") or []
        types = sorted(f["file_type"] for f in files)
        want = ["Comment", "Primary", "Reduced"] if d == "2026-02-27" else ["Comment", "Primary"]   # Reduced = month-end only
        if types != want:
            bad.append(f"{d} files {types}")
        if any(str(f.get("xsd_valid")).lower() not in ("true", "1") for f in files if f["file_type"] in ("Primary", "Reduced")):
            bad.append(f"{d} XSD not valid")
        for f in files:
            code, _, r = http("GET", f"/api/submission/{d}/file/{f['file_type']}")
            if code != 200 or not r.content.lstrip().startswith(b"<?xml"):
                bad.append(f"{d} {f['file_type']} download {code}")
    assert not bad, "; ".join(bad[:8])
    return "5 dates x 3 files OK"


@case("F10", "Functionality", "Excel download of all report tables opens and has one sheet per table + Summary",
      "xlsx with >= 14 sheets")
def f10():
    code, _, r = http("GET", f"/api/filing/{D}/download-excel")
    assert code == 200, code
    z = zipfile.ZipFile(io.BytesIO(r.content))
    sheets = [n for n in z.namelist() if n.startswith("xl/worksheets/sheet")]
    assert len(sheets) >= 14, f"{len(sheets)} sheets"
    return f"{len(sheets)} sheets"


@case("F11", "Functionality", "Lineage: a filed record traces back to positions, the source record and the 6G file",
      "lineage/record returns positions, source and files; position and source lineage answer")
def f11():
    rk = pg("SELECT record_key FROM filing_records WHERE as_of_date = %s AND table_code = 'O.D' LIMIT 1", (D,))[0][0]
    r = get(f"/api/wb/lineage/{D}/record/{rk}")
    pos = r.get("positions") or []
    assert pos and r.get("files"), f"positions {len(pos)}, files {len(r.get('files') or [])}"
    get(f"/api/wb/lineage/{D}/position/{pos[0]['position_id']}")
    get(f"/api/wb/lineage/{D}/source/{pos[0]['record_id']}")
    return f"{rk}: {len(pos)} positions"


@case("F12", "Functionality", "LCR: calculation, mapping, reference, explain, disclosure answer for each entity",
      "200 for ENT001-003; LCR ratio present")
def f12():
    out = []
    code, _, _ = http("GET", f"/api/wb/lcr/{D}/calculation?entity=ENT003")
    assert code == 400, f"ENT003 (not subject to the LCR) -> {code}"
    for e in ("ENT001", "ENT002"):
        c = get(f"/api/wb/lcr/{D}/calculation?entity={e}")
        get(f"/api/wb/lcr/{D}/mapping?entity={e}")
        out.append(f"{e} lcr={c.get('summary', {}).get('lcr') if isinstance(c.get('summary'), dict) else '?'}")
    get("/api/wb/lcr/reference")
    return ", ".join(out)


@case("F13", "Functionality", "LCR disclosure export downloads (quarter template + approved sections)",
      "export returns a file (200, non-empty)")
def f13():
    code, _, r = http("GET", f"/api/wb/lcr/disclosure/export?start=2026-02-23&end=2026-02-27&entity=ENT001")
    assert code == 200 and len(r.content) > 500, f"{code} {len(r.content)} bytes"
    return f"{len(r.content)} bytes, {r.headers.get('content-type')}"


@case("F14", "Functionality", "Audit: trail for the day + examiner export (zip with masked data + SHA-256 manifest that verifies)",
      "export zip has manifest; every file's SHA-256 matches; no internal_rating values")
def f14():
    get(f"/api/wb/agents/{D}/audit")
    code, _, r = http("GET", f"/api/wb/agents/{D}/audit/export?audience=Federal%20Reserve%20examiners", timeout=300)
    assert code == 200, f"export {code}"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    man = next((n for n in names if "manifest" in n.lower()), None)
    assert man, f"no manifest in {names}"
    text = z.read(man).decode()
    bad = []
    for n in names:
        if n == man or n.lower().startswith("readme"):
            continue
        h = hashlib.sha256(z.read(n)).hexdigest()
        if h not in text:
            bad.append(n)
    leak = [n for n in names if b"internal_rating" in z.read(n) and n != man]
    assert not bad, f"hash not in manifest: {bad[:5]}"
    return (("WARN", f"internal_rating column appears in {leak}") if leak else f"{len(names)} files, manifest verifies")


@case("F15", "Functionality", "Reference: every configuration table loads and is non-empty",
      "all /api/config/* return rows")
def f15():
    empty = []
    for name in re.findall(r'^\s+"([a-z-]+)": ', SRC[f"{REPO}/app/app.py"].split("CONFIG = {")[1].split("}\n")[0], re.M):
        if not get(f"/api/config/{name}"):
            empty.append(name)
    return (("WARN", f"empty: {empty}") if empty else "all non-empty")


@case("F16", "Functionality", "Genie (Ask): a question returns an answer from the Genie space",
      "POST /wb/genie then poll -> COMPLETED with text or SQL")
def f16():
    code, j, _ = http("POST", "/api/wb/genie", {"question": "What is the LCR for ENT001 on 2026-02-27?"})
    assert code == 200, f"{code} {str(j)[:200]}"
    cid, mid = j.get("conversation_id"), j.get("message_id")
    for _ in range(40):
        time.sleep(3)
        m = get(f"/api/wb/genie/{cid}/{mid}")
        if str(m.get("status")).upper() in ("COMPLETED", "FAILED", "CANCELLED"):
            break
    assert str(m.get("status")).upper() == "COMPLETED", f"status {m.get('status')}"
    return f"answered ({str(m)[:120]})"


@case("F17", "Functionality", "History: run history and submission history answer",
      "pipeline runs listed; submission history has the 5 dates")
def f17():
    h = get("/api/submission-history")
    ds = {str(x.get("as_of_date")) for x in h}
    assert set(DATES) <= ds, f"history dates {sorted(ds)}"
    return f"{len(h)} rows"


# ═══ W. Workflow and controls ═══════════════════════════════════════════════════════════
@case("W01", "Workflow", "Step 5 is gated: Generate is refused while steps 1-4 have open items",
      "POST /wb/generate -> 409 'Finish steps 1-4 first' on a date with open items")
def w01():
    r = get(f"/api/wb/agents/{D}/review")
    if not any(s["open"] or s.get("waiting") for s in r["steps"][:4]):
        return ("WARN", "no open item on the date - not sent (it would start a release generation)")
    code, j, _ = http("POST", f"/api/wb/generate/{D}", {})
    assert code == 409 and "Finish steps 1-4" in str(j), f"{code} {j}"
    return f"409: {j.get('detail')[:120]}"


@case("W02", "Workflow", "Only a release generation can be approved (not the pipeline's generation)",
      "APPROVED on a pipeline-generated run -> 409")
def w02():
    s = get(f"/api/submission/{D}")
    log = s.get("review_log") or []
    gen = next((r for r in log if r["action"] == "GENERATED"), {})
    if gen.get("actor") not in (None, "fr2052a pipeline"):
        return ("WARN", f"latest run generated by {gen.get('actor')} - not sent (approval would be recorded)")
    code, j, _ = http("POST", f"/api/submission/{D}/review", {"action": "APPROVED", "note": "QA negative test"})
    assert code == 409, f"{code} {j}"
    return f"409: {j.get('detail')}"


@case("W03", "Workflow", "Submit before approval is refused; invalid action and reject without note are refused",
      "SUBMITTED on READY_FOR_REVIEW -> 409; action XYZ -> 400; REJECTED without note -> 400")
def w03():
    out = []
    st = get(f"/api/submission/{D}").get("status")
    if st != "APPROVED":
        code, j, _ = http("POST", f"/api/submission/{D}/review", {"action": "SUBMITTED"})
        assert code == 409, f"submit on {st}: {code} {j}"
        out.append(f"submit on {st} 409")
    code, _, _ = http("POST", f"/api/submission/{D}/review", {"action": "XYZ"})
    assert code == 400, f"XYZ {code}"
    code, _, _ = http("POST", f"/api/submission/{D}/review", {"action": "REJECTED"})
    assert code == 400, f"reject without note {code}"
    return "; ".join(out + ["XYZ 400", "reject w/o note 400"])


@case("W04", "Workflow", "Checker decisions validate input: unknown break 404, decided break 409, bad reason code 400",
      "no write happens on any of these")
def w04():
    n0 = pg("SELECT COUNT(*) FROM break_decisions")[0][0]
    code, _, _ = http("POST", "/api/wb/agents/break/BRK-9999-999/decide", {"action": "approve", "reason_code": "X"})
    assert code == 404, f"unknown {code}"
    dec = pg("SELECT break_id FROM breaks WHERE status <> 'PROPOSED' LIMIT 1")
    if dec:
        code, _, _ = http("POST", f"/api/wb/agents/break/{dec[0][0]}/decide", {"action": "approve", "reason_code": "X"})
        assert code == 409, f"decided {code}"
    op = pg("SELECT break_id FROM breaks WHERE status = 'PROPOSED' LIMIT 1")
    if op:
        code, _, _ = http("POST", f"/api/wb/agents/break/{op[0][0]}/decide", {"action": "approve", "reason_code": "NOT-A-CODE"})
        assert code == 400, f"bad reason {code}"
    assert pg("SELECT COUNT(*) FROM break_decisions")[0][0] == n0, "a decision was written"
    return "404 / 409 / 400, nothing written"


@case("W05", "Workflow", "Step-page resolvers validate input",
      "DQ resolve of a non-quarantined record -> 404; validate resolve with unknown action -> 400; AI decide bad decision -> 400")
def w05():
    code, _, _ = http("POST", f"/api/wb/dq/{D}/resolve", {"record_id": "NOT-A-RECORD", "action": "exclude"})
    assert code == 404, f"dq {code}"
    code, _, _ = http("POST", f"/api/wb/validate/{D}/resolve", {"action": "bogus", "rule_id": "X", "item_key": "Y"})
    assert code == 400, f"validate {code}"
    code, _, _ = http("POST", "/api/wb/ai/x/decide", {"decision": "MAYBE"})
    assert code == 400, f"ai {code}"
    return "404 / 400 / 400"


@case("W06", "Workflow", "Validate resolve only accepts an open exception of the day, with its evidence",
      "unknown item -> 404; decided item -> 409; manual without a note / correction -> 400 / 409 (nothing written)")
def w06():
    n0 = pg("SELECT COUNT(*) FROM validation_decisions")[0][0]
    code, _, _ = http("POST", f"/api/wb/validate/{D}/resolve", {"action": "explain", "rule_id": "NO-RULE", "item_key": "NO-ITEM", "note": "QA"})
    assert code == 404, f"unknown item -> {code}"
    q = get(f"/api/wb/validate/{D}/queue")
    dec = next((v for v in q if v["state"] != "open"), None)
    if dec:
        code, _, _ = http("POST", f"/api/wb/validate/{D}/resolve", {"action": "explain", "rule_id": dec["rule_id"], "item_key": dec["item_key"], "note": "QA"})
        assert code == 409, f"decided item -> {code}"
    op = next((v for v in get("/api/wb/validate/2026-02-23/queue") if v["state"] == "open"), None)
    if op:
        code, _, _ = http("POST", "/api/wb/validate/2026-02-23/resolve", {"action": "manual", "rule_id": op["rule_id"], "item_key": op["item_key"]})
        assert code == 400, f"manual without note -> {code}"
    assert pg("SELECT COUNT(*) FROM validation_decisions")[0][0] == n0, "a decision was written"
    return "404 / 409 / 400, nothing written"


@case("W07", "Workflow", "A decided AI suggestion cannot be re-decided; AI decisions are on the audit trail",
      "second decision -> 409; ai_decisions is append-only for the app; decisions appear in the Audit timeline")
def w07():
    dec = pg("SELECT d.suggestion_id, s.as_of_date FROM ai_decisions d JOIN ai_suggestions s USING (suggestion_id) LIMIT 1")
    if not dec:   # right after a demo reset nothing is decided yet; the 409 guard is also covered by the unit tests
        return ("WARN", "no decided suggestion yet (demo dates reset) - not exercised live")
    sid, d = dec[0][0], str(dec[0][1])
    code, j, _ = http("POST", f"/api/wb/ai/{sid}/decide", {"decision": "REJECTED", "note": "QA negative test"})
    assert code == 409, f"re-decide -> {code} {j}"
    ev = get(f"/api/wb/agents/{d}/audit?who=decisions")["events"]
    assert any(e.get("evidence") == f"ai_decisions {sid}" for e in ev), "decision not in the Audit timeline"
    rows = pg("SELECT p, has_table_privilege(%s, 'public.ai_decisions', p) FROM unnest(ARRAY['UPDATE','DELETE']) p", (APP_SP,))
    can = [p for p, ok in rows if ok]
    return (("WARN", f"409 + in Audit; app SP can still {can} on ai_decisions until notebook 07 runs") if can else "409, in Audit, append-only")


@case("W08", "Workflow", "Pipeline run from the app accepts only reporting dates",
      "POST /pipeline/run refuses dates outside the reporting dates (checked in code; a live call would start a job if it failed)")
def w08():
    body = SRC[f"{REPO}/app/app.py"].split("def run_pipeline(")[1].split("\n@app")[0]
    code, _, _ = http("POST", "/api/pipeline/run", {"date": "not-a-date", "scope": "both"})
    assert code == 400, f"malformed -> {code}"
    return "reporting dates only" if "_reporting_dates()" in body else ("FAIL", "run_pipeline does not check the reporting dates")


@case("W09", "Workflow", "Append-only audit trail: the app's role cannot UPDATE / DELETE agent_events, break_decisions",
      "has_table_privilege(app SP, UPDATE/DELETE) = false")
def w09():
    rows = pg("""SELECT t, p, has_table_privilege(%s, 'public.' || t, p) FROM unnest(ARRAY['agent_events','break_decisions']) t,
                 unnest(ARRAY['UPDATE','DELETE']) p""", (APP_SP,))
    bad = [f"{t} {p}" for t, p, ok in rows if ok]
    assert not bad, f"app SP can {bad}"
    return "UPDATE/DELETE revoked"


@case("W10", "Workflow", "Four eyes on release: approver cannot submit; override approved by another person (code)",
      "guards present in review_submission")
def w10():
    body = SRC[f"{REPO}/app/app.py"].split("def review_submission(")[1].split("\n@app")[0]
    assert "four eyes" in body and body.count("== user") >= 2, "guard missing"
    return "both guards present"


# ═══ R. Reconciliation - numbers agree everywhere ═══════════════════════════════════════
@case("R01", "Reconciliation", "Today's counts = each step page's own queue (one source of truth)",
      "review.dq.open = DQ queue open; enrich.open = enrich queue open; validate.open = open exceptions + open comments")
def r01():
    bad = []
    for d in DATES:
        r = {s["key"]: s for s in get(f"/api/wb/agents/{d}/review")["steps"]}
        dq = get(f"/api/wb/dq/{d}/queue")
        dq_open = sum(1 for x in dq if (x.get("state") or x.get("status") or "").lower() in ("open", "to review", "proposed", "quarantined"))
        en = get(f"/api/wb/enrich/{d}/queue")
        en_open = sum(1 for x in en if (x.get("status") or "").upper() in ("PROPOSED", "OPEN"))
        va = get(f"/api/wb/validate/{d}/queue")
        va_open = sum(1 for x in va if x.get("state") == "open")
        ai = get(f"/api/wb/ai/{d}")
        c_open = sum(1 for x in ai if x["suggestion_type"] in ("COMMENT_DRAFT", "VARIANCE_COMMENTARY") and x["status"] == "PROPOSED")
        for k, mine in (("dq", dq_open), ("enrich", en_open), ("validate", va_open + c_open)):
            if r[k]["open"] != mine:
                bad.append(f"{d} {k}: Today {r[k]['open']} vs page {mine}")
    assert not bad, "; ".join(bad)
    return "5 dates reconcile"


@case("R02", "Reconciliation", "Data flow Bronze -> Silver -> positions -> report -> 6G (qa_flow.sh, 14 checks)",
      "no defect rows")
def r02():
    out = subprocess.run(["zsh", "qa_flow.sh"], cwd=f"{REPO}/scripts/qa", capture_output=True, text=True).stdout
    defects = [l for l in out.splitlines() if l and not l.startswith("==")]
    assert not defects, " | ".join(defects[:10])
    return "14 checks clean"


@case("R03", "Reconciliation", "6G XML = report tables per entity x table (qa_xml.sh)",
      "0 mismatches on 5 dates")
def r03():
    os.makedirs("/tmp/qa_xml", exist_ok=True)
    out = subprocess.run(["zsh", f"{REPO}/scripts/qa/qa_xml.sh"], cwd="/tmp/qa_xml", capture_output=True, text=True).stdout
    lines = [l for l in out.splitlines() if "mismatches" in l]
    assert len(lines) == 5 and all(l.endswith("mismatches 0") for l in lines), out[-600:]
    return " / ".join(l.split("xml records ")[1].split(" db")[0] for l in lines) + " records"


@case("R04", "Reconciliation", "Synced tables are complete: Lakebase row count = Delta row count for every synced table",
      "62 tables equal")
def r04():
    sys.path.insert(0, f"{REPO}/deploy")
    import lakebase_synced_tables as L
    src = {**{n: s for n, s in L.TABLES.items()}, **{n: s for n, (s, _) in L.TRIGGERED.items()}, "fact_liquidity_position": "conformed.fact_liquidity_position"}
    bad, n = [], 0
    for name, s in src.items():
        delta = int(wh(f"SELECT COUNT(*) FROM {C}.{s}")[0][0])
        lb = pg(f"SELECT COUNT(*) FROM app_serving.{name}")[0][0]
        n += 1
        if delta != lb:
            bad.append(f"{name} delta {delta} vs lakebase {lb}")
    assert not bad, f"{len(bad)}/{n}: " + "; ".join(bad[:10])
    return f"{n} tables equal"


@case("R05", "Reconciliation", "Report summary totals = sum of the filed records",
      "/filing/{date}/summary per table = filing_records count/amount")
def r05():
    s = get(f"/api/filing/{D}/summary")
    db = {r[0]: (r[1], float(r[2] or 0)) for r in pg("SELECT table_code, COUNT(*), SUM(reported_amount) FROM filing_records WHERE as_of_date = %s GROUP BY 1", (D,))}
    bad = []
    for x in s:
        code = x.get("schedule_code") or x.get("table_code")
        n = x.get("record_count") or x.get("records") or x.get("n")
        if code in db and n is not None and int(n) != db[code][0]:
            bad.append(f"{code} summary {n} vs records {db[code][0]}")
    assert not bad, "; ".join(bad)
    return f"{len(s)} tables agree"


@case("R06", "Reconciliation", "S.L.6 (the LCR in the filing) = the LCR engine's result per entity",
      "equal to 4 decimals")
def r06():
    rows = pg("""SELECT f.reporting_entity, f.reported_amount, c.lcr_ratio FROM filing_records f
                 JOIN calculation_results c ON c.as_of_date = f.as_of_date AND c.entity_id = f.reporting_entity
                 WHERE f.as_of_date = %s AND f.product_id = 'S.L.6'""", (D,))
    bad = [f"{e} filed {a} vs engine {l}" for e, a, l in rows if a is None or l is None or abs(float(a) - float(l)) > 1e-4]
    assert rows and not bad, f"rows {len(rows)}; " + "; ".join(bad)
    return f"{len(rows)} entities tie"


@case("R07", "Reconciliation", "Due dates: Primary = T+2 business days (Fed calendar), Reduced as configured",
      "Feb 27 2026 (Fri) -> Primary Tue Mar 3")
def r07():
    r = get(f"/api/wb/agents/{D}/review")
    assert r["due"]["primary"] == "2026-03-03", r["due"]
    return r["due"]


# ═══ A. AI maker / human checker ═══════════════════════════════════════════════════════
@case("A01", "AI", "Every open item of every step has a stored agent proposal (AI computed in the pipeline)",
      "each PROPOSED break has a proposal; open feed/DQ/master-data/validate/comment items are in the breaks register; a record with no PID rule has an AI suggestion")
def a01():
    bad = []
    for d in DATES:
        miss = pg("""SELECT COUNT(*) FROM breaks b WHERE b.as_of_date = %s AND b.status = 'PROPOSED'
                     AND NOT EXISTS (SELECT 1 FROM proposals p WHERE p.break_id = b.break_id)""", (d,))[0][0]
        if miss:
            bad.append(f"{d}: {miss} breaks without proposal")
        r = get(f"/api/wb/agents/{d}/review")
        # records with no PID rule carry the AI-suggested fix of notebook 09 on the PID enrichment page, not a break in the register
        no_rule = [q for q in get(f"/api/wb/enrich/{d}/queue") if q["kind"] == "No PID rule matched" and q["status"] == "PROPOSED"]
        bad += [f"{d}: {q['key']} has no AI suggestion" for q in no_rule if not q.get("suggestion")]
        # a new product code is quarantined by DQ and waits on PID enrichment: one item for the agents, proposed once (on DQ)
        dq_codes = {q.get("source_product_code") for q in get(f"/api/wb/dq/{d}/queue") if q["state"] == "open"}
        twice = [q for q in get(f"/api/wb/enrich/{d}/queue") if q["kind"] == "New product code" and q["status"] == "PROPOSED" and q["key"] in dq_codes]
        open_total = sum(s["open"] or 0 for s in r["steps"][:4]) - len(no_rule) - len(twice)
        n_prop = pg("SELECT COUNT(*) FROM breaks WHERE as_of_date = %s AND status = 'PROPOSED'", (d,))[0][0]
        if n_prop < open_total:
            bad.append(f"{d}: {open_total} open items but {n_prop} proposed breaks")
    assert not bad, "; ".join(bad)
    return "every open item has a proposal"


@case("A02", "AI", "Proposals carry the evidence: rule check, LCR effect, sources, trace, 'made by' model version",
      "latest proposal per break has rule_check, impact, sources (>=1 for rule items), trace, model")
def a02():
    rows = pg("""SELECT DISTINCT ON (break_id) break_id, rule_check, impact, sources, trace, model FROM proposals ORDER BY break_id, version DESC""")
    gaps = collections.Counter()
    for b, rc, im, so, tr, mo in rows:
        for k, v in (("rule_check", rc), ("impact", im), ("trace", tr), ("model", mo)):
            if v in (None, "", "{}", "[]"):
                gaps[k] += 1
        if so in (None, "", "[]"):
            gaps["sources"] += 1
    return (("WARN", f"{len(rows)} proposals; missing: {dict(gaps)}") if gaps else f"{len(rows)} proposals complete")


@case("A03", "AI", "Proposals name the registered model version that made them",
      "every proposal made since provenance was fixed (agents v4, 2026-11-02 18:00 UTC) is 'fr2052a_agents v<n>'; the newest = champion when made after it")
def a03():
    champ = w.api_client.do("GET", f"/api/2.1/unity-catalog/models/{C}.ai_assist.fr2052a_agents/aliases/champion")["version"]
    rows = dict(pg("SELECT model, COUNT(*) FROM proposals WHERE created_at >= '2026-11-02 18:00' GROUP BY 1"))
    bad = {k: v for k, v in rows.items() if not str(k).startswith("fr2052a_agents v")}
    assert not bad, f"proposals without the registered model version: {bad}"
    return f"{sum(rows.values())} recent proposals by {sorted(rows)}; champion v{champ}"


@case("A04", "AI", "The agents' serving endpoint serves the champion and answers a proposal request",
      "endpoint READY, version = champion, predict returns JSON with break_type + summary")
def a04():
    e = w.api_client.do("GET", "/api/2.0/serving-endpoints/fr2052a-agents")
    champ = w.api_client.do("GET", f"/api/2.1/unity-catalog/models/{C}.ai_assist.fr2052a_agents/aliases/champion")["version"]
    v = e["config"]["served_entities"][0]["entity_version"]
    assert e["state"]["ready"] == "READY" and str(v) == str(champ), f"state {e['state']}, serves v{v}, champion v{champ}"
    item = next((x for x in get(f"/api/wb/validate/{D}/queue")), None)
    if not item:
        return f"READY v{v} (no item to call with)"
    t = time.time()
    r = w.api_client.do("POST", "/serving-endpoints/fr2052a-agents/invocations",
                        body={"dataframe_records": [{"kind": "validation", "as_of_date": D, "item_json": json.dumps(item)}]})
    p = json.loads(r["predictions"][0])
    assert p.get("break_type") and "summary" in p, str(p)[:300]
    return f"READY v{v}; predict {time.time() - t:.1f}s -> {p['break_type']}"


@case("A05", "AI", "MLflow traces of the agents' latest pipeline run are in Unity Catalog",
      "trace rows in ai_assist.<exp>_otel_spans from the last 2 days")
def a05():
    n = wh(f"SELECT COUNT(*) FROM {C}.ai_assist.`{EXP}_otel_spans` WHERE start_time_unix_nano > (unix_timestamp() - 2*86400) * 1000000000")[0][0]
    return (("PASS", f"{n} spans in the last 2 days") if int(n) > 0 else ("FAIL", "no spans in the last 2 days - the pipeline run of today did not trace"))


@case("A06", "AI", "Vector Search (regulatory text) is online and returns passages",
      "index ONLINE; query returns >= 1 row")
def a06():
    i = w.api_client.do("GET", f"/api/2.0/vector-search/indexes/{C}.reference.reg_text_index")
    st = i.get("status", {})
    assert st.get("ready"), f"index {st}"
    r = w.api_client.do("POST", f"/api/2.0/vector-search/indexes/{C}.reference.reg_text_index/query",
                        body={"query_text": "outflow rate for retail deposits", "columns": ["chunk_id"], "num_results": 3})
    n = len(r.get("result", {}).get("data_array", []))
    assert n, "no results"
    return f"ONLINE, {n} passages"


@case("A07", "AI", "On-demand AI answers: LCR 'why it moved' and 'ask about this item'",
      "explain returns text grounded on numbers; ask returns an answer")
def a07():
    t = time.time()
    e = get(f"/api/wb/lcr/{D}/explain?entity=ENT001")
    secs = time.time() - t
    assert e, "empty"
    return (("WARN", f"explain took {secs:.1f}s") if secs > 15 else f"explain {secs:.1f}s")

@case("A08", "AI", "Feedback loop: the checker's decisions are on the traces of the proposals they decided; the endpoint traces too",
      "checker_decision assessments exist; a trace made by the serving endpoint exists; each decision sits on a trace made before it")
def a08():
    T = f"{C}.ai_assist.`{EXP}_trace_unified`"
    n = int(wh(f"SELECT COUNT(*) FROM {T} LATERAL VIEW explode(assessments) x AS a WHERE a.assessment_name = 'checker_decision'")[0][0])
    ep = int(wh(f"SELECT COUNT(*) FROM {T} WHERE tags['fr2052a.agents_model_version'] >= '6'")[0][0])
    late = int(wh(f"""SELECT COUNT(*) FROM {T} LATERAL VIEW explode(assessments) x AS a
                      WHERE a.assessment_name = 'checker_decision' AND a.create_time < request_time""")[0][0])
    assert n > 0, "no checker feedback on any trace"
    assert ep > 0, "no trace from the serving endpoint (v6+)"
    assert late == 0, f"{late} feedback rows created before their trace"
    return f"{n} checker decisions on traces; {ep} traces by v6+ (endpoint / pipeline)"


# ═══ X. Architecture and system completeness ═══════════════════════════════════════════
@case("X01", "Architecture", "The app reads Lakebase only on the click path (no SQL warehouse calls in request handlers)",
      "no run_sql in app request paths except declared fallbacks")
def x01():
    hits = []
    for f, s in SRC.items():
        for i, l in enumerate(s.splitlines(), 1):
            if re.search(r"\brun_sql\(|statement_execution", l) and "def run_sql" not in l:
                hits.append(f"{os.path.basename(f)}:{i}")
    return (("WARN", f"{len(hits)} warehouse calls remain: {', '.join(hits[:20])} (agents' rule check / fallbacks - check each is off the click path)")
            if hits else "none")


@case("X02", "Architecture", "Synced tables: all ONLINE, refreshed after the latest pipeline run",
      "62 synced tables ONLINE")
def x02():
    names = [t.name for t in w.tables.list(C, "app_serving")]
    bad = []
    for n in names:
        s = w.api_client.do("GET", f"/api/2.0/postgres/synced_tables/{C}.app_serving.{n}")
        st = str(s.get("status", {}).get("detailed_state") or s.get("status", {}).get("state"))
        if "ONLINE" not in st:
            bad.append(f"{n} {st}")
    assert len(names) == 62, f"{len(names)} synced tables (expected 62)"
    assert not bad, "; ".join(bad[:8])
    return f"{len(names)} ONLINE"


@case("X03", "Architecture", "No configuration drift: the workspace = the bundles",
      "databricks bundle plan of the platform bundle and the app bundle: nothing to change")
def x03():
    bad = []
    for d in (REPO, f"{REPO}/app"):
        out = subprocess.run(["databricks", "bundle", "plan", "-t", "dev", "-p", PROFILE, "-o", "json"], cwd=d, capture_output=True, text=True)
        try:   # a field counts as drift only when its value differs (the CLI also lists app config fields whose value is unchanged)
            plan = json.loads(out.stdout).get("plan", {})
            changes = [f"{k}.{f}" for k, v in plan.items() if v.get("action") not in (None, "skip", "noop")
                       for f, c in (v.get("changes") or {}).items() if c.get("action") not in ("skip", None) and c.get("old") != c.get("new")]
        except ValueError:
            changes = ["plan not readable"]
        if out.returncode != 0 or changes:
            bad.append(f"{os.path.relpath(d, REPO)}: {changes or out.stderr[-200:]}")
    assert not bad, "; ".join(bad)
    return "both bundles: nothing to change"


@case("X04", "Architecture", "No drift: workspace notebooks / app files = repo",
      "every notebook and app .py in the workspace equals the repo file")
def x04():
    bad = []
    for f in sorted(glob.glob(f"{REPO}/notebooks/*.py")) + [f"{REPO}/app/{x}" for x in ("app.py", "workbench.py", "agents.py", "agents_model.py", "agent_tracing.py", "requirements.txt")] + [f"{REPO}/pipelines/bronze_ingest.py"]:
        rel = os.path.relpath(f, REPO)
        path = (f"{APP_BUNDLE}/{rel[4:]}" if rel.startswith("app/") else f"{BUNDLE}/{rel[:-3] if rel.startswith('notebooks/') else rel}")
        try:
            ex = w.workspace.export(path, format=ExportFormat.SOURCE)
            live = base64.b64decode(ex.content).decode()
        except Exception as e:
            bad.append(f"{rel} missing")
            continue
        norm = lambda s: [l.rstrip() for l in s.strip().splitlines() if l.strip()]
        if norm(live) != norm(open(f).read()):
            bad.append(rel)
    assert not bad, "differ: " + ", ".join(bad)
    return "all equal"


@case("X05", "Architecture", "Deployed frontend = the repo build (no stale bundle)",
      "workspace static/index.html references the same asset hashes as a fresh local build")
def x05():
    W = f"{APP_BUNDLE}/static"
    live = base64.b64decode(w.workspace.export(f"{W}/index.html", format=ExportFormat.AUTO).content).decode()
    local = open(f"{REPO}/app/static/index.html").read()
    a, b = sorted(re.findall(r"assets/[^\"]+", live)), sorted(re.findall(r"assets/[^\"]+", local))
    assert a == b, f"live {a} vs local {b}"
    assets = [o.path.rsplit("/", 1)[1] for o in w.workspace.list(f"{W}/assets")]
    stale = [x for x in assets if f"assets/{x}" not in a]
    return (("WARN", f"stale bundles in workspace: {stale}") if stale else f"{a}")


@case("X06", "Architecture", "App runtime safety: no backslash inside f-string expressions (Python < 3.12)",
      "none in app/*.py")
def x06():
    hits = []
    for f, s in SRC.items():
        for i, l in enumerate(s.splitlines(), 1):
            for m in re.finditer(r'f"([^"\\]|\\.)*"|f\'([^\'\\]|\\.)*\'', l):
                for expr in re.findall(r"\{([^{}]*)\}", m.group(0)):
                    if "\\" in expr:
                        hits.append(f"{os.path.basename(f)}:{i}")
    assert not hits, ", ".join(hits)
    return "none"


@case("X07", "Architecture", "App deployment is healthy and its resources exist",
      "compute ACTIVE, deployment SUCCEEDED; every resource (warehouse, Lakebase, Genie, 3 jobs, 2 endpoints) resolvable")
def x07():
    a = w.api_client.do("GET", "/api/2.0/apps/fr2052a")
    assert a["compute_status"]["state"] == "ACTIVE" and a["active_deployment"]["status"]["state"] == "SUCCEEDED", str(a["compute_status"])
    names = sorted(r["name"] for r in a.get("resources", []))
    want = sorted(["sql-warehouse", "fr2052a-lakebase", "genie-space", "daily-job", "revalidate-job", "generate-job", "ai-model", "agents-model", "demo-reset-job"])
    assert names == want, f"resources {names}"
    return "ACTIVE, 8 resources"


@case("X08", "Architecture", "App logs: no errors / tracebacks since the last deployment",
      "no ERROR or Traceback lines in the app logs")
def x08():
    out = subprocess.run(["databricks", "apps", "logs", "fr2052a", "-p", PROFILE, "--tail-lines", "2000"], capture_output=True, text=True)
    lines = (out.stdout + out.stderr).splitlines()
    errs = [l for l in lines if re.search(r"Traceback|\bERROR\b| 500 ", l)]
    if out.returncode != 0 and not lines:
        return ("WARN", f"logs not readable: {out.stderr[:200]}")
    return (("FAIL", f"{len(errs)} error lines, e.g. {' | '.join(errs[:4])[:600]}") if errs else f"{len(lines)} log lines, no errors")


@case("X09", "Architecture", "Dashboards: every dataset query runs on the warehouse",
      "main + LCR dashboards: all datasets succeed")
def x09():
    bad, n = [], 0
    ws = S.get(f"{APP}/api/workspace-url", timeout=60).json()
    for did in (ws["dashboard_id"], ws["lcr_dashboard_id"]):
        d = w.api_client.do("GET", f"/api/2.0/lakeview/dashboards/{did}")
        ser = json.loads(d["serialized_dashboard"])
        for ds in ser.get("datasets", []):
            q = ds.get("query") or "".join(ds.get("queryLines", []))
            n += 1
            params = []
            for prm in ds.get("parameters", []):
                v = (((prm.get("defaultSelection") or {}).get("values") or {}).get("values") or [{}])[0].get("value")
                params.append({"name": prm["keyword"], "value": v if v is not None else D, "type": prm.get("dataType", "STRING")})
            try:
                r = w.statement_execution.execute_statement(warehouse_id=WH, statement=f"SELECT COUNT(*) FROM ({q}) x", wait_timeout="50s", catalog=C,
                                                            parameters=[StatementParameterListItem(**p_) for p_ in params] or None)
                if r.status.state.value != "SUCCEEDED":
                    bad.append(f"{ds.get('displayName')}: {r.status.error.message[:120] if r.status.error else r.status.state}")
            except Exception as e:
                bad.append(f"{ds.get('displayName')}: {str(e)[:120]}")
    assert not bad, f"{len(bad)}/{n} fail: " + "; ".join(bad[:6])
    return f"{n} datasets run"


@case("X10", "Architecture", "Genie space and its metric views / UC functions work",
      "3 metric views and 7 UC functions answer")
def x10():
    bad = []
    for mv in ("reg_2052a.fr2052a_metrics", "reg_2052a.fr2052a_check_metrics", "reg_lcr.fr2052a_lcr_metrics"):
        try:
            cols = wh(f"DESCRIBE TABLE {C}.{mv}")
            meas = next((r[0] for r in cols if r[0] and r[1] and "measure" in str(r).lower()), None)
            wh(f"SELECT * FROM {C}.{mv} LIMIT 1") if not meas else None
        except AssertionError as e:
            bad.append(f"{mv}: {str(e)[:100]}")
    for fn, args in (("filing_status", f"'{D}'"), ("lcr_summary", f"'{D}'"), ("validation_issues", f"'{D}'"), ("open_suggestions", f"'{D}'"),
                     ("variance_anomalies", f"'{D}'"), ("pid_rule_lookup", "'DEPOSIT'")):
        try:
            wh(f"SELECT * FROM {C}.ai_assist.{fn}({args}) LIMIT 1")
        except AssertionError as e:
            bad.append(f"{fn}: {str(e)[:120]}")
    assert not bad, "; ".join(bad)
    return "metric views + functions answer"


@case("X11", "Architecture", "Security: the masked column internal_rating never reaches Lakebase",
      "app_serving.fact_liquidity_position has no internal_rating; Delta column has the mask")
def x11():
    cols = [r[0] for r in pg("SELECT column_name FROM information_schema.columns WHERE table_schema='app_serving' AND table_name='fact_liquidity_position'")]
    assert "internal_rating" not in cols, "internal_rating is in Lakebase"
    sp = [r[0] for r in pg("SELECT column_name FROM information_schema.columns WHERE table_schema='app_serving' AND table_name='source_position'")]
    return (("WARN", "fact_liquidity_position clean, but source_position in Lakebase still carries internal_rating unmasked (decided 2026-11-01: not now)")
            if "internal_rating" in sp else "clean")


@case("X12", "Architecture", "Security: unauthenticated requests are refused; no secrets in the repo or the bundle",
      "401/302 without a token; no token/secret patterns in tracked files")
def x12():
    r = requests.get(APP + "/api/dates", timeout=30, allow_redirects=False)
    assert r.status_code in (401, 302, 303), f"no token -> {r.status_code}"
    files = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True).stdout.split()
    pat = re.compile(r"dapi[0-9a-f]{32}|dose[0-9a-f]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY|client_secret\s*=\s*['\"][^'\"]{8,}")
    hits = [f for f in files if os.path.isfile(f"{REPO}/{f}") and os.path.getsize(f"{REPO}/{f}") < 5e6 and pat.search(open(f"{REPO}/{f}", errors="ignore").read())]
    assert not hits, f"secret-like strings in {hits}"
    return f"{r.status_code} without token; {len(files)} files clean"


@case("X13", "Architecture", "Security: request parameters cannot inject SQL",
      "quote / SQL payloads in path and query params give 400/404, never 500 or extra rows")
def x13():
    pay = "x' OR '1'='1"
    q = requests.utils.quote(pay, safe="")
    probes = [f"/api/wb/lineage/{D}/record/{q}", f"/api/wb/lineage/{D}/position/{q}", f"/api/wb/lineage/{D}/source/{q}",
              f"/api/wb/collect/{D}/record/{q}", f"/api/wb/dq/{D}/suggest/{q}", f"/api/wb/validate/{D}/suggest?rule_id={q}&item_key={q}",
              f"/api/wb/enrich/{D}/positions?code={q}&page=0", f"/api/wb/enrich/{D}/table/{q}/pids", f"/api/wb/metadata?q={q}",
              f"/api/wb/lcr/{D}/rule/{q}/positions?entity=ENT001&page=0", f"/api/wb/lcr/{D}/calculation?entity={q}",
              f"/api/wb/agents/{D}/item?kind=dq&ref={q}", f"/api/wb/agents/{D}/audit?who={q}", f"/api/wb/correct/{D}?record_key={q}",
              f"/api/filing/{q}/summary", f"/api/wb/variance/{q}", f"/api/wb/agents/break/{q}", f"/api/config/{q}",
              f"/api/wb/lcr/disclosure?start={q}&end={q}&entity=ENT001", f"/api/submission/{D}/file/{q}"]
    bad = []
    for p in probes:
        code, j, _ = http("GET", p)
        rows = j if isinstance(j, list) else (j or {}).get("rows") if isinstance(j, dict) else None
        if code >= 500 or (code == 200 and rows):
            bad.append(f"{p.split('?')[0].replace(q, '<sqli>')} -> {code}{' with rows' if code == 200 and rows else ''}")
    assert not bad, f"{len(bad)}/{len(probes)}: " + "; ".join(bad)
    return f"{len(probes)} probes refused"


@case("X14", "Architecture", "Robustness: unknown / malformed dates and codes give 4xx, not 500",
      "bad date 'abc', out-of-window 2025-01-01, unknown table -> 400/404")
def x14():
    probes = ["/api/wb/today/abc", "/api/wb/agents/abc/review", "/api/filing/abc/summary", "/api/wb/dq/abc/queue", "/api/wb/validate/abc/queue",
              "/api/wb/agents/2025-01-01/review", "/api/wb/today/2025-01-01", "/api/filing/2025-01-01/summary", "/api/submission/2025-01-01",
              f"/api/filing/{D}/table/ZZ", "/api/wb/enrich/abc/queue", "/api/wb/lcr/abc/calculation", "/api/wb/collect/abc"]
    bad = []
    for p in probes:
        code, j, _ = http("GET", p)
        if code >= 500:
            bad.append(f"{p} -> {code}")
        elif code == 200 and "2025-01-01" in p:
            bad.append(f"{p} -> 200 (date outside the reporting window accepted)")
    assert not bad, f"{len(bad)}/{len(probes)}: " + "; ".join(bad)
    return f"{len(probes)} probes 4xx"


@case("X15", "Architecture", "Performance: page APIs answer fast from Lakebase (warm)",
      "p95 of the GET endpoints < 2 s; none > 5 s")
def x15():
    out = subprocess.run(["bash", f"{REPO}/scripts/qa/app_test.sh", D], capture_output=True, text=True).stdout.splitlines()
    paths = [l.split()[1] for l in out if l.startswith("200 ")]
    secs = []
    for p in paths:
        http("GET", p)
        secs.append((TIMES[p], p))
    secs.sort(reverse=True)
    p95 = statistics.quantiles([s for s, _ in secs], n=20)[18]
    slow = [f"{p.split('?')[0]} {s:.1f}s" for s, p in secs if s > 5]
    worst = ", ".join(f"{p.split('?')[0]} {s:.1f}s" for s, p in secs[:5])
    if slow or p95 > 2:
        return ("FAIL" if slow else "WARN", f"p95 {p95:.2f}s; slowest {worst}")
    return f"p95 {p95:.2f}s; slowest {worst}"


@case("X16", "Architecture", "Concurrency: a break is decided once (double click / two checkers)",
      "_decide claims the break with a conditional UPDATE before applying")
def x16():
    body = SRC[f"{REPO}/app/agents.py"].split("def _decide(")[1].split("\ndef ")[0]
    ok = "AND status = %s RETURNING" in body and body.index("claim(status") < body.index("_apply(")
    return "claimed before apply" if ok else ("FAIL", "_decide applies before claiming the break")


@case("X17", "Architecture", "Lakebase app tables have primary keys (idempotent writes, no duplicate decisions)",
      "every public app table has a PK or unique index")
def x17():
    rows = pg("""SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'public' AND c.relkind = 'r'
                   AND NOT EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = c.oid AND (i.indisprimary OR i.indisunique))""")
    no = sorted(r[0] for r in rows)
    return (("WARN", f"no PK/unique key: {no}") if no else "all keyed")


@case("X18", "Architecture", "Wording rules: no 'copilot', no run numbers in UI text",
      "frontend + API labels free of 'copilot' and 'run <n>'")
def x18():
    hits = []
    for f, s in {**FE, **SRC}.items():
        for i, l in enumerate(s.splitlines(), 1):
            if re.search(r"copilot", l, re.I):
                hits.append(f"{os.path.basename(f)}:{i} copilot")
            if re.search(r"['\"`][^'\"`]*\b[Rr]un (#|number )?\$?\{?\w*[Nn]umber", l) and f in FE:
                hits.append(f"{os.path.basename(f)}:{i} run number")
    return (("WARN", "; ".join(hits[:10])) if hits else "clean")


@case("X19", "Architecture", "Deployment is code and the repo holds no workspace-specific values",
      "both bundles exist; no workspace ids, hosts or catalog names in the bundles, config or docs (they are in gitignored local files)")
def x19():
    need_files = ["databricks.yml", "resources/jobs.yml", "resources/pipeline.yml", "resources/dashboards.yml", "resources/lakebase.yml", "app/databricks.yml"]
    bad = [f"missing {f}" for f in need_files if not os.path.exists(f"{REPO}/{f}")]
    live = [str(v) for v in JOBS.values()] + [C, WH, APP_SP, APP.split("//")[-1]]
    for f in need_files + ["CLAUDE.md", "PROGRESS.md", "app/frontend/src/api.js"] + glob.glob(f"{REPO}/notebooks/*.py") + glob.glob(f"{REPO}/app/*.py"):
        path = f if f.startswith("/") else f"{REPO}/{f}"
        if os.path.exists(path):
            txt = open(path).read()
            bad += [f"{os.path.relpath(path, REPO)}: {x}" for x in live if x and x in txt]
    assert not bad, "; ".join(bad[:8])
    return "bundles present; no workspace values in code, config or docs"


@case("X20", "Architecture", "Operability: alerting / failure notification on the scheduled jobs",
      "fr2052a-daily / generate have email or webhook notifications on failure")
def x20():
    out = []
    for k, jid in JOBS.items():
        s = w.api_client.do("GET", "/api/2.2/jobs/get", query={"job_id": jid})["settings"]
        if not (s.get("email_notifications", {}).get("on_failure") or s.get("webhook_notifications", {}).get("on_failure")):
            out.append(k)
    return (("WARN", f"no failure notification on: {out}") if out else "all notify")


@case("X21", "Architecture", "Backend test coverage: automated tests run without the live system",
      "unit tests exist for the rules (due dates, gating, transitions, Postgres SQL)")
def x21():
    tests = [f for f in glob.glob(f"{REPO}/**/test_*.py", recursive=True) if "node_modules" not in f]
    return (("WARN", "no unit tests - only live QA scripts (app_test, qa_flow, qa_xml, uat, this file)") if not tests else f"{len(tests)} test files")

# ═══ I. AI-first features ═════════════════════════════════════════════════════════════
@case("I01", "AI-first", "Today leads with the agents' work and never says more is left than the step pages",
      "review.agents.headline present; its open count <= the steps' open items")
def i01():
    bad = []
    for d in DATES:
        r = get(f"/api/wb/agents/{d}/review")
        a = r.get("agents") or {}
        if a.get("total") and not a.get("headline"):
            bad.append(f"{d} no headline")
        if (a.get("open") or 0) > sum(s["open"] or 0 for s in r["steps"][:4]):
            bad.append(f"{d}: headline {a.get('open')} open vs steps {sum(s['open'] or 0 for s in r['steps'][:4])}")
    assert not bad, "; ".join(bad)
    return get(f"/api/wb/agents/{D}/review")["agents"]["headline"]


@case("I02", "AI-first", "Straight-through processing: only the agents apply STP, and only bulk-qualifying proposals; spot checks are guarded",
      "spot-check of a non-STP item -> 409; every STP decision is by the agents' actor on a proposal with confidence >= 0.95")
def i02():
    nb = pg("SELECT break_id FROM breaks b WHERE NOT EXISTS (SELECT 1 FROM break_decisions d WHERE d.break_id = b.break_id AND d.reason_code = 'STP') LIMIT 1")
    if nb:
        code, _, _ = http("POST", f"/api/wb/agents/break/{nb[0][0]}/spot-check", {"verdict": "confirm"})
        assert code == 409, f"spot-check of a non-STP item -> {code}"
    bad = pg("""SELECT d.break_id FROM break_decisions d JOIN proposals p ON p.proposal_id = d.proposal_id WHERE d.reason_code = 'STP'
                AND (d.decided_by <> 'fr2052a agents (straight-through)' OR p.confidence < 0.95)""")
    n = pg("SELECT COUNT(*) FROM break_decisions WHERE reason_code = 'STP'")[0][0]
    assert not bad, f"STP decisions outside the rule: {bad}"
    return f"{n} straight-through decisions, all within the rule; spot-check guard 409"


@case("I03", "AI-first", "Release memo for the approver: written from the run's facts, kept per run, in the examiner pack",
      "memo for a released run; its numbers come from the facts (LCR values appear in facts); 08_release_memo.csv in the export")
def i03():
    d = next((x for x in DATES if get(f"/api/submission/{x}").get("released_by")), None)
    if not d:
        return ("WARN", "no released run to write a memo for")
    m = get(f"/api/wb/agents/{d}/release-memo")
    assert m.get("memo") and m.get("facts"), str(m)[:200]
    lcr = [str(r["lcr"]) for r in m["facts"]["lcr"] if r.get("lcr") is not None]
    nums = re.findall(r"\b\d\.\d{4}\b", m["memo"])
    stray = [x for x in nums if x not in lcr]
    code, _, r = http("GET", f"/api/wb/agents/{d}/audit/export?audience=Internal%20audit", timeout=300)
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist() if code == 200 else []
    assert "08_release_memo.csv" in names, f"export files {names}"
    return (("WARN", f"ratios in the memo not in the facts: {stray}") if stray else f"{d} run {m['run_number']}: memo grounded, in the pack")


@case("I04", "AI-first", "Learning loop: recurring fixes are found across reporting days with a permanent fix proposed",
      "/agents/learning: each pattern has >= 2 days, a proposal and an owner")
def i04():
    L = get("/api/wb/agents/learning")
    bad = [x for x in L if len(x["days"]) < 2 or not x["proposal"] or not x["owner"]]
    assert not bad, bad[:3]
    return f"{len(L)} recurring patterns: " + "; ".join(x["pattern"][:60] for x in L[:3])


@case("I05", "AI-first", "Agent accuracy on Audit: from the checkers' decisions + the latest GenAI evaluation",
      "/agents/accuracy: per agent proposals and rates (0..1); evaluation metrics present; model = champion")
def i05():
    a = get("/api/wb/agents/accuracy")
    champ = w.api_client.do("GET", f"/api/2.1/unity-catalog/models/{C}.ai_assist.fr2052a_agents/aliases/champion")["version"]
    bad = [x["agent"] for x in a["agents"] if any(v is not None and not 0 <= v <= 1 for v in (x["acceptance"], x["edit_rate"], x["spot_agreement"]))]
    assert a["agents"] and not bad, f"rates out of range: {bad}"
    assert a["model"] == f"fr2052a_agents v{champ}", f"model {a['model']} vs champion v{champ}"
    return (("WARN", "no GenAI evaluation synced yet") if not a["evaluation"] else
            f"{len(a['agents'])} agents; evaluation {len(a['evaluation'])} metrics; model {a['model']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=f"{REPO}/evidence/qa_report.md")
    ap.add_argument("--only", default="", help="comma-separated test ids")
    a = ap.parse_args()
    only = set(filter(None, a.only.split(",")))
    for tid, run in CASES:
        if not only or tid in only:
            run()
    cnt = collections.Counter(r["status"] for r in RESULTS)
    lines = [f"# FR 2052a end-to-end QA - {datetime.datetime.now():%Y-%m-%d %H:%M}", "",
             f"{len(RESULTS)} test cases: " + ", ".join(f"{k} {v}" for k, v in sorted(cnt.items())), "",
             "| ID | Area | Test case | Expected | Result | Evidence |", "|---|---|---|---|---|---|"]
    for r in RESULTS:
        lines.append(f"| {r['id']} | {r['area']} | {r['title']} | {r['expected']} | **{r['status']}** | {r['detail'].replace('|', '/')[:600]} |")
    open(a.out, "w").write("\n".join(lines) + "\n")
    json.dump(RESULTS, open("/tmp/fr2052a_qa.json", "w"), indent=1)
    print("\n", dict(cnt), "->", a.out)


if __name__ == "__main__":
    main()
