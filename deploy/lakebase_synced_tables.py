"""Serve the app from Lakebase with synced tables (Unity Catalog -> Lakebase Postgres, one-way, Databricks-managed).

For each Delta table / view the app reads, this creates (idempotent):
  1. a source view  <catalog>.lakebase_src.<name>  = the table + a unique _row_key (most tables have no natural primary key);
  2. a synced table <catalog>.app_serving.<name>   (SNAPSHOT, bin-packed into ONE pipeline) -> Postgres app_serving.<name>;
  3. SELECT for the app's service principal on the Postgres schema.
Notebook 07 refreshes the pipeline after each pipeline run. The app's own tables (decisions, sign-off) stay in Postgres public
and are read back into Delta by notebooks 00 / 05 / 06 (custom, until Lakebase change data feed is GA).

  python deploy/lakebase_synced_tables.py --catalog <c> --warehouse <id> [--profile <p>]
  (also the task lakebase_tables of the job fr2052a-pipeline, after notebook 01 - creates what is missing, so a new workspace gets them)
"""
import argparse
import json
import time

from databricks.sdk import WorkspaceClient

# Postgres / app name -> Delta source (schema.table) in the catalog
TABLES = {
    "ai_evaluation": "ai_assist.evaluation",
    "ai_suggestions": "ai_assist.suggestions",
    "assessment_results": "dq.assessment_results",
    "calculation_detail": "reg_lcr.calculation_detail",
    "calculation_results": "reg_lcr.calculation_results",
    "cross_metric_recon": "audit.cross_metric_recon",
    "feed_monitor": "dq.feed_monitor",
    "filing_records": "reg_2052a.v_filing_records",
    "gl_reconciliation": "audit.gl_reconciliation",
    "gold_validation": "reg_2052a.gold_validation",
    "gold_validation_detail": "reg_2052a.gold_validation_detail",
    "i_a_assets": "reg_2052a.i_a_assets",
    "i_o_other": "reg_2052a.i_o_other",
    "i_s_secured": "reg_2052a.i_s_secured",
    "i_u_unsecured": "reg_2052a.i_u_unsecured",
    "intercompany_elimination": "audit.intercompany_elimination",
    "o_d_deposits": "reg_2052a.o_d_deposits",
    "o_o_other": "reg_2052a.o_o_other",
    "o_s_secured": "reg_2052a.o_s_secured",
    "o_w_wholesale": "reg_2052a.o_w_wholesale",
    "pid_derivation_summary": "audit.pid_derivation_summary",
    "pid_exceptions": "dq.pid_exceptions",
    "quarantine": "dq.quarantine",
    "ref_bank_holidays": "reference.ref_bank_holidays",
    "ref_collateral": "reference.ref_collateral",
    "ref_counterparty": "reference.ref_counterparty",
    "ref_customer_master": "reference.v_customer_master",
    "ref_firm_schema_values": "reference.ref_firm_schema_values",
    "ref_fx_rates": "reference.ref_fx_rates",
    "ref_legal_entity": "reference.ref_legal_entity",
    "ref_maturity_bucket": "reference.ref_maturity_bucket",
    "ref_product": "reference.ref_product",
    "ref_report_template": "reference.ref_report_template",
    "ref_reporting_entity": "reference.ref_reporting_entity",
    "ref_source_product_map": "reference.v_source_product_map",
    "ref_standard_product_type": "reference.ref_standard_product_type",
    "ref_stwf_mdrm": "reference.ref_stwf_mdrm",
    "rule_failures": "dq.rule_failures",
    "rules_dq": "reference.rules_dq",
    "rules_fed_psv": "reference.rules_fed_psv",
    "rules_lcr_appendix_vi": "reference.rules_lcr_appendix_vi",
    "rules_pid_derivation": "reference.rules_pid_derivation",
    "rules_spec": "reference.rules_spec",
    "rules_stwf_appendix_vii": "reference.rules_stwf_appendix_vii",
    "rules_validation": "reference.rules_validation",
    "s_b_balance_sheet": "reg_2052a.s_b_balance_sheet",
    "s_c_comments": "reg_2052a.s_c_comments",
    "s_dc_derivatives_collateral": "reg_2052a.s_dc_derivatives_collateral",
    "s_fx_foreign_exchange": "reg_2052a.s_fx_foreign_exchange",
    "s_i_informational": "reg_2052a.s_i_informational",
    "s_l_liquidity_risk_measurement": "reg_2052a.s_l_liquidity_risk_measurement",
    "spec_collateral_class_requirements": "reference.spec_collateral_class_requirements",
    "spec_counterparty_requirements": "reference.spec_counterparty_requirements",
    "spec_table_fields": "reference.spec_table_fields",
    "spec_tables": "reference.spec_tables",
    "submission_files": "reg_2052a.submission_files",
    "v_source_files": "conformed.v_source_files",
    "variance": "reg_2052a.variance",
}
# Large per-day tables, synced incrementally (TRIGGERED: inserts, updates and deletes of the change data feed - enabled in notebook 01)
# straight from the Delta table on its natural key.
TRIGGERED = {
    "source_position": ("conformed.source_position", ["as_of_date", "record_id"]),
    "entity_position": ("conformed.entity_position", ["as_of_date", "reporting_entity", "position_id"]),
    "record_lineage": ("reg_2052a.record_lineage", ["as_of_date", "record_key", "position_id"]),
}
# Synced tables cannot be built on a table with row / column security: fact_liquidity_position (internal_rating is column-masked)
# goes through a view that leaves the masked column out, so it never reaches Postgres (SNAPSHOT, natural key).
VIEWS = {
    "fact_liquidity_position": ("SELECT * EXCEPT (internal_rating) FROM {C}.conformed.fact_liquidity_position", ["as_of_date", "position_id"]),
}
BRANCH = "projects/fr2052a/branches/production"
DATABASE = "fr2052a"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=None, help="CLI profile (omit inside a job)")
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--warehouse", required=True)
    a = ap.parse_args()
    w, C = (WorkspaceClient(profile=a.profile) if a.profile else WorkspaceClient()), a.catalog

    def sql(s):
        r = w.statement_execution.execute_statement(warehouse_id=a.warehouse, statement=s, wait_timeout="50s")
        if r.status.state.value != "SUCCEEDED":
            raise RuntimeError(r.status.error.message if r.status.error else r.status.state)

    sql(f"CREATE SCHEMA IF NOT EXISTS {C}.lakebase_src COMMENT 'Source views for the Lakebase synced tables (one per app table, with a unique _row_key)'")
    sql(f"CREATE SCHEMA IF NOT EXISTS {C}.app_serving COMMENT 'Lakebase synced tables the fr2052a app reads (Postgres schema app_serving)'")
    for name, src in TABLES.items():
        sql(f"""CREATE OR REPLACE VIEW {C}.lakebase_src.{name} AS
                SELECT * EXCEPT (_h), CONCAT(_h, '-', CAST(ROW_NUMBER() OVER (PARTITION BY _h ORDER BY _h) AS STRING)) AS _row_key
                FROM (SELECT s.*, SHA2(TO_JSON(STRUCT(s.*)), 256) AS _h FROM {C}.{src} s)""")
    print(f"{len(TABLES)} source views")

    def get(name):
        try:
            return w.api_client.do("GET", f"/api/2.0/postgres/synced_tables/{C}.app_serving.{name}")
        except Exception:
            return None

    for name, (body, _) in VIEWS.items():
        sql(f"CREATE OR REPLACE VIEW {C}.lakebase_src.{name} AS " + body.format(C=C))
    for name, (src, _) in TRIGGERED.items():
        sql(f"ALTER TABLE {C}.{src} SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")
    plan = {n: (f"{C}.lakebase_src.{n}", ["_row_key"], "SNAPSHOT") for n in TABLES}
    plan.update({n: (f"{C}.lakebase_src.{n}", pk, "SNAPSHOT") for n, (_, pk) in VIEWS.items()})
    plan.update({n: (f"{C}.{src}", pk, "TRIGGERED") for n, (src, pk) in TRIGGERED.items()})

    pipeline = next((s["status"].get("pipeline_id") for s in map(get, plan) if s and s.get("status", {}).get("pipeline_id")), None)
    for name, (source, pk, policy) in plan.items():
        if get(name):
            continue
        spec = {"source_table_full_name": source, "branch": BRANCH, "postgres_database": DATABASE,
                "primary_key_columns": pk, "scheduling_policy": policy, "create_database_objects_if_missing": True}
        spec.update({"existing_pipeline_id": pipeline} if pipeline else {"new_pipeline_spec": {"storage_catalog": C, "storage_schema": "lakebase_src"}})
        w.api_client.do("POST", "/api/2.0/postgres/synced_tables", query={"synced_table_id": f"{C}.app_serving.{name}"}, body={"spec": spec})
        print("created", name)
        while not pipeline:
            time.sleep(10)
            pipeline = (get(name) or {}).get("status", {}).get("pipeline_id")
    print("pipeline", pipeline, "- notebook 07 refreshes it after each run; first load: start an update of the pipeline")


if __name__ == "__main__":
    main()   # no sys.exit: a serverless Python task fails on any SystemExit, even 0 (errors raise)
