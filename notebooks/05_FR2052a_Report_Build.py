# Databricks notebook source
# MAGIC %md
# MAGIC # FR 2052a Report Build: entity positions -> the 13 data tables + Comments (v9)
# MAGIC ## Owned by: Regulatory Reporting Team
# MAGIC
# MAGIC 1. **Aggregate** each reporting entity's positions (`conformed.v_entity_position` - consolidated and solo, intercompany
# MAGIC    eliminated) into the 13 `reg_2052a` data tables on the **6G report key** (every field except the amounts; the
# MAGIC    Reporting Entity is part of the key). Seven currencies are reported natively, others converted to USD. Records
# MAGIC    rounding below 0.01 are not reported (p.24). Every filed record keeps its positions in `reg_2052a.record_lineage`.
# MAGIC 2. **S.L.6** per LCR entity from notebook 04; **Comments** from the reporting workbench feed.
# MAGIC 3. **Governed adjustments** approved in the app are applied on top (`reg_2052a.adjustments`).
# MAGIC 4. **FR Y-15 Schedule G** (STWF) items computed from the consolidated entity's data elements (Appendix VII) with MDRM codes.
# MAGIC 5. **Reconcile**: Silver per legal entity vs the GL; FR 2052a vs the LCR mart per LCR entity.

# COMMAND ----------

# MAGIC %pip install psycopg2-binary --quiet

# COMMAND ----------

dbutils.widgets.text("as_of_date", "2026-02-27")
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("lakebase_endpoint", "projects/fr2052a/branches/production/endpoints/primary")
dbutils.widgets.text("lakebase_db", "fr2052a")
AS_OF = dbutils.widgets.get("as_of_date")
CATALOG = dbutils.widgets.get("catalog")
spark.sql(f"USE CATALOG {CATALOG}")
EP = f"{CATALOG}.conformed.v_entity_position"

TABLE_ORDER = ["I.A", "I.U", "I.S", "I.O", "O.D", "O.W", "O.S", "O.O", "S.DC", "S.L", "S.B", "S.I", "S.FX"]
tables = {r.table_code: r for r in spark.table(f"{CATALOG}.reference.spec_tables").collect()}
fields = {}
for f in spark.table(f"{CATALOG}.reference.spec_table_fields").orderBy("table_code", "seq").collect():
    fields.setdefault(f.table_code, []).append(f)
NATIVE = [r.currency_code for r in spark.table(f"{CATALOG}.reference.ref_fx_rates").where("is_fr2052a_currency").collect()]
NATIVE_SQL = ", ".join(f"'{c}'" for c in NATIVE)
entity_cols = set(spark.table(EP).columns)
n = spark.sql(f"SELECT COUNT(*) AS n FROM {EP} WHERE as_of_date = '{AS_OF}'").first().n
print(f"Report build for {AS_OF}: {n} entity positions; native currencies {NATIVE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Aggregate into the data tables on the 6G report key (+ drill-down lineage)

# COMMAND ----------

# Gold column -> position column where the names differ; S.FX legs 1 / 2
SILVER_SRC = {"maturity_amount": "principal_amount", "maturity_amount_currency_1": "principal_amount",
              "maturity_amount_currency_2": "principal_amount_2", "forward_start_amount_currency_1": "forward_start_amount",
              "forward_start_amount_currency_2": "forward_start_amount_2", "currency_1": "currency"}
LEG2 = {"maturity_amount_currency_2", "forward_start_amount_currency_2", "currency_2"}
RATIO_PIDS = "('S.L.6', 'S.L.10')"
PRIMARY = {code: tables[code].primary_amount_column for code in TABLE_ORDER}

def native(ccy):
    return f"{ccy} IN ({NATIVE_SQL})"

def gold_select(code):
    """(key expressions, amount expressions) for one table."""
    keys, amounts = [], []
    for f in fields[code]:
        col = f.column_name
        ccy = "f.currency_2" if col in LEG2 else "f.currency"
        rate = "fx2.rate_to_usd" if col in LEG2 else "fx1.rate_to_usd"
        if f.data_type == "numeric":
            src = f"f.{SILVER_SRC.get(col, col)}"
            amounts.append((col, f"CASE WHEN f.product_id IN {RATIO_PIDS} OR {native(ccy)} THEN {src} ELSE {src} * {rate} END"))
        elif col in ("currency", "currency_1", "currency_2"):
            keys.append((col, f"CASE WHEN {ccy} IS NULL OR {native(ccy)} THEN {ccy} ELSE 'USD' END"))
        elif col == "converted":
            keys.append((col, f"NOT (f.product_id IN {RATIO_PIDS} OR {native('f.currency')})"))
        else:
            src = SILVER_SRC.get(col, col)
            if src not in entity_cols:
                raise ValueError(f"{code}.{col}: no entity-position column {src}")
            keys.append((col, f"f.{src}"))
    if code == "S.FX":
        keys.append(("converted_2", f"NOT {native('f.currency_2')}"))
    return keys, amounts

spark.sql(f"DELETE FROM {CATALOG}.reg_2052a.record_lineage WHERE as_of_date = '{AS_OF}'")
for code in TABLE_ORDER:
    t = tables[code]
    keys, amounts = gold_select(code)
    key_cols = [k for k, _ in keys]
    amount_cols = [a for a, _ in amounts]
    record_key = "SHA2(CONCAT_WS('|', " + ", ".join(f"COALESCE(CAST({k} AS STRING), '')" for k in key_cols) + "), 256)"
    # p.24: a record whose aggregate amount rounds to less than 0.01 (USD 10,000) is not reported; this also keeps
    # all-zero records out of the file (6G BR General #19)
    nonzero = " OR ".join(f"ABS(ROUND(COALESCE({a}, 0), 2)) >= 0.01" for a in amount_cols) or "true"
    spark.sql(f"""CREATE OR REPLACE TEMP VIEW v_rows AS
      SELECT f.as_of_date, f.position_id, f.record_id, {', '.join(f'{e} AS {c}' for c, e in keys + amounts)}
      FROM {EP} f
      LEFT JOIN {CATALOG}.reference.ref_fx_rates fx1 ON fx1.currency_code = f.currency
      LEFT JOIN {CATALOG}.reference.ref_fx_rates fx2 ON fx2.currency_code = f.currency_2
      WHERE f.as_of_date = '{AS_OF}' AND f.table_code = '{code}'""")
    spark.sql(f"CREATE OR REPLACE TEMP VIEW v_keyed AS SELECT *, {record_key} AS record_key FROM v_rows")
    spark.sql(f"DELETE FROM {CATALOG}.reg_2052a.{t.gold_table} WHERE as_of_date = '{AS_OF}'")
    spark.sql(f"""
    INSERT INTO {CATALOG}.reg_2052a.{t.gold_table} (as_of_date, {', '.join(key_cols + amount_cols)}, record_count, record_key)
    WITH agg AS (
      SELECT as_of_date, {', '.join(key_cols)}, record_key,
             {', '.join(f'CAST(ROUND(SUM({a}), 8) AS DECIMAL(26,8)) AS {a}' for a in amount_cols)}, COUNT(*) AS record_count
      FROM v_keyed GROUP BY as_of_date, {', '.join(key_cols)}, record_key
    )
    SELECT as_of_date, {', '.join(key_cols + amount_cols)}, CAST(record_count AS INT), record_key FROM agg WHERE {nonzero}""")
    spark.sql(f"""
    INSERT INTO {CATALOG}.reg_2052a.record_lineage
    SELECT k.as_of_date, k.reporting_entity, '{code}', k.record_key, k.position_id, k.record_id, CAST(k.{PRIMARY[code]} AS DECIMAL(26,8)),
           current_timestamp()
    FROM v_keyed k JOIN {CATALOG}.reg_2052a.{t.gold_table} g ON g.as_of_date = k.as_of_date AND g.record_key = k.record_key""")

# S.L.6 Liquidity Coverage Ratio per LCR entity (decimal with four points of precision, p.71)
spark.sql(f"""
INSERT INTO {CATALOG}.reg_2052a.s_l_liquidity_risk_measurement
  (as_of_date, reporting_entity, product_id, market_value, internal, currency, converted, record_count, record_key)
SELECT as_of_date, entity_id, 'S.L.6', CAST(ROUND(lcr_ratio, 4) AS DECIMAL(26,8)), false, 'USD', false, 1,
       SHA2(CONCAT_WS('|', entity_id, 'S.L.6'), 256)
FROM {CATALOG}.reg_lcr.calculation_results WHERE as_of_date = '{AS_OF}' AND lcr_ratio IS NOT NULL""")

# Comments table (S.C) from the regulatory reporting workbench feed
spark.sql(f"DELETE FROM {CATALOG}.reg_2052a.s_c_comments WHERE as_of_date = '{AS_OF}'")
spark.sql(f"""
INSERT INTO {CATALOG}.reg_2052a.s_c_comments (as_of_date, reporting_entity, collection, product_id, sub_product, comments, record_count, record_key)
SELECT as_of_date, reporting_entity, collection, product_id, sub_product, comments, 1,
       SHA2(CONCAT_WS('|', reporting_entity, collection, COALESCE(product_id, ''), COALESCE(sub_product, ''), comments), 256)
FROM {CATALOG}.raw.comments WHERE as_of_date = '{AS_OF}'
UNION ALL   -- AI-drafted comments a reviewer accepted in the app (notebook 00 brings the decision into Delta)
SELECT as_of_date, get_json_object(suggestion, '$.reporting_entity'), get_json_object(suggestion, '$.collection'),
       get_json_object(suggestion, '$.product_id'), NULL, get_json_object(suggestion, '$.comments'), 1,
       SHA2(CONCAT_WS('|', 'AI', suggestion_id), 256)
FROM {CATALOG}.ai_assist.suggestions WHERE as_of_date = '{AS_OF}' AND suggestion_type = 'COMMENT_DRAFT' AND status = 'ACCEPTED'""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Governed adjustments (posted and approved in the app)
# MAGIC An adjustment adds an amount to one value of one filed record; the preparer and the approver must differ. Approved
# MAGIC adjustments are read from Lakebase, kept in `reg_2052a.adjustments` and applied here; the record's lineage then shows
# MAGIC the positions plus the adjustment.

# COMMAND ----------

try:
    import psycopg2
    from databricks.sdk import WorkspaceClient
    _w = WorkspaceClient()
    _ep = dbutils.widgets.get("lakebase_endpoint")
    _conn = psycopg2.connect(host=_w.api_client.do("GET", f"/api/2.0/postgres/{_ep}")["status"]["hosts"]["host"], port=5432,
                             database=dbutils.widgets.get("lakebase_db"), user=_w.current_user.me().user_name, sslmode="require",
                             password=_w.api_client.do("POST", "/api/2.0/postgres/credentials", body={"endpoint": _ep})["token"])
    with _conn.cursor() as cur:
        cur.execute("""SELECT adjustment_id, as_of_date, reporting_entity, table_code, record_key, column_name, amount, reason, preparer,
                              approver, status, created_at, decided_at FROM adjustments WHERE as_of_date = %s""", (AS_OF,))
        app_adj = cur.fetchall()
    _conn.close()
except Exception as e:   # first run: no Lakebase table yet
    app_adj = []
    print(f"No adjustments read from Lakebase ({str(e)[:120]})")
if app_adj:
    spark.createDataFrame(app_adj, """adjustment_id STRING, as_of_date DATE, reporting_entity STRING, table_code STRING, record_key STRING,
        column_name STRING, amount DECIMAL(26,8), reason STRING, preparer STRING, approver STRING, status STRING, created_at TIMESTAMP,
        decided_at TIMESTAMP""").createOrReplaceTempView("v_app_adj")
    spark.sql(f"""MERGE INTO {CATALOG}.reg_2052a.adjustments t USING v_app_adj s ON t.adjustment_id = s.adjustment_id
                  WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *""")
applied = 0
for a in spark.sql(f"""SELECT * FROM {CATALOG}.reg_2052a.adjustments WHERE as_of_date = '{AS_OF}' AND status = 'APPROVED'
                       AND approver IS NOT NULL AND approver <> preparer""").collect():
    gt = tables[a.table_code].gold_table
    spark.sql(f"""UPDATE {CATALOG}.reg_2052a.{gt} SET {a.column_name} = {a.column_name} + {a.amount},
                  adjustment_ids = CONCAT_WS(',', adjustment_ids, '{a.adjustment_id}')
                  WHERE as_of_date = '{AS_OF}' AND record_key = '{a.record_key}'""")
    spark.sql(f"""INSERT INTO {CATALOG}.reg_2052a.record_lineage VALUES ('{AS_OF}', '{a.reporting_entity}', '{a.table_code}',
                  '{a.record_key}', 'ADJ:{a.adjustment_id}', NULL, {a.amount}, current_timestamp())""")
    applied += 1
print(f"{len(app_adj)} adjustment(s) read from the app; {applied} approved adjustment(s) applied")

counts = spark.sql(f"""SELECT reporting_entity, table_code, COUNT(*) AS records, SUM(record_count) AS positions
FROM {CATALOG}.reg_2052a.v_filing_records WHERE as_of_date = '{AS_OF}' GROUP BY ALL ORDER BY 1, 2""")
display(counts)
total_records = spark.sql(f"SELECT COUNT(*) AS n FROM {CATALOG}.reg_2052a.v_filing_records WHERE as_of_date = '{AS_OF}'").first().n
spark.sql(f"""INSERT INTO {CATALOG}.audit.data_lineage VALUES ('{AS_OF}', 'Report Build', 'Entity positions -> FR 2052a tables',
  'conformed.v_entity_position', 'reg_2052a (13 data tables + comments)', {n}, {total_records}, current_timestamp())""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. FR Y-15 Schedule G - short-term wholesale funding (Appendix VII), with MDRM codes
# MAGIC Columns by remaining maturity: A <= 30 days (incl. Open), B 31-90, C 91-180, D 181-365. The weighted amount applies
# MAGIC the 12 CFR 217.406 category weight (tier) and maturity weight (A 100%, B 75%, C 50%, D 25%).

# COMMAND ----------

stwf = spark.table(f"{CATALOG}.reference.rules_stwf_appendix_vii").collect()
STWF_FIRM = "ENT001"   # the FR Y-15 filer: the consolidated BHC
parts = []
for r in stwf:
    pids = ", ".join(f"'{p}'" for p in r.product_ids.split(","))
    amount = SILVER_SRC.get(r.amount_column, r.amount_column)
    parts.append(f"""SELECT '{r.stwf_item}' AS stwf_item, '{r.item_name.replace("'", "''")}' AS item_name, f.position_id, f.maturity_days,
        f.maturity_type, CAST(f.{amount} AS DOUBLE) * COALESCE(fx.rate_to_usd, 1) AS amount_usd, {r.tier_weight} AS tier_weight
      FROM (SELECT * FROM {EP} WHERE as_of_date = '{AS_OF}' AND reporting_entity = '{STWF_FIRM}') f
      LEFT JOIN {CATALOG}.reference.ref_fx_rates fx ON fx.currency_code = f.currency
      WHERE f.product_id IN ({pids}) AND ({r.condition_sql})""")
spark.sql(f"""CREATE OR REPLACE TEMP VIEW v_stwf AS
  SELECT *, CASE WHEN maturity_type = 'OPEN' OR maturity_days <= 30 THEN 'A' WHEN maturity_days <= 90 THEN 'B'
                 WHEN maturity_days <= 180 THEN 'C' WHEN maturity_days <= 365 THEN 'D' END AS maturity_column
  FROM ({' UNION ALL '.join(parts)})""")
spark.sql(f"DELETE FROM {CATALOG}.reg_2052a.stwf_schedule_g WHERE as_of_date = '{AS_OF}'")
spark.sql(f"""
INSERT INTO {CATALOG}.reg_2052a.stwf_schedule_g
WITH items AS (
  SELECT stwf_item, FIRST(item_name) AS item_name, maturity_column, SUM(amount_usd) AS amount_usd,
         SUM(amount_usd * tier_weight * CASE maturity_column WHEN 'A' THEN 1.0 WHEN 'B' THEN 0.75 WHEN 'C' THEN 0.5 ELSE 0.25 END) AS weighted,
         COUNT(*) AS records
  FROM v_stwf WHERE maturity_column IS NOT NULL GROUP BY stwf_item, maturity_column),
totals AS (
  SELECT CONCAT(SUBSTR(stwf_item, 1, 1), ' total') AS stwf_item, CONCAT('Tier ', SUBSTR(stwf_item, 1, 1), ' total') AS item_name,
         maturity_column, SUM(amount_usd), SUM(weighted), SUM(records)
  FROM items WHERE SUBSTR(stwf_item, 1, 1) IN ('1', '2', '3') GROUP BY ALL)
SELECT DATE'{AS_OF}', '{STWF_FIRM}', x.stwf_item, x.item_name, x.maturity_column, m.mdrm, CAST(x.amount_usd AS DECIMAL(22,4)),
       CAST(x.weighted AS DECIMAL(22,4)), CAST(x.records AS INT), current_timestamp()
FROM (SELECT * FROM items UNION ALL SELECT * FROM totals) x
LEFT JOIN {CATALOG}.reference.ref_stwf_mdrm m ON m.stwf_item = x.stwf_item AND m.maturity_column = x.maturity_column""")
display(spark.sql(f"""SELECT stwf_item, item_name, maturity_column, mdrm, amount_usd, weighted_amount_usd, records
FROM {CATALOG}.reg_2052a.stwf_schedule_g WHERE as_of_date = '{AS_OF}' ORDER BY stwf_item, maturity_column"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Reconciliation
# MAGIC * **GL**: Silver per legal entity and table (USD, before elimination) vs the GL control totals; breaks above 0.5% fail
# MAGIC   and must be explained in the business review.
# MAGIC * **FR 2052a vs LCR** per LCR entity: the HQLA-eligible I.A market value and the reported S.L.6 vs the LCR mart.

# COMMAND ----------

spark.sql(f"DELETE FROM {CATALOG}.audit.gl_reconciliation WHERE as_of_date = '{AS_OF}'")
spark.sql(f"""
INSERT INTO {CATALOG}.audit.gl_reconciliation
WITH filing AS (
  SELECT f.booking_entity, f.table_code,
         SUM(COALESCE(CASE WHEN f.table_code IN ('I.A', 'S.DC', 'S.L', 'S.I', 'S.B') THEN f.market_value ELSE f.principal_amount END, 0)
             * COALESCE(fx.rate_to_usd, 1)) AS pipeline_total
  FROM {CATALOG}.conformed.fact_liquidity_position f
  LEFT JOIN {CATALOG}.reference.ref_fx_rates fx ON fx.currency_code = f.currency
  WHERE f.as_of_date = '{AS_OF}' AND f.product_id <> 'S.L.10' GROUP BY ALL
),
held AS (   -- positions held for customer approval are in the GL: reconciling items
  SELECT booking_entity, REGEXP_EXTRACT(provisional_product_id, '^(.*)\\\\.[0-9]+$', 1) AS table_code, SUM(amount_usd) AS held_usd
  FROM {CATALOG}.dq.pid_exceptions WHERE as_of_date = '{AS_OF}' AND exception_type = 'CUSTOMER_PENDING' GROUP BY ALL
)
SELECT g.as_of_date, g.legal_entity_id, CONCAT('GL vs ', g.legal_entity_id, ' ', g.table_code), g.gl_balance_usd,
       CAST(COALESCE(p.pipeline_total, 0) + COALESCE(h.held_usd, 0) AS DECIMAL(22,4)),
       CAST(COALESCE(p.pipeline_total, 0) + COALESCE(h.held_usd, 0) - g.gl_balance_usd AS DECIMAL(22,4)),
       CAST(100 * (COALESCE(p.pipeline_total, 0) + COALESCE(h.held_usd, 0) - g.gl_balance_usd) / NULLIF(g.gl_balance_usd, 0) AS DECIMAL(9,4)),
       CASE WHEN ABS(COALESCE(p.pipeline_total, 0) + COALESCE(h.held_usd, 0) - g.gl_balance_usd) <= 0.005 * ABS(g.gl_balance_usd) THEN 'PASS' ELSE 'BREAK' END,
       CONCAT(g.gl_account_group, ' (', g.source_system, ') - tolerance 0.5%',
              CASE WHEN h.held_usd IS NOT NULL THEN CONCAT('; includes ', ROUND(h.held_usd, 1), ' held for customer approval') ELSE '' END),
       current_timestamp()
FROM {CATALOG}.raw.gl_balances g LEFT JOIN filing p ON p.booking_entity = g.legal_entity_id AND p.table_code = g.table_code
LEFT JOIN held h ON h.booking_entity = g.legal_entity_id AND h.table_code = g.table_code
WHERE g.as_of_date = '{AS_OF}'""")

spark.sql(f"DELETE FROM {CATALOG}.audit.cross_metric_recon WHERE as_of_date = '{AS_OF}'")
for e in spark.table(f"{CATALOG}.reference.ref_reporting_entity").where("lcr_standalone").collect():
    E = e.entity_id
    spark.sql(f"""
    INSERT INTO {CATALOG}.audit.cross_metric_recon
    WITH lcr AS (SELECT * FROM {CATALOG}.reg_lcr.calculation_results WHERE as_of_date = '{AS_OF}' AND entity_id = '{E}'),
    hqla_lcr AS (SELECT SUM(amount_usd) AS v FROM {CATALOG}.reg_lcr.calculation_detail
                 WHERE as_of_date = '{AS_OF}' AND entity_id = '{E}' AND flow_direction = 'HQLA' AND product_id LIKE 'I.A.%'),
    ia AS (
      SELECT SUM(g.market_value * COALESCE(fx.rate_to_usd, 1)) AS v
      FROM {CATALOG}.reg_2052a.i_a_assets g
      JOIN {CATALOG}.reference.ref_collateral c ON c.collateral_class = g.collateral_class AND c.is_hqla
      LEFT JOIN {CATALOG}.reference.ref_fx_rates fx ON fx.currency_code = g.currency
      WHERE g.as_of_date = '{AS_OF}' AND g.reporting_entity = '{E}' AND g.product_id IN ('I.A.1', 'I.A.2', 'I.A.3')
        AND (g.treasury_control OR g.product_id = 'I.A.3')),
    sl6 AS (SELECT market_value AS v FROM {CATALOG}.reg_2052a.s_l_liquidity_risk_measurement
            WHERE as_of_date = '{AS_OF}' AND reporting_entity = '{E}' AND product_id = 'S.L.6')
    SELECT '{AS_OF}', '{E}', 'HQLA-eligible I.A market value (USD mm)', CAST((SELECT v FROM ia) AS DECIMAL(22,4)),
           CAST((SELECT v FROM hqla_lcr) AS DECIMAL(22,4)), CAST((SELECT v FROM ia) - (SELECT v FROM hqla_lcr) AS DECIMAL(22,4)),
           CASE WHEN ABS((SELECT v FROM ia) - (SELECT v FROM hqla_lcr)) < 0.01 THEN 'PASS' ELSE 'BREAK' END,
           'I.A.1-3 HQLA under treasury control in the filing vs LCR engine HQLA (pre-haircut)', current_timestamp()
    UNION ALL
    SELECT '{AS_OF}', '{E}', 'S.L.6 Liquidity Coverage Ratio', CAST((SELECT v FROM sl6) AS DECIMAL(22,4)),
           CAST(ROUND((SELECT lcr_ratio FROM lcr), 4) AS DECIMAL(22,4)), CAST((SELECT v FROM sl6) - ROUND((SELECT lcr_ratio FROM lcr), 4) AS DECIMAL(22,4)),
           CASE WHEN (SELECT v FROM sl6) = ROUND((SELECT lcr_ratio FROM lcr), 4) THEN 'PASS' ELSE 'BREAK' END,
           'Reported S.L.6 vs reg_lcr.calculation_results', current_timestamp()""")
display(spark.sql(f"""
SELECT recon_type AS check, gl_total AS expected, pipeline_total AS actual, difference_pct AS diff_pct, status
FROM {CATALOG}.audit.gl_reconciliation WHERE as_of_date = '{AS_OF}' AND status <> 'PASS'
UNION ALL
SELECT CONCAT(entity_id, ' ', metric_name), reg_lcr_value, reg_2052a_value, NULL, status FROM {CATALOG}.audit.cross_metric_recon WHERE as_of_date = '{AS_OF}'"""))
