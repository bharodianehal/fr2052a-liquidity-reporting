# Databricks notebook source
# MAGIC %md
# MAGIC # Unity Catalog Governance - FR 2052a / LCR
# MAGIC ## Owned by: Data Governance
# MAGIC
# MAGIC Applies the governance layer on top of the medallion tables. It runs as the last step of
# MAGIC `fr2052a-pipeline` because notebook 01 recreates the tables on a full rebuild.
# MAGIC
# MAGIC | Control | What |
# MAGIC |---------|------|
# MAGIC | Tags | Schema / table / column tags: regulation, medallion layer, owner team, sensitivity, units |
# MAGIC | Documentation | Column comments on the Gold FR 2052a and LCR tables (also used by Genie) |
# MAGIC | Column mask | `conformed.fact_liquidity_position.internal_rating` is visible only to `fr2052a_risk_officers` |
# MAGIC | Access | Least-privilege grants: the app service principal reads Silver/Gold, not Bronze |

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("app_sp_client_id", "")
dbutils.widgets.text("agents_sp_client_id", "")
dbutils.widgets.text("reader_group", "fr2052a_risk_officers")

CATALOG = dbutils.widgets.get("catalog")
APP_SP = dbutils.widgets.get("app_sp_client_id").strip()
AGENTS_SP = dbutils.widgets.get("agents_sp_client_id").strip()
READER_GROUP = dbutils.widgets.get("reader_group").strip()

def run(sql):
    spark.sql(sql)

def tag_sql(tags: dict) -> str:
    return ", ".join(f"'{k}' = '{v}'" for k, v in tags.items())

print(f"Governing catalog {CATALOG}; app SP = {APP_SP or '(none)'}; agents SP = {AGENTS_SP or '(none)'}; reader group = {READER_GROUP}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Schema and table tags

# COMMAND ----------

SCHEMA_TAGS = {
    "reference": {"fr2052a_layer": "reference", "fr2052a_owner": "regulatory_reporting"},
    "raw":       {"fr2052a_layer": "bronze", "fr2052a_owner": "platform_engineering"},
    "dq":        {"fr2052a_layer": "dq_gate", "fr2052a_owner": "data_governance"},
    "conformed": {"fr2052a_layer": "silver", "fr2052a_owner": "data_governance"},
    "reg_2052a": {"fr2052a_layer": "gold", "fr2052a_owner": "regulatory_reporting", "fr2052a_regulation": "FR_2052a_6G"},
    "reg_lcr":   {"fr2052a_layer": "gold", "fr2052a_owner": "treasury_alm", "fr2052a_regulation": "12_CFR_249"},
    "audit":     {"fr2052a_layer": "control", "fr2052a_owner": "risk_control"},
}
for schema, tags in SCHEMA_TAGS.items():
    run(f"ALTER SCHEMA {CATALOG}.{schema} SET TAGS ({tag_sql({'fr2052a_domain': 'liquidity_risk', **tags})})")

SUPERVISORY = {"fr2052a_regulation": "FR_2052a_6G", "fr2052a_classification": "confidential_supervisory"}
spec_tables = spark.table(f"{CATALOG}.reference.spec_tables").collect()
TABLE_TAGS = {f"reg_2052a.{t.gold_table}": {**SUPERVISORY, "fr2052a_table": t.table_code} for t in spec_tables}
TABLE_TAGS.update({
    "reg_2052a.submission_files": SUPERVISORY,
    "reg_2052a.submission_review": {**SUPERVISORY, "fr2052a_contains": "sign_off_log"},
    "reg_lcr.calculation_results":  {"fr2052a_regulation": "12_CFR_249", "fr2052a_classification": "confidential_supervisory"},
    "conformed.fact_liquidity_position": {"fr2052a_classification": "confidential", "fr2052a_contains": "counterparty_ratings"},
    "reference.ref_customer_master": {"fr2052a_classification": "confidential", "fr2052a_owner": "data_governance"},
    "reference.rules_pid_derivation": {"fr2052a_owner": "regulatory_reporting", "fr2052a_change_control": "required"},
})
for table, tags in TABLE_TAGS.items():
    run(f"ALTER TABLE {CATALOG}.{table} SET TAGS ({tag_sql(tags)})")
print(f"Tagged {len(SCHEMA_TAGS)} schemas and {len(TABLE_TAGS)} tables")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Column tags and comments

# COMMAND ----------

fields = spark.table(f"{CATALOG}.reference.spec_table_fields").where("data_type = 'numeric'").collect()
gold_of = {t.table_code: t.gold_table for t in spec_tables}
AMOUNT_COLS = {}
for f in fields:   # FR 2052a values are reported in millions of the reported currency
    AMOUNT_COLS.setdefault(f"reg_2052a.{gold_of[f.table_code]}", []).append(f.column_name)
AMOUNT_COLS.update({
    "reg_lcr.calculation_results": ["level1_hqla", "level2a_hqla_adjusted", "level2b_hqla_adjusted", "total_hqla",
                                    "total_outflows", "total_inflows", "capped_inflows", "total_net_cash_outflows"],
    "conformed.fact_liquidity_position": ["principal_amount", "market_value", "forward_start_amount"],
})
for table, cols in AMOUNT_COLS.items():
    for c in cols:
        run(f"ALTER TABLE {CATALOG}.{table} ALTER COLUMN {c} SET TAGS ('fr2052a_unit' = 'millions_of_reported_currency')")

SENSITIVE_COLS = {
    "conformed.fact_liquidity_position": {"internal_rating": "restricted", "customer_id": "confidential", "counterparty": "confidential"},
    "raw.deposits": {"internal_rating": "restricted"},
    "raw.loans": {"internal_rating": "restricted"},
    "raw.securities": {"internal_rating": "restricted"},
    "raw.derivatives": {"internal_rating": "restricted"},
    "raw.funding": {"internal_rating": "restricted"},
}
for table, cols in SENSITIVE_COLS.items():
    for c, level in cols.items():
        tags = f"ALTER COLUMN {c} SET TAGS ('fr2052a_sensitivity' = '{level}')"
        try:
            run(f"ALTER TABLE {CATALOG}.{table} {tags}")
        except Exception:  # raw.* are Lakeflow streaming tables
            run(f"ALTER STREAMING TABLE {CATALOG}.{table} {tags}")

COLUMN_COMMENTS = {
    # the FR 2052a tables get their column comments from reference.spec_table_fields at creation (notebook 01)
    "conformed.fact_liquidity_position": {
        "product_id": "FR 2052a PID derived by notebook 03 from reference.rules_pid_derivation (see pid_rule_id)",
        "pid_rule_id": "The PID derivation rule that classified this position (reference.rules_pid_derivation.rule_id)",
    },
    "reg_lcr.calculation_results": {
        "total_hqla": "High-quality liquid assets after haircuts and Level 2 caps, USD millions",
        "total_net_cash_outflows": "Total stressed outflows minus capped inflows (cap = 75% of outflows), plus maturity mismatch add-on, USD millions",
        "lcr_ratio": "Liquidity Coverage Ratio = total_hqla / total_net_cash_outflows (1.171 = 117.1%); minimum 1.00",
        "lcr_compliant": "TRUE when lcr_ratio >= 1.00 (12 CFR 249.10)",
    },
    "conformed.fact_liquidity_position": {
        "internal_rating": "Internal counterparty credit rating. MASKED unless the reader is in fr2052a_risk_officers",
    },
}
n = 0
for table, cols in COLUMN_COMMENTS.items():
    for c, text in cols.items():
        run(f"ALTER TABLE {CATALOG}.{table} ALTER COLUMN {c} COMMENT '{text}'")
        n += 1
print(f"Applied column tags and {n} column comments")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Column mask on internal ratings

# COMMAND ----------

run(f"""CREATE OR REPLACE FUNCTION {CATALOG}.reference.mask_internal_rating(rating STRING)
RETURNS STRING
COMMENT 'Column mask: internal counterparty ratings are visible only to {READER_GROUP}'
RETURN CASE WHEN is_account_group_member('{READER_GROUP}') OR is_member('{READER_GROUP}') THEN rating ELSE 'RESTRICTED' END""")
run(f"ALTER TABLE {CATALOG}.conformed.fact_liquidity_position ALTER COLUMN internal_rating SET MASK {CATALOG}.reference.mask_internal_rating")
print("Column mask applied to conformed.fact_liquidity_position.internal_rating")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Least-privilege grants

# COMMAND ----------

READ_SCHEMAS = ["reference", "dq", "conformed", "reg_2052a", "reg_lcr", "audit", "ai_assist"]  # not raw (Bronze)
def grant_read(p):
    run(f"GRANT USE CATALOG ON CATALOG {CATALOG} TO `{p}`")
    for schema in READ_SCHEMAS:
        run(f"GRANT USE SCHEMA, SELECT ON SCHEMA {CATALOG}.{schema} TO `{p}`")
    run(f"GRANT EXECUTE ON FUNCTION {CATALOG}.reference.mask_internal_rating TO `{p}`")
    run(f"GRANT EXECUTE ON SCHEMA {CATALOG}.ai_assist TO `{p}`")   # the agent tools (UC functions MCP)
    run(f"GRANT READ VOLUME ON VOLUME {CATALOG}.reference.docs TO `{p}`")   # the regulatory text the agents cite
    run(f"REVOKE ALL PRIVILEGES ON SCHEMA {CATALOG}.raw FROM `{p}`")

if APP_SP:
    grant_read(APP_SP)
    print(f"Granted read on {READ_SCHEMAS} to app SP {APP_SP}; Bronze (raw) is not readable by it")

# The agents' service principal fr2052a-agents (the serving endpoint runs as it): the same read, plus the Lakebase source
# views and write on the MLflow trace tables in ai_assist (the endpoint logs a trace per proposal)
if AGENTS_SP:
    grant_read(AGENTS_SP)
    run(f"GRANT USE SCHEMA, SELECT ON SCHEMA {CATALOG}.lakebase_src TO `{AGENTS_SP}`")
    for t in spark.sql(f"SHOW TABLES IN {CATALOG}.ai_assist LIKE '*_otel_*'").collect():
        run(f"GRANT SELECT, MODIFY ON TABLE {CATALOG}.ai_assist.`{t.tableName}` TO `{AGENTS_SP}`")
    print(f"Granted read and trace write to agents SP {AGENTS_SP}")

# UC grants need an account-level group. A workspace-local group still drives the mask (is_member),
# so report instead of failing when the group is not an account principal.
try:
    grant_read(READER_GROUP)
    print(f"Granted read on {READ_SCHEMAS} to {READER_GROUP}")
except Exception as e:
    print(f"Skipped UC grants to {READER_GROUP}: not an account-level principal ({type(e).__name__}). "
          "The column mask still uses workspace group membership.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Verify

# COMMAND ----------

display(spark.sql(f"""
SELECT 'schema' AS level, schema_name AS object, NULL AS column_name, tag_name, tag_value
FROM {CATALOG}.information_schema.schema_tags WHERE tag_name LIKE 'fr2052a_%'
UNION ALL
SELECT 'table', concat(schema_name, '.', table_name), NULL, tag_name, tag_value
FROM {CATALOG}.information_schema.table_tags WHERE tag_name LIKE 'fr2052a_%'
UNION ALL
SELECT 'column', concat(schema_name, '.', table_name), column_name, tag_name, tag_value
FROM {CATALOG}.information_schema.column_tags WHERE tag_name LIKE 'fr2052a_%'
ORDER BY level, object, column_name, tag_name"""))

# COMMAND ----------

# The run identity is not in the reader group, so the mask returns RESTRICTED here
display(spark.sql(f"""
SELECT current_user() AS reader,
       is_account_group_member('{READER_GROUP}') OR is_member('{READER_GROUP}') AS in_reader_group,
       internal_rating, COUNT(*) AS positions
FROM {CATALOG}.conformed.fact_liquidity_position
GROUP BY ALL ORDER BY internal_rating"""))

# COMMAND ----------

display(spark.sql(f"SHOW GRANTS ON SCHEMA {CATALOG}.reg_lcr"))
