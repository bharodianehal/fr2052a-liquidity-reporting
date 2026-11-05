# Databricks notebook source
# MAGIC %md
# MAGIC # AI evaluation - the AI Assist suggestions vs the synthetic answer keys (MLflow) - v9
# MAGIC ## Owned by: Regulatory Reporting Team (model risk review)
# MAGIC
# MAGIC The synthetic generator plants known cases with a known right answer, so every AI suggestion type can be scored:
# MAGIC
# MAGIC | Suggestion | Answer key | Metric |
# MAGIC |---|---|---|
# MAGIC | CUSTOMER_CLASSIFICATION | `audit.customer_answer_key` (Counterparty, G-SIB parent) | accuracy |
# MAGIC | PRODUCT_MAPPING | `audit.pid_answer_key` - the mapped type must be able to produce the record's true PID | accuracy |
# MAGIC | PID_EXCEPTION | the planted secured term loan without its rehypothecation flag (true PID I.S.6) | accuracy |
# MAGIC | COMMENT_DRAFT | 6G BR General #29 (ASCII 32-126) and the 4,000-character limit | valid rate |
# MAGIC
# MAGIC The human accept rate per suggestion type is logged as a live quality signal.
# MAGIC
# MAGIC Results go to `ai_assist.evaluation` and to an MLflow experiment, so model changes (e.g. a new Foundation Model
# MAGIC endpoint) are compared before they are used.
# MAGIC
# MAGIC **The AI agents (the maker)** are evaluated in their own experiment `fr2052a_agents` (traces in Unity Catalog, `ai_assist`):
# MAGIC the checker's decisions are logged on each proposal's trace as human feedback; per agent and break type the rates approved
# MAGIC without edit / edited / returned are logged; and MLflow GenAI evaluation scores every current proposal - the rule agent agrees,
# MAGIC it cites a regulatory source, and an LLM judge checks it is grounded in its evidence.

# COMMAND ----------

# MAGIC %pip install -q "mlflow[databricks]>=3.11.1" fastapi==0.115.6 psycopg2-binary==2.9.10
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.text("catalog", "")
CATALOG = dbutils.widgets.get("catalog")
spark.sql(f"USE CATALOG {CATALOG}")
S = f"{CATALOG}.ai_assist.suggestions"

import json, uuid
from datetime import datetime
import mlflow

RUN = datetime.now().strftime("%Y%m%d-%H%M%S")
metrics = []   # (suggestion_type, metric, value, n, details)

def score(stype, sql, metric="accuracy"):
    rows = spark.sql(sql).collect()
    n = len(rows)
    ok = sum(1 for r in rows if r.correct)
    misses = [r.subject_key for r in rows if not r.correct][:20]
    metrics.append((stype, metric, (100.0 * ok / n) if n else None, n, json.dumps({"misses": misses})))
    print(f"{stype:26s} {metric:10s} {ok}/{n}" + (f"  misses: {misses}" if misses else ""))

# COMMAND ----------

# Customer classification: Counterparty and G-SIB parent both right
score("CUSTOMER_CLASSIFICATION", f"""
SELECT s.subject_key, get_json_object(s.suggestion, '$.counterparty') = k.true_counterparty
       AND COALESCE(get_json_object(s.suggestion, '$.gsib_parent'), '') = COALESCE(k.true_gsib_parent, '') AS correct
FROM (SELECT * FROM {S} WHERE suggestion_type = 'CUSTOMER_CLASSIFICATION' QUALIFY ROW_NUMBER() OVER (PARTITION BY subject_key ORDER BY created_timestamp DESC) = 1) s
JOIN {CATALOG}.audit.customer_answer_key k ON k.customer_id = s.subject_key""")

# Product mapping: the proposed standard product type must be able to produce the PID the record must get
score("PRODUCT_MAPPING", f"""
SELECT s.subject_key, ARRAY_CONTAINS(SPLIT(FIRST(t.candidate_product_ids), ','), FIRST(k.expected_product_id)) AS correct
FROM {S} s
JOIN {CATALOG}.dq.quarantine q ON q.as_of_date = s.as_of_date AND q.source_product_code = s.subject_key
JOIN {CATALOG}.audit.pid_answer_key k ON k.as_of_date = q.as_of_date AND k.record_id = q.record_id   -- any part (e.g. INS / UNI)
LEFT JOIN {CATALOG}.reference.ref_standard_product_type t
  ON t.standard_product_type = get_json_object(s.suggestion, '$.standard_product_type')
 AND t.source_system = get_json_object(s.suggestion, '$.source_system')
WHERE s.suggestion_type = 'PRODUCT_MAPPING' GROUP BY s.subject_key""")

# PID exception: the planted case is a secured term loan (I.S.6) whose rehypothecation flag is missing
score("PID_EXCEPTION", f"""
SELECT s.subject_key, get_json_object(s.suggestion, '$.product_id') = 'I.S.6' AS correct
FROM {S} s JOIN {CATALOG}.dq.pid_exceptions e ON e.position_id = s.subject_key AND e.as_of_date = s.as_of_date
WHERE s.suggestion_type = 'PID_EXCEPTION' AND e.record_id LIKE 'LOA-%-EXC01%'""")

# Comment drafts: every draft must be valid for the Comment file (ASCII 32-126, <= 4000 characters)
score("COMMENT_DRAFT", f"""
SELECT subject_key, get_json_object(suggestion, '$.comments') RLIKE '^[ -~]{{1,4000}}$' AS correct
FROM {S} WHERE suggestion_type = 'COMMENT_DRAFT'""", metric="valid_6g")

# Human decisions so far (accept rate is a live quality signal)
for r in spark.sql(f"""SELECT suggestion_type, COUNT_IF(status = 'ACCEPTED') AS a, COUNT_IF(status IN ('ACCEPTED', 'REJECTED')) AS d
                       FROM {S} GROUP BY suggestion_type""").collect():
    if r.d:
        metrics.append((r.suggestion_type, "accept_rate", 100.0 * r.a / r.d, r.d, "{}"))

# COMMAND ----------

now = datetime.now()
spark.createDataFrame([(RUN, t, m, v, n, d, now) for t, m, v, n, d in metrics],
    "eval_run STRING, suggestion_type STRING, metric STRING, value DOUBLE, n INT, details STRING, run_timestamp TIMESTAMP"
).write.mode("append").saveAsTable(f"{CATALOG}.ai_assist.evaluation")

user = spark.sql("SELECT current_user() AS u").first().u
mlflow.set_experiment(f"/Users/{user}/fr2052a_ai_assist_evaluation")
model = spark.sql(f"SELECT MAX_BY(model, created_timestamp) AS m FROM {S} WHERE model LIKE 'databricks-%'").first().m
with mlflow.start_run(run_name=f"eval-{RUN}"):
    mlflow.log_param("model", model)
    for t, m, v, n, _ in metrics:
        if v is not None:
            mlflow.log_metric(f"{t.lower()}.{m}", v)
            mlflow.log_metric(f"{t.lower()}.n", n)
display(spark.sql(f"SELECT * FROM {CATALOG}.ai_assist.evaluation WHERE eval_run = '{RUN}' ORDER BY suggestion_type, metric"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## The AI agents - checker feedback, approval rates and GenAI evaluation

# COMMAND ----------

import os, sys, json
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
dbutils.widgets.text("warehouse_id", "")
dbutils.widgets.text("lakebase_endpoint", "projects/fr2052a/branches/production/endpoints/primary")
os.environ.update({"CATALOG": CATALOG, "DATABRICKS_WAREHOUSE_ID": dbutils.widgets.get("warehouse_id"), "FR2052A_AGENTS_BATCH": "1",
                   "LAKEBASE_ENDPOINT": dbutils.widgets.get("lakebase_endpoint"), "LAKEBASE_DB": "fr2052a",
                   "LAKEBASE_HOST": w.api_client.do("GET", f"/api/2.0/postgres/{dbutils.widgets.get('lakebase_endpoint')}")["status"]["hosts"]["host"]})
nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
sys.path.insert(0, "/Workspace" + nb.rsplit("/notebooks/", 1)[0] + "/app")
import app as main, agent_tracing   # noqa: E402
AGENTS_EXP = agent_tracing.setup(w.current_user.me().user_name, CATALOG, os.environ["DATABRICKS_WAREHOUSE_ID"])
# the registered agents model whose proposals are evaluated (the champion version notebook 15 calls)
mlflow.set_registry_uri("databricks-uc")
AGENTS_MODEL = f"{CATALOG}.ai_assist.fr2052a_agents"
try:
    champion = mlflow.MlflowClient().get_model_version_by_alias(AGENTS_MODEL, "champion")
    CHAMPION = {"version": str(champion.version), "model_id": getattr(champion, "model_id", None)}
except Exception as e:
    CHAMPION = {"version": None, "model_id": None}
    print("no champion version of", AGENTS_MODEL, "-", str(e)[:200])
print("evaluating", AGENTS_MODEL, CHAMPION)

dates = [str(r["as_of_date"]) for r in main.run_pg("SELECT DISTINCT as_of_date FROM breaks ORDER BY 1")]
fb = {d: agent_tracing.log_checker_feedback(main, d, AGENTS_EXP) for d in dates}
print("checker feedback on traces:", fb)

# the latest proposal of every break and its latest decision
P = main.run_pg("""SELECT b.as_of_date, b.break_id, b.break_type, b.status, b.title, b.detail, p.agent, p.confidence, p.summary, p.fields, p.rule_check,
                          p.sources, p.impact, d.action AS decision, d.reason_code
                   FROM breaks b
                   JOIN LATERAL (SELECT * FROM proposals x WHERE x.break_id = b.break_id ORDER BY x.version DESC LIMIT 1) p ON TRUE
                   LEFT JOIN LATERAL (SELECT * FROM break_decisions y WHERE y.break_id = b.break_id ORDER BY y.decided_at DESC LIMIT 1) d ON TRUE""")
made = [r for r in P if (r["rule_check"] or {}).get("detail") != "Decided on the step page"]   # proposals the agents made (not step-page stubs)

def outcome(r):
    if r["status"] == "PROPOSED": return "pending"
    if r["reason_code"] == "RERUN": return "resolved_by_rerun"
    if r["reason_code"] == "STEP": return "decided_on_step_page"
    return {"APPROVE": "approved", "APPROVE_WITH_EDIT": "edited", "RETURN": "returned"}.get(r["decision"], "other")

agent_metrics = []
for key in sorted({(r["agent"], r["break_type"]) for r in made}):
    rows = [r for r in made if (r["agent"], r["break_type"]) == key]
    o = [outcome(r) for r in rows]
    decided = [x for x in o if x in ("approved", "edited", "returned")]   # the checker's decisions on the agents' proposals
    for m_, v in (("proposals", len(rows)), ("decided", len(decided)), ("decided_on_step_page", o.count("decided_on_step_page")),
                  ("resolved_by_rerun", o.count("resolved_by_rerun")), ("pending", o.count("pending")),
                  ("approved_without_edit_pct", 100.0 * o.count("approved") / len(decided) if decided else None),
                  ("edited_pct", 100.0 * o.count("edited") / len(decided) if decided else None),
                  ("returned_pct", 100.0 * o.count("returned") / len(decided) if decided else None),
                  ("rule_agent_agrees_pct", 100.0 * sum(1 for r in rows if (r["rule_check"] or {}).get("status") != "break") / len(rows))):
        agent_metrics.append((f"AGENT:{key[0]}:{key[1]}", m_, v, len(rows), json.dumps({"outcomes": {x: o.count(x) for x in set(o)}, "agents_model_version": CHAMPION["version"]})))

# COMMAND ----------

# MLflow GenAI evaluation of the current proposals: two code scorers and an LLM judge
from mlflow.genai.scorers import Guidelines, scorer

@scorer
def rule_agent_agrees(outputs) -> bool:
    return (outputs.get("rule_check") or {}).get("status") != "break"

@scorer
def cites_regulation(outputs) -> bool:
    return any(("Instruction" in (s.get("title") or "")) or ("CFR" in (s.get("title") or "")) or ("249." in (s.get("ref") or "")) for s in outputs.get("sources") or [])

grounded = Guidelines(name="grounded_in_evidence", guidelines=[
    "The proposed change must follow from the evidence shown: the item (its title and detail), the failing rule, the proposed field values and the cited regulatory passages.",
    "The proposal must not introduce numbers, products or regulatory requirements that do not appear in that evidence."])

data = [{"inputs": {"break_type": r["break_type"], "item": r["title"], "detail": (r["detail"] or "")[:1500]},
         "outputs": {"proposal": r["summary"], "fields": r["fields"], "rule_check": r["rule_check"],
                     "sources": [{"title": x.get("title"), "ref": x.get("ref"), "passage": (x.get("passage") or "")[:800]} for x in (r["sources"] or [])]}}
        for r in made if r["status"] == "PROPOSED" or outcome(r) in ("approved", "edited", "returned")]
if data:
    res = mlflow.genai.evaluate(data=data, scorers=[rule_agent_agrees, cites_regulation, grounded],
                                **({"model_id": CHAMPION["model_id"]} if CHAMPION["model_id"] else {}))
    for k, v in (res.metrics or {}).items():
        if isinstance(v, (int, float)):
            agent_metrics.append(("AGENT:all", k.replace("/", "."), float(v), len(data), "{}"))
    print("GenAI evaluation run", res.run_id, res.metrics)

with mlflow.start_run(run_name=f"agents-{RUN}"):
    mlflow.log_params({"agents_model": AGENTS_MODEL, "agents_model_version": CHAMPION["version"]})
    for t, m_, v, n, _ in agent_metrics:
        if v is not None:
            mlflow.log_metric(f"{t.lower().replace(':', '.').replace(' ', '_')}.{m_}", v)
if agent_metrics:
    spark.createDataFrame([(RUN, t, m_, v, n, d, datetime.now()) for t, m_, v, n, d in agent_metrics],
        "eval_run STRING, suggestion_type STRING, metric STRING, value DOUBLE, n INT, details STRING, run_timestamp TIMESTAMP"
    ).write.mode("append").saveAsTable(f"{CATALOG}.ai_assist.evaluation")
display(spark.sql(f"SELECT * FROM {CATALOG}.ai_assist.evaluation WHERE eval_run = '{RUN}' AND suggestion_type LIKE 'AGENT%' ORDER BY suggestion_type, metric"))
