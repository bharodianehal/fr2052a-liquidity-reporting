# Databricks notebook source
# MAGIC %md
# MAGIC # AI refresh for one as-of date (v9)
# MAGIC ## Owned by: Regulatory Reporting Team
# MAGIC Re-runs AI Assist (notebook 09) for the chosen steps, republishes the date to Lakebase (notebook 07) and runs the
# MAGIC agents (notebook 15) on the new drafts, without a new reporting run. The full build and the demo reset use it for the
# MAGIC variance and commentary of the latest days, in date order, once every day has been built (`ai_forecast` needs the
# MAGIC history). The agents run last: the regenerated comment drafts are new items and need their proposals.

# COMMAND ----------

dbutils.widgets.text("as_of_date", "2026-02-27")
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("steps", "variance")
dbutils.widgets.text("app_sp_client_id", "")
dbutils.widgets.text("agents_sp_client_id", "")
dbutils.widgets.text("warehouse_id", "")
args = {k: dbutils.widgets.get(k) for k in ("as_of_date", "catalog")}
print(dbutils.notebook.run("./09_AI_Assist", 3600, {**args, "steps": dbutils.widgets.get("steps"), "warehouse_id": dbutils.widgets.get("warehouse_id")}))
print(dbutils.notebook.run("./07_Lakebase_Sync", 3600, {**args, "app_sp_client_id": dbutils.widgets.get("app_sp_client_id"), "agents_sp_client_id": dbutils.widgets.get("agents_sp_client_id")}))
print(dbutils.notebook.run("./15_Run_Agents", 3600, {**args, "warehouse_id": dbutils.widgets.get("warehouse_id"), "requested_by": "ai-refresh"}))
