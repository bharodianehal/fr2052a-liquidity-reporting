"""Build and validate the FR 2052a AI/BI (Lakeview) dashboards - one page per step of the analyst's day.

  python deploy/dashboard.py --profile <p> --catalog <c> --warehouse <id> [--dashboard main|lcr]
      builds the dashboard, runs every dataset on the SQL warehouse (validation) and writes dashboards/<name>.lvdash.json
      without the catalog in the queries; the bundle deploys it (resources/dashboards.yml sets dataset_catalog).

Every dataset queries Delta directly through the SQL warehouse, so it scales to the full position volume (no copy to
Lakebase). The app embeds the published dashboard on Today and each step page; the app keeps only the actions
(decisions, adjustments, sign-off).
"""
import argparse
import json
import pathlib
import sys
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

HERE = pathlib.Path(__file__).resolve().parent
TITLE = "FR 2052a Liquidity Reporting"
DEFAULTS = {"as_of": "2026-02-27", "entity": "ENT001", "feed": "deposits"}

# USD amount of a Silver / entity position (millions, converted)
AMT = "COALESCE(p.principal_amount, p.market_value, 0) * COALESCE(fx.rate_to_usd, 1)"
FX = "LEFT JOIN {C}.reference.ref_fx_rates fx ON fx.currency_code = p.currency"
D = "CAST(:as_of AS DATE)"
INFL_D = None   # set below: INFL with the detail alias
# LCR inflow category of each Appendix VI inflow rule (the disclosure template's inflow lines 20-27)
INFL = """CASE WHEN rule_id IN ('LCR-I10','LCR-I11','LCR-I12','LCR-I13','LCR-I14','LCR-I15','LCR-I16') THEN 'Inflows - secured lending'
            WHEN rule_id = 'LCR-I02' THEN 'Inflows - retail' WHEN rule_id IN ('LCR-I01','LCR-I03','LCR-I04','LCR-I05','LCR-I06') THEN 'Inflows - unsecured wholesale'
            ELSE 'Inflows - other (derivatives, securities, other)' END"""
INFL_D = INFL.replace("rule_id", "d.rule_id")

DATASETS = [  # (name, display name, sql, parameters)
    ("v_dates", "As-of dates", "SELECT DISTINCT CAST(as_of_date AS STRING) AS as_of FROM {C}.reg_2052a.submission_files ORDER BY 1 DESC", []),
    ("v_entities", "Reporting entities", "SELECT entity_id AS entity FROM {C}.reference.ref_reporting_entity ORDER BY 1", []),

    ("v_feeds", "Source feeds", "SELECT feed FROM VALUES ('deposits'), ('loans'), ('securities'), ('derivatives'), ('funding'), ('finance') AS t(feed)", []),

    # ---- Data by layer: the exact rows of one source feed at every layer (filters: as-of date, feed)
    ("l_counts", "Source to report - counts per step", f"""
WITH b AS (SELECT record_id FROM {{C}}.conformed.v_source_files WHERE as_of_date = {D} AND feed = :feed),
s AS (SELECT record_id FROM {{C}}.conformed.source_position WHERE as_of_date = {D} AND source_feed = :feed),
f AS (SELECT p.position_id FROM {{C}}.conformed.fact_liquidity_position p JOIN s USING (record_id) WHERE p.as_of_date = {D}),
e AS (SELECT e.position_id FROM {{C}}.conformed.entity_position e JOIN f USING (position_id) WHERE e.as_of_date = {D}),
g AS (SELECT DISTINCT l.record_key FROM {{C}}.reg_2052a.record_lineage l JOIN f USING (position_id) WHERE l.as_of_date = {D})
SELECT (SELECT COUNT(*) FROM b) AS bronze_records, (SELECT COUNT(*) FROM s) AS dq_passed,
       (SELECT COUNT(*) FROM {{C}}.dq.quarantine WHERE as_of_date = {D} AND source_feed = :feed) AS quarantined,
       (SELECT COUNT(*) FROM f) AS silver_positions, (SELECT COUNT(*) FROM e) AS entity_positions, (SELECT COUNT(*) FROM g) AS filed_records""", ["as_of", "feed"]),
    ("l_bronze", "Source to report - 1 source records as received", f"""
SELECT * EXCEPT (internal_rating, as_of_date) FROM (
  SELECT 'deposits' AS feed, * FROM {{C}}.raw.deposits UNION ALL SELECT 'loans', * FROM {{C}}.raw.loans
  UNION ALL SELECT 'securities', * FROM {{C}}.raw.securities UNION ALL SELECT 'derivatives', * FROM {{C}}.raw.derivatives
  UNION ALL SELECT 'funding', * FROM {{C}}.raw.funding UNION ALL SELECT 'finance', * FROM {{C}}.raw.finance)
WHERE as_of_date = {D} AND feed = :feed ORDER BY record_id""", ["as_of", "feed"]),
    ("l_dq", "Source to report - 2 data quality check", f"""
WITH r AS (SELECT record_id, ARRAY_JOIN(ARRAY_SORT(COLLECT_SET(rule_id)), ', ') AS rules_failed FROM {{C}}.dq.rule_failures
           WHERE as_of_date = {D} AND source_feed = :feed GROUP BY 1)
SELECT b.record_id, CASE WHEN q.record_id IS NOT NULL THEN 'QUARANTINED' ELSE 'PASSED' END AS dq_result,
       COALESCE(q.failed_rules, r.rules_failed) AS rules_failed, b.landing_file, b.ingested_at,
       s.source_product_code, s.customer_id, s.currency, s.principal_amount, s.market_value, s.dq_timestamp
FROM {{C}}.conformed.v_source_files b
LEFT JOIN {{C}}.conformed.source_position s ON s.as_of_date = b.as_of_date AND s.record_id = b.record_id
LEFT JOIN {{C}}.dq.quarantine q ON q.as_of_date = b.as_of_date AND q.record_id = b.record_id
LEFT JOIN r ON r.record_id = b.record_id
WHERE b.as_of_date = {D} AND b.feed = :feed ORDER BY dq_result DESC, b.record_id""", ["as_of", "feed"]),
    ("l_silver", "Source to report - 3 enriched positions", f"""
SELECT p.record_id, p.position_id, p.part, p.booking_entity, p.source_product_code, p.standard_product_type, p.pid_rule_id, p.product_id,
       p.table_code, p.customer_id, p.counterparty, p.counterparty_category, p.gsib, p.collateral_class, p.collateral_basis,
       p.maturity_date, p.maturity_basis, p.maturity_bucket, p.insured, p.insured_basis, p.currency,
       COALESCE(p.principal_amount, p.market_value) AS amount, p.lendable_value, p.lendable_basis, p.risk_weight, p.business_line
FROM {{C}}.conformed.fact_liquidity_position p
JOIN {{C}}.conformed.source_position s ON s.as_of_date = p.as_of_date AND s.record_id = p.record_id
WHERE p.as_of_date = {D} AND s.source_feed = :feed ORDER BY p.position_id""", ["as_of", "feed"]),
    ("l_entity", "Source to report - 4 positions by reporting entity", f"""
SELECT e.reporting_entity, e.position_id, e.relationship, e.internal, e.internal_counterparty, p.product_id, COALESCE(p.principal_amount, p.market_value) AS amount
FROM {{C}}.conformed.entity_position e
JOIN {{C}}.conformed.fact_liquidity_position p ON p.as_of_date = e.as_of_date AND p.position_id = e.position_id
JOIN {{C}}.conformed.source_position s ON s.as_of_date = p.as_of_date AND s.record_id = p.record_id
WHERE e.as_of_date = {D} AND s.source_feed = :feed ORDER BY e.position_id, e.reporting_entity""", ["as_of", "feed"]),
    ("l_gold", "Source to report - 5 reported FR 2052a records", f"""
WITH pos AS (SELECT l.record_key, COUNT(*) AS positions_from_feed, SUM(l.amount) AS amount_from_feed
             FROM {{C}}.reg_2052a.record_lineage l
             JOIN {{C}}.conformed.fact_liquidity_position p ON p.as_of_date = l.as_of_date AND p.position_id = l.position_id
             JOIN {{C}}.conformed.source_position s ON s.as_of_date = p.as_of_date AND s.record_id = p.record_id
             WHERE l.as_of_date = {D} AND s.source_feed = :feed GROUP BY 1)
SELECT v.reporting_entity, v.table_code, v.product_id, v.counterparty, v.collateral_class, v.maturity_bucket, v.currency, v.converted,
       v.reported_amount, v.record_count AS positions_in_record, pos.positions_from_feed, pos.amount_from_feed, v.record_key
FROM pos JOIN {{C}}.reg_2052a.v_filing_records v ON v.as_of_date = {D} AND v.record_key = pos.record_key
ORDER BY v.reporting_entity, v.table_code, v.product_id""", ["as_of", "feed"]),

    ("v_lcr_entities", "LCR reporting entities", "SELECT DISTINCT entity_id AS entity FROM {C}.reg_lcr.calculation_results ORDER BY 1", []),

    # ---- LCR module (its own dashboard): the ratio and its components today, then each one day over day
    ("m_kpi", "LCR - the day", f"""
SELECT lcr_ratio, total_hqla * 1e6 AS hqla, total_outflows * 1e6 AS outflows, capped_inflows * 1e6 AS inflows, total_net_cash_outflows * 1e6 AS nco
FROM {{C}}.reg_lcr.calculation_results WHERE as_of_date = {D} AND entity_id = :entity""", ["as_of", "entity"]),
    ("m_lcr_trend", "LCR - by day against the 100% minimum", """
SELECT as_of_date, 'LCR' AS series, lcr_ratio * 100 AS lcr_pct FROM {C}.reg_lcr.calculation_results WHERE entity_id = :entity
UNION ALL SELECT DISTINCT as_of_date, 'Regulatory minimum (100%)', 100.0 FROM {C}.reg_lcr.calculation_results ORDER BY 1""", ["entity"]),
    ("m_hqla_nco", "LCR - HQLA and total net cash outflows by day", """
SELECT as_of_date, measure, usd_bn FROM {C}.reg_lcr.calculation_results
LATERAL VIEW STACK(2, 'HQLA', CAST(total_hqla / 1000 AS DOUBLE), 'Net cash outflows (30 days)', CAST(total_net_cash_outflows / 1000 AS DOUBLE)) s AS measure, usd_bn
WHERE entity_id = :entity ORDER BY 1""", ["entity"]),
    ("m_hqla_days", "LCR - HQLA by level and day", """
SELECT as_of_date, component, usd_bn FROM {C}.reg_lcr.calculation_results
LATERAL VIEW STACK(3, 'Level 1', CAST(level1_hqla / 1000 AS DOUBLE), 'Level 2A (after 15% haircut)', CAST(level2a_hqla_adjusted / 1000 AS DOUBLE),
  'Level 2B (after 50% haircut)', CAST(level2b_hqla_adjusted / 1000 AS DOUBLE)) s AS component, usd_bn
WHERE entity_id = :entity ORDER BY 1""", ["entity"]),
    ("m_nco_days", "LCR - net cash outflows: cash outflows and cash inflows by day", """
SELECT as_of_date, measure, usd_bn FROM {C}.reg_lcr.calculation_results
LATERAL VIEW STACK(3, 'Cash outflows', CAST(total_outflows / 1000 AS DOUBLE), 'Less cash inflows counted', CAST(capped_inflows / 1000 AS DOUBLE),
  'Net cash outflows (30 days)', CAST(total_net_cash_outflows / 1000 AS DOUBLE)) s AS measure, usd_bn
WHERE entity_id = :entity ORDER BY 1""", ["entity"]),

    ("m_out_days", "LCR - cash outflows by category and day", """
SELECT as_of_date, component, usd_bn FROM {C}.reg_lcr.calculation_results
LATERAL VIEW STACK(6, 'Outflows - retail deposits', CAST(retail_deposit_outflows / 1000 AS DOUBLE), 'Outflows - unsecured wholesale', CAST(wholesale_unsecured_outflows / 1000 AS DOUBLE),
  'Outflows - secured funding', CAST(secured_funding_outflows / 1000 AS DOUBLE), 'Outflows - derivatives and collateral', CAST(derivative_outflows / 1000 AS DOUBLE),
  'Outflows - credit and liquidity facilities', CAST(commitment_outflows / 1000 AS DOUBLE), 'Outflows - other', CAST(other_outflows / 1000 AS DOUBLE)) s AS component, usd_bn
WHERE entity_id = :entity ORDER BY 1""", ["entity"]),
    ("m_in_days", "LCR - cash inflows by category and day", f"""
SELECT as_of_date, {INFL} AS component, CAST(SUM(weighted_amount_usd) / 1000 AS DOUBLE) AS usd_bn FROM {{C}}.reg_lcr.calculation_detail
WHERE entity_id = :entity AND flow_direction = 'INFLOW' GROUP BY 1, 2 ORDER BY 1""", ["entity"]),
    ("m_inputs", "LCR - the input data of the day", f"""
WITH d AS (SELECT d.*, CASE
             WHEN d.flow_direction = 'HQLA' THEN CONCAT('HQLA - ', d.hqla_level)
             WHEN d.flow_direction = 'HQLA_EXCLUDED' THEN 'HQLA - less: not transferable from subsidiaries'
             WHEN d.flow_direction = 'OUTFLOW' THEN CASE WHEN d.product_id LIKE 'O.D.%' AND f.counterparty_category = 'Retail' THEN 'Outflows - retail deposits'
                 WHEN d.product_id LIKE 'O.W.%' OR d.product_id LIKE 'O.D.%' THEN 'Outflows - unsecured wholesale'
                 WHEN d.product_id LIKE 'O.S.%' THEN 'Outflows - secured funding'
                 WHEN d.product_id IN ('O.O.1', 'O.O.2', 'O.O.8', 'O.O.20') THEN 'Outflows - derivatives and collateral'
                 WHEN d.product_id IN ('O.O.4', 'O.O.5', 'O.O.6') THEN 'Outflows - credit and liquidity facilities' ELSE 'Outflows - other' END
             ELSE {INFL_D} END AS component
           FROM {{C}}.reg_lcr.calculation_detail d
           LEFT JOIN {{C}}.conformed.fact_liquidity_position f ON f.as_of_date = d.as_of_date AND f.position_id = d.record_id
           WHERE d.as_of_date = {D} AND d.entity_id = :entity),
g AS (SELECT component, COUNT(*) AS positions, SUM(amount_usd) AS balance, SUM(weighted_amount_usd) AS weighted FROM d GROUP BY 1),
r AS (SELECT * FROM {{C}}.reg_lcr.calculation_results WHERE as_of_date = {D} AND entity_id = :entity),
t AS (SELECT CASE WHEN component LIKE 'HQLA%' THEN 'HQLA' WHEN component LIKE 'Outflows%' THEN 'OUT' ELSE 'IN' END AS grp,
             SUM(positions) AS positions, SUM(balance) AS balance FROM g
      WHERE component NOT LIKE '%not transferable%' GROUP BY 1),   -- HQLA balance: the eligible assets of the three levels
lines AS (
  SELECT CASE component WHEN 'HQLA - Level 1' THEN 2 WHEN 'HQLA - Level 2A' THEN 3 WHEN 'HQLA - Level 2B' THEN 4 ELSE 5 END AS seq, CONCAT('   ', component) AS component,
         positions, balance AS balance_usd_mm,
         CASE WHEN component = 'HQLA - Level 2A' THEN 0.85 WHEN component = 'HQLA - Level 2B' THEN 0.50 ELSE 1.0 END AS rate,
         CASE WHEN component = 'HQLA - Level 2A' THEN balance * 0.85 WHEN component = 'HQLA - Level 2B' THEN balance * 0.5
              WHEN component LIKE '%not transferable%' THEN -balance ELSE balance END AS weighted_usd_mm
  FROM g WHERE component LIKE 'HQLA%'
  UNION ALL SELECT 1, 'HQLA (after haircuts and caps)', t.positions, t.balance, r.total_hqla / t.balance, r.total_hqla FROM t, r WHERE t.grp = 'HQLA'
  UNION ALL SELECT 10, 'Cash outflows (30 days)', t.positions, t.balance, r.total_outflows / t.balance, r.total_outflows FROM t, r WHERE t.grp = 'OUT'
  UNION ALL SELECT 10 + ROW_NUMBER() OVER (ORDER BY weighted DESC), CONCAT('   ', component), positions, balance, weighted / NULLIF(balance, 0), weighted
            FROM g WHERE component LIKE 'Outflows%'
  UNION ALL SELECT 20, 'Cash inflows (30 days)', t.positions, t.balance, r.total_inflows / t.balance, r.total_inflows FROM t, r WHERE t.grp = 'IN'
  UNION ALL SELECT 20 + ROW_NUMBER() OVER (ORDER BY weighted DESC), CONCAT('   ', component), positions, balance, weighted / NULLIF(balance, 0), weighted
            FROM g WHERE component LIKE 'Inflows%'
  UNION ALL SELECT 30, 'Cash inflows counted (cap 75% of outflows)', NULL, NULL, NULL, r.capped_inflows FROM r
  UNION ALL SELECT 31, 'Maturity mismatch add-on', NULL, NULL, NULL, r.maturity_mismatch_add_on FROM r
  UNION ALL SELECT 32, 'Net cash outflows (30 days)', NULL, NULL, NULL, r.total_net_cash_outflows FROM r)
SELECT seq, component, COALESCE(FORMAT_NUMBER(positions, 0), '') AS positions, COALESCE(FORMAT_NUMBER(balance_usd_mm, 1), '') AS balance_usd_mm,
       COALESCE(CONCAT(FORMAT_NUMBER(rate * 100, 1), '%'), '') AS rate, COALESCE(FORMAT_NUMBER(weighted_usd_mm, 1), '') AS weighted_usd_mm
FROM lines ORDER BY seq""", ["as_of", "entity"]),

    # ---- 2 Data: do I have all of it (completeness) and is it right (accuracy) - BCBS 239 principles 3 and 4
    ("c_kpi", "Data - completeness and accuracy of the day", f"""
SELECT (SELECT COUNT_IF(status = 'PASS') FROM {{C}}.dq.feed_monitor WHERE as_of_date = {D}) AS feeds_complete,
       (SELECT SUM(records) / SUM(expected_records) FROM {{C}}.dq.feed_monitor WHERE as_of_date = {D}) AS volume_vs_expected,
       (SELECT COUNT(*) FROM {{C}}.dq.quarantine WHERE as_of_date = {D}) AS records_rejected,
       (SELECT COUNT_IF(status <> 'PASS') FROM {{C}}.audit.gl_reconciliation WHERE as_of_date = {D})
       + (SELECT COUNT_IF(status <> 'PASS') FROM {{C}}.audit.cross_metric_recon WHERE as_of_date = {D}) AS recon_breaks""", ["as_of"]),
    ("c_feeds", "Data - records received vs expected, per source feed", f"""
SELECT feed, measure, n AS records FROM {{C}}.dq.feed_monitor
LATERAL VIEW STACK(2, 'Received', CAST(records AS DOUBLE), 'Expected (5-day median)', CAST(expected_records AS DOUBLE)) s AS measure, n
WHERE as_of_date = {D} ORDER BY feed""", ["as_of"]),
    ("c_issues", "Data - issues to act on", f"""
SELECT 'Completeness' AS dimension, 'Source feed incomplete' AS issue, feed AS item, details AS detail, 'Chase the source system, then re-run' AS action
FROM {{C}}.dq.feed_monitor WHERE as_of_date = {D} AND status <> 'PASS'
UNION ALL
SELECT 'Accuracy', 'Record rejected by a data quality rule', q.record_id, CONCAT(q.source_feed, ': ', q.failed_rules),
       COALESCE(CONCAT('Fixed in the app: ', x.fix), 'Fix, map or exclude it in step 2 Data quality')
FROM {{C}}.dq.quarantine q
LEFT JOIN (SELECT as_of_date, record_id, MAX_BY(CONCAT(field, ' -> ', new_value, ' (', status, ')'), created_at) AS fix FROM {{C}}.dq.record_fixes
           WHERE status <> 'WITHDRAWN' GROUP BY 1, 2) x ON x.as_of_date = q.as_of_date AND x.record_id = q.record_id
WHERE q.as_of_date = {D}
UNION ALL
SELECT 'Accuracy', 'General ledger does not tie', recon_type, CONCAT('GL ', ROUND(gl_total, 1), ' vs filing ', ROUND(pipeline_total, 1), ' USD mm (', difference_pct, '%)'),
       'Explain or fix it in step 4 Validate (RECON-GL)'
FROM {{C}}.audit.gl_reconciliation WHERE as_of_date = {D} AND status <> 'PASS'
UNION ALL
SELECT 'Accuracy', 'FR 2052a does not tie to the LCR', CONCAT(entity_id, ' ', metric_name), CONCAT('LCR ', reg_lcr_value, ' vs filing ', reg_2052a_value),
       'Blocks the filing - investigate'
FROM {{C}}.audit.cross_metric_recon WHERE as_of_date = {D} AND status <> 'PASS'""", ["as_of"]),

    # ---- 3 Rules: did every record get its FR 2052a product (PID) by a rule - what has none, and why
    ("r_kpi", "Rules - coverage of the day", f"""
SELECT s.derived / (s.positions + COALESCE(h.n, 0)) AS classified_pct, COALESCE(h.n, 0) AS without_rule, COALESCE(h.usd, 0) * 1e6 AS without_rule_usd,
       (SELECT COUNT(*) FROM {{C}}.ai_assist.suggestions WHERE status = 'PROPOSED' AND suggestion_type IN ('CUSTOMER_CLASSIFICATION', 'PRODUCT_MAPPING')
          AND as_of_date <= {D}
          AND subject_key NOT IN (SELECT customer_id FROM {{C}}.reference.customer_master_approvals)
          AND subject_key NOT IN (SELECT source_product_code FROM {{C}}.reference.source_product_map_approvals)) AS awaiting_master_data
FROM {{C}}.audit.pid_derivation_summary s
LEFT JOIN (SELECT as_of_date, COUNT(*) AS n, SUM(amount_usd) AS usd FROM {{C}}.dq.pid_exceptions GROUP BY 1) h USING (as_of_date)
WHERE s.as_of_date = {D}""", ["as_of"]),
    ("r_by_table", "Rules - positions classified by a rule vs without one, per FR 2052a table", f"""
SELECT table_code, 'Classified by a PID rule' AS outcome, COUNT(*) AS positions FROM {{C}}.conformed.fact_liquidity_position WHERE as_of_date = {D} GROUP BY 1, 2
UNION ALL
SELECT COALESCE(REGEXP_EXTRACT(provisional_product_id, '^([A-Z]+\\\\.[A-Z]+)', 1), 'unknown'), 'No rule / missing master data', COUNT(*)
FROM {{C}}.dq.pid_exceptions WHERE as_of_date = {D} GROUP BY 1, 2""", ["as_of"]),
    ("r_gaps", "Rules - records without a rule, and what is missing", f"""
SELECT e.record_id AS item, CASE e.exception_type WHEN 'CUSTOMER_PENDING' THEN 'Customer not classified yet' WHEN 'NO_RULE' THEN 'No PID rule matches'
       ELSE e.exception_type END AS gap, e.source_system, e.source_product_code, e.customer_id, e.provisional_product_id, e.amount_usd, e.reason,
       CASE WHEN e.exception_type = 'CUSTOMER_PENDING' AND a.approved_on IS NOT NULL
              THEN CONCAT('Approved from ', a.approved_on, ' - re-run this day to include it, or leave it out')
            WHEN e.exception_type = 'CUSTOMER_PENDING' THEN 'Approve the customer in step 3 PID enrichment' ELSE 'Add or extend a PID rule' END AS action
FROM {{C}}.dq.pid_exceptions e LEFT JOIN {{C}}.reference.customer_master_approvals a ON a.customer_id = e.customer_id
WHERE e.as_of_date = {D}
UNION ALL
SELECT q.record_id, 'Bank product code not in the catalogue', get_json_object(q.record_json, '$.source_system'), q.source_product_code,
       get_json_object(q.record_json, '$.customer_id'), NULL, NULL, 'New product code - the record cannot be classified',
       CASE WHEN m.source_product_code IS NOT NULL THEN CONCAT('Mapped to ', m.standard_product_type, ' - re-run to classify') ELSE 'Map the code in step 2 Data quality' END
FROM {{C}}.dq.quarantine q LEFT JOIN {{C}}.reference.source_product_map_approvals m ON m.source_product_code = q.source_product_code
WHERE q.as_of_date = {D} AND q.failed_rules LIKE '%DQ_006%'
UNION ALL
SELECT s.subject_key, CASE s.suggestion_type WHEN 'CUSTOMER_CLASSIFICATION' THEN 'New customer awaiting approval' ELSE 'New product code awaiting mapping' END,
       NULL, NULL, NULL, NULL, NULL, s.subject, 'Accept or edit the AI suggestion in step 3 PID enrichment'
FROM {{C}}.ai_assist.suggestions s WHERE s.status = 'PROPOSED' AND s.suggestion_type IN ('CUSTOMER_CLASSIFICATION', 'PRODUCT_MAPPING') AND s.as_of_date <= {D}
  AND s.subject_key NOT IN (SELECT customer_id FROM {{C}}.reference.customer_master_approvals)
  AND s.subject_key NOT IN (SELECT source_product_code FROM {{C}}.reference.source_product_map_approvals)""", ["as_of"]),

    # ---- 4 Validation: did today's report pass every check
    ("x_kpi", "Validation - result of the day", f"""
WITH v AS (SELECT COUNT(*) AS checks, COUNT_IF(status IN ('PASS', 'NOT_APPLICABLE')) AS passed, COUNT_IF(status = 'FAIL') AS failed
           FROM {{C}}.reg_2052a.gold_validation WHERE as_of_date = {D}),
items AS (SELECT DISTINCT d.rule_id, COALESCE(d.record_key, NULLIF(REGEXP_EXTRACT(d.failure_detail, '([A-Z]{{3}}-[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}-[A-Z0-9]+#[A-Z0-9]+)', 1), ''),
                      CONCAT(d.table_code, '|', COALESCE(d.product_id, 'None'), '|', SUBSTR(COALESCE(d.failure_detail, ''), 1, 80))) AS item_key
          FROM {{C}}.reg_2052a.gold_validation_detail d JOIN {{C}}.reg_2052a.gold_validation g
            ON g.as_of_date = d.as_of_date AND g.rule_id = d.rule_id AND g.status = 'WARNING' WHERE d.as_of_date = {D}),
open AS (SELECT COUNT(*) AS n FROM items i LEFT ANTI JOIN {{C}}.reg_2052a.validation_decisions x
         ON x.as_of_date = {D} AND x.rule_id = i.rule_id AND x.item_key = i.item_key AND x.status <> 'WITHDRAWN'),
f AS (SELECT COUNT_IF(xsd_valid) / COUNT(*) AS xsd_valid FROM {{C}}.reg_2052a.submission_files
      WHERE as_of_date = {D} AND run_number = (SELECT MAX(run_number) FROM {{C}}.reg_2052a.submission_files WHERE as_of_date = {D}))
SELECT v.passed / v.checks AS passed_pct, v.failed, open.n AS warnings_open, f.xsd_valid FROM v, open, f""", ["as_of"]),
    ("x_by_source", "Validation - checks by source and result", f"""
SELECT CASE rule_source WHEN 'Fed PSV' THEN 'Fed post-submission checks' WHEN 'Instructions' THEN 'FR 2052a Instructions'
            WHEN '6G BR' THEN 'Fed 6G business rules' WHEN '6G BR General' THEN 'Fed 6G file rules' WHEN '6G XSD' THEN 'Fed 6G schema (XSD)'
            ELSE rule_source END AS source,
       CASE WHEN status IN ('PASS', 'NOT_APPLICABLE') THEN 'Passed' WHEN status = 'WARNING' THEN 'Warning' ELSE 'Failed' END AS result, COUNT(*) AS checks
FROM {{C}}.reg_2052a.gold_validation WHERE as_of_date = {D} GROUP BY ALL""", ["as_of"]),
    ("x_issues", "Validation - checks not passing today and where each stands", f"""
WITH items AS (SELECT DISTINCT d.rule_id, COALESCE(d.record_key, NULLIF(REGEXP_EXTRACT(d.failure_detail, '([A-Z]{{3}}-[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}-[A-Z0-9]+#[A-Z0-9]+)', 1), ''),
                      CONCAT(d.table_code, '|', COALESCE(d.product_id, 'None'), '|', SUBSTR(COALESCE(d.failure_detail, ''), 1, 80))) AS item_key FROM {{C}}.reg_2052a.gold_validation_detail d WHERE d.as_of_date = {D}),
st AS (SELECT i.rule_id, COUNT(*) AS exceptions, COUNT(x.item_key) AS resolved
       FROM items i LEFT JOIN (SELECT DISTINCT rule_id, item_key FROM {{C}}.reg_2052a.validation_decisions WHERE as_of_date = {D} AND status <> 'WITHDRAWN') x
         USING (rule_id, item_key) GROUP BY 1)
SELECT v.rule_id, v.rule_name, v.rule_source, v.severity, CASE v.status WHEN 'FAIL' THEN 'Failed' ELSE 'Warning' END AS result,
       COALESCE(st.exceptions, v.records_failed) AS exceptions, COALESCE(st.resolved, 0) AS resolved,
       COALESCE(st.exceptions, v.records_failed) - COALESCE(st.resolved, 0) AS still_open,
       CASE WHEN COALESCE(st.exceptions, v.records_failed) - COALESCE(st.resolved, 0) = 0 THEN 'Resolved - nothing to do'
            WHEN v.status = 'FAIL' THEN 'Blocks the filing - correct in step 4 Validate' ELSE 'Explain or fix in step 4 Validate' END AS action
FROM {{C}}.reg_2052a.gold_validation v LEFT JOIN st USING (rule_id)
WHERE v.as_of_date = {D} AND v.status IN ('FAIL', 'WARNING') ORDER BY v.status, still_open DESC""", ["as_of"]),

    # ---- 3 The FR 2052a as the Federal Reserve prescribes it: section -> table -> PID -> reported record -> positions
    ("p_tables", "Report - tables", f"""
SELECT t.section, v.table_code, t.table_name, COUNT(*) AS records, SUM(v.record_count) AS positions,
       SUM(CASE WHEN v.product_id IN ('S.L.6', 'S.L.10') THEN 0 ELSE v.reported_amount_usd END) AS usd_mm
FROM {{C}}.reg_2052a.v_filing_records v JOIN {{C}}.reference.spec_tables t USING (table_code)
WHERE v.as_of_date = {D} AND v.reporting_entity = :entity GROUP BY ALL ORDER BY v.table_code""", ["as_of", "entity"]),
    ("p_records", "Report - reported records", f"""
SELECT t.section, v.table_code, v.product_id, pr.product_name, COALESCE(v.sub_product, '') AS sub_product, COALESCE(v.counterparty, '') AS counterparty,
       COALESCE(v.collateral_class, '') AS collateral_class, v.maturity_bucket, v.currency,
       v.converted, v.reported_amount, v.reported_amount_usd, v.record_count AS positions, v.validation_status, v.record_key
FROM {{C}}.reg_2052a.v_filing_records v JOIN {{C}}.reference.spec_tables t USING (table_code)
LEFT JOIN {{C}}.reference.ref_product pr ON pr.product_id = v.product_id
WHERE v.as_of_date = {D} AND v.reporting_entity = :entity ORDER BY v.table_code, v.product_id, v.reported_amount_usd DESC""", ["as_of", "entity"]),
    ("p_positions", "Report - positions behind each record", f"""
SELECT t.section, l.table_code, p.product_id, l.record_key, l.position_id, p.record_id, p.source_system, p.source_product_code, p.booking_entity,
       COALESCE(p.customer_id, '') AS customer_id, COALESCE(p.counterparty, '') AS counterparty, COALESCE(p.collateral_class, '') AS collateral_class,
       p.maturity_date, p.maturity_bucket, p.currency, l.amount, p.pid_rule_id
FROM {{C}}.reg_2052a.record_lineage l JOIN {{C}}.reference.spec_tables t USING (table_code)
JOIN {{C}}.conformed.fact_liquidity_position p ON p.as_of_date = l.as_of_date AND p.position_id = l.position_id
WHERE l.as_of_date = {D} AND l.reporting_entity = :entity ORDER BY l.table_code, p.product_id, l.record_key""", ["as_of", "entity"]),

    # ---- 5 Every adjustment made in the app: who changed what, when, why, and where it stands
    ("a_log", "Adjustments - audit trail", f"""
SELECT as_of_date, adjustment_type, subject, COALESCE(field, '') AS field, COALESCE(old_value, '') AS old_value, COALESCE(new_value, '') AS new_value,
       COALESCE(note, '') AS note, made_by, made_at, status FROM (
  SELECT as_of_date, 'Data quality fix' AS adjustment_type, record_id AS subject,
         CASE field WHEN '_map_code' THEN 'product code mapped' WHEN '_exclude' THEN 'record excluded' ELSE field END AS field,
         old_value, new_value, reason AS note, preparer AS made_by, created_at AS made_at, status FROM {{C}}.dq.record_fixes
  UNION ALL SELECT as_of_date, 'Position correction', position_id, field, old_value, new_value, reason, preparer, created_at, status FROM {{C}}.reg_2052a.position_corrections
  UNION ALL SELECT as_of_date, 'Reported amount adjustment', record_key, column_name, NULL, CAST(amount AS STRING), reason, preparer, created_at, status FROM {{C}}.reg_2052a.adjustments
  UNION ALL SELECT approved_on, 'New customer approved', customer_id, 'counterparty', NULL, counterparty, customer_name, approved_by, decided_at, 'APPROVED' FROM {{C}}.reference.customer_master_approvals
  UNION ALL SELECT approved_on, 'New product code mapped', source_product_code, 'standard product type', NULL, standard_product_type, description, approved_by, decided_at, 'APPROVED'
            FROM {{C}}.reference.source_product_map_approvals
  UNION ALL SELECT as_of_date, CASE WHEN suggestion_type IN ('COMMENT_DRAFT', 'VARIANCE_COMMENTARY') THEN 'Comment for the Fed' ELSE 'PID exception' END,
            subject_key, LOWER(REPLACE(suggestion_type, '_', ' ')), NULL, NULL, subject, decided_by, decided_at, status
            FROM {{C}}.ai_assist.suggestions WHERE status <> 'PROPOSED' AND suggestion_type IN ('COMMENT_DRAFT', 'VARIANCE_COMMENTARY', 'PID_EXCEPTION')
  UNION ALL SELECT as_of_date, CASE WHEN action = 'explain' THEN 'Validation exception explained' ELSE 'Validation exception corrected' END,
            item_key, rule_id, NULL, NULL, note, decided_by, decided_at, status FROM {{C}}.reg_2052a.validation_decisions
  UNION ALL SELECT as_of_date, 'Sign-off', CONCAT('run ', run_number, ' v', version), LOWER(REPLACE(action, '_', ' ')), NULL, status, note, actor, action_timestamp, status
            FROM {{C}}.reg_2052a.submission_review WHERE action <> 'GENERATED')
WHERE as_of_date = {D} ORDER BY made_at DESC""", ["as_of"]),
]


def sql_lines(text, catalog):
    return [ln + "\n" for ln in text.replace("{C}", f"`{catalog}`").strip().splitlines()]


def param_spec(name):
    return {"keyword": name, "displayName": name, "dataType": "STRING",
            "defaultSelection": {"values": {"dataType": "STRING", "values": [{"value": DEFAULTS[name]}]}}}


def pos(x, y, w, h):
    return {"x": x, "y": y, "width": w, "height": h}


def text(name, lines, x, y, w, h):
    return {"widget": {"name": name, "multilineTextboxSpec": {"lines": lines}}, "position": pos(x, y, w, h)}


NUM = {"type": "number-plain", "abbreviation": "compact"}
PCT = {"type": "number-percent", "decimalPlaces": {"type": "exact", "places": 1}}


def counter(name, ds, field, title, fmt, x, y, w=2, h=3):
    return {"widget": {"name": name, "queries": [{"name": "main_query", "query": {"datasetName": ds,
            "fields": [{"name": field, "expression": f"`{field}`"}], "disaggregated": True}}],
            "spec": {"version": 2, "widgetType": "counter", "encodings": {"value": {"fieldName": field, "displayName": title, "format": fmt}},
                     "frame": {"showTitle": True, "title": title}}}, "position": pos(x, y, w, h)}


RIGHT = {"positions", "balance_usd_mm", "rate", "weighted_usd_mm"}   # text-formatted numbers, aligned like numbers


def table(name, ds, cols, title, x, y, w, h, description=None):
    frame = {"showTitle": True, "title": title}
    if description:
        frame.update(showDescription=True, description=description)
    return {"widget": {"name": name, "queries": [{"name": "main_query", "query": {"datasetName": ds,
            "fields": [{"name": c, "expression": f"`{c}`"} for c, _ in cols], "disaggregated": True}}],
            "spec": {"version": 2, "widgetType": "table", "encodings": {"columns": [{"fieldName": c, "displayName": d, **({"alignContent": "right"} if ds == "m_inputs" and c in RIGHT else {})}
                                                                          for c, d in cols]},
                     "frame": frame}}, "position": pos(x, y, w, h)}


LABEL = {"_source_file": "Source file", "_ingested_at": "Received at", "load_timestamp": "Extracted at", "record_id": "Record",
         "source_system": "Source system", "source_product_code": "Bank product code", "customer_id": "Customer", "collateral_id": "Collateral id",
         "booking_entity": "Booking entity", "report_for_entity": "Report for entity", "principal_amount": "Principal", "market_value": "Market value",
         "feed": "Feed", "risk_weight": "Risk weight %", "link_id": "Collateral link"}


def table_all(name, ds, title, x, y, w, h):
    """A table that shows every column of its dataset (SELECT *): the columns are listed at build time from the warehouse."""
    return {"_all_columns": True, "widget": {"name": name, "queries": [{"name": "main_query", "query": {"datasetName": ds, "fields": [],
            "disaggregated": True}}], "spec": {"version": 2, "widgetType": "table", "encodings": {"columns": []}, "frame": {"showTitle": True, "title": title}}},
            "position": pos(x, y, w, h)}


LCR_COLORS = {"Outflows - retail deposits": "#7A1F2B", "Outflows - unsecured wholesale": "#D1495B", "Outflows - secured funding": "#F2A541",
              "Outflows - derivatives and collateral": "#8E6C8A", "Outflows - credit and liquidity facilities": "#C8B273", "Outflows - other": "#A3B4C4",
              "Inflows - secured lending": "#2E7D5B", "Inflows - unsecured wholesale": "#5BB5A2", "Inflows - retail": "#9ED9C5",
              "Inflows - other (derivatives, securities, other)": "#C8E6DA",
              "LCR": "#0B2545", "Regulatory minimum (100%)": "#D1495B", "HQLA": "#0B2545", "Net cash outflows (30 days)": "#D1495B",
              "Level 1": "#0B2545", "Level 2A (after 15% haircut)": "#2F7FB8", "Level 2B (after 50% haircut)": "#8ACAFF",
              "Cash outflows": "#F2A541", "Less cash inflows counted": "#5BB5A2"}


def chart(name, ds, wtype, x_field, y_field, title, x, y, w, h, color=None, agg="SUM", stacked=False, xtype="categorical", ytitle="USD mm", grouped=False, colors=None):
    yname = f"{agg.lower()}({y_field})"
    fields = [{"name": x_field, "expression": f"`{x_field}`"}, {"name": yname, "expression": f"{agg}(`{y_field}`)"}]
    enc = {"x": {"fieldName": x_field, "scale": {"type": xtype}, "displayName": x_field.replace("_", " ")},
           "y": {"fieldName": yname, "scale": {"type": "quantitative"}, "displayName": ytitle}}
    if color:
        fields.append({"name": color, "expression": f"`{color}`"})
        enc["color"] = {"fieldName": color, "scale": {"type": "categorical"}, "displayName": color.replace("_", " ")}
        if colors:
            enc["color"]["scale"]["mappings"] = [{"value": k, "color": v} for k, v in colors.items()]
    spec = {"version": 3, "widgetType": wtype, "encodings": enc, "frame": {"showTitle": True, "title": title}}
    if stacked or grouped:
        spec["mark"] = {"layout": "stack" if stacked else "group"}
    return {"widget": {"name": name, "queries": [{"name": "main_query", "query": {"datasetName": ds, "fields": fields, "disaggregated": False}}],
            "spec": spec}, "position": pos(x, y, w, h)}


def flt(name, title, values_ds, field, param, datasets, x, y, w=3, h=2):
    queries = [{"name": f"{name}_values", "query": {"datasetName": values_ds, "fields": [{"name": field, "expression": f"`{field}`"}],
                                                    "disaggregated": False}}]
    fields = [{"fieldName": field, "displayName": title, "queryName": f"{name}_values"}]
    for ds in datasets:
        queries.append({"name": f"{name}_{ds}", "query": {"datasetName": ds, "parameters": [{"name": param, "keyword": param}], "disaggregated": False}})
        fields.append({"parameterName": param, "queryName": f"{name}_{ds}"})
    return {"widget": {"name": name, "queries": queries, "spec": {"version": 2, "widgetType": "filter-single-select",
            "encodings": {"fields": fields}, "frame": {"showTitle": True, "title": title}}}, "position": pos(x, y, w, h)}


def ffilter(name, title, field, datasets, x, y, w=3, h=2, multi=True):
    """A filter on a column (not a parameter): narrows every listed dataset on the page that has the column."""
    queries = [{"name": f"{name}_{ds}", "query": {"datasetName": ds, "fields": [{"name": field, "expression": f"`{field}`"}], "disaggregated": False}}
               for ds in datasets]
    return {"widget": {"name": name, "queries": queries, "spec": {"version": 2, "widgetType": "filter-multi-select" if multi else "filter-single-select",
            "encodings": {"fields": [{"fieldName": field, "displayName": title, "queryName": q["name"]} for q in queries]},
            "frame": {"showTitle": True, "title": title}}}, "position": pos(x, y, w, h)}


def uses(datasets, param):
    return [n for n, _, _, ps in DATASETS if n in datasets and param in ps]


def page(name, title, intro, body, ds, entity=False, feed=False, entity_values="v_entities"):
    head = [text(f"{name}_title", [f"## {title}\n", "\n", intro + "\n"], 0, 0, 12 if not (entity or feed) else 6, 2),
            flt(f"{name}_f_date", "As-of date", "v_dates", "as_of", "as_of", uses(ds, "as_of"), 6 if (entity or feed) else 9, 0, 3, 2)]
    if entity:
        head.append(flt(f"{name}_f_entity", "Reporting entity", entity_values, "entity", "entity", uses(ds, "entity"), 9, 0, 3, 2))
    elif feed:
        head.append(flt(f"{name}_f_feed", "Source feed", "v_feeds", "feed", "feed", uses(ds, "feed"), 9, 0, 3, 2))
    else:
        head[0]["position"]["width"] = 9
    return {"name": name, "displayName": title, "pageType": "PAGE_TYPE_CANVAS", "layout": head + body}


def pages():
    bn = {"type": "number-currency", "currencyCode": "USD", "abbreviation": "compact", "decimalPlaces": {"type": "exact", "places": 1}}
    pct0 = {"type": "number-percent", "decimalPlaces": {"type": "max", "places": 1}}
    quality = page("quality", "Data quality", "Do I have all the data, and is it right? Completeness: every source feed and record received. "
                   "Accuracy: every record passes the data quality rules and the filing ties to the general ledger and the LCR (BCBS 239 principles 3 and 4).", [
        counter("c_c1", "c_kpi", "feeds_complete", "Source feeds complete (of 10)", NUM, 0, 2, 3),
        counter("c_c2", "c_kpi", "volume_vs_expected", "Records received vs expected", pct0, 3, 2, 3),
        counter("c_c3", "c_kpi", "records_rejected", "Records rejected by data quality", NUM, 6, 2, 3),
        counter("c_c4", "c_kpi", "recon_breaks", "Reconciliation breaks (GL, LCR)", NUM, 9, 2, 3),
        chart("c_feed_chart", "c_feeds", "bar", "feed", "records", "Records received vs expected (5-day median), per source feed", 0, 5, 12, 6,
              color="measure", agg="SUM", ytitle="records", grouped=True),
        table("c_issue_table", "c_issues", [("dimension", "BCBS 239"), ("issue", "Issue"), ("item", "Item"), ("detail", "Detail"), ("action", "What to do")],
              "Issues to act on - empty when the data is complete and accurate", 0, 11, 12, 6),
    ], [n for n, *_ in DATASETS if n.startswith("c_")])
    rules = page("rules", "Rule coverage and validation", "Did every record get its FR 2052a product (PID) from a rule, and did today's report pass every check - "
                 "the FR 2052a Instructions, the Fed's 6G business rules and schema, the Fed's post-submission checks and the reconciliations?", [
        text("r_t1", ["### Rule coverage - what has no rule (a new product code, a customer not classified yet, a combination no rule covers) and what to do\n"], 0, 2, 12, 1),
        counter("r_c1", "r_kpi", "classified_pct", "Positions classified by a PID rule", pct0, 0, 3, 3),
        counter("r_c2", "r_kpi", "without_rule", "Positions without a rule", NUM, 3, 3, 3),
        counter("r_c3", "r_kpi", "without_rule_usd", "Amount without a rule", bn, 6, 3, 3),
        counter("r_c4", "r_kpi", "awaiting_master_data", "New customers / codes awaiting a decision", NUM, 9, 3, 3),
        chart("r_tab_chart", "r_by_table", "bar", "table_code", "positions", "Positions per FR 2052a table: classified by a rule vs without one", 0, 6, 12, 6,
              color="outcome", stacked=True, ytitle="positions"),
        table("r_gap_table", "r_gaps", [("item", "Record / customer / code"), ("gap", "What is missing"), ("source_system", "System"), ("source_product_code", "Bank product code"),
              ("customer_id", "Customer"), ("provisional_product_id", "Likely PID"), ("amount_usd", "USD mm"), ("reason", "Why"), ("action", "What to do")],
              "Records without a rule - empty when every record is classified", 0, 12, 12, 6),
        text("x_t1", ["### Validation - did the report pass every check, and is every warning explained\n"], 0, 18, 12, 1),
        counter("x_c1", "x_kpi", "passed_pct", "Checks passed", pct0, 0, 19, 3), counter("x_c2", "x_kpi", "failed", "Blocking failures", NUM, 3, 19, 3),
        counter("x_c3", "x_kpi", "warnings_open", "Warnings not yet explained", NUM, 6, 19, 3), counter("x_c4", "x_kpi", "xsd_valid", "6G files valid against the XSD", pct0, 9, 19, 3),
        chart("x_src_chart", "x_by_source", "bar", "source", "checks", "Checks by source and result", 0, 22, 12, 6, color="result", stacked=True, ytitle="checks"),
        table("x_issue_table", "x_issues", [("rule_id", "Check"), ("rule_name", "What it checks"), ("rule_source", "Source"), ("result", "Result"),
              ("exceptions", "Exceptions"), ("resolved", "Resolved"), ("still_open", "Still open"), ("action", "What to do")],
              "Checks not passing today and where each stands", 0, 28, 12, 6),
    ], [n for n, *_ in DATASETS if n.startswith(("r_", "x_"))])
    lcr = page("lcr", "LCR", "The Liquidity Coverage Ratio (12 CFR 249) = HQLA / total net cash outflows over the next 30 days "
               "(cash outflows less cash inflows counted, capped at 75% of outflows, plus the maturity mismatch add-on). USD bn.", [
        counter("m_c1", "m_kpi", "lcr_ratio", "LCR (minimum 100%)", PCT, 0, 2, 4, 4), counter("m_c2", "m_kpi", "hqla", "HQLA", bn, 4, 2, 2, 4),
        counter("m_c3", "m_kpi", "outflows", "Cash outflows (30 days)", bn, 6, 2, 2, 4), counter("m_c4", "m_kpi", "inflows", "Cash inflows counted (30 days)", bn, 8, 2, 2, 4),
        counter("m_c5", "m_kpi", "nco", "Net cash outflows (30 days)", bn, 10, 2, 2, 4),
        chart("m_lcr_chart", "m_lcr_trend", "line", "as_of_date", "lcr_pct", "LCR trend (%)", 0, 6, 6, 7, color="series", agg="AVG", xtype="temporal", ytitle="LCR %", colors=LCR_COLORS),
        chart("m_hn_chart", "m_hqla_nco", "line", "as_of_date", "usd_bn", "HQLA and net cash outflows, day over day (USD bn)", 6, 6, 6, 7,
              color="measure", xtype="temporal", ytitle="USD bn", colors=LCR_COLORS),
        chart("m_hqla_chart", "m_hqla_days", "bar", "as_of_date", "usd_bn", "HQLA trend by level - Level 1, 2A and 2B (USD bn, after haircuts)", 0, 13, 6, 7,
              color="component", stacked=True, xtype="temporal", ytitle="USD bn", colors=LCR_COLORS),
        chart("m_nco_chart", "m_nco_days", "bar", "as_of_date", "usd_bn", "Net cash outflows trend - cash outflows, less cash inflows counted, = net (USD bn)", 6, 13, 6, 7,
              color="measure", xtype="temporal", ytitle="USD bn", grouped=True, colors=LCR_COLORS),
        chart("m_out_chart", "m_out_days", "bar", "as_of_date", "usd_bn", "Cash outflows by category, day over day (USD bn, weighted)", 0, 20, 6, 7,
              color="component", stacked=True, xtype="temporal", ytitle="USD bn", colors=LCR_COLORS),
        chart("m_in_chart", "m_in_days", "bar", "as_of_date", "usd_bn", "Cash inflows by category, day over day (USD bn, weighted, before the cap)", 6, 20, 6, 7,
              color="component", stacked=True, xtype="temporal", ytitle="USD bn", colors=LCR_COLORS),
        table("m_inputs_table", "m_inputs", [("component", "Component"), ("positions", "Positions"), ("balance_usd_mm", "Balance (USD mm, unweighted)"),
              ("rate", "Average rate (weighted / balance)"), ("weighted_usd_mm", "Weighted (USD mm)")],
              "The input data of the day - from HQLA to net cash outflows: positions, balances, rates and weighted amounts", 0, 27, 12, 14,
              description="Balance is before the LCR rates and haircuts; weighted is after. Positions and balances are the FR 2052a positions each LCR rule applied to."),
    ], [n for n, *_ in DATASETS if n.startswith("m_")], entity=True, entity_values="v_lcr_entities")
    pf = ["p_tables", "p_records", "p_positions"]
    report = page("report", "FR 2052a tables", "The report as the Federal Reserve prescribes it: Inflows, Outflows and Supplemental, each table, product (PID) and "
                  "reported record, down to the positions behind it. Narrow it with the filters.", [
        ffilter("p_f_sec", "Section", "section", pf, 0, 2), ffilter("p_f_tab", "Table", "table_code", pf, 3, 2),
        ffilter("p_f_pid", "Product (PID)", "product_id", ["p_records", "p_positions"], 6, 2), ffilter("p_f_rec", "Reported record", "record_key", ["p_records", "p_positions"], 9, 2),
        table("p_tab_table", "p_tables", [("section", "Section"), ("table_code", "Table"), ("table_name", "Name"), ("records", "Records"), ("positions", "Positions"),
              ("usd_mm", "USD mm")], "Tables", 0, 4, 12, 6),
        table("p_rec_table", "p_records", [("table_code", "Table"), ("product_id", "PID"), ("product_name", "Product"), ("sub_product", "Sub-product"), ("counterparty", "Counterparty"),
              ("collateral_class", "Collateral"), ("maturity_bucket", "Maturity"), ("currency", "Ccy"), ("converted", "Converted"), ("reported_amount", "Amount"),
              ("reported_amount_usd", "USD mm"), ("positions", "Positions"), ("validation_status", "Checks"), ("record_key", "Record")],
              "Reported records - as filed in the 6G file", 0, 10, 12, 9),
        table("p_pos_table", "p_positions", [("table_code", "Table"), ("product_id", "PID"), ("record_key", "Record"), ("position_id", "Position"), ("record_id", "Source record"),
              ("source_system", "System"), ("source_product_code", "Bank product code"), ("booking_entity", "Booked at"), ("customer_id", "Customer"),
              ("counterparty", "Counterparty"), ("collateral_class", "Collateral"), ("maturity_date", "Maturity date"), ("maturity_bucket", "Bucket"),
              ("currency", "Ccy"), ("amount", "Amount"), ("pid_rule_id", "PID rule")], "Positions behind the records - the most granular data", 0, 19, 12, 10,
              description="Pick a record in the filter above (or a table / PID) to see exactly which positions it adds up."),
    ], pf, entity=True)
    adj = page("adjustments", "Adjustments", "Every change made in the app for the day - what changed, from and to, why, by whom and when - as of the last pipeline run "
               "(changes made since then are in the app, and appear here after the next run).", [
        chart("a_type_chart", "a_log", "bar", "adjustment_type", "subject", "Adjustments by type", 0, 2, 12, 5, agg="COUNT", ytitle="adjustments"),
        table("a_log_table", "a_log", [("made_at", "When"), ("adjustment_type", "Adjustment"), ("subject", "Record / position / item"), ("field", "Field"),
              ("old_value", "From"), ("new_value", "To"), ("note", "Reason"), ("made_by", "By"), ("status", "Status")], "Audit trail", 0, 7, 12, 10),
    ], ["a_log"])
    data = page("data", "Source to Report", "Pick a day and a source feed: the exact records it sent, which passed the data quality check, the positions they became after enrichment, how each reporting entity reports them, and the FR 2052a records they end up in.", [
        counter("l_n_bronze", "l_counts", "bronze_records", "1 Source records", NUM, 0, 2), counter("l_n_pass", "l_counts", "dq_passed", "2 Passed quality check", NUM, 2, 2),
        counter("l_n_quar", "l_counts", "quarantined", "2 Held back", NUM, 4, 2), counter("l_n_silver", "l_counts", "silver_positions", "3 Enriched positions", NUM, 6, 2),
        counter("l_n_entity", "l_counts", "entity_positions", "4 By reporting entity", NUM, 8, 2), counter("l_n_gold", "l_counts", "filed_records", "5 Reported records", NUM, 10, 2),
        text("l_t1", ["### 1. Source records - exactly as the source system sent them\n"], 0, 5, 12, 1),
        table_all("l_bronze_table", "l_bronze", "Every record of the feed, every field, with the file it arrived in and when it was received", 0, 6, 12, 9),
        text("l_t2", ["### 2. Data quality check - which records passed, which were held back and by which rule\n"], 0, 15, 12, 1),
        table("l_dq_table", "l_dq", [("record_id", "Record"), ("dq_result", "Quality check"), ("rules_failed", "Rules failed"), ("source_product_code", "Code"),
              ("customer_id", "Customer"), ("currency", "Ccy"), ("principal_amount", "Principal"), ("market_value", "Market value"),
              ("landing_file", "Source file"), ("ingested_at", "Received at"), ("dq_timestamp", "Checked at")], "Quality check result per record", 0, 16, 12, 8),
        text("l_t3", ["### 3. Enriched positions - each record split into its FR 2052a parts (e.g. insured / uninsured), with counterparty, collateral, maturity and its FR 2052a product (PID)\n"], 0, 24, 12, 1),
        table("l_silver_table", "l_silver", [("record_id", "Record"), ("position_id", "Position"), ("part", "Part"), ("booking_entity", "Booked at"),
              ("source_product_code", "Code"), ("standard_product_type", "Product type"), ("pid_rule_id", "Classification rule"), ("product_id", "FR 2052a product (PID)"), ("table_code", "Table"),
              ("customer_id", "Customer"), ("counterparty", "Counterparty"), ("gsib", "G-SIB"), ("collateral_class", "Collateral"), ("collateral_basis", "Collateral basis"),
              ("maturity_date", "Maturity"), ("maturity_basis", "Maturity basis"), ("maturity_bucket", "Bucket"), ("insured", "Insured"), ("insured_basis", "Insured basis"),
              ("currency", "Ccy"), ("amount", "Amount"), ("lendable_value", "Lendable"), ("risk_weight", "Risk weight"), ("business_line", "Business line")],
              "Positions after enrichment and classification", 0, 25, 12, 9),
        text("l_t4", ["### 4. Positions by reporting entity - each position in every reporting entity that owns the booking entity (consolidated, bank, broker-dealer)\n"], 0, 34, 12, 1),
        table("l_entity_table", "l_entity", [("reporting_entity", "Entity"), ("position_id", "Position"), ("relationship", "Relationship"), ("internal", "Internal"),
              ("internal_counterparty", "Internal counterparty"), ("product_id", "PID"), ("amount", "Amount")], "Reported by", 0, 35, 12, 7),
        text("l_t5", ["### 5. Reported FR 2052a records - positions with the same reporting fields are added up into one record of the 6G file\n"], 0, 42, 12, 1),
        table("l_gold_table", "l_gold", [("reporting_entity", "Entity"), ("table_code", "Table"), ("product_id", "PID"), ("counterparty", "Counterparty"),
              ("collateral_class", "Collateral"), ("maturity_bucket", "Bucket"), ("currency", "Ccy"), ("converted", "Converted"), ("reported_amount", "Reported amount"),
              ("positions_in_record", "Positions in record"), ("positions_from_feed", "From this feed"), ("amount_from_feed", "Amount from this feed"), ("record_key", "Record key")],
              "FR 2052a records containing this feed's positions", 0, 43, 12, 8,
              description="A record can also hold positions from other feeds; paste its record key in the app's Lineage page to trace it."),
    ], [n for n, *_ in DATASETS if n.startswith("l_")], feed=True)
    return {"main": [data, quality, rules, report, adj], "lcr": [lcr]}


THEME = {"canvasBackgroundColor": {"light": "#F7F8FA", "dark": "#1F272D"}, "widgetBackgroundColor": {"light": "#FFFFFF", "dark": "#11171C"},
         "widgetBorderColor": {"light": "#FFFFFF", "dark": "#11171C"}, "fontColor": {"light": "#11171C", "dark": "#E8ECF0"},
         "selectionColor": {"light": "#2272B4", "dark": "#8ACAFF"},
         "visualizationColors": ["#0B2545", "#2F7FB8", "#5BB5A2", "#F2A541", "#D1495B", "#8E6C8A", "#A3B4C4", "#4E5185", "#C8B273"],
         "widgetHeaderAlignment": "LEFT"}


# Two dashboards from one definition: the main FR 2052a dashboard (the app's Dashboard module) and the LCR module's own.
DASHBOARDS = {"main": ("FR 2052a Liquidity Reporting", HERE.parent / "dashboards" / "fr2052a_liquidity_reporting.lvdash.json"),
              "lcr": ("FR 2052a LCR", HERE.parent / "dashboards" / "fr2052a_lcr.lvdash.json")}


def build(catalog, which="main"):
    pgs = pages()[which]
    used = {q["query"]["datasetName"] for pg in pgs for it in pg["layout"] for q in it["widget"].get("queries", [])}
    ds = []
    for n, disp, q, ps in [x for x in DATASETS if x[0] in used]:
        d = {"name": n, "displayName": disp, "queryLines": sql_lines(q, catalog)}
        if ps:
            d["parameters"] = [param_spec(p) for p in ps]
        ds.append(d)
    return {"datasets": ds, "pages": pgs, "uiSettings": {"theme": THEME}}


def run(w, wh, q):
    st = w.statement_execution.execute_statement(warehouse_id=wh, statement=q, wait_timeout="50s")
    while st.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        st = w.statement_execution.get_statement(st.statement_id)
    if st.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(st.status.error.message if st.status.error else st.status.state)
    cols = [c.name for c in st.manifest.schema.columns]
    return cols, (st.result.data_array or []) if st.result else []


def validate(w, wh, dash):
    ok, cols_of, order_of = True, {}, {}
    for d in dash["datasets"]:
        q = "".join(d["queryLines"])
        for p in ("as_of", "entity", "feed"):
            q = q.replace(f":{p}", f"'{DEFAULTS[p]}'")
        try:
            cols, rows = run(w, wh, q)
            cols_of[d["name"]] = set(cols)
            order_of[d["name"]] = cols
            print(f"  {d['name']:18s} {len(rows):6d} rows")
        except Exception as e:
            ok = False
            print(f"  {d['name']:18s} ERROR {str(e)[:300]}")
    for pg in dash["pages"]:   # SELECT * tables: list the actual columns
        for item in pg["layout"]:
            if item.pop("_all_columns", False):
                q = item["widget"]["queries"][0]["query"]
                cols = order_of.get(q["datasetName"], [])
                q["fields"] = [{"name": c, "expression": f"`{c}`"} for c in cols]
                item["widget"]["spec"]["encodings"]["columns"] = [{"fieldName": c, "displayName": LABEL.get(c, c.replace("_", " ").strip().capitalize())} for c in cols]
    for pg in dash["pages"]:
        for item in pg["layout"]:
            for q in item["widget"].get("queries", []):
                for f in q["query"].get("fields", []):
                    col = f["expression"].split("`")[1] if "`" in f["expression"] else None
                    if col and col not in cols_of.get(q["query"]["datasetName"], {col}):
                        ok = False
                        print(f"  {pg['name']}/{item['widget']['name']}: field {col} missing from {q['query']['datasetName']}")
        cells = {}
        for item in pg["layout"]:
            p, name = item["position"], item["widget"]["name"]
            hit = {cells[(r, c)] for r in range(p["y"], p["y"] + p["height"]) for c in range(p["x"], p["x"] + p["width"]) if (r, c) in cells}
            if hit or p["x"] + p["width"] > 12:
                ok = False
                print(f"  {pg['name']}/{name}: overlaps {sorted(hit)} or exceeds 12 columns")
            cells.update({(r, c): name for r in range(p["y"], p["y"] + p["height"]) for c in range(p["x"], p["x"] + p["width"])})
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--warehouse", required=True)
    ap.add_argument("--dashboard", choices=list(DASHBOARDS), default="main")
    a = ap.parse_args()
    w = WorkspaceClient(profile=a.profile)
    dash = build(a.catalog, a.dashboard)
    print(f"{len(dash['datasets'])} datasets, {sum(len(p['layout']) for p in dash['pages'])} widgets on {len(dash['pages'])} pages")
    if not validate(w, a.warehouse, dash):
        print("validation failed - not written")
        return 1
    out = json.dumps(dash, indent=2).replace(f"`{a.catalog}`.", "")   # catalog-free: the bundle sets dataset_catalog
    DASHBOARDS[a.dashboard][1].write_text(out + "\n")
    print("wrote", DASHBOARDS[a.dashboard][1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
