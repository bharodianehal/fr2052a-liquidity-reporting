"""The FR 2052a AI agents (the maker) as an MLflow pyfunc model, registered in Unity Catalog as <catalog>.ai_assist.fr2052a_agents.

predict() takes open items of the day and returns one proposal per item - the AI-suggested fix, the independent rule check, the exact
LCR effect, the regulatory sources and the agents' trace - exactly what agents.propose() makes. It only reads (Lakebase, the SQL
warehouse, the Foundation Model endpoint, Vector Search); notebook 15 stores the proposals and the person (the checker) decides.

  input  (DataFrame): kind ("dq" | "master" | "validation" | "comment" | "feed"), as_of_date ("YYYY-MM-DD"), item_json (the queue item)
  output (list[str]): the proposal of each row as JSON
The agents' code (app.py, workbench.py, agents.py) is packaged with the model (code_paths), so a model version pins the agents' logic.
"""
import json
import os

import mlflow
import pandas as pd


class FR2052aAgents(mlflow.pyfunc.PythonModel):
    def load_context(self, context):
        cfg = context.model_config or {}
        for k, v in {"CATALOG": cfg.get("catalog"), "DATABRICKS_WAREHOUSE_ID": cfg.get("warehouse_id"), "LAKEBASE_ENDPOINT": cfg.get("lakebase_endpoint"),
                     "LAKEBASE_DB": cfg.get("lakebase_db"), "AI_MODEL": cfg.get("ai_model"), "FR2052A_AGENTS_BATCH": "1"}.items():
            if v and not os.environ.get(k):
                os.environ[k] = v
        import agents   # noqa: F401  (packaged with the model; imports app / workbench)
        self.agents = agents
        # On the Model Serving endpoint (FR2052A_TRACE=1, set by notebook 16): trace every proposal into the agents' experiment (Unity
        # Catalog trace tables in <catalog>.ai_assist), tagged like the pipeline's, so the checker's decision on it becomes feedback.
        # In the pipeline notebook 15 sets up tracing itself.
        if os.environ.get("FR2052A_TRACE") == "1":
            try:
                import agent_tracing
                import workbench
                agent_tracing.setup(os.environ.get("FR2052A_TRACE_USER") or cfg.get("trace_user"), os.environ["CATALOG"], os.environ["DATABRICKS_WAREHOUSE_ID"])
                agent_tracing.MODEL = {"name": f"{os.environ['CATALOG']}.ai_assist.fr2052a_agents", "version": os.environ.get("FR2052A_AGENTS_MODEL_VERSION", ""),
                                       "model_id": ""}
                agent_tracing.instrument(agents, workbench)
                print("[agents] MLflow tracing on")
            except Exception as e:   # tracing never stops a proposal
                print(f"[agents] MLflow tracing not available: {str(e)[:300]}")

    def predict(self, context, model_input: pd.DataFrame, params=None):
        out = []
        for row in model_input.to_dict("records"):
            item = json.loads(row["item_json"]) if isinstance(row["item_json"], str) else row["item_json"]
            p = self.agents.propose(row["kind"], row["as_of_date"], item)
            out.append(json.dumps(p, default=str))
        return out


mlflow.models.set_model(FR2052aAgents())
