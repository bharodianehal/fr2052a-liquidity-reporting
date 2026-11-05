# Databricks notebook source
# MAGIC %md
# MAGIC # Calculation Layer, PID Derivation & Entity Scoping: conformed.source_position -> Silver (v9)
# MAGIC ## Owned by: Regulatory Reporting Team (rules) / Data Governance (master data)
# MAGIC
# MAGIC Source systems do not know FR 2052a. This notebook turns each DQ-passed source record into FR 2052a data elements:
# MAGIC
# MAGIC | Step | What | Reference |
# MAGIC |---|---|---|
# MAGIC | 1 Enrichment | Bank product code -> **standard product type**; customer -> Counterparty, G-SIB, affiliate (only approvals effective on the as-of date); collateral -> Collateral Class from the security id, the **linked (placed / received) collateral - lowest-liquidity piece wins** - or the **generic terms of substitutable collateral** | `v_source_product_map`, `v_customer_master`, `ref_security_master`, `raw.collateral_links`, `ref_generic_collateral_map` |
# MAGIC | 2 Splits | **Operational deposits** (qualifying service, >= 30-day notice): operational amount vs excess; **central bank reserves**: reserve requirement (restricted) vs excess; **FDIC insurance allocation**: insured vs uninsured part per depositor (USD 250,000) | LRM s.3 / 249.4(b); Reg D 204.5; FDIC 370 |
# MAGIC | 3 PID | Ordered SQL rules per standard product type over the calculated record; first match wins (`pid_rule_id`) | `rules_pid_derivation` |
# MAGIC | 4 Maturity | **Embedded options** per LRM s.31(a): outflows at the earliest possible date (counterparty put, firm call, notice), inflows at the latest (borrower extension); **effective drawdown date** for commitments (earliest date they can be drawn); Maturity Optionality; Appendix IV-a buckets; weekend-flow flag | Field Definitions p.22-23, p.31-32; O.O product definitions |
# MAGIC | 5 Values | **Lendable value** from the pledge-venue haircut table (or the collateral system's value); Risk Weight to the 6G decimal; Accounting Designation only on I.A.1 / I.A.2 | `ref_lendable_haircuts`; p.30-31 |
# MAGIC | 6 Holds | Positions of customers still awaiting classification approval, and positions no rule classifies, go to `dq.pid_exceptions` | |
# MAGIC | 7 Entity scope | For each reporting entity (consolidated + solo): positions in scope, **intercompany eliminated**, Internal / Internal Counterparty for affiliates outside the scope, SELF flagged as a data error | `ref_reporting_entity`, `ref_legal_entity` |
# MAGIC
# MAGIC For the synthetic data the derived PID of every part is compared with `audit.pid_answer_key`; any mismatch fails the run.

# COMMAND ----------

dbutils.widgets.text("as_of_date", "2026-02-27")
dbutils.widgets.text("catalog", "")
AS_OF = dbutils.widgets.get("as_of_date")
CATALOG = dbutils.widgets.get("catalog")
spark.sql(f"USE CATALOG {CATALOG}")
R = f"{CATALOG}.reference"

src_count = spark.sql(f"SELECT COUNT(*) AS n FROM {CATALOG}.conformed.source_position WHERE as_of_date = '{AS_OF}'").first().n
print(f"{AS_OF}: {src_count} DQ-passed source records")
if src_count == 0:
    dbutils.notebook.exit(f"No source positions for {AS_OF}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Enrichment: standard product type, customer, collateral

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TEMP VIEW v_links AS
SELECT l.record_id, SUM(l.collateral_amount) AS linked_value,
       MAX_BY(sm.collateral_class, STRUCT(CASE c.hqla_level WHEN 'Level 1' THEN 1 WHEN 'Level 2A' THEN 2 WHEN 'Level 2B' THEN 3 ELSE 4 END,
                                         l.collateral_amount)) AS linked_class,
       COUNT(*) AS pieces
FROM {CATALOG}.raw.collateral_links l
JOIN {R}.ref_security_master sm ON sm.collateral_id = l.collateral_id
JOIN {R}.ref_collateral c ON c.collateral_class = sm.collateral_class
WHERE l.as_of_date = '{AS_OF}'
GROUP BY l.record_id""")

spark.sql(f"""
CREATE OR REPLACE TEMP VIEW v_enriched AS
SELECT s.*, pm.standard_product_type,
  cm.counterparty, rc.counterparty_category, cm.gsib_parent AS gsib, cm.affiliate_legal_entity_id,
  COALESCE(cm.has_relationship, false) AS has_relationship,
  (s.customer_id IS NOT NULL AND cm.customer_id IS NULL) AS customer_pending,
  COALESCE(sm.collateral_class, lk.linked_class, gm.collateral_class) AS collateral_class,
  CASE WHEN sm.collateral_class IS NOT NULL THEN 'SECURITY' WHEN lk.linked_class IS NOT NULL THEN CONCAT('LINKED (', lk.pieces, ' pieces, lowest level)')
       WHEN gm.collateral_class IS NOT NULL THEN 'GENERIC (substitutable)' END AS collateral_basis,
  COALESCE(lk.linked_value, s.collateral_value) AS collateral_value_calc
FROM {CATALOG}.conformed.source_position s
LEFT JOIN {R}.v_source_product_map pm ON pm.source_product_code = s.source_product_code
LEFT JOIN (SELECT * FROM {R}.v_customer_master WHERE approved_on <= '{AS_OF}') cm ON cm.customer_id = s.customer_id
LEFT JOIN {R}.ref_counterparty rc ON rc.counterparty = cm.counterparty
LEFT JOIN {R}.ref_security_master sm ON sm.collateral_id = s.collateral_id
LEFT JOIN v_links lk ON lk.record_id = s.record_id
LEFT JOIN {R}.ref_generic_collateral_map gm ON gm.generic_issuer_type = s.generic_issuer_type AND gm.generic_product = s.generic_product
WHERE s.as_of_date = '{AS_OF}'""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Splits: operational / excess, restricted / unrestricted reserves, insured / uninsured

# COMMAND ----------

INSURANCE_LIMIT = 0.25   # USD 250,000 per depositor and ownership category, in millions
QUALIFYING = "service_type IN ('CASH_MANAGEMENT', 'CUSTODY', 'CLEARING') AND COALESCE(notice_days, 0) >= 30 AND operational_requirement IS NOT NULL"
OPERATIONAL_TYPES = "standard_product_type IN ('DDA', 'NOSTRO') AND COALESCE(counterparty_category, '') <> 'Retail'"
spark.sql(f"""
CREATE OR REPLACE TEMP VIEW v_parts AS
WITH base AS (SELECT *, COALESCE(principal_amount, market_value) AS bal FROM v_enriched)
-- operational deposits / balances at other banks: the operational amount and the excess
SELECT *, 'OP' AS part, LEAST(bal, operational_requirement) AS part_amount, 'OPERATIONAL' AS calc_subtype, insured AS calc_insured,
       'SOURCE' AS insured_basis FROM base WHERE {OPERATIONAL_TYPES} AND {QUALIFYING}
UNION ALL
SELECT *, 'EX', bal - LEAST(bal, operational_requirement), 'EXCESS', insured, 'SOURCE' FROM base WHERE {OPERATIONAL_TYPES} AND {QUALIFYING}
UNION ALL
SELECT *, '1', bal, 'NON_OPERATIONAL', insured, 'SOURCE' FROM base WHERE {OPERATIONAL_TYPES} AND NOT ({QUALIFYING})
UNION ALL
-- central bank balances: the reserve balance requirement is restricted (I.A.4), the rest unrestricted (I.A.3)
SELECT *, 'RST', LEAST(bal, COALESCE(reserve_requirement, 0)), 'RESTRICTED', insured, 'SOURCE' FROM base WHERE standard_product_type = 'CB-RES'
UNION ALL
SELECT *, 'UNR', bal - LEAST(bal, COALESCE(reserve_requirement, 0)), 'UNRESTRICTED', insured, 'SOURCE' FROM base WHERE standard_product_type = 'CB-RES'
UNION ALL
-- deposit insurance allocation: insured part up to the limit per depositor, the rest uninsured
SELECT *, 'INS', LEAST(bal, depositor_count * {INSURANCE_LIMIT}), product_subtype,
       CASE insurance_scheme WHEN 'OTHER' THEN 'Other' ELSE 'FDIC' END, 'FDIC_370_ALLOCATION'
FROM base WHERE depositor_count IS NOT NULL AND NOT ({OPERATIONAL_TYPES})
UNION ALL
SELECT *, 'UNI', bal - LEAST(bal, depositor_count * {INSURANCE_LIMIT}), product_subtype, 'Uninsured', 'FDIC_370_ALLOCATION'
FROM base WHERE depositor_count IS NOT NULL AND NOT ({OPERATIONAL_TYPES})
UNION ALL
SELECT *, '1', bal, product_subtype, insured, 'SOURCE' FROM base
WHERE NOT ({OPERATIONAL_TYPES}) AND COALESCE(standard_product_type, '') <> 'CB-RES' AND depositor_count IS NULL
""")
spark.sql("""CREATE OR REPLACE TEMP VIEW v_parts_nz AS
SELECT * EXCEPT (product_subtype, insured), calc_subtype AS product_subtype, calc_insured AS insured
FROM v_parts WHERE part = '1' OR ABS(part_amount) > 1e-9""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. PID derivation rules
# MAGIC
# MAGIC Each condition is compiled against the calculated view first, so a broken rule fails here with its id.

# COMMAND ----------

rules = spark.table(f"{R}.rules_pid_derivation").orderBy("standard_product_type", "priority").collect()
for r in rules:
    try:
        spark.sql(f"SELECT 1 FROM v_parts_nz WHERE {r.condition_sql} LIMIT 1").collect()
    except Exception as e:
        raise ValueError(f"PID rule {r.rule_id} does not compile: {r.condition_sql} -> {str(e)[:300]}")
RULE_CASE = "CASE " + " ".join(
    f"WHEN standard_product_type = '{r.standard_product_type}' AND ({r.condition_sql}) THEN '{r.rule_id}'" for r in rules) + " END"
spark.sql(f"""
CREATE OR REPLACE TEMP VIEW v_derived AS
SELECT e.*, pr.product_id, REGEXP_EXTRACT(pr.product_id, '^(.*)\\\\.[0-9]+$', 1) AS table_code
FROM (SELECT *, {RULE_CASE} AS pid_rule_id FROM v_parts_nz) e
LEFT JOIN {R}.rules_pid_derivation pr ON pr.rule_id = e.pid_rule_id""")
print(f"{len(rules)} PID rules over {len({r.standard_product_type for r in rules})} standard product types compile")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4-5. Maturity (options, drawdown), buckets, lendable value -> Silver

# COMMAND ----------

BUCKETS = (spark.table(f"{R}.ref_maturity_bucket").where("is_standard AND day_start > 0").orderBy("bucket_seq").collect())

def bucket_sql(date_col, open_when_null=False):
    """Appendix IV-a bucket for a date relative to the as-of date (<= 0 days -> Open)."""
    null_case = "'Open'" if open_when_null else "NULL"
    days = f"DATEDIFF({date_col}, as_of_date)"
    ranges = " ".join(f"WHEN {days} BETWEEN {b.day_start} AND {b.day_end} THEN '{b.bucket_label}'" for b in BUCKETS)
    return f"CASE WHEN {date_col} IS NULL THEN {null_case} WHEN {days} <= 0 THEN 'Open' {ranges} END"

DRAWDOWN_TYPES = "('COMMIT-CREDIT', 'COMMIT-LIQ', 'MORTG-COMMIT', 'FAC-PURCH')"
spark.sql(f"""
CREATE OR REPLACE TEMP VIEW v_maturity AS
SELECT d.*,
  CASE WHEN table_code LIKE 'O.%' THEN 'OUT' WHEN table_code LIKE 'I.%' THEN 'IN' END AS side,
  -- effective drawdown date (earliest date a commitment can be drawn)
  CASE WHEN standard_product_type IN {DRAWDOWN_TYPES} THEN
         CASE WHEN funding_start_date > as_of_date THEN funding_start_date
              WHEN as_of_date <= funding_end_date THEN DATE_ADD(as_of_date, COALESCE(draw_notice_days, 0))
              WHEN DATE_ADD(funding_end_date, COALESCE(draw_notice_days, 0)) > as_of_date THEN DATE_ADD(funding_end_date, draw_notice_days)
              ELSE as_of_date END END AS drawdown_date
FROM v_derived d WHERE product_id IS NOT NULL AND NOT customer_pending""")
spark.sql(f"""
CREATE OR REPLACE TEMP VIEW v_calc AS
SELECT m.*,
  CASE WHEN drawdown_date IS NOT NULL THEN drawdown_date
       WHEN option_type = 'NOTICE' THEN DATE_ADD(as_of_date, notice_days)
       WHEN option_type IN ('PUT_COUNTERPARTY', 'CALL_FIRM') AND side = 'OUT' THEN option_date
       WHEN option_type = 'EXTEND_COUNTERPARTY' AND side = 'IN' THEN option_date
       ELSE maturity_date END AS eff_maturity_date,
  CASE WHEN drawdown_date IS NOT NULL THEN 'DRAWDOWN'
       WHEN option_type = 'NOTICE' THEN 'NOTICE'
       WHEN option_type IN ('PUT_COUNTERPARTY', 'CALL_FIRM') AND side = 'OUT' THEN 'OPTION_EARLIEST'
       WHEN option_type = 'EXTEND_COUNTERPARTY' AND side = 'IN' THEN 'OPTION_LATEST'
       WHEN option_type IS NOT NULL THEN 'CONTRACTUAL (option not exercised)'
       ELSE 'CONTRACTUAL' END AS maturity_basis,
  CASE WHEN option_type = 'NOTICE' THEN 'Evergreen'
       WHEN option_type IN ('EXTEND_COUNTERPARTY', 'EXTEND_FIRM') THEN 'Extendible'
       WHEN option_type = 'PUT_COUNTERPARTY' AND side = 'OUT' THEN 'Accelerated-Counterparty'
       WHEN option_type = 'CALL_FIRM' AND side = 'OUT' THEN 'Accelerated-Firm'
       WHEN option_type IS NOT NULL THEN 'Not Accelerated' END AS calc_optionality,
  CASE WHEN drawdown_date IS NOT NULL OR option_type = 'NOTICE' THEN 'DATED' ELSE maturity_type END AS eff_maturity_type
FROM v_maturity m""")

HAIRCUT = f"""COALESCE(
  (SELECT MIN(h.haircut) FROM {R}.ref_lendable_haircuts h WHERE h.asset_key = 'CASH' AND c.collateral_class = 'A-0-Q'),
  (SELECT MIN(h.haircut) FROM {R}.ref_lendable_haircuts h WHERE h.pledge_venue = COALESCE(c.sub_product, 'NONE') AND h.asset_key = c.collateral_class),
  (SELECT MIN(h.haircut) FROM {R}.ref_lendable_haircuts h WHERE h.pledge_venue = COALESCE(c.sub_product, 'NONE') AND h.asset_key = 'L-' AND c.collateral_class LIKE 'L-%'),
  (SELECT MIN(h.haircut) FROM {R}.ref_lendable_haircuts h WHERE h.pledge_venue = COALESCE(c.sub_product, 'NONE') AND h.asset_key = COALESCE(col.hqla_level, 'Non-HQLA')),
  (SELECT MIN(h.haircut) FROM {R}.ref_lendable_haircuts h WHERE h.pledge_venue = 'NONE' AND h.asset_key = COALESCE(col.hqla_level, 'Non-HQLA')))"""
# Settlement date (Instructions, Maturity Bucket: "report maturities based upon the actual settlement of cash flows ... if a payment is
# scheduled to occur on a weekend or bank holiday, but will not actually settle until the next good business day, the maturity bucket
# must correspond to the date on which the payment will actually settle"). Day buckets stay calendar days after the as-of date.
spark.sql(f"""
CREATE OR REPLACE TEMP VIEW v_bday AS
WITH d AS (SELECT EXPLODE(SEQUENCE(DATE'2020-01-01', DATE'2080-12-31')) AS d),
f AS (SELECT d.d, DAYOFWEEK(d.d) NOT IN (1, 7) AND h.holiday_date IS NULL AS is_bd, h.holiday_name
      FROM d LEFT JOIN {R}.ref_bank_holidays h ON h.holiday_date = d.d)
SELECT d, is_bd, holiday_name, MIN(CASE WHEN is_bd THEN d END) OVER (ORDER BY d ROWS BETWEEN CURRENT ROW AND 10 FOLLOWING) AS settle FROM f""")
spark.sql("""
CREATE OR REPLACE TEMP VIEW v_settled AS
SELECT c.* EXCEPT (eff_maturity_date, forward_start_date, effective_maturity_date, maturity_basis),
  COALESCE(s1.settle, c.eff_maturity_date) AS eff_maturity_date, COALESCE(s2.settle, c.forward_start_date) AS forward_start_date,
  COALESCE(s3.settle, c.effective_maturity_date) AS effective_maturity_date,
  CASE WHEN s1.settle IS NOT NULL AND s1.settle <> c.eff_maturity_date
       THEN CONCAT(c.maturity_basis, ' - settles on the next business day (', CASE WHEN s1.holiday_name IS NOT NULL THEN s1.holiday_name ELSE 'weekend' END, ')')
       ELSE c.maturity_basis END AS maturity_basis,
  -- after the roll no flow should fall on a non-business day; a date outside the calendar is still caught by the Fed check PSV-01
  ((c.eff_maturity_date IS NOT NULL AND s1.settle IS NULL AND DAYOFWEEK(c.eff_maturity_date) IN (1, 7))
   OR (c.forward_start_date IS NOT NULL AND s2.settle IS NULL AND DAYOFWEEK(c.forward_start_date) IN (1, 7))
   OR (c.effective_maturity_date IS NOT NULL AND s3.settle IS NULL AND DAYOFWEEK(c.effective_maturity_date) IN (1, 7))) AS non_business_flow
FROM v_calc c
LEFT JOIN v_bday s1 ON s1.d = c.eff_maturity_date
LEFT JOIN v_bday s2 ON s2.d = c.forward_start_date
LEFT JOIN v_bday s3 ON s3.d = c.effective_maturity_date""")
rolled = spark.sql("SELECT COUNT(*) AS n FROM v_settled WHERE maturity_basis LIKE '%next business day%'").first().n
print(f"{rolled} maturities fall on a weekend or bank holiday and are reported on the date they settle")
spark.sql(f"DELETE FROM {CATALOG}.conformed.fact_liquidity_position WHERE as_of_date = '{AS_OF}'")
spark.sql(f"""
INSERT INTO {CATALOG}.conformed.fact_liquidity_position
SELECT c.as_of_date, CONCAT(c.record_id, '#', c.part) AS position_id, c.record_id, c.part, c.booking_entity, c.report_for_entity,
  c.source_feed, c.source_system, c.instrument_type, c.source_product_code, c.standard_product_type, c.product_subtype, c.flow_direction,
  c.customer_id, c.affiliate_legal_entity_id, c.collateral_id, c.product_id, c.table_code, c.pid_rule_id, c.sub_product, c.sub_product_2,
  c.counterparty, c.counterparty_category, c.gsib, c.subsidiary_entity, c.currency, c.currency_2,
  c.eff_maturity_type AS maturity_type, c.maturity_date AS contract_maturity_date, c.eff_maturity_date AS maturity_date, c.maturity_basis,
  CASE WHEN c.eff_maturity_type = 'DATED' THEN DATEDIFF(c.eff_maturity_date, c.as_of_date) END AS maturity_days,
  CASE c.eff_maturity_type WHEN 'OPEN' THEN 'Open' WHEN 'PERPETUAL' THEN 'Perpetual' ELSE {bucket_sql('c.eff_maturity_date', True)} END AS maturity_bucket,
  c.calc_optionality AS maturity_optionality,
  c.forward_start_date, {bucket_sql('c.forward_start_date')} AS forward_start_bucket,
  c.effective_maturity_date, {bucket_sql('c.effective_maturity_date')} AS effective_maturity_bucket,
  c.non_business_flow AS weekend_flow,
  CASE WHEN c.principal_amount IS NOT NULL THEN CAST(c.part_amount AS DECIMAL(22,4)) END AS principal_amount, c.principal_amount_2,
  c.forward_start_amount, c.forward_start_amount_2,
  CASE WHEN c.principal_amount IS NULL AND c.market_value IS NOT NULL THEN CAST(c.part_amount AS DECIMAL(22,4)) END AS market_value,
  CASE WHEN c.table_code <> 'I.A' THEN NULL
       WHEN c.lendable_value IS NOT NULL THEN c.lendable_value
       WHEN c.product_id IN ('I.A.4', 'I.A.7') THEN 0
       ELSE CAST(c.part_amount * (1 - {HAIRCUT}) AS DECIMAL(22,4)) END AS lendable_value,
  CASE WHEN c.table_code <> 'I.A' THEN NULL WHEN c.lendable_value IS NOT NULL THEN 'SOURCE (collateral system)'
       WHEN c.product_id IN ('I.A.4', 'I.A.7') THEN 'NOT LENDABLE' ELSE 'CALCULATED (pledge-venue haircut)' END AS lendable_basis,
  c.collateral_class, c.collateral_basis, col.hqla_level, col.is_hqla, CAST(c.collateral_value_calc AS DECIMAL(22,4)) AS collateral_value,
  c.collateral_level, c.encumbrance_type, CAST(c.risk_weight_pct / 100 AS DECIMAL(9,4)) AS risk_weight,
  -- Field Definitions p.30: Accounting Designation applies to I.A.1 / I.A.2; other I.A products report Not Applicable
  CASE WHEN c.product_id IN ('I.A.1', 'I.A.2') THEN c.accounting_designation WHEN c.product_id LIKE 'I.A.%' THEN 'Not Applicable' END AS accounting_designation,
  c.insured, c.insured_basis, c.trigger_flag, c.rehypothecated, c.unencumbered, c.treasury_control, c.settlement, c.netting_eligible,
  c.loss_absorbency, c.fx_option_direction, c.collection_reference, c.product_reference, c.sub_product_reference, c.business_line,
  c.internal_rating, c.interest_rate, c.link_id, current_timestamp() AS enrichment_timestamp
FROM v_settled c LEFT JOIN {R}.ref_collateral col ON col.collateral_class = c.collateral_class
""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Holds - customers awaiting approval, positions no rule classifies

# COMMAND ----------

spark.sql(f"DELETE FROM {CATALOG}.dq.pid_exceptions WHERE as_of_date = '{AS_OF}'")
spark.sql(f"""
INSERT INTO {CATALOG}.dq.pid_exceptions
SELECT d.as_of_date, d.record_id, CONCAT(d.record_id, '#', d.part),
  CASE WHEN d.customer_pending THEN 'CUSTOMER_PENDING' ELSE 'NO_RULE' END, d.booking_entity, d.product_id,
  d.source_feed, d.source_system, d.source_product_code, d.standard_product_type, d.product_subtype, d.flow_direction,
  d.customer_id, d.collateral_id,
  CASE WHEN d.customer_pending THEN CONCAT('Customer ', d.customer_id, ' is onboarded but its FR 2052a classification is not approved yet')
       ELSE CONCAT('No PID rule matched standard product type ', COALESCE(d.standard_product_type, 'NULL'), ' (subtype ',
                   COALESCE(d.product_subtype, 'NULL'), ', direction ', COALESCE(d.flow_direction, 'NULL'), ', counterparty ',
                   COALESCE(d.counterparty, 'NULL'), ', collateral ', COALESCE(d.collateral_class, 'NULL'), ')') END,
  CAST(COALESCE(d.part_amount, 0) * COALESCE(fx.rate_to_usd, 1) AS DECIMAL(22,4)),
  TO_JSON(STRUCT(d.*)), 'OPEN', current_timestamp()
FROM v_derived d LEFT JOIN {R}.ref_fx_rates fx ON fx.currency_code = d.currency
WHERE d.product_id IS NULL OR d.customer_pending
""")
display(spark.sql(f"SELECT exception_type, record_id, reason, amount_usd FROM {CATALOG}.dq.pid_exceptions WHERE as_of_date = '{AS_OF}'"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Reporting-entity scope: elimination and Internal Counterparty

# COMMAND ----------

les = {r.legal_entity_id: r for r in spark.table(f"{R}.ref_legal_entity").collect()}
def descendants(root):
    out, frontier = {root}, [root]
    while frontier:
        nxt = [l for l, r in les.items() if r.parent_legal_entity_id in frontier and l not in out]
        out.update(nxt)
        frontier = nxt
    return out
scope_rows = []
for e in spark.table(f"{R}.ref_reporting_entity").collect():
    members = descendants(e.root_legal_entity_id) if e.scope_type == "CONSOLIDATED" else {e.root_legal_entity_id}
    scope_rows += [(e.entity_id, m) for m in members]
spark.createDataFrame(scope_rows, "reporting_entity STRING, legal_entity_id STRING").createOrReplaceTempView("v_scope")
spark.createDataFrame([(k, v.legal_name) for k, v in les.items()], "legal_entity_id STRING, legal_name STRING").createOrReplaceTempView("v_le")

spark.sql(f"""
CREATE OR REPLACE TEMP VIEW v_entity AS
SELECT re.entity_id AS reporting_entity, f.*,
  CASE WHEN f.affiliate_legal_entity_id IS NULL THEN 'EXTERNAL'
       WHEN f.affiliate_legal_entity_id = f.booking_entity THEN 'SELF'
       WHEN sa.legal_entity_id IS NOT NULL THEN 'INTERCOMPANY'
       ELSE 'INTERNAL' END AS relationship
FROM {CATALOG}.conformed.fact_liquidity_position f
CROSS JOIN {R}.ref_reporting_entity re
LEFT JOIN v_scope sb ON sb.reporting_entity = re.entity_id AND sb.legal_entity_id = f.booking_entity
LEFT JOIN v_scope sa ON sa.reporting_entity = re.entity_id AND sa.legal_entity_id = f.affiliate_legal_entity_id
WHERE f.as_of_date = '{AS_OF}'
  AND ((f.report_for_entity IS NULL AND sb.legal_entity_id IS NOT NULL) OR f.report_for_entity = re.entity_id)""")

spark.sql(f"DELETE FROM {CATALOG}.conformed.entity_position WHERE as_of_date = '{AS_OF}'")
spark.sql(f"""
INSERT INTO {CATALOG}.conformed.entity_position
SELECT v.as_of_date, v.reporting_entity, v.position_id, v.relationship, v.relationship IN ('INTERNAL', 'SELF'),
       CASE WHEN v.relationship IN ('INTERNAL', 'SELF') THEN le.legal_name ELSE v.subsidiary_entity END
FROM v_entity v LEFT JOIN v_le le ON le.legal_entity_id = v.affiliate_legal_entity_id
WHERE v.relationship <> 'INTERCOMPANY'""")
spark.sql(f"DELETE FROM {CATALOG}.audit.intercompany_elimination WHERE as_of_date = '{AS_OF}'")
spark.sql(f"""
INSERT INTO {CATALOG}.audit.intercompany_elimination
SELECT v.as_of_date, v.reporting_entity, v.position_id, v.booking_entity, v.affiliate_legal_entity_id, v.product_id,
       CAST(COALESCE(v.principal_amount, v.market_value, 0) * COALESCE(fx.rate_to_usd, 1) AS DECIMAL(22,4)), current_timestamp()
FROM v_entity v LEFT JOIN {R}.ref_fx_rates fx ON fx.currency_code = v.currency
WHERE v.relationship = 'INTERCOMPANY'""")
display(spark.sql(f"""SELECT reporting_entity, relationship, COUNT(*) AS positions FROM v_entity GROUP BY ALL ORDER BY 1, 2"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Rule usage, coverage and accuracy

# COMMAND ----------

spark.sql(f"DELETE FROM {CATALOG}.audit.pid_rule_usage WHERE as_of_date = '{AS_OF}'")
spark.sql(f"""
INSERT INTO {CATALOG}.audit.pid_rule_usage
SELECT as_of_date, pid_rule_id, standard_product_type, product_id, COUNT(*), current_timestamp()
FROM v_derived WHERE pid_rule_id IS NOT NULL GROUP BY ALL""")

# Held customers are expected holds, not derivation errors. Each record is compared as a whole: the set of
# (part, PID) it was split into must equal the expected set, so a wrong split counts as a mismatch.
spark.sql(f"""CREATE OR REPLACE TEMP VIEW v_accuracy AS
WITH got AS (SELECT record_id, ARRAY_SORT(COLLECT_LIST(CONCAT(part, '=', COALESCE(product_id, 'none')))) AS parts
             FROM v_derived WHERE NOT customer_pending GROUP BY record_id),
want AS (SELECT record_id, ARRAY_SORT(COLLECT_LIST(CONCAT(part, '=', COALESCE(expected_product_id, 'none')))) AS parts
         FROM {CATALOG}.audit.pid_answer_key WHERE as_of_date = '{AS_OF}' GROUP BY record_id)
SELECT g.record_id, g.parts AS derived_parts, w.parts AS expected_parts FROM got g JOIN want w USING (record_id)""")
acc = spark.sql("SELECT COUNT(*) AS checked, SUM(CASE WHEN derived_parts <> expected_parts THEN 1 ELSE 0 END) AS mismatches FROM v_accuracy").first()
positions = spark.sql("SELECT COUNT(*) AS n FROM v_derived").first().n
derived = spark.sql("SELECT COUNT(*) AS n FROM v_derived WHERE product_id IS NOT NULL AND NOT customer_pending").first().n
accuracy = 100.0 * (acc.checked - acc.mismatches) / acc.checked if acc.checked else None
spark.sql(f"DELETE FROM {CATALOG}.audit.pid_derivation_summary WHERE as_of_date = '{AS_OF}'")
spark.sql(f"""INSERT INTO {CATALOG}.audit.pid_derivation_summary VALUES
  ('{AS_OF}', {src_count}, {positions}, {derived}, {positions - derived}, {acc.checked}, {acc.mismatches},
   {accuracy if accuracy is not None else 'NULL'}, current_timestamp())""")
entity_rows = spark.sql(f"SELECT COUNT(*) AS n FROM {CATALOG}.conformed.entity_position WHERE as_of_date = '{AS_OF}'").first().n
spark.sql(f"""INSERT INTO {CATALOG}.audit.data_lineage VALUES
  ('{AS_OF}', 'Calculation & PID', 'Source positions -> Silver positions', 'conformed.source_position', 'conformed.fact_liquidity_position',
   {src_count}, {derived}, current_timestamp()),
  ('{AS_OF}', 'Entity scoping', 'Silver -> reporting entities', 'conformed.fact_liquidity_position', 'conformed.entity_position',
   {derived}, {entity_rows}, current_timestamp())""")
print(f"{src_count} records -> {positions} position parts -> {derived} with a PID; {positions - derived} held; "
      f"answer key: {acc.checked} records checked, {acc.mismatches} mismatch(es); {entity_rows} entity positions")
if acc.mismatches:
    display(spark.sql("SELECT * FROM v_accuracy WHERE derived_parts <> expected_parts"))
    raise AssertionError(f"PID derivation disagrees with the answer key for {acc.mismatches} record(s)")

# COMMAND ----------

display(spark.sql(f"""
SELECT table_code, COUNT(*) AS positions, COUNT(DISTINCT product_id) AS products, COUNT(DISTINCT pid_rule_id) AS rules_used,
       SUM(CASE WHEN maturity_basis <> 'CONTRACTUAL' THEN 1 ELSE 0 END) AS calculated_maturities,
       SUM(CASE WHEN part <> '1' THEN 1 ELSE 0 END) AS split_parts, SUM(CASE WHEN maturity_bucket IS NULL THEN 1 ELSE 0 END) AS unbucketed
FROM {CATALOG}.conformed.fact_liquidity_position WHERE as_of_date = '{AS_OF}' GROUP BY table_code ORDER BY table_code"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Analyst corrections
# MAGIC Re-apply the corrections an analyst made to this day's positions (step 4 of the app), so a full re-run keeps them.

# COMMAND ----------

print(dbutils.notebook.run("./14_Apply_Corrections", 1800, {"as_of_date": AS_OF, "catalog": CATALOG, "pull": "false"}))
