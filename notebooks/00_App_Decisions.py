# Databricks notebook source
# MAGIC %md
# MAGIC # App decisions -> Delta (v9)
# MAGIC ## Owned by: Platform Engineering
# MAGIC
# MAGIC The people's decisions are made in the FR 2052a app and written to Lakebase. Before a day is (re)processed they are
# MAGIC brought into Delta, the system of record, so the pipeline uses them and the audit trail keeps them:
# MAGIC
# MAGIC | Lakebase (app) | Delta | Used by |
# MAGIC |---|---|---|
# MAGIC | `ai_decisions` | `ai_assist.suggestions` status / decided_by / decided_at | audit, evaluation (notebook 10), accepted comment drafts (notebook 05) |
# MAGIC | `customer_master_approvals` | `reference.customer_master_approvals` -> `v_customer_master` | enrichment (notebook 03) |
# MAGIC | `source_product_map_approvals` | `reference.source_product_map_approvals` -> `v_source_product_map` | DQ gate and enrichment (02, 03) |
# MAGIC
# MAGIC Adjustments and sign-off actions are read by notebooks 05 and 06.

# COMMAND ----------

# MAGIC %pip install -q psycopg2-binary

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("lakebase_endpoint", "projects/fr2052a/branches/production/endpoints/primary")
dbutils.widgets.text("lakebase_db", "fr2052a")
CATALOG = dbutils.widgets.get("catalog")

import psycopg2
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
ep = dbutils.widgets.get("lakebase_endpoint")

def merge(sql, tries=5):
    """The same decisions are merged by every daily run; runs for several dates at once can conflict - retry, the MERGE is idempotent."""
    import time
    for i in range(tries):
        try:
            return spark.sql(sql)
        except Exception as e:
            if "CONCURRENT" not in str(e).upper() or i == tries - 1:
                raise
            time.sleep(5 * (i + 1))

def pg_rows(sql):
    try:
        conn = psycopg2.connect(host=w.api_client.do("GET", f"/api/2.0/postgres/{ep}")["status"]["hosts"]["host"], port=5432,
                                database=dbutils.widgets.get("lakebase_db"), user=w.current_user.me().user_name, sslmode="require",
                                password=w.api_client.do("POST", "/api/2.0/postgres/credentials", body={"endpoint": ep})["token"])
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
        conn.close()
        return rows
    except Exception as e:   # first run: the app tables do not exist yet
        print(f"  (nothing read: {str(e)[:120]})")
        return []

# COMMAND ----------

dec = pg_rows("SELECT suggestion_id, decision, decided_by, decided_at FROM ai_decisions")
if dec:
    spark.createDataFrame(dec, "suggestion_id STRING, decision STRING, decided_by STRING, decided_at TIMESTAMP").createOrReplaceTempView("v_dec")
    merge(f"""MERGE INTO {CATALOG}.ai_assist.suggestions t USING v_dec s ON t.suggestion_id = s.suggestion_id
                  WHEN MATCHED AND (t.status <> s.decision OR t.decided_at IS NULL)
                  THEN UPDATE SET status = s.decision, decided_by = s.decided_by, decided_at = s.decided_at""")
print(f"AI decisions: {len(dec)}")

cust = pg_rows("""SELECT customer_id, customer_name, counterparty, gsib_parent, affiliate_legal_entity_id, has_relationship, approved_on,
                         approved_by, suggestion_id, decided_at FROM customer_master_approvals""")
if cust:
    spark.createDataFrame(cust, """customer_id STRING, customer_name STRING, counterparty STRING, gsib_parent STRING, affiliate_legal_entity_id STRING,
        has_relationship BOOLEAN, approved_on DATE, approved_by STRING, suggestion_id STRING, decided_at TIMESTAMP""").createOrReplaceTempView("v_cust")
    merge(f"""MERGE INTO {CATALOG}.reference.customer_master_approvals t USING v_cust s ON t.customer_id = s.customer_id
                  WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *""")
print(f"customer approvals: {len(cust)}")

prod = pg_rows("""SELECT source_system, source_product_code, standard_product_type, description, approved_on, approved_by, suggestion_id,
                         decided_at FROM source_product_map_approvals""")
if prod:
    spark.createDataFrame(prod, """source_system STRING, source_product_code STRING, standard_product_type STRING, description STRING,
        approved_on DATE, approved_by STRING, suggestion_id STRING, decided_at TIMESTAMP""").createOrReplaceTempView("v_prod")
    merge(f"""MERGE INTO {CATALOG}.reference.source_product_map_approvals t USING v_prod s ON t.source_product_code = s.source_product_code
                  WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *""")
print(f"product code approvals: {len(prod)}")

# COMMAND ----------

# Validation decisions (an exception explained or resolved in the app's Validate step) - copied whole into Delta for the audit
# trail on the dashboard and for Genie; the app's Lakebase table stays the system of record.
vd = pg_rows("SELECT decision_id, as_of_date, rule_id, item_key, action, note, decided_by, decided_at, status FROM validation_decisions")
VD_SCHEMA = "decision_id STRING, as_of_date DATE, rule_id STRING, item_key STRING, action STRING, note STRING, decided_by STRING, decided_at TIMESTAMP, status STRING"
spark.sql(f"CREATE TABLE IF NOT EXISTS {CATALOG}.reg_2052a.validation_decisions ({VD_SCHEMA}) COMMENT 'Validate step decisions from the app (Lakebase validation_decisions)'")
if vd:
    spark.createDataFrame(vd, VD_SCHEMA).createOrReplaceTempView("v_vd")
    merge(f"""MERGE INTO {CATALOG}.reg_2052a.validation_decisions t USING v_vd s ON t.decision_id = s.decision_id
                  WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *""")
print(f"validation decisions: {len(vd)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## A feed re-sent by the source (Collect)
# MAGIC When a short feed is re-sent by the source (demo: the send icon in the app header), the day re-runs with
# MAGIC `resend_feed`. For the synthetic data notebook 01 holds the missing records of one feed per demo date in
# MAGIC `raw.landing/_late/`; the re-sent file lands next to the original, and the Lakeflow ingest that follows picks it up.

# COMMAND ----------

import time
dbutils.widgets.text("as_of_date", "")
dbutils.widgets.text("resend_feed", "")
RESEND, AS_OF = dbutils.widgets.get("resend_feed").strip(), dbutils.widgets.get("as_of_date")
FEEDS = ("deposits", "loans", "securities", "derivatives", "funding", "finance")
if RESEND:
    assert RESEND in FEEDS, f"unknown feed {RESEND}"
    LANDING = f"/Volumes/{CATALOG}/raw/landing"
    try:
        held = dbutils.fs.ls(f"{LANDING}/_late/{RESEND}/{AS_OF}")
    except Exception:
        held = []
    done = [f for f in dbutils.fs.ls(f"{LANDING}/{RESEND}/{AS_OF}") if "_resent_" in f.name]
    if done:
        print(f"{RESEND} {AS_OF}: already re-sent ({done[0].name})")
    for f in ([] if done else held):
        dst = f"{LANDING}/{RESEND}/{AS_OF}/{f.name[:-4]}_resent_{int(time.time())}.csv"
        dbutils.fs.cp(f.path, dst)
        print(f"re-sent by the source: {dst}")
    if not held:
        print(f"{RESEND} {AS_OF}: nothing held back at the source")
