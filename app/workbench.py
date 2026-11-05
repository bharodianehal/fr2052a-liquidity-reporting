"""
FR 2052a reporting workbench (v9): the day-by-day process screens.

  calendar -> feeds -> AI review queue (enrichment / PID / rules) -> datasets per entity -> Fed checks -> variance
  -> drill-down -> adjustments (maker / checker) -> PID dictionary -> Genie (the FR 2052a Genie space)

Reads come from Lakebase (synced from Delta by notebook 07); the record drill-down reads Delta through the SQL
warehouse. People's decisions are written to Lakebase app tables, which notebooks 00 / 05 / 06 bring back into Delta.
"""
import json
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/wb")


class _Pg:
    """The app module's helpers, with one difference: a Lakebase table or column the pipeline has not published yet
    (notebook 07 creates them on its first run for a date) is a 503 with a clear message, not a 500."""
    def __getattr__(self, name):
        import app as main   # the FastAPI module: shared connection helpers
        return getattr(main, name)

    def run_pg(self, sql, params=None):
        import app as main
        import psycopg2
        try:
            return main.run_pg(sql, params)
        except (psycopg2.errors.UndefinedTable, psycopg2.errors.UndefinedColumn) as e:
            raise HTTPException(503, f"Not published to Lakebase yet - run the pipeline for this date ({str(e).splitlines()[0]})")


def _deps():
    return _Pg()


def _user(request: Request):
    return request.headers.get("X-Forwarded-Email") or request.headers.get("X-Forwarded-User") or "app"


# ─── Calendar: one row per business day, the state of its filing ─────────────
@router.get("/calendar")
def calendar():
    m = _deps()
    rows = m.run_pg("""
        WITH runs AS (SELECT as_of_date, MAX(run_number) AS run_number FROM submission_files GROUP BY as_of_date),
        st AS (SELECT DISTINCT ON (r.as_of_date) r.as_of_date, r.status, r.actor, r.action_timestamp
               FROM submission_review r JOIN runs USING (as_of_date) WHERE r.run_number = runs.run_number
               ORDER BY r.as_of_date, r.action_timestamp DESC),
        val AS (SELECT as_of_date, COUNT(*) FILTER (WHERE status = 'FAIL') AS fails,
                       COUNT(*) FILTER (WHERE status = 'WARNING') AS warnings,
                       COUNT(*) FILTER (WHERE rule_source = 'Fed PSV' AND status <> 'PASS') AS psv FROM gold_validation GROUP BY 1),
        feeds AS (SELECT as_of_date, COUNT(*) FILTER (WHERE status <> 'PASS') AS feed_issues FROM feed_monitor GROUP BY 1),
        ai AS (SELECT s.as_of_date, COUNT(DISTINCT s.suggestion_type || s.subject_key) AS open FROM ai_suggestions s LEFT JOIN ai_decisions d USING (suggestion_id)
               WHERE d.suggestion_id IS NULL GROUP BY 1),
        anom AS (SELECT as_of_date, COUNT(*) FILTER (WHERE is_anomaly) AS anomalies FROM variance GROUP BY 1)
        SELECT runs.as_of_date, runs.run_number, st.status, st.actor, st.action_timestamp, val.fails, val.warnings, val.psv,
               COALESCE(feeds.feed_issues, 0) AS feed_issues, COALESCE(ai.open, 0) AS open_ai, COALESCE(anom.anomalies, 0) AS anomalies
        FROM runs LEFT JOIN st USING (as_of_date) LEFT JOIN val USING (as_of_date) LEFT JOIN feeds USING (as_of_date)
        LEFT JOIN ai USING (as_of_date) LEFT JOIN anom USING (as_of_date)
        ORDER BY runs.as_of_date DESC""")
    for r in rows:
        r["due"] = m._due_dates(str(r["as_of_date"]))["primary"]
    return rows


@router.get("/today/{date}")
def today(date: str):
    """The analyst's checklist for one as-of date: the five steps, each with its open items."""
    m = _deps()
    one = lambda sql: (m.run_pg(sql, (date,)) or [{}])[0]
    feeds = one("""SELECT COUNT(*) AS feeds, COUNT(*) FILTER (WHERE status <> 'PASS') AS issues,
                          STRING_AGG(CASE WHEN status <> 'PASS' THEN feed || ' ' || status END, ', ') AS detail
                   FROM feed_monitor WHERE as_of_date = %s""")
    dq = one("SELECT COUNT(*) FILTER (WHERE status = 'FAIL') AS fails, COUNT(*) FILTER (WHERE status = 'WARNING') AS warnings FROM assessment_results WHERE as_of_date = %s")
    quarantined = one("SELECT COUNT(*) AS n FROM quarantine WHERE as_of_date = %s")
    pid = one("SELECT source_records, positions, derived, exceptions FROM pid_derivation_summary WHERE as_of_date = %s")
    exc = one("""SELECT COUNT(*) FILTER (WHERE exception_type = 'NO_RULE') AS no_rule,
                        COUNT(*) FILTER (WHERE exception_type = 'CUSTOMER_PENDING') AS customer_pending FROM pid_exceptions WHERE as_of_date = %s""")
    ai = {r["suggestion_type"]: r["n"] for r in m.run_pg("""
        SELECT s.suggestion_type, COUNT(DISTINCT s.subject_key) AS n FROM ai_suggestions s LEFT JOIN ai_decisions d USING (suggestion_id)
        LEFT JOIN (""" + _MASTER_APPROVALS + """) ma ON ma.suggestion_type = s.suggestion_type AND ma.subject_key = s.subject_key AND ma.approved_on <= %s
        WHERE d.suggestion_id IS NULL AND ma.subject_key IS NULL
          AND (s.as_of_date = %s OR (s.suggestion_type IN ('CUSTOMER_CLASSIFICATION', 'PRODUCT_MAPPING') AND s.as_of_date <= %s))
        GROUP BY 1""", (date, date, date))}
    val = one("""SELECT COUNT(*) FILTER (WHERE status = 'FAIL' AND severity = 'ERROR') AS errors, COUNT(*) FILTER (WHERE status = 'FAIL') AS fails,
                        COUNT(*) FILTER (WHERE status = 'WARNING') AS warnings,
                        COUNT(*) FILTER (WHERE rule_source = 'Fed PSV' AND status <> 'PASS') AS psv FROM gold_validation WHERE as_of_date = %s""")
    gl = one("SELECT COUNT(*) FILTER (WHERE status <> 'PASS') AS breaks FROM gl_reconciliation WHERE as_of_date = %s")
    try:
        vq = [x for x in validate_queue(date) if x["state"] == "open"]
    except HTTPException:
        vq = []
    vq_open, vq_open_fail = len(vq), sum(1 for x in vq if x["status"] == "FAIL")
    xm = one("SELECT COUNT(*) FILTER (WHERE status <> 'PASS') AS breaks FROM cross_metric_recon WHERE as_of_date = %s")
    var = one("SELECT COUNT(*) AS series, COUNT(*) FILTER (WHERE is_anomaly) AS anomalies FROM variance WHERE as_of_date = %s")
    adj = one("SELECT COUNT(*) FILTER (WHERE status = 'PENDING') AS pending, COUNT(*) FILTER (WHERE status = 'APPROVED') AS approved FROM adjustments WHERE as_of_date = %s")
    lcr = m.run_pg("SELECT entity_id, lcr_ratio, lcr_compliant FROM calculation_results WHERE as_of_date = %s ORDER BY entity_id", (date,))
    sub = m.get_submission(date)
    rep = one("SELECT COUNT(DISTINCT table_code) AS tables, COUNT(*) AS records, SUM(record_count) AS positions FROM filing_records WHERE as_of_date = %s")
    by_entity = m.run_pg("SELECT reporting_entity, COUNT(*) AS records FROM filing_records WHERE as_of_date = %s GROUP BY 1 ORDER BY 1", (date,))
    xsd_bad = any(not f.get("xsd_valid") for f in sub.get("files", []))
    pc = one("SELECT COUNT(*) AS n FROM position_corrections WHERE as_of_date = %s AND status = 'PENDING'")
    fx = one("SELECT COUNT(*) AS n FROM dq_fixes WHERE as_of_date = %s AND status = 'PENDING'")
    built = bool(pid.get("positions"))
    classify_open = (exc.get("no_rule") or 0) + (exc.get("customer_pending") or 0) + sum(ai.get(k, 0) for k in ("CUSTOMER_CLASSIFICATION", "PRODUCT_MAPPING"))
    review_open = (var.get("anomalies") or 0) + (adj.get("pending") or 0)
    state = lambda bad, warn=0: "todo" if not built else ("action" if bad else ("check" if warn else "done"))
    return {
        "date": date, "built": built, "due": m._due_dates(date),
        "steps": [
            {"key": "collect", "title": "Collect", "state": state(feeds.get("issues") or 0),
             "facts": {"feeds": feeds.get("feeds"), "feed_issues": feeds.get("issues"), "feed_detail": feeds.get("detail")}},
            {"key": "dq", "title": "Data quality", "state": state(quarantined.get("n") or 0, dq.get("warnings") or 0),
             "facts": {"dq_fails": dq.get("fails"), "dq_warnings": dq.get("warnings"), "quarantined": quarantined.get("n"), "pending_fixes": fx.get("n")}},
            {"key": "enrich", "title": "PID enrichment", "state": state(classify_open),
             "facts": {"source_records": pid.get("source_records"), "positions": pid.get("positions"), "derived": pid.get("derived"),
                       "no_rule": exc.get("no_rule"), "customer_pending": exc.get("customer_pending"),
                       "ai_customers": ai.get("CUSTOMER_CLASSIFICATION", 0), "ai_products": ai.get("PRODUCT_MAPPING", 0), "ai_pid": ai.get("PID_EXCEPTION", 0)}},
            {"key": "validate", "title": "Validate",   # from the exceptions still open: a resolved / explained exception needs nothing more
             "state": "todo" if not built else ("action" if vq_open_fail or (xm.get("breaks") or 0) else ("check" if vq_open else "done")),
             "facts": {"errors": val.get("errors"), "fails": val.get("fails"), "warnings": val.get("warnings"), "fed_checks_not_passing": val.get("psv"),
                       "gl_breaks": gl.get("breaks"), "lcr_recon_breaks": xm.get("breaks"), "ai_explanations": ai.get("RULE_EXPLANATION", 0),
                       "pending_corrections": pc.get("n"), "records": rep.get("records"), "anomalies": var.get("anomalies"),
                       "open_exceptions": vq_open, "open_blocking_exceptions": vq_open_fail}},
            {"key": "release", "title": "Generate 6G & release",
             "state": "todo" if not sub.get("run_number") else ("done" if sub.get("status") == "SUBMITTED" else
                                                                ("action" if sub.get("status") in ("BLOCKED", "REJECTED") or xsd_bad else "check")),
             "facts": {"run_number": sub.get("run_number"), "status": sub.get("status"), "version": sub.get("version"),
                       "files": [{"file": f["file_name"], "xsd_valid": f["xsd_valid"]} for f in sub.get("files", [])],
                       "ai_comment_drafts": ai.get("COMMENT_DRAFT", 0) + ai.get("VARIANCE_COMMENTARY", 0)}},
        ],
    }


# ─── Collect drill-down: feed -> source records -> the DQ rules they failed -> what enrichment the passing ones got ─────
@router.get("/collect/{date}")
def collect(date: str):
    """Per feed: landing files, Bronze records, DQ-passed and quarantined; every DQ rule with its SQL and the records that failed it."""
    _check_date(date)
    m = _deps()
    feeds = m.run_wh(f"""
      WITH b AS (SELECT feed, COUNT(DISTINCT landing_file) AS files, COUNT(*) AS bronze, array_to_string(array_agg(DISTINCT landing_file), ', ') AS landing_files
                 FROM v_source_files WHERE as_of_date = '{date}' GROUP BY feed),
      p AS (SELECT source_feed AS feed, COUNT(*) AS passed FROM source_position WHERE as_of_date = '{date}' GROUP BY 1),
      q AS (SELECT source_feed AS feed, COUNT(*) AS quarantined FROM quarantine WHERE as_of_date = '{date}' GROUP BY 1),
      w AS (SELECT source_feed AS feed, COUNT(DISTINCT record_id) AS warned FROM rule_failures WHERE as_of_date = '{date}' AND NOT quarantined GROUP BY 1)
      SELECT b.feed, b.files, b.landing_files, b.bronze, COALESCE(p.passed, 0) AS passed, COALESCE(q.quarantined, 0) AS quarantined,
             COALESCE(w.warned, 0) AS warned
      FROM b LEFT JOIN p USING (feed) LEFT JOIN q USING (feed) LEFT JOIN w USING (feed) ORDER BY b.feed""")
    rules = m.run_wh(f"""
      SELECT r.rule_id, r.rule_name, r.rule_description, r.rule_category, r.severity, r.fail_predicate, r.quarantine, r.applicable_sources,
             a.total_records, a.failed_records, a.status,
             (SELECT COALESCE(array_to_string((array_agg(DISTINCT f.record_id ORDER BY f.record_id))[1:1 + 20 - 1], ', '), '') FROM rule_failures f
              WHERE f.as_of_date = '{date}' AND f.rule_id = r.rule_id) AS failing_records
      FROM rules_dq r
      LEFT JOIN assessment_results a ON a.as_of_date = '{date}' AND a.rule_id = r.rule_id
      ORDER BY r.rule_id""")
    return {"feeds": feeds, "rules": rules, "monitor": m.run_pg("SELECT * FROM feed_monitor WHERE as_of_date = %s ORDER BY feed", (date,))}



@router.get("/collect/{date}/record/{record_id}")
def collect_record(date: str, record_id: str):
    """One source record end to end: its landing file, every value as received, the DQ rules it failed (with the rule SQL),
    and - if it passed - the enrichment and PID derivation of each position it became."""
    _check_date(date)
    rid = _safe_id(record_id)
    m = _deps()
    src = m.run_wh(f"SELECT feed, landing_file, ingested_at FROM v_source_files WHERE as_of_date = '{date}' AND record_id = '{rid}' LIMIT 1")
    q = m.run_wh(f"SELECT failed_rules, record_json FROM quarantine WHERE as_of_date = '{date}' AND record_id = '{rid}'")
    passed = m.run_wh(f"SELECT * FROM source_position WHERE as_of_date = '{date}' AND record_id = '{rid}'")
    values = passed[0] if passed else (json.loads(q[0]["record_json"]) if q else {})
    failed = m.run_wh(f"""SELECT f.rule_id, f.severity, f.quarantined, r.rule_name, r.rule_description, r.rule_category, r.fail_predicate
                           FROM rule_failures f LEFT JOIN rules_dq r ON r.rule_id = f.rule_id
                           WHERE f.as_of_date = '{date}' AND f.record_id = '{rid}' ORDER BY f.rule_id""")
    enrichment = m.run_wh(f"""
      SELECT f.position_id, f.part, f.booking_entity, f.standard_product_type, f.product_id, f.pid_rule_id, r.condition_sql AS rule_condition,
             r.rationale AS rule_rationale, f.customer_id, f.counterparty, f.counterparty_category, f.gsib, f.affiliate_legal_entity_id,
             f.collateral_id, f.collateral_class, f.collateral_basis, f.is_hqla, f.maturity_date, f.maturity_basis, f.maturity_bucket,
             f.effective_maturity_date, f.weekend_flow, f.insured, f.insured_basis, f.lendable_value, f.lendable_basis, f.risk_weight,
             f.principal_amount, f.market_value, f.currency, f.enrichment_timestamp
      FROM fact_liquidity_position f LEFT JOIN rules_pid_derivation r ON r.rule_id = f.pid_rule_id
      WHERE f.as_of_date = '{date}' AND f.record_id = '{rid}' ORDER BY f.part""")
    held = m.run_wh(f"SELECT exception_type, reason, provisional_product_id FROM pid_exceptions WHERE as_of_date = '{date}' AND record_id = '{rid}'")
    return {"record_id": rid, "source": src[0] if src else None, "dq_result": "PASSED" if passed else ("QUARANTINED" if q else "UNKNOWN"),
            "quarantine_reason": q[0]["failed_rules"] if q else None, "values": values, "failed_rules": failed,
            "positions": enrichment, "held": held}





# A customer / product code proposal is decided once its master data is approved, whichever page approved it
# (e.g. a new product code mapped in the data quality queue is not asked again in PID enrichment).
_MASTER_APPROVALS = """SELECT 'CUSTOMER_CLASSIFICATION' AS suggestion_type, customer_id AS subject_key, approved_on, approved_by, decided_at FROM customer_master_approvals
                       UNION ALL SELECT 'PRODUCT_MAPPING', source_product_code, approved_on, approved_by, decided_at FROM source_product_map_approvals"""


# ─── AI review queue: proposals from Databricks AI Functions, decided by a person ─────
@router.get("/ai/{date}")
def ai_queue(date: str, kind: str = None):
    sql = """SELECT s.suggestion_id, s.as_of_date, s.suggestion_type, s.subject_key, s.subject, s.suggestion, s.rationale, s.ai_function,
                    s.model, s.confidence,
                    COALESCE(d.decision, CASE WHEN ma.approved_by IS NOT NULL THEN 'ACCEPTED' ELSE 'PROPOSED' END) AS status,
                    COALESCE(d.decided_by, ma.approved_by) AS decided_by, COALESCE(d.decided_at, ma.decided_at) AS decided_at,
                    COALESCE(d.note, CASE WHEN ma.approved_by IS NOT NULL THEN 'already approved in the master data (e.g. mapped in data quality)' END) AS note
             FROM ai_suggestions s LEFT JOIN ai_decisions d USING (suggestion_id)
             LEFT JOIN (""" + _MASTER_APPROVALS + """) ma ON ma.suggestion_type = s.suggestion_type AND ma.subject_key = s.subject_key AND ma.approved_on <= %s
             WHERE (s.as_of_date = %s OR (s.suggestion_type IN ('CUSTOMER_CLASSIFICATION', 'PRODUCT_MAPPING') AND s.as_of_date <= %s))"""
    params = [date, date, date]
    if kind:
        sql += " AND s.suggestion_type = %s"
        params.append(kind)
    rows = _deps().run_pg(f"""SELECT * FROM (SELECT DISTINCT ON (suggestion_type, subject_key) * FROM ({sql}) q
                              ORDER BY suggestion_type, subject_key, (status <> 'PROPOSED') DESC, as_of_date) x
                              ORDER BY suggestion_type, subject""", params)   # one row per customer / code (parallel runs can propose twice)
    for r in rows:
        try:
            r["suggestion"] = json.loads(r["suggestion"] or "{}")
        except ValueError:
            pass
    return rows


@router.post("/ai/{suggestion_id}/decide")
def ai_decide(suggestion_id: str, data: dict, request: Request):
    """Accept (optionally with edits) or reject one suggestion. Accepting master-data proposals writes the approval
    the pipeline uses from the suggestion's as-of date; comment drafts go into the next run's Comment file."""
    m = _deps()
    decision = (data.get("decision") or "").upper()
    if decision not in ("ACCEPTED", "REJECTED"):
        raise HTTPException(400, "decision must be ACCEPTED or REJECTED")
    rows = m.run_pg("SELECT * FROM ai_suggestions WHERE suggestion_id = %s", (suggestion_id,))
    if not rows:
        raise HTTPException(404, "Unknown suggestion")
    s = rows[0]
    sug = {**json.loads(s["suggestion"] or "{}"), **(data.get("edits") or {})}
    user, note = _user(request), (data.get("note") or "")[:1000]
    if decision == "REJECTED" and not note:
        raise HTTPException(400, "a rejection needs a note")
    with m.get_pg() as conn:
        with conn.cursor() as cur:
            # one decision per suggestion, kept as it was made (ai_decisions is append-only for the app - notebook 07 revokes UPDATE / DELETE)
            cur.execute("""INSERT INTO ai_decisions (suggestion_id, decision, decided_by, decided_at, note) VALUES (%s, %s, %s, NOW(), %s)
                           ON CONFLICT (suggestion_id) DO NOTHING RETURNING suggestion_id""", (suggestion_id, decision, user, note))
            if not cur.fetchone():
                conn.rollback()
                raise HTTPException(409, "This suggestion is already decided")
            if decision == "ACCEPTED" and s["suggestion_type"] == "CUSTOMER_CLASSIFICATION":
                cur.execute("""INSERT INTO customer_master_approvals VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                               ON CONFLICT (customer_id) DO UPDATE SET counterparty = EXCLUDED.counterparty, gsib_parent = EXCLUDED.gsib_parent,
                               affiliate_legal_entity_id = EXCLUDED.affiliate_legal_entity_id, has_relationship = EXCLUDED.has_relationship,
                               approved_on = EXCLUDED.approved_on, approved_by = EXCLUDED.approved_by, suggestion_id = EXCLUDED.suggestion_id,
                               decided_at = NOW()""",
                            (s["subject_key"], s["subject"], sug.get("counterparty"), sug.get("gsib_parent"), sug.get("affiliate_legal_entity_id"),
                             bool(sug.get("has_relationship")), s["as_of_date"], user, suggestion_id))
            if decision == "ACCEPTED" and s["suggestion_type"] == "PRODUCT_MAPPING":
                cur.execute("""INSERT INTO source_product_map_approvals VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                               ON CONFLICT (source_product_code) DO UPDATE SET standard_product_type = EXCLUDED.standard_product_type,
                               approved_on = EXCLUDED.approved_on, approved_by = EXCLUDED.approved_by, suggestion_id = EXCLUDED.suggestion_id,
                               decided_at = NOW()""",
                            (sug.get("source_product_code"), sug.get("source_system"), sug.get("standard_product_type"), sug.get("description"),
                             s["as_of_date"], user, suggestion_id))
        conn.commit()
    return {"suggestion_id": suggestion_id, "decision": decision,
            "next": "Re-run the day (Sign-off > Request reporting run) so the pipeline uses it" if decision == "ACCEPTED" else None}


# ─── Datasets per reporting entity, Fed checks, STWF ─────────────────────────
@router.get("/entity-summary/{date}")
def entity_summary(date: str):
    m = _deps()
    return {
        "tables": m.run_pg("""SELECT reporting_entity, table_code, COUNT(*) AS records, SUM(record_count) AS positions,
                                     SUM(CASE WHEN product_id IN ('S.L.6', 'S.L.10') THEN 0 ELSE reported_amount_usd END) AS usd
                              FROM filing_records WHERE as_of_date = %s GROUP BY 1, 2 ORDER BY 1, 2""", (date,)),
        "lcr": m.run_pg("""SELECT entity_id, total_hqla, total_outflows, capped_inflows, total_net_cash_outflows, lcr_ratio, lcr_compliant
                           FROM calculation_results WHERE as_of_date = %s ORDER BY entity_id""", (date,)),
        "eliminated": m.run_pg("SELECT * FROM intercompany_elimination WHERE as_of_date = %s", (date,)),
    }




# ─── Business review: variance (ai_forecast), drill-down, adjustments ────────
@router.get("/variance/{date}")
def variance(date: str, anomalies_only: bool = False):
    return _deps().run_pg(f"""SELECT * FROM variance WHERE as_of_date = %s {"AND is_anomaly" if anomalies_only else ""}
                              ORDER BY is_anomaly DESC, ABS(amount_usd - prior_amount_usd) DESC""", (date,))







# ─── Lineage: the day's data flow, and any record traced end to end (Delta, through the SQL warehouse) ─────
def _check_date(date):
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise HTTPException(400, "date must be YYYY-MM-DD")


def _safe_id(v):
    if not v or not all(c.isalnum() or c in "-_#:." for c in v):
        raise HTTPException(400, "bad identifier")
    return v



@router.get("/lineage/{date}/record/{record_key}")
def lineage_record(date: str, record_key: str):
    """Backward lineage of one filed record: 6G file -> filed record -> adjustments -> positions (how each field was derived)
    -> DQ-passed source record -> Bronze row and landing file; plus the checks it failed."""
    _check_date(date)
    key = _safe_id(record_key)
    m = _deps()
    rec = m.run_wh(f"SELECT * FROM filing_records WHERE as_of_date = '{date}' AND record_key = '{key}'")
    if not rec:
        raise HTTPException(404, "No filed record with this key on this date")
    table = rec[0]["table_code"]
    gold = m.run_pg("SELECT gold_table, xml_report_type FROM spec_tables WHERE table_code = %s", (table,))[0]
    fields = m.run_wh(f"SELECT * FROM {gold['gold_table']} WHERE as_of_date = '{date}' AND record_key = '{key}'")
    files = m.run_wh(f"""SELECT file_type, file_name, run_number, version, xsd_valid, release_status FROM submission_files
                          WHERE as_of_date = '{date}' AND file_type IN ('Primary', 'Reduced')
                            AND run_number = (SELECT MAX(run_number) FROM submission_files WHERE as_of_date = '{date}')""")
    positions = m.run_wh(f"""
      SELECT l.position_id, l.record_id, l.amount, f.part, f.booking_entity, e.relationship, e.internal_counterparty, f.source_system,
             f.source_product_code, f.standard_product_type, f.product_id, f.pid_rule_id, r.priority AS rule_priority, r.condition_sql AS rule_condition,
             r.rationale AS rule_rationale, f.customer_id, f.counterparty, c.approved_by AS customer_approved_by, f.gsib, f.collateral_id,
             f.collateral_class, f.collateral_basis, f.maturity_date, f.maturity_basis, f.maturity_bucket, f.effective_maturity_date,
             f.insured, f.insured_basis, f.lendable_value, f.lendable_basis, f.currency, f.enrichment_timestamp
      FROM record_lineage l
      LEFT JOIN fact_liquidity_position f ON f.as_of_date = l.as_of_date AND f.position_id = l.position_id
      LEFT JOIN entity_position e ON e.as_of_date = l.as_of_date AND e.position_id = l.position_id AND e.reporting_entity = l.reporting_entity
      LEFT JOIN rules_pid_derivation r ON r.rule_id = f.pid_rule_id
      LEFT JOIN ref_customer_master c ON c.customer_id = f.customer_id
      WHERE l.as_of_date = '{date}' AND l.record_key = '{key}' ORDER BY l.amount DESC LIMIT 200""")
    ids = sorted({p["record_id"] for p in positions if p.get("record_id")})
    sources = []
    if ids:
        in_list = ", ".join(f"'{_safe_id(i)}'" for i in ids)
        sources = m.run_wh(f"""
          SELECT DISTINCT ON (s.record_id) s.record_id, s.source_feed, s.source_system, s.source_product_code, s.instrument_type, s.customer_id, s.collateral_id,
                 s.currency, s.principal_amount, s.market_value, s.maturity_type, s.maturity_date, s.dq_status, s.dq_timestamp,
                 b.feed AS bronze_feed, b.landing_file, b.ingested_at
          FROM source_position s
          LEFT JOIN v_source_files b ON b.as_of_date = s.as_of_date AND b.record_id = s.record_id
          WHERE s.as_of_date = '{date}' AND s.record_id IN ({in_list}) ORDER BY s.record_id, b.ingested_at DESC""")
    adjustments = m.run_wh(f"SELECT * FROM adjustments WHERE as_of_date = '{date}' AND record_key = '{key}'")
    checks = m.run_wh(f"""SELECT d.rule_id, d.rule_source, d.failure_detail, v.rule_name, v.severity, v.status
                           FROM gold_validation_detail d
                           LEFT JOIN gold_validation v ON v.as_of_date = d.as_of_date AND v.rule_id = d.rule_id
                           WHERE d.as_of_date = '{date}' AND d.record_key = '{key}'""")
    return {"record": rec[0], "fields": fields[0] if fields else {}, "xml_report_type": gold["xml_report_type"], "files": files,
            "adjustments": adjustments, "positions": positions, "sources": sources, "checks": checks}


ENRICH = [  # (field, how it is derived) - the attribute-level enrichment of the calculation layer (notebook 03)
    ("standard_product_type", "bank product code -> standard product type (reference.v_source_product_map)"),
    ("counterparty", "customer id -> FR 2052a Counterparty (reference.v_customer_master)"),
    ("counterparty_category", "Counterparty -> category (reference.ref_counterparty)"),
    ("gsib", "customer master G-SIB parent (FSB list)"),
    ("affiliate_legal_entity_id", "customer master affiliate -> Internal / intercompany"),
    ("collateral_class", "collateral_basis"), ("is_hqla", "collateral class -> HQLA (reference.ref_collateral)"),
    ("maturity_date", "maturity_basis"), ("maturity_bucket", "maturity date -> Appendix IV-a bucket (reference.ref_maturity_bucket)"),
    ("effective_maturity_date", "option-adjusted / drawdown date"), ("weekend_flow", "maturity falls on a weekend"),
    ("insured", "insured_basis"), ("lendable_value", "lendable_basis"), ("risk_weight", "source risk weight % -> 6G decimal"),
    ("sub_product", "source sub product"), ("encumbrance_type", "source encumbrance"), ("business_line", "source business line"),
]


@router.get("/lineage/{date}/position/{position_id}")
def lineage_position(date: str, position_id: str):
    """One position, step by step from the CSV row to its element in the 6G XML: for each step the environment, the exact
    table / file, the notebook or pipeline, when it ran, and what was added or changed."""
    import re
    _check_date(date)
    pid_ = _safe_id(position_id)
    m, C = _deps(), _deps().CATALOG
    if "#" not in pid_:   # a source record id: list its positions to choose from
        parts = m.run_wh(f"""SELECT position_id, part, product_id, principal_amount, market_value, currency FROM fact_liquidity_position
                              WHERE as_of_date = '{date}' AND record_id = '{pid_}' ORDER BY part""")
        if len(parts) != 1:
            return {"choose": parts, "record_id": pid_}
        pid_ = parts[0]["position_id"]
    rid = pid_.split("#")[0]
    f = m.run_wh(f"SELECT * FROM fact_liquidity_position WHERE as_of_date = '{date}' AND position_id = '{pid_}'")
    if not f:
        raise HTTPException(404, "No such position on this date (it may have been quarantined or held out - see Collect)")
    f = f[0]
    src = (m.run_wh(f"SELECT * FROM source_position WHERE as_of_date = '{date}' AND record_id = '{rid}'") or [{}])[0]
    land = (m.run_wh(f"SELECT feed, landing_file, ingested_at FROM v_source_files WHERE as_of_date = '{date}' AND record_id = '{rid}' LIMIT 1") or [{}])[0]
    nrules = m.run_wh(f"SELECT COUNT(*) AS n FROM rules_dq")[0]["n"]
    warn = m.run_wh(f"SELECT rule_id FROM rule_failures WHERE as_of_date = '{date}' AND record_id = '{rid}'")
    rule = (m.run_wh(f"SELECT * FROM rules_pid_derivation WHERE rule_id = '{_safe_id(f['pid_rule_id'] or 'x')}'") or [{}])[0]
    cand = m.run_wh(f"""SELECT rule_id, priority, condition_sql, product_id FROM rules_pid_derivation
                         WHERE standard_product_type = '{_safe_id(f['standard_product_type'] or 'x')}' ORDER BY CAST(priority AS INT)""")
    scope = m.run_wh(f"""SELECT e.reporting_entity, e.relationship, e.internal, e.internal_counterparty, r.entity_name, r.scope_type
                          FROM entity_position e JOIN ref_reporting_entity r ON r.entity_id = e.reporting_entity
                          WHERE e.as_of_date = '{date}' AND e.position_id = '{pid_}' ORDER BY 1""")
    elim = m.run_wh(f"""SELECT reporting_entity, counterparty_legal_entity, amount_usd FROM intercompany_elimination
                         WHERE as_of_date = '{date}' AND position_id = '{pid_}'""")
    tables = {t["table_code"]: t for t in m.run_pg("SELECT table_code, table_name, gold_table, xml_report_type FROM spec_tables")}
    key_fields = [r["column_name"] for r in m.run_pg("""SELECT column_name FROM spec_table_fields WHERE table_code = %s
                                                       AND data_type <> 'numeric' ORDER BY seq""", (f["table_code"],))]
    run = (m.run_wh(f"SELECT MAX(run_number) AS r FROM submission_files WHERE as_of_date = '{date}'") or [{}])[0].get("r")
    files = m.run_wh(f"""SELECT file_type, file_name, file_path, xml_content, generated_timestamp, xsd_valid, release_status, version
                          FROM submission_files WHERE as_of_date = '{date}' AND run_number = {int(run or 0)} ORDER BY file_name DESC""")
    t = tables[f["table_code"]]
    filed = []
    for l in m.run_wh(f"""SELECT reporting_entity, record_key, amount, run_timestamp FROM record_lineage
                           WHERE as_of_date = '{date}' AND position_id = '{pid_}' ORDER BY reporting_entity"""):
        g = (m.run_wh(f"SELECT * FROM {t['gold_table']} WHERE as_of_date = '{date}' AND record_key = '{l['record_key']}'") or [{}])[0]
        checks = m.run_wh(f"""SELECT rule_id, failure_detail FROM gold_validation_detail
                               WHERE as_of_date = '{date}' AND record_key = '{l['record_key']}'""")
        xml, xfile = None, None
        for fl in files:
            if g.get("report_id") is None or not fl.get("xml_content"):
                continue
            mt = re.search(rf'<{t["xml_report_type"]} reportID="{g["report_id"]}"[^>]*>.*?</{t["xml_report_type"]}>', fl["xml_content"], re.S)
            if mt:
                xml, xfile = mt.group(0), fl
                break
        published = m.run_pg("SELECT COUNT(*) AS n FROM filing_records WHERE as_of_date = %s AND record_key = %s", (date, l["record_key"]))[0]["n"]
        filed.append({"reporting_entity": l["reporting_entity"], "record_key": l["record_key"], "contribution": l["amount"],
                      "aggregated_at": l["run_timestamp"], "report_key": {k: g.get(k) for k in key_fields},
                      "amounts": {k: v for k, v in g.items() if k not in key_fields and k not in ("as_of_date", "record_key", "report_id",
                                  "validation_status", "adjustment_ids", "record_count") and v is not None},
                      "record_count": g.get("record_count"), "report_id": g.get("report_id"), "adjustment_ids": g.get("adjustment_ids"),
                      "checks_failed": checks, "xml": xml, "xml_file": {k: xfile[k] for k in ("file_type", "file_name", "file_path", "generated_timestamp", "xsd_valid", "release_status", "version")} if xfile else None,
                      "published_to_lakebase": bool(published)})
    lcr = m.run_wh(f"""SELECT entity_id, rule_id, rule_name, flow_direction, hqla_level, amount_usd, rate, weighted_amount_usd FROM calculation_detail
                        WHERE as_of_date = '{date}' AND record_id = '{pid_}'""")   # LCR detail is keyed by position
    status = m.get_submission(date)
    return {
        "position_id": pid_, "record_id": rid, "product_id": f["product_id"], "table": t,
        "steps": [
            {"n": 1, "stage": "Source extract", "environment": "Unity Catalog Volume (landing zone)", "where": land.get("landing_file"),
             "by": f"source system {src.get('source_system') or f.get('source_system')}", "when": None,
             "detail": {k: src.get(k) for k in ("source_system", "booking_entity", "instrument_type", "source_product_code", "product_subtype", "flow_direction",
                        "customer_id", "collateral_id", "currency", "principal_amount", "market_value", "maturity_type", "maturity_date", "insurance_scheme",
                        "depositor_count") if src.get(k) not in (None, "")}},
            {"n": 2, "stage": "Bronze ingest", "environment": "Lakeflow Declarative Pipeline fr2052a-bronze-ingest (Auto Loader) -> Delta",
             "where": f"{C}.raw.{land.get('feed')}", "by": "pipelines/bronze_ingest.py", "when": land.get("ingested_at"),
             "detail": {"rows": "one row per CSV line, values as received, plus _source_file and _ingested_at"}},
            {"n": 3, "stage": "Data quality gate", "environment": "Delta (serverless notebook)", "where": f"{C}.conformed.source_position",
             "by": "notebooks/02_Data_Quality_Gate", "when": src.get("dq_timestamp"),
             "detail": {"rules evaluated": nrules, "result": src.get("dq_status") or "PASSED",
                        "warnings": ", ".join(w["rule_id"] for w in warn) or "none", "rules": "reference.rules_dq (SQL predicates)"}},
            {"n": 4, "stage": "Calculation layer and enrichment", "environment": "Delta Silver (serverless notebook)",
             "where": f"{C}.conformed.fact_liquidity_position", "by": "notebooks/03_PID_Derivation_and_Enrichment", "when": f.get("enrichment_timestamp"),
             "detail": {"part": f"{f.get('part')} - the source record split into its FR 2052a parts (e.g. insured / uninsured, operational / excess)",
                        "amount": f.get("principal_amount") if f.get("principal_amount") is not None else f.get("market_value"),
                        "booking_entity": f.get("booking_entity")},
             "enrichment": [{"field": k, "value": f.get(k), "how": f.get(b) if b.endswith("_basis") else b} for k, b in ENRICH if f.get(k) not in (None, "")]},
            {"n": 5, "stage": "PID derivation", "environment": "Delta Silver", "where": f"{C}.conformed.fact_liquidity_position.product_id",
             "by": "reference.rules_pid_derivation (ordered, first match wins)", "when": f.get("enrichment_timestamp"),
             "detail": {"standard product type": f.get("standard_product_type"), "rule": f.get("pid_rule_id"), "priority": rule.get("priority"),
                        "condition": rule.get("condition_sql"), "PID": f.get("product_id"), "rationale": rule.get("rationale"), "table": f.get("table_code")},
             "candidates": cand},
            {"n": 6, "stage": "Reporting-entity scope", "environment": "Delta Silver", "where": f"{C}.conformed.entity_position",
             "by": "notebooks/03 (legal-entity tree of each reporting entity)", "when": f.get("enrichment_timestamp"),
             "scope": scope, "eliminated": elim},
            {"n": 7, "stage": f"Aggregation into FR 2052a {t['table_code']} {t['table_name']}", "environment": "Delta Gold",
             "where": f"{C}.reg_2052a.{t['gold_table']}", "by": "notebooks/05_FR2052a_Report_Build (grouped on the 6G report key)", "when": filed[0]["aggregated_at"] if filed else None,
             "filed": filed},
            {"n": 8, "stage": "Validation", "environment": "Delta Gold", "where": f"{C}.reg_2052a.gold_validation(_detail)",
             "by": "notebooks/06 (6G XSD + business rules, Instructions appendix rules, Fed post-submission checks)", "when": files[0]["generated_timestamp"] if files else None,
             "detail": {e["reporting_entity"]: (", ".join(c["rule_id"] for c in e["checks_failed"]) or "no check failed on this record") for e in filed}},
            {"n": 9, "stage": "6G XML file", "environment": "Unity Catalog Volume reg_2052a.xml_filings",
             "where": (files[0]["file_path"].rsplit("/", 1)[0] if files else None), "by": "notebooks/06 (lxml, validated against 6GSchema.xsd)",
             "when": files[0]["generated_timestamp"] if files else None,
             "detail": {"run": run, "status": status.get("status"), "files": ", ".join(fl["file_name"] for fl in files)}},
            {"n": 10, "stage": "Published to the app", "environment": "Lakebase (Postgres) - read copy for the app; sign-off written back",
             "where": "Lakebase fr2052a: filing_records, submission_files, submission_review", "by": "notebooks/07_Lakebase_Sync", "when": None,
             "detail": {e["reporting_entity"]: ("published" if e["published_to_lakebase"] else "not published") for e in filed}},
        ],
        "also": {"lcr": lcr},
    }


@router.get("/lineage/{date}/source/{record_id}")
def lineage_source(date: str, record_id: str):
    """Forward lineage of one source record: the positions it became and every filed record (per reporting entity) it is in."""
    _check_date(date)
    rid = _safe_id(record_id)
    m = _deps()
    positions = m.run_wh(f"""SELECT position_id, part, product_id, pid_rule_id, booking_entity, principal_amount, market_value, currency
                              FROM fact_liquidity_position WHERE as_of_date = '{date}' AND record_id = '{rid}'""")
    filed = m.run_wh(f"""
      SELECT l.reporting_entity, l.table_code, l.record_key, l.position_id, l.amount, v.product_id, v.counterparty, v.maturity_bucket,
             v.reported_amount, v.record_count, e.relationship
      FROM record_lineage l
      JOIN filing_records v ON v.as_of_date = l.as_of_date AND v.record_key = l.record_key
      LEFT JOIN entity_position e ON e.as_of_date = l.as_of_date AND e.position_id = l.position_id AND e.reporting_entity = l.reporting_entity
      WHERE l.as_of_date = '{date}' AND l.record_id = '{rid}' ORDER BY l.reporting_entity, l.table_code""")
    held = m.run_wh(f"""SELECT 'quarantined' AS state, failed_rules AS reason FROM quarantine WHERE as_of_date = '{date}' AND record_id = '{rid}'
                         UNION ALL SELECT exception_type, reason FROM pid_exceptions WHERE as_of_date = '{date}' AND record_id = '{rid}'""")
    eliminated = m.run_wh(f"""SELECT reporting_entity, position_id, counterparty_legal_entity, amount_usd FROM intercompany_elimination
                               WHERE as_of_date = '{date}' AND position_id LIKE '{rid}#%'""")
    return {"record_id": rid, "positions": positions, "filed": filed, "held": held, "eliminated": eliminated}


# ─── Data quality: fix a quarantined record and put it back (applied by notebook 02 on the next run of the day) ─────
DQ_NOT_EDITABLE = {"record_id", "as_of_date", "load_timestamp", "source_feed"}





@router.post("/rerun-from-dq/{date}")
def rerun_from_dq(date: str, request: Request):
    """Re-run the day from the data quality check (no re-ingest): fixes and accepted enrichments are applied, then everything after."""
    _check_date(date)
    m = _deps()
    m._no_active_run(date)   # one run per date at a time
    r = m.get_ws().api_client.do("POST", "/api/2.2/jobs/run-now", body={"job_id": int(m.DAILY_JOB_ID), "job_parameters": {
        "as_of_date": date, "ingest": "false", "requested_by": _user(request)}})
    return {"run_id": str(r["run_id"])}


@router.post("/collect/{date}/resend/{feed}")
def collect_resend(date: str, feed: str, request: Request):
    """Ask the source to re-send a feed that arrived short, then re-run the day with it (re-ingest, notebook 00 lands the file)."""
    _check_date(date)
    m = _deps()
    mon = {r["feed"]: r["status"] for r in m.run_pg("SELECT feed, status FROM feed_monitor WHERE as_of_date = %s", (date,))}
    if feed not in mon or feed in ("comments", "collateral_links", "gl_balances", "customers"):
        raise HTTPException(404, f"No position feed {feed} on {date}")
    if mon[feed] == "PASS":
        raise HTTPException(409, f"Feed {feed} arrived complete on {date}")
    m._no_active_run(date)   # one run per date at a time
    r = m.get_ws().api_client.do("POST", "/api/2.2/jobs/run-now", body={"job_id": int(m.DAILY_JOB_ID), "job_parameters": {
        "as_of_date": date, "ingest": "true", "resend_feed": feed, "requested_by": _user(request)}})
    return {"run_id": str(r["run_id"])}


@router.get("/rerun-from-dq/{date}")
def rerun_from_dq_status(date: str):
    m = _deps()
    for r in m.get_ws().api_client.do("GET", "/api/2.2/jobs/runs/list", query={"job_id": m.DAILY_JOB_ID, "limit": 25}).get("runs", []):
        params = {p["name"]: p.get("value", p.get("default")) for p in r.get("job_parameters", [])}
        if params.get("as_of_date") == date:
            st = r["state"]
            return {"run_id": str(r["run_id"]), "state": st.get("life_cycle_state"), "result": st.get("result_state"), "url": r.get("run_page_url")}
    return {}


# ─── Data quality work queue: one failing record at a time - AI fix, manual fix, or exclude ─────
_DQ_SUGGEST = {}
# rule -> (field it is about, SQL listing the valid values) for the AI to pick from
DQ_CANDIDATES = {
    "DQ_001": ("source_system", "SELECT DISTINCT source_system, CONCAT('owns bank product code ', source_product_code) AS label FROM {C}.reference.v_source_product_map WHERE source_product_code = '{code}'"),
    "DQ_005": ("customer_id", "SELECT customer_id, customer_name AS label FROM {C}.reference.v_customer_master"),
    "DQ_012": ("customer_id", "SELECT customer_id, customer_name AS label FROM {C}.reference.v_customer_master"),
    "DQ_006": ("source_product_code", "SELECT source_product_code, CONCAT(standard_product_type, ' - ', description) AS label FROM {C}.reference.v_source_product_map WHERE source_system = '{system}'"),
    "DQ_007": ("collateral_id", "SELECT collateral_id, CONCAT(collateral_class, ' - ', description) AS label FROM {C}.reference.ref_security_master"),
    "DQ_009": ("booking_entity", "SELECT legal_entity_id, legal_name AS label FROM {C}.reference.ref_legal_entity"),
    "DQ_011": ("currency", "SELECT currency_code, CAST(rate_to_usd AS STRING) AS label FROM {C}.reference.ref_fx_rates"),
}


def _dq_status(m, date):
    rows = m.run_pg("""SELECT DISTINCT ON (record_id) record_id, field, new_value, status, preparer, created_at, reason FROM dq_fixes
                       WHERE as_of_date = %s AND status <> 'WITHDRAWN' ORDER BY record_id, created_at DESC""", (date,))
    return {r["record_id"]: r for r in rows}


# The Delta layers the app reads are served from their Lakebase synced tables (app_serving, refreshed by notebook 07 after each run).
def _wh_rows(m, name, date, sql):
    return m.run_wh(sql)


@router.get("/dq/{date}/queue")
def dq_queue(date: str):
    """Every record that failed a data quality rule, one row per record, with its rules and where it stands."""
    _check_date(date)
    m = _deps()
    rows = _wh_rows(m, "dq_queue", date, f"""
      WITH f AS (SELECT record_id, source_feed, array_agg(DISTINCT rule_id) AS rules, MAX(CAST(quarantined AS INT)) AS q, MAX(severity) AS sev
                 FROM rule_failures WHERE as_of_date = '{date}' GROUP BY 1, 2
                 UNION ALL   -- every quarantined record, also those of a run without rule-level rows (rules from the quarantine reason)
                 SELECT q.record_id, q.source_feed, ARRAY(SELECT (regexp_matches(q.failed_rules, 'DQ_[0-9]+', 'g'))[1]),
                        1, 'ERROR' FROM quarantine q
                 WHERE q.as_of_date = '{date}' AND NOT EXISTS (SELECT 1 FROM rule_failures r WHERE r.as_of_date = q.as_of_date AND r.record_id = q.record_id))
      SELECT f.record_id, f.source_feed, array_to_string(ARRAY(SELECT unnest(f.rules) ORDER BY 1), ', ') AS rules, f.q AS quarantined, f.sev AS severity,
             (q.record_json::json->>'source_system') AS source_system, q.source_product_code,
             (q.record_json::json->>'customer_id') AS customer_id, (q.record_json::json->>'principal_amount') AS amount,
             (q.record_json::json->>'currency') AS currency
      FROM f LEFT JOIN quarantine q ON q.as_of_date = '{date}' AND q.record_id = f.record_id
      ORDER BY f.q DESC, f.record_id""")
    st = _dq_status(m, date)
    names = {r["rule_id"]: r["rule_name"] for r in m.run_pg("SELECT rule_id, rule_name FROM rules_dq")}
    for r in rows:
        d = st.get(r["record_id"])
        r["rule_names"] = "; ".join(f"{x} {names.get(x, '')}" for x in r["rules"].split(", "))
        if r["quarantined"] in ("0", 0):
            r["state"] = "warning"        # in Silver already; reported only
        elif not d:
            r["state"] = "open"
        elif d["field"] == "_exclude":
            r["state"] = "excluded"
        elif d["field"] == "_map_code":
            r["state"] = "mapped" if d["status"] == "PENDING" else "fixed"
        else:
            r["state"] = "fixed" if d["status"] == "APPLIED" else "fix pending re-run"
        r["decision"] = d
    return rows


# The AI-suggested fix a step page shows is the one the AI agents made in the pipeline (notebook 15), read from Lakebase: one AI answer
# per item, no AI call on the click. dq_suggest / validate_suggest below are what the agents call to make it.
NOT_YET = "The AI agents have not proposed a fix for this item yet - they run at the end of the pipeline for the day."


def _proposal(date, kind, ref):
    r = _deps().run_pg("""SELECT p.action, p.confidence, p.summary, p.fields, p.rule_check FROM breaks b
                          JOIN LATERAL (SELECT * FROM proposals x WHERE x.break_id = b.break_id ORDER BY x.version DESC LIMIT 1) p ON TRUE
                          WHERE b.as_of_date = %s AND b.source_kind = %s AND b.source_ref = %s""", (date, kind, ref[:400]))
    if not r:
        return None
    r = r[0]
    for k in ("action", "fields", "rule_check"):
        if isinstance(r[k], str):
            r[k] = json.loads(r[k])
    return r


@router.get("/dq/{date}/suggest/{record_id}")
def dq_suggestion(date: str, record_id: str):
    _check_date(date)
    p = _proposal(date, "dq", _safe_id(record_id))
    act = (p or {}).get("action") or {}
    if act.get("kind") != "dq":
        return {"rationale": NOT_YET if not p else "Decided on this page.", "pending": not p}
    if act.get("ai"):
        return {**act["ai"], "confidence": act["ai"].get("confidence", p["confidence"])}
    edits = act.get("edits") or {}
    return {"action": {"accept_ai": "fix_field", "map_code": "map_code", "exclude": "exclude"}.get(act.get("action")),
            "field": next(iter(edits), None), "new_value": act.get("new_value") or next(iter(edits.values()), None),
            "rationale": p["summary"], "confidence": float(p["confidence"]) if p["confidence"] is not None else None}


@router.get("/validate/{date}/suggest")
def validate_suggestion(date: str, rule_id: str, item_key: str):
    _check_date(date)
    p = _proposal(date, "validate", f"{rule_id}|{item_key}")
    act = (p or {}).get("action") or {}
    if act.get("kind") != "validate":
        return {"explanation": NOT_YET if not p else "Decided on this page.", "pending": not p}
    if act.get("ai"):
        return {**act["ai"], "confidence": act["ai"].get("confidence", p["confidence"])}
    f0 = (p.get("fields") or [{}])[0]
    return {"action": "correct" if act.get("action") == "accept_ai" else "explain", "position_id": act.get("position_id"), "field": act.get("field"),
            "new_value": act.get("new_value"), "old_value": f0.get("now"), "explanation": act.get("note") or p["summary"],
            "confidence": float(p["confidence"]) if p["confidence"] is not None else None}


def dq_suggest(date: str, record_id: str):
    """AI-suggested fix for one failing record (Databricks ai_query on the SQL warehouse), from the rule, the record and the valid values."""
    _check_date(date)
    rid = _safe_id(record_id)
    if (date, rid) in _DQ_SUGGEST:
        return _DQ_SUGGEST[(date, rid)]
    m, C = _deps(), _deps().CATALOG
    rec = collect_record(date, rid)
    rules = [r["rule_id"] for r in rec["failed_rules"]] or (["DQ_010"] if (rec.get("quarantine_reason") or "").startswith("DQ_010") else [])
    if rules == ["DQ_010"]:
        out = {"action": "exclude", "field": None, "new_value": None, "confidence": 0.95,
               "rationale": "A duplicate copy of a record already loaded from the same file; the first copy is in Silver, so this copy stays out."}
        _DQ_SUGGEST[(date, rid)] = out
        return out
    vals = rec["values"]
    cands, field = [], None
    for r in rules:
        if r in DQ_CANDIDATES:
            field, sql = DQ_CANDIDATES[r]
            cands = m.run_sql(sql.format(C=C, system=_safe_id(vals.get("source_system") or "x"), code=_safe_id(vals.get("source_product_code") or "x")))[:200]
            break
    product_types = []
    if "DQ_006" in rules:
        product_types = m.run_sql(f"""SELECT standard_product_type, description FROM {C}.reference.ref_standard_product_type
                                      WHERE source_system = '{_safe_id(vals.get("source_system") or "x")}'""")
    prompt = ("You fix FR 2052a source records that failed a data quality rule. Use ONLY the record and the valid values given. "
              "Failed rules: " + json.dumps([{k: r[k] for k in ("rule_id", "rule_name", "rule_description", "fail_predicate")} for r in rec["failed_rules"]]) +
              ". Record: " + json.dumps({k: v for k, v in vals.items() if v not in (None, "")}, default=str) +
              (f". Valid values for {field}: " + json.dumps([list(c.values()) for c in cands]) if cands else "") +
              (". This source system's standard product types (for mapping a NEW product code instead of changing it): " + json.dumps([list(p.values()) for p in product_types]) if product_types else "") +
              ". Choose ONE action: fix_field (set one field to a valid value - only when the record clearly points to it, e.g. a placeholder id, "
              "or a product code that is an obvious typo of an existing code: same letters, one character off), map_code (an unmapped product code "
              "that is a NEW product of the bank - a code that is not a typo and has its own description: never rename it to an existing code, map "
              "it to the standard product type above that fits its description), or exclude "
              "(the record cannot be fixed from the data; it stays out of the report). Answer ONLY JSON: {\"action\": \"fix_field\" | \"map_code\" | \"exclude\", "
              "\"field\": field or null, \"new_value\": value (for map_code: the standard product type) or null, \"confidence\": 0.0-1.0, "
              "\"rationale\": \"one sentence for the analyst\"}")
    try:
        out = _ai_json(m, prompt, 300)
    except Exception as e:
        out = {"action": None, "rationale": f"No AI suggestion available ({str(e)[:120]}) - fix manually or exclude."}
    out["rules"] = rules
    _DQ_SUGGEST[(date, rid)] = out
    return out


@router.post("/dq/{date}/resolve")
def dq_resolve(date: str, data: dict, request: Request):
    """Resolve one failing record: accept the AI fix, fix it manually (field edits), or exclude it. Logged in dq_fixes."""
    _check_date(date)
    m = _deps()
    rid, action = _safe_id(data.get("record_id")), data.get("action")
    reason = (data.get("reason") or "").strip()
    user = _user(request)
    q = m.run_wh(f"SELECT source_feed, record_json FROM quarantine WHERE as_of_date = '{date}' AND record_id = '{rid}'")
    if not q:
        raise HTTPException(404, "Only quarantined records are resolved here")
    feed, values = q[0]["source_feed"], json.loads(q[0]["record_json"])
    rows = []
    if action == "exclude":
        rows.append(("_exclude", None, "true", reason or "Excluded from the report"))
    elif action == "map_code":
        std = data.get("new_value")
        ok = {r["standard_product_type"] for r in m.run_wh(f"""SELECT standard_product_type FROM ref_standard_product_type
                                                              WHERE source_system = '{_safe_id(values.get("source_system") or "x")}'""")}
        if std not in ok:
            raise HTTPException(400, "Choose a standard product type of this source system")
        with m.get_pg() as conn:
            with conn.cursor() as c:
                c.execute("""INSERT INTO source_product_map_approvals VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                             ON CONFLICT (source_product_code) DO UPDATE SET standard_product_type = EXCLUDED.standard_product_type,
                             approved_on = EXCLUDED.approved_on, approved_by = EXCLUDED.approved_by, decided_at = NOW()""",
                          (values.get("source_product_code"), values.get("source_system"), std, values.get("instrument_type"), date, user, f"dq:{rid}"))
            conn.commit()
        rows.append(("_map_code", values.get("source_product_code"), std, reason or f"New product code mapped to {std}"))
    elif action in ("accept_ai", "manual"):
        edits = data.get("edits") or {}
        if not edits:
            raise HTTPException(400, "No field changed")
        for f, v in edits.items():
            if f in DQ_NOT_EDITABLE or (f not in values and f not in {c[0] for c in DQ_CANDIDATES.values()}):   # a null field is absent from the JSON
                raise HTTPException(400, f"{f} cannot be fixed here")
            rows.append((f, None if values.get(f) is None else str(values.get(f)), None if v in (None, "") else str(v),
                         reason or ("AI-suggested fix accepted" if action == "accept_ai" else "Manual fix")))
    else:
        raise HTTPException(400, "action must be accept_ai, manual, map_code or exclude")
    with m.get_pg() as conn:
        with conn.cursor() as c:
            c.execute("UPDATE dq_fixes SET status = 'WITHDRAWN' WHERE as_of_date = %s AND record_id = %s AND status = 'PENDING'", (date, rid))
            for f, old, new, why in rows:
                c.execute("INSERT INTO dq_fixes VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)",
                          (str(uuid.uuid4())[:8], date, rid, feed, f, old, new, why[:1000], user, "DECIDED" if f == "_exclude" else "PENDING"))
        conn.commit()
    return {"record_id": rid, "action": action}


# ─── PID enrichment: Silver organised like the report, with the enrichment issues per table ─────
ISSUES_SQL = """
  CASE WHEN p.product_id IS NULL THEN 'no product (PID)' END,
  CASE WHEN p.counterparty IS NULL AND p.product_id IN (SELECT product_id FROM spec_counterparty_requirements) THEN 'counterparty missing' END,
  CASE WHEN p.counterparty IS NOT NULL AND p.product_id IN (SELECT product_id FROM spec_counterparty_requirements)
        AND (p.product_id, p.counterparty) NOT IN (SELECT product_id, counterparty FROM spec_counterparty_requirements WHERE applicability = 'Applicable')
       THEN 'counterparty not allowed for this product' END,
  CASE WHEN p.currency IS NULL OR p.currency NOT IN (SELECT currency_code FROM ref_fx_rates) THEN 'unknown currency' END,
  CASE WHEN p.collateral_class IS NULL AND p.product_id IN (SELECT product_id FROM spec_collateral_class_requirements WHERE requirement = 'Required')
       THEN 'collateral class missing' END,
  CASE WHEN p.maturity_bucket IS NULL AND p.table_code ~ '^[IO]' THEN 'maturity bucket missing' END"""


@router.get("/enrich/{date}")
def enrich_summary(date: str):
    """Per FR 2052a table: Silver positions, how many carry an enrichment issue, and the positions held out (no PID / customer pending)."""
    _check_date(date)
    m = _deps()
    tbl = m.run_wh(f"""
      WITH p AS (SELECT p.table_code, array_remove(ARRAY[{ISSUES_SQL}], NULL) AS issues FROM fact_liquidity_position p WHERE p.as_of_date = '{date}')
      SELECT p.table_code, COUNT(*) AS positions, COUNT(*) FILTER (WHERE COALESCE(cardinality(p.issues), 0) > 0) AS with_issues,
             COALESCE((SELECT string_agg(DISTINCT x, ', ') FROM p p2 CROSS JOIN LATERAL unnest(p2.issues) x WHERE p2.table_code = p.table_code), '') AS issue_types
      FROM p GROUP BY p.table_code""")
    held = m.run_pg("""SELECT REGEXP_REPLACE(provisional_product_id, '\\.[0-9]+$', '') AS table_code, exception_type, COUNT(*) AS n
                       FROM pid_exceptions WHERE as_of_date = %s GROUP BY 1, 2""", (date,))
    rules = m.run_pg("SELECT COUNT(*) AS n FROM rules_pid_derivation")[0]["n"]
    return {"tables": tbl, "held_out": held, "pid_rules": rules}



@router.get("/enrich/{date}/table/{code}/pids")
def enrich_pids(date: str, code: str):
    """One FR 2052a table summarised by product (PID): positions, USD amount and positions with an issue."""
    _check_date(date)
    m = _deps()
    return m.run_wh(f"""
      SELECT p.product_id, MIN(r.product_name) AS product_name, COUNT(*) AS positions,
             round(CAST(SUM(COALESCE(p.principal_amount, p.market_value, 0) * COALESCE(fx.rate_to_usd, 1)) AS NUMERIC), 2) AS usd_mm,
             COUNT(*) FILTER (WHERE COALESCE(cardinality(array_remove(ARRAY[{ISSUES_SQL}], NULL)), 0) > 0) AS with_issues, COUNT(DISTINCT p.pid_rule_id) AS rules
      FROM fact_liquidity_position p
      LEFT JOIN ref_fx_rates fx ON fx.currency_code = p.currency
      LEFT JOIN ref_product r ON r.product_id = p.product_id
      WHERE p.as_of_date = '{date}' AND p.table_code = '{_safe_id(code)}' GROUP BY p.product_id ORDER BY p.product_id""")


# How each FR 2052a field of a position is derived (notebook 03) and the source column it starts from. A field with a *_basis column
# carries its own per-position explanation (e.g. the holiday roll of a maturity, the FDIC split of a deposit).
DERIVED = {
    "standard_product_type": ("source_product_code", "bank product code -> standard product type (product code map)"),
    "counterparty": ("customer_id", "customer -> FR 2052a Counterparty (customer master)"),
    "gsib": ("customer_id", "customer -> G-SIB parent on the FSB list (customer master)"),
    "collateral_class": ("collateral_id", "collateral_basis"),
    "collateral_value": ("collateral_id", "collateral market value from the collateral links"),
    "maturity_bucket": ("contract_maturity_date", "maturity_basis"),
    "maturity_optionality": ("contract_maturity_date", "option terms -> earliest (outflows) / latest (inflows) date"),
    "effective_maturity_bucket": ("contract_maturity_date", "option-adjusted / drawdown date -> Appendix IV-a bucket"),
    "forward_start_bucket": ("forward_start_date", "forward start date -> Appendix IV-a bucket"),
    "insured": ("principal_amount", "insured_basis"),
    "lendable_value": ("market_value", "lendable_basis"),
    "accounting_designation": ("source_product_code", "I.A.1 / I.A.2 carry the source designation; other I.A products Not Applicable"),
    "risk_weight": ("risk_weight", "source risk weight % -> 6G decimal"),
}
SCOPE_FIELDS = {"reporting_entity", "product_id", "converted", "converted_2", "internal", "internal_counterparty"}   # set per reporting entity, after this step


def _table_fields(m, table_code, cols):
    out = [{"column": "standard_product_type", "label": "Standard Product Type", "field_class": "Calculated"}]
    for f in m.run_pg("SELECT field_name, column_name, field_class FROM spec_table_fields WHERE table_code = %s ORDER BY seq", (table_code,)):
        col = SILVER_SRC.get(f["column_name"], f["column_name"])
        if f["column_name"] in SCOPE_FIELDS or col not in cols or any(e["column"] == col for e in out):
            continue
        out.append({"column": col, "label": f["field_name"], "field_class": f["field_class"]})
    for f in out:
        src, how = DERIVED.get(f["column"], (f["column"], "as sent by the source system"))
        f.update(source=src, how=how if not how.endswith("_basis") else None, basis=how if how.endswith("_basis") else None)
    return out


@router.get("/enrich/{date}/positions")
def enrich_positions(date: str, code: str, pid: str = None, page: int = 0, size: int = 50, issues: bool = False):
    """Positions of a table / PID, one page at a time (server-side paging, for any volume): the source values, every FR 2052a field of
    the table as the 6G spec lists it, how each was derived, and the PID rule that fired."""
    _check_date(date)
    m = _deps()
    size = max(10, min(size, 200))
    where = f"p.as_of_date = '{date}' AND p.table_code = '{_safe_id(code)}'" + (f" AND p.product_id = '{_safe_id(pid)}'" if pid else "")
    base = f"""SELECT p.*, COALESCE(p.principal_amount, p.market_value) AS amount,
                      array_to_string(array_remove(ARRAY[{ISSUES_SQL}], NULL), '; ') AS issues
               FROM fact_liquidity_position p WHERE {where}"""
    flt = "WHERE issues <> ''" if issues else ""
    total = m.run_wh(f"SELECT COUNT(*) AS n FROM ({base}) {flt}")[0]["n"]
    rows = m.run_wh(f"SELECT * FROM ({base}) {flt} ORDER BY issues DESC, position_id LIMIT {size} OFFSET {max(0, page) * size}")
    cols = set(rows[0].keys()) if rows else set()
    rules = {r["rule_id"]: r for r in m.run_pg("SELECT rule_id, condition_sql, rationale FROM rules_pid_derivation WHERE rule_id = ANY(%s)",
                                               (list({r["pid_rule_id"] for r in rows if r.get("pid_rule_id")}),))} if rows else {}
    for r in rows:
        r.pop("as_of_date", None)
        rule = rules.get(r.get("pid_rule_id")) or {}
        r["pid_rule_condition"], r["pid_rule_rationale"] = rule.get("condition_sql"), rule.get("rationale")
    return {"total": int(total), "page": page, "size": size, "rows": rows, "fields": _table_fields(m, _safe_id(code), cols) if rows else []}


@router.get("/enrich/{date}/queue")
def enrich_queue(date: str):
    """Everything in PID enrichment that needs a person: new customers, new product codes, positions no rule classifies,
    positions with an enrichment issue - each with what it affects and the AI suggestion."""
    _check_date(date)
    m = _deps()
    sugg = ai_queue(date)
    held = m.run_pg("SELECT * FROM pid_exceptions WHERE as_of_date = %s", (date,))
    items = []
    for s_ in sugg:
        t, g = s_["suggestion_type"], s_["suggestion"] if isinstance(s_["suggestion"], dict) else {}
        if t == "CUSTOMER_CLASSIFICATION":
            aff = [h for h in held if h.get("customer_id") == s_["subject_key"]]
            items.append({"id": s_["suggestion_id"], "kind": "New customer", "title": s_["subject"], "key": s_["subject_key"], "status": s_["status"],
                          "problem": f"Customer {s_['subject_key']} is not in the customer master yet, so its positions cannot get a counterparty and are held out of the report.",
                          "affects": f"{len(aff)} position(s), USD {sum(float(h.get('amount_usd') or 0) for h in aff):,.1f} mm held out",
                          "suggestion": {"counterparty": g.get("counterparty"), "gsib_parent": g.get("gsib_parent")},
                          "editable": ["counterparty", "gsib_parent"], "rationale": s_.get("rationale"), "confidence": s_.get("confidence"),
                          "context": g.get("description"), "decided_by": s_.get("decided_by")})
        elif t == "PRODUCT_MAPPING":
            items.append({"id": s_["suggestion_id"], "kind": "New product code", "title": s_["subject"], "key": s_["subject_key"], "status": s_["status"],
                          "problem": f"Bank product code {s_['subject_key']} is not in the product catalogue, so its records cannot be classified.",
                          "affects": f"{g.get('records', '?')} record(s)", "suggestion": {"standard_product_type": g.get("standard_product_type")},
                          "editable": ["standard_product_type"], "rationale": s_.get("rationale"), "confidence": s_.get("confidence"),
                          "context": g.get("description"), "decided_by": s_.get("decided_by")})
        elif t == "PID_EXCEPTION":
            items.append({"id": s_["suggestion_id"], "kind": "No PID rule matched", "title": s_["subject"], "key": s_["subject_key"], "status": s_["status"],
                          "problem": "No PID derivation rule matched this position, so it is held out of the report.",
                          "affects": "1 position", "suggestion": {"product_id": g.get("product_id"), "missing_attribute": g.get("missing_attribute")},
                          "editable": ["product_id"], "rationale": g.get("fix") or s_.get("rationale"), "confidence": s_.get("confidence"),
                          "decided_by": s_.get("decided_by")})
    issues = _wh_rows(m, "enrich_issues", date, f"""SELECT * FROM (SELECT p.position_id, p.table_code, p.product_id, array_to_string(array_remove(ARRAY[{ISSUES_SQL}], NULL), '; ') AS issues
                           FROM fact_liquidity_position p WHERE p.as_of_date = '{date}') WHERE issues <> '' LIMIT 500""")
    for i in issues:
        items.append({"id": i["position_id"], "kind": "Enrichment issue", "title": f"{i['position_id']} ({i['table_code']} {i['product_id']})", "key": i["position_id"],
                      "status": "PROPOSED", "problem": i["issues"], "affects": "1 position", "suggestion": None, "editable": [], "position_id": i["position_id"]})
    order = {"PROPOSED": 0}
    items.sort(key=lambda x: (order.get(x["status"], 1), x["kind"]))
    return items


# ─── Validation rules: correct the most granular data (Silver positions), then re-run the validation ─────
SILVER_SRC = {"maturity_amount": "principal_amount", "maturity_amount_currency_1": "principal_amount", "maturity_amount_currency_2": "principal_amount_2",
              "forward_start_amount_currency_1": "forward_start_amount", "forward_start_amount_currency_2": "forward_start_amount_2", "currency_1": "currency"}
NOT_EDITABLE = {"reporting_entity", "internal", "internal_counterparty", "converted", "converted_2"}   # set by the entity scope / conversion
REVALIDATE_JOB_ID = os.environ.get("REVALIDATE_JOB_ID", "")


def _editable(m, table_code, fact_cols):
    out = []
    for f in m.run_pg("SELECT field_name, column_name, field_class FROM spec_table_fields WHERE table_code = %s ORDER BY seq", (table_code,)):
        col = SILVER_SRC.get(f["column_name"], f["column_name"])
        if f["column_name"] in NOT_EDITABLE or col not in fact_cols or any(e["column"] == col for e in out):
            continue
        out.append({"column": col, "label": f["field_name"], "field_class": f["field_class"]})
    if "maturity_date" in fact_cols:
        out.insert(next((i for i, e in enumerate(out) if e["column"] == "maturity_bucket"), len(out)),
                   {"column": "maturity_date", "label": "Maturity Date (sets the bucket)", "field_class": "Source"})
    return out


@router.get("/correct/{date}")
def correct_target(date: str, record_key: str = None, position_id: str = None):
    """The positions behind a failing record (or one position), with the reporting fields that can be corrected."""
    _check_date(date)
    m = _deps()
    if record_key:
        pos = m.run_wh(f"""SELECT f.* FROM record_lineage l JOIN fact_liquidity_position f
                            ON f.as_of_date = l.as_of_date AND f.position_id = l.position_id
                            WHERE l.as_of_date = '{date}' AND l.record_key = '{_safe_id(record_key)}' ORDER BY f.position_id LIMIT 200""")
        rec = m.run_pg("SELECT * FROM filing_records WHERE as_of_date = %s AND record_key = %s LIMIT 1", (date, record_key))
        if not pos:   # some appendix rules (SPEC-V-04 / -21: collateral not linked) name the source record, not the reported record
            pos = m.run_wh(f"""SELECT * FROM fact_liquidity_position WHERE as_of_date = '{date}' AND record_id = '{_safe_id(record_key)}'
                                ORDER BY position_id LIMIT 200""")
    else:
        pos = m.run_wh(f"SELECT * FROM fact_liquidity_position WHERE as_of_date = '{date}' AND position_id = '{_safe_id(position_id)}'")
        rec = []
    if not pos:
        raise HTTPException(404, "No positions found")
    table = pos[0]["table_code"]
    fields = _editable(m, table, set(pos[0].keys()))
    ids = tuple(p["position_id"] for p in pos)
    corr = m.run_pg("SELECT * FROM position_corrections WHERE as_of_date = %s AND position_id = ANY(%s) ORDER BY created_at DESC", (date, list(ids)))
    keep = {"position_id", "record_id", "source_system", "source_product_code", "booking_entity"} | {f["column"] for f in fields}
    return {"record": rec[0] if rec else None, "table_code": table, "fields": fields,
            "positions": [{k: v for k, v in p.items() if k in keep} for p in pos], "corrections": corr}


@router.post("/corrections/{date}")
def post_correction(date: str, data: dict, request: Request):
    """Save one field correction of one position (applied by the next re-validation)."""
    _check_date(date)
    m = _deps()
    pid, field, new = _safe_id(data.get("position_id")), data.get("field"), data.get("new_value")
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "a correction needs a reason")
    cur = m.run_wh(f"SELECT * FROM fact_liquidity_position WHERE as_of_date = '{date}' AND position_id = '{pid}'")
    if not cur:
        raise HTTPException(404, "No such position")
    allowed = {f["column"] for f in _editable(m, cur[0]["table_code"], set(cur[0].keys()))}
    if field not in allowed:
        raise HTTPException(400, f"{field} cannot be corrected here")
    cid = str(uuid.uuid4())[:8]
    with m.get_pg() as conn:
        with conn.cursor() as c:
            c.execute("""INSERT INTO position_corrections VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), 'PENDING', NULL)""",
                      (cid, date, pid, data.get("record_key"), cur[0]["table_code"], field, None if cur[0].get(field) is None else str(cur[0][field]),
                       None if new in (None, "") else str(new), reason[:1000], _user(request)))
        conn.commit()
    return {"correction_id": cid, "status": "PENDING"}





@router.post("/revalidate/{date}")
def revalidate(date: str, request: Request):
    """Apply the corrections and rebuild + re-check the day (fr2052a-revalidate: 14 -> 04 -> 05 -> 06 -> 09 -> 07)."""
    _check_date(date)
    if not REVALIDATE_JOB_ID:
        raise HTTPException(500, "REVALIDATE_JOB_ID is not configured")
    _deps()._no_active_run(date)   # one run per date at a time
    r = _deps().get_ws().api_client.do("POST", "/api/2.2/jobs/run-now", body={
        "job_id": int(REVALIDATE_JOB_ID), "job_parameters": {"as_of_date": date, "requested_by": _user(request)}})
    return {"run_id": str(r["run_id"])}


@router.get("/revalidate/{date}")
def revalidate_status(date: str):
    if not REVALIDATE_JOB_ID:
        return {}
    runs = _deps().get_ws().api_client.do("GET", "/api/2.2/jobs/runs/list", query={"job_id": REVALIDATE_JOB_ID, "limit": 25}).get("runs", [])
    for r in runs:
        params = {p["name"]: p.get("value", p.get("default")) for p in r.get("job_parameters", [])}
        if params.get("as_of_date") == date:
            st = r["state"]
            return {"run_id": str(r["run_id"]), "state": st.get("life_cycle_state"), "result": st.get("result_state"),
                    "started": r.get("start_time"), "ended": r.get("end_time"), "url": r.get("run_page_url")}
    return {}


GENERATE_JOB_ID = os.environ.get("GENERATE_JOB_ID", "")


@router.post("/generate/{date}")
def generate(date: str, request: Request):
    """Step 5: generate the 6G files for release (fr2052a-generate: 00 app decisions -> 14 corrections -> 04 -> 05 -> 06 XML -> 07),
    once steps 1-4 have nothing open and nothing waiting for a re-run."""
    _check_date(date)
    if not GENERATE_JOB_ID:
        raise HTTPException(500, "GENERATE_JOB_ID is not configured")
    import agents
    r = agents.review_state(date)
    left = [f"{s['title']}: {s['open_label'] if s['open'] else s.get('waiting_label')}" for s in r["steps"][:4] if s["open"] or s.get("waiting")]
    if left:
        raise HTTPException(409, "Finish steps 1-4 first - " + "; ".join(left))
    _deps()._no_active_run(date)
    run = _deps().get_ws().api_client.do("POST", "/api/2.2/jobs/run-now", body={
        "job_id": int(GENERATE_JOB_ID), "job_parameters": {"as_of_date": date, "requested_by": _user(request), "released_by": _user(request)}})
    return {"run_id": str(run["run_id"])}


def generate_status(date: str):
    if not GENERATE_JOB_ID:
        return {}
    runs = _deps().get_ws().api_client.do("GET", "/api/2.2/jobs/runs/list", query={"job_id": GENERATE_JOB_ID, "limit": 25}).get("runs", [])
    for r in runs:
        params = {p["name"]: p.get("value", p.get("default")) for p in r.get("job_parameters", [])}
        if params.get("as_of_date") == date:
            st = r["state"]
            return {"run_id": str(r["run_id"]), "state": st.get("life_cycle_state"), "result": st.get("result_state"),
                    "started": r.get("start_time"), "ended": r.get("end_time"), "url": r.get("run_page_url"), "by": params.get("released_by")}
    return {}


@router.get("/generate/{date}")
def generate_status_api(date: str):
    _check_date(date)
    return generate_status(date)


# ─── Validate: a work queue of rule exceptions - AI fix (a position correction), manual fix, or explain a warning ─────
_VAL_SUGGEST = {}
_POS_RE = __import__("re").compile(r"\b[A-Z]{3}-\d{4}-\d{2}-\d{2}-[A-Z0-9]+#[A-Z0-9]+\b")


@router.get("/validate/{date}/queue")
def validate_queue(date: str):
    """Every exception of the day's checks: one row per failing record of a FAIL / WARNING rule, with its state."""
    _check_date(date)
    m = _deps()
    rules = {r["rule_id"]: r for r in m.run_pg("""SELECT rule_id, rule_name, rule_source, severity, status, table_code, records_failed, failure_details
                                                 FROM gold_validation WHERE as_of_date = %s AND status IN ('FAIL', 'WARNING')""", (date,))}
    det = m.run_pg("""SELECT rule_id, table_code, product_id, record_key, failure_detail FROM gold_validation_detail
                      WHERE as_of_date = %s AND rule_id = ANY(%s) ORDER BY rule_id LIMIT 5000""", (date, list(rules)))
    dec = {(d["rule_id"], d["item_key"]): d for d in m.run_pg("""SELECT DISTINCT ON (rule_id, item_key) * FROM validation_decisions
                                                                  WHERE as_of_date = %s AND status <> 'WITHDRAWN' ORDER BY rule_id, item_key, decided_at DESC""", (date,))}
    corr = {c["position_id"]: c for c in m.run_pg("""SELECT DISTINCT ON (position_id) position_id, record_key, status FROM position_corrections
                                                      WHERE as_of_date = %s AND status <> 'WITHDRAWN' ORDER BY position_id, created_at DESC""", (date,))}
    corr_keys = {c["record_key"]: c for c in corr.values() if c.get("record_key")}
    seen, items = set(), []
    for d in det or []:
        r = rules[d["rule_id"]]
        pos = (_POS_RE.search(d["failure_detail"] or "") or [None])[0] if not d["record_key"] else None
        key = d["record_key"] or pos or f"{d['table_code']}|{d['product_id']}|{(d['failure_detail'] or '')[:80]}"
        if (d["rule_id"], key) in seen:
            continue
        seen.add((d["rule_id"], key))
        c = corr.get(pos) if pos else corr_keys.get(d["record_key"])
        dd = dec.get((d["rule_id"], key))
        state = ("explained" if dd and dd["action"] == "explain" else "corrected" if c and c["status"] == "APPLIED" and not (dd and dd["action"] == "reopen")
                 else "corrected - re-run" if c else "open")
        items.append({"rule_id": d["rule_id"], "rule_name": r["rule_name"], "rule_source": r["rule_source"], "severity": r["severity"], "status": r["status"],
                      "table_code": d["table_code"], "product_id": d["product_id"], "record_key": d["record_key"], "position_id": pos, "item_key": key,
                      "detail": d["failure_detail"], "state": state, "decision": dd})
    for rid, r in rules.items():   # rules that failed without record-level detail
        if not any(i["rule_id"] == rid for i in items):
            dd = dec.get((rid, rid))
            items.append({"rule_id": rid, "rule_name": r["rule_name"], "rule_source": r["rule_source"], "severity": r["severity"], "status": r["status"],
                          "table_code": r["table_code"], "product_id": None, "record_key": None, "position_id": None, "item_key": rid,
                          "detail": r["failure_details"], "state": "explained" if dd else "open", "decision": dd})
    items.sort(key=lambda i: (i["state"] != "open", i["status"] != "FAIL", i["rule_id"], i["item_key"]))
    return items


def validate_suggest(date: str, rule_id: str, item_key: str):
    """AI-suggested fix for one exception (ai_query on the SQL warehouse): a field correction on a position, or an explanation."""
    _check_date(date)
    k = (date, rule_id, item_key)
    if k in _VAL_SUGGEST:
        return _VAL_SUGGEST[k]
    m = _deps()
    item = next((i for i in validate_queue(date) if i["rule_id"] == rule_id and i["item_key"] == item_key), None)
    if not item:
        raise HTTPException(404, "No such exception")
    rule = (m.run_pg("SELECT validation_rule FROM rules_validation WHERE rule_id = %s", (rule_id,)) or [{}])[0].get("validation_rule")
    expl = m.run_pg("SELECT suggestion FROM ai_suggestions WHERE as_of_date = %s AND suggestion_type = 'RULE_EXPLANATION' AND subject_key = %s LIMIT 1", (date, rule_id))
    positions, fields = [], []
    if item["record_key"] or item["position_id"]:
        t = correct_target(date, record_key=item["record_key"], position_id=item["position_id"])
        positions, fields = t["positions"][:20], [f["column"] for f in t["fields"]]
    prompt = ("You resolve an FR 2052a validation exception. Use ONLY the facts given. Rule " + rule_id + " (" + item["rule_name"] + ", " + item["rule_source"] +
              ", severity " + item["severity"] + ")" + (": " + rule if rule else "") + ". Failure: " + str(item["detail"]) +
              (". Earlier analysis: " + expl[0]["suggestion"] if expl else "") +
              ". Positions behind the record (editable fields " + json.dumps(fields) + "): " + json.dumps(positions, default=str) +
              ". Choose ONE action: correct (one position field is clearly wrong and the right value follows from the rule and the data; give "
              "position_id, field and new_value), or explain (the data is right or cannot be fixed from what is given - e.g. a WARNING the Fed only "
              "asks to be explained; draft the explanation). Answer ONLY JSON: {\"action\": \"correct\" | \"explain\", \"position_id\": id or null, "
              "\"field\": field or null, \"new_value\": value or null, \"explanation\": \"one or two sentences\", \"confidence\": 0.0-1.0}")
    try:
        out = _ai_json(m, prompt, 350)
        if out.get("action") == "correct" and (out.get("field") not in fields or not any(p["position_id"] == out.get("position_id") for p in positions)):
            out = {"action": "explain", "explanation": out.get("explanation"), "confidence": out.get("confidence")}
    except Exception as e:
        out = {"action": None, "explanation": f"No AI suggestion available ({str(e)[:100]})."}
    if out.get("action") == "correct":
        p = next(p for p in positions if p["position_id"] == out["position_id"])
        out["old_value"] = p.get(out["field"])
    _VAL_SUGGEST[k] = out
    return out


@router.post("/validate/{date}/resolve")
def validate_resolve(date: str, data: dict, request: Request):
    """Accept the AI correction (saved as a position correction), record a manual correction, or explain and keep (warnings)."""
    _check_date(date)
    m = _deps()
    action, rule_id, key = data.get("action"), data.get("rule_id"), data.get("item_key")
    note = (data.get("note") or "").strip()
    if action not in ("accept_ai", "manual", "explain"):
        raise HTTPException(400, "action must be accept_ai, manual or explain")
    item = next((v for v in validate_queue(date) if v["rule_id"] == rule_id and v["item_key"] == key), None)
    if not item:
        raise HTTPException(404, "No such exception on this date")
    if item["state"] != "open":
        raise HTTPException(409, f"This exception is already {item['state']}")
    if action in ("manual", "explain") and not note:
        raise HTTPException(400, "a note is required")
    if action == "manual" and not m.run_pg("""SELECT 1 FROM position_corrections WHERE as_of_date = %s AND status <> 'WITHDRAWN'
                                               AND (position_id = %s OR (record_key IS NOT NULL AND record_key = %s)) LIMIT 1""",
                                            (date, item.get("position_id"), item.get("record_key"))):
        raise HTTPException(409, "Save the correction of the positions first - a manual fix needs the correction behind it")
    if action == "accept_ai":
        post_correction(date, {"position_id": data.get("position_id"), "field": data.get("field"), "new_value": data.get("new_value"),
                               "reason": note or f"{rule_id}: AI-suggested correction accepted", "record_key": data.get("record_key")}, request)
    with m.get_pg() as conn:
        with conn.cursor() as c:
            c.execute("INSERT INTO validation_decisions VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), 'DECIDED')",
                      (str(uuid.uuid4())[:8], date, rule_id, key, action, note[:1000], _user(request)))
        conn.commit()
    return {"rule_id": rule_id, "item_key": key, "action": action}


# ─── PID dictionary: FR 2052a is identified by product ID (PID), not MDRM ─────
@router.get("/metadata")
def metadata(q: str = ""):
    """FR 2052a products (PIDs) with the firm's derivation rules that assign them; MDRM codes only where they exist -
    the FR Y-15 Schedule G (STWF) items computed from FR 2052a data."""
    m = _deps()
    like = f"%{q.strip()}%"
    products = m.run_pg("""SELECT p.product_id, p.product_name, p.instructions_name, p.table_name, p.definition_page,
                                  COUNT(r.rule_id) AS pid_rules, STRING_AGG(DISTINCT r.standard_product_type, ', ') AS standard_product_types
                           FROM ref_product p LEFT JOIN rules_pid_derivation r ON r.product_id = p.product_id
                           WHERE p.product_id ILIKE %s OR p.product_name ILIKE %s OR p.instructions_name ILIKE %s
                           GROUP BY p.product_id, p.product_name, p.instructions_name, p.table_name, p.definition_page, p.table_code, p.product_number
                           ORDER BY p.table_code, p.product_number LIMIT 200""", (like, like, like))
    stwf = m.run_pg("""SELECT s.stwf_item, s.maturity_column, s.mdrm, s.description, r.product_ids
                       FROM ref_stwf_mdrm s LEFT JOIN (SELECT stwf_item, STRING_AGG(DISTINCT product_ids, ',') AS product_ids
                                                       FROM rules_stwf_appendix_vii GROUP BY stwf_item) r USING (stwf_item)
                       WHERE s.stwf_item ILIKE %s OR s.mdrm ILIKE %s OR s.description ILIKE %s OR r.product_ids ILIKE %s
                       ORDER BY s.stwf_item, s.maturity_column""", (like, like, like, like))
    return {"products": products, "stwf": stwf}


# ─── Genie: the FR 2052a Genie space (Genie Agent on the UC metric views), called directly - no agent in between ─────
@router.post("/genie")
def genie(data: dict):
    """Start a question (or a follow-up in the same conversation); the page polls /genie/{conversation}/{message}."""
    m = _deps()
    question = (data.get("question") or "").strip()
    if not question:
        raise HTTPException(400, "No question")
    if not m.GENIE_SPACE_ID:
        raise HTTPException(500, "GENIE_SPACE_ID is not configured")
    conv = data.get("conversation_id")
    if conv:
        r = m._genie_api("POST", f"/api/2.0/genie/spaces/{m.GENIE_SPACE_ID}/conversations/{_safe_id(conv)}/messages", {"content": question})
        return {"conversation_id": conv, "message_id": r.get("id") or r.get("message_id")}
    r = m._genie_api("POST", f"/api/2.0/genie/spaces/{m.GENIE_SPACE_ID}/start-conversation", {"content": question})
    return {"conversation_id": r.get("conversation_id"), "message_id": r.get("message_id")}


@router.get("/genie/{conversation_id}/{message_id}")
def genie_result(conversation_id: str, message_id: str):
    """The state of one question; when done: the answer text, the SQL Genie ran, the result rows and suggested follow-ups."""
    m = _deps()
    msg = m._genie_api("GET", f"/api/2.0/genie/spaces/{m.GENIE_SPACE_ID}/conversations/{_safe_id(conversation_id)}/messages/{_safe_id(message_id)}")
    status = msg.get("status", "")
    if status not in ("COMPLETED", "FAILED", "CANCELLED", "QUERY_RESULT_EXPIRED"):
        return {"status": "running", "step": status.replace("_", " ").lower()}
    out = m._extract_genie_result(msg)
    host = m.get_ws().config.host.rstrip("/")
    out.update(status=status.lower(), explore_url=f"{host}/genie/spaces/{m.GENIE_SPACE_ID}/conversations/{conversation_id}")
    return out




# ─── LCR module: the regulation's parameters and rules, how the source data maps to them, and the calculation step by step ─────
# The engine is notebook 04 (12 CFR 249); these are its constants, shown so the analyst sees exactly what is applied.
LCR_PARAMETERS = [
    {"parameter": "Level 2A haircut", "value": "15%", "cite": "12 CFR 249.21(b)(2)", "how": "Level 2A HQLA counts at 85% of fair value"},
    {"parameter": "Level 2B haircut", "value": "50%", "cite": "12 CFR 249.21(b)(3)", "how": "Level 2B HQLA counts at 50% of fair value"},
    {"parameter": "Level 2 cap", "value": "40% of HQLA", "cite": "12 CFR 249.21(d)", "how": "Level 2A + 2B after haircuts may not exceed 40/60 of Level 1"},
    {"parameter": "Level 2B cap", "value": "15% of HQLA", "cite": "12 CFR 249.21(e)", "how": "Level 2B after haircut may not exceed 15/85 of Level 1 + Level 2A"},
    {"parameter": "Inflow cap", "value": "75% of outflows", "cite": "12 CFR 249.30(a)", "how": "Inflows count up to 75% of total outflows"},
    {"parameter": "Outflow adjustment", "value": "100% / 85% / 70%", "cite": "12 CFR 249.30(b); 249 Subpart G", "how": "Category I-II 100%, Category III 85% (reduced LCR), Category IV 70%"},
    {"parameter": "Horizon", "value": "30 calendar days", "cite": "12 CFR 249.30", "how": "Outflows and inflows maturing (or callable) within the next 30 days"},
    {"parameter": "Maturity mismatch add-on", "value": "peak day less day 30", "cite": "12 CFR 249.30(b)", "how": "Largest net cumulative maturity outflow over days 1-30 (maturing outflows less maturing inflows, floored at 0) less the amount on day 30"},
]


def _entity(entity: str) -> str:
    if entity not in ("ENT001", "ENT002"):
        raise HTTPException(400, "entity must be ENT001 or ENT002 (the entities subject to the LCR)")
    return entity


@router.get("/lcr/reference")
def lcr_reference():
    """The regulatory reference the engine applies: its parameters, the HQLA classes of collateral, and the 74 FR 2052a Appendix VI rules."""
    m = _deps()
    rules = m.run_pg("""SELECT rule_id, rule_section, flow_direction, rule_name, rule_description, applicable_product_ids, sub_product_condition,
                               counterparty_condition, counterparty_category_condition, collateral_hqla_condition, insured_condition, maturity_condition,
                               other_condition, amount_basis, COALESCE(outflow_rate, inflow_rate) AS rate, rule_priority
                        FROM rules_lcr_appendix_vi ORDER BY flow_direction, rule_id""")
    hqla = m.run_wh(f"""SELECT collateral_class, description, category_group, hqla_level, is_hqla, lcr_haircut_pct
                         FROM ref_collateral ORDER BY is_hqla DESC, hqla_level, collateral_class""")
    lines = {ln: t for ln, t, _, _ in LCR_TEMPLATE}
    for r in rules:
        ln = LCR_RULE_LINE.get(r["rule_id"]) or {"HQLA": None}.get(r["flow_direction"])
        r["disclosure_line"] = f"{ln} {lines[ln]}" if ln else ("1-4 HQLA" if r["flow_direction"].startswith("HQLA") else "")
    return {"parameters": LCR_PARAMETERS, "hqla_classes": hqla, "rules": rules}


@router.get("/lcr/{date}/mapping")
def lcr_mapping(date: str, entity: str = "ENT001"):
    """Per LCR rule: which source data reached it today - feeds, source systems, bank product codes, standard product types, PIDs -
    with positions and amounts. Rules no position matched today are listed too."""
    _check_date(date)
    e = _entity(entity)
    m = _deps()
    rows = m.run_wh(f"""
      SELECT r.rule_id, r.rule_section, r.flow_direction, r.rule_name, COALESCE(r.outflow_rate, r.inflow_rate) AS rate, r.applicable_product_ids,
             COUNT(d.record_id) AS positions, COALESCE(SUM(d.amount_usd), 0) AS amount_usd, COALESCE(SUM(d.weighted_amount_usd), 0) AS weighted_usd,
             array_to_string(array_agg(DISTINCT s.source_feed ORDER BY s.source_feed), ', ') AS source_feeds,
             array_to_string(array_agg(DISTINCT f.source_system ORDER BY f.source_system), ', ') AS source_systems,
             array_to_string((array_agg(DISTINCT f.source_product_code ORDER BY f.source_product_code))[1:1 + 8 - 1], ', ') AS bank_product_codes,
             array_to_string(array_agg(DISTINCT f.standard_product_type ORDER BY f.standard_product_type), ', ') AS standard_product_types,
             array_to_string(array_agg(DISTINCT d.product_id ORDER BY d.product_id), ', ') AS pids_matched
      FROM rules_lcr_appendix_vi r
      LEFT JOIN calculation_detail d ON d.rule_id = r.rule_id AND d.as_of_date = '{date}' AND d.entity_id = '{e}'
      LEFT JOIN fact_liquidity_position f ON f.as_of_date = d.as_of_date AND f.position_id = d.record_id
      LEFT JOIN source_position s ON s.as_of_date = f.as_of_date AND s.record_id = f.record_id
      GROUP BY 1, 2, 3, 4, 5, 6 ORDER BY COUNT(d.record_id) = 0, r.flow_direction, weighted_usd DESC""")
    return rows


@router.get("/lcr/{date}/calculation")
def lcr_calculation(date: str, entity: str = "ENT001"):
    """The LCR of the day as the engine computed it, step by step (HQLA, outflows, inflows and cap, net cash outflows, ratio),
    with every LCR rule's contribution."""
    _check_date(date)
    e = _entity(entity)
    m = _deps()
    r = (m.run_pg("SELECT * FROM calculation_results WHERE as_of_date = %s AND entity_id = %s ORDER BY calculation_timestamp DESC LIMIT 1", (date, e)) or [None])[0]
    if not r:
        raise HTTPException(404, f"No LCR for {e} on {date}")
    f = lambda k: float(r.get(k) or 0)
    cap = max(f("level2_cap_excess"), f("level2b_cap_excess"))
    steps = [
        {"group": "HQLA", "step": "Level 1 assets", "usd": f("level1_hqla"), "how": "Level 1 fair value, less HQLA that cannot be transferred from subsidiaries"
                                                                             + (f" ({f('excluded_hqla'):,.1f} excluded)" if f("excluded_hqla") else "")},
        {"group": "HQLA", "step": "Level 2A assets", "usd": f("level2a_hqla"), "how": "fair value before haircut"},
        {"group": "HQLA", "step": "Level 2A after 15% haircut", "usd": f("level2a_hqla_adjusted"), "how": "x 85%"},
        {"group": "HQLA", "step": "Level 2B assets", "usd": f("level2b_hqla"), "how": "fair value before haircut"},
        {"group": "HQLA", "step": "Level 2B after 50% haircut", "usd": f("level2b_hqla_adjusted"), "how": "x 50%"},
        {"group": "HQLA", "step": "Less Level 2 / 2B cap excess", "usd": -cap, "how": f"40% cap excess {f('level2_cap_excess'):,.1f}; 15% Level 2B cap excess {f('level2b_cap_excess'):,.1f}; the larger is deducted"},
        {"group": "HQLA", "step": "HQLA", "usd": f("total_hqla"), "how": "Level 1 + Level 2A + Level 2B after haircuts, less cap excess", "total": True},
        {"group": "Outflows", "step": "Retail deposits", "usd": f("retail_deposit_outflows"), "how": "O.D retail - amount x run-off rate"},
        {"group": "Outflows", "step": "Wholesale unsecured funding", "usd": f("wholesale_unsecured_outflows"), "how": "O.W, O.D non-retail"},
        {"group": "Outflows", "step": "Secured funding", "usd": f("secured_funding_outflows"), "how": "O.S - by the collateral's HQLA level"},
        {"group": "Outflows", "step": "Derivatives", "usd": f("derivative_outflows"), "how": "O.O derivative payables and collateral"},
        {"group": "Outflows", "step": "Commitments", "usd": f("commitment_outflows"), "how": "O.O undrawn credit and liquidity facilities"},
        {"group": "Outflows", "step": "Other outflows", "usd": f("other_outflows"), "how": "the rest of O.O"},
        {"group": "Outflows", "step": "Total outflows", "usd": f("total_outflows"), "how": "sum of the above", "total": True},
        {"group": "Inflows", "step": "Total inflows", "usd": f("total_inflows"), "how": "I.U, I.S, I.O within 30 days - amount x inflow rate"},
        {"group": "Inflows", "step": "Inflow cap (75% of outflows)", "usd": f("inflow_cap"), "how": "12 CFR 249.30(a)"},
        {"group": "Inflows", "step": "Inflows counted", "usd": f("capped_inflows"), "how": "the lower of the two", "total": True},
        {"group": "Net cash outflows", "step": "Maturity mismatch add-on", "usd": f("maturity_mismatch_add_on"), "how": "peak-day net cumulative maturity outflow less day 30 (12 CFR 249.30(b))"},
        {"group": "Net cash outflows", "step": "Outflow adjustment", "usd": None, "pct": f("outflow_adjustment_pct"), "how": "by the entity's Fed category"},
        {"group": "Net cash outflows", "step": "Net cash outflows", "usd": f("total_net_cash_outflows"), "how": "(outflows - inflows counted + add-on) x adjustment", "total": True},
        {"group": "LCR", "step": "Liquidity Coverage Ratio", "usd": None, "pct": f("lcr_ratio"), "how": "HQLA / net cash outflows - minimum 100%", "total": True},
    ]
    by_rule = m.run_pg("""SELECT d.flow_direction, d.rule_id, r.rule_section, d.rule_name, COUNT(*) AS positions, SUM(d.amount_usd) AS amount_usd,
                                 MAX(d.rate) AS rate, SUM(d.weighted_amount_usd) AS weighted_usd
                          FROM calculation_detail d LEFT JOIN rules_lcr_appendix_vi r USING (rule_id)
                          WHERE d.as_of_date = %s AND d.entity_id = %s GROUP BY 1, 2, 3, 4 ORDER BY 1, SUM(d.weighted_amount_usd) DESC""", (date, e))
    return {"entity": e, "lcr_ratio": f("lcr_ratio"), "compliant": r.get("lcr_compliant"), "unmatched_positions": r.get("unmatched_positions"),
            "steps": steps, "by_rule": by_rule}


@router.get("/lcr/{date}/rule/{rule_id}/positions")
def lcr_rule_positions(date: str, rule_id: str, entity: str = "ENT001", page: int = 0):
    """The positions one LCR rule applied to, with their source, amount, rate and weighted amount (paged, from Delta)."""
    _check_date(date)
    e, rid, size = _entity(entity), _safe_id(rule_id), 50
    m = _deps()
    base = f"""FROM calculation_detail d
               JOIN fact_liquidity_position f ON f.as_of_date = d.as_of_date AND f.position_id = d.record_id
               WHERE d.as_of_date = '{date}' AND d.entity_id = '{e}' AND d.rule_id = '{rid}'"""
    total = int(m.run_wh(f"SELECT COUNT(*) AS n {base}")[0]["n"])
    rows = m.run_wh(f"""SELECT d.record_id AS position_id, f.source_system, f.source_product_code, f.standard_product_type, d.product_id, f.counterparty,
                                d.collateral_class, d.hqla_level, f.maturity_bucket, d.amount_usd, d.rate, d.weighted_amount_usd
                         {base} ORDER BY d.weighted_amount_usd DESC LIMIT {size} OFFSET {max(0, page) * size}""")
    return {"total": total, "size": size, "rows": rows}


# ─── LCR public disclosure (12 CFR 249.90-91): the 35-line quantitative template, averaged over the period's daily LCRs ─────
LCR_TEMPLATE = [   # (line, text, section, indent)
    (1, "Total eligible high-quality liquid assets (HQLA), of which:", "High-Quality Liquid Assets", 0), (2, "Eligible level 1 liquid assets", "High-Quality Liquid Assets", 1),
    (3, "Eligible level 2A liquid assets", "High-Quality Liquid Assets", 1), (4, "Eligible level 2B liquid assets", "High-Quality Liquid Assets", 1),
    (5, "Deposit outflow from retail customers and counterparties, of which:", "Cash Outflow Amounts", 0), (6, "Stable retail deposit outflow", "Cash Outflow Amounts", 1),
    (7, "Other retail funding outflow", "Cash Outflow Amounts", 1), (8, "Brokered deposit outflow", "Cash Outflow Amounts", 1),
    (9, "Unsecured wholesale funding outflow, of which:", "Cash Outflow Amounts", 0), (10, "Operational deposit outflow", "Cash Outflow Amounts", 1),
    (11, "Non-operational funding outflow", "Cash Outflow Amounts", 1), (12, "Unsecured debt outflow", "Cash Outflow Amounts", 1),
    (13, "Secured wholesale funding and asset exchange outflow", "Cash Outflow Amounts", 0), (14, "Additional outflow requirements, of which:", "Cash Outflow Amounts", 0),
    (15, "Outflow related to derivative exposures and other collateral requirements", "Cash Outflow Amounts", 1),
    (16, "Outflow related to credit and liquidity facilities including unconsolidated structured transactions and mortgage commitments", "Cash Outflow Amounts", 1),
    (17, "Other contractual funding obligation outflow", "Cash Outflow Amounts", 0), (18, "Other contingent funding obligations outflow", "Cash Outflow Amounts", 0),
    (19, "Total Cash Outflow", "Cash Outflow Amounts", 0),
    (20, "Secured lending and asset exchange cash inflow", "Cash Inflow Amounts", 0), (21, "Retail cash inflow", "Cash Inflow Amounts", 0),
    (22, "Unsecured wholesale cash inflow", "Cash Inflow Amounts", 0), (23, "Other cash inflows, of which:", "Cash Inflow Amounts", 0),
    (24, "Net derivative cash inflow", "Cash Inflow Amounts", 1), (25, "Securities cash inflow", "Cash Inflow Amounts", 1),
    (26, "Broker-dealer segregated account inflow", "Cash Inflow Amounts", 1), (27, "Other cash inflow", "Cash Inflow Amounts", 1),
    (28, "Total Cash Inflow", "Cash Inflow Amounts", 0),
    (29, "HQLA Amount", "Average Amount", 0), (30, "Total Net Cash Outflow Amount Excluding the Maturity Mismatch Add-On", "Average Amount", 0),
    (31, "Maturity Mismatch Add-On", "Average Amount", 0), (32, "Total Net Cash Outflow Amount Including the Maturity Mismatch Add-On", "Average Amount", 0),
    (33, "Outflow Adjustment Percentage", "Average Amount", 0), (34, "Total Adjusted Net Cash Outflow Amount", "Average Amount", 0),
    (35, "Liquidity Coverage Ratio (%)", "Average Amount", 0),
]
# Each FR 2052a Appendix VI LCR rule's disclosure line (outflows 5-18, inflows 20-27; HQLA lines 1-4 come from the HQLA calculation)
LCR_RULE_LINE = {"LCR-O01": 6, "LCR-O02": 7, "LCR-O24": 7, "LCR-O03": 8, "LCR-O04": 8, "LCR-O05": 8, "LCR-O06": 8, "LCR-O07": 8, "LCR-O08": 8,
                 "LCR-O10": 10, "LCR-O11": 10, "LCR-O12": 11, "LCR-O13": 11, "LCR-O14": 11, "LCR-O22": 11, "LCR-O23": 11, "LCR-O25": 11,
                 "LCR-O20": 12, "LCR-O21": 12, "LCR-O59": 12, "LCR-O60": 12,
                 **{f"LCR-O{n}": 13 for n in range(30, 40)},
                 "LCR-O40": 15, "LCR-O41": 15, "LCR-O52": 15, "LCR-O53": 15, "LCR-O54": 15, "LCR-O55": 15, "LCR-O56": 15, "LCR-O58": 15,
                 **{f"LCR-O{n}": 16 for n in range(42, 51)}, "LCR-O57": 17, "LCR-O51": 18,
                 **{f"LCR-I1{n}": 20 for n in range(0, 7)}, "LCR-I02": 21, "LCR-I01": 22, "LCR-I03": 22, "LCR-I04": 22, "LCR-I05": 22, "LCR-I06": 22,
                 "LCR-I20": 24, "LCR-I23": 24, "LCR-I24": 25, "LCR-I25": 25, "LCR-I21": 27, "LCR-I22": 27}
_LCR_PARENT = {5: (6, 7, 8), 9: (10, 11, 12), 14: (15, 16), 23: (24, 25, 26, 27)}


def _lcr_days(m, e, start, end):
    return m.run_pg("""SELECT * FROM calculation_results WHERE entity_id = %s AND as_of_date BETWEEN %s AND %s ORDER BY as_of_date""", (e, start, end))


@router.get("/lcr/disclosure")
def lcr_disclosure(start: str, end: str, entity: str = "ENT001"):
    """The LCR public disclosure template (12 CFR 249.91): every line as the simple average of the daily amounts over the period,
    unweighted (before rates, haircuts and caps) and weighted (after) - with the LCR rules behind each line."""
    _check_date(start), _check_date(end)
    e = _entity(entity)
    m = _deps()
    days = _lcr_days(m, e, start, end)
    if not days:
        raise HTTPException(404, f"No LCR for {e} between {start} and {end}")
    n = len(days)
    det = m.run_pg("""SELECT rule_id, SUM(amount_usd) AS unweighted, SUM(weighted_amount_usd) AS weighted FROM calculation_detail
                      WHERE entity_id = %s AND as_of_date BETWEEN %s AND %s AND flow_direction IN ('INFLOW', 'OUTFLOW') GROUP BY 1""", (e, start, end))
    uw, w, rules_of = {}, {}, {}
    for r in det:
        line = LCR_RULE_LINE.get(r["rule_id"])
        if line:
            uw[line] = uw.get(line, 0) + float(r["unweighted"] or 0) / n
            w[line] = w.get(line, 0) + float(r["weighted"] or 0) / n
            rules_of.setdefault(line, []).append(r["rule_id"])
    for parent, kids in _LCR_PARENT.items():
        uw[parent], w[parent] = sum(uw.get(k, 0) for k in kids), sum(w.get(k, 0) for k in kids)
    for tot, parts in ((19, (5, 9, 13, 14, 17, 18)), (28, (20, 21, 22, 23))):
        uw[tot], w[tot] = sum(uw.get(k, 0) for k in parts), sum(w.get(k, 0) for k in parts)
    avg = lambda k: sum(float(d.get(k) or 0) for d in days) / n
    uw[2], w[2] = avg("level1_hqla"), avg("level1_hqla")
    uw[3], w[3] = avg("level2a_hqla"), avg("level2a_hqla_adjusted")
    uw[4], w[4] = avg("level2b_hqla"), avg("level2b_hqla_adjusted")
    uw[1], w[1] = uw[2] + uw[3] + uw[4], avg("total_hqla")
    single = {29: avg("total_hqla"), 30: avg("total_outflows") - avg("capped_inflows"), 31: avg("maturity_mismatch_add_on"),
              32: avg("total_outflows") - avg("capped_inflows") + avg("maturity_mismatch_add_on"), 33: avg("outflow_adjustment_pct"),
              34: avg("total_net_cash_outflows"), 35: avg("lcr_ratio")}
    lines = [{"line": ln, "text": t, "section": sec, "indent": ind,
              "unweighted": None if ln >= 29 else round(uw.get(ln, 0), 1), "weighted": round(single[ln] if ln >= 29 else w.get(ln, 0), 4 if ln in (33, 35) else 1),
              "rules": sorted(rules_of.get(ln, []))} for ln, t, sec, ind in LCR_TEMPLATE]
    return {"entity": e, "start": str(days[0]["as_of_date"]), "end": str(days[-1]["as_of_date"]), "days": n,
            "daily": [{"as_of_date": str(d["as_of_date"]), "lcr": float(d["lcr_ratio"] or 0), "hqla": float(d["total_hqla"] or 0),
                       "nco": float(d["total_net_cash_outflows"] or 0), "add_on": float(d.get("maturity_mismatch_add_on") or 0)} for d in days],
            "lines": lines, "note": "Simple averages of the daily amounts over the period. Line 1 weighted, and lines 29-35, are after the level 2 caps, the inflow cap and the "
                                    "maturity mismatch add-on, so they need not equal the sum of lines 2-28. Line 35 is the average of the daily LCRs."}


# ─── AI (Databricks ai_query): explain the day's LCR move, and draft the disclosure's qualitative sections for review ─────
_LCR_EXPLAIN = {}
DISCLOSURE_SECTIONS = [("lcr_variance", "LCR variance"), ("drivers", "Drivers of the average LCR"), ("hqla_composition", "HQLA composition"),
                       ("outflow_drivers", "Outflow drivers"), ("inflow_drivers", "Inflow drivers"), ("funding_concentration", "Concentration of funding sources"),
                       ("derivatives_collateral", "Derivative exposures and collateral calls"), ("currency_mismatch", "Currency mismatch"),
                       ("liquidity_management", "Centralized liquidity management")]


AI_MODEL = os.environ.get("AI_MODEL", "databricks-claude-sonnet-4-6")


def _ai_text(m, prompt, tokens=900):
    """The model's answer, from the Foundation Model serving endpoint directly (no SQL warehouse on the click path);
    falls back to ai_query on the warehouse if the endpoint cannot be reached."""
    try:
        r = m.get_ws().api_client.do("POST", f"/serving-endpoints/{AI_MODEL}/invocations", body={
            "messages": [{"role": "user", "content": prompt}], "max_tokens": tokens, "temperature": 0})
        c = r["choices"][0]["message"]["content"]
        return c if isinstance(c, str) else "".join(x.get("text", "") for x in c if isinstance(x, dict))
    except Exception as e:
        print(f"[ai] serving endpoint failed, using ai_query on the warehouse: {str(e)[:160]}")
        sql = (f"SELECT ai_query('{AI_MODEL}', '" + prompt.replace("\\", "\\\\").replace("'", "\\'") +
               f"', modelParameters => named_struct('max_tokens', {tokens}, 'temperature', 0.0)) AS r")
        return m.run_sql(sql)[0]["r"]


def _ai_json(m, prompt, tokens=900):
    import re
    return json.loads(re.search(r"\{.*\}", _ai_text(m, prompt, tokens), re.S).group(0))


@router.get("/lcr/{date}/explain")
def lcr_explain(date: str, entity: str = "ENT001"):
    """Why the LCR moved since the prior day: an exact attribution (HQLA effect, and the net cash outflow effect split by category)
    computed from the engine's results, and an AI explanation of it that uses only those numbers and the rules that moved most."""
    _check_date(date)
    e = _entity(entity)
    m = _deps()
    rows = m.run_pg("""SELECT * FROM calculation_results WHERE entity_id = %s AND as_of_date <= %s ORDER BY as_of_date DESC LIMIT 2""", (e, date))
    if len(rows) < 2:
        raise HTTPException(404, "No prior day to compare with")
    t, p = rows
    f = lambda r, k: float(r.get(k) or 0)
    h0, h1, n0, n1 = f(p, "total_hqla"), f(t, "total_hqla"), f(p, "total_net_cash_outflows"), f(t, "total_net_cash_outflows")
    hqla_effect, nco_effect = (h1 - h0) / n0, h1 / n1 - h1 / n0
    cats = [("Retail deposits", "retail_deposit_outflows", 1), ("Wholesale unsecured funding", "wholesale_unsecured_outflows", 1),
            ("Secured funding", "secured_funding_outflows", 1), ("Derivatives", "derivative_outflows", 1), ("Commitments", "commitment_outflows", 1),
            ("Other outflows", "other_outflows", 1), ("Inflows counted", "capped_inflows", -1), ("Maturity mismatch add-on", "maturity_mismatch_add_on", 1)]
    adj = f(t, "outflow_adjustment_pct") or 1
    d_nco = sum(sign * (f(t, k) - f(p, k)) for _, k, sign in cats) * adj
    attribution = [{"driver": "HQLA", "prior": h0, "today": h1, "change": h1 - h0, "lcr_effect": hqla_effect}]
    for name, k, sign in cats:
        ch = sign * (f(t, k) - f(p, k)) * adj
        attribution.append({"driver": name, "prior": f(p, k), "today": f(t, k), "change": f(t, k) - f(p, k),
                            "lcr_effect": nco_effect * ch / d_nco if d_nco else 0.0})
    movers = m.run_pg("""SELECT rule_id, rule_name, flow_direction, SUM(CASE WHEN as_of_date = %s THEN weighted_amount_usd ELSE -weighted_amount_usd END) AS change
                         FROM calculation_detail WHERE entity_id = %s AND as_of_date IN (%s, %s) AND flow_direction IN ('INFLOW', 'OUTFLOW', 'HQLA')
                         GROUP BY 1, 2, 3 ORDER BY ABS(SUM(CASE WHEN as_of_date = %s THEN weighted_amount_usd ELSE -weighted_amount_usd END)) DESC LIMIT 6""",
                      (t["as_of_date"], e, t["as_of_date"], p["as_of_date"], t["as_of_date"]))
    out = {"entity": e, "date": str(t["as_of_date"]), "prior_date": str(p["as_of_date"]), "lcr_prior": f(p, "lcr_ratio"), "lcr_today": f(t, "lcr_ratio"),
           "attribution": attribution, "movers": movers}
    key = (e, out["date"], round(out["lcr_today"], 6))
    if key not in _LCR_EXPLAIN:
        facts = {k: out[k] for k in ("entity", "date", "prior_date", "lcr_prior", "lcr_today")}
        facts["attribution_usd_mm_and_lcr_points"] = [{**a, "lcr_effect_pct_points": round(a["lcr_effect"] * 100, 2)} for a in attribution if abs(a["change"]) > 0.05]
        facts["largest_rule_movements_usd_mm"] = movers
        prompt = ("You are a liquidity risk analyst explaining a bank's Liquidity Coverage Ratio (12 CFR 249) move to the treasurer. Use ONLY these facts; never "
                  "invent numbers. Facts: " + json.dumps(facts, default=str) + ". Write: a one-sentence headline (LCR from x% to y%, up/down n pp, and the main reason), "
                  "then 2-3 sentences on the drivers in order of their LCR effect, naming the LCR rules that moved most and whether HQLA or net cash outflows drove "
                  "it. Answer ONLY JSON: {\"headline\": \"...\", \"explanation\": \"...\"}")
        try:
            _LCR_EXPLAIN[key] = _ai_json(m, prompt, 400)
        except Exception as x:
            _LCR_EXPLAIN[key] = {"headline": "", "explanation": f"AI explanation not available ({str(x)[:120]})"}
    out.update(_LCR_EXPLAIN[key])
    out["generated_by"] = "ai_query (databricks-claude-sonnet-4-6) over the attribution computed from reg_lcr.calculation_results"
    return out


def _disclosure_facts(m, start, end, e):
    """The numbers the disclosure narrative may use: the template, the daily LCR, HQLA by collateral class, funding concentration
    by counterparty, and the currency split - all from the LCR engine's detail."""
    d = lcr_disclosure(start, end, e)
    hq = m.run_wh(f"""SELECT COALESCE(c.description, d.collateral_class, d.rule_name) AS asset, d.hqla_level, round(CAST(SUM(d.amount_usd) / COUNT(DISTINCT d.as_of_date) AS NUMERIC), 1) AS avg_usd_mm
                       FROM calculation_detail d LEFT JOIN ref_collateral c USING (collateral_class)
                       WHERE d.entity_id = '{e}' AND d.as_of_date BETWEEN '{start}' AND '{end}' AND d.flow_direction = 'HQLA' GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 8""")
    cpty = m.run_wh(f"""SELECT COALESCE(counterparty, 'n/a') AS counterparty, round(CAST(SUM(weighted_amount_usd) / COUNT(DISTINCT as_of_date) AS NUMERIC), 1) AS avg_weighted_outflow_usd_mm
                         FROM calculation_detail WHERE entity_id = '{e}' AND as_of_date BETWEEN '{start}' AND '{end}' AND flow_direction = 'OUTFLOW'
                         GROUP BY 1 ORDER BY 2 DESC LIMIT 6""")
    ccy = m.run_wh(f"""SELECT f.currency, d.flow_direction, round(CAST(SUM(d.weighted_amount_usd) / COUNT(DISTINCT d.as_of_date) AS NUMERIC), 1) AS avg_weighted_usd_mm
                        FROM calculation_detail d JOIN fact_liquidity_position f ON f.as_of_date = d.as_of_date AND f.position_id = d.record_id
                        WHERE d.entity_id = '{e}' AND d.as_of_date BETWEEN '{start}' AND '{end}' GROUP BY 1, 2 ORDER BY 3 DESC""")
    ent = (m.run_pg("SELECT entity_id, entity_name, fed_category FROM ref_reporting_entity WHERE entity_id = %s", (e,)) or [{}])[0]
    days = _lcr_days(m, e, start, end)
    f = lambda r, k: float(r.get(k) or 0)
    derived = {   # facts the narrative must state correctly - computed, not left to the model
        "lcr_min_pct": round(min(f(r, "lcr_ratio") for r in days) * 100, 1), "lcr_max_pct": round(max(f(r, "lcr_ratio") for r in days) * 100, 1),
        "lcr_first_day_pct": round(f(days[0], "lcr_ratio") * 100, 1), "lcr_last_day_pct": round(f(days[-1], "lcr_ratio") * 100, 1),
        "inflow_cap_binding_days": sum(1 for r in days if f(r, "total_inflows") > f(r, "inflow_cap")),
        "level2_cap_binding_days": sum(1 for r in days if max(f(r, "level2_cap_excess"), f(r, "level2b_cap_excess")) > 0),
        "maturity_mismatch_add_on_days": sum(1 for r in days if f(r, "maturity_mismatch_add_on") > 0),
        "every_day_above_100pct": all(f(r, "lcr_ratio") >= 1 for r in days)}
    derived["statements"] = [   # the plain-language facts the draft must not contradict
        "Inflows were " + ("above the 75% inflow cap on %d day(s), so the cap applied" % derived["inflow_cap_binding_days"] if derived["inflow_cap_binding_days"]
                           else "below the 75% inflow cap on every day - the cap did not apply; all weighted inflows counted"),
        "The level 2 caps " + ("applied on %d day(s)" % derived["level2_cap_binding_days"] if derived["level2_cap_binding_days"] else "did not apply on any day"),
        "A maturity mismatch add-on " + ("applied on %d day(s)" % derived["maturity_mismatch_add_on_days"] if derived["maturity_mismatch_add_on_days"] else "was zero on every day")]
    return {"entity": ent, "period": {"start": d["start"], "end": d["end"], "days": d["days"]}, "derived_facts": derived, "daily_lcr": d["daily"],
            "template_usd_mm": [{"line": x["line"], "text": x["text"], "unweighted": x["unweighted"], "weighted": x["weighted"]} for x in d["lines"]],
            "hqla_by_asset": hq, "outflow_by_counterparty": cpty, "by_currency": ccy}


@router.get("/lcr/disclosure/draft")
def lcr_disclosure_draft(start: str, end: str, entity: str = "ENT001"):
    """The latest draft of the disclosure's qualitative sections for the period (AI text, the analyst's edits, approval)."""
    _check_date(start), _check_date(end)
    rows = _deps().run_pg("""SELECT * FROM lcr_disclosure_sections WHERE entity_id = %s AND period_start = %s AND period_end = %s
                             AND draft_id = (SELECT draft_id FROM lcr_disclosure_sections WHERE entity_id = %s AND period_start = %s AND period_end = %s
                                             ORDER BY created_at DESC LIMIT 1)""", (_entity(entity), start, end, entity, start, end))
    order = {k: i for i, (k, _) in enumerate(DISCLOSURE_SECTIONS)}
    return sorted(rows, key=lambda r: order.get(r["section"], 99))


@router.post("/lcr/disclosure/draft")
def lcr_disclosure_generate(data: dict, request: Request):
    """AI drafts every qualitative section of the LCR disclosure, in the structure large US banks publish, from the period's numbers only.
    Each section is then reviewed, edited and approved by the analyst."""
    start, end, e = data.get("start"), data.get("end"), _entity(data.get("entity", "ENT001"))
    _check_date(start), _check_date(end)
    m = _deps()
    facts = _disclosure_facts(m, start, end, e)
    prompt = ("You draft the qualitative part of a US bank holding company's quarterly Liquidity Coverage Ratio public disclosure (12 CFR 249.90), in the style "
              "of the disclosures of large US banks (State Street, BNY, Goldman Sachs, Capital One): factual, concise, regulatory tone, amounts in $ billions with one "
              "decimal, ratios in %. Use ONLY these facts - never invent numbers, products or events; where the facts do not cover a topic, say so plainly in "
              "general terms. derived_facts and its statements are authoritative and must be stated as given: never say the inflow cap, a level 2 cap or the maturity mismatch add-on applied unless its _days count "
              "is above 0, and state the LCR range exactly as given. Facts (USD mm): " + json.dumps(facts, default=str) + ". Write each section in 2-4 sentences. "
              "Answer ONLY JSON with these keys, every one with text: " + json.dumps({k: label for k, label in DISCLOSURE_SECTIONS}))
    try:
        sections = _ai_json(m, prompt, 2600)
        missing = [k for k, _ in DISCLOSURE_SECTIONS if not (sections.get(k) or "").strip()]
        if missing:   # one more pass for any section that came back empty
            again = _ai_json(m, prompt + " Return ONLY these keys: " + json.dumps(missing), 1200)
            sections.update({k: again.get(k, "") for k in missing})
    except Exception as x:
        raise HTTPException(502, f"AI draft not available: {str(x)[:200]}")
    did, user = str(uuid.uuid4())[:8], _user(request)
    with m.get_pg() as conn:
        with conn.cursor() as c:
            for k, _ in DISCLOSURE_SECTIONS:
                c.execute("""INSERT INTO lcr_disclosure_sections (draft_id, entity_id, period_start, period_end, section, ai_text, final_text, status,
                             created_by, created_at, model) VALUES (%s, %s, %s, %s, %s, %s, %s, 'DRAFT', %s, NOW(), 'databricks-claude-sonnet-4-6')""",
                          (did, e, start, end, k, sections.get(k, ""), sections.get(k, ""), user))
        conn.commit()
    return {"draft_id": did, "sections": len(DISCLOSURE_SECTIONS)}


@router.post("/lcr/disclosure/section")
def lcr_disclosure_section(data: dict, request: Request):
    """Save the analyst's edit of one section, or approve it (the approver is recorded; an approved section is locked until re-opened)."""
    m, user = _deps(), _user(request)
    action, did, sec = data.get("action"), _safe_id(data.get("draft_id") or ""), data.get("section")
    if sec not in dict(DISCLOSURE_SECTIONS):
        raise HTTPException(400, "unknown section")
    with m.get_pg() as conn:
        with conn.cursor() as c:
            if action == "save":
                c.execute("""UPDATE lcr_disclosure_sections SET final_text = %s, status = 'EDITED', edited_by = %s, edited_at = NOW()
                             WHERE draft_id = %s AND section = %s AND status <> 'APPROVED'""", ((data.get("text") or "")[:6000], user, did, sec))
            elif action == "approve":
                c.execute("""UPDATE lcr_disclosure_sections SET status = 'APPROVED', approved_by = %s, approved_at = NOW()
                             WHERE draft_id = %s AND section = %s""", (user, did, sec))
            elif action == "reopen":
                c.execute("""UPDATE lcr_disclosure_sections SET status = 'EDITED', approved_by = NULL, approved_at = NULL WHERE draft_id = %s AND section = %s""", (did, sec))
            else:
                raise HTTPException(400, "action must be save, approve or reopen")
            if c.rowcount == 0:
                raise HTTPException(409, "Nothing changed - the section is approved (re-open it first) or does not exist")
        conn.commit()
    return {"draft_id": did, "section": sec, "action": action}


@router.get("/lcr/disclosure/export")
def lcr_disclosure_export(start: str, end: str, entity: str = "ENT001"):
    """The disclosure as one HTML document: the quantitative template and the qualitative sections (approved text; drafts marked)."""
    from fastapi.responses import HTMLResponse
    import html
    d = lcr_disclosure(start, end, entity)
    secs = lcr_disclosure_draft(start, end, entity)
    fmt = lambda x, ln: "" if x is None else (f"{x * 100:.0f}%" if ln in (33, 35) else f"{x:,.0f}")
    rows = "".join(f"<tr><td>{x['line']}</td><td style='padding-left:{8 + 16 * x['indent']}px'>{html.escape(x['text'])}</td><td class=n>{fmt(x['unweighted'], x['line'])}</td>"
                   f"<td class=n>{fmt(x['weighted'], x['line'])}</td></tr>" for x in d["lines"])
    body = "".join(f"<h3>{html.escape(dict(DISCLOSURE_SECTIONS)[s['section']])}</h3><p>{html.escape(s['final_text'] or '')}</p>"
                   + ("" if s["status"] == "APPROVED" else "<p class=draft>Draft - not approved</p>") for s in secs)
    page = (f"<html><head><meta charset=utf-8><title>LCR Disclosure {d['entity']} {d['start']} to {d['end']}</title><style>body{{font-family:Arial;max-width:900px;margin:30px auto;color:#111}}"
            "table{border-collapse:collapse;width:100%;font-size:12px}td,th{border-bottom:1px solid #ddd;padding:4px}.n{text-align:right}.draft{color:#b45309;font-size:11px}</style></head><body>"
            f"<h1>U.S. Liquidity Coverage Ratio Disclosure</h1><p>{d['entity']} - average of {d['days']} daily observations, {d['start']} to {d['end']} ($ in millions)</p>"
            f"{body}<h2>Quantitative disclosure</h2><table><tr><th></th><th></th><th class=n>Average unweighted amount</th><th class=n>Average weighted amount</th></tr>{rows}</table>"
            f"<p style='font-size:11px;color:#555'>{html.escape(d['note'])}</p></body></html>")
    return HTMLResponse(page, headers={"Content-Disposition": f"attachment; filename=LCR_Disclosure_{d['entity']}_{d['start']}_{d['end']}.html"})
