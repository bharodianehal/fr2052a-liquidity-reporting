# Databricks notebook source
# MAGIC %md
# MAGIC # Register the AI agents as an MLflow model (v10)
# MAGIC ## Owned by: Regulatory Reporting Team (model risk: change control of the agents)
# MAGIC
# MAGIC Packages the agents (`app/agents_model.py`, a pyfunc model from code, with `app.py`, `workbench.py`, `agents.py`) and registers a new
# MAGIC version of **`<catalog>.ai_assist.fr2052a_agents`** in Unity Catalog. Notebook 15 calls the version behind the alias **`champion`**
# MAGIC for every open item of the day, so the agents that make the filing's proposals are a governed, versioned model:
# MAGIC
# MAGIC 1. run the job `fr2052a-register-agents` after a change to the agents (prompts, rules, model) -> a new version (alias `challenger`);
# MAGIC 2. notebook 10 evaluates it (checker feedback, GenAI scorers);
# MAGIC 3. promote: run the job with `promote = true` (or move the alias in Catalog Explorer) -> `champion` + the serving endpoint, used from the next pipeline run;
# MAGIC    the endpoint is in the app bundle: set `agents_model_version` in its overrides to the promoted version.

# COMMAND ----------

# MAGIC %pip install -q "mlflow[databricks]>=3.11.1" fastapi==0.115.6 psycopg2-binary==2.9.10
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("warehouse_id", "")
dbutils.widgets.text("lakebase_endpoint", "projects/fr2052a/branches/production/endpoints/primary")
dbutils.widgets.text("ai_model", "databricks-claude-sonnet-4-6")
dbutils.widgets.dropdown("promote", "false", ["true", "false"])   # job fr2052a-register-agents, parameter promote
CATALOG = dbutils.widgets.get("catalog")
MODEL_NAME = f"{CATALOG}.ai_assist.fr2052a_agents"

import os, sys, json
import mlflow
import pandas as pd
from mlflow import MlflowClient
from mlflow.models import infer_signature
from mlflow.models.resources import DatabricksServingEndpoint, DatabricksSQLWarehouse, DatabricksVectorSearchIndex
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
APP_DIR = "/Workspace" + nb.rsplit("/notebooks/", 1)[0] + "/app"
CONFIG = {"catalog": CATALOG, "warehouse_id": dbutils.widgets.get("warehouse_id"), "lakebase_endpoint": dbutils.widgets.get("lakebase_endpoint"),
          "lakebase_db": "fr2052a", "ai_model": dbutils.widgets.get("ai_model"), "trace_user": w.current_user.me().user_name}
os.environ.update({"CATALOG": CATALOG, "DATABRICKS_WAREHOUSE_ID": CONFIG["warehouse_id"], "LAKEBASE_ENDPOINT": CONFIG["lakebase_endpoint"],
                   "LAKEBASE_DB": "fr2052a", "FR2052A_AGENTS_BATCH": "1",
                   "LAKEBASE_HOST": w.api_client.do("GET", f"/api/2.0/postgres/{CONFIG['lakebase_endpoint']}")["status"]["hosts"]["host"]})
sys.path.insert(0, APP_DIR)
import app as main, agents, workbench as wb, agent_tracing   # noqa: E402
EXPERIMENT_ID = agent_tracing.setup(w.current_user.me().user_name, CATALOG, CONFIG["warehouse_id"])

# an input example: one real open item (a validation exception if there is one, else a data quality break)
example = None
for d in [str(r["as_of_date"]) for r in main.run_pg("SELECT DISTINCT as_of_date FROM gold_validation ORDER BY 1 DESC")]:
    v = next((x for x in wb.validate_queue(d) if x["state"] == "open"), None)
    if v:
        example = pd.DataFrame([{"kind": "validation", "as_of_date": d, "item_json": json.dumps(v, default=str)}])
        break
assert example is not None, "no open item to use as the input example"
print("input example:", example.iloc[0]["kind"], example.iloc[0]["as_of_date"], json.loads(example.iloc[0]["item_json"])["rule_id"])

# COMMAND ----------

mlflow.set_registry_uri("databricks-uc")
signature = infer_signature(example, ["{\"break_type\": \"...\", \"summary\": \"...\"}"])
with mlflow.start_run(run_name="register fr2052a_agents") as run:
    info = mlflow.pyfunc.log_model(
        name="fr2052a_agents",
        python_model=f"{APP_DIR}/agents_model.py",
        code_paths=[f"{APP_DIR}/{f}" for f in ("app.py", "workbench.py", "agents.py", "agent_tracing.py")],
        model_config=CONFIG,
        signature=signature,
        input_example=example,
        pip_requirements=["mlflow[databricks]>=3.11.1", "fastapi==0.115.6", "psycopg2-binary==2.9.10", "databricks-sdk", "pandas"],
        resources=[DatabricksServingEndpoint(endpoint_name=CONFIG["ai_model"]), DatabricksSQLWarehouse(warehouse_id=CONFIG["warehouse_id"]),
                   DatabricksVectorSearchIndex(index_name=f"{CATALOG}.{agents.VS_INDEX}")],
        registered_model_name=MODEL_NAME,
    )
    mlflow.log_params({"agents": json.dumps(agents.VERSIONS), "ai_model": CONFIG["ai_model"], "review_threshold_usd_mm": agents.REVIEW_THRESHOLD_USD_MM,
                       "bulk_confidence": agents.AUTO_CONFIDENCE})
version = info.registered_model_version
client = MlflowClient()
client.set_model_version_tag(MODEL_NAME, version, "fr2052a_agents", json.dumps(agents.VERSIONS))
client.set_model_version_tag(MODEL_NAME, version, "fr2052a_ai_model", CONFIG["ai_model"])   # "ai_model" is a governed tag key in this workspace
client.set_registered_model_alias(MODEL_NAME, "challenger", version)
if dbutils.widgets.get("promote") == "true":
    client.set_registered_model_alias(MODEL_NAME, "champion", version)
    # the serving endpoint the app calls ("Run the agent again") serves the champion. It is a resource of the app bundle
    # (app/databricks.yml, served version = variable agents_model_version); a promotion moves it right away - then set
    # agents_model_version to this version in the app overrides, so the next app deploy keeps it
    try:
        ep = w.api_client.do("GET", "/api/2.0/serving-endpoints/fr2052a-agents")
    except Exception:
        print(f"serving endpoint fr2052a-agents not there yet - deploy the app bundle with agents_model_version={version}")
    else:
        served = ep["config"]["served_entities"]
        for e in served:
            e["entity_version"] = str(version)
            e["environment_vars"] = {**(e.get("environment_vars") or {}), "FR2052A_AGENTS_MODEL_VERSION": str(version)}
        keep = ("name", "entity_name", "entity_version", "workload_size", "scale_to_zero_enabled", "environment_vars")
        w.api_client.do("PUT", "/api/2.0/serving-endpoints/fr2052a-agents/config", body={"served_entities": [{k: e[k] for k in keep if k in e} for e in served]})
        print(f"serving endpoint fr2052a-agents -> version {version}; set agents_model_version={version} in app/.databricks/bundle/<target>/variable-overrides.json")
print(f"{MODEL_NAME} version {version} (model_id {info.model_id}) - aliases:", client.get_model_version(MODEL_NAME, version).aliases)

# COMMAND ----------

# smoke test: the registered version, loaded by alias, makes the proposal for the example item (nothing is stored)
loaded = mlflow.pyfunc.load_model(f"models:/{MODEL_NAME}@challenger")
p = json.loads(loaded.predict(example)[0])
print(json.dumps({k: p.get(k) for k in ("break_type", "agent", "confidence", "summary", "rule_check")}, default=str, indent=1)[:1500])
assert p.get("break_type") and p.get("summary") is not None
