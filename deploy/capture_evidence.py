"""Capture text-readable execution evidence of the build into evidence/ - every file is real output (job runs, executed notebooks with
their cell outputs, query results, model output, API responses), so a reader can verify each stage ran.

  python deploy/capture_evidence.py [--daily-run <fr2052a-daily run id>] [--extra-run <run id> ...]
                                                          [--only jobs notebooks lakeflow results uc lakebase ml genie app tests]

Writes (one file per stage of the journey):
  evidence/01_job_runs.md          the jobs (daily, revalidate, generate, register-agents, full build, demo reset): recent runs with per-task results
  evidence/notebook_runs/*.ipynb   executed notebooks with their cell outputs (exported from the job runs) + README with the run ids
  evidence/02_lakeflow_ingest.md   Lakeflow ingest: pipeline updates, rows and expectation results per flow, Bronze row / file counts
  evidence/03_results_by_date.md   Silver / Gold / LCR / validation / 6G results per reporting date (SQL warehouse)
  evidence/04_unity_catalog.md     tags, column mask in effect, grants, lineage (system tables)
  evidence/05_lakebase.md          synced tables and the app's own tables in Lakebase Postgres, read back
  evidence/06_ml_genai.md          the agents model (UC registry, aliases), a live prediction from its serving endpoint, MLflow traces
                                   and the checker's feedback on them, the GenAI evaluation, AI Functions suggestions
  evidence/07_genie.md             Genie questions -> generated SQL -> result rows
  evidence/08_app_api.md           responses of the deployed Databricks App's API
  evidence/09_tests.md             offline unit tests (pytest output) and the live QA suite summary (evidence/qa_report.md)
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests
from databricks.sdk import WorkspaceClient

ROOT = Path(__file__).resolve().parent.parent
EV = ROOT / "evidence"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from fr2052a_env import need   # the repo's gitignored .env (see .env.example)
CATALOG = need("FR2052A_CATALOG")
WAREHOUSE = need("FR2052A_WAREHOUSE")
APP_URL = need("FR2052A_APP_URL")
# everything else is looked up in the workspace by name
_w = WorkspaceClient(profile=os.environ.get("DATABRICKS_CONFIG_PROFILE"))
JOBS = {n: next(iter(_w.jobs.list(name=n))).job_id for n in ("fr2052a-daily", "fr2052a-revalidate", "fr2052a-generate",
                                                             "fr2052a-register-agents", "fr2052a-pipeline", "fr2052a-demo-reset")}
PIPELINE_ID = next(p.pipeline_id for p in _w.pipelines.list_pipelines(filter="name LIKE 'fr2052a-bronze-ingest'"))
_APP = _w.api_client.do("GET", "/api/2.0/apps/fr2052a")
GENIE_SPACE = next(r["genie_space"]["space_id"] for r in _APP["resources"] if "genie_space" in r)
SERVICE_PRINCIPALS = [_APP["service_principal_client_id"]] + [sp.application_id for sp in _w.service_principals.list(filter='displayName eq "fr2052a-agents"')]
LAKEBASE_ENDPOINT = "projects/fr2052a/branches/production/endpoints/primary"
MODEL = f"{CATALOG}.ai_assist.fr2052a_agents"
# MLflow traces of the agents' experiment (app/agent_tracing.py) are stored in UC as <catalog>.ai_assist.`<experiment id>_trace_unified`
_ME = _w.current_user.me().user_name
TRACE_EXPERIMENT = _w.api_client.do("GET", "/api/2.0/mlflow/experiments/get-by-name",
                                    query={"experiment_name": f"/Users/{_ME}/fr2052a_agents"})["experiment"]["experiment_id"]
TRACES = f"{CATALOG}.ai_assist.`{TRACE_EXPERIMENT}_trace_unified`"
FR2052A_SCHEMAS = "('reference', 'raw', 'dq', 'conformed', 'reg_2052a', 'reg_lcr', 'audit', 'ai_assist', 'lakebase_src', 'app_serving')"   # resources/catalog.yml
D = "2026-02-27"

GENIE_QUESTIONS = [
    "What is the LCR ratio for each reporting entity on the latest reporting date and is it compliant?",
    "Show the LCR ratio, total HQLA and net cash outflows for ENT001 for every reporting date",
    "Break down reported outflows by FR 2052a table for the latest date",
    "Which validation rules failed or warned on the latest date?",
]
APP_ENDPOINTS = ["/api/dates", f"/api/wb/agents/{D}/review", f"/api/filing/{D}/summary", f"/api/submission/{D}", f"/api/wb/validate/{D}/queue",
                 "/api/wb/agents/accuracy", "/api/wb/agents/learning", "/api/wb/agents/2026-02-24/release-memo", f"/api/wb/lcr/{D}/explain?entity=ENT001"]
TASK_NOTEBOOKS = {"setup": "01_Setup_Schema_and_Reference_Data", "app_decisions": "00_App_Decisions", "dq_gate": "02_Data_Quality_Gate", "pid_derivation": "03_PID_Derivation_and_Enrichment",
                  "lcr_engine": "04_LCR_Calculation_Engine", "report_build": "05_FR2052a_Report_Build",
                  "validation_submission": "06_FR2052a_Validation_and_Submission", "lakebase_sync": "07_Lakebase_Sync", "governance": "08_Governance",
                  "ai_assist": "09_AI_Assist", "ai_evaluation": "10_AI_Evaluation", "ai_tools": "11_AI_Tools_UC_Functions", "metric_views": "13_Metric_Views",
                  "apply_corrections": "14_Apply_Corrections", "run_agents": "15_Run_Agents", "register": "16_Register_Agents_Model", "agents": "15_Run_Agents",
                  "reset": "17_Demo_Reset", "ai_variance_one_date": "12_AI_Refresh"}
# Why a run that ended SUCCESS shows a FAILED task (repaired runs): the cause, verified when it happened
RUN_NOTES = {540452625223577: "lakebase_tables failed twice on `sys.exit(0)` in deploy/lakebase_synced_tables.py (any SystemExit fails a "
                              "serverless Python task); fixed in the script, then the run was repaired and every task succeeded."}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@databricks\.com")


def ts(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if ms else ""


def md_table(cols, rows, limit=None):
    rows = rows[:limit] if limit else rows
    cell = lambda v: "" if v is None else str(v).replace("|", "\\|").replace("\n", " ")
    return "\n".join(["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)] + ["| " + " | ".join(cell(v) for v in r) + " |" for r in rows])


def header(title, w):
    return f"# {title}\n\nCaptured {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} from `{w.config.host}` by `deploy/capture_evidence.py`.\n\n"


class Sql:
    def __init__(self, w):
        self.w = w

    def __call__(self, statement):
        r = self.w.statement_execution.execute_statement(warehouse_id=WAREHOUSE, statement=statement, wait_timeout="50s", catalog=CATALOG)
        while r.status.state.value in ("PENDING", "RUNNING"):
            time.sleep(2)
            r = self.w.statement_execution.get_statement(r.statement_id)
        if r.status.state.value != "SUCCEEDED":
            raise RuntimeError(f"{r.status.error.message if r.status.error else r.status.state}")
        return [c.name for c in r.manifest.schema.columns], (r.result.data_array or []) if r.result else []


def section(md, title, sql, s, limit=None, show_sql=True):
    try:
        cols, data = sql(s)
        q = f"```sql\n{' '.join(s.split())}\n```\n\n" if show_sql else ""
        return md + f"## {title}\n\n{q}{md_table(cols, data, limit)}\n\n"
    except Exception as e:  # noqa: BLE001 - record and continue
        return md + f"## {title}\n\n_query failed: {str(e)[:300]}_\n\n"


# ─── executed notebooks ──────────────────────────────────────────────────────
def _outputs(results):
    if not results:
        return []
    items = results["data"] if results.get("type") == "listResults" else [results]
    outs = []
    for it in items:
        t, d = it.get("type"), it.get("data")
        if t in ("ansi", "text") and d:
            outs.append({"output_type": "stream", "name": it.get("name", "stdout"), "text": d})
        elif t == "mimeBundle" and isinstance(d, dict):
            text = d.get("text/plain", "")
            if text and text != "DataFrame[]" and "widget-view" not in json.dumps(d)[:300]:
                outs.append({"output_type": "execute_result", "execution_count": None, "metadata": {}, "data": {"text/plain": text}})
            elif "application/databricks.mlflow.trace" in d:
                outs.append({"output_type": "execute_result", "execution_count": None, "metadata": {}, "data": {"text/plain": d.get("text/plain", "")[:3000]}})
        elif t == "table":
            cols = [x["name"] for x in it.get("schema", [])]
            outs.append({"output_type": "execute_result", "execution_count": None, "metadata": {}, "data": {"text/plain": md_table(cols, d or [], limit=200)}})
        elif t == "error" or it.get("errorSummary"):
            outs.append({"output_type": "error", "ename": "Error", "evalue": str(it.get("errorSummary") or d)[:2000], "traceback": []})
    return outs


def export_notebook(w, task_run_id, out_path):
    view = w.api_client.do("GET", "/api/2.2/jobs/runs/export", query={"run_id": task_run_id, "views_to_export": "CODE"})
    html = view["views"][0]["content"]
    nb = json.loads(urllib.parse.unquote(base64.b64decode(re.search(r"__DATABRICKS_NOTEBOOK_MODEL = '([^']*)'", html).group(1)).decode()))
    cells = []
    for cmd in sorted(nb["commands"], key=lambda c: c.get("position", 0)):
        src = cmd.get("command", "")
        if src.lstrip().startswith("%md"):
            cells.append({"cell_type": "markdown", "metadata": {}, "source": src.lstrip()[3:].lstrip("\n")})
            continue
        outs = _outputs(cmd.get("results"))
        if cmd.get("error"):
            outs.append({"output_type": "error", "ename": "Error", "evalue": str(cmd["error"])[:2000], "traceback": []})
        cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "source": src, "outputs": outs})
    out_path.write_text(json.dumps({"nbformat": 4, "nbformat_minor": 5, "cells": cells, "metadata": {
        "kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}, "databricks_job_task_run_id": task_run_id}}, indent=1) + "\n")
    return sum(len(c.get("outputs", [])) for c in cells)


def job_runs(w):
    md = header("Job runs", w) + ("The pipeline runs as Lakeflow Jobs on serverless compute. `fr2052a-daily` builds one reporting date end to end "
                                  "(app decisions -> Lakeflow ingest -> DQ -> PID enrichment -> LCR -> report -> validation + 6G XML -> AI assist -> "
                                  "Lakebase sync -> the AI agents).\n\n")
    out = {}
    for name, jid in JOBS.items():
        runs = w.api_client.do("GET", "/api/2.2/jobs/runs/list", query={"job_id": jid, "limit": 6, "expand_tasks": "true"}).get("runs", [])
        out[name] = runs
        rows = []
        for r in runs:
            p = {x["name"]: x.get("value", x.get("default")) for x in r.get("job_parameters", [])}
            tasks = ", ".join(f"{t['task_key']}={t['state'].get('result_state')}" for t in sorted(r.get("tasks", []), key=lambda t: t.get("start_time") or 0))
            rows.append([r["run_id"], ts(r.get("start_time")), r["state"].get("result_state") or r["state"].get("life_cycle_state"),
                         p.get("as_of_date") or p.get("promote", ""), round(((r.get("end_time") or 0) - r["start_time"]) / 60000, 1) if r.get("end_time") else "", tasks])
        md += f"## {name} (job {jid})\n\n" + md_table(["run id", "started", "result", "as_of_date / promote", "minutes", "tasks"], rows) + "\n\n"
        for r in runs:
            ts_ = r.get("tasks", [])
            if r["state"].get("result_state") == "SUCCESS" and any(t["state"].get("result_state") == "FAILED" for t in ts_):
                md += f"- Run `{r['run_id']}` was repaired: {RUN_NOTES.get(r['run_id'], 'a task failed, the run was repaired and every task then succeeded.')}\n"
            if any(t["state"].get("result_state") in ("EXCLUDED", "DISABLED") for t in ts_) and r["state"].get("result_state") == "SUCCESS" and name == "fr2052a-pipeline":
                ran = [t["task_key"] for t in ts_ if t["state"].get("result_state") == "SUCCESS"]
                if len(ran) < len(ts_):
                    md += f"- Run `{r['run_id']}` ran only these tasks: {', '.join(sorted(set(ran)))} (the rest were not selected).\n"
        md += "\n"
        # Python script tasks (not notebooks, so not in notebook_runs/): their output in the latest run that ran them
        done = set()
        for r in runs:
            for t in r.get("tasks", []):
                if t.get("spark_python_task") and t["state"].get("result_state") == "SUCCESS" and t["task_key"] not in done:
                    done.add(t["task_key"])
                    try:
                        log = (w.api_client.do("GET", "/api/2.2/jobs/runs/get-output", query={"run_id": t["run_id"]}).get("logs") or "").strip()
                    except Exception as e:  # noqa: BLE001 - record and continue
                        log = f"(output not available: {str(e)[:200]})"
                    src = t["spark_python_task"]["python_file"].split("/files/")[-1]
                    md += (f"### Task `{t['task_key']}` (`{src}`), run `{r['run_id']}` ({ts(t.get('start_time'))}): output\n\n"
                           f"```\n{log[-4000:] or '(no output)'}\n```\n\n")
    (EV / "01_job_runs.md").write_text(md)
    return out


def notebooks(w, runs, daily_run, extra_runs):
    nb_dir = EV / "notebook_runs"
    nb_dir.mkdir(parents=True, exist_ok=True)
    for f in nb_dir.glob("*.ipynb"):
        f.unlink()
    picks = {}
    def take(run_id, label):
        r = w.api_client.do("GET", "/api/2.2/jobs/runs/get", query={"run_id": run_id})
        p = {x["name"]: x.get("value", x.get("default")) for x in r.get("job_parameters", [])}
        label = next((n for n, j in JOBS.items() if j == r.get("job_id")), label)
        tasks = list(r.get("tasks", []))
        for t in r.get("tasks", []):   # a for_each task: its first successful iteration (e.g. notebook 12 in fr2052a-pipeline)
            inner = (t.get("for_each_task") or {}).get("task", {})
            if inner.get("notebook_task"):
                its = w.api_client.do("GET", "/api/2.2/jobs/runs/get", query={"run_id": t["run_id"]}).get("iterations", [])
                ok = next((i for i in its if i.get("state", {}).get("result_state") == "SUCCESS"), None)
                if ok:
                    tasks.append({**ok, "task_key": inner["task_key"], "notebook_task": inner["notebook_task"]})
        for t in tasks:
            name = TASK_NOTEBOOKS.get(t["task_key"])
            if name and t.get("notebook_task") and t["state"].get("result_state") == "SUCCESS":
                picks[name] = (t["run_id"], f"{label} run `{run_id}` ({ts(r.get('start_time'))}{', as_of_date ' + p['as_of_date'] if p.get('as_of_date') else ''})")
    for name in ("fr2052a-generate", "fr2052a-register-agents"):   # the daily run (taken after) wins for the notebooks they share
        ok = next((r for r in runs.get(name, []) if r["state"].get("result_state") == "SUCCESS"), None)
        if ok:
            take(ok["run_id"], name)
    if daily_run:
        take(daily_run, "fr2052a-daily")
    for rid in extra_runs:
        take(rid, "one-time")
    rows = []
    for name, (tid, where) in sorted(picks.items()):
        n = export_notebook(w, tid, nb_dir / f"{name}.ipynb")
        rows.append([f"[{name}.ipynb]({name}.ipynb)", tid, n, where])
    (nb_dir / "README.md").write_text("# Executed notebooks (with their cell outputs)\n\nExported from the job runs with `GET /api/2.2/jobs/runs/export` "
                                      "and converted to .ipynb by `deploy/capture_evidence.py`.\n\n" +
                                      md_table(["notebook", "task run id", "cell outputs", "from"], rows) + "\n")


def lakeflow(w):
    sql = Sql(w)
    updates = w.api_client.do("GET", f"/api/2.0/pipelines/{PIPELINE_ID}/updates", query={"max_results": 10}).get("updates", [])
    md = header("Lakeflow ingest - pipeline fr2052a-bronze-ingest", w)
    md += ("`pipelines/bronze_ingest.py`: a Lakeflow Declarative Pipeline with Auto Loader reading the synthetic source-system extracts (CSV) "
           "from the volume `raw.landing/<source>/<date>/` into the Bronze tables `raw.*`, with expectations.\n\n")
    md += "## Updates\n\n" + md_table(["update id", "state", "full refresh", "created"],
                                      [[u["update_id"], u.get("state"), u.get("full_refresh", False), ts(u.get("creation_time"))] for u in updates]) + "\n\n"
    target = next((u["update_id"] for u in updates if u.get("state") == "COMPLETED"), None)
    if target:
        events = w.api_client.do("GET", f"/api/2.0/pipelines/{PIPELINE_ID}/events", query={"max_results": 250, "filter": f"update_id='{target}'"}).get("events", [])
        flows = {}
        for e in events:
            fp = (e.get("details") or {}).get("flow_progress") or {}
            name = e.get("origin", {}).get("flow_name")
            if not fp or not name:
                continue
            f = flows.setdefault(name, {"rows": 0, "dropped": 0, "status": "", "exp": {}})
            f["status"] = fp.get("status") if fp.get("status") == "COMPLETED" else f["status"] or fp.get("status")
            f["rows"] += (fp.get("metrics") or {}).get("num_output_rows", 0) or 0
            dq = fp.get("data_quality") or {}
            f["dropped"] += dq.get("dropped_records", 0) or 0
            for x in dq.get("expectations", []):
                p, fl = f["exp"].get(x["name"], (0, 0))
                f["exp"][x["name"]] = (p + x.get("passed_records", 0), fl + x.get("failed_records", 0))
        md += f"## Latest completed update `{target}`: rows and expectations per flow\n\n" + md_table(
            ["flow", "status", "output rows", "dropped", "expectations"],
            [[n.split(".")[-1], f["status"], f["rows"], f["dropped"], "; ".join(f"{k}: passed {p}, failed {fl}" for k, (p, fl) in sorted(f["exp"].items()))]
             for n, f in sorted(flows.items())]) + "\n\n"
    parts = [f"SELECT '{s}' AS source, as_of_date, COUNT(*) AS records, COUNT(DISTINCT _source_file) AS files FROM {CATALOG}.raw.{s} "
             f"WHERE as_of_date >= '2026-02-23' GROUP BY ALL" for s in ["deposits", "loans", "securities", "derivatives", "funding"]]
    md = section(md, "Bronze tables (`raw.*`), reporting dates", sql, " UNION ALL ".join(parts) + " ORDER BY source, as_of_date")
    (EV / "02_lakeflow_ingest.md").write_text(md)


def results(w):
    sql = Sql(w)
    md = header("Pipeline results by reporting date (Silver / Gold, SQL warehouse)", w)
    for title, s in {
        "Data quality gate: assessment per date (dq.assessment_results)": f"""SELECT as_of_date, COUNT(*) AS rules, SUM(CASE WHEN failed_records > 0 THEN 1 ELSE 0 END) AS rules_failing,
              SUM(failed_records) AS failed_records FROM {CATALOG}.dq.assessment_results WHERE as_of_date >= '2026-02-23' GROUP BY 1 ORDER BY 1""",
        "Quarantined records and PID exceptions": f"""SELECT as_of_date, record_id, source_feed, failed_rules AS reason FROM {CATALOG}.dq.quarantine WHERE as_of_date >= '2026-02-23'
              UNION ALL SELECT as_of_date, record_id, source_feed, reason FROM {CATALOG}.dq.pid_exceptions WHERE as_of_date >= '2026-02-23' ORDER BY 1, 2""",
        "PID derivation (audit.pid_derivation_summary)": f"""SELECT as_of_date, source_records, positions, derived, exceptions, answer_key_checked, answer_key_mismatches, accuracy_pct
              FROM {CATALOG}.audit.pid_derivation_summary WHERE as_of_date >= '2026-02-23' ORDER BY 1""",
        "LCR per entity (reg_lcr.calculation_results)": f"""SELECT as_of_date, entity_id, ROUND(total_hqla, 1) AS hqla, ROUND(total_outflows, 1) AS outflows, ROUND(capped_inflows, 1) AS inflows_capped,
              ROUND(total_net_cash_outflows, 1) AS nco, ROUND(lcr_ratio * 100, 2) AS lcr_pct, lcr_compliant FROM {CATALOG}.reg_lcr.calculation_results
              WHERE as_of_date >= '2026-02-23' ORDER BY 1, 2""",
        f"Filing records by entity and table, {D} (reg_2052a.v_filing_records)": f"""SELECT reporting_entity, table_code, COUNT(*) AS records, ROUND(SUM(reported_amount_usd), 1) AS amount_usd
              FROM {CATALOG}.reg_2052a.v_filing_records WHERE as_of_date = '{D}' GROUP BY 1, 2 ORDER BY 1, 2""",
        "Validation by source and status (reg_2052a.gold_validation)": f"""SELECT as_of_date, rule_source, status, COUNT(*) AS rules FROM {CATALOG}.reg_2052a.gold_validation
              WHERE as_of_date >= '2026-02-23' GROUP BY ALL ORDER BY 1, 2, 3""",
        "Rules not passing": f"""SELECT as_of_date, entity_id, rule_id, severity, status, records_failed, substr(failure_details, 1, 120) AS details FROM {CATALOG}.reg_2052a.gold_validation
              WHERE status IN ('FAIL', 'WARNING') AND as_of_date >= '2026-02-23' ORDER BY 1, 2, 3""",
        f"Reconciliation, {D}": f"""SELECT entity_id, recon_type AS check_name, ROUND(gl_total, 1) AS expected, ROUND(pipeline_total, 1) AS actual, status FROM {CATALOG}.audit.gl_reconciliation
              WHERE as_of_date = '{D}' UNION ALL SELECT entity_id, metric_name, ROUND(reg_lcr_value, 4), ROUND(reg_2052a_value, 4), status FROM {CATALOG}.audit.cross_metric_recon WHERE as_of_date = '{D}' ORDER BY 1, 2""",
        "6G files of the latest run per date (reg_2052a.submission_files)": f"""SELECT f.as_of_date, f.run_number, f.file_type, f.file_name, f.record_count, f.xsd_valid, f.xsd_errors, f.release_status
              FROM {CATALOG}.reg_2052a.submission_files f WHERE f.as_of_date >= '2026-02-23'
              AND f.run_number = (SELECT MAX(run_number) FROM {CATALOG}.reg_2052a.submission_files x WHERE x.as_of_date = f.as_of_date) ORDER BY 1, 3""",
        f"6G Primary XML, {D} (first 1,500 characters)": f"""SELECT file_name, substr(xml_content, 1, 1500) AS xml_head FROM {CATALOG}.reg_2052a.submission_files
              WHERE as_of_date = '{D}' AND file_type = 'Primary' AND run_number = (SELECT MAX(run_number) FROM {CATALOG}.reg_2052a.submission_files WHERE as_of_date = '{D}')""",
        f"Lineage, {D} (audit.data_lineage)": f"""SELECT pipeline_name, stage, source_table, target_table, records_read, records_written FROM {CATALOG}.audit.data_lineage
              WHERE as_of_date = '{D}' ORDER BY run_timestamp""",
    }.items():
        md = section(md, title, sql, s)
    (EV / "03_results_by_date.md").write_text(md)


def unity_catalog(w):
    sql = Sql(w)
    md = header("Unity Catalog governance", w)
    for title, s in {
        "Schemas of the catalog": f"SELECT schema_name, comment FROM {CATALOG}.information_schema.schemata WHERE schema_name IN {FR2052A_SCHEMAS} ORDER BY 1",
        "Tags (information_schema)": f"""SELECT 'schema' AS level, schema_name AS object, '' AS column_name, tag_name, tag_value FROM {CATALOG}.information_schema.schema_tags WHERE tag_name LIKE 'fr2052a_%'
              UNION ALL SELECT 'table', schema_name || '.' || table_name, '', tag_name, tag_value FROM {CATALOG}.information_schema.table_tags WHERE tag_name LIKE 'fr2052a_%'
              UNION ALL SELECT 'column', schema_name || '.' || table_name, column_name, tag_name, tag_value FROM {CATALOG}.information_schema.column_tags WHERE tag_name LIKE 'fr2052a_%'
              ORDER BY 1, 2, 3, 4""",
        "Column mask in effect (the reader is not in fr2052a_risk_officers)": f"""SELECT current_user() AS reader, internal_rating, COUNT(*) AS positions
              FROM {CATALOG}.conformed.fact_liquidity_position GROUP BY ALL""",
        "Mask definition (information_schema.column_masks)": f"SELECT table_schema, table_name, column_name, mask_name FROM {CATALOG}.information_schema.column_masks",
        "Grants to the app and the agents' service principals": f"""SELECT grantee, schema_name AS object, privilege_type FROM {CATALOG}.information_schema.schema_privileges
              WHERE grantee IN ({', '.join(repr(x) for x in SERVICE_PRINCIPALS)}) ORDER BY 1, 2, 3""",
        "Registered model, functions, metric views, volumes": f"""SELECT 'function' AS kind, routine_schema || '.' || routine_name AS name FROM {CATALOG}.information_schema.routines WHERE routine_schema IN ('ai_assist', 'reference')
              UNION ALL SELECT 'metric view', table_schema || '.' || table_name FROM {CATALOG}.information_schema.tables WHERE table_type = 'METRIC_VIEW'
              UNION ALL SELECT 'volume', volume_schema || '.' || volume_name FROM {CATALOG}.information_schema.volumes WHERE volume_schema IN {FR2052A_SCHEMAS} ORDER BY 1, 2""",
        "Table lineage captured by UC (system.access.table_lineage, last 3 days)": f"""SELECT DISTINCT source_table_full_name, target_table_full_name, entity_type FROM system.access.table_lineage
              WHERE (target_table_catalog = '{CATALOG}' OR source_table_catalog = '{CATALOG}') AND event_date >= current_date() - 3
                AND source_table_full_name IS NOT NULL AND target_table_full_name IS NOT NULL
                AND coalesce(target_table_schema, source_table_schema) IN ('raw', 'dq', 'conformed', 'reg_2052a', 'reg_lcr', 'audit', 'lakebase_src') ORDER BY 1, 2""",
    }.items():
        md = section(md, title, sql, s, limit=120)
    (EV / "04_unity_catalog.md").write_text(md)


def _pg(w):
    import psycopg2
    host = w.api_client.do("GET", f"/api/2.0/postgres/{LAKEBASE_ENDPOINT}")["status"]["hosts"]["host"]
    token = w.api_client.do("POST", "/api/2.0/postgres/credentials", body={"endpoint": LAKEBASE_ENDPOINT})["token"]
    return host, psycopg2.connect(host=host, dbname="fr2052a", user=w.current_user.me().user_name, password=token, sslmode="require",
                                  options="-c search_path=app_serving,public")


def lakebase(w):
    host, conn = _pg(w)
    cur = conn.cursor()
    md = header("Lakebase (Postgres) - operational serving for the app", w)
    md += (f"Endpoint `{LAKEBASE_ENDPOINT}` (host `{host}`), database `fr2052a`. Schema `app_serving` = Unity Catalog synced tables (Delta -> Postgres, "
           "one pipeline); schema `public` = the app's own tables (the checker's decisions, sign-off - append-only for the audit trail).\n\n")
    sync = w.api_client.do("GET", f"/api/2.0/postgres/synced_tables/{CATALOG}.app_serving.calculation_results")
    md += "## A synced table's status (`GET /api/2.0/postgres/synced_tables/...calculation_results`)\n\n```json\n" + json.dumps(sync.get("status", sync), indent=1, default=str)[:2500] + "\n```\n\n"
    for schema in ("app_serving", "public"):
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s AND table_type = 'BASE TABLE' ORDER BY 1", (schema,))
        rows = []
        for (t,) in cur.fetchall():
            cur.execute(f"SELECT COUNT(*) FROM {schema}.{t}")
            rows.append([t, cur.fetchone()[0]])
        md += f"## Tables in `{schema}` ({len(rows)})\n\n" + md_table(["table", "rows"], rows) + "\n\n"
    for title, q in {"What the app reads: `SELECT ... FROM calculation_results` (synced)": "SELECT as_of_date, entity_id, total_hqla, total_net_cash_outflows, lcr_ratio, lcr_compliant FROM calculation_results ORDER BY 1, 2",
                     "The checker's decisions: `break_decisions` (app-owned, append-only)": "SELECT decision_id, break_id, proposal_id, action, reason_code, decided_by, decided_at FROM break_decisions ORDER BY decided_at DESC LIMIT 15"}.items():
        cur.execute(q)
        md += f"## {title}\n\n" + md_table([c[0] for c in cur.description], cur.fetchall()) + "\n\n"
    conn.close()
    (EV / "05_lakebase.md").write_text(md)


def ml(w):
    sql = Sql(w)
    md = header("ML / Gen AI - the AI agents (maker) with the person as checker", w)
    md += ("The agents are an MLflow pyfunc model registered in Unity Catalog; notebook 15 runs its `@champion` in the pipeline for every open item, "
           "the app's \"Run the agent again\" calls it on a Model Serving endpoint. Each proposal is an MLflow trace in Unity Catalog; the checker's "
           "decision is logged on it as human feedback; notebook 10 evaluates the champion with `mlflow.genai.evaluate`.\n\n")
    vers = w.api_client.do("GET", "/api/2.1/unity-catalog/models/" + MODEL + "/versions", query={"max_results": 20}).get("model_versions", [])
    champ = w.api_client.do("GET", f"/api/2.1/unity-catalog/models/{MODEL}/aliases/champion")
    md += f"## Registered model `{MODEL}`\n\nchampion = version {champ['version']}\n\n" + md_table(
        ["version", "status", "created", "source"], [[v["version"], v.get("status"), ts(v.get("created_at")), v.get("source")] for v in sorted(vers, key=lambda v: v["version"])]) + "\n\n"
    ep = w.api_client.do("GET", "/api/2.0/serving-endpoints/fr2052a-agents")
    md += "## Serving endpoint `fr2052a-agents`\n\n" + md_table(["state", "served entity", "version", "workload", "scale to zero"],
        [[json.dumps(ep["state"]), s["entity_name"], s["entity_version"], s.get("workload_size"), s.get("scale_to_zero_enabled")] for s in ep["config"]["served_entities"]]) + "\n\n"
    token = json.loads(subprocess.check_output(["databricks", "auth", "token", "-p", w.config.profile]))["access_token"]
    q = requests.get(f"{APP_URL}/api/wb/validate/2026-02-26/queue", headers={"Authorization": f"Bearer {token}"}, timeout=120).json()
    row = q[0] if q else None
    if row:
        item = {**row, "state": "open", "decision": None}   # the queue item as the pipeline passes it to the model
        body = {"dataframe_records": [{"kind": "validation", "as_of_date": "2026-02-26", "item_json": json.dumps(item)}]}
        t0 = time.time()
        r = w.api_client.do("POST", "/serving-endpoints/fr2052a-agents/invocations", body=body)
        p = json.loads(r["predictions"][0])
        keep = {k: p.get(k) for k in ("break_type", "agent", "confidence", "summary", "fields", "rule_check", "impact", "sources", "trace", "source_fix")}
        md += (f"## A live prediction from the endpoint ({time.time() - t0:.1f} s; nothing stored)\n\nInput:\n\n```json\n{json.dumps(body, indent=1)[:2000]}\n```\n\n"
               f"Output (the agents' proposal):\n\n```json\n{json.dumps(keep, indent=1, default=str)[:6000]}\n```\n\n")
    for title, s in {
        "MLflow traces in Unity Catalog, by date and model version": f"""SELECT tags['fr2052a.as_of_date'] AS as_of_date, tags['fr2052a.agents_model_version'] AS model_version,
              tags['fr2052a.source_kind'] AS kind, COUNT(*) AS traces, MIN(request_time) AS first, MAX(request_time) AS last FROM {TRACES} GROUP BY ALL ORDER BY 1, 2""",
        "The checker's decisions as human feedback on the traces": f"""SELECT trace_id, tags['fr2052a.as_of_date'] AS as_of_date, tags['fr2052a.agents_model_version'] AS model_version,
              a.assessment_name, a.feedback.value AS value, a.source.source_type, a.source.source_id, a.rationale FROM {TRACES} LATERAL VIEW explode(assessments) x AS a
              WHERE a.assessment_name = 'checker_decision' ORDER BY a.create_time""",
        "GenAI evaluation of the agents (ai_assist.evaluation, latest run)": f"""SELECT eval_run, suggestion_type, metric, ROUND(value, 3) AS value, n FROM {CATALOG}.ai_assist.evaluation
              WHERE suggestion_type LIKE 'AGENT%' AND eval_run = (SELECT MAX(eval_run) FROM {CATALOG}.ai_assist.evaluation WHERE suggestion_type LIKE 'AGENT%') ORDER BY 2, 3""",
        "AI Functions suggestions (ai_assist.suggestions, notebook 09)": f"""SELECT as_of_date, suggestion_type, ai_function, model, subject_key, ROUND(confidence, 2) AS confidence, status,
              substr(suggestion, 1, 160) AS suggestion FROM {CATALOG}.ai_assist.suggestions WHERE as_of_date >= '2026-02-26' ORDER BY 1, 2 LIMIT 40""",
    }.items():
        md = section(md, title, sql, s, limit=80)
    (EV / "06_ml_genai.md").write_text(md)


def genie(w):
    md = header("Genie Agent - FR 2052a Liquidity Risk Genie", w)
    md += f"Space `{GENIE_SPACE}` on the UC metric views, asked through the Genie Conversation API: the answer, the SQL it generated and the result.\n\n"
    for q in GENIE_QUESTIONS:
        start = w.api_client.do("POST", f"/api/2.0/genie/spaces/{GENIE_SPACE}/start-conversation", body={"content": q})
        path = f"/api/2.0/genie/spaces/{GENIE_SPACE}/conversations/{start['conversation_id']}/messages/{start['message_id']}"
        for _ in range(60):
            msg = w.api_client.do("GET", path)
            if msg.get("status") in ("COMPLETED", "FAILED", "CANCELLED"):
                break
            time.sleep(3)
        md += f"## Q: {q}\n\nstatus: {msg.get('status')}\n\n"
        for att in msg.get("attachments", []):
            if "text" in att:
                md += f"**Genie:** {att['text'].get('content', '')}\n\n"
            if "query" in att:
                qa = att["query"]
                md += (f"**Genie:** {qa['description']}\n\n" if qa.get("description") else "") + f"```sql\n{qa.get('query', '')}\n```\n\n"
                res = w.api_client.do("GET", f"{path}/attachments/{att['attachment_id']}/query-result")
                sr = res.get("statement_response", {})
                cols = [c["name"] for c in sr.get("manifest", {}).get("schema", {}).get("columns", [])]
                md += md_table(cols, sr.get("result", {}).get("data_array", []) or [], limit=25) + "\n\n"
        time.sleep(15)   # the Conversation API rate limit
    (EV / "07_genie.md").write_text(md)


def app_api(w, profile):
    token = json.loads(subprocess.check_output(["databricks", "auth", "token", "-p", profile]))["access_token"]
    md = header("Databricks App - API responses", w)
    md += f"App: {APP_URL} (FastAPI + React; reads Lakebase; calls Genie, the agents' serving endpoint and the jobs as its service principal).\n\n"
    for ep in APP_ENDPOINTS:
        t0 = time.time()
        r = requests.get(APP_URL + ep, headers={"Authorization": f"Bearer {token}"}, timeout=180)
        try:
            body = json.dumps(r.json(), indent=1, default=str)
        except ValueError:
            body = r.text
        body = body[:6000] + ("\n... (truncated)" if len(body) > 6000 else "")
        md += f"## GET {ep} -> {r.status_code} ({time.time() - t0:.2f} s)\n\n```json\n{body}\n```\n\n"
    (EV / "08_app_api.md").write_text(md)


def tests(w):
    out = subprocess.run([sys.executable, "-m", "pytest", str(ROOT / "tests"), "-v", "-p", "no:cacheprovider"], capture_output=True, text=True, cwd=ROOT).stdout
    qa = (EV / "qa_report.md").read_text().splitlines()[:4] if (EV / "qa_report.md").exists() else []
    md = header("Tests", w) + "## Offline unit tests (`python -m pytest tests -v`)\n\n```\n" + out[-12000:] + "\n```\n\n"
    md += "## Live QA suite (`scripts/qa/e2e_qa.py`) - full results in [qa_report.md](qa_report.md)\n\n" + "\n".join(qa) + "\n\n"
    md += "## User acceptance test of the write paths - see [uat_2026-02-24.md](uat_2026-02-24.md)\n"
    (EV / "09_tests.md").write_text(md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=os.environ.get("DATABRICKS_CONFIG_PROFILE"))
    ap.add_argument("--daily-run", type=int, help="the fr2052a-daily run whose notebooks to export (default: the latest successful run with ingest)")
    ap.add_argument("--extra-run", type=int, nargs="*", default=[], help="more (one-time) runs whose notebooks to export")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    w = WorkspaceClient(profile=a.profile)
    EV.mkdir(exist_ok=True)
    only = set(a.only or ["jobs", "notebooks", "lakeflow", "results", "uc", "lakebase", "ml", "genie", "app", "tests"])
    runs = job_runs(w)
    recent = w.api_client.do("GET", "/api/2.2/jobs/runs/list", query={"job_id": JOBS["fr2052a-daily"], "limit": 25, "expand_tasks": "true"}).get("runs", [])
    daily = a.daily_run or next((r["run_id"] for r in recent if r["state"].get("result_state") == "SUCCESS"
                                 and any(t["task_key"] == "ingest" and t["state"].get("result_state") == "SUCCESS" for t in r.get("tasks", []))), None)
    steps = [("notebooks", lambda: notebooks(w, runs, daily, a.extra_run)), ("lakeflow", lambda: lakeflow(w)), ("results", lambda: results(w)),
             ("uc", lambda: unity_catalog(w)), ("lakebase", lambda: lakebase(w)), ("ml", lambda: ml(w)), ("genie", lambda: genie(w)),
             ("app", lambda: app_api(w, a.profile)), ("tests", lambda: tests(w))]
    for name, fn in steps:
        if name in only:
            t0 = time.time()
            fn()
            print(f"{name}: {time.time() - t0:.0f}s")
    redact(w)
    print("evidence written to", EV)


def redact(w):
    """The evidence is published: replace workspace-specific identifiers with stable placeholders (jobs and run ids stay - they are
    counters inside the workspace and mean nothing outside it). Personal addresses -> user1@example.com, ...; the workspace URL, its id,
    the catalog, the app URL, the Lakebase host, service principals and other object ids (UUIDs, Genie / dashboard ids) -> <...>."""
    host = w.config.host.rstrip("/")
    fixed = [(host, "https://<workspace>.cloud.databricks.com"), (host.split("//")[-1].split(".")[0], "<workspace>"),
             (str(w.get_workspace_id()), "<workspace-id>"), (CATALOG, "<catalog>"), (TRACE_EXPERIMENT, "<experiment-id>")]
    sps = {SERVICE_PRINCIPALS[0]: "<app-service-principal>", **{sp: "<agents-service-principal>" for sp in SERVICE_PRINCIPALS[1:]}}
    patterns = [(EMAIL, "user{}@example.com"), (re.compile(r"https://[A-Za-z0-9.-]+\.databricksapps\.com"), "https://<app>.databricksapps.com"),
                (re.compile(r"\bep-[a-z0-9-]+\.database\.[a-z0-9.-]+\.databricks\.com"), "<lakebase-host>"),
                (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"), "<uuid-{}>"),
                (re.compile(r"\b01f[0-9a-f]{29}\b"), "<object-id-{}>")]
    home = re.compile(r"/Users/(?!<|user\d+@)[A-Za-z0-9._-]+")   # local paths (pytest output): /Users/<name>/... -> /Users/<user>/...
    seen = {}
    def sub(rx, label):
        def f(m):
            v = m.group(0)
            if v in sps:
                return sps[v]
            key = (label, v.lower())
            if key not in seen:
                seen[key] = label.format(sum(1 for k in seen if k[0] == label) + 1)
            return seen[key]
        return lambda t: rx.sub(f, t)
    subs = [sub(rx, label) for rx, label in patterns]
    for f in sorted(EV.rglob("*")):
        if f.is_file() and f.suffix in (".md", ".ipynb", ".json", ".txt"):
            t = f.read_text()
            m = t
            for a, b in fixed:
                if a:
                    m = m.replace(a, b)
            for s_ in subs:
                m = s_(m)
            m = home.sub("/Users/<user>", m)
            if m != t:
                f.write_text(m)


if __name__ == "__main__":
    main()
