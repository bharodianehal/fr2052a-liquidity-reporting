# Databricks notebook source
# MAGIC %md
# MAGIC # Apply position corrections (v9)
# MAGIC ## Owned by: Regulatory Reporting Team
# MAGIC
# MAGIC Corrections are made by an analyst in the app (step 4, Validation rules) on the most granular data we hold - a Silver
# MAGIC position - and stored in Lakebase with who, when, before -> after and the reason. This notebook brings them into Delta
# MAGIC (`reg_2052a.position_corrections`, the audit record) and applies them to `conformed.fact_liquidity_position`. It runs at
# MAGIC the start of `fr2052a-revalidate` (then 04 -> 05 -> 06 rebuild and re-check the day) and at the end of notebook 03, so a
# MAGIC full re-run of the day keeps the corrections.

# COMMAND ----------

# MAGIC %pip install -q psycopg2-binary

# COMMAND ----------

dbutils.widgets.text("as_of_date", "2026-02-27")
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("pull", "true")
dbutils.widgets.text("lakebase_endpoint", "projects/fr2052a/branches/production/endpoints/primary")
dbutils.widgets.text("lakebase_db", "fr2052a")
AS_OF, C = dbutils.widgets.get("as_of_date"), dbutils.widgets.get("catalog")
T = f"{C}.reg_2052a.position_corrections"
spark.sql(f"""CREATE TABLE IF NOT EXISTS {T} (
  correction_id STRING, as_of_date DATE, position_id STRING, record_key STRING, table_code STRING, field STRING, old_value STRING,
  new_value STRING, reason STRING, preparer STRING, created_at TIMESTAMP, status STRING, applied_at TIMESTAMP
) COMMENT 'Analyst corrections of Silver positions (step 4 of the app): before -> after, reason, who and when; applied by notebook 14'""")

# COMMAND ----------

import json
from datetime import datetime

def pg():
    import psycopg2
    from databricks.sdk import WorkspaceClient
    w, ep = WorkspaceClient(), dbutils.widgets.get("lakebase_endpoint")
    return psycopg2.connect(host=w.api_client.do("GET", f"/api/2.0/postgres/{ep}")["status"]["hosts"]["host"], port=5432,
                            database=dbutils.widgets.get("lakebase_db"), user=w.current_user.me().user_name, sslmode="require",
                            password=w.api_client.do("POST", "/api/2.0/postgres/credentials", body={"endpoint": ep})["token"])

if dbutils.widgets.get("pull") == "true":
    try:
        conn = pg()
        with conn.cursor() as cur:
            cur.execute("""SELECT correction_id, as_of_date, position_id, record_key, table_code, field, old_value, new_value, reason, preparer,
                                  created_at, status, applied_at FROM position_corrections WHERE as_of_date = %s""", (AS_OF,))
            rows = cur.fetchall()
        conn.close()
    except Exception as e:
        rows = []
        print(f"no corrections read from Lakebase ({str(e)[:120]})")
    if rows:
        spark.createDataFrame(rows, spark.table(T).schema).createOrReplaceTempView("v_corr")
        spark.sql(f"""MERGE INTO {T} t USING v_corr s ON t.correction_id = s.correction_id
                      WHEN MATCHED AND s.status = 'WITHDRAWN' THEN UPDATE SET status = 'WITHDRAWN'
                      WHEN NOT MATCHED THEN INSERT *""")
    print(f"{len(rows)} correction(s) in Lakebase for {AS_OF}")

# COMMAND ----------

# Apply the latest correction per position and field (withdrawn ones are skipped), cast to the column's type
types = {f.name: f.dataType.simpleString() for f in spark.table(f"{C}.conformed.fact_liquidity_position").schema.fields}
latest = spark.sql(f"""SELECT * FROM {T} WHERE as_of_date = '{AS_OF}' AND status <> 'WITHDRAWN'
                       QUALIFY ROW_NUMBER() OVER (PARTITION BY position_id, field ORDER BY created_at DESC) = 1""").collect()
applied = []
for c in latest:
    if c.field not in types:
        print(f"  skip {c.correction_id}: unknown field {c.field}")
        continue
    val = "NULL" if c.new_value in (None, "") else "CAST('" + str(c.new_value).replace("'", "''") + f"' AS {types[c.field]})"
    spark.sql(f"""UPDATE {C}.conformed.fact_liquidity_position SET {c.field} = {val}
                  WHERE as_of_date = '{AS_OF}' AND position_id = '{c.position_id}'""")
    if c.field == "product_id":   # the table follows the product
        spark.sql(f"""UPDATE {C}.conformed.fact_liquidity_position SET table_code = REGEXP_EXTRACT(product_id, '^(.*)\\\\.[0-9]+$', 1)
                      WHERE as_of_date = '{AS_OF}' AND position_id = '{c.position_id}'""")
    if c.field == "maturity_date":   # the maturity bucket follows the date
        spark.sql(f"""MERGE INTO {C}.conformed.fact_liquidity_position f
                      USING (SELECT p.position_id, DATEDIFF(p.maturity_date, p.as_of_date) AS d,
                                    MIN_BY(b.bucket_label, b.bucket_seq) AS bucket
                             FROM {C}.conformed.fact_liquidity_position p JOIN {C}.reference.ref_maturity_bucket b
                               ON b.is_standard AND DATEDIFF(p.maturity_date, p.as_of_date) BETWEEN b.day_start AND b.day_end
                             WHERE p.as_of_date = '{AS_OF}' AND p.position_id = '{c.position_id}' GROUP BY 1, 2) s
                      ON f.as_of_date = '{AS_OF}' AND f.position_id = s.position_id
                      WHEN MATCHED THEN UPDATE SET maturity_days = s.d, maturity_bucket = s.bucket""")
    if c.field == "maturity_date":   # the effective maturity follows when it was the corrected date
        spark.sql(f"""UPDATE {C}.conformed.fact_liquidity_position SET effective_maturity_date = maturity_date
                      WHERE as_of_date = '{AS_OF}' AND position_id = '{c.position_id}' AND effective_maturity_date = CAST('{c.old_value}' AS DATE)""")
    if c.field in ("maturity_date", "forward_start_date", "effective_maturity_date"):   # weekend flow, as notebook 03 derives it
        # a corrected date is the analyst's: it is not rolled, but a weekend or Federal Reserve holiday is flagged (Fed check PSV-01)
        hol = {r.holiday_date for r in spark.table(f"{C}.reference.ref_bank_holidays").collect()}
        p_ = spark.sql(f"""SELECT maturity_date, forward_start_date, effective_maturity_date FROM {C}.conformed.fact_liquidity_position
                           WHERE as_of_date = '{AS_OF}' AND position_id = '{c.position_id}'""").first()
        nb = any(d is not None and (d.weekday() >= 5 or d in hol) for d in (p_ or [None, None, None]))
        spark.sql(f"""UPDATE {C}.conformed.fact_liquidity_position SET weekend_flow = {str(nb).lower()}
                      WHERE as_of_date = '{AS_OF}' AND position_id = '{c.position_id}'""")
    applied.append(c.correction_id)
    print(f"  {c.position_id}.{c.field}: {c.old_value} -> {c.new_value}")
now = datetime.now()
if applied:
    ids = ", ".join(f"'{i}'" for i in applied)
    spark.sql(f"UPDATE {T} SET status = 'APPLIED', applied_at = current_timestamp() WHERE correction_id IN ({ids}) AND status <> 'APPLIED'")
    if dbutils.widgets.get("pull") == "true":
        try:
            conn = pg()
            with conn.cursor() as cur:
                cur.execute(f"UPDATE position_corrections SET status = 'APPLIED', applied_at = NOW() WHERE correction_id IN ({ids})")
            conn.commit(); conn.close()
        except Exception as e:
            print(f"status not written back ({str(e)[:120]})")
print(f"{len(applied)} correction(s) applied to {AS_OF}")
