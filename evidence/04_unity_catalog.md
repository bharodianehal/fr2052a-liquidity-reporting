# Unity Catalog governance

Captured 2026-11-05 18:14 UTC from `https://<workspace>.cloud.databricks.com` by `deploy/capture_evidence.py`.

## Schemas of the catalog

```sql
SELECT schema_name, comment FROM <catalog>.information_schema.schemata WHERE schema_name IN ('reference', 'raw', 'dq', 'conformed', 'reg_2052a', 'reg_lcr', 'audit', 'ai_assist', 'lakebase_src', 'app_serving') ORDER BY 1
```

| schema_name | comment |
|---|---|
| ai_assist | Databricks-native AI suggestions and their human decisions |
| app_serving | Lakebase synced tables the fr2052a app reads (Postgres schema app_serving) |
| audit | Control - GL reconciliation, cross-metric consistency, eliminations, PID derivation accuracy, data lineage |
| conformed | Silver - harmonized golden source, only DQ-passed records |
| dq | Data Quality Gate - DQ assessment results and quarantine between Bronze and Silver |
| lakebase_src | Source views for the Lakebase synced tables (one per app table, with a unique _row_key) |
| raw | Bronze - source system extracts ingested by Lakeflow |
| reference | Reference data - FR 2052a specification tables and firm configuration, versioned by reg_version |
| reg_2052a | Gold - FR 2052a filing: the 13 data tables + Comments, validation and XML |
| reg_lcr | Gold - LCR calculation mart (owned by Treasury/ALM) |

## Tags (information_schema)

```sql
SELECT 'schema' AS level, schema_name AS object, '' AS column_name, tag_name, tag_value FROM <catalog>.information_schema.schema_tags WHERE tag_name LIKE 'fr2052a_%' UNION ALL SELECT 'table', schema_name || '.' || table_name, '', tag_name, tag_value FROM <catalog>.information_schema.table_tags WHERE tag_name LIKE 'fr2052a_%' UNION ALL SELECT 'column', schema_name || '.' || table_name, column_name, tag_name, tag_value FROM <catalog>.information_schema.column_tags WHERE tag_name LIKE 'fr2052a_%' ORDER BY 1, 2, 3, 4
```

| level | object | column_name | tag_name | tag_value |
|---|---|---|---|---|
| column | conformed.fact_liquidity_position | counterparty | fr2052a_sensitivity | confidential |
| column | conformed.fact_liquidity_position | customer_id | fr2052a_sensitivity | confidential |
| column | conformed.fact_liquidity_position | forward_start_amount | fr2052a_unit | millions_of_reported_currency |
| column | conformed.fact_liquidity_position | internal_rating | fr2052a_sensitivity | restricted |
| column | conformed.fact_liquidity_position | market_value | fr2052a_unit | millions_of_reported_currency |
| column | conformed.fact_liquidity_position | principal_amount | fr2052a_unit | millions_of_reported_currency |
| column | raw.deposits | internal_rating | fr2052a_sensitivity | restricted |
| column | raw.derivatives | internal_rating | fr2052a_sensitivity | restricted |
| column | raw.funding | internal_rating | fr2052a_sensitivity | restricted |
| column | raw.loans | internal_rating | fr2052a_sensitivity | restricted |
| column | raw.securities | internal_rating | fr2052a_sensitivity | restricted |
| column | reg_2052a.i_a_assets | forward_start_amount | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.i_a_assets | lendable_value | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.i_a_assets | market_value | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.i_o_other | collateral_value | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.i_o_other | forward_start_amount | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.i_o_other | maturity_amount | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.i_s_secured | collateral_value | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.i_s_secured | forward_start_amount | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.i_s_secured | maturity_amount | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.i_u_unsecured | forward_start_amount | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.i_u_unsecured | maturity_amount | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.o_d_deposits | collateral_value | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.o_d_deposits | maturity_amount | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.o_o_other | collateral_value | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.o_o_other | forward_start_amount | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.o_o_other | maturity_amount | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.o_s_secured | collateral_value | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.o_s_secured | forward_start_amount | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.o_s_secured | maturity_amount | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.o_w_wholesale | collateral_value | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.o_w_wholesale | forward_start_amount | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.o_w_wholesale | maturity_amount | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.s_b_balance_sheet | collateral_value | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.s_b_balance_sheet | market_value | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.s_b_balance_sheet | maturity_amount | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.s_dc_derivatives_collateral | market_value | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.s_fx_foreign_exchange | forward_start_amount_currency_1 | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.s_fx_foreign_exchange | forward_start_amount_currency_2 | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.s_fx_foreign_exchange | maturity_amount_currency_1 | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.s_fx_foreign_exchange | maturity_amount_currency_2 | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.s_i_informational | market_value | fr2052a_unit | millions_of_reported_currency |
| column | reg_2052a.s_l_liquidity_risk_measurement | market_value | fr2052a_unit | millions_of_reported_currency |
| column | reg_lcr.calculation_results | capped_inflows | fr2052a_unit | millions_of_reported_currency |
| column | reg_lcr.calculation_results | level1_hqla | fr2052a_unit | millions_of_reported_currency |
| column | reg_lcr.calculation_results | level2a_hqla_adjusted | fr2052a_unit | millions_of_reported_currency |
| column | reg_lcr.calculation_results | level2b_hqla_adjusted | fr2052a_unit | millions_of_reported_currency |
| column | reg_lcr.calculation_results | total_hqla | fr2052a_unit | millions_of_reported_currency |
| column | reg_lcr.calculation_results | total_inflows | fr2052a_unit | millions_of_reported_currency |
| column | reg_lcr.calculation_results | total_net_cash_outflows | fr2052a_unit | millions_of_reported_currency |
| column | reg_lcr.calculation_results | total_outflows | fr2052a_unit | millions_of_reported_currency |
| schema | audit |  | fr2052a_domain | liquidity_risk |
| schema | audit |  | fr2052a_layer | control |
| schema | audit |  | fr2052a_owner | risk_control |
| schema | conformed |  | fr2052a_domain | liquidity_risk |
| schema | conformed |  | fr2052a_layer | silver |
| schema | conformed |  | fr2052a_owner | data_governance |
| schema | dq |  | fr2052a_domain | liquidity_risk |
| schema | dq |  | fr2052a_layer | dq_gate |
| schema | dq |  | fr2052a_owner | data_governance |
| schema | raw |  | fr2052a_domain | liquidity_risk |
| schema | raw |  | fr2052a_layer | bronze |
| schema | raw |  | fr2052a_owner | platform_engineering |
| schema | reference |  | fr2052a_domain | liquidity_risk |
| schema | reference |  | fr2052a_layer | reference |
| schema | reference |  | fr2052a_owner | regulatory_reporting |
| schema | reg_2052a |  | fr2052a_domain | liquidity_risk |
| schema | reg_2052a |  | fr2052a_layer | gold |
| schema | reg_2052a |  | fr2052a_owner | regulatory_reporting |
| schema | reg_2052a |  | fr2052a_regulation | FR_2052a_6G |
| schema | reg_lcr |  | fr2052a_domain | liquidity_risk |
| schema | reg_lcr |  | fr2052a_layer | gold |
| schema | reg_lcr |  | fr2052a_owner | treasury_alm |
| schema | reg_lcr |  | fr2052a_regulation | 12_CFR_249 |
| table | conformed.fact_liquidity_position |  | fr2052a_classification | confidential |
| table | conformed.fact_liquidity_position |  | fr2052a_contains | counterparty_ratings |
| table | reference.ref_customer_master |  | fr2052a_classification | confidential |
| table | reference.ref_customer_master |  | fr2052a_owner | data_governance |
| table | reference.rules_pid_derivation |  | fr2052a_change_control | required |
| table | reference.rules_pid_derivation |  | fr2052a_owner | regulatory_reporting |
| table | reg_2052a.i_a_assets |  | fr2052a_classification | confidential_supervisory |
| table | reg_2052a.i_a_assets |  | fr2052a_regulation | FR_2052a_6G |
| table | reg_2052a.i_a_assets |  | fr2052a_table | I.A |
| table | reg_2052a.i_o_other |  | fr2052a_classification | confidential_supervisory |
| table | reg_2052a.i_o_other |  | fr2052a_regulation | FR_2052a_6G |
| table | reg_2052a.i_o_other |  | fr2052a_table | I.O |
| table | reg_2052a.i_s_secured |  | fr2052a_classification | confidential_supervisory |
| table | reg_2052a.i_s_secured |  | fr2052a_regulation | FR_2052a_6G |
| table | reg_2052a.i_s_secured |  | fr2052a_table | I.S |
| table | reg_2052a.i_u_unsecured |  | fr2052a_classification | confidential_supervisory |
| table | reg_2052a.i_u_unsecured |  | fr2052a_regulation | FR_2052a_6G |
| table | reg_2052a.i_u_unsecured |  | fr2052a_table | I.U |
| table | reg_2052a.o_d_deposits |  | fr2052a_classification | confidential_supervisory |
| table | reg_2052a.o_d_deposits |  | fr2052a_regulation | FR_2052a_6G |
| table | reg_2052a.o_d_deposits |  | fr2052a_table | O.D |
| table | reg_2052a.o_o_other |  | fr2052a_classification | confidential_supervisory |
| table | reg_2052a.o_o_other |  | fr2052a_regulation | FR_2052a_6G |
| table | reg_2052a.o_o_other |  | fr2052a_table | O.O |
| table | reg_2052a.o_s_secured |  | fr2052a_classification | confidential_supervisory |
| table | reg_2052a.o_s_secured |  | fr2052a_regulation | FR_2052a_6G |
| table | reg_2052a.o_s_secured |  | fr2052a_table | O.S |
| table | reg_2052a.o_w_wholesale |  | fr2052a_classification | confidential_supervisory |
| table | reg_2052a.o_w_wholesale |  | fr2052a_regulation | FR_2052a_6G |
| table | reg_2052a.o_w_wholesale |  | fr2052a_table | O.W |
| table | reg_2052a.s_b_balance_sheet |  | fr2052a_classification | confidential_supervisory |
| table | reg_2052a.s_b_balance_sheet |  | fr2052a_regulation | FR_2052a_6G |
| table | reg_2052a.s_b_balance_sheet |  | fr2052a_table | S.B |
| table | reg_2052a.s_c_comments |  | fr2052a_classification | confidential_supervisory |
| table | reg_2052a.s_c_comments |  | fr2052a_regulation | FR_2052a_6G |
| table | reg_2052a.s_c_comments |  | fr2052a_table | S.C |
| table | reg_2052a.s_dc_derivatives_collateral |  | fr2052a_classification | confidential_supervisory |
| table | reg_2052a.s_dc_derivatives_collateral |  | fr2052a_regulation | FR_2052a_6G |
| table | reg_2052a.s_dc_derivatives_collateral |  | fr2052a_table | S.DC |
| table | reg_2052a.s_fx_foreign_exchange |  | fr2052a_classification | confidential_supervisory |
| table | reg_2052a.s_fx_foreign_exchange |  | fr2052a_regulation | FR_2052a_6G |
| table | reg_2052a.s_fx_foreign_exchange |  | fr2052a_table | S.FX |
| table | reg_2052a.s_i_informational |  | fr2052a_classification | confidential_supervisory |
| table | reg_2052a.s_i_informational |  | fr2052a_regulation | FR_2052a_6G |
| table | reg_2052a.s_i_informational |  | fr2052a_table | S.I |
| table | reg_2052a.s_l_liquidity_risk_measurement |  | fr2052a_classification | confidential_supervisory |

## Column mask in effect (the reader is not in fr2052a_risk_officers)

```sql
SELECT current_user() AS reader, internal_rating, COUNT(*) AS positions FROM <catalog>.conformed.fact_liquidity_position GROUP BY ALL
```

| reader | internal_rating | positions |
|---|---|---|
| user1@example.com | RESTRICTED | 1963 |

## Mask definition (information_schema.column_masks)

```sql
SELECT table_schema, table_name, column_name, mask_name FROM <catalog>.information_schema.column_masks
```

| table_schema | table_name | column_name | mask_name |
|---|---|---|---|
| conformed | fact_liquidity_position | internal_rating | <catalog>.reference.mask_internal_rating |

## Grants to the app and the agents' service principals

```sql
SELECT grantee, schema_name AS object, privilege_type FROM <catalog>.information_schema.schema_privileges WHERE grantee IN ('<app-service-principal>', '<agents-service-principal>') ORDER BY 1, 2, 3
```

| grantee | object | privilege_type |
|---|---|---|
| <agents-service-principal> | ai_assist | EXECUTE |
| <agents-service-principal> | ai_assist | SELECT |
| <agents-service-principal> | ai_assist | USE_SCHEMA |
| <agents-service-principal> | audit | SELECT |
| <agents-service-principal> | audit | USE_SCHEMA |
| <agents-service-principal> | conformed | SELECT |
| <agents-service-principal> | conformed | USE_SCHEMA |
| <agents-service-principal> | dq | SELECT |
| <agents-service-principal> | dq | USE_SCHEMA |
| <agents-service-principal> | lakebase_src | SELECT |
| <agents-service-principal> | lakebase_src | USE_SCHEMA |
| <agents-service-principal> | reference | SELECT |
| <agents-service-principal> | reference | USE_SCHEMA |
| <agents-service-principal> | reg_2052a | SELECT |
| <agents-service-principal> | reg_2052a | USE_SCHEMA |
| <agents-service-principal> | reg_lcr | SELECT |
| <agents-service-principal> | reg_lcr | USE_SCHEMA |
| <app-service-principal> | ai_assist | EXECUTE |
| <app-service-principal> | ai_assist | SELECT |
| <app-service-principal> | ai_assist | USE_SCHEMA |
| <app-service-principal> | audit | SELECT |
| <app-service-principal> | audit | USE_SCHEMA |
| <app-service-principal> | conformed | SELECT |
| <app-service-principal> | conformed | USE_SCHEMA |
| <app-service-principal> | dq | SELECT |
| <app-service-principal> | dq | USE_SCHEMA |
| <app-service-principal> | reference | SELECT |
| <app-service-principal> | reference | USE_SCHEMA |
| <app-service-principal> | reg_2052a | SELECT |
| <app-service-principal> | reg_2052a | USE_SCHEMA |
| <app-service-principal> | reg_lcr | SELECT |
| <app-service-principal> | reg_lcr | USE_SCHEMA |

## Registered model, functions, metric views, volumes

```sql
SELECT 'function' AS kind, routine_schema || '.' || routine_name AS name FROM <catalog>.information_schema.routines WHERE routine_schema IN ('ai_assist', 'reference') UNION ALL SELECT 'metric view', table_schema || '.' || table_name FROM <catalog>.information_schema.tables WHERE table_type = 'METRIC_VIEW' UNION ALL SELECT 'volume', volume_schema || '.' || volume_name FROM <catalog>.information_schema.volumes WHERE volume_schema IN ('reference', 'raw', 'dq', 'conformed', 'reg_2052a', 'reg_lcr', 'audit', 'ai_assist', 'lakebase_src', 'app_serving') ORDER BY 1, 2
```

| kind | name |
|---|---|
| function | ai_assist.filing_status |
| function | ai_assist.lcr_summary |
| function | ai_assist.open_suggestions |
| function | ai_assist.pid_rule_lookup |
| function | ai_assist.record_drilldown |
| function | ai_assist.validation_issues |
| function | ai_assist.variance_anomalies |
| function | reference.mask_internal_rating |
| metric view | controllership.unified_fr_y9c_controllership_metrics |
| metric view | fpa.unified_fr_y9c_fpa_metrics |
| metric view | reg_2052a.fr2052a_check_metrics |
| metric view | reg_2052a.fr2052a_metrics |
| metric view | reg_lcr.fr2052a_lcr_metrics |
| volume | raw.landing |
| volume | reference.docs |
| volume | reference.spec_files |
| volume | reg_2052a.xml_filings |

## Table lineage captured by UC (system.access.table_lineage, last 3 days)

```sql
SELECT DISTINCT source_table_full_name, target_table_full_name, entity_type FROM system.access.table_lineage WHERE (target_table_catalog = '<catalog>' OR source_table_catalog = '<catalog>') AND event_date >= current_date() - 3 AND source_table_full_name IS NOT NULL AND target_table_full_name IS NOT NULL AND coalesce(target_table_schema, source_table_schema) IN ('raw', 'dq', 'conformed', 'reg_2052a', 'reg_lcr', 'audit', 'lakebase_src') ORDER BY 1, 2
```

| source_table_full_name | target_table_full_name | entity_type |
|---|---|---|
| <catalog>.ai_assist.evaluation | <catalog>.lakebase_src.ai_evaluation | PIPELINE |
| <catalog>.ai_assist.evaluation | <catalog>.lakebase_src.ai_evaluation |  |
| <catalog>.ai_assist.forecast_output | <catalog>.reg_2052a.variance | JOB |
| <catalog>.ai_assist.suggestions | <catalog>.lakebase_src.ai_suggestions | PIPELINE |
| <catalog>.ai_assist.suggestions | <catalog>.lakebase_src.ai_suggestions |  |
| <catalog>.ai_assist.suggestions | <catalog>.reg_2052a.s_c_comments | JOB |
| <catalog>.audit.cross_metric_recon | <catalog>.lakebase_src.cross_metric_recon | PIPELINE |
| <catalog>.audit.cross_metric_recon | <catalog>.lakebase_src.cross_metric_recon |  |
| <catalog>.audit.data_lineage | <catalog>.lakebase_src.data_lineage | PIPELINE |
| <catalog>.audit.gl_reconciliation | <catalog>.lakebase_src.gl_reconciliation | PIPELINE |
| <catalog>.audit.gl_reconciliation | <catalog>.lakebase_src.gl_reconciliation |  |
| <catalog>.audit.intercompany_elimination | <catalog>.lakebase_src.intercompany_elimination | PIPELINE |
| <catalog>.audit.intercompany_elimination | <catalog>.lakebase_src.intercompany_elimination |  |
| <catalog>.audit.pid_derivation_summary | <catalog>.lakebase_src.pid_derivation_summary | PIPELINE |
| <catalog>.audit.pid_derivation_summary | <catalog>.lakebase_src.pid_derivation_summary |  |
| <catalog>.audit.pid_rule_usage | <catalog>.lakebase_src.pid_rule_usage | PIPELINE |
| <catalog>.conformed.entity_position | <catalog>.conformed.v_entity_position | JOB |
| <catalog>.conformed.fact_liquidity_position | <catalog>.audit.gl_reconciliation | JOB |
| <catalog>.conformed.fact_liquidity_position | <catalog>.audit.intercompany_elimination | JOB |
| <catalog>.conformed.fact_liquidity_position | <catalog>.conformed.entity_position | JOB |
| <catalog>.conformed.fact_liquidity_position | <catalog>.conformed.fact_liquidity_position | JOB |
| <catalog>.conformed.fact_liquidity_position | <catalog>.conformed.v_entity_position | JOB |
| <catalog>.conformed.fact_liquidity_position | <catalog>.lakebase_src.fact_liquidity_position | PIPELINE |
| <catalog>.conformed.fact_liquidity_position | <catalog>.lakebase_src.fact_liquidity_position |  |
| <catalog>.conformed.source_position | <catalog>.audit.pid_rule_usage | JOB |
| <catalog>.conformed.source_position | <catalog>.conformed.fact_liquidity_position | JOB |
| <catalog>.conformed.source_position | <catalog>.dq.pid_exceptions | JOB |
| <catalog>.conformed.v_entity_position | <catalog>.reg_2052a.i_a_assets | JOB |
| <catalog>.conformed.v_entity_position | <catalog>.reg_2052a.i_o_other | JOB |
| <catalog>.conformed.v_entity_position | <catalog>.reg_2052a.i_s_secured | JOB |
| <catalog>.conformed.v_entity_position | <catalog>.reg_2052a.i_u_unsecured | JOB |
| <catalog>.conformed.v_entity_position | <catalog>.reg_2052a.o_d_deposits | JOB |
| <catalog>.conformed.v_entity_position | <catalog>.reg_2052a.o_o_other | JOB |
| <catalog>.conformed.v_entity_position | <catalog>.reg_2052a.o_s_secured | JOB |
| <catalog>.conformed.v_entity_position | <catalog>.reg_2052a.o_w_wholesale | JOB |
| <catalog>.conformed.v_entity_position | <catalog>.reg_2052a.record_lineage | JOB |
| <catalog>.conformed.v_entity_position | <catalog>.reg_2052a.s_b_balance_sheet | JOB |
| <catalog>.conformed.v_entity_position | <catalog>.reg_2052a.s_dc_derivatives_collateral | JOB |
| <catalog>.conformed.v_entity_position | <catalog>.reg_2052a.s_fx_foreign_exchange | JOB |
| <catalog>.conformed.v_entity_position | <catalog>.reg_2052a.s_i_informational | JOB |
| <catalog>.conformed.v_entity_position | <catalog>.reg_2052a.s_l_liquidity_risk_measurement | JOB |
| <catalog>.conformed.v_entity_position | <catalog>.reg_2052a.stwf_schedule_g | JOB |
| <catalog>.conformed.v_entity_position | <catalog>.reg_lcr.calculation_detail | JOB |
| <catalog>.conformed.v_source_files | <catalog>.lakebase_src.v_source_files | PIPELINE |
| <catalog>.conformed.v_source_files | <catalog>.lakebase_src.v_source_files |  |
| <catalog>.dq.assessment_results | <catalog>.lakebase_src.assessment_results | PIPELINE |
| <catalog>.dq.assessment_results | <catalog>.lakebase_src.assessment_results |  |
| <catalog>.dq.feed_monitor | <catalog>.lakebase_src.feed_monitor |  |
| <catalog>.dq.feed_monitor | <catalog>.lakebase_src.feed_monitor | PIPELINE |
| <catalog>.dq.pid_exceptions | <catalog>.audit.gl_reconciliation | JOB |
| <catalog>.dq.pid_exceptions | <catalog>.lakebase_src.pid_exceptions | PIPELINE |
| <catalog>.dq.pid_exceptions | <catalog>.lakebase_src.pid_exceptions |  |
| <catalog>.dq.quarantine | <catalog>.lakebase_src.quarantine | PIPELINE |
| <catalog>.dq.quarantine | <catalog>.lakebase_src.quarantine |  |
| <catalog>.dq.rule_failures | <catalog>.lakebase_src.rule_failures | PIPELINE |
| <catalog>.dq.rule_failures | <catalog>.lakebase_src.rule_failures |  |
| <catalog>.raw.collateral_links | <catalog>.audit.pid_rule_usage | JOB |
| <catalog>.raw.collateral_links | <catalog>.conformed.fact_liquidity_position | JOB |
| <catalog>.raw.collateral_links | <catalog>.dq.pid_exceptions | JOB |
| <catalog>.raw.comments | <catalog>.reg_2052a.s_c_comments | JOB |
| <catalog>.raw.deposits | <catalog>.conformed.source_position | JOB |
| <catalog>.raw.deposits | <catalog>.conformed.v_source_files | PIPELINE |
| <catalog>.raw.deposits | <catalog>.conformed.v_source_files |  |
| <catalog>.raw.deposits | <catalog>.conformed.v_source_files | DASHBOARD_V3 |
| <catalog>.raw.deposits | <catalog>.conformed.v_source_files | JOB |
| <catalog>.raw.deposits | <catalog>.dq.quarantine | JOB |
| <catalog>.raw.derivatives | <catalog>.conformed.source_position | JOB |
| <catalog>.raw.derivatives | <catalog>.conformed.v_source_files |  |
| <catalog>.raw.derivatives | <catalog>.conformed.v_source_files | PIPELINE |
| <catalog>.raw.derivatives | <catalog>.conformed.v_source_files | DASHBOARD_V3 |
| <catalog>.raw.derivatives | <catalog>.conformed.v_source_files | JOB |
| <catalog>.raw.derivatives | <catalog>.dq.quarantine | JOB |
| <catalog>.raw.finance | <catalog>.conformed.source_position | JOB |
| <catalog>.raw.finance | <catalog>.conformed.v_source_files | PIPELINE |
| <catalog>.raw.finance | <catalog>.conformed.v_source_files |  |
| <catalog>.raw.finance | <catalog>.conformed.v_source_files | DASHBOARD_V3 |
| <catalog>.raw.finance | <catalog>.conformed.v_source_files | JOB |
| <catalog>.raw.finance | <catalog>.dq.quarantine | JOB |
| <catalog>.raw.funding | <catalog>.conformed.source_position | JOB |
| <catalog>.raw.funding | <catalog>.conformed.v_source_files | PIPELINE |
| <catalog>.raw.funding | <catalog>.conformed.v_source_files |  |
| <catalog>.raw.funding | <catalog>.conformed.v_source_files | DASHBOARD_V3 |
| <catalog>.raw.funding | <catalog>.conformed.v_source_files | JOB |
| <catalog>.raw.funding | <catalog>.dq.quarantine | JOB |
| <catalog>.raw.gl_balances | <catalog>.audit.gl_reconciliation | JOB |
| <catalog>.raw.loans | <catalog>.conformed.source_position | JOB |
| <catalog>.raw.loans | <catalog>.conformed.v_source_files |  |
| <catalog>.raw.loans | <catalog>.conformed.v_source_files | PIPELINE |
| <catalog>.raw.loans | <catalog>.conformed.v_source_files | DASHBOARD_V3 |
| <catalog>.raw.loans | <catalog>.conformed.v_source_files | JOB |
| <catalog>.raw.loans | <catalog>.dq.quarantine | JOB |
| <catalog>.raw.securities | <catalog>.conformed.source_position | JOB |
| <catalog>.raw.securities | <catalog>.conformed.v_source_files | PIPELINE |
| <catalog>.raw.securities | <catalog>.conformed.v_source_files |  |
| <catalog>.raw.securities | <catalog>.conformed.v_source_files | DASHBOARD_V3 |
| <catalog>.raw.securities | <catalog>.conformed.v_source_files | JOB |
| <catalog>.raw.securities | <catalog>.dq.quarantine | JOB |
| <catalog>.reference.ref_bank_holidays | <catalog>.conformed.fact_liquidity_position | JOB |
| <catalog>.reference.ref_bank_holidays | <catalog>.lakebase_src.ref_bank_holidays | PIPELINE |
| <catalog>.reference.ref_bank_holidays | <catalog>.lakebase_src.ref_bank_holidays |  |
| <catalog>.reference.ref_collateral | <catalog>.audit.cross_metric_recon | JOB |
| <catalog>.reference.ref_collateral | <catalog>.audit.pid_rule_usage | JOB |
| <catalog>.reference.ref_collateral | <catalog>.conformed.fact_liquidity_position | JOB |
| <catalog>.reference.ref_collateral | <catalog>.dq.pid_exceptions | JOB |
| <catalog>.reference.ref_collateral | <catalog>.lakebase_src.ref_collateral | PIPELINE |
| <catalog>.reference.ref_collateral | <catalog>.lakebase_src.ref_collateral |  |
| <catalog>.reference.ref_collateral | <catalog>.reg_lcr.calculation_detail | JOB |
| <catalog>.reference.ref_counterparty | <catalog>.audit.pid_rule_usage | JOB |
| <catalog>.reference.ref_counterparty | <catalog>.conformed.fact_liquidity_position | JOB |
| <catalog>.reference.ref_counterparty | <catalog>.dq.pid_exceptions | JOB |
| <catalog>.reference.ref_counterparty | <catalog>.lakebase_src.ref_counterparty | PIPELINE |
| <catalog>.reference.ref_counterparty | <catalog>.lakebase_src.ref_counterparty |  |
| <catalog>.reference.ref_firm_schema_values | <catalog>.lakebase_src.ref_firm_schema_values | PIPELINE |
| <catalog>.reference.ref_firm_schema_values | <catalog>.lakebase_src.ref_firm_schema_values |  |
| <catalog>.reference.ref_fx_rates | <catalog>.audit.cross_metric_recon | JOB |
| <catalog>.reference.ref_fx_rates | <catalog>.audit.gl_reconciliation | JOB |
| <catalog>.reference.ref_fx_rates | <catalog>.audit.intercompany_elimination | JOB |
| <catalog>.reference.ref_fx_rates | <catalog>.dq.pid_exceptions | JOB |
| <catalog>.reference.ref_fx_rates | <catalog>.lakebase_src.ref_fx_rates | PIPELINE |
| <catalog>.reference.ref_fx_rates | <catalog>.lakebase_src.ref_fx_rates |  |

