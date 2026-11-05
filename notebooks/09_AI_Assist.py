# Databricks notebook source
# MAGIC %md
# MAGIC # AI Assist for the FR 2052a workbench (Databricks AI Functions) - v9
# MAGIC ## Owned by: Regulatory Reporting Team
# MAGIC
# MAGIC Databricks-native AI only: **AI Functions** in SQL (`ai_classify`, `ai_similarity`, `ai_query` on a Databricks
# MAGIC Foundation Model endpoint, `ai_forecast`). The rules and calculations stay authoritative - the AI **proposes**, a person
# MAGIC **accepts or rejects** in the app, and every suggestion and decision is kept in `ai_assist.suggestions`.
# MAGIC
# MAGIC | Step | Stage | Suggestion |
# MAGIC |---|---|---|
# MAGIC | 1 | Enrichment | New customers: FR 2052a Counterparty (`ai_classify` over the 19 types), G-SIB parent (`ai_similarity` vs the FSB 2020 list), rationale (`ai_query`) |
# MAGIC | 2 | Sourcing | Unmapped bank product codes: the standard product type (`ai_query` with the system's catalogue) |
# MAGIC | 3 | PID | Records no rule classifies: the likely PID and the missing attribute (`ai_query` with the rule conditions) |
# MAGIC | 4 | Validation | Plain-English explanation and fix for each failed / warning rule (`ai_query`) |
# MAGIC | 5 | Business review | Expected range per entity x table and top PIDs (`ai_forecast`), anomalies, drafted variance commentary and S.C comments (`ai_query`) |

# COMMAND ----------

dbutils.widgets.text("as_of_date", "2026-02-27")
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("model", "databricks-claude-sonnet-4-6")
dbutils.widgets.text("warehouse_id", "")
dbutils.widgets.text("steps", "customers,products,pid,rules,variance")
AS_OF = dbutils.widgets.get("as_of_date")
CATALOG = dbutils.widgets.get("catalog")
MODEL = dbutils.widgets.get("model")
WAREHOUSE = dbutils.widgets.get("warehouse_id")
STEPS = {s.strip() for s in dbutils.widgets.get("steps").split(",")}
spark.sql(f"USE CATALOG {CATALOG}")
R, S = f"{CATALOG}.reference", f"{CATALOG}.ai_assist.suggestions"

import json, re, uuid
from datetime import datetime
from pyspark.sql import functions as F

def sq(v):
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"

def parse_json(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except Exception:
        return {}

def save(rows):
    """rows: (suggestion_type, subject_key, subject, suggestion dict, rationale, ai_function, confidence)"""
    if not rows:
        return 0
    now = datetime.now()
    out = [(str(uuid.uuid4()), AS_OF, t, k, subj, json.dumps(sug), (rat or "")[:2000], fn, MODEL if "query" in fn or "classify" in fn else fn,
            conf, "PROPOSED", None, None, now) for t, k, subj, sug, rat, fn, conf in rows]
    (spark.createDataFrame(out, """suggestion_id STRING, as_of_date STRING, suggestion_type STRING, subject_key STRING, subject STRING,
        suggestion STRING, rationale STRING, ai_function STRING, model STRING, confidence DOUBLE, status STRING, decided_by STRING,
        decided_at TIMESTAMP, created_timestamp TIMESTAMP""").withColumn("as_of_date", F.to_date("as_of_date"))
     .write.mode("append").saveAsTable(S))
    return len(out)

def existing(stype):
    """Subjects that already have an open or decided suggestion - each subject is proposed once."""
    return {r.subject_key for r in spark.sql(f"SELECT DISTINCT subject_key FROM {S} WHERE suggestion_type = '{stype}' AND status <> 'REJECTED'").collect()}

def ai(prompt, max_tokens=600):
    return spark.sql(f"SELECT ai_query('{MODEL}', {sq(prompt)}, modelParameters => named_struct('max_tokens', {max_tokens}, 'temperature', 0.0)) AS r").first().r

# Redraft only what this run recomputes: rule explanations with the rules step, commentary and comments with the variance step
_redraft = (["RULE_EXPLANATION"] if "rules" in STEPS else []) + (["VARIANCE_COMMENTARY", "COMMENT_DRAFT"] if "variance" in STEPS else [])
if _redraft:
    spark.sql(f"DELETE FROM {S} WHERE as_of_date = '{AS_OF}' AND status = 'PROPOSED' AND suggestion_type IN ({', '.join(repr(t) for t in _redraft)})")
counts = {}

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. New customers - Counterparty, G-SIB parent, rationale

# COMMAND ----------

if "customers" in STEPS:
    labels = [r.counterparty for r in spark.table(f"{R}.ref_counterparty").collect()]
    gsibs = [r.allowed_value for r in spark.table(f"{R}.spec_field_values").where("field_name = 'G-SIB'").collect()]
    done = existing("CUSTOMER_CLASSIFICATION")
    pending = [r for r in spark.sql(f"""
        SELECT c.* FROM {CATALOG}.raw.customers c WHERE c.as_of_date = '{AS_OF}'
          AND c.customer_id NOT IN (SELECT customer_id FROM {R}.v_customer_master)""").collect() if r.customer_id not in done]
    rows = []
    for c in pending:
        desc = f"{c.customer_name}; legal form: {c.legal_form}; NAICS {c.naics_code}; country {c.country}"
        label_sql = "ARRAY(" + ", ".join(sq(l) for l in labels) + ")"
        cls = spark.sql(f"SELECT ai_classify({sq(desc)}, {label_sql}) AS c").first().c
        sims = spark.sql("SELECT g, ai_similarity(" + sq(c.customer_name) + ", g) AS s FROM VALUES " +
                         ", ".join(f"({sq(g)})" for g in gsibs) + " AS t(g) ORDER BY s DESC LIMIT 1").first()
        gsib = sims.g if sims.s >= 0.80 else None
        why = ai(f"""You classify counterparties for the Federal Reserve FR 2052a liquidity report. Customer: {desc}.
The proposed FR 2052a Counterparty type is "{cls}"{f' and its G-SIB parent "{gsib}" (FSB list)' if gsib else ''}.
In two sentences, explain why this classification fits the FR 2052a Counterparty definitions, or say clearly if another type fits better.""", 220)
        rows.append(("CUSTOMER_CLASSIFICATION", c.customer_id, c.customer_name,
                     {"counterparty": cls, "gsib_parent": gsib, "affiliate_legal_entity_id": None, "has_relationship": False,
                      "gsib_similarity": round(float(sims.s), 3), "description": desc}, why, "ai_classify + ai_similarity + ai_query", float(sims.s) if gsib else None))
    counts["customers"] = save(rows)
    print(f"customer classifications proposed: {counts['customers']}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Unmapped bank product codes - standard product type

# COMMAND ----------

if "products" in STEPS:
    done = existing("PRODUCT_MAPPING")
    codes = [r for r in spark.sql(f"""
        SELECT source_product_code, FIRST(source_feed) AS feed, FIRST(get_json_object(record_json, '$.source_system')) AS system,
               FIRST(get_json_object(record_json, '$.instrument_type')) AS instrument, COUNT(*) AS n
        FROM {CATALOG}.dq.quarantine WHERE as_of_date = '{AS_OF}' AND failed_rules LIKE '%DQ_006%' AND source_product_code IS NOT NULL
        GROUP BY source_product_code""").collect() if r.source_product_code not in done]
    rows = []
    for c in codes:
        catalog = spark.sql(f"""SELECT standard_product_type, description FROM {R}.ref_standard_product_type
                                WHERE source_system = {sq(c.system)}""").collect()
        options = "\n".join(f"- {x.standard_product_type}: {x.description}" for x in catalog)
        out = parse_json(ai(f"""A {c.system} source extract contains an unmapped bank product code "{c.source_product_code}"
(source description: "{c.instrument}", feed: {c.feed}). Map it to one of this system's standard product types:
{options}
Answer only JSON: {{"standard_product_type": "...", "confidence": 0.0-1.0, "rationale": "one sentence"}}"""))
        if out.get("standard_product_type") in {x.standard_product_type for x in catalog}:
            rows.append(("PRODUCT_MAPPING", c.source_product_code, f"{c.system} {c.source_product_code} ({c.instrument})",
                         {"source_system": c.system, "source_product_code": c.source_product_code,
                          "standard_product_type": out["standard_product_type"], "description": c.instrument, "records": c.n},
                         out.get("rationale"), "ai_query", out.get("confidence")))
    counts["products"] = save(rows)
    print(f"product code mappings proposed: {counts['products']}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Records no PID rule classifies - likely PID and the missing attribute

# COMMAND ----------

if "pid" in STEPS:
    exc = spark.sql(f"""SELECT * FROM {CATALOG}.dq.pid_exceptions WHERE as_of_date = '{AS_OF}' AND exception_type = 'NO_RULE'""").collect()
    rows = []
    for e in exc:
        rules = spark.sql(f"""SELECT r.priority, r.condition_sql, r.product_id, p.product_name, r.rationale FROM {R}.rules_pid_derivation r
                              JOIN {R}.ref_product p USING (product_id) WHERE r.standard_product_type = {sq(e.standard_product_type)} ORDER BY priority""").collect()
        rec = {k: v for k, v in json.loads(e.record_json).items() if v is not None and k in (
            "standard_product_type", "product_subtype", "flow_direction", "counterparty", "counterparty_category", "collateral_class",
            "hqla_level", "encumbrance_type", "sub_product", "insured", "maturity_type", "part_amount", "currency")}
        out = parse_json(ai(f"""An FR 2052a PID derivation rule set did not classify this source position:
{json.dumps(rec)}
The ordered rules for standard product type {e.standard_product_type} are:
""" + "\n".join(f"{x.priority}. IF {x.condition_sql} THEN {x.product_id} ({x.product_name}) - {x.rationale}" for x in rules) + """
Which PID is this position most likely, and which attribute is missing or wrong so that no rule matched?
Answer only JSON: {"product_id": "...", "missing_attribute": "...", "fix": "one sentence for the source system owner", "confidence": 0.0-1.0}""", 300))
        if out.get("product_id"):
            rows.append(("PID_EXCEPTION", e.position_id, f"{e.record_id} ({e.standard_product_type})", out, out.get("fix"), "ai_query", out.get("confidence")))
    counts["pid"] = save(rows)
    print(f"PID exception suggestions: {counts['pid']}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Failed and warning rules - plain-English explanation and fix

# COMMAND ----------

if "rules" in STEPS:
    fails = spark.sql(f"""SELECT v.rule_id, v.rule_source, v.rule_name, v.table_code, v.severity, v.status, v.records_failed, v.failure_details,
                                 b.validation_rule FROM {CATALOG}.reg_2052a.gold_validation v
                          LEFT JOIN {R}.rules_validation b ON b.rule_id = v.rule_id
                          WHERE v.as_of_date = '{AS_OF}' AND v.status IN ('FAIL', 'WARNING')""").collect()
    rows = []
    for f in fails:
        out = parse_json(ai(f"""You support an FR 2052a (6G) regulatory reporting team. A pre-filing check did not pass.
Check: {f.rule_id} ({f.rule_source}) - {f.rule_name}. {('Fed rule text: ' + f.validation_rule) if f.validation_rule else ''}
Table: {f.table_code}; severity {f.severity}; status {f.status}; {f.records_failed} record(s); details: {f.failure_details}
Answer only JSON: {{"explanation": "two sentences a business reviewer understands", "likely_cause": "one sentence",
"fix": "one sentence - what to change and where (source data, master data, rule, or adjustment)", "blocks_filing": true/false}}""", 350))
        if out:
            rows.append(("RULE_EXPLANATION", f.rule_id, f"{f.rule_id} {f.rule_name}"[:200], out, out.get("explanation"), "ai_query", None))
    counts["rules"] = save(rows)
    print(f"rule explanations: {counts['rules']}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Variance: ai_forecast expected range, anomalies, drafted commentary and comments

# COMMAND ----------

if "variance" in STEPS:
    series = f"""
      SELECT as_of_date AS ds, CONCAT(reporting_entity, '|', table_code, '|*') AS series, SUM(reported_amount_usd) AS y
      FROM {CATALOG}.reg_2052a.v_filing_records WHERE as_of_date <= '{AS_OF}' AND product_id NOT IN ('S.L.6', 'S.L.10') GROUP BY ALL
      UNION ALL
      SELECT as_of_date, CONCAT(reporting_entity, '|', table_code, '|', product_id), SUM(reported_amount_usd)
      FROM {CATALOG}.reg_2052a.v_filing_records WHERE as_of_date <= '{AS_OF}' AND product_id NOT IN ('S.L.6', 'S.L.10')
        AND (reporting_entity, product_id) IN (SELECT reporting_entity, product_id FROM {CATALOG}.reg_2052a.v_filing_records
                                               WHERE as_of_date = '{AS_OF}' GROUP BY ALL HAVING SUM(reported_amount_usd) >= 2000)
      GROUP BY ALL"""
    spark.sql(f"CREATE OR REPLACE TEMP VIEW v_series AS {series}")
    hist = spark.sql(f"SELECT series, COUNT(*) AS n FROM v_series WHERE ds < '{AS_OF}' GROUP BY series").collect()
    eligible = [h.series for h in hist if h.n >= 4]   # ai_forecast needs a few prior business days
    spark.sql(f"DELETE FROM {CATALOG}.reg_2052a.variance WHERE as_of_date = '{AS_OF}'")
    if eligible:
        spark.createDataFrame([(x,) for x in eligible], "series STRING").createOrReplaceTempView("v_eligible")
        # ai_forecast runs on a Databricks SQL warehouse (it is not enabled for serverless notebooks in this workspace):
        # stage the history in Delta, forecast through the warehouse, read the result back.
        FIN, FOUT = f"{CATALOG}.ai_assist.forecast_input", f"{CATALOG}.ai_assist.forecast_output"
        (spark.sql(f"SELECT ds, series, CAST(y AS DOUBLE) AS y FROM v_series WHERE ds < '{AS_OF}' AND series IN (SELECT series FROM v_eligible)")
         .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(FIN))
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.service.sql import StatementState
        _w = WorkspaceClient()
        st = _w.statement_execution.execute_statement(warehouse_id=WAREHOUSE, wait_timeout="50s", statement=f"""
            CREATE OR REPLACE TABLE {FOUT} AS SELECT * FROM ai_forecast(TABLE({FIN}), horizon => date_add(DATE'{AS_OF}', 1),
              time_col => 'ds', value_col => 'y', group_col => 'series', frequency => 'D')""")   # horizon is exclusive
        while st.status.state in (StatementState.PENDING, StatementState.RUNNING):
            import time; time.sleep(5)
            st = _w.statement_execution.get_statement(st.statement_id)
        if st.status.state != StatementState.SUCCEEDED:
            raise RuntimeError(f"ai_forecast failed: {st.status.error.message if st.status.error else st.status.state}")
        spark.table(FOUT).createOrReplaceTempView("v_fc")
        spark.sql(f"""
        INSERT INTO {CATALOG}.reg_2052a.variance
        WITH cur AS (SELECT series, y FROM v_series WHERE ds = '{AS_OF}'),
        prev AS (SELECT series, MAX_BY(y, ds) AS y FROM v_series WHERE ds < '{AS_OF}' GROUP BY series),
        fc AS (SELECT series, y_forecast, y_lower, y_upper FROM v_fc WHERE CAST(ds AS DATE) = DATE'{AS_OF}'),
        npts AS (SELECT series, COUNT(*) AS n FROM v_series WHERE ds < '{AS_OF}' GROUP BY series)
        SELECT DATE'{AS_OF}', SPLIT(c.series, '[|]')[0], CASE WHEN SPLIT(c.series, '[|]')[2] = '*' THEN 'TABLE' ELSE 'PID' END,
               SPLIT(c.series, '[|]')[1], NULLIF(SPLIT(c.series, '[|]')[2], '*'), c.y, p.y, 100 * (c.y - p.y) / NULLIF(p.y, 0),
               f.y_forecast, f.y_lower, f.y_upper,
               (c.y < f.y_lower OR c.y > f.y_upper) AND ABS(c.y - p.y) > 0.03 * ABS(p.y), n.n, current_timestamp()
        FROM cur c JOIN prev p USING (series) JOIN fc f USING (series) JOIN npts n USING (series)""")
    anomalies = spark.sql(f"""SELECT * FROM {CATALOG}.reg_2052a.variance WHERE as_of_date = '{AS_OF}' AND is_anomaly
                              ORDER BY ABS(amount_usd - prior_amount_usd) DESC LIMIT 8""").collect()
    rows = []
    TABLE_NAME = {r.table_code: r.table_name for r in spark.table(f"{CATALOG}.reference.spec_tables").collect()}
    for a in anomalies:
        movers = spark.sql(f"""
          SELECT l.record_id, f.counterparty, f.maturity_bucket, f.source_system, SUM(l.amount) AS amount
          FROM {CATALOG}.reg_2052a.record_lineage l
          JOIN {CATALOG}.conformed.fact_liquidity_position f ON f.as_of_date = l.as_of_date AND f.position_id = l.position_id
          WHERE l.as_of_date = '{AS_OF}' AND l.reporting_entity = {sq(a.reporting_entity)} AND l.table_code = {sq(a.table_code)}
            {"AND f.product_id = " + sq(a.product_id) if a.product_id else ""}
          GROUP BY ALL ORDER BY amount DESC LIMIT 5""").collect()
        subject = f"{a.reporting_entity} {a.table_code}{' ' + a.product_id if a.product_id else ''}"
        out = parse_json(ai(f"""Draft FR 2052a business-review commentary for an unusual day-over-day change.
{a.table_code} is the FR 2052a table "{TABLE_NAME.get(a.table_code, a.table_code)}" - call it by that name and nothing else.
{subject}: USD {a.prior_amount_usd:,.0f}mm -> {a.amount_usd:,.0f}mm ({a.change_pct:+.1f}%); expected range from ai_forecast
USD {a.lower_usd:,.0f}mm - {a.upper_usd:,.0f}mm over {a.history_points} business days.
Largest records now: {json.dumps([dict(r.asDict(), amount=float(r.amount)) for r in movers])}
Answer only JSON: {{"commentary": "two to three sentences for the reviewer - what moved and what to verify",
"comment_text": "one sentence suitable for the FR 2052a Comments file, plain ASCII, no special characters"}}""", 400))
        if out:
            rows.append(("VARIANCE_COMMENTARY", f"{AS_OF}|{subject}", subject, {**out, "change_pct": a.change_pct, "amount_usd": a.amount_usd},
                         out.get("commentary"), "ai_forecast + ai_query", None))
            text = re.sub(r"[^\x20-\x7E]", "", out.get("comment_text", ""))   # 6G BR General #29: ASCII 32-126 only
            if text:
                rows.append(("COMMENT_DRAFT", f"{AS_OF}|{subject}", subject,
                             {"reporting_entity": a.reporting_entity, "collection": a.table_code, "product_id": a.product_id, "comments": text},
                             "Draft for the S.C Comments table; accept to include it in the Comment file", "ai_query", None))
    counts["variance"] = save(rows)
    n_var = spark.sql(f"SELECT COUNT(*) AS n, SUM(CAST(is_anomaly AS INT)) AS a FROM {CATALOG}.reg_2052a.variance WHERE as_of_date = '{AS_OF}'").first()
    print(f"variance series: {n_var.n}, anomalies: {n_var.a}; commentary / comment drafts: {counts['variance']}")

# COMMAND ----------

print(counts)
display(spark.sql(f"""SELECT suggestion_type, status, COUNT(*) AS n FROM {S} WHERE as_of_date = '{AS_OF}' GROUP BY ALL ORDER BY 1"""))
