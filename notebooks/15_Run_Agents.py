# Databricks notebook source
# MAGIC %md
# MAGIC # Run the AI agents - the maker (v10)
# MAGIC ## Owned by: Regulatory Reporting Team
# MAGIC
# MAGIC The last task of `fr2052a-daily` and `fr2052a-revalidate`, after notebook 07 has refreshed Lakebase. For the as-of date, the AI
# MAGIC agents look at every open item of the day - data quality breaks, new customers / product codes, validation exceptions, comments
# MAGIC for the Fed, incomplete feeds - and store a proposal for each in Lakebase (`breaks`, `proposals`, `agent_events`), with the
# MAGIC evidence: the independent rule check, the exact LCR effect, the FR 2052a Instructions / 12 CFR 249 passages (Vector Search) and
# MAGIC the source fix. The app only reads them: the person (the checker) approves, edits or returns each proposal on its step page. The
# MAGIC proposals that pass the bulk-approval test are applied **straight through** by the agents and listed on Today for a spot check.
# MAGIC
# MAGIC **The maker is a registered MLflow model:** `<catalog>.ai_assist.fr2052a_agents@champion` (pyfunc, registered by notebook 16) is
# MAGIC loaded and its `predict()` makes the proposal of every open item - the agents' code that runs is the code packaged in that model version.
# MAGIC
# MAGIC **MLflow Tracing:** each proposal is a trace in the experiment `fr2052a_agents` (Unity Catalog trace tables in `ai_assist`) - the agent,
# MAGIC its AI call, the regulatory search and the LCR effect as spans, tagged with the date, item, break type and agent version. The checker's
# MAGIC decisions so far are logged on the traces as human feedback; notebook 10 evaluates the agents from them.

# COMMAND ----------

# MAGIC %pip install -q fastapi==0.115.6 psycopg2-binary==2.9.10 "mlflow[databricks]>=3.11.1"
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.text("as_of_date", "2026-02-27")
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("warehouse_id", "")
dbutils.widgets.text("lakebase_endpoint", "projects/fr2052a/branches/production/endpoints/primary")
dbutils.widgets.text("requested_by", "pipeline")
dbutils.widgets.dropdown("straight_through", "true", ["true", "false"])
AS_OF = dbutils.widgets.get("as_of_date")

import os, sys, json
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
host = w.api_client.do("GET", f"/api/2.0/postgres/{dbutils.widgets.get('lakebase_endpoint')}")["status"]["hosts"]["host"]
os.environ.update({"CATALOG": dbutils.widgets.get("catalog"), "DATABRICKS_WAREHOUSE_ID": dbutils.widgets.get("warehouse_id"),
                   "LAKEBASE_ENDPOINT": dbutils.widgets.get("lakebase_endpoint"), "LAKEBASE_HOST": host, "LAKEBASE_DB": "fr2052a",
                   "FR2052A_AGENTS_BATCH": "1"})
# The maker: the registered model's champion version. Loading it first puts ITS packaged code (app.py, workbench.py, agents.py) on the
# path, so everything below - the queues, the proposals, storing them - runs that version's code.
import mlflow
mlflow.set_registry_uri("databricks-uc")
MODEL_NAME = f"{os.environ['CATALOG']}.ai_assist.fr2052a_agents"
model = mlflow.pyfunc.load_model(f"models:/{MODEL_NAME}@champion")
mv = mlflow.MlflowClient().get_model_version_by_alias(MODEL_NAME, "champion")
import app as main   # noqa: E402  (from the model's code)
import agents        # noqa: E402
import agent_tracing  # noqa: E402
print(f"maker: {MODEL_NAME} version {mv.version} (champion, model_id {model.metadata.model_id}); agents code {agents.__file__}; Lakebase {host}")

# The champion pins the agents' code: say so when it is not the code deployed with the app (register + promote a new version, notebook 16)
import hashlib
nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
APP_DIR = "/Workspace" + nb.rsplit("/notebooks/", 1)[0] + "/app"
CODE_DIR = os.path.dirname(agents.__file__)
digest = lambda d: {f: hashlib.sha256(open(f"{d}/{f}", "rb").read()).hexdigest()[:12] for f in ("app.py", "workbench.py", "agents.py", "agent_tracing.py")
                    if os.path.exists(f"{d}/{f}")}
stale = [f for f, h in digest(CODE_DIR).items() if digest(APP_DIR).get(f) != h]
print(("WARNING: the champion's agents code differs from the app code in " + APP_DIR + " (" + ", ".join(stale) + ") - register and promote a new "
       "version with notebook 16") if stale else "champion code = app code")

import pandas as pd
MADE_BY = f"{MODEL_NAME.rsplit('.', 1)[1]} v{mv.version}"
def propose_with_model(kind, date, item):
    p = json.loads(model.predict(pd.DataFrame([{"kind": kind, "as_of_date": date, "item_json": json.dumps(item, default=str)}]))[0])
    p["model"] = MADE_BY   # stored with the proposal: which registered model version made it
    return p
agents.PROPOSE = propose_with_model   # agents._run calls the registered model for every open item

# COMMAND ----------

# MLflow Tracing (observability - a tracing problem never stops the filing)
import agent_tracing   # noqa: E402
user_name = w.current_user.me().user_name
try:
    EXPERIMENT_ID = agent_tracing.setup(user_name, os.environ["CATALOG"], os.environ["DATABRICKS_WAREHOUSE_ID"])
    agent_tracing.MODEL = {"name": MODEL_NAME, "version": str(mv.version), "model_id": model.metadata.model_id}
    if model.metadata.model_id:
        mlflow.set_active_model(model_id=model.metadata.model_id)   # traces are linked to the model version that made them
    agent_tracing.instrument(agents, sys.modules["workbench"])
    print("MLflow tracing on - experiment", EXPERIMENT_ID)
except Exception as e:
    EXPERIMENT_ID = None
    print("WARNING: MLflow tracing not available -", str(e)[:300])

# COMMAND ----------

import uuid, time
run_id = f"RUN-{AS_OF[5:7]}{AS_OF[8:10]}-{uuid.uuid4().hex[:4]}"
user = dbutils.widgets.get("requested_by") or "pipeline"
with main.get_pg() as conn:
    with conn.cursor() as c:
        c.execute("INSERT INTO agent_runs VALUES (%s, %s, NOW(), NULL, 'RUNNING', NULL, %s)", (run_id, AS_OF, f"pipeline ({user})"))
    conn.commit()
agents._RUNS[run_id] = {"status": "RUNNING", "date": AS_OF, "done": 0, "total": None}
t0 = time.time()
agents._safe_run(AS_OF, run_id, user)
r = agents._RUNS[run_id]
print(json.dumps({k: v for k, v in r.items() if k != "date"}, default=str, indent=1), f"in {time.time() - t0:.0f}s")
if r.get("status") != "DONE":
    raise RuntimeError(f"agents run {run_id} {r.get('status')}: {r.get('error')}")

# Straight-through processing: the proposals that pass the bulk-approval test (confidence >= 95%, the rule agent agrees, no material LCR
# effect) are applied by the agents themselves and listed on Today for the checker to spot-check.
if dbutils.widgets.get("straight_through") == "true" and hasattr(agents, "straight_through"):
    print("straight through:", json.dumps(agents.straight_through(AS_OF), default=str))

# COMMAND ----------

# The checker's decisions -> human feedback on the proposals' traces (for notebook 10's evaluation). Every date with decisions, not only
# this one: a decision made after a date's last run (e.g. on the release day) is logged by the next run of any date.
if EXPERIMENT_ID:
    dates = [str(r["as_of_date"]) for r in main.run_pg("""SELECT DISTINCT b.as_of_date FROM breaks b JOIN break_decisions d ON d.break_id = b.break_id
                                                            ORDER BY 1""")]
    for d in dates:
        try:
            print("checker feedback", d, agent_tracing.log_checker_feedback(main, d, EXPERIMENT_ID))
        except Exception as e:
            print("WARNING: checker feedback not logged for", d, "-", str(e)[:300])
