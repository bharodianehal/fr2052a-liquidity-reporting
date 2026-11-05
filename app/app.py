"""
FR 2052a Liquidity Risk Platform - Backend API (v9 - reporting workbench)
  - Lakebase PostgreSQL for UI reads (synced from Delta by notebook 07) and the submission sign-off log
  - SQL Warehouse for the catalog schema list only
"""
import os, io, json
from datetime import datetime
from typing import Optional
from contextlib import contextmanager
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import StreamingResponse
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState
import threading
import time
import psycopg2
import psycopg2.extras
import psycopg2.pool

_DATES = {"t": 0, "dates": set()}


def _reporting_dates():
    """The reporting dates of this deployment (as /api/dates), cached for a minute."""
    if time.time() - _DATES["t"] > 60:
        _DATES.update(t=time.time(), dates=set(get_dates()))
    return _DATES["dates"]


def check_dates(request: Request):
    """Every route: a malformed date -> 400; a {date} that is not a reporting date of this deployment -> 404 (never a 500 or an empty 200)."""
    for v in (request.path_params.get("date"), request.query_params.get("start"), request.query_params.get("end")):
        if v is not None:
            try:
                datetime.strptime(v, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(400, "date must be YYYY-MM-DD")
    d = request.path_params.get("date")
    if d is not None and d not in _reporting_dates():
        raise HTTPException(404, f"{d} is not a reporting date")


app = FastAPI(title="FR 2052a Liquidity Risk Platform", version="3.0.0", dependencies=[Depends(check_dates)])

# ─── Configuration ────────────────────────────────────────────────
CATALOG = os.environ.get("CATALOG", "")
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
REPORTING_START = os.environ.get("REPORTING_START", "1900-01-01")

# Lakebase connection config (auto-injected PG* env vars take priority)
PG_HOST = os.environ.get("PGHOST", os.environ.get("LAKEBASE_HOST", ""))
PG_PORT = int(os.environ.get("PGPORT", os.environ.get("LAKEBASE_PORT", "5432")))
PG_DB = os.environ.get("PGDATABASE", os.environ.get("LAKEBASE_DB", "fr2052a"))
LAKEBASE_ENDPOINT = os.environ.get("LAKEBASE_ENDPOINT", "projects/fr2052a/branches/production/endpoints/primary")

# Cached Lakebase credentials (token expires, refresh periodically)
_pg_creds = {"user": None, "password": None, "expires": 0}

# ─── Database Connections ─────────────────────────────────────────

def get_ws():
    return WorkspaceClient()

def _refresh_pg_creds():
    """Generate fresh Lakebase credentials. Uses auto-injected env vars if available."""
    import time
    now = time.time()
    if _pg_creds["user"] and now < _pg_creds["expires"]:
        return _pg_creds["user"], _pg_creds["password"]

    # Try auto-injected env vars first (Databricks Apps lakebase resource)
    pg_user = os.environ.get("PGUSER")
    pg_pass = os.environ.get("PGPASSWORD")
    if pg_user and pg_pass:
        _pg_creds["user"] = pg_user
        _pg_creds["password"] = pg_pass
        _pg_creds["expires"] = now + 3000
        print(f"[Lakebase] Using auto-injected credentials for {pg_user}")
        return pg_user, pg_pass

    # Fall back to manual OAuth token generation
    w = get_ws()
    cred = w.api_client.do("POST", "/api/2.0/postgres/credentials", body={
        "endpoint": LAKEBASE_ENDPOINT
    })
    token = cred.get("token", "")
    me = w.current_user.me()
    user = me.user_name

    _pg_creds["user"] = user
    _pg_creds["password"] = token
    _pg_creds["expires"] = now + 3000  # Refresh before 1h expiry
    print(f"[Lakebase] Generated OAuth token for {user}")
    return user, token

def run_sql(sql: str) -> list[dict]:
    """Execute SQL via Databricks SQL Warehouse (used only for silver queries)."""
    w = get_ws()
    resp = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID, statement=sql, wait_timeout="30s"
    )
    import time
    deadline = time.time() + 120
    while resp.status.state in (StatementState.PENDING, StatementState.RUNNING) and time.time() < deadline:
        time.sleep(2)
        resp = w.statement_execution.get_statement(resp.statement_id)
    if resp.status.state != StatementState.SUCCEEDED:
        msg = resp.status.error.message if resp.status.error else "Query failed"
        raise HTTPException(500, detail=msg)
    cols = [c.name for c in resp.manifest.schema.columns]
    return [dict(zip(cols, row)) for row in (resp.result.data_array or [])]

# The app reads Delta through Lakebase synced tables (schema app_serving, refreshed by notebook 07) and writes its own tables in public.
PG_OPTIONS = "-c search_path=app_serving,public"

# A pool of Lakebase connections (a new SSL connection per query cost ~100 ms); rebuilt when the credentials rotate.
_pool = {"key": None, "pool": None}
_pool_lock = threading.Lock()


def _pg_pool():
    user, password = _refresh_pg_creds()
    with _pool_lock:
        if _pool["key"] != (user, password):
            _pool.update(key=(user, password), pool=psycopg2.pool.ThreadedConnectionPool(
                1, 20, host=PG_HOST, port=PG_PORT, database=PG_DB, user=user, password=password, sslmode="require",
                connect_timeout=10, keepalives=1, keepalives_idle=30, options=PG_OPTIONS))
        return _pool["pool"]


@contextmanager
def get_pg():
    """A pooled Lakebase PostgreSQL connection. Whatever the caller does not commit is rolled back when it goes back to the pool."""
    pool = _pg_pool()
    try:
        conn = pool.getconn()
    except psycopg2.pool.PoolError:   # all in use: a one-off connection
        pool, conn = None, psycopg2.connect(host=PG_HOST, port=PG_PORT, database=PG_DB, user=_pool["key"][0], password=_pool["key"][1], sslmode="require",
                                            options=PG_OPTIONS)
    ok = False
    try:
        yield conn
        ok = True
    finally:
        try:
            if not conn.closed:
                conn.rollback()
        except Exception:
            ok = False
        if pool is None:
            conn.close()
        else:
            pool.putconn(conn, close=not ok or bool(conn.closed))

def _as_text(v):
    """A value as the SQL warehouse returns it (every value a string), so a read moved from Delta to Lakebase keeps its shape."""
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, datetime):
        return v.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, (list, dict)):
        return json.dumps(v, default=str)
    return format(v, "f") if hasattr(v, "as_tuple") else str(v)


def run_wh(sql: str, params=None) -> list[dict]:
    """A read of the Delta layers, served from their Lakebase synced tables (app_serving) - drop-in for run_sql: values as text."""
    return [{k: _as_text(v) for k, v in r.items()} for r in run_pg(sql, params)]


def run_pg(sql: str, params=None) -> list[dict]:
    """Execute SQL against Lakebase PostgreSQL (one retry if a pooled connection was dropped by the server)."""
    for attempt in (1, 2):
        try:
            with get_pg() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(sql, params)
                    return [{k: v for k, v in row.items() if k != "_row_key"} for row in cur.fetchall()] if cur.description else []   # _row_key: the synced tables' key
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            if attempt == 2:
                raise

# ─── Available Dates ───────────────────────────────────────────────
@app.get("/api/dates")
def get_dates():
    # the reporting window of this deployment (REPORTING_START); days before it are history, not offered for reporting
    rows = run_pg("SELECT DISTINCT as_of_date FROM assessment_results WHERE as_of_date >= %s ORDER BY as_of_date DESC", (REPORTING_START,))
    return [str(r["as_of_date"]) for r in rows]

# ─── Executive Dashboard ──────────────────────────────────────────


# ─── DQ Assessment ────────────────────────────────────────────────



# ─── FR 2052a data tables ─────────────────────────────────────────
# The 13 data tables + Comments (Data Tables p.84-85); filing_records is the cross-table view with one primary amount.






@app.get("/api/filing/{date}/summary")
def get_filing_summary(date: str):
    return run_pg("""
        SELECT fr.table_code || ' ' || REPLACE(t.table_name, 'Supplemental-', '') AS section_name,
               CASE WHEN fr.table_code LIKE 'I.%%' THEN 'Inflow' WHEN fr.table_code LIKE 'O.%%' THEN 'Outflow' ELSE 'Supplemental' END AS direction,
               COUNT(*) AS record_count,
               SUM(CASE WHEN fr.product_id IN ('S.L.6', 'S.L.10') THEN 0 ELSE fr.reported_amount_usd END) AS total_amount
        FROM filing_records fr JOIN spec_tables t ON t.table_code = fr.table_code
        WHERE fr.as_of_date = %s GROUP BY 1, 2, fr.table_code ORDER BY fr.table_code
    """, (date,))

@app.get("/api/tables")
def get_tables():
    return run_pg("SELECT table_code, table_name, section, gold_table, xml_report_type FROM spec_tables ORDER BY table_code")

@app.get("/api/filing/{date}/table/{table_code}")
def get_table_records(date: str, table_code: str):
    """All fields of one FR 2052a data table, as filed (incl. 6G reportID and validation issues)."""
    t = run_pg("SELECT gold_table FROM spec_tables WHERE table_code = %s", (table_code,))
    if not t:
        raise HTTPException(404, "Unknown table")
    fields = run_pg("SELECT column_name, field_name, field_class, xml_element FROM spec_table_fields WHERE table_code = %s ORDER BY seq", (table_code,))
    rows = run_pg(f"SELECT * FROM {t[0]['gold_table']} WHERE as_of_date = %s ORDER BY product_id, report_id", (date,))
    return {"fields": fields, "rows": rows}

# ─── 6G submission: files, validation, business review and sign-off ─────────
def _latest_run(date):
    v = run_pg("SELECT MAX(run_number) AS r FROM submission_files WHERE as_of_date = %s", (date,))
    return v[0]["r"] if v and v[0]["r"] is not None else None

def _review_status(date, run):
    log = run_pg("SELECT * FROM submission_review WHERE as_of_date = %s AND run_number = %s ORDER BY action_timestamp", (date, run))
    return (log[-1]["status"] if log else None), log

@app.get("/api/submission/{date}")
def get_submission(date: str, run: Optional[int] = None):
    run = run or _latest_run(date)
    if run is None:
        return {"run_number": None}
    files = run_pg("""SELECT file_type, file_name, run_number, version, reporting_frequency, report_types, record_count, xsd_valid, xsd_errors,
                             xsd_error_sample, br_rules_failed, release_status, xml_size_bytes, file_path, generated_timestamp
                      FROM submission_files WHERE as_of_date = %s AND run_number = %s ORDER BY file_type DESC""", (date, run))
    status, log = _review_status(date, run)
    gen = next((r for r in log if r["action"] == "GENERATED"), None)
    released_by = gen["actor"] if gen and gen["actor"] != "fr2052a pipeline" else None   # generated for release in step 5 (fr2052a-generate)
    runs = run_pg("""SELECT run_number, MAX(version) AS version, MAX(release_status) AS release_status, MIN(generated_timestamp) AS generated
                     FROM submission_files WHERE as_of_date = %s GROUP BY run_number ORDER BY run_number DESC""", (date,))
    summary = run_pg("""SELECT rule_source, status, COUNT(*) AS rules FROM gold_validation WHERE as_of_date = %s
                        GROUP BY rule_source, status ORDER BY rule_source, status""", (date,))
    issues = run_pg("""SELECT rule_id, rule_source, appendix, table_code, rule_name, rule_category, severity, status, records_failed, failure_details
                       FROM gold_validation WHERE as_of_date = %s AND status IN ('FAIL', 'WARNING')
                       ORDER BY CASE status WHEN 'FAIL' THEN 0 ELSE 1 END, rule_id""", (date,))
    recon = run_pg("SELECT recon_type AS name, gl_total AS expected, pipeline_total AS actual, difference_pct, status, details FROM gl_reconciliation WHERE as_of_date = %s", (date,))
    recon += run_pg("SELECT entity_id || ' ' || metric_name AS name, reg_lcr_value AS expected, reg_2052a_value AS actual, NULL AS difference_pct, status, details FROM cross_metric_recon WHERE as_of_date = %s", (date,))
    pid = run_pg("SELECT * FROM pid_derivation_summary WHERE as_of_date = %s", (date,))
    exceptions = run_pg("SELECT record_id, exception_type, source_system, source_product_code, reason, amount_usd, review_status FROM pid_exceptions WHERE as_of_date = %s", (date,))
    entities = run_pg("SELECT entity_id, entity_name, scope_type, entity_type, fed_category, reporter_ticker, listing_exchange, primary_timing, reduced_timing FROM ref_reporting_entity ORDER BY entity_id")
    return {"run_number": run, "version": files[0]["version"] if files else None, "status": status, "runs": runs, "files": files,
            "released_by": released_by, "generated_at": gen["action_timestamp"] if gen else None,
            "review_log": log, "validation_summary": summary, "issues": issues, "recon": recon, "pid": pid[0] if pid else None,
            "pid_exceptions": exceptions, "entities": entities, "entity": entities[0] if entities else None, "due": _due_dates(date)}

_HOLIDAYS = None


def holidays():
    """The Federal Reserve holiday calendar (reference.ref_bank_holidays), read once."""
    global _HOLIDAYS
    if _HOLIDAYS is None:
        from datetime import date as _d
        try:
            _HOLIDAYS = {_d.fromisoformat(str(r["holiday_date"])[:10]) for r in run_wh(f"SELECT holiday_date FROM ref_bank_holidays")}
        except Exception:
            return set()
    return _HOLIDAYS


def is_business_day(d):
    return d.weekday() < 5 and d not in holidays()


def _due_dates(date):
    """6G BR General #8: Primary T+2 business days (weekends and Federal Reserve holidays), Reduced T+15 calendar days."""
    from datetime import date as _d, timedelta
    d = _d.fromisoformat(date)
    p, n = d, 0
    while n < 2:
        p += timedelta(days=1)
        if is_business_day(p):
            n += 1
    return {"primary": p.isoformat(), "reduced": (d + timedelta(days=15)).isoformat()}

# Reporting-run control (maker / checker). A run is GENERATED as READY_FOR_REVIEW or BLOCKED by notebook 06.
#   APPROVED            <- READY_FOR_REVIEW, or OVERRIDE_REQUESTED by someone else
#   OVERRIDE_REQUESTED  <- BLOCKED (a documented reason to file despite failed checks)
#   REJECTED            <- READY_FOR_REVIEW, BLOCKED, OVERRIDE_REQUESTED, APPROVED
#   SUBMITTED           <- APPROVED, by someone other than the approver (four eyes)
#   REPORTING_REQUESTED <- any state except SUBMITTED: asks for a new run (fixes made); triggers fr2052a-daily
TRANSITIONS = {"APPROVED": {"READY_FOR_REVIEW", "OVERRIDE_REQUESTED"}, "OVERRIDE_REQUESTED": {"BLOCKED"},
               "REJECTED": {"READY_FOR_REVIEW", "BLOCKED", "OVERRIDE_REQUESTED", "APPROVED"}, "SUBMITTED": {"APPROVED"},
               "REPORTING_REQUESTED": {"READY_FOR_REVIEW", "BLOCKED", "OVERRIDE_REQUESTED", "APPROVED", "REJECTED", "REPORTING_REQUESTED"}}

def _user(request: Request):
    return request.headers.get("X-Forwarded-Email") or request.headers.get("X-Forwarded-User") or "app"

@app.post("/api/submission/{date}/review")
def review_submission(date: str, data: dict, request: Request):
    """Record a reporting-run action on the latest run (see TRANSITIONS)."""
    action = (data.get("action") or "").upper()
    note = (data.get("note") or "").strip()[:1000]
    if action not in TRANSITIONS:
        raise HTTPException(400, f"action must be one of {', '.join(TRANSITIONS)}")
    if action in ("REJECTED", "OVERRIDE_REQUESTED", "REPORTING_REQUESTED") and not note:
        raise HTTPException(400, f"{action.lower().replace('_', ' ')} needs a note")
    if action == "REPORTING_REQUESTED":
        _no_active_run(date)
    run = _latest_run(date)
    if run is None:
        raise HTTPException(404, "No reporting run for this date")
    status, log = _review_status(date, run)
    if status not in TRANSITIONS[action]:
        raise HTTPException(409, f"Cannot {action.lower().replace('_', ' ')} a run that is {status}")
    user = _user(request)
    if action == "APPROVED" and not (log and next((r for r in log if r["action"] == "GENERATED"), {}).get("actor") not in (None, "fr2052a pipeline")):
        raise HTTPException(409, "Generate the 6G files for release first (step 5) - only a release generation can be approved")
    if action == "SUBMITTED" and any(r["action"] == "APPROVED" and r["actor"] == user for r in log):
        raise HTTPException(409, "The approver cannot also submit (four eyes)")
    if action == "APPROVED" and status == "OVERRIDE_REQUESTED" and log[-1]["actor"] == user:
        raise HTTPException(409, "The override must be approved by someone other than the requester (four eyes)")
    version = run_pg("SELECT MAX(version) AS v FROM submission_files WHERE as_of_date = %s AND run_number = %s", (date, run))[0]["v"]
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO submission_review (as_of_date, run_number, version, action, status, actor, note, action_timestamp)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())""", (date, run, version, action, action, user, note))
        conn.commit()
    out = {"run_number": run, "version": version, "status": action}
    if action == "REPORTING_REQUESTED":
        out["job_run_id"] = run_pipeline({"date": date, "scope": "both"}, request)["run_id"]
    return out

@app.get("/api/submission/{date}/file/{file_type}")
def download_submission_file(date: str, file_type: str, run: Optional[int] = None):
    run = run or _latest_run(date)
    rows = run_pg("SELECT file_name, xml_content FROM submission_files WHERE as_of_date = %s AND run_number = %s AND file_type = %s",
                  (date, run, file_type))
    if not rows:
        raise HTTPException(404, "File not found")
    return StreamingResponse(io.BytesIO(rows[0]["xml_content"].encode("utf-8")), media_type="application/xml",
                             headers={"Content-Disposition": f"attachment; filename={rows[0]['file_name']}"})


@app.get("/api/submission-history")
def submission_history():
    return run_pg("""SELECT r.as_of_date, r.run_number, r.version, r.action, r.status, r.actor, r.note, r.action_timestamp
                     FROM submission_review r ORDER BY r.action_timestamp DESC LIMIT 200""")

# ─── PID derivation ───────────────────────────────────────────────

# ─── LCR ──────────────────────────────────────────────────────────



# ─── Validation ───────────────────────────────────────────────────
@app.get("/api/validation/{date}")
def get_validation(date: str):
    return run_pg("""
        SELECT gv.rule_id, gv.rule_name, gv.rule_source, gv.appendix, gv.table_code AS schedule_code, gv.severity, gv.status,
               gv.records_checked, gv.records_failed, gv.failure_details, gv.rule_category,
               rv.report_type, rv.xml_element, rv.validation_rule, rv.required_by_schema, rv.enforced_by
        FROM gold_validation gv
        LEFT JOIN rules_validation rv ON gv.rule_id = rv.rule_id
        WHERE gv.as_of_date = %s ORDER BY gv.rule_id
    """, (date,))

# ─── Reconciliation ──────────────────────────────────────────────

# ─── Data Lineage ────────────────────────────────────────────────

# ─── Configuration: reference data ───────────────────────────────
CONFIG = {
    "products": "SELECT product_id, table_code, product_number, product_name, instructions_name, table_name, definition_page FROM ref_product ORDER BY table_code, product_number",
    "counterparties": "SELECT counterparty, counterparty_category, is_financial, source FROM ref_counterparty ORDER BY counterparty",
    "collateral": "SELECT collateral_class, description, hqla_level, lcr_haircut_pct, is_hqla FROM ref_collateral ORDER BY collateral_class",
    "bank-holidays": "SELECT holiday_date, holiday_name, calendar FROM ref_bank_holidays ORDER BY holiday_date",
    "maturity-buckets": "SELECT bucket_seq, bucket_label, maturity_start, maturity_end, day_start, day_end, bucket_type, is_within_30d, is_standard FROM ref_maturity_bucket ORDER BY bucket_seq",
    "header": "SELECT * FROM ref_reporting_entity",
    "firm-schema": "SELECT list_name, value, description FROM ref_firm_schema_values ORDER BY list_name, value",
    "standard-products": "SELECT standard_product_type, source_system, description, requires_customer, requires_collateral, candidate_product_ids FROM ref_standard_product_type ORDER BY source_system, standard_product_type",
    "source-products": "SELECT source_system, source_product_code, standard_product_type, description, approved_on FROM ref_source_product_map ORDER BY source_system, source_product_code",
    "pid-rules": "SELECT rule_id, standard_product_type, priority, condition_sql, product_id, rationale FROM rules_pid_derivation ORDER BY standard_product_type, priority",
    "customers": "SELECT customer_id, customer_name, counterparty, gsib_parent, affiliate_legal_entity_id, has_relationship, approved_on, approved_by FROM ref_customer_master ORDER BY customer_id",
    "legal-entities": "SELECT legal_entity_id, legal_name, entity_type, parent_legal_entity_id, country FROM ref_legal_entity ORDER BY legal_entity_id",
    "fed-psv": "SELECT * FROM rules_fed_psv ORDER BY check_no",
    "templates": "SELECT * FROM ref_report_template ORDER BY activated_on",
    "stwf-rules": "SELECT * FROM rules_stwf_appendix_vii ORDER BY rule_id",
    "dq-rules": "SELECT rule_id, rule_name, rule_description, rule_category, severity, fail_predicate, quarantine FROM rules_dq ORDER BY rule_id",
    "lcr-rules": """SELECT rule_id, rule_section, rule_name, rule_description, flow_direction, applicable_product_ids, counterparty_condition,
                    counterparty_category_condition, collateral_hqla_condition, maturity_condition, outflow_rate, inflow_rate, rule_priority
                    FROM rules_lcr_appendix_vi ORDER BY rule_id""",
    "validation-rules": """SELECT rule_id, report_type, schedule_code, seq_num, business_field, xml_element, xml_child_element, required_by_schema,
                           xml_data_type, validation_rule, enumeration_ref, rule_category, enforced_by, severity FROM rules_validation ORDER BY rule_id""",
    "spec-rules": "SELECT rule_id, appendix, table_code, rule_name, check_type, severity, params FROM rules_spec ORDER BY rule_id",
}

@app.get("/api/config/{name}")
def get_config(name: str):
    if name not in CONFIG:
        raise HTTPException(404, "Unknown configuration table")
    return run_pg(CONFIG[name])

# ─── Report downloads ─────────────────────────────────────────────
@app.get("/api/filing/{date}/download-excel")
def download_excel(date: str):
    """One sheet per FR 2052a data table with every field, as filed."""
    import pandas as pd
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(get_filing_summary(date)).to_excel(writer, sheet_name="Summary", index=False)
        for t in get_tables():
            rows = run_pg(f"SELECT * FROM {t['gold_table']} WHERE as_of_date = %s ORDER BY product_id, report_id", (date,))
            if rows:
                pd.DataFrame(rows).to_excel(writer, sheet_name=f"{t['table_code']} {t['table_name']}"[:31].replace("/", "-"), index=False)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f"attachment; filename=FR2052a_{date}_6G.xlsx"})


# ─── Schemas info ─────────────────────────────────────────────────

# ─── Genie (Natural Language Q&A) ────────────────────────────────

GENIE_SPACE_ID = os.environ.get("GENIE_SPACE_ID", "")

def _genie_api(method: str, path: str, body: dict = None):
    """Call Genie REST API via workspace client."""
    w = get_ws()
    if method == "GET":
        return w.api_client.do("GET", path)
    else:
        return w.api_client.do("POST", path, body=body or {})


def _fetch_statement_result(statement_id: str) -> tuple:
    """Fetch query results from the Statement Execution API."""
    w = get_ws()
    try:
        resp = w.api_client.do("GET", f"/api/2.0/sql/statements/{statement_id}")
        state = resp.get("status", {}).get("state", "")
        if state != "SUCCEEDED":
            return [], []
        manifest = resp.get("manifest", {})
        columns = [c.get("name", f"col{i}") for i, c in enumerate(manifest.get("schema", {}).get("columns", []))]
        rows = resp.get("result", {}).get("data_array", [])
        return columns, rows
    except Exception:
        return [], []

def _extract_genie_result(resp: dict) -> dict:
    """Extract answer text, SQL, table data, and follow-up suggestions from Genie response."""
    status = resp.get("status", "UNKNOWN")
    if status != "COMPLETED":
        error = resp.get("error", {}).get("message", "Query did not complete")
        return {"text": f"Sorry, I couldn't answer that. {error}", "sql": None, "columns": [], "rows": [], "suggestions": []}

    attachments = resp.get("attachments", [])
    text_parts = []
    sql = None
    statement_id = None
    columns = []
    rows = []
    suggestions = []

    for att in attachments:
        if "text" in att:
            text_content = att["text"].get("content", "")
            if text_content:
                text_parts.append(text_content)

        if "query" in att:
            q = att["query"]
            sql = q.get("query", "")
            desc = q.get("description", "")
            if desc and desc not in text_parts:
                text_parts.insert(0, desc)
            # Get statement_id from the query attachment
            meta = q.get("query_result_metadata", {})
            if isinstance(meta, dict):
                statement_id = meta.get("statement_id")

        if "suggested_questions" in att:
            suggestions = att["suggested_questions"].get("questions", [])

    # Also check top-level query_result for statement_id
    if not statement_id:
        statement_id = resp.get("query_result", {}).get("statement_id")

    # Fetch actual row data from Statement Execution API
    if statement_id:
        columns, rows = _fetch_statement_result(statement_id)

    answer_text = "\n\n".join(text_parts) if text_parts else "Here are the results:"
    return {"text": answer_text, "sql": sql, "columns": columns, "rows": rows, "suggestions": suggestions}





# ─── Run Pipeline (fr2052a-daily job) ─────────────────────────────
DAILY_JOB_ID = os.environ.get("DAILY_JOB_ID", "")
SCOPE_LABELS = {"both": "FR 2052a + LCR", "2052a": "FR 2052a", "lcr": "LCR"}

def _fmt_ts(ms):
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S") if ms else "--"

def _run_row(run: dict) -> dict:
    params = {p["name"]: p.get("value", p.get("default")) for p in run.get("job_parameters", [])}
    state = run.get("state", {})
    life, result = state.get("life_cycle_state", ""), state.get("result_state", "")
    if life in ("PENDING", "QUEUED", "RUNNING", "TERMINATING", "BLOCKED"):
        status = "Running" if life == "RUNNING" else life.title()
    elif result == "SUCCESS":
        status = "Completed Successfully"
    else:
        status = (result or life).replace("_", " ").title()
    start, end = run.get("start_time"), run.get("end_time")
    secs = int(((end or 0) - (start or 0)) / 1000) if end else None
    return {
        "id": str(run["run_id"]),
        "date": params.get("as_of_date", ""),
        "pipeline": SCOPE_LABELS.get(params.get("scope", "both"), params.get("scope", "")),
        "user": params.get("requested_by") or run.get("creator_user_name", ""),
        "started": _fmt_ts(start),
        "completed": _fmt_ts(end),
        "duration": f"{secs // 60}m {secs % 60:02d}s" if secs is not None else "--",
        "status": status,
        "url": run.get("run_page_url", ""),
    }

def active_run(date: str):
    """The run already building this as-of date (fr2052a-daily, -revalidate or -generate), if any: one run per date at a time,
    two runs of the same day would overwrite each other's tables."""
    for job in (DAILY_JOB_ID, os.environ.get("REVALIDATE_JOB_ID", ""), os.environ.get("GENERATE_JOB_ID", "")):
        if not job:
            continue
        for r in get_ws().api_client.do("GET", "/api/2.2/jobs/runs/list", query={"job_id": job, "active_only": "true", "limit": 25}).get("runs", []):
            if any(p.get("name") == "as_of_date" and p.get("value", p.get("default")) == date for p in r.get("job_parameters", [])):
                return str(r["run_id"])
    return None


def _no_active_run(date: str):
    rid = active_run(date)
    if rid:
        raise HTTPException(409, f"{date} is already being built (job run {rid}); wait for it to finish")


@app.post("/api/pipeline/run")
def run_pipeline(data: dict, request: Request):
    """Trigger fr2052a-daily for one as_of_date and scope (both | 2052a | lcr)."""
    if not DAILY_JOB_ID:
        raise HTTPException(500, "DAILY_JOB_ID is not configured")
    as_of = (data.get("date") or "").strip()
    scope = data.get("scope", "both")
    try:
        datetime.strptime(as_of, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    if as_of not in _reporting_dates():
        raise HTTPException(404, f"{as_of} is not a reporting date")
    if scope not in SCOPE_LABELS:
        raise HTTPException(400, "scope must be both, 2052a or lcr")
    _no_active_run(as_of)
    user = request.headers.get("X-Forwarded-Email") or request.headers.get("X-Forwarded-User") or "app"
    resp = get_ws().api_client.do("POST", "/api/2.2/jobs/run-now", body={
        "job_id": int(DAILY_JOB_ID),
        "job_parameters": {"as_of_date": as_of, "scope": scope, "requested_by": user},
    })
    return {"run_id": str(resp["run_id"])}

DEMO_RESET_JOB_ID = os.environ.get("DEMO_RESET_JOB_ID", "")


def _last_reset():
    runs = get_ws().api_client.do("GET", "/api/2.2/jobs/runs/list", query={"job_id": DEMO_RESET_JOB_ID, "limit": 1}).get("runs", [])
    if not runs:
        return {}
    st = runs[0]["state"]
    return {"run_id": str(runs[0]["run_id"]), "state": st.get("life_cycle_state"), "result": st.get("result_state")}


@app.get("/api/demo/resend")
def demo_resend_options():
    """Demo only (header icon): per reporting date, the position feeds that arrived short and could be re-sent by the source,
    and whether the day is being built right now (POST /api/wb/collect/{date}/resend/{feed} does the re-send)."""
    short = run_pg("""SELECT as_of_date::text AS date, feed, records, expected_records, status FROM feed_monitor
                      WHERE status <> 'PASS' AND feed IN ('deposits', 'loans', 'securities', 'derivatives', 'funding', 'finance')
                      ORDER BY as_of_date, feed""")
    out = []
    for d in sorted(_reporting_dates()):
        feeds = [{k: r[k] for k in ("feed", "records", "expected_records", "status")} for r in short if r["date"] == d]
        out.append({"date": d, "feeds": feeds, "running": active_run(d) if feeds else None})
    return out


@app.get("/api/demo/reset")
def demo_reset_status():
    """The last demo reset (fr2052a-demo-reset), for the small link in the sidebar."""
    return _last_reset() if DEMO_RESET_JOB_ID else {}


@app.post("/api/demo/reset")
def demo_reset(request: Request):
    """Demo environment only: put the demo dates back to 'nothing worked yet' (notebook 17), then re-run them."""
    if not DEMO_RESET_JOB_ID:
        raise HTTPException(500, "DEMO_RESET_JOB_ID is not configured")
    last = _last_reset()
    if last.get("state") in ("PENDING", "QUEUED", "RUNNING", "BLOCKED"):
        raise HTTPException(409, f"A reset is already running (job run {last['run_id']})")
    busy = [d for d in sorted(_reporting_dates()) if active_run(d)]
    if busy:
        raise HTTPException(409, f"{', '.join(busy)} is being built; reset when the run has finished")
    user = request.headers.get("X-Forwarded-Email") or request.headers.get("X-Forwarded-User") or "app"
    print(f"demo reset requested by {user}")
    resp = get_ws().api_client.do("POST", "/api/2.2/jobs/run-now", body={"job_id": int(DEMO_RESET_JOB_ID)})
    return {"run_id": str(resp["run_id"])}


@app.get("/api/pipeline/runs")
def list_pipeline_runs(limit: int = 25):
    """Recent fr2052a-daily runs, newest first."""
    if not DAILY_JOB_ID:
        return []
    resp = get_ws().api_client.do("GET", "/api/2.2/jobs/runs/list",
                                  query={"job_id": DAILY_JOB_ID, "limit": min(limit, 25)})
    return [_run_row(r) for r in resp.get("runs", [])]

# ─── Workspace Info ──────────────────────────────────────────────
@app.get("/api/workspace-url")
def get_workspace_url():
    """Return workspace URL for Databricks One link."""
    w = get_ws()
    host = w.config.host.rstrip("/")
    dash = os.environ.get("DASHBOARD_ID", "")
    ws_id = w.get_workspace_id() if (dash or GENIE_SPACE_ID) else None
    return {"url": host, "genie_url": f"{host}/genie/rooms/{GENIE_SPACE_ID}" if GENIE_SPACE_ID else None,
            # the Genie Agent embedded in the app (Share -> Embed agent; the app's domain is an approved embedding surface)
            "genie_embed_url": f"{host}/embed/genie/rooms/{GENIE_SPACE_ID}?o={ws_id}" if GENIE_SPACE_ID else None,
            "dashboard_id": dash or None, "workspace_id": ws_id if dash else None,
            "dashboard_url": f"{host}/dashboardsv3/{dash}/published" if dash else None,
            "lcr_dashboard_id": os.environ.get("LCR_DASHBOARD_ID") or None}

# ─── Reporting workbench (v9) ─────────────────────────────────────
from workbench import router as workbench_router
app.include_router(workbench_router)
from agents import router as agents_router   # AI maker, human checker
app.include_router(agents_router)

# ─── Serve React frontend ────────────────────────────────────────
class SPAStaticFiles(StaticFiles):
    """Serve index.html for client-side routes (e.g. /genie) so deep links and refreshes work."""
    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code != 404 or path.startswith("api") or "." in path.rsplit("/", 1)[-1]:
                raise
            return await super().get_response("index.html", scope)

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/", SPAStaticFiles(directory=static_dir, html=True), name="static")
