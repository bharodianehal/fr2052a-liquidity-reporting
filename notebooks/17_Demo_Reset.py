# Databricks notebook source
# MAGIC %md
# MAGIC # Demo reset - put the demo dates back to "nothing worked yet"
# MAGIC ## Owned by: Platform Engineering (demo environment only)
# MAGIC
# MAGIC Run by the job `fr2052a-demo-reset` before a demo. For each date in `dates` it removes what people and the agents did in the
# MAGIC app, so every step has work again when the day is re-run (the job's next task):
# MAGIC
# MAGIC | Step | Work on every demo date (planted by notebook 01) |
# MAGIC |---|---|
# MAGIC | 1 Collect | one position feed arrives 30% short; the rest is held at the source until the analyst asks for a re-send |
# MAGIC | 2 Data quality | an unknown currency (`US$`) and an unknown booking entity (`LE-00`), plus the rotating defects |
# MAGIC | 3 PID enrichment | a secured loan without the rehypothecation flag (no PID rule); new customers / a new product code on their dates |
# MAGIC | 4 Validate | the Fed post-submission checks, GL breaks, comments for the Fed |
# MAGIC
# MAGIC Removed for those dates: Lakebase app tables (fixes, corrections, validation decisions, adjustments, sign-off actions, the agents'
# MAGIC breaks / proposals / decisions / events / runs, release memos, AI decisions and the master-data approvals made on those dates),
# MAGIC their Delta copies, and the re-sent feed files with their Bronze rows. **This deletes audit-trail rows** (append-only for the app)
# MAGIC - it is a demo environment tool, never a production one. MLflow traces and their feedback stay.

# COMMAND ----------

# MAGIC %pip install -q psycopg2-binary

# COMMAND ----------

import json
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("dates", '["2026-02-23", "2026-02-24", "2026-02-25", "2026-02-26", "2026-02-27"]')
dbutils.widgets.text("lakebase_endpoint", "projects/fr2052a/branches/production/endpoints/primary")
dbutils.widgets.text("lakebase_db", "fr2052a")
CATALOG = dbutils.widgets.get("catalog")
DATES = json.loads(dbutils.widgets.get("dates"))
assert DATES and all(d >= "2026-02-23" for d in DATES), "the reset is for the demo dates only"
IN = ", ".join(f"'{d}'" for d in DATES)

import psycopg2
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
ep = dbutils.widgets.get("lakebase_endpoint")
conn = psycopg2.connect(host=w.api_client.do("GET", f"/api/2.0/postgres/{ep}")["status"]["hosts"]["host"], port=5432,
                        database=dbutils.widgets.get("lakebase_db"), user=w.current_user.me().user_name, sslmode="require",
                        password=w.api_client.do("POST", "/api/2.0/postgres/credentials", body={"endpoint": ep})["token"])
print("dates:", DATES)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Lakebase - the app's tables

# COMMAND ----------

# AI decisions to undo: the suggestions of these dates, and the approvals made on these dates (a customer / product code suggestion
# can be older than the day it was approved on)
sugg = [r.suggestion_id for r in spark.sql(f"SELECT suggestion_id FROM {CATALOG}.ai_assist.suggestions WHERE as_of_date IN ({IN})").collect()]
with conn.cursor() as cur:
    cur.execute("""SELECT suggestion_id FROM public.customer_master_approvals WHERE approved_on = ANY(%s::date[])
                   UNION SELECT suggestion_id FROM public.source_product_map_approvals WHERE approved_on = ANY(%s::date[])""", (DATES, DATES))
    sugg = sorted({s for s in sugg + [r[0] for r in cur.fetchall()] if s})
    steps = [
        ("break_decisions", "DELETE FROM public.break_decisions WHERE break_id IN (SELECT break_id FROM public.breaks WHERE as_of_date = ANY(%s::date[]))", (DATES,)),
        ("proposals", "DELETE FROM public.proposals WHERE break_id IN (SELECT break_id FROM public.breaks WHERE as_of_date = ANY(%s::date[]))", (DATES,)),
        ("ai_decisions", "DELETE FROM public.ai_decisions WHERE suggestion_id = ANY(%s)", (sugg,)),
        ("customer_master_approvals", "DELETE FROM public.customer_master_approvals WHERE approved_on = ANY(%s::date[])", (DATES,)),
        ("source_product_map_approvals", "DELETE FROM public.source_product_map_approvals WHERE approved_on = ANY(%s::date[])", (DATES,)),
        ("submission_review (sign-off actions)", "DELETE FROM public.submission_review WHERE as_of_date = ANY(%s::date[]) AND action <> 'GENERATED'", (DATES,)),
    ] + [(t, f"DELETE FROM public.{t} WHERE as_of_date = ANY(%s::date[])", (DATES,))
         for t in ["breaks", "agent_events", "agent_runs", "release_memos", "dq_fixes", "position_corrections", "validation_decisions", "adjustments"]]
    for name, sql, args in steps:
        cur.execute(sql, args)
        print(f"  {name:38s} {cur.rowcount:5d} removed")
conn.commit()
conn.close()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Delta - the copies of those decisions

# COMMAND ----------

def run(label, sql):
    n = spark.sql(sql).first()
    print(f"  {label:38s} {n[0] if n else '':>5}")

run("reg_2052a.validation_decisions", f"DELETE FROM {CATALOG}.reg_2052a.validation_decisions WHERE as_of_date IN ({IN})")
run("reg_2052a.position_corrections", f"DELETE FROM {CATALOG}.reg_2052a.position_corrections WHERE as_of_date IN ({IN})")
run("reg_2052a.submission_review", f"DELETE FROM {CATALOG}.reg_2052a.submission_review WHERE as_of_date IN ({IN}) AND action <> 'GENERATED'")
run("reference.customer_master_approvals", f"DELETE FROM {CATALOG}.reference.customer_master_approvals WHERE approved_on IN ({IN})")
run("reference.source_product_map_approvals", f"DELETE FROM {CATALOG}.reference.source_product_map_approvals WHERE approved_on IN ({IN})")
if sugg:
    run("ai_assist.suggestions -> PROPOSED", f"""UPDATE {CATALOG}.ai_assist.suggestions SET status = 'PROPOSED', decided_by = NULL, decided_at = NULL
        WHERE suggestion_id IN ({', '.join(repr(s) for s in sugg)})""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Collect - the re-sent feed files and their Bronze rows

# COMMAND ----------

LANDING = f"/Volumes/{CATALOG}/raw/landing"
for feed in ["deposits", "loans", "securities", "derivatives", "funding", "finance"]:
    for d in DATES:
        try:
            files = [f for f in dbutils.fs.ls(f"{LANDING}/{feed}/{d}") if "_resent_" in f.name]
        except Exception:
            files = []
        for f in files:
            dbutils.fs.rm(f.path)
            print(f"  removed {feed}/{d}/{f.name}")
    run(f"raw.{feed} re-sent rows", f"DELETE FROM {CATALOG}.raw.{feed} WHERE as_of_date IN ({IN}) AND _source_file LIKE '%\\_resent\\_%'")
print("done - the job re-runs the days next")
