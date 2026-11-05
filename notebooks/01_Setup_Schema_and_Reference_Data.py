# Databricks notebook source
# MAGIC %md
# MAGIC # FR 2052a Liquidity Risk Platform - Setup, Spec Reference Data & Source Extracts
# MAGIC ## Version 8 - FR 2052a Instructions + Fed 6G schema package as the source of truth
# MAGIC
# MAGIC **One-time setup.** Loads the FR 2052a specification and the firm's reference data from CSV, builds the 13 data
# MAGIC tables + Comments as laid out on the *Data Tables* pages, and lands 10 business days of synthetic source extracts.
# MAGIC
# MAGIC | Step | What | Source |
# MAGIC |------|------|--------|
# MAGIC | 1 | 8 schemas | |
# MAGIC | 2 | Spec + firm reference CSVs uploaded to the Volume `reference.spec_files`, loaded as `reference.*` | `reference_data/*.csv`: spec from the Instructions PDF and the 6G XSD / Business Requirements (`scripts/spec/build_reference_data.py`); firm product catalogue, PID derivation rules, customer and security masters (`scripts/firm/build_firm_reference.py`) |
# MAGIC | 3 | `reference.rules_spec` - executable appendix rules generated from the spec tables | Appendices II-a, II-b, II-c, II-d, IV-a, IV-b, V + Field Definitions |
# MAGIC | 4 | Source-system CSV extracts in the Volume `raw.landing` (Lakeflow ingests them). Extracts carry the bank's source product codes, customer and security ids - **not** PIDs; notebook 03 derives the PIDs | synthetic |
# MAGIC | 5 | DQ, Silver, the 14 FR 2052a tables (DDL generated from `reference.spec_table_fields`), submission, LCR and audit tables | |

# COMMAND ----------

dbutils.widgets.text("catalog", "", "Catalog Name")
dbutils.widgets.text("reference_dir", "", "Reference CSV folder (default: <repo>/reference_data)")
CATALOG = dbutils.widgets.get("catalog")
REG_VERSION = "6G"

import os
REF_DIR = dbutils.widgets.get("reference_dir").strip()
if not REF_DIR:
    nb_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
    REF_DIR = "/Workspace" + os.path.dirname(os.path.dirname(nb_path)) + "/reference_data"

spark.sql(f"USE CATALOG {CATALOG}")
print(f"Catalog: {CATALOG} | reference CSVs: {REF_DIR}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Schemas

# COMMAND ----------

for schema, comment in [
    ("reference", "Reference data - FR 2052a specification tables and firm configuration, versioned by reg_version"),
    ("raw", "Bronze - source system extracts ingested by Lakeflow"),
    ("dq", "Data Quality Gate - DQ assessment results and quarantine between Bronze and Silver"),
    ("conformed", "Silver - harmonized golden source, only DQ-passed records"),
    ("reg_2052a", "Gold - FR 2052a filing: the 13 data tables + Comments, validation and XML"),
    ("reg_lcr", "Gold - LCR calculation mart (owned by Treasury/ALM)"),
    ("audit", "Control - GL reconciliation, cross-metric consistency, eliminations, PID derivation accuracy, data lineage"),
    ("ai_assist", "Databricks-native AI suggestions and their human decisions"),
]:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {schema} COMMENT '{comment}'")
print("8 schemas ready")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Upload the reference CSVs to `reference.spec_files` and load `reference.*`
# MAGIC
# MAGIC The CSVs in `reference_data/` are the single source of the specification: products, table layouts, appendix
# MAGIC requirements, asset categories, maturity buckets, field values and the Fed 6G validation rules. They are copied to a
# MAGIC governed Volume and every reference table is (re)loaded from that Volume.

# COMMAND ----------

import shutil
from pyspark.sql import functions as F

spark.sql(f"""CREATE VOLUME IF NOT EXISTS {CATALOG}.reference.spec_files
COMMENT 'FR 2052a specification and firm reference data (CSV). Source: reference_data/ in the fr2052a repo'""")
SPEC_VOL = f"/Volumes/{CATALOG}/reference/spec_files/{REG_VERSION}"
os.makedirs(SPEC_VOL, exist_ok=True)
for name in sorted(os.listdir(REF_DIR)):
    if name.endswith(".csv"):
        shutil.copyfile(f"{REF_DIR}/{name}", f"{SPEC_VOL}/{name}")
for name in os.listdir(SPEC_VOL):   # the volume mirrors reference_data/: remove CSVs no longer in the repo
    if name.endswith(".csv") and not os.path.exists(f"{REF_DIR}/{name}"):
        os.remove(f"{SPEC_VOL}/{name}")
print(f"Uploaded {len([n for n in os.listdir(SPEC_VOL) if n.endswith('.csv')])} CSVs to {SPEC_VOL}")

# table: (csv file, column casts, comment)
REFERENCE_TABLES = {
    "spec_tables": ("spec_tables.csv", {}, "FR 2052a Appendix I - the 13 data tables + Comments and their gold table / 6G XML names"),
    "spec_table_fields": ("spec_table_fields.csv", {"seq": "int", "xsd_required": "boolean"},
                          "Data Tables p.84-85 - fields per table, Mandatory (red) / Dependent (blue), plus Currency/Converted (footnote 16), with the 6G XML element"),
    "spec_xsd_layout": ("spec_xsd_layout.csv", {"seq": "int", "xsd_required": "boolean"},
                        "6GSchema.xsd - ordered elements and attributes per report type (drives the XML generator)"),
    "ref_product": ("spec_products.csv", {"product_number": "int", "definition_page": "int"},
                    "The 147 FR 2052a products (PIDs); product_name is the 6G XSD value sent in the XML"),
    "spec_subproducts": ("spec_subproducts.csv", {"required_by_instructions": "boolean"},
                         "Appendix II-a / 6G BR Prod-SubProd-SubProd2 - allowed Sub-Product / Sub-Product 2 values per product"),
    "spec_counterparty_requirements": ("spec_counterparty_requirements.csv", {}, "Appendix II-b - products requiring a Counterparty and the applicable values"),
    "spec_collateral_class_requirements": ("spec_collateral_class_requirements.csv", {}, "Appendix II-c - Collateral Class Required / Dependent / Not Applicable per product"),
    "spec_forward_start_exclusions": ("spec_forward_start_exclusions.csv", {}, "Appendix II-d - products that must not carry Forward Start fields"),
    "ref_collateral": ("spec_asset_categories.csv", {"lcr_haircut_pct": "decimal(5,4)", "is_hqla": "boolean"}, "Appendix III - asset categories (Collateral Class) with HQLA level"),
    "ref_maturity_bucket": ("spec_maturity_buckets.csv", {"bucket_seq": "int", "day_start": "int", "day_end": "int",
                                                          "is_within_30d": "boolean", "is_standard": "boolean"},
                            "Appendix IV-a - 76 maturity buckets (+ 2 IV-b tailored aggregates)"),
    "spec_maturity_tailoring": ("spec_maturity_tailoring.csv", {}, "Appendix IV-b - allowed maturity buckets per firm profile and product scope"),
    "spec_double_counting": ("spec_double_counting.csv", {"item_no": "int"}, "Appendix V - permitted double counting and the cross-table checks"),
    "spec_field_values": ("spec_field_values.csv", {}, "Allowed field values per table - 6G XSD enumerations and the BR G-SIB list"),
    "ref_counterparty": ("spec_counterparties.csv", {"is_financial": "boolean"}, "Field Definitions p.17-21 - the 19 counterparty types (XSD spellings)"),
    "rules_validation": ("rules_validation_6g.csv", {"seq_num": "int"},
                         "Fed 6G Business Requirements - the 652 validation rules; enforced_by XSD (schema validation) or FRS (application rule)"),
    "rules_dq": ("rules_dq.csv", {}, "Bronze -> Silver data quality rules (fail_predicate is SQL over the staging view)"),
    "rules_lcr_appendix_vi": ("rules_lcr_appendix_vi.csv", {"outflow_rate": "decimal(5,4)", "inflow_rate": "decimal(5,4)", "rule_priority": "int"},
                              "LCR rates per 12 CFR 249 mapped to FR 2052a products"),
    "ref_bank_holidays": ("ref_bank_holidays.csv", {"holiday_date": "date"},
                          "Federal Reserve holiday calendar - with weekends, the days no payment settles (scripts/firm/build_bank_holidays.py)"),
    "ref_fx_rates": ("ref_fx_rates.csv", {"rate_to_usd": "decimal(12,6)", "rate_date": "date", "is_fr2052a_currency": "boolean"},
                     "FX rates to USD; is_fr2052a_currency marks the 7 currencies reported natively (p.16)"),
    "ref_reporting_entity": ("ref_reporting_entity.csv", {"is_gsib": "boolean", "wstwf_usd_bn": "decimal(12,2)", "reports_native_currency": "boolean",
                                                          "lcr_standalone": "boolean", "nsfr_standalone": "boolean", "broker_dealer_material_entity": "boolean"},
                             "Reporting entities (consolidated + material entities), scope root legal entity, entity type, Fed category, IV-b profile"),
    "ref_firm_schema_values": ("ref_firm_schema_values.csv", {},
                               "Firm include XSD values: reporter ticker, exchange, reportScope, internalCounterparty, businessLine"),
    "ref_standard_product_type": ("ref_standard_product_type.csv", {"requires_customer": "boolean", "requires_collateral": "boolean"},
                                  "Firm - standard product types (one per regulatory product family) the PID rules are written against"),
    "ref_source_product_map": ("ref_source_product_map.csv", {}, "Firm - source system product codes -> standard product type (reclassification)"),
    "rules_pid_derivation": ("rules_pid_derivation.csv", {"priority": "int"},
                             "Firm - PID derivation rules: ordered SQL conditions per standard product type (first match wins)"),
    "ref_customer_master": ("ref_customer_master.csv", {"has_relationship": "boolean", "approved_on": "date"},
                            "Firm - approved customer master: FR 2052a Counterparty, G-SIB parent, affiliate legal entity"),
    "ref_legal_entity": ("ref_legal_entity.csv", {}, "Firm - legal entities and org structure (parent)"),
    "ref_lendable_haircuts": ("ref_lendable_haircuts.csv", {"haircut": "decimal(6,4)"}, "Firm - lendable value haircut by pledge venue and asset class"),
    "ref_generic_collateral_map": ("ref_generic_collateral_map.csv", {}, "Firm - generic issuer / product of substitutable collateral -> Collateral Class"),
    "ref_expected_products": ("ref_expected_products.csv", {}, "Firm - products expected per entity type (Fed post-submission check 9)"),
    "rules_fed_psv": ("rules_fed_psv.csv", {"check_no": "int"}, "Fed FR 2052a post-submission validation checks (14)"),
    "ref_report_template": ("ref_report_template.csv", {"activated_on": "date", "retired_on": "date"}, "Report template versions and activation dates"),
    "rules_stwf_appendix_vii": ("rules_stwf_appendix_vii.csv", {"appendix_table": "int", "tier_weight": "decimal(4,2)"},
                                "Appendix VII - FR Y-15 Schedule G (STWF) items from FR 2052a data elements"),
    "ref_stwf_mdrm": ("ref_stwf_mdrm.csv", {}, "Fed MDRM codes of the FR Y-15 Schedule G items and columns"),
    "ref_mdrm_items": ("ref_mdrm_items.csv", {}, "Fed MDRM dictionary extract: the active FR Y-15 Schedule G items (FR 2052a itself is identified by PID, not MDRM)"),
    "ref_security_master": ("ref_security_master.csv", {}, "Firm - security / collateral master: Appendix III Collateral Class"),
}

for table, (csv_name, casts, comment) in REFERENCE_TABLES.items():
    df = (spark.read.option("header", True).option("escape", '"').option("multiLine", True)
          .csv(f"{SPEC_VOL}/{csv_name}"))
    for col_name, dtype in casts.items():
        df = df.withColumn(col_name, F.col(col_name).cast(dtype))
    df = df.withColumn("reg_version", F.lit(REG_VERSION))
    (df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.reference.{table}"))
    spark.sql(f"COMMENT ON TABLE {CATALOG}.reference.{table} IS '{comment.replace(chr(39), '')} (source: {csv_name})'")
    print(f"  reference.{table:36s} {df.count():5d} rows  <- {csv_name}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Executable appendix rules - `reference.rules_spec`
# MAGIC
# MAGIC Every requirement on pages 84-106 becomes one or more rows here; notebook 04 runs each `check_type` against the
# MAGIC reported data. Nothing is marked PASS without being evaluated.

# COMMAND ----------

import json

TABLE_ORDER = ["I.A", "I.U", "I.S", "I.O", "O.D", "O.W", "O.S", "O.O", "S.DC", "S.L", "S.B", "S.I", "S.FX", "S.C"]
_t = {r.table_code: r for r in spark.table(f"{CATALOG}.reference.spec_tables").collect()}
tables = {code: _t[code] for code in TABLE_ORDER}
fields = spark.table(f"{CATALOG}.reference.spec_table_fields").orderBy("table_code", "seq").collect()
fields_by_table = {}
for f in fields:
    fields_by_table.setdefault(f.table_code, []).append(f)
field_values = spark.table(f"{CATALOG}.reference.spec_field_values").collect()

rules = []
def rule(rule_id, appendix, table_code, name, check_type, severity="ERROR", **params):
    rules.append((rule_id, appendix, table_code, name, check_type, json.dumps(params), severity))

for code, t in tables.items():
    cols = {f.column_name: f for f in fields_by_table[code]}
    # Data Tables p.84-85: mandatory (red) fields
    for f in fields_by_table[code]:
        if f.field_class == "Mandatory" and f.column_name not in ("converted",):
            rule(f"SPEC-DT-{code}-{f.seq:02d}", "Data Tables p.84-85", code, f"{f.field_name} is mandatory in {t.table_name}",
                 "MANDATORY_FIELD", column=f.column_name, field=f.field_name)
    if "converted" in cols:
        rule(f"SPEC-DT-{code}-CNV", "Footnote 16 / p.17", code, "Converted is reported and is true only for USD-converted values",
             "CONVERTED_CURRENCY", currency_columns=[c for c in ("currency", "currency_1", "currency_2") if c in cols])
    # Field Definitions: enumerated values
    for fv_field in sorted({v.field_name for v in field_values}):
        scopes = {v.table_scope for v in field_values if v.field_name == fv_field}
        col = {"Currency": "currency", "G-SIB": "gsib"}.get(fv_field) or next(
            (f.column_name for f in fields_by_table[code] if f.field_name == fv_field), None)
        targets = [col] if col in cols else []
        if fv_field == "Currency" and code == "S.FX":
            targets = ["currency_1", "currency_2"]
        for scope in scopes:
            if targets and (scope == "ALL" or code in scope.split(",")):
                for tc in targets:
                    rule(f"SPEC-FD-{code}-{tc}", "Field Definitions p.16-32", code, f"{fv_field} values ({tc})",
                         "FIELD_DOMAIN", column=tc, field=fv_field, scope=scope)
    for col, ref, where, label in [("collateral_class", "ref_collateral.collateral_class", None, "Appendix III"),
                                   ("counterparty", "ref_counterparty.counterparty", None, "Field Definitions p.17-21"),
                                   ("internal_counterparty", "ref_firm_schema_values.value", "list_name = 'internalCounterparty'", "Field Definitions p.25; firm include XSD"),
                                   ("business_line", "ref_firm_schema_values.value", "list_name = 'businessLine'", "Field Definitions p.26; firm include XSD"),
                                   ("reporting_entity", "ref_reporting_entity.entity_id", None, "Field Definitions p.16")]:
        if col in cols:
            rule(f"SPEC-RF-{code}-{col}", label, code, f"{cols[col].field_name} uses a defined value", "REFERENCE_VALUE",
                 column=col, reference=ref, where=where)
    if "product_id" in cols:
        rule(f"SPEC-PR-{code}", "Product Definitions", code, f"Product belongs to {t.table_name}", "PRODUCT_IN_TABLE")
    for col in ("maturity_bucket", "forward_start_bucket", "effective_maturity_bucket"):
        if col in cols:
            rule(f"SPEC-IVa-{code}-{col}", "Appendix IV-a p.101", code, f"{cols[col].field_name} is an Appendix IV-a value",
                 "BUCKET_VALUE", column=col)
    if "maturity_bucket" in cols:
        rule(f"SPEC-IVb-{code}", "Appendix IV-b p.102", code, "Maturity buckets allowed for the firm's tailoring profile",
             "MATURITY_TAILORING", columns=[c for c in ("maturity_bucket", "forward_start_bucket") if c in cols])
    if code != "S.C":
        if "sub_product" in cols or "sub_product_2" in cols:
            rule(f"SPEC-IIa-{code}", "Appendix II-a p.86-87; 6G BR Prod-SubProd-SubProd2", code,
                 "Sub-Product / Sub-Product 2 is an allowed value for the product (FRS rejects the file otherwise)", "SUBPRODUCT",
                 has_sub="sub_product" in cols, has_sub2="sub_product_2" in cols)
            rule(f"SPEC-IIa-{code}-REQ", "Appendix II-a p.86-87", code, "Sub-Product reported where the Instructions require one",
                 "SUBPRODUCT_REQUIRED", severity="WARNING")
    if "counterparty" in cols:
        rule(f"SPEC-IIb-{code}", "Appendix II-b p.88-90", code, "Counterparty required and applicable per product", "COUNTERPARTY_REQ")
    if "collateral_class" in cols:
        rule(f"SPEC-IIc-{code}", "Appendix II-c p.91-94", code, "Collateral Class Required / Dependent / Not Applicable per product", "COLLATERAL_REQ")
    fwd_amt = [c for c in ("forward_start_amount", "forward_start_amount_currency_1", "forward_start_amount_currency_2") if c in cols]
    if fwd_amt or "forward_start_bucket" in cols:
        rule(f"SPEC-IId-{code}", "Appendix II-d p.95-97", code, "Forward Start fields not reported for excluded products", "FORWARD_START_EXCL",
             columns=fwd_amt + (["forward_start_bucket"] if "forward_start_bucket" in cols else []))
    if "forward_start_bucket" in cols and fwd_amt and code != "S.FX":
        rule(f"SPEC-FS-{code}", "Field Definitions p.24", code, "Forward Start Amount and Forward Start Bucket are reported together",
             "FORWARD_START_PAIR", amount=fwd_amt[0])
    if "forward_start_bucket" in cols and "maturity_bucket" in cols:
        rule(f"SPEC-FM-{code}", "Field Definitions p.22-23", code, "Forward Start Bucket is not later than Maturity Bucket", "FORWARD_BEFORE_MATURITY")
    if "internal" in cols:
        rule(f"SPEC-IC-{code}", "Field Definitions p.24-25", code, "Internal Counterparty reported when (and only when) Internal = Yes", "INTERNAL_COUNTERPARTY")
    if "gsib" in cols:
        rule(f"SPEC-GS-{code}", "Field Definitions p.31; 6G BR", code, "G-SIB only reported where Counterparty is populated", "GSIB_WITH_COUNTERPARTY")
    if "risk_weight" in cols:
        rule(f"SPEC-RW-{code}", "Field Definitions p.31; 6G BR", code, "Risk Weight is a decimal between 0 and 12.50", "RISK_WEIGHT_RANGE")
    if t.primary_amount_column:
        rule(f"SPEC-MA-{code}", "Field Definitions p.23-24", code, "Aggregates rounding below 0.01 are not reported", "MIN_AMOUNT",
             column=t.primary_amount_column, severity="WARNING")

rule("SPEC-DC-NE", "Field Definitions p.29", "S.DC", "Netting Eligible only for S.DC.8 - S.DC.10", "FIELD_PRODUCT_SCOPE",
     column="netting_eligible", products=["S.DC.8", "S.DC.9", "S.DC.10"])
rule("SPEC-DC-CL", "Field Definitions p.29-30", "S.DC", "Collateral Level only for S.DC.1, S.DC.2, S.DC.8 - S.DC.10", "FIELD_PRODUCT_SCOPE",
     column="collateral_level", products=["S.DC.1", "S.DC.2", "S.DC.8", "S.DC.9", "S.DC.10"])
rule("SPEC-IA-AD", "Field Definitions p.30", "I.A", "Accounting Designation other than Not Applicable only for I.A.1 / I.A.2", "FIELD_PRODUCT_SCOPE",
     column="accounting_designation", products=["I.A.1", "I.A.2"], allowed_elsewhere=["Not Applicable"])
rule("SPEC-OW-LA", "Field Definitions p.30-31", "O.W", "Loss Absorbency only for capital / TLAC debt instruments", "FIELD_PRODUCT_SCOPE",
     column="loss_absorbency", products=["O.W.11", "O.W.12", "O.W.13", "O.W.14", "O.W.15"])
rule("SPEC-DC-SV", "S.DC.18-21 p.68-70", "S.DC", "Collateral substitution products: a single USD value per reporting entity", "SINGLE_USD_VALUE",
     products=["S.DC.18", "S.DC.19", "S.DC.20"])
rule("SPEC-SL-RT", "S.L.6 / S.L.10 p.71-72", "S.L", "LCR and NSFR reported as decimals with four points of precision", "RATIO_PRECISION",
     products=["S.L.6", "S.L.10"])
rule("SPEC-SL-L6", "S.L.6 p.71", "S.L", "S.L.6 Liquidity Coverage Ratio reported (entity subject to the LCR on a standalone basis)", "PRODUCT_PRESENT",
     products=["S.L.6"], entity_flag="lcr_standalone")
rule("SPEC-SL-IN", "S.L.1-2, S.L.7-8 p.70-72; S.I.6 p.75", "S.L", "Subsidiary liquidity products carry an Internal Counterparty and Internal = No",
     "SUBSIDIARY_INTERNAL", products=["S.L.1", "S.L.2", "S.L.7", "S.L.8"])
rule("SPEC-SI-IN", "S.I.6 p.75", "S.I", "S.I.6 carries an Internal Counterparty and Internal = No", "SUBSIDIARY_INTERNAL", products=["S.I.6"])
rule("SPEC-SB-NT", "S.B.5 p.73", "S.B", "S.B.5 Counterparty Netting is negative and reported twice (asset and liability)", "SB5_NETTING")
rule("SPEC-SB-ME", "S.B general guidance p.72-73; S.L NSFR p.71", "S.B", "Month-end products reported on the last business day of the month",
     "MONTH_END_PRODUCTS", severity="WARNING", products=["S.B.1", "S.B.2", "S.B.3", "S.B.4", "S.B.6", "S.L.7", "S.L.8", "S.L.9", "S.L.10"])
rule("SPEC-SB-5D", "S.B.5 p.73", "S.B", "Category I firms report S.B.5 for each as-of date", "PRODUCT_PRESENT",
     products=["S.B.5"], entity_category="Category I")
rule("SPEC-FX-CC", "S.FX currency reporting p.76", "S.FX", "Currency 1 and Currency 2 are different currencies", "FX_CURRENCY_PAIR")
rule("SPEC-C-OTH", "Field Definitions p.21, p.29", "S.C", "Counterparty / Encumbrance Type 'Other' is described in the Comments table", "OTHER_HAS_COMMENT",
     severity="WARNING")

for r in spark.table(f"{CATALOG}.reference.spec_double_counting").orderBy("item_no").collect():
    rule(f"SPEC-V-{r.item_no:02d}", "Appendix V p.103-105", "ALL", r.description[:240], f"DOUBLE_COUNT_{r.check_type}",
         item_no=r.item_no, products_a=r.products_a.split(",") if r.products_a else [],
         products_b=r.products_b.split(",") if r.products_b else [], comparison=r.comparison)

spark.createDataFrame(rules, "rule_id STRING, appendix STRING, table_code STRING, rule_name STRING, check_type STRING, params STRING, severity STRING") \
    .withColumn("reg_version", F.lit(REG_VERSION)) \
    .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.reference.rules_spec")
spark.sql(f"COMMENT ON TABLE {CATALOG}.reference.rules_spec IS 'Executable FR 2052a appendix rules generated from the spec reference tables (notebook 01 section 3)'")
print(f"reference.rules_spec: {len(rules)} rules")
display(spark.sql(f"SELECT appendix, check_type, COUNT(*) AS rules FROM {CATALOG}.reference.rules_spec GROUP BY ALL ORDER BY 1, 2"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Source-system extracts (Bronze landing) - 39 business days, 5 legal entities
# MAGIC
# MAGIC CSV extracts land in `raw.landing/<feed>/<as_of_date>/` and are ingested by the Lakeflow pipeline
# MAGIC `fr2052a-bronze-ingest`. Position feeds: deposits, loans, securities, derivatives, funding, finance; plus comments,
# MAGIC gl_balances (GL control totals per legal entity), customers (KYC onboarding extract) and collateral_links (placed /
# MAGIC received collateral per secured transaction).
# MAGIC
# MAGIC * Each **pool** is one position split into a few source records, booked in one of the group's legal entities
# MAGIC   (`booking_entity`). Extracts carry what source systems hold - the bank's own product code, customer id, security id,
# MAGIC   embedded options, facility draw terms, reserve requirements, operational-service attributes, depositor counts -
# MAGIC   not the PID or any FR 2052a classification; notebook 03 calculates and derives those.
# MAGIC * Intercompany pairs between the bank and the broker-dealer are booked on both sides (eliminated in the consolidated
# MAGIC   report, Internal in the solo reports).
# MAGIC * `audit.pid_answer_key` keeps the PID each calculated part of each record must get (test oracle for notebook 03).
# MAGIC * Planted events: Fed post-submission check defects, a short derivatives feed, a GL break, two balance shocks,
# MAGIC   new customers onboarded during the window (two still pending approval at the end) and an unmapped product code.

# COMMAND ----------

import csv as _csv
import random
from datetime import date, datetime, timedelta

spark.sql(f"""CREATE VOLUME IF NOT EXISTS {CATALOG}.raw.landing
COMMENT 'Landing zone for FR 2052a source-system extracts (CSV), ingested by Lakeflow pipeline fr2052a-bronze-ingest'""")
LANDING = f"/Volumes/{CATALOG}/raw/landing"
POSITION_FEEDS = ["deposits", "loans", "securities", "derivatives", "funding", "finance"]
OTHER_FEEDS = ["comments", "gl_balances", "customers", "collateral_links"]

# raw.<feed> tables are owned by the Lakeflow pipeline; drop non-pipeline tables of the same name.
for t in spark.sql(f"SHOW TABLES IN {CATALOG}.raw").collect():
    if t.tableName in POSITION_FEEDS + OTHER_FEEDS:
        ttype = spark.sql(f"DESCRIBE TABLE EXTENDED {CATALOG}.raw.{t.tableName}").filter("col_name = 'Type'").collect()
        if ttype and ttype[0].data_type not in ("STREAMING_TABLE", "MATERIALIZED_VIEW"):
            spark.sql(f"DROP TABLE {CATALOG}.raw.{t.tableName}")

HOLIDAYS = {date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16)}   # New Year, MLK Day, Presidents Day
def is_business(d):
    return d.weekday() < 5 and d not in HOLIDAYS
def roll(d):
    while not is_business(d):
        d += timedelta(days=1)
    return d
DATES = [d for d in (date(2026, 1, 2) + timedelta(days=i) for i in range(57)) if is_business(d)]
MONTH_ENDS = {d for d in DATES if roll(d + timedelta(days=1)).month != d.month}
BUCKETS = {r.bucket_label: (r.day_start, r.day_end) for r in spark.table(f"{CATALOG}.reference.ref_maturity_bucket").collect()}
FX = {r.currency_code: float(r.rate_to_usd) for r in spark.table(f"{CATALOG}.reference.ref_fx_rates").collect()}
print(f"{len(DATES)} business days {DATES[0]} .. {DATES[-1]}; month-ends {sorted(MONTH_ENDS)}")

# Bronze record layout - also the CSV header read by pipelines/bronze_ingest.py
BRONZE_COLUMNS = [
    "record_id", "as_of_date", "booking_entity", "report_for_entity", "source_system", "instrument_type", "source_product_code",
    "product_subtype", "flow_direction", "customer_id", "collateral_id", "subsidiary_entity", "sub_product", "sub_product_2",
    "currency", "currency_2", "maturity_type", "maturity_date", "forward_start_date", "effective_maturity_date",
    "option_type", "option_date", "notice_days", "funding_start_date", "funding_end_date", "draw_notice_days",
    "reserve_requirement", "service_type", "operational_requirement", "depositor_count", "insurance_scheme",
    "principal_amount", "principal_amount_2", "forward_start_amount", "forward_start_amount_2", "market_value", "lendable_value",
    "collateral_value", "collateral_level", "encumbrance_type", "generic_issuer_type", "generic_product",
    "risk_weight", "accounting_designation", "insured", "trigger_flag", "rehypothecated", "unencumbered",
    "treasury_control", "settlement", "netting_eligible", "loss_absorbency", "fx_option_direction",
    "collection_reference", "product_reference", "sub_product_reference", "business_line", "internal_rating",
    "interest_rate", "link_id", "load_timestamp",
]
TABLE_FEED = {"I.A": "securities", "I.U": "loans", "I.S": "loans", "I.O": "derivatives", "O.D": "deposits",
              "O.W": "funding", "O.S": "funding", "O.O": "derivatives", "S.DC": "derivatives", "S.FX": "derivatives",
              "S.L": "finance", "S.B": "finance", "S.I": "finance"}
BUSINESS_LINE = {"I.A": "Treasury", "I.U": "Commercial Banking", "I.S": "Investment Banking", "I.O": "Investment Banking",
                 "O.D": "Retail Banking", "O.W": "Treasury", "O.S": "Investment Banking", "O.O": "Commercial Banking",
                 "S.DC": "Investment Banking", "S.FX": "Treasury", "S.L": "Treasury", "S.B": "Treasury", "S.I": "Wealth Management"}
MV_TABLES = {"I.A", "S.DC", "S.L", "S.I", "S.B"}   # primary amount is Market Value
TABLE_DEFAULTS = {
    "I.A": dict(tc=True, acct="Available for Sale"),
    "I.S": dict(unenc=False, tc=False, settle="Bilateral", cv=1.02),
    "O.S": dict(rehyp=False, tc=True, settle="Bilateral", cv=1.03),
    "O.D": dict(ins="Uninsured", trig=False),
    "I.O": dict(tc=False),
}

def booking_entity(pid):
    """Which legal entity books the product (the group's operating model)."""
    t, n = pid.rsplit(".", 1)[0], int(pid.rsplit(".", 1)[1])
    if t in ("I.A", "I.U", "O.D") or pid in ("I.S.6", "I.S.7", "I.S.8", "O.S.5", "O.S.6", "O.W.16", "O.W.17", "I.O.6", "I.O.8", "I.O.9",
                                           "O.O.4", "O.O.5", "O.O.6", "O.O.7", "O.O.19", "O.O.21", "O.O.22", "S.B.3", "S.B.4"):
        return "LE02"
    if pid in ("O.W.8", "O.W.11", "O.W.12", "O.W.13", "O.W.14", "O.W.15") or t == "S.L" or pid in ("S.B.1", "S.B.2", "S.B.5", "S.B.6", "S.I.5", "S.I.6"):
        return "LE00"
    if t == "O.W" and n <= 7:
        return "LE05"
    return "LE03"

def P(pid, amt, bucket="Open", n=2, **kw):
    """One position: primary amount `amt` (millions of the currency) split across `n` source records."""
    return dict(pid=pid, amt=amt, bucket=bucket, n=n, **kw)

D = lambda s: date.fromisoformat(s)
POOLS = [
    # ---------------- I.A Inflows-Assets (custody, central bank balances) ----------------
    P("I.A.1", 12000, ">2 Yr <= 3 Yr", 4, cc="A-1-Q", rating="AAA", shock={D("2026-02-11"): 0.70}),
    P("I.A.1", 4000, ">= 1 Yr <= 2 Yr", 1, cc="A-1-Q", link=["L19a", "L19b", "L19f"], rating="AAA"),
    P("I.A.1", 3000, ">4 Yr <= 5 Yr", 2, cc="A-2-Q", acct="Held to Maturity"),
    P("I.A.1", 3000, ">5 Yr", 3, cc="A-3-Q", link="L21a"),
    P("I.A.1", 2000, ">3 Yr <= 4 Yr", 2, cc="S-1-Q", ccy="EUR"),
    P("I.A.1", 4000, ">2 Yr <= 3 Yr", 2, cc="G-1-Q"),
    P("I.A.1", 5000, ">5 Yr", 4, cc="G-2-Q", acct="Held to Maturity", link="L21b"),
    P("I.A.1", 2500, "Perpetual", 2, cc="E-1-Q", acct="Trading Asset"),
    P("I.A.1", 2000, ">3 Yr <= 4 Yr", 2, cc="IG-1-Q"),
    P("I.A.1", 3000, ">2 Yr <= 3 Yr", 2, cc="IG-1", tc=False),
    P("I.A.1", 1500, ">4 Yr <= 5 Yr", 2, cc="N-2", acct="Trading Asset", tc=False),
    P("I.A.1", 590, "Day 25", 2, cc="L-10", acct="Held to Maturity", tc=False, link="L04b"),
    P("I.A.1", 590, "Day 10", 2, cc="L-8", acct="Held to Maturity", tc=False, link="L04c"),
    P("I.A.1", 1770, "91 - 120 Days", 2, cc="L-6", acct="Held to Maturity", tc=False, link="L04d"),
    P("I.A.1", 1960, ">2 Yr <= 3 Yr", 2, cc="L-7", acct="Held to Maturity", tc=False, link="L04e"),
    P("I.A.1", 5880, "180 - 270 Days", 3, cc="L-10", acct="Held to Maturity", tc=False, link="L04f"),
    P("I.A.1", 1790, "Open", 2, cc="L-11", acct="Held to Maturity", tc=False, link="L04g"),
    P("I.A.1", 895, "Open", 1, cc="L-11", acct="Held to Maturity", tc=False, link="L04h"),
    P("I.A.1", 595, "Day 40", 1, cc="L-10", acct="Held to Maturity", tc=False, link="L04i"),
    P("I.A.1", 1480, ">= 1 Yr <= 2 Yr", 2, cc="L-9", acct="Held to Maturity", tc=False, link="L04j"),
    P("I.A.1", 790, "121 - 150 Days", 1, cc="L-11", acct="Held to Maturity", tc=False, link="L04k"),
    P("I.A.1", 880, "180 - 270 Days", 1, cc="L-10", acct="Held to Maturity", tc=False, link="L04n", start=D("2026-01-13")),   # the C0301 loan at market value
    P("I.A.2", 2450, ">= 1 Yr <= 2 Yr", 2, sub="Federal Reserve Bank", cc="L-10", tc=False, link="L04a"),
    P("I.A.2", 1000, ">2 Yr <= 3 Yr", 1, sub="Federal Reserve Bank", cc="A-1-Q", acct="Not Applicable", link="L03"),
    P("I.A.2", 6000, ">5 Yr", 3, sub="Federal Home Loan Bank", cc="L-1", tc=False, link="L04m1"),
    # central bank balances: one balance per central bank; the reserve requirement splits I.A.4 (restricted) / I.A.3
    P("I.A.3", 13200, "Open", 2, kind="CBRES", req=1200 / 13200, sub="Federal Reserve Bank", cc="A-0-Q", acct="Not Applicable"),
    P("I.A.3", 1500, "Open", 1, kind="CBRES", req=0.0, sub="European Central Bank", cc="A-0-Q", ccy="EUR", acct="Not Applicable"),
    P("I.A.3", 300, "Open", 1, kind="CBRES", req=1.0, sub="Bank of England", cc="A-0-Q", ccy="GBP", acct="Not Applicable", tc=False),
    P("I.A.3", 800, "Open", 1, sub="Currency and Coin", cc="A-0-Q", acct="Not Applicable"),
    P("I.A.5", 1500, ">2 Yr <= 3 Yr", 2, cc="A-1-Q", fwd="Day 1", fa=1.0, acct="Not Applicable"),
    P("I.A.6", 900, ">5 Yr", 2, cc="G-2-Q", fwd="Day 12", fa=1.0, acct="Not Applicable"),
    P("I.A.7", 5000, ">2 Yr <= 3 Yr", 2, cc="A-1-Q", enc="Securities Financing Transaction", eff="Day 25", tc=False, link="L05a"),
    P("I.A.7", 2000, ">3 Yr <= 4 Yr", 2, cc="G-1-Q", enc="Derivative IM and DFC", eff="91 - 120 Days", tc=False, link="L05b"),
    P("I.A.7", 3000, ">5 Yr", 2, cc="L-1", enc="Securities Financing Transaction", eff="91 - 120 Days", tc=False,
      acct="Held to Maturity", link=["L05c", "L04m2"]),
    P("I.A.7", 1000, ">2 Yr <= 3 Yr", 1, cc="IG-1", enc="Derivative VM", eff="Day 1", tc=False, link="L05d"),
    # ---------------- I.U Inflows-Unsecured ----------------
    P("I.U.1", 3000, "Day 3", 2, cp="Bank", gsib="JP Morgan Chase", rw=20),
    P("I.U.1", 2000, "Day 14", 2, cp="Bank", rw=20),
    P("I.U.1", 700, "Day 2", 1, cust="C0201", rw=100),                     # to the UK affiliate (in the consolidation)
    P("I.U.1", 700, "Day 2", 1, cust="C0202", rw=100, ic_pair="A"),        # intercompany pair A: bank lends to the broker-dealer
    P("I.U.1", 500, "Open", 1, cust="C0203", rw=20, be="LE03", ic_pair="C"),   # pair C, broker-dealer side: cash placed at the bank
    P("I.U.2", 1200, "Day 7", 2, cp="Bank", gsib="Barclays", ccy="GBP", rw=20, be="LE04"),
    P("I.U.2", 800, "Day 21", 1, cp="Bank", ccy="EUR", rw=20, be="LE04"),
    P("I.U.2", 500, "Day 5", 1, cp="Bank", ccy="HKD", rw=20, be="LE04"),
    P("I.U.3", 2000, "Open", 1, kind="NOSTRO", req=0.45, cp="Bank", gsib="Citigroup", rw=20, service="CLEARING", notice=30),
    P("I.U.5", 2500, ">= 1 Yr <= 2 Yr", 2, cp="Non-Financial Corporate", rw=100, opt="Extendible", link="L04a"),
    P("I.U.5", 600, "Day 25", 2, cp="Small Business", rw=75, bl="Retail Banking", link="L04b"),
    P("I.U.6", 600, "Day 10", 2, cp="Retail", rw=75, bl="Retail Banking", link="L04c"),
    P("I.U.6", 1800, "91 - 120 Days", 2, cp="Retail", rw=75, bl="Retail Banking", link="L04d"),
    P("I.U.6", 2000, ">2 Yr <= 3 Yr", 2, cp="Retail", rw=75, bl="Retail Banking", link="L04e"),
    P("I.U.6", 6000, "180 - 270 Days", 3, cp="Non-Financial Corporate", rw=100, link="L04f"),
    P("I.U.6", 6500, ">5 Yr", 3, cp="Retail", rw=50, bl="Retail Banking", link="L04m1"),
    P("I.U.6", 3200, ">5 Yr", 2, cp="Retail", rw=50, bl="Retail Banking", link="L04m2"),
    P("I.U.6", 900, "180 - 270 Days", 1, cust="C0301", rw=100, start=D("2026-01-13"), link="L04n"),   # new customer, onboarded mid-window
    P("I.U.7", 700, "Day 1", 1, cp="Bank", rw=20),
    P("I.U.8", 1500, "Day 30", 2, cp="Bank", rw=20),
    P("I.U.8", 500, "Day 6", 1, cp="Sovereign", rw=0),
    P("I.U.8", 400, "Day 45", 1, cust="C0302", rw=0, start=D("2026-01-21")),
    # ---------------- I.S Inflows-Secured ----------------
    P("I.S.1", 4000, "Day 2", 2, cp="Bank", gsib="Goldman Sachs", cc="A-1-Q", settle="FICC", unenc=True, tc=True, rw=0),
    P("I.S.1", 2500, "Day 9", 2, cp="Broker Dealer", cc="G-2-Q", settle="Triparty", enc="Securities Financing Transaction",
      eff="Day 9", rw=20, links=[("A-1-Q", 0.55), ("G-2-Q", 0.47)]),
    P("I.S.1", 1000, "Day 20", 1, cp="Bank", cc="A-1-Q", settle="Bilateral", rw=0, link="L03"),
    P("I.S.1", 1200, "Day 25", 1, cp="Non-Financial Corporate", cc="IG-1", rw=100),
    P("I.S.1", 1200, "Day 3", 1, cust="C0203", cc="A-1-Q", rw=0, ic_pair="B"),   # pair B: broker-dealer lends cash to the bank
    P("I.S.2", 1500, "Open", 2, cp="Broker Dealer", cc="E-1-Q", settle="Other", rw=100),
    P("I.S.2", 800, "Day 4", 1, cp="Bank", cc="A-2-Q", unenc=True, tc=True, rw=20),
    P("I.S.3", 700, "Day 15", 1, cp="Bank", cc="G-2-Q", fwd="Day 5", fa=1.0, rw=20),
    P("I.S.4", 1000, "Day 18", 1, cp="Bank", sub="Level 2a Pledged", cc="A-1-Q", rw=20, link="L02"),
    P("I.S.5", 1800, "Open", 2, cp="Non-regulated Fund", cc="E-3", cv=1.45, rw=100, link="L04g"),
    P("I.S.5", 900, "Open", 1, cp="Investment Company or Advisor", cc="IG-1-Q", cv=1.30, rw=100, link="L04h"),
    P("I.S.6", 600, "Day 40", 1, cp="Non-Financial Corporate", cc="N-2", cv=1.25, rw=100, link="L04i", subtype="REHYPOTHECATABLE"),
    P("I.S.7", 1500, ">= 1 Yr <= 2 Yr", 2, cp="Non-Financial Corporate", cc="L-9", cv=1.40, rw=100, link="L04j"),
    P("I.S.8", 800, "121 - 150 Days", 1, cp="Pension Fund", cc="L-4", cv=1.35, rw=50, link="L04k", subtype="NON_REHYPOTHECATABLE"),
    P("I.S.9", 500, "Open", 1, cp="Non-regulated Fund", sub="Physical Long Position", cc="E-1-Q", rw=100),
    P("I.S.10", 300, "Day 30", 1, cp="Bank", sub="Futures", cc="E-3", rw=100),
    # ---------------- I.O Inflows-Other ----------------
    P("I.O.1", 1800, "Day 5", 2, cp="Bank", gsib="Goldman Sachs"),
    P("I.O.1", 900, "Day 22", 1, cp="Broker Dealer"),
    P("I.O.1", 1000, "91 - 120 Days", 1, cp="Bank"),
    P("I.O.2", 600, "Open", 2, cp="Bank", cc="A-0-Q", cv=1.0, link="L13"),
    P("I.O.2", 300, "Day 1", 1, cp="Financial Market Utlility", cc="A-0-Q", cv=1.0),
    P("I.O.2", 150, "Day 2", 1, cp="Bank", cc="A-1-Q", cv=1.0, link="L15"),
    P("I.O.3", 400, "Day 17", 1, cp="Bank", cc="G-2-Q", cv=1.0),
    P("I.O.4", 2000, "Open", 1, cp="Bank", drawdown=(-400, 300, 0)),
    P("I.O.5", 350, "Open", 1, cp="Broker Dealer"),
    P("I.O.6", 200, "Day 15", 1, cc="A-1-Q"),
    P("I.O.6", 150, "Day 20", 1, cc="L-10"),
    P("I.O.8", 300, "Day 25", 3, cc="A-3-Q", link="L21a"),
    P("I.O.8", 200, "Day 10", 4, cc="G-2-Q", link="L21b"),
    P("I.O.9", 250, "Day 12", 1),
    # ---------------- O.D Outflows-Deposits ----------------
    # retail / small business account groups: depositor_count drives the FDIC insured allocation (insured vs uninsured part)
    P("O.D.1", 18000, "Open", 5, cp="Retail", dep=57600),
    P("O.D.1", 6000, "Open", 3, cp="Retail", dep=4000),
    P("O.D.1", 4000, "Open", 3, cp="Small Business", dep=12000),
    P("O.D.1", 900, "Open", 2, cp="Small Business", ccy="EUR", dep=2800, scheme="OTHER"),
    P("O.D.2", 14000, "Open", 4, cp="Retail", dep=52000),
    P("O.D.2", 2000, "Open", 1, cp="Retail", dep=8000, link=["L19c", "L19d"]),
    P("O.D.2", 5000, "Open", 3, cp="Retail", dep=3000),
    P("O.D.2", 2500, "Open", 2, cp="Small Business", dep=9000),
    P("O.D.3", 3500, "Day 45", 2, cp="Retail", dep=1500),
    P("O.D.3", 2000, "91 - 120 Days", 2, cp="Retail", dep=8000),
    P("O.D.3", 1500, "Day 20", 2, cp="Retail", dep=600, opt="Accelerated-Counterparty"),
    # wholesale demand deposits: operational services + requirement split O.D.4 (operational) / O.D.5 (excess)
    P("O.D.4", 14000, "Open", 3, kind="OPDDA", req=9000 / 14000, cp="Non-Financial Corporate", bl="Commercial Banking",
      service="CASH_MANAGEMENT", notice=30),
    P("O.D.4", 6500, "Open", 2, kind="OPDDA", req=4000 / 6500, cp="Bank", gsib="Citigroup", bl="Commercial Banking",
      service="CLEARING", notice=60),
    P("O.D.4", 1500, "Open", 1, kind="OPDDA", req=1.0, cp="Pension Fund", ins="FDIC", bl="Commercial Banking",
      service="CUSTODY", notice=30),
    P("O.D.6", 8000, "Open", 3, cp="Non-Financial Corporate", bl="Commercial Banking", shock={D("2026-02-24"): 1.40}),
    P("O.D.6", 1000, "Open", 2, cp="Non-Financial Corporate", bl="Commercial Banking", link="L20"),
    P("O.D.6", 1200, "Open", 1, cp="Sovereign", bl="Commercial Banking"),
    P("O.D.6", 4000, "Open", 2, cp="Investment Company or Advisor", bl="Wealth Management", service="PRIME_BROKERAGE", notice=30),
    P("O.D.6", 2000, "Open", 2, cp="Non-regulated Fund", trig=True, bl="Wealth Management"),
    P("O.D.6", 800, "Open", 1, cp="Public Sector Entity", cc="A-1-Q", cv=1.06, rehyp=False, bl="Commercial Banking"),
    P("O.D.6", 300, "Open", 1, cp="Non-Financial Corporate", ccy="SGD", bl="Commercial Banking", service="CASH_MANAGEMENT", notice=5),
    P("O.D.6", 500, "Open", 1, cust="C0202", bl="Commercial Banking", ic_pair="C"),   # pair C: deposit from the broker-dealer affiliate
    P("O.D.6", 1100, "Open", 1, cust="C0303", bl="Wealth Management", start=D("2026-02-03")),
    P("O.D.6", 700, "Open", 1, cust="C0305", bl="Commercial Banking", start=D("2026-02-24")),   # pending approval at window end
    P("O.D.7", 1200, "Open", 2, cp="Non-Financial Corporate", ins="FDIC"),
    P("O.D.7", 600, "Open", 1, cp="Retail", dep=2400),
    P("O.D.8", 2500, "Day 60", 2, cp="Retail", dep=10000),
    P("O.D.8", 700, "Open", 1, cp="Retail", dep=800),
    P("O.D.9", 5000, "Open", 2, cp="Retail", dep=12000, bl="Wealth Management", sweep=True),   # insured part -> O.D.9, rest -> O.D.10
    P("O.D.11", 1500, "Open", 1, cp="Investment Company or Advisor", bl="Wealth Management"),
    P("O.D.12", 1000, "Open", 2, cp="Non-Financial Corporate", bl="Commercial Banking", link="L20"),
    P("O.D.13", 1800, "Open", 2, cp="Retail", dep=7200),
    P("O.D.14", 900, "Open", 1, cp="Non-Financial Corporate", bl="Commercial Banking"),
    P("O.D.15", 300, "Open", 1, cp="Other", shock={D("2026-02-19"): 4.6}),
    # ---------------- O.W Outflows-Wholesale ----------------
    P("O.W.1", 1500, "Day 25", 2, cc="L-6", subtype="SINGLE_SELLER"),
    P("O.W.2", 800, "Day 40", 1, cc="L-7", subtype="MULTI_SELLER"),
    P("O.W.3", 600, "Day 15", 1, cc="IG-3"),
    P("O.W.4", 2000, ">2 Yr <= 3 Yr", 2, cc="L-6"),
    P("O.W.4", 300, "Day 29", 1, cc="L-7"),
    P("O.W.5", 1200, ">4 Yr <= 5 Yr", 1, cc="L-3", ccy="EUR"),
    P("O.W.6", 400, "Day 7", 1, cc="IG-2-Q", opt="Accelerated-Counterparty"),
    P("O.W.7", 700, "151 - 179 Days", 1, cc="L-9"),
    P("O.W.8", 3000, "Day 10", 2),
    P("O.W.8", 2000, "Day 35", 2),
    P("O.W.9", 2000, "Day 1", 2, cp="Bank", gsib="Wells Fargo", subtype="ONSHORE", be="LE03"),
    P("O.W.9", 500, "Day 5", 1, cp="Non-Financial Corporate", subtype="ONSHORE", be="LE03"),
    P("O.W.9", 700, "Day 2", 1, cust="C0203", subtype="ONSHORE", be="LE03", ic_pair="A"),   # pair A, broker-dealer side
    P("O.W.9", 600, "Day 4", 1, cust="C0304", subtype="ONSHORE", be="LE03", start=D("2026-02-10")),
    P("O.W.10", 900, "Day 3", 1, cp="Bank", ccy="GBP", subtype="OFFSHORE", be="LE04"),
    P("O.W.11", 9000, ">3 Yr <= 4 Yr", 3, la="TLAC", subtype="UNSTRUCTURED_LTD"),
    P("O.W.11", 4000, ">2 Yr <= 3 Yr", 1, la="TLAC", link="L10a", subtype="UNSTRUCTURED_LTD"),
    P("O.W.11", 2000, ">5 Yr", 1, la="Capital", subtype="UNSTRUCTURED_LTD"),
    P("O.W.11", 1000, "Day 20", 1, la="TLAC", subtype="UNSTRUCTURED_LTD"),
    P("O.W.12", 2000, ">3 Yr <= 4 Yr", 1, opt="Accelerated-Firm", la="TLAC", link="L10b", subtype="STRUCTURED_LTD"),
    P("O.W.13", 500, ">5 Yr", 1, subtype="GOVT_SUPPORTED"),
    P("O.W.14", 1200, "180 - 270 Days", 1, la="TLAC", subtype="NOTE"),
    P("O.W.15", 800, "271 - 364 Days", 1, opt="Evergreen", subtype="STRUCTURED_NOTE"),
    P("O.W.16", 2500, "Day 60", 2, cp="Non-Financial Corporate"),
    P("O.W.16", 1000, "Day 14", 1, cp="Investment Company or Advisor"),
    P("O.W.17", 1000, "Day 30", 1, cp="Bank"),
    P("O.W.18", 600, "Open", 1, cp="Retail", bl="Wealth Management"),
    P("O.W.18", 1200, "Open", 1, cp="Non-regulated Fund", bl="Investment Banking"),
    P("O.W.18", 800, "Open", 1, cust="C0306", bl="Investment Banking", start=D("2026-02-26")),   # pending approval at window end
    P("O.W.19", 200, "Day 9", 1, cp="Other"),
    # ---------------- O.S Outflows-Secured ----------------
    P("O.S.1", 6000, "Day 1", 3, cp="Bank", gsib="Bank of America", cc="A-1-Q", settle="FICC"),
    P("O.S.1", 2400, "Day 9", 2, cp="Broker Dealer", cc="G-2-Q", settle="Triparty", rehyp=True, links=[("A-1-Q", 0.60), ("G-2-Q", 0.45)]),
    P("O.S.1", 1500, "Day 14", 1, cp="Bank", cc="N-2", tc=False),
    P("O.S.1", 5000, "Day 25", 2, cp="Bank", cc="A-1-Q", settle="FICC", link="L05a"),
    P("O.S.1", 1200, "Day 3", 1, cust="C0202", cc="A-1-Q", be="LE02", ic_pair="B"),   # pair B, bank side
    P("O.S.2", 1500, "Open", 2, cp="Investment Company or Advisor", cc="E-1-Q", settle="Other", gen=("EQUITY_RUSSELL_1000", "EQUITY")),
    P("O.S.2", 900, "Day 6", 1, cp="Pension Fund", cc="A-2-Q"),
    P("O.S.3", 600, "Day 20", 1, cp="Bank", cc="G-2-Q", fwd="Day 4", fa=1.0),
    P("O.S.4", 1000, "Day 18", 1, cp="Bank", sub="Level 1 Received", cc="G-1-Q", link="L02"),
    P("O.S.5", 3000, "91 - 120 Days", 2, cp="Government Sponsored Entity", cc="L-1", tc=False, cv=1.25, link="L05c",
      links=[("L-1", 1.10), ("G-2-Q", 0.15)]),
    P("O.S.5", 2000, "Day 28", 1, cp="Government Sponsored Entity", cc="L-1", tc=False, cv=1.25),
    P("O.S.6", 500, "Day 7", 1, cp="Central Bank", sub="Federal Reserve Bank", cc="A-1-Q"),
    P("O.S.7", 700, "Open", 1, cp="Non-regulated Fund", sub="External Cash Transactions", cc="E-1-Q", tc=False),
    P("O.S.8", 500, "Day 8", 1, cp="Broker Dealer", sub="Unsettled - Forward", cc="A-1-Q", fwd="Day 8", fa=1.0),
    P("O.S.8", 1000, "Open", 1, cp="Bank", sub="External Non-Cash Transactions", cc="G-1-Q"),
    P("O.S.9", 300, "Open", 1, cp="Bank", sub="Futures", cc="E-1-Q", tc=False),
    P("O.S.10", 200, "Day 30", 1, cp="Bank", sub="Other", cc="E-3", tc=False),
    P("O.S.11", 1200, "Day 40", 1, cp="Non-Financial Corporate", cc="IG-1", tc=False),
    P("O.S.11", 800, "Day 15", 1, cp="Bank", cc="Z-1", tc=False),
    # ---------------- O.O Outflows-Other (commitments carry draw terms -> effective drawdown date) ----------------
    P("O.O.1", 1500, "Day 6", 2, cp="Bank", gsib="Deutsche Bank"),
    P("O.O.1", 1100, "Day 19", 1, cp="Broker Dealer"),
    P("O.O.1", 800, "121 - 150 Days", 1, cp="Bank"),
    P("O.O.2", 700, "Open", 2, cp="Bank", cc="A-0-Q", cv=1.0, link="L14"),
    P("O.O.2", 120, "Day 1", 1, cp="Bank", cc="A-0-Q", cv=1.0, link="L16"),
    P("O.O.3", 450, "Day 17", 1, cp="Bank", cc="G-2-Q", cv=1.0),
    P("O.O.4", 12000, ">2 Yr <= 3 Yr", 3, cp="Non-Financial Corporate", drawdown=(-500, None, 1)),
    P("O.O.4", 2000, ">= 1 Yr <= 2 Yr", 1, cp="Bank", drawdown=(45, None, 0)),         # forward-start facility
    P("O.O.4", 1500, ">5 Yr", 2, cp="Retail", bl="Retail Banking", drawdown=(-700, None, 0)),
    P("O.O.4", 800, ">= 1 Yr <= 2 Yr", 1, cp="Debt Issuing Special Purpose Entity", drawdown=(-200, None, 2)),
    P("O.O.4", 1200, ">= 1 Yr <= 2 Yr", 1, cp="Investment Company or Advisor", drawdown=(-300, None, 3)),
    P("O.O.4", 600, ">3 Yr <= 4 Yr", 1, cp="Public Sector Entity", drawdown=(-900, None, 1)),
    P("O.O.5", 1500, ">= 1 Yr <= 2 Yr", 1, cp="Debt Issuing Special Purpose Entity", drawdown=(-100, None, 1)),
    P("O.O.5", 400, ">= 1 Yr <= 2 Yr", 1, cp="Municipalities for VRDN Structures", drawdown=(-100, None, 7)),
    P("O.O.5", 600, ">= 1 Yr <= 2 Yr", 1, cp="Bank", drawdown=(-100, None, 1)),
    P("O.O.5", 900, ">2 Yr <= 3 Yr", 1, cp="Non-Financial Corporate", drawdown=(-400, None, 2)),
    P("O.O.6", 2500, "Day 30", 2, cp="Retail", bl="Retail Banking", drawdown=(-20, None, 0)),
    P("O.O.7", 1000, "Day 60", 1, cp="Non-Financial Corporate"),
    P("O.O.8", 2000, "Open", 1),
    P("O.O.9", 200, "Open", 1, cc="A-1-Q", cv=1.0, subtype="NOTCH1"),
    P("O.O.10", 350, "Open", 1, cc="A-1-Q", cv=1.0, subtype="NOTCH2"),
    P("O.O.11", 500, "Open", 1, cc="A-1-Q", cv=1.0, subtype="NOTCH3"),
    P("O.O.12", 800, "Open", 1, cc="A-1-Q", cv=1.0, subtype="FIN_CONDITION"),
    P("O.O.13", 1000, "Open", 1, cc="A-0-Q", cv=1.0, subtype="NOTCH1"),
    P("O.O.14", 1800, "Open", 1, cc="A-0-Q", cv=1.0, subtype="NOTCH2"),
    P("O.O.15", 2600, "Open", 1, cc="A-0-Q", cv=1.0, subtype="NOTCH3"),
    P("O.O.16", 4000, "Open", 1, cc="A-0-Q", cv=1.0, subtype="FIN_CONDITION"),
    P("O.O.17", 600, "Open", 1, cp="Non-regulated Fund", cc="A-0-Q", cv=1.0),
    P("O.O.18", 300, "Day 45", 1, cp="Bank"),
    P("O.O.19", 900, "Day 15", 2),
    P("O.O.21", 250, "Day 20", 1),
    P("O.O.22", 400, "Day 5", 1),
    # ---------------- S.DC Supplemental-Derivatives & Collateral ----------------
    P("S.DC.1", 8000, None, 2, sub2="OTC - Bilateral", cp="Bank", gsib="JP Morgan Chase", level="Undercollateralized"),
    P("S.DC.1", 3000, None, 1, sub2="OTC - Centralized (Principal)", cp="Financial Market Utlility", level="Fully Collateralized"),
    P("S.DC.1", 600, None, 1, sub2="Exchange-traded (Principal)", cp="Financial Market Utlility", level="Fully Collateralized"),
    P("S.DC.2", 7200, None, 2, sub2="OTC - Bilateral", cp="Bank", gsib="Deutsche Bank", level="Undercollateralized"),
    P("S.DC.2", 2800, None, 1, sub2="OTC - Centralized (Principal)", cp="Financial Market Utlility", level="Fully Collateralized"),
    P("S.DC.3", 1100, None, 1, sub="Non-Segregated Cash", sub2="OTC - Centralized (Principal)", cc="A-0-Q", cp="Financial Market Utlility"),
    P("S.DC.4", 1250, None, 1, sub="Non-Segregated Cash", sub2="OTC - Centralized (Principal)", cc="A-0-Q", cp="Financial Market Utlility"),
    P("S.DC.5", 1500, None, 1, sub="Segregated Cash", sub2="OTC - Centralized (Principal)", cc="A-0-Q", cp="Financial Market Utlility", subtype="HOUSE"),
    P("S.DC.5", 2000, None, 2, sub="Rehypothecateable Collateral Encumbered", sub2="OTC - Bilateral", cc="G-1-Q", cp="Bank",
      enc="Derivative IM and DFC", eff="91 - 120 Days", link="L05b", subtype="HOUSE"),
    P("S.DC.6", 900, None, 1, sub="Non-Rehypothecateable Collateral", sub2="OTC - Centralized (Agent)", cc="A-1-Q", cp="Financial Market Utlility", subtype="CUSTOMER"),
    P("S.DC.7", 1400, None, 2, sub="Rehypothecateable Collateral Unencumbered", sub2="OTC - Bilateral", cc="A-1-Q", cp="Bank", tc=True),
    P("S.DC.7", 600, None, 1, sub="Segregated Cash", sub2="Exchange-traded (Principal)", cc="A-0-Q", cp="Broker Dealer"),
    P("S.DC.8", 2500, None, 2, sub="Non-Segregated Cash", sub2="OTC - Bilateral", cc="A-0-Q", cp="Bank", level="Undercollateralized",
      net=True, link="L14", subtype="HOUSE"),
    P("S.DC.8", 1000, None, 1, sub="Rehypothecateable Collateral Encumbered", sub2="OTC - Bilateral", cc="IG-1", cp="Bank",
      level="Undercollateralized", net=False, enc="Derivative VM", eff="Day 1", link="L05d", subtype="HOUSE"),
    P("S.DC.9", 700, None, 1, sub="Non-Segregated Cash", sub2="OTC - Centralized (Agent)", cc="A-0-Q", cp="Financial Market Utlility",
      level="Fully Collateralized", net=True, subtype="CUSTOMER"),
    P("S.DC.10", 2200, None, 2, sub="Non-Segregated Cash", sub2="OTC - Bilateral", cc="A-0-Q", cp="Bank", level="Undercollateralized",
      net=True, link="L13"),
    P("S.DC.11", 400, None, 1, cc="A-1-Q", cp="Financial Market Utlility"),
    P("S.DC.12", 250, None, 1, cc="A-1-Q", cp="Financial Market Utlility"),
    P("S.DC.13", 120, None, 1, cp="Bank", link="L16"),
    P("S.DC.14", 150, None, 1, cp="Bank", link="L15"),
    P("S.DC.15", 300, None, 1, cc="A-1-Q"),
    P("S.DC.16", 200, None, 1, cc="A-0-Q"),
    P("S.DC.17", 250, None, 1, cc="A-0-Q"),
    P("S.DC.18", 300, None, 1, subtype="DERIV_RISK"),
    P("S.DC.19", 450, None, 1, subtype="DERIV_CAPACITY"),
    P("S.DC.20", 150, None, 1, subtype="OTHER_RISK"),
    P("S.DC.21", 200, None, 1, subtype="OTHER_CAPACITY"),
    # ---------------- S.L Supplemental-LRM: entity-level measures (S.L.6 comes from the LCR engine) ----------------
    P("S.L.1", 1800, None, 1, cc="A-1-Q", ic="Acme National Bank N.A.", link="L19a", rfe="ENT001", subtype="RESTRICTED"),
    P("S.L.2", 2500, None, 1, cc="A-1-Q", ic="Acme National Bank N.A.", link="L19b", rfe="ENT001", subtype="TRANSFERABLE"),
    P("S.L.3", 350, None, 1, cc="A-1-Q", rfe="ENT001"),
    P("S.L.4", 450, None, 1, link="L10a", rfe="ENT001", subtype="NON_STRUCTURED"),
    P("S.L.5", 120, None, 1, link="L10b", rfe="ENT001", subtype="STRUCTURED"),
    P("S.L.7", 3000, None, 1, ic="Acme National Bank N.A.", link="L19c", monthly=True, rfe="ENT001", subtype="RESTRICTED"),
    P("S.L.8", 1500, None, 1, ic="Acme National Bank N.A.", link="L19d", monthly=True, rfe="ENT001", subtype="TRANSFERABLE"),
    P("S.L.9", 200, None, 1, cc="E-1-Q", monthly=True, rfe="ENT001"),
    P("S.L.10", 1.1840, None, 1, ratio=True, monthly=True, rfe="ENT001"),
    P("S.L.10", 1.2265, None, 1, ratio=True, monthly=True, rfe="ENT002"),
    # ---------------- S.B Supplemental-Balance Sheet ----------------
    P("S.B.1", 32000, "Perpetual", 1, monthly=True, rfe="ENT001"),
    P("S.B.2", 4500, "Open", 1, monthly=True, rfe="ENT001"),
    P("S.B.3", 900, "Open", 1, cc="L-10", cp="Non-Financial Corporate", rw=150, monthly=True),
    P("S.B.4", 6000, "Open", 1, cc="Z-1", monthly=True),
    P("S.B.5", -1200, "Day 5", 1, cp="Bank", cc="Z-1", cref="I.O", pref="I.O.1", rfe="ENT001"),
    P("S.B.5", -1200, "Day 6", 1, cp="Bank", cc="Z-1", cref="O.O", pref="O.O.1", rfe="ENT001"),
    P("S.B.6", -350, ">5 Yr", 1, cref="I.A", pref="I.A.1", cc="G-2-Q", monthly=True, rfe="ENT001"),
    P("S.B.6", 220, ">3 Yr <= 4 Yr", 1, cref="O.W", pref="O.W.11", monthly=True, rfe="ENT001"),
    # ---------------- S.I Supplemental-Informational ----------------
    P("S.I.1", 9000, None, 2, cc="E-3"),
    P("S.I.2", 4500, None, 1, cc="E-3"),
    P("S.I.3", 1200, None, 1, cc="A-0-Q", direction="RECEIVE"),
    P("S.I.4", 1100, None, 1, cc="A-0-Q", direction="PAY"),
    P("S.I.5", 6000, None, 1, ic="Acme National Bank N.A.", rfe="ENT001"),
    P("S.I.6", 1800, None, 1, cc="A-1-Q", ic="Acme National Bank N.A.", link="L19f", rfe="ENT001"),
    # ---------------- S.FX Supplemental-Foreign Exchange (amt = Maturity Amount Currency 1) ----------------
    P("S.FX.1", 500, "Day 2", 1, cp="Bank", ccy="EUR", ccy2="USD", amt2=1.080, settle="CLS"),
    P("S.FX.1", 270, "Day 2", 1, cp="Bank", ccy="USD", ccy2="GBP", amt2=0.789, settle="CLS"),
    P("S.FX.2", 75000, "Day 25", 1, cp="Bank", ccy="JPY", ccy2="USD", amt2=0.00667, settle="Bilateral"),
    P("S.FX.2", 800, "91 - 120 Days", 1, cp="Non-Financial Corporate", ccy="USD", ccy2="EUR", amt2=0.925, settle="Bilateral"),
    P("S.FX.2", 100, "Day 30", 1, cp="Non-Financial Corporate", ccy="EUR", ccy2="USD", amt2=1.080, settle="Bilateral", fxdir="Sold"),
    P("S.FX.3", 1000, "91 - 120 Days", 1, cp="Bank", gsib="HSBC", ccy="EUR", ccy2="USD", amt2=1.085, fwd="Day 3", fa=1.0, fa2=1.080, settle="CLS"),
    P("S.FX.3", 2000, "Day 40", 1, cp="Bank", ccy="HKD", ccy2="USD", amt2=0.1281, fwd="Day 2", fa=1.0, fa2=0.1280, settle="Other"),
]

COMMENTS = [  # collection, PID, sub-product, text, month-end only, from date
    ("O.D", "O.D.15", None, "Counterparty 'Other': balances of structured settlement trusts that do not meet any of the 19 counterparty definitions; reviewed with the supervisory team.", False, None),
    ("O.W", "O.W.19", None, "Counterparty 'Other': deferred purchase-price obligations to a court-appointed receiver; not classifiable under the defined counterparty types.", False, None),
    ("S.B", "S.B.6", None, "Carrying value adjustments: amortized cost vs fair value on HTM GSE MBS (I.A.1) and fair-value hedge adjustments on TLAC debt (O.W.11).", True, None),
]
print(f"{len(POOLS)} pools covering {len({p['pid'] for p in POOLS})} PIDs (+ S.L.6 from the LCR engine)")

# COMMAND ----------

def tcode(pid):
    return pid.rsplit(".", 1)[0]

# ---- Source-system view of each PID: standard product type, subtype and direction, then a bank product code ----------
import re
_rules = spark.table(f"{CATALOG}.reference.rules_pid_derivation").orderBy("standard_product_type", "priority").collect()
SOURCE_OF = {}
for r in _rules:
    if r.product_id not in SOURCE_OF:   # first rule that yields the PID
        subtype = re.search(r"product_subtype = '([A-Z0-9_]+)'", r.condition_sql)
        direction = re.search(r"flow_direction = '([A-Z]+)'", r.condition_sql)
        SOURCE_OF[r.product_id] = (r.standard_product_type, subtype.group(1) if subtype else None, direction.group(1) if direction else None)
SOURCE_OF.update({"O.D.6": ("DDA", None, None), "O.D.4": ("DDA", None, None), "I.U.3": ("NOSTRO", None, None),
                  "I.A.3": ("CB-RES", None, None), "O.D.9": ("SWEEP-AFF", None, None)})   # subtypes from the calculation layer
_map = spark.table(f"{CATALOG}.reference.ref_source_product_map").collect()
CODES = {}
for m in _map:
    CODES.setdefault(m.standard_product_type, []).append((m.source_system, m.source_product_code))

def source_product(pid, o, rng):
    std, subtype, direction = SOURCE_OF[pid]
    if pid in ("I.A.1", "I.A.2", "I.A.7") and (o.get("cc") or "").startswith("L-"):
        std = "LOAN-POOL"                        # whole loans held at market value come from the loan pool, not custody
    if pid == "I.A.3" and o.get("sub") == "Currency and Coin":
        std = "VAULT-CASH"
    system, code = rng.choice(CODES[std])
    return system, code, std, o.get("subtype", subtype), o.get("direction", direction)

_cust = spark.table(f"{CATALOG}.reference.ref_customer_master").collect()
def customer_for(o, pid):
    """The customer whose master data gives the pool's Counterparty / G-SIB (affiliates and new customers are explicit)."""
    if o.get("cust"):
        return o["cust"]
    cp = o.get("cp")
    if cp is None:
        return None
    for c in _cust:
        if c.counterparty == cp and (c.gsib_parent or None) == o.get("gsib") and not c.affiliate_legal_entity_id \
                and c.customer_id < "C0300" and (cp not in ("Retail", "Small Business") or c.has_relationship == (pid != "O.D.3")):
            return c.customer_id
    raise ValueError(f"no customer for {pid} {cp} {o.get('gsib')}")

SECURITY_OF = {r.collateral_class: r.collateral_id for r in spark.table(f"{CATALOG}.reference.ref_security_master").collect()}

def bucket_date(as_of, label, rng):
    """(maturity_type, date) for a bucket label; a business day inside the bucket (flows are not observed on weekends)."""
    if label in (None, "Open"):
        return ("OPEN", None)
    if label == "Perpetual":
        return ("PERPETUAL", None)
    lo, hi = BUCKETS[label]
    return ("DATED", roll(as_of + timedelta(days=rng.randint(lo, min(hi, lo + 1500)))))

def flag(v):
    return None if v is None else ("Y" if v else "N")

INSURANCE_LIMIT = 0.25   # USD 250,000 per depositor and ownership category, in millions

def parts_of(o, pid, record):
    """Expected PIDs per calculated part of one source record - the same split notebook 03 calculates (test oracle)."""
    bal = record["principal_amount"] if record["principal_amount"] is not None else (record["market_value"] or 0.0)
    if o.get("kind") == "OPDDA":
        op = min(bal, record["operational_requirement"])
        return [("OP", "O.D.4", op), ("EX", "O.D.5", bal - op)]
    if o.get("kind") == "NOSTRO":
        op = min(bal, record["operational_requirement"])
        return [("OP", "I.U.3", op), ("EX", "I.U.4", bal - op)]
    if o.get("kind") == "CBRES":
        rst = min(bal, record["reserve_requirement"])
        return [("RST", "I.A.4", rst), ("UNR", "I.A.3", bal - rst)]
    if o.get("dep"):
        ins = min(bal, record["depositor_count"] * INSURANCE_LIMIT)
        return [("INS", "O.D.9" if o.get("sweep") else pid, ins), ("UNI", "O.D.10" if o.get("sweep") else pid, bal - ins)]
    return [("1", pid, bal)]

def option_terms(o, as_of, mdate, rng):
    """Embedded option attributes that make the LRM s.31(a) maturity land in the pool's bucket."""
    opt = o.get("opt")
    if not opt:
        return {}, mdate
    target = mdate
    if opt == "Evergreen":
        return {"option_type": "NOTICE", "notice_days": (target - as_of).days}, None
    if opt == "Extendible":            # inflow, borrower may extend: latest date = the extension date
        return {"option_type": "EXTEND_COUNTERPARTY", "option_date": target}, roll(as_of + timedelta(days=rng.randint(181, 270)))
    later = roll(target + timedelta(days=rng.randint(400, 900)))
    return {"option_type": "PUT_COUNTERPARTY" if opt == "Accelerated-Counterparty" else "CALL_FIRM", "option_date": target}, later

def level_series():
    """Daily level per table: a slow random walk (seeded) so day-over-day changes look like a real balance sheet."""
    rng = random.Random(7)
    lv, out = {k: 1.0 for k in ("I.A", "I.U", "I.S", "I.O", "O.D", "O.W", "O.S", "O.O", "S")}, {}
    for i, d in enumerate(DATES):
        for k in lv:
            lv[k] *= 1.0 + rng.gauss(0.0004 if k == "O.D" else 0.0, 0.006)
        out[d] = dict(lv)
    return out
LEVELS = level_series()

def build_day(as_of, day_idx):
    rng = random.Random(20260102 + day_idx)
    ts = datetime(as_of.year, as_of.month, as_of.day, 22, 0, 0)
    counters, rows = {}, []
    for pool in POOLS:
        if pool.get("monthly") and as_of not in MONTH_ENDS:
            continue
        if pool.get("start") and as_of < pool["start"]:
            continue
        pid, code = pool["pid"], tcode(pool["pid"])
        o = {**TABLE_DEFAULTS.get(code, {}), **pool}
        feed = TABLE_FEED[code]
        n = o["n"]
        if o.get("ratio"):
            shares, d = [1.0], 1.0
        else:
            weights = [rng.uniform(0.6, 1.4) for _ in range(n)]
            shares = [w / sum(weights) for w in weights]
            d = LEVELS[as_of].get(code, LEVELS[as_of]["S"]) if pid not in ("S.DC.18", "S.DC.19", "S.DC.20", "S.DC.21") else 1.0
            if o.get("ic_pair"):
                d = 1.0                                 # intercompany pairs are booked identically on both sides
            d *= o.get("shock", {}).get(as_of, 1.0)
        for i, share in enumerate(shares):
            counters[feed] = counters.get(feed, 0) + 1
            amt = round(o["amt"] * d * share, 4)
            mtype, mdate = bucket_date(as_of, o["bucket"], rng)
            opt_attrs, contract_date = option_terms(o, as_of, mdate, rng)
            if o.get("opt") == "Evergreen":
                mtype = "OPEN"
            fdate = bucket_date(as_of, o["fwd"], rng)[1] if o.get("fwd") else None
            edate = (as_of if o["eff"] == "Open" else bucket_date(as_of, o["eff"], rng)[1]) if o.get("eff") else None
            mv_table = code in MV_TABLES
            links = o.get("link")
            link_id = "|".join(f"{k}-{as_of}-{i}" for k in ([links] if isinstance(links, str) else links)) if links else None
            system, src_code, std, subtype, direction = source_product(pid, o, rng)
            dd = o.get("drawdown")
            rec = {
                "record_id": f"{feed[:3].upper()}-{as_of}-{counters[feed]:05d}", "as_of_date": as_of,
                "booking_entity": o.get("be") or booking_entity(pid), "report_for_entity": o.get("rfe"),
                "source_system": system, "instrument_type": std, "source_product_code": src_code, "product_subtype": subtype,
                "flow_direction": direction, "customer_id": customer_for(o, pid),
                "collateral_id": SECURITY_OF[o["cc"]] if o.get("cc") and not o.get("links") and not o.get("gen") else None,
                "subsidiary_entity": o.get("ic"), "sub_product": o.get("sub"), "sub_product_2": o.get("sub2"),
                "currency": o.get("ccy", "USD"), "currency_2": o.get("ccy2"),
                "maturity_type": mtype, "maturity_date": contract_date if opt_attrs else mdate,
                "forward_start_date": fdate, "effective_maturity_date": edate,
                "option_type": opt_attrs.get("option_type"), "option_date": opt_attrs.get("option_date"),
                "notice_days": opt_attrs.get("notice_days", o.get("notice")),   # evergreen notice, or the operational-service termination notice
                "funding_start_date": as_of + timedelta(days=dd[0]) if dd else None,
                "funding_end_date": (mdate or as_of + timedelta(days=365)) if dd else None, "draw_notice_days": dd[2] if dd else None,
                "reserve_requirement": round(amt * o["req"], 4) if o.get("kind") == "CBRES" else None,
                "service_type": o.get("service"), "operational_requirement": round(amt * o["req"], 4) if o.get("kind") in ("OPDDA", "NOSTRO") else None,
                "depositor_count": max(1, int(o["dep"] * share)) if o.get("dep") else None,
                "insurance_scheme": o.get("scheme", "FDIC") if o.get("dep") else None,
                "principal_amount": None if mv_table else amt, "principal_amount_2": round(amt * o["amt2"], 4) if o.get("amt2") else None,
                "forward_start_amount": round(amt * o["fa"], 4) if o.get("fa") else None,
                "forward_start_amount_2": round(amt * o["fa2"], 4) if o.get("fa2") else None,
                "market_value": amt if mv_table else None, "lendable_value": None,
                "collateral_value": round(amt * o.get("cv", 1.0), 4) if o.get("cc") and code in ("I.S", "O.S", "I.O", "O.O", "O.D", "O.W") and o.get("cv") and not o.get("links") else None,
                "collateral_level": o.get("level"), "encumbrance_type": o.get("enc"),
                "generic_issuer_type": o["gen"][0] if o.get("gen") else None, "generic_product": o["gen"][1] if o.get("gen") else None,
                "risk_weight": o.get("rw"),   # source systems carry the risk weight in percent; notebook 03 converts to the 6G decimal
                "accounting_designation": o.get("acct"), "insured": None if o.get("dep") else o.get("ins"),
                "trigger_flag": flag(o.get("trig")), "rehypothecated": flag(o.get("rehyp")), "unencumbered": flag(o.get("unenc")),
                "treasury_control": flag(o.get("tc")), "settlement": o.get("settle"), "netting_eligible": flag(o.get("net")),
                "loss_absorbency": o.get("la"), "fx_option_direction": o.get("fxdir"), "collection_reference": o.get("cref"),
                "product_reference": o.get("pref"), "sub_product_reference": o.get("sref"),
                "business_line": o.get("bl", BUSINESS_LINE[code]), "internal_rating": o.get("rating", rng.choice(["AA", "A", "BBB", "BB"])),
                "interest_rate": round(rng.uniform(0.001, 0.0525), 6), "link_id": link_id, "load_timestamp": ts, "_feed": feed,
                "_pid": pid, "_pool": o,
            }
            rec["_parts"] = parts_of(o, pid, rec)
            if o.get("links"):
                rec["_links"] = [(SECURITY_OF[cc], round(amt * f, 4)) for cc, f in o["links"]]
            rows.append(rec)
    return rows

# COMMAND ----------

def usd(row, amount_col, ccy_col="currency"):
    v = row.get(amount_col)
    return 0.0 if v is None else float(v) * FX[row[ccy_col]]

def within_30(as_of, d):
    return d is None or (d - as_of).days <= 30

def add_net30(as_of, rows):
    """I.O.7 / O.O.20 per booking entity: net of the <= 30-day derivative, collateral-call, FX and forward-settlement flows."""
    nets = {}
    for r in rows:
        pid, open_or_30 = r["_pid"], r["maturity_type"] == "OPEN" or within_30(as_of, r["maturity_date"])
        be, v = r["booking_entity"], 0.0
        if pid in ("I.O.1", "I.O.2") and open_or_30:
            v = usd(r, "principal_amount")
        elif pid in ("O.O.1", "O.O.2") and open_or_30:
            v = -usd(r, "principal_amount")
        elif pid == "I.A.6" and r["forward_start_date"] and within_30(as_of, r["forward_start_date"]):
            v = -usd(r, "forward_start_amount")
        elif pid == "O.S.8" and r["sub_product"] == "Unsettled - Forward" and r["forward_start_date"] and within_30(as_of, r["forward_start_date"]):
            v = usd(r, "forward_start_amount")
        elif pid.startswith("S.FX."):
            if within_30(as_of, r["maturity_date"]):
                v += usd(r, "principal_amount") - usd(r, "principal_amount_2", "currency_2")
            if r["forward_start_date"] and within_30(as_of, r["forward_start_date"]):
                v += usd(r, "forward_start_amount_2", "currency_2") - usd(r, "forward_start_amount")
        if v:
            nets[be] = nets.get(be, 0.0) + v
    base = next(r for r in rows if r["_pid"] == "I.O.1")
    for be, net in sorted(nets.items()):
        pid = "I.O.7" if net >= 0 else "O.O.20"
        rec = {**{k: None for k in base}, "record_id": f"DER-{as_of}-NET30-{be}", "as_of_date": as_of, "booking_entity": be,
               "source_system": "MUREX", "instrument_type": "NET30", "source_product_code": "MX-NET30",
               "flow_direction": "RECEIVE" if pid == "I.O.7" else "PAY", "_pid": pid, "_pool": {},
               "currency": "USD", "maturity_type": "OPEN", "principal_amount": round(abs(net), 4),
               "treasury_control": "N" if pid == "I.O.7" else None, "business_line": "Investment Banking",
               "internal_rating": "NR", "interest_rate": 0.0, "load_timestamp": base["load_timestamp"], "_feed": "derivatives"}
        rec["_parts"] = [("1", pid, rec["principal_amount"])]
        rows.append(rec)
    return sum(nets.values())

GL_TABLES = ["I.A", "I.U", "I.S", "I.O", "O.D", "O.W", "O.S", "O.O", "S.DC", "S.B", "S.I"]
def gl_balances(as_of, rows, rng):
    """GL control totals per legal entity and FR 2052a table (USD), taken before any feed problem."""
    totals = {}
    for r in rows:
        code = tcode(r["_pid"])
        if code in GL_TABLES:
            col = "market_value" if code in MV_TABLES else "principal_amount"
            totals[(r["booking_entity"], code)] = totals.get((r["booking_entity"], code), 0.0) + usd(r, col)
    out = []
    for (be, code), total in sorted(totals.items()):
        noise = rng.uniform(-0.0012, 0.0012)
        if code == "O.W" and be == "LE00" and as_of == date(2026, 2, 24):
            noise = 0.0085   # one GL break above the 0.5% threshold
        out.append({"as_of_date": as_of, "legal_entity_id": be, "table_code": code, "gl_account_group": f"GL-{be}-{code.replace('.', '')}",
                    "gl_balance_usd": round(total * (1 + noise), 4), "source_system": "ORACLE_GL",
                    "load_timestamp": datetime(as_of.year, as_of.month, as_of.day, 21, 0)})
    return out

# Demo dates: one feed arrives 30% short; the rest is held back in landing/_late/ until the analyst asks the source to
# re-send it (Collect -> notebook 00 copies it into the feed's folder and the day re-runs). One feed per date, so the
# trailing 5-day medians stay whole.
DEMO_SHORT_FEED = {date(2026, 2, 23): "funding", date(2026, 2, 24): "securities", date(2026, 2, 25): "loans",
                   date(2026, 2, 26): "derivatives", date(2026, 2, 27): "deposits"}

def plant_events(as_of, day_idx, rows):
    """Deliberate problems the controls must catch. Returns the number of records added or changed."""
    first = lambda pid: next(r for r in rows if r["_pid"] == pid)
    tmpl, loan = first("O.D.1"), first("I.S.6")
    changed = []
    def clone(src, **kw):
        r = {**src, **kw}
        r["_parts"] = parts_of(src["_pool"], r["_pid"], r) if r["_pid"] else []
        rows.append(r)
        changed.append(r)
    # --- DQ gate (quarantine) and PID derivation exceptions ---
    if day_idx % 9 == 1:
        clone(tmpl, record_id=f"DEP-{as_of}-BAD01", source_system=None, principal_amount=12.5, depositor_count=40)
    if day_idx % 9 == 2:
        clone(tmpl, record_id=f"DEP-{as_of}-BAD02", customer_id="C9999", principal_amount=40.0, depositor_count=100)   # not onboarded
    if day_idx % 9 == 3:
        clone(tmpl, record_id=f"DEP-{as_of}-BAD03", principal_amount=-5.0, depositor_count=10)
    if day_idx % 9 == 4:
        rows.append(dict(tmpl))   # duplicate record_id - collapsed to one record by DQ_010
    if day_idx % 9 == 5:
        clone(tmpl, record_id=f"DEP-{as_of}-BAD05", currency="XYZ", principal_amount=3.0, depositor_count=10)
    if day_idx % 9 == 6:   # secured term loan without the rehypothecation flag: passes DQ, no PID rule matches -> exception queue
        clone(loan, record_id=f"LOA-{as_of}-EXC01", product_subtype=None, principal_amount=15.0, link_id=None, _pid=None)
    if as_of >= date(2026, 2, 25):   # a new deposit product code the product catalogue does not map yet
        clone(tmpl, record_id=f"DEP-{as_of}-NEWCODE", source_product_code="FIS-CHK-PREMIER", instrument_type="Premier Checking - relationship pricing",
              principal_amount=55.0, depositor_count=180)
    # --- Demo dates: work at every step for the analyst (fr2052a-demo-reset restores it) ---
    if as_of in DEMO_SHORT_FEED:
        clone(tmpl, record_id=f"DEP-{as_of}-DQ11", currency="US$", principal_amount=21.0, depositor_count=70)   # DQ_011 -> USD
        clone(tmpl, record_id=f"DEP-{as_of}-DQ09", booking_entity="LE-00", principal_amount=9.5, depositor_count=30)   # DQ_009 -> LE00
        clone(loan, record_id=f"LOA-{as_of}-EXC02", product_subtype=None, principal_amount=22.0, link_id=None, _pid=None)   # no PID rule
    # --- Fed post-submission check defects ---
    if as_of == date(2026, 1, 14):   # PSV-01 weekend maturity
        r = next(x for x in rows if x["_pid"] == "O.W.16")
        r["maturity_date"] = date(2026, 1, 17)
    if as_of == date(2026, 1, 21):   # PSV-04 lendable value above market value (override from the collateral system)
        r = next(x for x in rows if x["_pid"] == "I.A.1")
        r["lendable_value"] = round(r["market_value"] * 1.08, 4)
    if as_of == date(2026, 1, 28):   # PSV-07 large haircut on a secured transaction
        r = next(x for x in rows if x["_pid"] == "I.S.6" and x["record_id"] != f"LOA-{as_of}-EXC01")
        r["collateral_value"] = round(r["principal_amount"] * 3.4, 4)
    if as_of == date(2026, 2, 5):    # PSV-06 intercompany asymmetry: the broker-dealer books pair A at 650 instead of 700
        r = next(x for x in rows if x["_pid"] == "O.W.9" and x["_pool"].get("ic_pair") == "A")
        r["principal_amount"] = 650.0
        r["_parts"] = [("1", "O.W.9", 650.0)]
    if as_of == date(2026, 2, 10):   # PSV-10 bank books a placement with itself as the customer
        clone(first("I.U.8"), record_id=f"LOA-{as_of}-SELF", customer_id="C0203", principal_amount=25.0, link_id=None)
    if as_of == date(2026, 2, 12):   # PSV-13 collateral class reported where it is not applicable (O.W.9)
        r = next(x for x in rows if x["_pid"] == "O.W.9")
        r["collateral_id"] = SECURITY_OF["A-1-Q"]
    return changed

def write_csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = _csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow(["" if r.get(c) is None else r[c] for c in header])

for feed in POSITION_FEEDS + OTHER_FEEDS + ["_late"]:
    shutil.rmtree(f"{LANDING}/{feed}", ignore_errors=True)

onboarding = list(_csv.DictReader(open(f"{REF_DIR}/ref_customer_onboarding.csv")))
summary, answer_key = [], []
for day_idx, as_of in enumerate(DATES):
    rows = build_day(as_of, day_idx)
    net = add_net30(as_of, rows)
    gl = gl_balances(as_of, rows, random.Random(99 + day_idx))
    planted = plant_events(as_of, day_idx, rows)
    n_bad = len(planted)
    late = []
    if as_of in DEMO_SHORT_FEED:
        feed, keep = DEMO_SHORT_FEED[as_of], {id(r) for r in planted}
        pool = [r for r in rows if r["_feed"] == feed and id(r) not in keep and "NET30" not in r["record_id"]]
        held = set(id(r) for r in random.Random(7 + day_idx).sample(pool, int(len(pool) * 0.3)))
        late, rows = [r for r in rows if id(r) in held], [r for r in rows if id(r) not in held]
        write_csv(f"{LANDING}/_late/{feed}/{as_of}/{feed}_{as_of}.csv", BRONZE_COLUMNS, late)
    if as_of == date(2026, 2, 3):   # short derivatives feed: 40% of the records do not arrive (GL is complete)
        drop = [r for r in rows if r["_feed"] == "derivatives" and not r["record_id"].endswith(("NET30-LE03", "NET30-LE02"))]
        lost = set(id(r) for r in random.Random(3).sample(drop, int(len(drop) * 0.4)))
        rows = [r for r in rows if id(r) not in lost]
    for feed in POSITION_FEEDS:
        write_csv(f"{LANDING}/{feed}/{as_of}/{feed}_{as_of}.csv", BRONZE_COLUMNS, [r for r in rows if r["_feed"] == feed])
    links = [{"as_of_date": as_of, "record_id": r["record_id"], "collateral_id": cid, "collateral_amount": a,
              "source_system": "ALGO_COLLATERAL", "load_timestamp": r["load_timestamp"]} for r in rows + late for cid, a in r.get("_links", [])]
    write_csv(f"{LANDING}/collateral_links/{as_of}/collateral_links_{as_of}.csv",
              ["as_of_date", "record_id", "collateral_id", "collateral_amount", "source_system", "load_timestamp"], links)
    comments = [{"record_id": f"CMT-{as_of}-{i + 1:03d}", "as_of_date": as_of, "reporting_entity": "ENT001", "collection": c[0],
                 "product_id": c[1], "sub_product": c[2], "comments": c[3], "source_system": "REG_REPORTING_WORKBENCH",
                 "load_timestamp": datetime(as_of.year, as_of.month, as_of.day, 23, 0)}
                for i, c in enumerate(COMMENTS) if (not c[4] or as_of in MONTH_ENDS)]
    write_csv(f"{LANDING}/comments/{as_of}/comments_{as_of}.csv",
              ["record_id", "as_of_date", "reporting_entity", "collection", "product_id", "sub_product", "comments", "source_system", "load_timestamp"], comments)
    write_csv(f"{LANDING}/gl_balances/{as_of}/gl_balances_{as_of}.csv",
              ["as_of_date", "legal_entity_id", "table_code", "gl_account_group", "gl_balance_usd", "source_system", "load_timestamp"], gl)
    kyc = [{**c, "as_of_date": as_of, "source_system": "KYC_ONBOARDING", "load_timestamp": datetime(as_of.year, as_of.month, as_of.day, 20, 0)}
           for c in onboarding if c["onboarded_on"] <= str(as_of)]
    write_csv(f"{LANDING}/customers/{as_of}/customers_{as_of}.csv",
              ["as_of_date", "customer_id", "customer_name", "country", "naics_code", "legal_form", "lei", "onboarded_on", "source_system", "load_timestamp"], kyc)
    summary.append((str(as_of), len(rows), len({r["_pid"] for r in rows if r["_pid"]}), n_bad, round(net, 2), len(comments), len(links)))
    answer_key += [(as_of, r["record_id"], part, pid) for r in rows + late for part, pid, amt in r["_parts"] if part == "1" or abs(amt) > 1e-9]

display(spark.createDataFrame(summary, "as_of_date STRING, source_records INT, products INT, planted INT, net30_usd DOUBLE, comments INT, collateral_links INT"))

# Test oracles for the synthetic data: the PID each calculated part of each record must get, and every customer's
# true classification (to score the AI-proposed classifications).
(spark.createDataFrame(answer_key, "as_of_date DATE, record_id STRING, part STRING, expected_product_id STRING")
 .dropDuplicates(["as_of_date", "record_id", "part"])
 .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.audit.pid_answer_key"))
spark.sql(f"COMMENT ON TABLE {CATALOG}.audit.pid_answer_key IS 'Synthetic data only - the PID each calculated part of each landed source record must get; notebook 03 measures the derivation against it'")
(spark.read.option("header", True).csv(f"{SPEC_VOL}/ref_customer_answer_key.csv")
 .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.audit.customer_answer_key"))
spark.sql(f"COMMENT ON TABLE {CATALOG}.audit.customer_answer_key IS 'Synthetic data only - true FR 2052a classification of every customer; scores the AI-proposed classifications'")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. DQ, Silver, FR 2052a (14 tables), LCR and audit tables
# MAGIC
# MAGIC The FR 2052a gold tables are generated from `reference.spec_table_fields`: one table per data table on p.84-85,
# MAGIC columns in the figure's order, plus Currency / Converted (footnote 16), `record_count`, `record_key` and the
# MAGIC validation flags written by notebook 04.

# COMMAND ----------

spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.dq.assessment_results")
spark.sql(f"""CREATE TABLE {CATALOG}.dq.assessment_results (
  as_of_date DATE, rule_id STRING, rule_name STRING, rule_category STRING, severity STRING,
  total_records INT, failed_records INT, pass_rate DECIMAL(5,2), sample_failures STRING, status STRING, run_timestamp TIMESTAMP
) COMMENT 'DQ rule results per as_of_date (rules from reference.rules_dq)'""")
spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.dq.feed_monitor")
spark.sql(f"""CREATE TABLE {CATALOG}.dq.feed_monitor (
  as_of_date DATE, feed STRING, files INT, records INT, expected_records DOUBLE, ratio DECIMAL(9,4), last_arrival TIMESTAMP,
  status STRING, details STRING, run_timestamp TIMESTAMP
) COMMENT 'Feed completeness per as_of_date: records vs the trailing 5-day median (data contract)'""")
spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.dq.quarantine")
spark.sql(f"""CREATE TABLE {CATALOG}.dq.quarantine (
  as_of_date DATE, record_id STRING, source_feed STRING, source_product_code STRING, failed_rules STRING, record_json STRING, run_timestamp TIMESTAMP
) COMMENT 'Bronze records excluded by ERROR-severity DQ rules'""")
spark.sql(f"""CREATE TABLE IF NOT EXISTS {CATALOG}.dq.rule_failures (
  as_of_date DATE, rule_id STRING, record_id STRING, source_feed STRING, severity STRING, quarantined BOOLEAN, run_timestamp TIMESTAMP
) COMMENT 'Every source record that failed a DQ rule (ERROR quarantines, WARNING reports only) - record-level evidence'""")
spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.dq.pid_exceptions")
spark.sql(f"""CREATE TABLE {CATALOG}.dq.pid_exceptions (
  as_of_date DATE, record_id STRING, position_id STRING, exception_type STRING, booking_entity STRING, provisional_product_id STRING,
  source_feed STRING, source_system STRING,
  source_product_code STRING, standard_product_type STRING, product_subtype STRING, flow_direction STRING, customer_id STRING,
  collateral_id STRING, reason STRING, amount_usd DECIMAL(22,4), record_json STRING, review_status STRING, run_timestamp TIMESTAMP
) COMMENT 'DQ-passed positions held out of the filing: no PID rule matched, or the customer awaits classification approval'""")

# DQ-passed source records, typed (notebook 02 output, notebook 03 input)
SOURCE_DDL = """
  as_of_date DATE, record_id STRING, source_feed STRING, source_system STRING, booking_entity STRING, report_for_entity STRING,
  instrument_type STRING, source_product_code STRING, product_subtype STRING, flow_direction STRING, customer_id STRING,
  collateral_id STRING, subsidiary_entity STRING, sub_product STRING, sub_product_2 STRING, currency STRING, currency_2 STRING,
  maturity_type STRING, maturity_date DATE, forward_start_date DATE, effective_maturity_date DATE,
  option_type STRING, option_date DATE, notice_days INT, funding_start_date DATE, funding_end_date DATE, draw_notice_days INT,
  reserve_requirement DECIMAL(22,4), service_type STRING, operational_requirement DECIMAL(22,4), depositor_count INT, insurance_scheme STRING,
  principal_amount DECIMAL(22,4), principal_amount_2 DECIMAL(22,4), forward_start_amount DECIMAL(22,4), forward_start_amount_2 DECIMAL(22,4),
  market_value DECIMAL(22,4), lendable_value DECIMAL(22,4), collateral_value DECIMAL(22,4), collateral_level STRING, encumbrance_type STRING,
  generic_issuer_type STRING, generic_product STRING, risk_weight_pct DECIMAL(9,4), accounting_designation STRING, insured STRING,
  trigger_flag BOOLEAN, rehypothecated BOOLEAN, unencumbered BOOLEAN, treasury_control BOOLEAN, settlement STRING, netting_eligible BOOLEAN,
  loss_absorbency STRING, fx_option_direction STRING, collection_reference STRING, product_reference STRING, sub_product_reference STRING,
  business_line STRING, internal_rating STRING, interest_rate DECIMAL(8,6), link_id STRING, dq_status STRING, dq_timestamp TIMESTAMP"""
spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.conformed.source_position")
spark.sql(f"""CREATE TABLE {CATALOG}.conformed.source_position ({SOURCE_DDL})
CLUSTER BY (as_of_date, source_product_code)
TBLPROPERTIES (delta.enableChangeDataFeed = true)   -- incremental Lakebase sync (synced table, TRIGGERED)
COMMENT 'DQ-passed source positions with typed flags, before the calculation layer and PID derivation (notebook 02 -> 03)'""")

# Silver: one row per calculated position part, at booking (legal entity) level
SILVER_DDL = """
  as_of_date DATE, position_id STRING, record_id STRING, part STRING, booking_entity STRING, report_for_entity STRING,
  source_feed STRING, source_system STRING, instrument_type STRING, source_product_code STRING, standard_product_type STRING,
  product_subtype STRING, flow_direction STRING, customer_id STRING, affiliate_legal_entity_id STRING, collateral_id STRING,
  product_id STRING, table_code STRING, pid_rule_id STRING, sub_product STRING, sub_product_2 STRING,
  counterparty STRING, counterparty_category STRING, gsib STRING, subsidiary_entity STRING, currency STRING, currency_2 STRING,
  maturity_type STRING, contract_maturity_date DATE, maturity_date DATE, maturity_basis STRING, maturity_days INT, maturity_bucket STRING,
  maturity_optionality STRING, forward_start_date DATE, forward_start_bucket STRING, effective_maturity_date DATE,
  effective_maturity_bucket STRING, weekend_flow BOOLEAN,
  principal_amount DECIMAL(22,4), principal_amount_2 DECIMAL(22,4), forward_start_amount DECIMAL(22,4), forward_start_amount_2 DECIMAL(22,4),
  market_value DECIMAL(22,4), lendable_value DECIMAL(22,4), lendable_basis STRING, collateral_class STRING, collateral_basis STRING,
  hqla_level STRING, is_hqla BOOLEAN, collateral_value DECIMAL(22,4), collateral_level STRING, encumbrance_type STRING, risk_weight DECIMAL(9,4),
  accounting_designation STRING, insured STRING, insured_basis STRING, trigger_flag BOOLEAN, rehypothecated BOOLEAN, unencumbered BOOLEAN,
  treasury_control BOOLEAN, settlement STRING, netting_eligible BOOLEAN, loss_absorbency STRING, fx_option_direction STRING,
  collection_reference STRING, product_reference STRING, sub_product_reference STRING, business_line STRING,
  internal_rating STRING, interest_rate DECIMAL(8,6), link_id STRING, enrichment_timestamp TIMESTAMP"""
spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.conformed.fact_liquidity_position")
spark.sql(f"""CREATE TABLE {CATALOG}.conformed.fact_liquidity_position ({SILVER_DDL})
CLUSTER BY (as_of_date, table_code)
TBLPROPERTIES (delta.enableChangeDataFeed = true)   -- incremental Lakebase sync (synced table, TRIGGERED)
COMMENT 'Silver golden source - one row per calculated position part (booking legal entity) with the derived PID, master-data enrichment and the calculation-layer results'""")

# Reporting-entity scope of each Silver position: intercompany eliminated, Internal / Internal Counterparty per entity
spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.conformed.entity_position")
spark.sql(f"""CREATE TABLE {CATALOG}.conformed.entity_position (
  as_of_date DATE, reporting_entity STRING, position_id STRING, relationship STRING, internal BOOLEAN, internal_counterparty STRING
) CLUSTER BY (as_of_date, reporting_entity)
TBLPROPERTIES (delta.enableChangeDataFeed = true)   -- incremental Lakebase sync (synced table, TRIGGERED)
COMMENT 'Which Silver positions each reporting entity reports: EXTERNAL / INTERNAL (affiliate outside the entity scope) / SELF (data error)'""")
spark.sql(f"""CREATE OR REPLACE VIEW {CATALOG}.conformed.v_entity_position
COMMENT 'Silver positions as reported by each reporting entity (intercompany eliminated, Internal / Internal Counterparty set)' AS
SELECT e.reporting_entity, e.relationship, e.internal, e.internal_counterparty, f.*
FROM {CATALOG}.conformed.entity_position e
JOIN {CATALOG}.conformed.fact_liquidity_position f ON f.as_of_date = e.as_of_date AND f.position_id = e.position_id""")

# Lineage to the landing file without exposing Bronze: record id, feed, landing file and ingestion time only (no values).
# Readers of conformed (the app, the agents) see where each source record came from; raw.* stays closed to them.
spark.sql(f"""CREATE OR REPLACE VIEW {CATALOG}.conformed.v_source_files
COMMENT 'Lineage: source record -> Bronze feed table -> landing file in raw.landing and ingestion time (no source values)' AS
""" + " UNION ALL ".join(f"SELECT as_of_date, record_id, '{f}' AS feed, _source_file AS landing_file, _ingested_at AS ingested_at FROM {CATALOG}.raw.{f}"
                         for f in ["deposits", "loans", "securities", "derivatives", "funding", "finance"]))

for t in ["pid_derivation_summary", "pid_rule_usage", "intercompany_elimination"]:
    spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.audit.{t}")
spark.sql(f"""CREATE TABLE {CATALOG}.audit.pid_derivation_summary (
  as_of_date DATE, source_records INT, positions INT, derived INT, exceptions INT, answer_key_checked INT, answer_key_mismatches INT,
  accuracy_pct DECIMAL(6,2), run_timestamp TIMESTAMP
) COMMENT 'PID derivation per as_of_date: coverage, exceptions and (synthetic data) accuracy against audit.pid_answer_key'""")
spark.sql(f"""CREATE TABLE {CATALOG}.audit.pid_rule_usage (
  as_of_date DATE, rule_id STRING, standard_product_type STRING, product_id STRING, records INT, run_timestamp TIMESTAMP
) COMMENT 'How many positions each PID derivation rule classified'""")
spark.sql(f"""CREATE TABLE {CATALOG}.audit.intercompany_elimination (
  as_of_date DATE, reporting_entity STRING, position_id STRING, booking_entity STRING, counterparty_legal_entity STRING,
  product_id STRING, amount_usd DECIMAL(22,4), run_timestamp TIMESTAMP
) COMMENT 'Positions between two legal entities inside a reporting entity scope - eliminated from that entity report'""")

# Steward decisions recorded in the app (Lakebase) and pulled into Delta before each run
spark.sql(f"""CREATE TABLE IF NOT EXISTS {CATALOG}.reference.customer_master_approvals (
  customer_id STRING, customer_name STRING, counterparty STRING, gsib_parent STRING, affiliate_legal_entity_id STRING,
  has_relationship BOOLEAN, approved_on DATE, approved_by STRING, suggestion_id STRING, decided_at TIMESTAMP
) COMMENT 'Customer classifications approved by the data steward in the app (AI-proposed or manual)'""")
spark.sql(f"""CREATE TABLE IF NOT EXISTS {CATALOG}.reference.source_product_map_approvals (
  source_system STRING, source_product_code STRING, standard_product_type STRING, description STRING, approved_on DATE,
  approved_by STRING, suggestion_id STRING, decided_at TIMESTAMP
) COMMENT 'Bank product code mappings approved in the app (AI-proposed or manual)'""")
spark.sql(f"""CREATE OR REPLACE VIEW {CATALOG}.reference.v_customer_master
COMMENT 'Effective customer master: initial load + steward-approved classifications' AS
SELECT customer_id, customer_name, counterparty, NULLIF(gsib_parent, '') AS gsib_parent, NULLIF(affiliate_legal_entity_id, '') AS affiliate_legal_entity_id,
       has_relationship, approved_on, approved_by FROM {CATALOG}.reference.ref_customer_master
UNION ALL
SELECT customer_id, customer_name, counterparty, NULLIF(gsib_parent, ''), NULLIF(affiliate_legal_entity_id, ''), has_relationship, approved_on, approved_by
FROM {CATALOG}.reference.customer_master_approvals
WHERE customer_id NOT IN (SELECT customer_id FROM {CATALOG}.reference.ref_customer_master)""")
spark.sql(f"""CREATE OR REPLACE VIEW {CATALOG}.reference.v_source_product_map
COMMENT 'Effective bank product code map: initial load + approved new codes' AS
SELECT source_system, source_product_code, standard_product_type, description, CAST(NULL AS DATE) AS approved_on FROM {CATALOG}.reference.ref_source_product_map
UNION ALL
SELECT source_system, source_product_code, standard_product_type, description, approved_on FROM {CATALOG}.reference.source_product_map_approvals
WHERE source_product_code NOT IN (SELECT source_product_code FROM {CATALOG}.reference.ref_source_product_map)""")

# Databricks-native AI assistance: every suggestion is proposed, then accepted or rejected by a person
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.ai_assist COMMENT 'AI suggestions (Databricks AI Functions) and their human decisions'")
spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.ai_assist.suggestions")
spark.sql(f"""CREATE TABLE {CATALOG}.ai_assist.suggestions (
  suggestion_id STRING, as_of_date DATE, suggestion_type STRING, subject_key STRING, subject STRING, suggestion STRING,
  rationale STRING, ai_function STRING, model STRING, confidence DOUBLE, status STRING, decided_by STRING, decided_at TIMESTAMP,
  created_timestamp TIMESTAMP
) COMMENT 'Suggestions from Databricks AI Functions (ai_classify, ai_similarity, ai_query, ai_forecast); status PROPOSED / ACCEPTED / REJECTED'""")
spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.ai_assist.evaluation")
spark.sql(f"""CREATE TABLE {CATALOG}.ai_assist.evaluation (
  eval_run STRING, suggestion_type STRING, metric STRING, value DOUBLE, n INT, details STRING, run_timestamp TIMESTAMP
) COMMENT 'Offline evaluation of the AI suggestions against the synthetic answer keys (logged to MLflow too)'""")

# COMMAND ----------

# 6G values carry up to 8 decimals (USD millions, i.e. to the cent); Risk Weight is a decimal 0 - 12.50
SQL_TYPE = {"text": "STRING", "flag": "BOOLEAN", "numeric": "DECIMAL(26,8)", "percent": "DECIMAL(9,4)"}
gold_tables = []
for code, t in tables.items():
    cols = ["as_of_date DATE COMMENT 'As-of date (T)'"]
    for f in fields_by_table[code]:
        cols.append(f"{f.column_name} {SQL_TYPE[f.data_type]} COMMENT '[{f.field_name}] {f.field_class} ({f.source})'")
    if code == "S.FX":   # 6G: each value carries its own converted attribute; Currency 2 legs can be converted independently
        cols.append("converted_2 BOOLEAN COMMENT '[Converted] for the Currency 2 values (6G converted attribute on target values)'")
    cols += ["record_count INT COMMENT 'Number of Silver positions aggregated into this data element'",
             "record_key STRING COMMENT 'Hash of the 6G report key: every field except amounts (Appendix I p.81; 6G BR General #20)'",
             "report_id INT COMMENT '6G reportID of this record in the XML file (unique per report type, assigned by notebook 06)'",
             "adjustment_ids STRING COMMENT 'Approved governed adjustments applied to this record (reg_2052a.adjustments)'",
             "validation_status STRING COMMENT 'PASS / FAIL from notebook 04'",
             "validation_issues STRING COMMENT 'Failed rule ids'"]
    spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.reg_2052a.{t.gold_table}")
    spark.sql(f"""CREATE TABLE {CATALOG}.reg_2052a.{t.gold_table} ({', '.join(cols)})
    COMMENT 'FR 2052a {t.table_code} {t.table_name} - layout per Data Tables p.84-85 (6G XML report {t.xml_report_type})'""")
    gold_tables.append(t.gold_table)
for legacy in ["gold_inflows", "gold_outflows", "gold_supplemental"]:
    spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.reg_2052a.{legacy}")
print(f"{len(gold_tables)} FR 2052a tables: {', '.join(gold_tables)}")

# COMMAND ----------

# Cross-table view used by the app and Genie: one row per data element with the table's primary amount in USD.
parts = []
for code, t in tables.items():
    if code == "S.C":
        continue
    colset = {f.column_name for f in fields_by_table[code]}
    ccy = "currency_1" if code == "S.FX" else "currency"
    pick = lambda c: c if c in colset else "CAST(NULL AS STRING)"
    parts.append(f"""SELECT g.as_of_date, '{code}' AS table_code, '{t.table_name}' AS table_name, g.reporting_entity, g.product_id,
      {pick('sub_product')} AS sub_product, {pick('counterparty')} AS counterparty, {pick('collateral_class')} AS collateral_class,
      {pick('maturity_bucket')} AS maturity_bucket, g.{ccy} AS currency, g.converted,
      g.{t.primary_amount_column} AS reported_amount,
      CASE WHEN g.product_id IN ('S.L.6', 'S.L.10') THEN g.{t.primary_amount_column}
           ELSE g.{t.primary_amount_column} * COALESCE(fx.rate_to_usd, 1) END AS reported_amount_usd,
      g.record_count, g.record_key, g.validation_status
    FROM {CATALOG}.reg_2052a.{t.gold_table} g
    LEFT JOIN {CATALOG}.reference.ref_fx_rates fx ON fx.currency_code = g.{ccy}""")
spark.sql(f"CREATE OR REPLACE VIEW {CATALOG}.reg_2052a.v_filing_records COMMENT 'All FR 2052a data elements across the 13 data tables (primary amount per table, USD-equivalent for totals)' AS " + " UNION ALL ".join(parts))

spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.reg_2052a.gold_header")
spark.sql(f"""CREATE TABLE {CATALOG}.reg_2052a.gold_header (
  as_of_date DATE, entity_id STRING, entity_name STRING, report_version STRING, fed_category STRING, tailoring_profile STRING,
  total_inflow_amount DECIMAL(22,4), total_outflow_amount DECIMAL(22,4), total_supplemental_amount DECIMAL(22,4),
  total_records INT, total_tables INT, products_reported INT, validation_status STRING, rules_evaluated INT, rules_failed INT,
  generation_timestamp TIMESTAMP, xml_file_path STRING
) COMMENT 'One row per FR 2052a submission (as_of_date)'""")
spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.reg_2052a.gold_validation")
spark.sql(f"""CREATE TABLE {CATALOG}.reg_2052a.gold_validation (
  as_of_date DATE, entity_id STRING, rule_id STRING, rule_source STRING, appendix STRING, table_code STRING, rule_name STRING,
  rule_category STRING, severity STRING, status STRING, records_checked INT, records_failed INT, failure_details STRING, run_timestamp TIMESTAMP
) COMMENT 'Validation results: Fed 6G business requirements (on the generated XML) and FR 2052a appendix rules (on the data)'""")
spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.reg_2052a.gold_validation_detail")
spark.sql(f"""CREATE TABLE {CATALOG}.reg_2052a.gold_validation_detail (
  as_of_date DATE, table_code STRING, record_key STRING, product_id STRING, rule_id STRING, rule_source STRING,
  failure_detail STRING, run_timestamp TIMESTAMP
) COMMENT 'One row per failing data element per rule'""")
for legacy in ["xml_output"]:
    spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.reg_2052a.{legacy}")
spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.reg_2052a.submission_files")
spark.sql(f"""CREATE TABLE {CATALOG}.reg_2052a.submission_files (
  as_of_date DATE, entity_id STRING, file_type STRING, file_name STRING, run_number INT, version INT, reporting_frequency STRING,
  report_types INT, record_count INT, xsd_valid BOOLEAN, xsd_errors INT, xsd_error_sample STRING,
  br_rules_failed INT, release_status STRING, xml_content STRING, xml_size_bytes INT, file_path STRING, generated_timestamp TIMESTAMP
) COMMENT '6G submission files per as_of_date and pipeline run (run_number); version is the 6G header version (resubmission count + 1)'""")
spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.reg_2052a.submission_review")
spark.sql(f"""CREATE TABLE {CATALOG}.reg_2052a.submission_review (
  as_of_date DATE, run_number INT, version INT, action STRING, status STRING, actor STRING, note STRING, action_timestamp TIMESTAMP
) COMMENT 'Reporting-run control and sign-off log: GENERATED -> REPORTING_REQUESTED -> APPROVED (or REJECTED / OVERRIDE_REQUESTED) -> SUBMITTED'""")
spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.reg_2052a.adjustments")
spark.sql(f"""CREATE TABLE {CATALOG}.reg_2052a.adjustments (
  adjustment_id STRING, as_of_date DATE, reporting_entity STRING, table_code STRING, record_key STRING, column_name STRING,
  amount DECIMAL(26,8), reason STRING, preparer STRING, approver STRING, status STRING, created_at TIMESTAMP, decided_at TIMESTAMP
) COMMENT 'Governed adjustments to filed records (posted in the app, approved by a second person, applied by notebook 05)'""")
spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.reg_2052a.record_lineage")
spark.sql(f"""CREATE TABLE {CATALOG}.reg_2052a.record_lineage (
  as_of_date DATE, reporting_entity STRING, table_code STRING, record_key STRING, position_id STRING, record_id STRING,
  amount DECIMAL(26,8), run_timestamp TIMESTAMP
) CLUSTER BY (as_of_date, reporting_entity)
TBLPROPERTIES (delta.enableChangeDataFeed = true)   -- incremental Lakebase sync (synced table, TRIGGERED)
COMMENT 'Drill-down: which Silver positions (and source records) make up each filed record'""")
spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.reg_2052a.stwf_schedule_g")
spark.sql(f"""CREATE TABLE {CATALOG}.reg_2052a.stwf_schedule_g (
  as_of_date DATE, reporting_entity STRING, stwf_item STRING, item_name STRING, maturity_column STRING, mdrm STRING,
  amount_usd DECIMAL(22,4), weighted_amount_usd DECIMAL(22,4), records INT, run_timestamp TIMESTAMP
) COMMENT 'FR Y-15 Schedule G short-term wholesale funding items computed from FR 2052a data elements (Appendix VII), with MDRM codes'""")
spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.reg_2052a.variance")
spark.sql(f"""CREATE TABLE {CATALOG}.reg_2052a.variance (
  as_of_date DATE, reporting_entity STRING, series_level STRING, table_code STRING, product_id STRING, amount_usd DOUBLE,
  prior_amount_usd DOUBLE, change_pct DOUBLE, forecast_usd DOUBLE, lower_usd DOUBLE, upper_usd DOUBLE, is_anomaly BOOLEAN,
  history_points INT, run_timestamp TIMESTAMP
) COMMENT 'Day-over-day variance per entity x table / PID, with ai_forecast expected range; anomalies go to business review'""")
spark.sql(f"""CREATE VOLUME IF NOT EXISTS {CATALOG}.reg_2052a.xml_filings COMMENT 'Generated FR 2052a XML filings'""")
# submission_files was re-created above, so the run numbers start again at 1: remove the 6G files of the previous build
for _d in os.listdir(f"/Volumes/{CATALOG}/reg_2052a/xml_filings"):
    shutil.rmtree(f"/Volumes/{CATALOG}/reg_2052a/xml_filings/{_d}", ignore_errors=True)

# COMMAND ----------

spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.reg_lcr.calculation_results")
spark.sql(f"""CREATE TABLE {CATALOG}.reg_lcr.calculation_results (
  calculation_id STRING, as_of_date DATE, entity_id STRING, scenario_code STRING,
  level1_hqla DECIMAL(22,4), level2a_hqla DECIMAL(22,4), level2a_hqla_adjusted DECIMAL(22,4), level2b_hqla DECIMAL(22,4),
  level2b_hqla_adjusted DECIMAL(22,4), level2_cap_excess DECIMAL(22,4), level2b_cap_excess DECIMAL(22,4), excluded_hqla DECIMAL(22,4),
  total_hqla DECIMAL(22,4), total_outflows DECIMAL(22,4), retail_deposit_outflows DECIMAL(22,4), wholesale_unsecured_outflows DECIMAL(22,4),
  secured_funding_outflows DECIMAL(22,4), derivative_outflows DECIMAL(22,4), commitment_outflows DECIMAL(22,4), other_outflows DECIMAL(22,4),
  total_inflows DECIMAL(22,4), inflow_cap DECIMAL(22,4), capped_inflows DECIMAL(22,4), maturity_mismatch_add_on DECIMAL(22,4),
  outflow_adjustment_pct DECIMAL(5,4), total_net_cash_outflows DECIMAL(22,4), lcr_ratio DECIMAL(10,4), lcr_compliant BOOLEAN,
  unmatched_positions INT, calculation_timestamp TIMESTAMP
) COMMENT 'LCR (12 CFR 249) per as_of_date - computed from Silver with reference.rules_lcr_appendix_vi'""")
spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.reg_lcr.calculation_detail")
spark.sql(f"""CREATE TABLE {CATALOG}.reg_lcr.calculation_detail (
  as_of_date DATE, entity_id STRING, record_id STRING, product_id STRING, flow_direction STRING, rule_id STRING, rule_name STRING,
  counterparty STRING, collateral_class STRING, hqla_level STRING, amount_usd DECIMAL(22,4), rate DECIMAL(5,4), weighted_amount_usd DECIMAL(22,4)
) COMMENT 'LCR rule applied to each Silver position'""")

for t in ["gl_reconciliation", "cross_metric_recon", "data_lineage"]:
    spark.sql(f"DROP TABLE IF EXISTS {CATALOG}.audit.{t}")
spark.sql(f"""CREATE TABLE {CATALOG}.audit.gl_reconciliation (
  as_of_date DATE, entity_id STRING, recon_type STRING, gl_total DECIMAL(22,4), pipeline_total DECIMAL(22,4),
  difference DECIMAL(22,4), difference_pct DECIMAL(9,4), status STRING, details STRING, run_timestamp TIMESTAMP
) COMMENT 'Silver totals per legal entity and FR 2052a table (USD, before elimination) vs GL control totals (raw.gl_balances); 0.5% threshold'""")
spark.sql(f"""CREATE TABLE {CATALOG}.audit.cross_metric_recon (
  as_of_date DATE, entity_id STRING, metric_name STRING, reg_2052a_value DECIMAL(22,4), reg_lcr_value DECIMAL(22,4),
  difference DECIMAL(22,4), status STRING, details STRING, run_timestamp TIMESTAMP
) COMMENT 'FR 2052a vs LCR engine consistency'""")
spark.sql(f"""CREATE TABLE {CATALOG}.audit.data_lineage (
  as_of_date DATE, pipeline_name STRING, stage STRING, source_table STRING, target_table STRING,
  records_read BIGINT, records_written BIGINT, run_timestamp TIMESTAMP
) COMMENT 'Pipeline lineage (no IDENTITY column, so parallel tasks can append)'""")
print("DQ, Silver, FR 2052a, LCR and audit tables created")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Verification

# COMMAND ----------

display(spark.sql(f"""
SELECT 'products (PIDs)' AS item, COUNT(*) AS n FROM {CATALOG}.reference.ref_product
UNION ALL SELECT 'data tables + comments', COUNT(*) FROM {CATALOG}.reference.spec_tables
UNION ALL SELECT 'table fields (incl. currency/converted)', COUNT(*) FROM {CATALOG}.reference.spec_table_fields
UNION ALL SELECT 'asset categories (Appendix III)', COUNT(*) FROM {CATALOG}.reference.ref_collateral
UNION ALL SELECT 'maturity buckets (Appendix IV-a)', COUNT(*) FROM {CATALOG}.reference.ref_maturity_bucket WHERE is_standard
UNION ALL SELECT 'counterparty types', COUNT(*) FROM {CATALOG}.reference.ref_counterparty
UNION ALL SELECT 'Fed 6G validation rules', COUNT(*) FROM {CATALOG}.reference.rules_validation
UNION ALL SELECT 'appendix rules (rules_spec)', COUNT(*) FROM {CATALOG}.reference.rules_spec
UNION ALL SELECT 'LCR rate rules', COUNT(*) FROM {CATALOG}.reference.rules_lcr_appendix_vi
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Lakebase synced tables start over
# MAGIC The incrementally synced tables (TRIGGERED: source_position, entity_position, record_lineage) read the change feed of tables this
# MAGIC notebook has just re-created - their streams must start over, so the synced-table pipeline gets a full refresh (the tables are
# MAGIC empty now, so it is quick). On the first deployment there are no synced tables yet (`deploy/lakebase_synced_tables.py` creates them).

# COMMAND ----------

import time
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
try:
    SYNC_PIPELINE = w.api_client.do("GET", f"/api/2.0/postgres/synced_tables/{CATALOG}.app_serving.source_position")["status"]["pipeline_id"]
except Exception:
    SYNC_PIPELINE = None
ACTIVE = ("CREATED", "WAITING_FOR_RESOURCES", "INITIALIZING", "RESETTING", "SETTING_UP_TABLES", "RUNNING", "STOPPING", "QUEUED")
def update(uid=None):
    if uid:
        return w.api_client.do("GET", f"/api/2.0/pipelines/{SYNC_PIPELINE}/updates/{uid}")["update"]
    ups = w.api_client.do("GET", f"/api/2.0/pipelines/{SYNC_PIPELINE}/updates", query={"max_results": 1}).get("updates", [])
    return ups[0] if ups else {}
if SYNC_PIPELINE:
    while update().get("state") in ACTIVE:
        time.sleep(15)
    uid = w.api_client.do("POST", f"/api/2.0/pipelines/{SYNC_PIPELINE}/updates", body={"full_refresh": True})["update_id"]
    while (u := update(uid)).get("state") in ACTIVE:
        time.sleep(15)
    assert u.get("state") == "COMPLETED", f"synced-table full refresh {uid} ended {u.get('state')}"
    print(f"synced-table pipeline {SYNC_PIPELINE}: full refresh {uid} completed")
else:
    print("no synced tables yet - create them with deploy/lakebase_synced_tables.py after the first build")
