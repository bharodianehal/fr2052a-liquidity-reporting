# Lakebase (Postgres) - operational serving for the app

Captured 2026-11-05 15:45 UTC from `https://<workspace>.cloud.databricks.com` by `deploy/capture_evidence.py`.

Endpoint `projects/fr2052a/branches/production/endpoints/primary` (host `<lakebase-host>`), database `fr2052a`. Schema `app_serving` = Unity Catalog synced tables (Delta -> Postgres, one pipeline); schema `public` = the app's own tables (the checker's decisions, sign-off - append-only for the audit trail).

## A synced table's status (`GET /api/2.0/postgres/synced_tables/...calculation_results`)

```json
{
 "message": "Synced table creation succeeded using Delta Live Tables: https://<workspace>.cloud.databricks.com#joblist/pipelines/<uuid-1>/updates/<uuid-12>.",
 "detailed_state": "SYNCED_TABLE_ONLINE_NO_PENDING_UPDATE",
 "last_sync": {
  "sync_start_time": "2026-11-05T14:31:53.324428Z",
  "sync_end_time": "2026-11-05T14:31:59.082881Z"
 },
 "pipeline_id": "<uuid-1>",
 "unity_catalog_provisioning_state": "ACTIVE",
 "project": "projects/fr2052a",
 "postgres_database": "fr2052a",
 "primary_key_columns": [
  "_row_key"
 ],
 "branch": "projects/fr2052a/branches/production",
 "source_table_full_name": "<catalog>.lakebase_src.calculation_results",
 "scheduling_policy": "SNAPSHOT"
}
```

## Tables in `app_serving` (62)

| table | rows |
|---|---|
| ai_evaluation | 70 |
| ai_suggestions | 63 |
| assessment_results | 60 |
| calculation_detail | 2038 |
| calculation_results | 10 |
| cross_metric_recon | 20 |
| entity_position | 3691 |
| fact_liquidity_position | 1963 |
| feed_monitor | 50 |
| filing_records | 2309 |
| gl_reconciliation | 111 |
| gold_validation | 5416 |
| gold_validation_detail | 62 |
| i_a_assets | 330 |
| i_o_other | 142 |
| i_s_secured | 148 |
| i_u_unsecured | 178 |
| intercompany_elimination | 31 |
| o_d_deposits | 420 |
| o_o_other | 312 |
| o_s_secured | 173 |
| o_w_wholesale | 180 |
| pid_derivation_summary | 5 |
| pid_exceptions | 11 |
| quarantine | 8 |
| record_lineage | 3691 |
| ref_bank_holidays | 112 |
| ref_collateral | 91 |
| ref_counterparty | 19 |
| ref_customer_master | 36 |
| ref_firm_schema_values | 15 |
| ref_fx_rates | 12 |
| ref_legal_entity | 5 |
| ref_maturity_bucket | 78 |
| ref_product | 147 |
| ref_report_template | 1 |
| ref_reporting_entity | 3 |
| ref_source_product_map | 117 |
| ref_standard_product_type | 98 |
| ref_stwf_mdrm | 52 |
| rule_failures | 8 |
| rules_dq | 12 |
| rules_fed_psv | 14 |
| rules_lcr_appendix_vi | 74 |
| rules_pid_derivation | 154 |
| rules_spec | 409 |
| rules_stwf_appendix_vii | 26 |
| rules_validation | 652 |
| s_b_balance_sheet | 18 |
| s_c_comments | 11 |
| s_dc_derivatives_collateral | 252 |
| s_fx_foreign_exchange | 66 |
| s_i_informational | 50 |
| s_l_liquidity_risk_measurement | 40 |
| source_position | 1755 |
| spec_collateral_class_requirements | 147 |
| spec_counterparty_requirements | 1140 |
| spec_table_fields | 219 |
| spec_tables | 14 |
| submission_files | 35 |
| v_source_files | 14130 |
| variance | 113 |

## Tables in `public` (15)

| table | rows |
|---|---|
| adjustments | 0 |
| agent_events | 542 |
| agent_runs | 7 |
| ai_decisions | 0 |
| break_decisions | 31 |
| breaks | 127 |
| customer_master_approvals | 0 |
| dq_fixes | 0 |
| lcr_disclosure_sections | 36 |
| position_corrections | 0 |
| proposals | 127 |
| release_memos | 1 |
| source_product_map_approvals | 0 |
| submission_review | 36 |
| validation_decisions | 15 |

## What the app reads: `SELECT ... FROM calculation_results` (synced)

| as_of_date | entity_id | total_hqla | total_net_cash_outflows | lcr_ratio | lcr_compliant |
|---|---|---|---|---|---|
| 2026-02-23 | ENT001 | 51066.1334 | 34568.8915 | 1.4772 | True |
| 2026-02-23 | ENT002 | 47839.2623 | 27160.1533 | 1.7614 | True |
| 2026-02-24 | ENT001 | 33728.5639 | 45768.9997 | 0.7369 | False |
| 2026-02-24 | ENT002 | 30477.7176 | 28468.3971 | 1.0706 | True |
| 2026-02-25 | ENT001 | 50020.2253 | 48600.8306 | 1.0292 | True |
| 2026-02-25 | ENT002 | 47568.9700 | 30237.8069 | 1.5732 | True |
| 2026-02-26 | ENT001 | 51000.7985 | 37123.0834 | 1.3738 | True |
| 2026-02-26 | ENT002 | 47691.0589 | 25745.3133 | 1.8524 | True |
| 2026-02-27 | ENT001 | 50622.0584 | 37583.4473 | 1.3469 | True |
| 2026-02-27 | ENT002 | 47289.7669 | 20330.1087 | 2.3261 | True |

## The checker's decisions: `break_decisions` (app-owned, append-only)

| decision_id | break_id | proposal_id | action | reason_code | decided_by | decided_at |
|---|---|---|---|---|---|---|
| af50f0a8-c57 | BRK-0227-023 |  | APPROVE | RERUN | checker | 2026-11-04 23:02:03.649874 |
| 7c0dc8d4-055 | BRK-0227-027 |  | APPROVE | RERUN | checker | 2026-11-04 23:02:03.649874 |
| 102a64b7-04f | BRK-0227-020 |  | APPROVE | RERUN | checker | 2026-11-04 23:02:03.649874 |
| 22d9243b-805 | BRK-0227-022 |  | APPROVE | RERUN | checker | 2026-11-04 23:02:03.649874 |
| 05dde9b2-bd1 | BRK-0227-024 |  | APPROVE | RERUN | checker | 2026-11-04 23:02:03.649874 |
| 1e0bd996-da9 | BRK-0227-026 |  | APPROVE | RERUN | checker | 2026-11-04 23:02:03.649874 |
| a723735c-5a1 | BRK-0227-016 |  | APPROVE | RERUN | checker | 2026-11-04 23:02:03.649874 |
| c59ec60f-692 | BRK-0227-017 |  | APPROVE | RERUN | checker | 2026-11-04 23:02:03.649874 |
| 81520bf1-d1a | BRK-0227-014 |  | APPROVE | RERUN | checker | 2026-11-04 23:02:03.649874 |
| 41b9f51a-ff3 | BRK-0227-021 |  | APPROVE | RERUN | checker | 2026-11-04 23:02:03.649874 |
| e378c284-3e6 | BRK-0227-015 |  | APPROVE | RERUN | checker | 2026-11-04 23:02:03.649874 |
| 70771ef8-dbd | BRK-0227-019 |  | APPROVE | RERUN | checker | 2026-11-04 23:02:03.649874 |
| 75068c20-6fc | BRK-0227-018 |  | APPROVE | RERUN | checker | 2026-11-04 23:02:03.649874 |
| e6bbd998-b38 | BRK-0227-025 |  | APPROVE | RERUN | checker | 2026-11-04 23:02:03.649874 |
| 1e9442cc-cf6 | BRK-0227-028 |  | APPROVE | RERUN | checker | 2026-11-04 23:02:03.649874 |

