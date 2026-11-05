# Databricks notebook source
# MAGIC %md
# MAGIC # Semantic layer: Unity Catalog metric views (v9)
# MAGIC ## Owned by: Regulatory Reporting Team
# MAGIC
# MAGIC The governed definitions of the FR 2052a numbers - measured once, used everywhere (the Genie space, the agent, the
# MAGIC dashboard). Query with `MEASURE(<measure>)` and `GROUP BY` any dimension.
# MAGIC
# MAGIC | Metric view | Grain | Measures |
# MAGIC |---|---|---|
# MAGIC | `reg_2052a.fr2052a_metrics` | one reported FR 2052a record | reported amount (USD mm, ratios excluded), inflows, outflows, 30-day inflows / outflows / net, records, positions, LCR (S.L.6) and NSFR (S.L.10) as reported |
# MAGIC | `reg_lcr.fr2052a_lcr_metrics` | one LCR calculation (entity x day) | HQLA by level, outflows, inflows, capped inflows, net cash outflows, LCR (ratio of sums), compliant days |
# MAGIC | `reg_2052a.fr2052a_check_metrics` | one check result (rule x day) | checks, passed, failed, warnings, blocking errors, Fed post-submission checks not passing, records failed |

# COMMAND ----------

dbutils.widgets.text("catalog", "")
C = dbutils.widgets.get("catalog")

VIEWS = {
"fr2052a_metrics": f"""
CREATE OR REPLACE VIEW {C}.reg_2052a.fr2052a_metrics
COMMENT 'FR 2052a reported records (13 tables, 3 reporting entities): amounts, flows and counts. Query with MEASURE(); always filter or group by reporting_entity - the consolidated entity already includes the subsidiaries.'
WITH METRICS LANGUAGE YAML AS $$
version: 1.1
comment: FR 2052a reported records per as-of date and reporting entity (USD millions; ENT001 consolidated BHC, ENT002 bank, ENT003 broker-dealer). Never add entities together.
source: {C}.reg_2052a.v_filing_records
joins:
  - name: product
    source: {C}.reference.ref_product
    on: source.product_id = product.product_id
  - name: entity
    source: {C}.reference.ref_reporting_entity
    on: source.reporting_entity = entity.entity_id
  - name: bucket
    source: {C}.reference.ref_maturity_bucket
    on: source.maturity_bucket = bucket.bucket_label
dimensions:
  - name: as_of_date
    expr: source.as_of_date
    comment: Business day the report is for (2026-01-02 .. 2026-02-27; month-ends 2026-01-30 and 2026-02-27)
    synonyms: [date, reporting date, report date, business day]
  - name: reporting_entity
    expr: source.reporting_entity
    comment: ENT001 consolidated BHC, ENT002 bank (solo), ENT003 broker-dealer (solo)
    synonyms: [entity, reporting entity id, filer]
  - name: entity_name
    expr: entity.entity_name
    synonyms: [entity name, legal name]
  - name: scope_type
    expr: entity.scope_type
    comment: CONSOLIDATED or SOLO
  - name: table_code
    expr: source.table_code
    comment: FR 2052a table, e.g. O.D (Outflows-Deposits), I.A (Inflows-Assets), S.L (Supplemental-Liquidity Risk Measurement)
    synonyms: [table, schedule, collection]
  - name: table_name
    expr: source.table_name
  - name: flow_side
    expr: CASE WHEN source.table_code LIKE 'I.%' THEN 'Inflow' WHEN source.table_code LIKE 'O.%' THEN 'Outflow' ELSE 'Supplemental' END
    comment: Inflow (I tables), Outflow (O tables) or Supplemental (S tables)
    synonyms: [direction, side]
  - name: product_id
    expr: source.product_id
    comment: FR 2052a product identifier (PID), e.g. O.D.1
    synonyms: [PID, product, product id]
  - name: product_name
    expr: product.product_name
    comment: 6G product name, e.g. Transactional Accounts
  - name: sub_product
    expr: source.sub_product
  - name: counterparty
    expr: source.counterparty
    comment: FR 2052a counterparty type, e.g. Retail, Bank, Non-Financial Corporate
    synonyms: [counterparty type, customer type, sector]
  - name: collateral_class
    expr: source.collateral_class
    comment: Appendix III collateral class, e.g. A-1-Q
  - name: maturity_bucket
    expr: source.maturity_bucket
    comment: Appendix IV-a maturity bucket, e.g. Open, Day 1, 31 - 60 Days
    synonyms: [bucket, maturity, tenor]
  - name: maturity_bucket_order
    expr: bucket.bucket_seq
    comment: Sort order of the maturity bucket
  - name: within_30_days
    expr: COALESCE(bucket.is_within_30d, false)
    comment: true when the maturity bucket is within the 30-day LCR horizon (Open counts as within 30 days)
  - name: currency
    expr: source.currency
  - name: converted
    expr: source.converted
    comment: true when a non-6G currency was converted to USD
measures:
  - name: reported_amount_usd_mm
    expr: SUM(source.reported_amount_usd) FILTER (WHERE source.product_id NOT IN ('S.L.6', 'S.L.10'))
    comment: Reported amount in USD millions (USD equivalent; the S.L.6 LCR and S.L.10 NSFR ratios are excluded)
    synonyms: [amount, balance, total, reported amount, exposure]
  - name: inflows_usd_mm
    expr: SUM(source.reported_amount_usd) FILTER (WHERE source.table_code LIKE 'I.%')
    synonyms: [inflows, cash inflows]
  - name: outflows_usd_mm
    expr: SUM(source.reported_amount_usd) FILTER (WHERE source.table_code LIKE 'O.%')
    synonyms: [outflows, cash outflows, funding]
  - name: inflows_30d_usd_mm
    expr: SUM(source.reported_amount_usd) FILTER (WHERE source.table_code LIKE 'I.%' AND COALESCE(bucket.is_within_30d, false))
    comment: Inflows maturing within 30 days (unweighted)
  - name: outflows_30d_usd_mm
    expr: SUM(source.reported_amount_usd) FILTER (WHERE source.table_code LIKE 'O.%' AND COALESCE(bucket.is_within_30d, false))
    comment: Outflows maturing within 30 days (unweighted)
  - name: net_30d_outflows_usd_mm
    expr: SUM(source.reported_amount_usd) FILTER (WHERE source.table_code LIKE 'O.%' AND COALESCE(bucket.is_within_30d, false)) - COALESCE(SUM(source.reported_amount_usd) FILTER (WHERE source.table_code LIKE 'I.%' AND COALESCE(bucket.is_within_30d, false)), 0)
    comment: 30-day outflows minus 30-day inflows (unweighted; the weighted LCR is in reg_lcr.fr2052a_lcr_metrics)
  - name: records
    expr: COUNT(1)
    comment: Number of reported FR 2052a records (rows in the 6G file)
    synonyms: [record count, rows, data elements]
  - name: positions
    expr: SUM(source.record_count)
    comment: Number of positions aggregated into the records
    synonyms: [position count]
  - name: reported_lcr
    expr: MAX(source.reported_amount) FILTER (WHERE source.product_id = 'S.L.6')
    comment: LCR as reported in S.L.6 (a ratio, 1.21 = 121%); meaningful per reporting entity and date only
    synonyms: [S.L.6, reported LCR]
  - name: reported_nsfr
    expr: MAX(source.reported_amount) FILTER (WHERE source.product_id = 'S.L.10')
    comment: NSFR as reported in S.L.10 (month-end); per reporting entity and date only
$$""",

"fr2052a_lcr_metrics": f"""
CREATE OR REPLACE VIEW {C}.reg_lcr.fr2052a_lcr_metrics
COMMENT 'Liquidity Coverage Ratio (12 CFR 249) per LCR entity (ENT001, ENT002) and day, from the LCR engine. Query with MEASURE(); the LCR is a ratio of sums.'
WITH METRICS LANGUAGE YAML AS $$
version: 1.1
comment: LCR per LCR reporting entity and as-of date (USD millions). ENT003 (broker-dealer) has no standalone LCR.
source: {C}.reg_lcr.calculation_results
dimensions:
  - name: as_of_date
    expr: source.as_of_date
    synonyms: [date, reporting date]
  - name: entity_id
    expr: source.entity_id
    comment: ENT001 consolidated BHC or ENT002 bank
    synonyms: [entity, reporting entity]
measures:
  - name: lcr
    expr: SUM(source.total_hqla) / NULLIF(SUM(source.total_net_cash_outflows), 0)
    comment: Liquidity Coverage Ratio = HQLA / total net cash outflows (1.21 = 121%; minimum 100%). Use per entity and date.
    synonyms: [LCR, liquidity coverage ratio, coverage ratio]
  - name: hqla_usd_mm
    expr: SUM(source.total_hqla)
    comment: High-quality liquid assets after haircuts and caps
    synonyms: [HQLA, liquid assets]
  - name: level1_hqla_usd_mm
    expr: SUM(source.level1_hqla)
  - name: level2a_hqla_usd_mm
    expr: SUM(source.level2a_hqla_adjusted)
  - name: level2b_hqla_usd_mm
    expr: SUM(source.level2b_hqla_adjusted)
  - name: total_outflows_usd_mm
    expr: SUM(source.total_outflows)
    comment: Weighted 30-day stressed outflows
  - name: total_inflows_usd_mm
    expr: SUM(source.total_inflows)
  - name: capped_inflows_usd_mm
    expr: SUM(source.capped_inflows)
    comment: Inflows after the 75% of outflows cap
  - name: net_cash_outflows_usd_mm
    expr: SUM(source.total_net_cash_outflows)
    synonyms: [NCO, net cash outflows]
  - name: compliant_days
    expr: COUNT_IF(source.lcr_compliant)
    comment: Number of entity-days with LCR >= 100%
$$""",

"fr2052a_check_metrics": f"""
CREATE OR REPLACE VIEW {C}.reg_2052a.fr2052a_check_metrics
COMMENT 'FR 2052a validation results per day: Fed 6G schema and business rules, Instructions appendix rules and the Fed''s 14 post-submission checks. Query with MEASURE().'
WITH METRICS LANGUAGE YAML AS $$
version: 1.1
comment: One row per check per as-of date; status PASS / FAIL / WARNING / NOT_APPLICABLE; an ERROR failure blocks the reporting run.
source: {C}.reg_2052a.gold_validation
dimensions:
  - name: as_of_date
    expr: source.as_of_date
    synonyms: [date, reporting date]
  - name: check_source
    expr: CASE source.rule_source WHEN 'Fed PSV' THEN 'Fed post-submission check' WHEN 'Instructions' THEN 'Instructions appendix rule' ELSE source.rule_source END
    comment: Fed post-submission check (PSV-01..14), 6G BR (business rules), 6G BR General (file rules), 6G XSD (schema), Instructions appendix rule
    synonyms: [rule source, check type]
  - name: rule_id
    expr: source.rule_id
    synonyms: [check, rule, check id]
  - name: rule_name
    expr: source.rule_name
  - name: table_code
    expr: source.table_code
  - name: severity
    expr: source.severity
    comment: ERROR or WARNING
  - name: status
    expr: source.status
measures:
  - name: checks
    expr: COUNT(1)
  - name: checks_passed
    expr: COUNT_IF(source.status = 'PASS')
  - name: checks_failed
    expr: COUNT_IF(source.status = 'FAIL')
    synonyms: [failures, failed checks]
  - name: warnings
    expr: COUNT_IF(source.status = 'WARNING')
  - name: blocking_errors
    expr: COUNT_IF(source.status = 'FAIL' AND source.severity = 'ERROR')
    comment: Failed ERROR checks - they block the reporting run
    synonyms: [blockers, blocking failures]
  - name: fed_checks_not_passing
    expr: COUNT_IF(source.rule_source = 'Fed PSV' AND source.status IN ('FAIL', 'WARNING'))
    comment: Fed post-submission checks (of 14) that failed or warned
    synonyms: [PSV not passing, post-submission checks failing]
  - name: records_failed
    expr: SUM(source.records_failed)
    comment: Records that failed the checks
$$""",
}

for name, ddl in VIEWS.items():
    spark.sql(ddl)
    print("created", name)

display(spark.sql(f"""SELECT reporting_entity, table_code, MEASURE(reported_amount_usd_mm) AS usd_mm, MEASURE(records) AS records
                      FROM {C}.reg_2052a.fr2052a_metrics WHERE as_of_date = '2026-02-27' GROUP BY ALL ORDER BY 1, 2"""))
display(spark.sql(f"SELECT as_of_date, entity_id, MEASURE(lcr) AS lcr FROM {C}.reg_lcr.fr2052a_lcr_metrics GROUP BY ALL ORDER BY 1 DESC, 2 LIMIT 6"))
display(spark.sql(f"SELECT as_of_date, MEASURE(blocking_errors) AS blocking, MEASURE(fed_checks_not_passing) AS psv FROM {C}.reg_2052a.fr2052a_check_metrics GROUP BY ALL ORDER BY 1 DESC LIMIT 6"))
