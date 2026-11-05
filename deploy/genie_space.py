"""Generate the FR 2052a Liquidity Risk Genie space (serialized_space version 2) as a resource of the app bundle:
app/resources/genie_space.yml (catalog-free - the bundle fills in ${var.catalog} and ${var.warehouse_id}).

  python deploy/genie_space.py          # after changing the tables, instructions, examples or benchmarks below; then deploy the app bundle

The space lives in the workspace folder /Users/<you>/fr2052a (workspace list / export do not show it - never delete that folder).
"""
import json, uuid
from pathlib import Path

HERE = Path(__file__).parent
TITLE = "FR 2052a Liquidity Risk Genie"
DESCRIPTION = ("Ask questions about the FR 2052a 6G filing of three reporting entities (the 13 data tables), its validation, the Fed's "
               "post-submission checks, reporting runs and sign-off, variance, drill-down to source records, PID derivation and data quality, "
               "FR Y-15 STWF, AI suggestions, and the LCR per entity (HQLA, net cash outflows, LCR ratio).")

TABLES = [
    "reg_2052a.fr2052a_metrics", "reg_lcr.fr2052a_lcr_metrics", "reg_2052a.fr2052a_check_metrics",   # the semantic layer (metric views)
    "reg_2052a.v_filing_records", "reg_2052a.i_a_assets", "reg_2052a.o_d_deposits", "reg_2052a.o_w_wholesale",
    "reg_2052a.gold_validation", "reg_2052a.submission_files", "reg_2052a.submission_review", "reg_2052a.variance",
    "reg_2052a.stwf_schedule_g", "reg_2052a.record_lineage", "reg_2052a.adjustments",
    "reg_lcr.calculation_results", "reg_lcr.calculation_detail", "dq.assessment_results", "dq.pid_exceptions", "dq.feed_monitor",
    "audit.pid_derivation_summary", "audit.gl_reconciliation", "audit.intercompany_elimination",
    "conformed.fact_liquidity_position", "conformed.entity_position", "ai_assist.suggestions",
    "reference.ref_product", "reference.ref_collateral", "reference.rules_pid_derivation", "reference.ref_reporting_entity",
    "reference.ref_legal_entity", "reference.rules_fed_psv",
]

INSTRUCTIONS = """\
SEMANTIC LAYER - use the Unity Catalog metric views first, with MEASURE() and GROUP BY on their dimensions:
- reg_2052a.fr2052a_metrics (one row per reported FR 2052a record): MEASURE(reported_amount_usd_mm), MEASURE(inflows_usd_mm), MEASURE(outflows_usd_mm), MEASURE(inflows_30d_usd_mm), MEASURE(outflows_30d_usd_mm), MEASURE(net_30d_outflows_usd_mm), MEASURE(records), MEASURE(positions), MEASURE(reported_lcr), MEASURE(reported_nsfr); dimensions as_of_date, reporting_entity, entity_name, scope_type, table_code, table_name, flow_side, product_id, product_name, sub_product, counterparty, collateral_class, maturity_bucket, maturity_bucket_order, within_30_days, currency, converted.
- reg_lcr.fr2052a_lcr_metrics (LCR engine, per LCR entity and day): MEASURE(lcr) (a ratio of sums - never average daily ratios), MEASURE(hqla_usd_mm), MEASURE(level1_hqla_usd_mm), MEASURE(level2a_hqla_usd_mm), MEASURE(level2b_hqla_usd_mm), MEASURE(total_outflows_usd_mm), MEASURE(total_inflows_usd_mm), MEASURE(capped_inflows_usd_mm), MEASURE(net_cash_outflows_usd_mm), MEASURE(compliant_days); dimensions as_of_date, entity_id.
- reg_2052a.fr2052a_check_metrics (validation results): MEASURE(checks), MEASURE(checks_passed), MEASURE(checks_failed), MEASURE(warnings), MEASURE(blocking_errors), MEASURE(fed_checks_not_passing), MEASURE(records_failed); dimensions as_of_date, check_source, rule_id, rule_name, table_code, severity, status.
Use the other tables only for record-level detail the metric views do not carry (positions, lineage, run status, variance, AI suggestions, STWF). Never re-derive an amount, LCR or check count that a measure already defines.
This space covers a synthetic US bank holding company (Category I) filing the Federal Reserve FR 2052a Complex Institution Liquidity Monitoring Report in the 6G XML format for three reporting entities in one file: ENT001 Acme Financial Holdings (Consolidated), ENT002 Acme National Bank N.A. (solo), ENT003 Acme Securities LLC (solo broker-dealer). reference.ref_reporting_entity lists them; reference.ref_legal_entity is the legal-entity tree (LE00 parent).
Always filter or group by reporting_entity (entity_id in the LCR and validation tables). When the user names no entity, use ENT001 and say so. Never add the three entities together - the consolidated entity already includes the subsidiaries.
Amounts are in millions of the reported currency; reported_amount_usd in v_filing_records is the USD equivalent. Show amounts with a $ sign, thousands separators and an "M" suffix, e.g. $50,950M.
Reporting dates are the business days 2026-01-02 to 2026-02-27 (as_of_date); month-ends are 2026-01-30 and 2026-02-27. When the user does not give a date, use the latest as_of_date.
FR 2052a tables (table_code): I.A Inflows-Assets, I.U Inflows-Unsecured, I.S Inflows-Secured, I.O Inflows-Other, O.D Outflows-Deposits, O.W Outflows-Wholesale, O.S Outflows-Secured, O.O Outflows-Other, S.DC Derivatives & Collateral, S.L Liquidity Risk Measurement, S.B Balance Sheet, S.I Informational, S.FX Foreign Exchange.
product_id is the FR 2052a product identifier (PID), e.g. 'O.D.1'; join reference.ref_product on product_id for product_name.
reg_2052a.v_filing_records has one row per filed record across all 13 tables with one primary amount; use it for cross-table questions. S.L.6 (LCR) and S.L.10 (NSFR) carry ratios, not amounts - exclude them from sums.
Each filed record (record_key) aggregates positions; reg_2052a.record_lineage maps record_key to the Silver positions and source record_ids (an approved adjustment shows as position_id 'ADJ:<id>'). conformed.entity_position says which Silver positions each reporting entity reports and whether they are EXTERNAL, INTERNAL (with an affiliate outside the entity scope) or SELF (a data error); audit.intercompany_elimination lists positions eliminated inside a scope.
Submission: every generation is a reporting run (run_number) per as_of_date. reg_2052a.submission_files has one row per 6G file (Primary, Reduced at month-end, Comment) and run, with xsd_valid and release_status (BLOCKED or READY_FOR_REVIEW); version is the 6G header version (1 + versions already submitted). reg_2052a.submission_review is the run-control log: GENERATED, REPORTING_REQUESTED, OVERRIDE_REQUESTED, APPROVED, REJECTED, SUBMITTED. The latest status of a run is the row with the latest action_timestamp.
Validation: reg_2052a.gold_validation has one row per check per date; rule_source is '6G BR' (Fed business requirements), '6G BR General', '6G XSD', 'Instructions' (appendix rules) or 'Fed PSV' (the Federal Reserve's 14 post-submission checks, rule_id PSV-01..PSV-14, described in reference.rules_fed_psv); status PASS / FAIL / WARNING / NOT_APPLICABLE.
LCR: reg_lcr.calculation_results has one row per as_of_date and LCR entity (entity_id ENT001, ENT002; the broker-dealer has no standalone LCR); lcr_ratio is a ratio (1.3438 = 134.38%); the minimum is 100%.
Variance: reg_2052a.variance has the day-over-day change per entity x table (series_level TABLE) and top PIDs (PID) with the ai_forecast expected range (lower_usd, upper_usd); is_anomaly marks movements outside it.
FR Y-15: reg_2052a.stwf_schedule_g is the short-term wholesale funding (Schedule G) computed from the FR 2052a data for ENT001, with its FR Y-15 MDRM codes (FR 2052a itself has no MDRM codes - it is identified by product_id); weighted_amount_usd applies the 12 CFR 217.406 weights.
Data quality: dq.feed_monitor is feed completeness per day; dq.assessment_results has one row per DQ rule per date; dq.pid_exceptions lists positions held out of the filing (NO_RULE, or CUSTOMER_PENDING awaiting classification).
AI: ai_assist.suggestions holds proposals from Databricks AI Functions (customer classification, product mapping, PID exception, rule explanation, variance commentary, comment drafts) and the human decision (status PROPOSED / ACCEPTED / REJECTED).
All data is synthetic.
"""

SAMPLE_QUESTIONS = [
    "What is the LCR per entity on the latest reporting date and is it compliant?",
    "Is the latest reporting run ready to sign off, and did the XML pass XSD validation?",
    "Which Fed post-submission checks are not passing on the latest date?",
    "Break down reported outflows by FR 2052a table for each reporting entity on the latest date",
    "Which movements were outside the ai_forecast range on the latest date?",
    "What is the weighted short-term wholesale funding by tier on the latest date?",
]

EXAMPLES = [
    ("What is the LCR per entity on the latest reporting date?",
     """SELECT as_of_date, entity_id, ROUND(MEASURE(lcr) * 100, 2) AS lcr_pct, MEASURE(hqla_usd_mm) AS hqla_usd_mm, MEASURE(net_cash_outflows_usd_mm) AS nco_usd_mm
FROM {c}.reg_lcr.fr2052a_lcr_metrics
WHERE as_of_date = (SELECT MAX(as_of_date) FROM {c}.reg_lcr.calculation_results)
GROUP BY ALL ORDER BY entity_id""",
     "LCR questions: use the LCR metric view; one row per LCR entity."),
    ("Show the consolidated LCR trend over time",
     """SELECT as_of_date, ROUND(MEASURE(lcr) * 100, 2) AS lcr_pct, MEASURE(hqla_usd_mm) AS hqla_usd_mm, MEASURE(net_cash_outflows_usd_mm) AS nco_usd_mm
FROM {c}.reg_lcr.fr2052a_lcr_metrics WHERE entity_id = 'ENT001' GROUP BY ALL ORDER BY as_of_date""",
     "LCR / HQLA / net cash outflow trends; filter one entity."),
    ("Break down outflows by FR 2052a table and entity for the latest date",
     """SELECT reporting_entity, table_code, table_name, MEASURE(outflows_usd_mm) AS outflows_usd_mm, MEASURE(records) AS records, MEASURE(positions) AS positions
FROM {c}.reg_2052a.fr2052a_metrics
WHERE as_of_date = (SELECT MAX(as_of_date) FROM {c}.reg_2052a.v_filing_records) AND flow_side = 'Outflow'
GROUP BY ALL ORDER BY reporting_entity, outflows_usd_mm DESC""",
     "Table-level breakdowns: use the FR 2052a metric view; keep entities separate."),
    ("Top products by reported amount for the consolidated entity on the latest date",
     """SELECT table_code, product_id, product_name, MEASURE(reported_amount_usd_mm) AS usd_mm
FROM {c}.reg_2052a.fr2052a_metrics
WHERE as_of_date = (SELECT MAX(as_of_date) FROM {c}.reg_2052a.v_filing_records) AND reporting_entity = 'ENT001'
GROUP BY ALL ORDER BY usd_mm DESC LIMIT 10""",
     "Product (PID) questions across tables."),
    ("Top counterparties by deposit outflows for ENT001 on the latest date",
     """SELECT counterparty, MEASURE(outflows_usd_mm) AS outflows_usd_mm, MEASURE(records) AS records
FROM {c}.reg_2052a.fr2052a_metrics
WHERE as_of_date = (SELECT MAX(as_of_date) FROM {c}.reg_2052a.v_filing_records) AND reporting_entity = 'ENT001' AND table_code = 'O.D'
GROUP BY ALL ORDER BY outflows_usd_mm DESC LIMIT 10""",
     "Counterparty breakdowns of a table."),
    ("What are the 30-day outflows and inflows by entity on the latest date?",
     """SELECT reporting_entity, MEASURE(outflows_30d_usd_mm) AS outflows_30d, MEASURE(inflows_30d_usd_mm) AS inflows_30d, MEASURE(net_30d_outflows_usd_mm) AS net_30d
FROM {c}.reg_2052a.fr2052a_metrics WHERE as_of_date = (SELECT MAX(as_of_date) FROM {c}.reg_2052a.v_filing_records) GROUP BY ALL ORDER BY 1""",
     "Unweighted 30-day maturity flows; the weighted view is the LCR."),
    ("How many checks failed or warned on the latest date, by source?",
     """SELECT check_source, MEASURE(checks) AS checks, MEASURE(checks_failed) AS failed, MEASURE(warnings) AS warnings, MEASURE(blocking_errors) AS blocking
FROM {c}.reg_2052a.fr2052a_check_metrics WHERE as_of_date = (SELECT MAX(as_of_date) FROM {c}.reg_2052a.gold_validation) GROUP BY ALL ORDER BY 1""",
     "Validation summaries: use the check metric view."),
    ("Which checks did not pass on the latest date?",
     """SELECT rule_id, rule_source, table_code, rule_name, severity, status, records_failed, failure_details
FROM {c}.reg_2052a.gold_validation
WHERE as_of_date = (SELECT MAX(as_of_date) FROM {c}.reg_2052a.gold_validation) AND status IN ('FAIL', 'WARNING')
ORDER BY status, rule_id""",
     "Detail of the checks that did not pass (the failure text is on gold_validation)."),
    ("What is the status of the latest reporting run?",
     """SELECT f.as_of_date, f.run_number, f.version, f.file_type, f.file_name, f.record_count, f.xsd_valid, f.release_status,
       (SELECT MAX_BY(r.status, r.action_timestamp) FROM {c}.reg_2052a.submission_review r
        WHERE r.as_of_date = f.as_of_date AND r.run_number = f.run_number) AS run_status
FROM {c}.reg_2052a.submission_files f
WHERE f.as_of_date = (SELECT MAX(as_of_date) FROM {c}.reg_2052a.submission_files)
  AND f.run_number = (SELECT MAX(run_number) FROM {c}.reg_2052a.submission_files x WHERE x.as_of_date = f.as_of_date)""",
     "Run status and the 6G files."),
    ("Which movements were outside the expected range on the latest date?",
     """SELECT reporting_entity, series_level, table_code, product_id, prior_amount_usd, amount_usd, ROUND(change_pct, 1) AS change_pct, lower_usd, upper_usd
FROM {c}.reg_2052a.variance
WHERE as_of_date = (SELECT MAX(as_of_date) FROM {c}.reg_2052a.variance) AND is_anomaly
ORDER BY ABS(amount_usd - prior_amount_usd) DESC""",
     "Variance / anomaly questions; the range comes from ai_forecast."),
]


BENCHMARKS = [   # (question, gold SQL) - Genie's answer is compared with the gold result
    ("What is the LCR of ENT001 on 2026-02-27?",
     "SELECT ROUND(MEASURE(lcr) * 100, 2) AS lcr_pct FROM {c}.reg_lcr.fr2052a_lcr_metrics WHERE entity_id = 'ENT001' AND as_of_date = '2026-02-27'"),
    ("What is the LCR of the bank ENT002 on 2026-02-27?",
     "SELECT ROUND(MEASURE(lcr) * 100, 2) AS lcr_pct FROM {c}.reg_lcr.fr2052a_lcr_metrics WHERE entity_id = 'ENT002' AND as_of_date = '2026-02-27'"),
    ("Total deposit outflows (O.D) for ENT001 on 2026-02-27 in USD millions",
     "SELECT MEASURE(outflows_usd_mm) AS outflows_usd_mm FROM {c}.reg_2052a.fr2052a_metrics WHERE reporting_entity = 'ENT001' AND as_of_date = '2026-02-27' AND table_code = 'O.D'"),
    ("How many FR 2052a records did each reporting entity report on 2026-02-27?",
     "SELECT reporting_entity, MEASURE(records) AS records FROM {c}.reg_2052a.fr2052a_metrics WHERE as_of_date = '2026-02-27' GROUP BY ALL ORDER BY 1"),
    ("Top 5 counterparties by O.D outflows for ENT001 on 2026-02-27",
     "SELECT counterparty, MEASURE(outflows_usd_mm) AS outflows_usd_mm FROM {c}.reg_2052a.fr2052a_metrics WHERE reporting_entity = 'ENT001' AND as_of_date = '2026-02-27' AND table_code = 'O.D' GROUP BY ALL ORDER BY 2 DESC LIMIT 5"),
    ("How many blocking errors and warnings were there on 2026-02-27?",
     "SELECT MEASURE(blocking_errors) AS blocking_errors, MEASURE(warnings) AS warnings FROM {c}.reg_2052a.fr2052a_check_metrics WHERE as_of_date = '2026-02-27'"),
    ("Which Fed post-submission checks did not pass on 2026-02-27?",
     "SELECT rule_id, rule_name, status FROM {c}.reg_2052a.gold_validation WHERE as_of_date = '2026-02-27' AND rule_source = 'Fed PSV' AND status <> 'PASS' ORDER BY rule_id"),
    ("Net 30-day outflows for ENT002 on 2026-02-27",
     "SELECT MEASURE(net_30d_outflows_usd_mm) AS net_30d_outflows_usd_mm FROM {c}.reg_2052a.fr2052a_metrics WHERE reporting_entity = 'ENT002' AND as_of_date = '2026-02-27'"),
]
# Not attached to the space: Genie certified-answer functions do not accept DATE arguments. The agent behind the app's
# Genie page calls them through the managed UC functions MCP server instead.
FUNCTIONS = ["ai_assist.filing_status", "ai_assist.validation_issues", "ai_assist.lcr_summary", "ai_assist.variance_anomalies",
             "ai_assist.record_drilldown", "ai_assist.open_suggestions", "ai_assist.pid_rule_lookup"]


def sid(kind: str, key: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"fr2052a/{kind}/{key}").hex


def lines(text: str) -> list[str]:
    parts = text.strip("\n").split("\n")
    return [p + "\n" for p in parts[:-1]] + [parts[-1]]


def build(catalog: str) -> dict:
    space = {
        "version": 2,
        "config": {"sample_questions": [{"id": sid("sample", q), "question": [q]} for q in SAMPLE_QUESTIONS]},
        "data_sources": {"tables": [{"identifier": f"{catalog}.{t}"} for t in TABLES]},
        "instructions": {
            "text_instructions": [{"id": sid("text", "main"), "content": lines(INSTRUCTIONS)}],
            "example_question_sqls": [{"id": sid("example", q), "question": [q], "sql": lines(sql.format(c=catalog)),
                                       "usage_guidance": [g]} for q, sql, g in EXAMPLES],
        },
        "benchmarks": {"questions": [{"id": sid("benchmark", q), "question": [q],
                                      "answer": [{"format": "SQL", "content": lines(sql.format(c=catalog))}]} for q, sql in BENCHMARKS]},
    }
    space["data_sources"]["tables"].sort(key=lambda t: t["identifier"])
    space["config"]["sample_questions"].sort(key=lambda x: x["id"])
    space["instructions"]["example_question_sqls"].sort(key=lambda x: x["id"])
    space["benchmarks"]["questions"].sort(key=lambda x: x["id"])
    return space


def main():
    payload = json.dumps(build("${var.catalog}"))
    out = HERE.parent / "app" / "resources" / "genie_space.yml"
    out.parent.mkdir(exist_ok=True)
    out.write_text(
        "# Generated by deploy/genie_space.py - do not edit by hand. The FR 2052a Genie space (Genie Agent on the UC metric views),\n"
        "# in the workspace folder /Users/<you>/fr2052a; the app embeds it and calls it (app resource genie-space).\n"
        "resources:\n  genie_spaces:\n    fr2052a_genie:\n"
        f"      title: {json.dumps(TITLE)}\n      description: {json.dumps(DESCRIPTION)}\n"
        "      warehouse_id: ${var.warehouse_id}\n"
        "      parent_path: /Workspace/Users/${workspace.current_user.userName}/fr2052a\n"
        f"      serialized_space: {json.dumps(payload)}\n")
    print("wrote", out.relative_to(HERE.parent))


if __name__ == "__main__":
    main()
