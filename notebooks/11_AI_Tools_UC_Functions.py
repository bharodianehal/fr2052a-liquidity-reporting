# Databricks notebook source
# MAGIC %md
# MAGIC # AI tools: Unity Catalog functions for the agents (managed MCP) - v9
# MAGIC ## Owned by: Regulatory Reporting Team
# MAGIC
# MAGIC Governed, read-only SQL table functions in `ai_assist`. Databricks serves them as tools to agents through the
# MAGIC **managed UC functions MCP server** (`/api/2.0/mcp/functions/<catalog>/ai_assist`), next to the **Genie MCP server**
# MAGIC of the FR 2052a Genie space (`/api/2.0/mcp/genie/<space_id>`). MCP clients (an agent, Claude Desktop, Cursor) use these, so
# MAGIC a client can only see what Unity Catalog grants - it never gets raw table access or write access.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
CATALOG = dbutils.widgets.get("catalog")
A = f"{CATALOG}.ai_assist"

FUNCTIONS = {
"filing_status": f"""
CREATE OR REPLACE FUNCTION {A}.filing_status(as_of DATE COMMENT 'FR 2052a as-of date (business day)')
RETURNS TABLE (as_of_date DATE, run_number INT, review_status STRING, records BIGINT, positions BIGINT, validation_fails BIGINT,
               validation_warnings BIGINT, fed_psv_not_passing BIGINT, gl_breaks BIGINT, open_ai_suggestions BIGINT)
COMMENT 'FR 2052a filing status for one as-of date: latest reporting run and sign-off state, record counts, validation, Fed post-submission checks, GL breaks and open AI suggestions'
RETURN
WITH runs AS (SELECT as_of_date, MAX_BY(run_number, action_timestamp) AS run_number, MAX_BY(status, action_timestamp) AS status
              FROM {CATALOG}.reg_2052a.submission_review GROUP BY as_of_date),
recs AS (SELECT as_of_date, COUNT(*) AS records, SUM(record_count) AS positions FROM {CATALOG}.reg_2052a.v_filing_records GROUP BY as_of_date),
val AS (SELECT as_of_date, COUNT_IF(status = 'FAIL') AS fails, COUNT_IF(status = 'WARNING') AS warnings,
               COUNT_IF(rule_source = 'Fed PSV' AND status <> 'PASS') AS psv FROM {CATALOG}.reg_2052a.gold_validation GROUP BY as_of_date),
gl AS (SELECT as_of_date, COUNT_IF(status <> 'PASS') AS breaks FROM {CATALOG}.audit.gl_reconciliation GROUP BY as_of_date),
sug AS (SELECT as_of_date, COUNT_IF(status = 'PROPOSED') AS open FROM {CATALOG}.ai_assist.suggestions GROUP BY as_of_date)
SELECT recs.as_of_date, runs.run_number, runs.status, recs.records, recs.positions, val.fails, val.warnings, val.psv, gl.breaks,
       COALESCE(sug.open, 0)
FROM recs LEFT JOIN runs USING (as_of_date) LEFT JOIN val USING (as_of_date) LEFT JOIN gl USING (as_of_date) LEFT JOIN sug USING (as_of_date)
WHERE recs.as_of_date = filing_status.as_of""",

"validation_issues": f"""
CREATE OR REPLACE FUNCTION {A}.validation_issues(as_of DATE COMMENT 'FR 2052a as-of date')
RETURNS TABLE (entity_id STRING, rule_id STRING, rule_source STRING, table_code STRING, rule_name STRING, severity STRING, status STRING,
               records_failed INT, failure_details STRING, ai_explanation STRING)
COMMENT 'FR 2052a checks that did not pass on an as-of date (6G business rules, appendix rules, Fed post-submission checks) with the AI explanation if one was drafted'
RETURN
SELECT v.entity_id, v.rule_id, v.rule_source, v.table_code, v.rule_name, v.severity, v.status, v.records_failed, v.failure_details, x.rationale
FROM {CATALOG}.reg_2052a.gold_validation v
LEFT JOIN (SELECT as_of_date, subject_key, MAX_BY(rationale, created_timestamp) AS rationale FROM {CATALOG}.ai_assist.suggestions
           WHERE suggestion_type = 'RULE_EXPLANATION' GROUP BY ALL) x ON x.as_of_date = v.as_of_date AND x.subject_key = v.rule_id
WHERE v.as_of_date = validation_issues.as_of AND v.status <> 'PASS'""",

"lcr_summary": f"""
CREATE OR REPLACE FUNCTION {A}.lcr_summary(as_of DATE COMMENT 'as-of date')
RETURNS TABLE (entity_id STRING, total_hqla DECIMAL(22,4), total_outflows DECIMAL(22,4), capped_inflows DECIMAL(22,4),
               total_net_cash_outflows DECIMAL(22,4), lcr_ratio DECIMAL(10,4), lcr_compliant BOOLEAN)
COMMENT 'Liquidity Coverage Ratio (12 CFR 249) per LCR reporting entity, USD millions; the ratio is reported as FR 2052a S.L.6'
RETURN
SELECT entity_id, total_hqla, total_outflows, capped_inflows, total_net_cash_outflows, lcr_ratio, lcr_compliant
FROM {CATALOG}.reg_lcr.calculation_results WHERE as_of_date = lcr_summary.as_of""",

"variance_anomalies": f"""
CREATE OR REPLACE FUNCTION {A}.variance_anomalies(as_of DATE COMMENT 'as-of date')
RETURNS TABLE (reporting_entity STRING, table_code STRING, product_id STRING, prior_amount_usd DOUBLE, amount_usd DOUBLE, change_pct DOUBLE,
               lower_usd DOUBLE, upper_usd DOUBLE, ai_commentary STRING)
COMMENT 'Day-over-day FR 2052a movements outside the ai_forecast expected range (USD millions), with the drafted review commentary'
RETURN
SELECT v.reporting_entity, v.table_code, v.product_id, v.prior_amount_usd, v.amount_usd, v.change_pct, v.lower_usd, v.upper_usd, x.rationale
FROM {CATALOG}.reg_2052a.variance v
LEFT JOIN (SELECT subject_key, MAX_BY(rationale, created_timestamp) AS rationale FROM {CATALOG}.ai_assist.suggestions
           WHERE suggestion_type = 'VARIANCE_COMMENTARY' GROUP BY ALL) x
  ON x.subject_key = CONCAT(CAST(v.as_of_date AS STRING), '|', v.reporting_entity, ' ', v.table_code, COALESCE(CONCAT(' ', v.product_id), ''))
WHERE v.as_of_date = variance_anomalies.as_of AND v.is_anomaly""",

"record_drilldown": f"""
CREATE OR REPLACE FUNCTION {A}.record_drilldown(as_of DATE COMMENT 'as-of date', key STRING COMMENT 'record_key of a filed FR 2052a record')
RETURNS TABLE (reporting_entity STRING, table_code STRING, position_id STRING, record_id STRING, amount DECIMAL(26,8), product_id STRING,
               source_system STRING, source_product_code STRING, counterparty STRING, booking_entity STRING)
COMMENT 'Drill-down from one filed FR 2052a record to the Silver positions and source records behind it (approved adjustments show as ADJ:<id>)'
RETURN
SELECT l.reporting_entity, l.table_code, l.position_id, l.record_id, l.amount, f.product_id, f.source_system, f.source_product_code,
       f.counterparty, f.booking_entity
FROM {CATALOG}.reg_2052a.record_lineage l
LEFT JOIN {CATALOG}.conformed.fact_liquidity_position f ON f.as_of_date = l.as_of_date AND f.position_id = l.position_id
WHERE l.as_of_date = record_drilldown.as_of AND l.record_key = record_drilldown.key""",

"open_suggestions": f"""
CREATE OR REPLACE FUNCTION {A}.open_suggestions(as_of DATE COMMENT 'as-of date')
RETURNS TABLE (suggestion_id STRING, suggestion_type STRING, subject STRING, suggestion STRING, rationale STRING, confidence DOUBLE)
COMMENT 'AI suggestions awaiting a human decision in the FR 2052a workbench (customer classification, product mapping, PID exceptions, rule explanations, variance commentary, comment drafts)'
RETURN
SELECT suggestion_id, suggestion_type, subject, suggestion, rationale, confidence FROM {CATALOG}.ai_assist.suggestions
WHERE status = 'PROPOSED' AND (as_of_date = open_suggestions.as_of OR suggestion_type IN ('CUSTOMER_CLASSIFICATION', 'PRODUCT_MAPPING'))
QUALIFY ROW_NUMBER() OVER (PARTITION BY suggestion_type, subject_key ORDER BY as_of_date) = 1   -- one per customer / code""",

"pid_rule_lookup": f"""
CREATE OR REPLACE FUNCTION {A}.pid_rule_lookup(pid STRING COMMENT 'FR 2052a product ID, e.g. O.D.1')
RETURNS TABLE (product_id STRING, product_name STRING, table_name STRING, standard_product_type STRING, priority STRING, condition_sql STRING, rationale STRING)
COMMENT 'The PID derivation rules that assign one FR 2052a product ID, with the product definition'
RETURN
SELECT p.product_id, p.product_name, p.table_name, r.standard_product_type, r.priority, r.condition_sql, r.rationale
FROM {CATALOG}.reference.ref_product p LEFT JOIN {CATALOG}.reference.rules_pid_derivation r USING (product_id)
WHERE p.product_id = pid_rule_lookup.pid""",
}

for name, ddl in FUNCTIONS.items():
    spark.sql(ddl)
    print(f"  {A}.{name}")
display(spark.sql(f"SELECT * FROM {A}.filing_status(DATE'2026-02-27')"))
