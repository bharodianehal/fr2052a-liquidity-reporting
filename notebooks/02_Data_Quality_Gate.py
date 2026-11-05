# Databricks notebook source
# MAGIC %md
# MAGIC # Data Quality Gate: Bronze -> conformed.source_position (v9)
# MAGIC ## Owned by: Data Quality / Governance Team
# MAGIC
# MAGIC Runs daily for one `as_of_date`:
# MAGIC 0. **Feed completeness** (data contracts): records per feed vs the trailing 5-day median -> `dq.feed_monitor`.
# MAGIC 1. Harmonizes the six position feeds (`raw.deposits`, `loans`, `securities`, `derivatives`, `funding`, `finance`).
# MAGIC 2. Runs the rules in `reference.rules_dq` - each rule's `fail_predicate` is SQL over the staging view, so rules are
# MAGIC    data, not code. ERROR rules quarantine records (`dq.quarantine`); DQ_010 collapses duplicates; WARNING rules only report.
# MAGIC    The referential rules check the keys the PID derivation depends on: source product code, customer, collateral.
# MAGIC 3. Promotes clean records to `conformed.source_position` with Y/N flags typed as booleans. Notebook 03 derives the
# MAGIC    PID and enriches them into Silver.

# COMMAND ----------

# MAGIC %pip install -q psycopg2-binary

# COMMAND ----------

dbutils.widgets.text("as_of_date", "2026-02-27")
dbutils.widgets.text("catalog", "")
AS_OF = dbutils.widgets.get("as_of_date")
CATALOG = dbutils.widgets.get("catalog")
REG_VERSION = "6G"
spark.sql(f"USE CATALOG {CATALOG}")
print(f"DQ Gate for {AS_OF}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 0. Feed completeness
# MAGIC A feed below 80% of its trailing 5-day median (or missing) is a FAIL that the business review must clear; below 90% a WARNING.

# COMMAND ----------

from pyspark.sql import functions as F

ALL_FEEDS = ["deposits", "loans", "securities", "derivatives", "funding", "finance", "comments", "gl_balances", "customers", "collateral_links"]
mon = []
for feed in ALL_FEEDS:
    hist = spark.sql(f"""SELECT as_of_date, COUNT(*) AS n, MAX(_ingested_at) AS arrived FROM {CATALOG}.raw.{feed}
                         WHERE as_of_date <= '{AS_OF}' GROUP BY as_of_date ORDER BY as_of_date DESC LIMIT 6""").collect()
    today = next((h for h in hist if str(h.as_of_date) == AS_OF), None)
    prior = sorted(h.n for h in hist if str(h.as_of_date) != AS_OF)[:5]
    expected = float(prior[len(prior) // 2]) if prior else None
    n = today.n if today else 0
    ratio = (n / expected) if expected else None
    status = "MISSING" if n == 0 and feed not in ("comments", "collateral_links") else (
        "FAIL" if ratio is not None and ratio < 0.8 else ("WARNING" if ratio is not None and ratio < 0.9 else "PASS"))
    mon.append((AS_OF, feed, 1 if today else 0, n, expected, ratio, today.arrived if today else None, status,
                f"{n} records vs trailing median {expected:.0f}" if expected else f"{n} records (no history)"))
spark.sql(f"DELETE FROM {CATALOG}.dq.feed_monitor WHERE as_of_date = '{AS_OF}'")
(spark.createDataFrame(mon, "as_of_date STRING, feed STRING, files INT, records INT, expected_records DOUBLE, ratio DOUBLE, last_arrival TIMESTAMP, status STRING, details STRING")
 .withColumn("as_of_date", F.to_date("as_of_date")).withColumn("ratio", F.col("ratio").cast("decimal(9,4)"))
 .withColumn("run_timestamp", F.current_timestamp()).write.mode("append").saveAsTable(f"{CATALOG}.dq.feed_monitor"))
for m in mon:
    print(f"  {m[1]:17s} {m[7]:8s} {m[8]}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Stage the Bronze feeds for the date

# COMMAND ----------

from datetime import datetime
from decimal import Decimal
from pyspark.sql import functions as F

FEEDS = ["deposits", "loans", "securities", "derivatives", "funding", "finance"]
COLUMNS = [c for c in spark.table(f"{CATALOG}.raw.deposits").columns if not c.startswith("_")]
staging = None
for feed in FEEDS:
    df = (spark.table(f"{CATALOG}.raw.{feed}").where(F.col("as_of_date") == AS_OF)
          .select(*COLUMNS).withColumn("source_feed", F.lit(feed)))
    staging = df if staging is None else staging.unionByName(df)
# Analyst fixes of quarantined records (app step 2, Data quality): applied to the staged Bronze values before the rules run, so a
# fixed record passes and flows into Silver. Bronze itself stays as received; the fix is logged in dq.record_fixes.
spark.sql(f"""CREATE TABLE IF NOT EXISTS {CATALOG}.dq.record_fixes (
  fix_id STRING, as_of_date DATE, record_id STRING, source_feed STRING, field STRING, old_value STRING, new_value STRING, reason STRING,
  preparer STRING, created_at TIMESTAMP, status STRING
) COMMENT 'Analyst fixes of quarantined source records (app step 2); applied by notebook 02 before the DQ rules'""")
try:
    import psycopg2
    from databricks.sdk import WorkspaceClient
    _w, _ep = WorkspaceClient(), "projects/fr2052a/branches/production/endpoints/primary"
    _c = psycopg2.connect(host=_w.api_client.do("GET", f"/api/2.0/postgres/{_ep}")["status"]["hosts"]["host"], port=5432, database="fr2052a",
                          user=_w.current_user.me().user_name, sslmode="require",
                          password=_w.api_client.do("POST", "/api/2.0/postgres/credentials", body={"endpoint": _ep})["token"])
    with _c.cursor() as cur:
        cur.execute("SELECT fix_id, as_of_date, record_id, source_feed, field, old_value, new_value, reason, preparer, created_at, status FROM dq_fixes WHERE as_of_date = %s", (AS_OF,))
        _fix_rows = cur.fetchall()
    _c.close()
except Exception as e:
    _fix_rows = []
    print(f"no fixes read from Lakebase ({str(e)[:100]})")
if _fix_rows:
    spark.createDataFrame(_fix_rows, spark.table(f"{CATALOG}.dq.record_fixes").schema).createOrReplaceTempView("v_fix")
    spark.sql(f"""MERGE INTO {CATALOG}.dq.record_fixes t USING v_fix s ON t.fix_id = s.fix_id
                  WHEN MATCHED THEN UPDATE SET status = s.status WHEN NOT MATCHED THEN INSERT *""")
fixes = spark.sql(f"""SELECT * FROM {CATALOG}.dq.record_fixes WHERE as_of_date = '{AS_OF}' AND status NOT IN ('WITHDRAWN', 'RETIRED')
                      QUALIFY ROW_NUMBER() OVER (PARTITION BY record_id, field ORDER BY created_at DESC) = 1""").collect()
types = dict(staging.dtypes)
# An override retires when the source is fixed: if the record now arrives with the corrected value, the fix is no longer applied.
retired = []
for fx in fixes:
    if fx.field in types and fx.field != "record_id" and fx.new_value not in (None, ""):
        cur_v = staging.filter(F.col("record_id") == fx.record_id).select(F.col(fx.field).cast("string").alias("v")).first()
        if cur_v is not None and cur_v.v == str(fx.new_value) and fx.old_value != fx.new_value and fx.status != "RETIRED":
            retired.append(fx)
if retired:
    print(f"Retired {len(retired)} override(s) - the source now sends the corrected value: " + ", ".join(f"{f.record_id}.{f.field}" for f in retired))
    try:
        _c = psycopg2.connect(host=_w.api_client.do("GET", f"/api/2.0/postgres/{_ep}")["status"]["hosts"]["host"], port=5432, database="fr2052a",
                              user=_w.current_user.me().user_name, sslmode="require",
                              password=_w.api_client.do("POST", "/api/2.0/postgres/credentials", body={"endpoint": _ep})["token"])
        with _c.cursor() as cur:
            cur.execute("UPDATE dq_fixes SET status = 'RETIRED' WHERE fix_id = ANY(%s)", ([f.fix_id for f in retired],))
        _c.commit(); _c.close()
        spark.sql(f"UPDATE {CATALOG}.dq.record_fixes SET status = 'RETIRED' WHERE fix_id IN ({', '.join(repr(f.fix_id) for f in retired)})")
    except Exception as e:
        print(f"retirement not written back ({str(e)[:100]})")
    fixes = [f for f in fixes if f.fix_id not in {r.fix_id for r in retired}]
for fx in fixes:
    if fx.field in types and fx.field != "record_id":
        newv = F.lit(None).cast(types[fx.field]) if fx.new_value in (None, "") else F.lit(fx.new_value).cast(types[fx.field])
        staging = staging.withColumn(fx.field, F.when(F.col("record_id") == fx.record_id, newv).otherwise(F.col(fx.field)))
if fixes:
    print(f"Applied {len(fixes)} analyst fix(es) to staged records: " + ", ".join(f"{f.record_id}.{f.field}" for f in fixes))
    try:   # mark them applied for the app
        _c = psycopg2.connect(host=_w.api_client.do("GET", f"/api/2.0/postgres/{_ep}")["status"]["hosts"]["host"], port=5432, database="fr2052a",
                              user=_w.current_user.me().user_name, sslmode="require",
                              password=_w.api_client.do("POST", "/api/2.0/postgres/credentials", body={"endpoint": _ep})["token"])
        with _c.cursor() as cur:
            cur.execute("UPDATE dq_fixes SET status = 'APPLIED' WHERE fix_id = ANY(%s)", ([f.fix_id for f in fixes],))
        _c.commit(); _c.close()
        spark.sql(f"UPDATE {CATALOG}.dq.record_fixes SET status = 'APPLIED' WHERE fix_id IN ({', '.join(repr(f.fix_id) for f in fixes)})")
    except Exception as e:
        print(f"fix status not written back ({str(e)[:100]})")
staging.createOrReplaceTempView("v_dq_staging")
total = staging.count()
print(f"Staged {total} Bronze records: " + ", ".join(f"{r.source_feed}={r['count']}" for r in staging.groupBy("source_feed").count().collect()))
if total == 0:
    dbutils.notebook.exit(f"No Bronze records for {AS_OF}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Run the DQ rules

# COMMAND ----------

rules = spark.table(f"{CATALOG}.reference.rules_dq").where(f"reg_version = '{REG_VERSION}'").orderBy("rule_id").collect()
now = datetime.now()
results, quarantine_ids, failures = [], {}, []
for r in rules:
    predicate = r.fail_predicate.replace("{catalog}", CATALOG).replace("{as_of}", AS_OF)
    try:
        failing = spark.sql(f"SELECT record_id, source_feed FROM v_dq_staging WHERE {predicate}").collect()
        failures += [(AS_OF, r.rule_id, f.record_id, f.source_feed, r.severity, r.quarantine == "true") for f in failing]
        n_fail = len(failing)
        status = "PASS" if n_fail == 0 else ("FAIL" if r.severity == "ERROR" else "WARNING")
        sample = ", ".join(sorted({f.record_id for f in failing})[:5]) or None
        if n_fail and r.quarantine == "true":
            for f in failing:
                quarantine_ids.setdefault(f.record_id, []).append(r.rule_id)
        pass_rate = Decimal(str(round((total - n_fail) / total * 100, 2)))
        results.append((AS_OF, r.rule_id, r.rule_name, r.rule_category, r.severity, total, n_fail, pass_rate, sample, status, now))
        print(f"  {r.rule_id}: {status:7s} {n_fail:4d}  {r.rule_name}")
    except Exception as e:
        results.append((AS_OF, r.rule_id, r.rule_name, r.rule_category, r.severity, total, 0, Decimal("0"), str(e)[:500], "ERROR", now))
        print(f"  {r.rule_id}: ERROR {str(e)[:120]}")

# Every failing record per rule (ERROR and WARNING) - the record-level evidence behind assessment_results
spark.sql(f"DELETE FROM {CATALOG}.dq.rule_failures WHERE as_of_date = '{AS_OF}'")
if failures:
    (spark.createDataFrame(failures, "as_of_date STRING, rule_id STRING, record_id STRING, source_feed STRING, severity STRING, quarantined BOOLEAN")
     .withColumn("as_of_date", F.to_date("as_of_date")).withColumn("run_timestamp", F.lit(now))
     .write.mode("append").saveAsTable(f"{CATALOG}.dq.rule_failures"))
spark.sql(f"DELETE FROM {CATALOG}.dq.assessment_results WHERE as_of_date = '{AS_OF}'")
(spark.createDataFrame(results, "as_of_date STRING, rule_id STRING, rule_name STRING, rule_category STRING, severity STRING, "
                       "total_records INT, failed_records INT, pass_rate DECIMAL(5,2), sample_failures STRING, status STRING, run_timestamp TIMESTAMP")
 .withColumn("as_of_date", F.to_date("as_of_date"))
 .write.mode("append").saveAsTable(f"{CATALOG}.dq.assessment_results"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Quarantine, de-duplicate and promote to `conformed.source_position`

# COMMAND ----------

q_ids = spark.createDataFrame([(k, ",".join(v)) for k, v in quarantine_ids.items()] or [("", "")], "record_id STRING, failed_rules STRING") \
    .where("record_id <> ''")
quarantined = staging.join(q_ids, "record_id", "inner")
dupes = (staging.groupBy("record_id").count().where("count > 1").select("record_id"))
spark.sql(f"DELETE FROM {CATALOG}.dq.quarantine WHERE as_of_date = '{AS_OF}'")
(quarantined.select("as_of_date", "record_id", "source_feed", "source_product_code", "failed_rules",
                    F.to_json(F.struct(*COLUMNS)).alias("record_json"))
 .unionByName(staging.join(dupes, "record_id").dropDuplicates(["record_id"])
              .select("as_of_date", "record_id", "source_feed", "source_product_code", F.lit("DQ_010 (duplicate copy collapsed)").alias("failed_rules"),
                      F.to_json(F.struct(*COLUMNS)).alias("record_json")))
 .withColumn("run_timestamp", F.lit(now))
 .write.mode("append").saveAsTable(f"{CATALOG}.dq.quarantine"))

clean = staging.join(q_ids, "record_id", "left_anti").dropDuplicates(["record_id"])
clean.createOrReplaceTempView("v_clean")
clean_count = clean.count()
print(f"DQ gate: {clean_count} clean, {quarantined.count()} quarantined, {dupes.count()} duplicate ids collapsed")

# COMMAND ----------

flag = lambda c: f"CASE {c} WHEN 'Y' THEN true WHEN 'N' THEN false END AS {c}"
spark.sql(f"DELETE FROM {CATALOG}.conformed.source_position WHERE as_of_date = '{AS_OF}'")
spark.sql(f"""
INSERT INTO {CATALOG}.conformed.source_position
SELECT as_of_date, record_id, source_feed, source_system, booking_entity, report_for_entity, instrument_type,
  source_product_code, product_subtype, flow_direction, customer_id, collateral_id, subsidiary_entity, sub_product, sub_product_2,
  currency, currency_2, maturity_type, maturity_date, forward_start_date, effective_maturity_date,
  option_type, option_date, notice_days, funding_start_date, funding_end_date, draw_notice_days,
  reserve_requirement, service_type, operational_requirement, depositor_count, insurance_scheme,
  principal_amount, principal_amount_2, forward_start_amount, forward_start_amount_2, market_value, lendable_value, collateral_value,
  collateral_level, encumbrance_type, generic_issuer_type, generic_product, risk_weight AS risk_weight_pct, accounting_designation, insured,
  {flag('trigger_flag')}, {flag('rehypothecated')}, {flag('unencumbered')}, {flag('treasury_control')}, settlement, {flag('netting_eligible')},
  loss_absorbency, fx_option_direction, collection_reference, product_reference, sub_product_reference, business_line,
  internal_rating, interest_rate, link_id, 'PASS' AS dq_status, current_timestamp() AS dq_timestamp
FROM v_clean
""")
feed_list = "raw.{" + ",".join(FEEDS) + "}"
spark.sql(f"""INSERT INTO {CATALOG}.audit.data_lineage VALUES
  ('{AS_OF}', 'DQ Gate', 'Bronze -> DQ-passed source positions', '{feed_list}', 'conformed.source_position', {total}, {clean_count}, current_timestamp())""")
print(f"conformed.source_position: {clean_count} records for {AS_OF}")

# COMMAND ----------

display(spark.sql(f"""
SELECT source_feed, source_system, COUNT(*) AS records, COUNT(DISTINCT source_product_code) AS source_products
FROM {CATALOG}.conformed.source_position WHERE as_of_date = '{AS_OF}' GROUP BY ALL ORDER BY 1, 2"""))
