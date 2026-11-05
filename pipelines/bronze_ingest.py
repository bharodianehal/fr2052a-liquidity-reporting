# Lakeflow Declarative Pipeline: FR 2052a Bronze ingestion
#
# Source-system extracts land as CSV files in the UC Volume
#   /Volumes/<catalog>/raw/landing/<feed>/<as_of_date>/*.csv
# (written by notebook 01 for the synthetic data; in production these are the core banking, loan, custody,
# trading, treasury, finance/GL and regulatory-reporting workbench feeds). Auto Loader picks up new files
# incrementally into one streaming table per feed in the `raw` schema.
#
# Expectations here are warn-only (records are kept and counted in the pipeline event log); the regulatory
# DQ gate (notebook 02) decides what is quarantined.

from pyspark import pipelines as dp
from pyspark.sql import functions as F

LANDING = spark.conf.get("fr2052a.landing_path")

# One layout for all position feeds (notebook 01 BRONZE_COLUMNS). Source systems supply their own product code, customer and
# security ids, booking legal entity and the contract terms the calculation layer needs (options, draw terms, reserve and
# operational requirements, depositor counts) - the PID and every FR 2052a classification are derived in notebook 03.
POSITION_SCHEMA = """
  record_id STRING, as_of_date DATE, booking_entity STRING, report_for_entity STRING, source_system STRING, instrument_type STRING,
  source_product_code STRING, product_subtype STRING, flow_direction STRING, customer_id STRING, collateral_id STRING,
  subsidiary_entity STRING, sub_product STRING, sub_product_2 STRING, currency STRING, currency_2 STRING,
  maturity_type STRING, maturity_date DATE, forward_start_date DATE, effective_maturity_date DATE,
  option_type STRING, option_date DATE, notice_days INT, funding_start_date DATE, funding_end_date DATE, draw_notice_days INT,
  reserve_requirement DECIMAL(22,4), service_type STRING, operational_requirement DECIMAL(22,4), depositor_count INT,
  insurance_scheme STRING, principal_amount DECIMAL(22,4), principal_amount_2 DECIMAL(22,4), forward_start_amount DECIMAL(22,4),
  forward_start_amount_2 DECIMAL(22,4), market_value DECIMAL(22,4), lendable_value DECIMAL(22,4),
  collateral_value DECIMAL(22,4), collateral_level STRING, encumbrance_type STRING, generic_issuer_type STRING, generic_product STRING,
  risk_weight DECIMAL(9,4), accounting_designation STRING, insured STRING,
  trigger_flag STRING, rehypothecated STRING, unencumbered STRING, treasury_control STRING, settlement STRING,
  netting_eligible STRING, loss_absorbency STRING, fx_option_direction STRING, collection_reference STRING,
  product_reference STRING, sub_product_reference STRING, business_line STRING, internal_rating STRING,
  interest_rate DECIMAL(8,6), link_id STRING, load_timestamp TIMESTAMP
"""
COMMENTS_SCHEMA = """
  record_id STRING, as_of_date DATE, reporting_entity STRING, collection STRING, product_id STRING,
  sub_product STRING, comments STRING, source_system STRING, load_timestamp TIMESTAMP
"""
GL_SCHEMA = """
  as_of_date DATE, legal_entity_id STRING, table_code STRING, gl_account_group STRING,
  gl_balance_usd DECIMAL(22,4), source_system STRING, load_timestamp TIMESTAMP
"""
CUSTOMER_SCHEMA = """
  as_of_date DATE, customer_id STRING, customer_name STRING, country STRING, naics_code STRING, legal_form STRING, lei STRING,
  onboarded_on DATE, source_system STRING, load_timestamp TIMESTAMP
"""
LINK_SCHEMA = """
  as_of_date DATE, record_id STRING, collateral_id STRING, collateral_amount DECIMAL(22,4), source_system STRING, load_timestamp TIMESTAMP
"""

POSITION_EXPECTATIONS = {
    "record_id_present": "record_id IS NOT NULL",
    "as_of_date_present": "as_of_date IS NOT NULL",
    "source_product_code_present": "source_product_code IS NOT NULL",
    "amount_present": "COALESCE(principal_amount, market_value) IS NOT NULL",
}

FEEDS = {
    "deposits": ("Bronze - core banking deposit extracts (FISERV_DDA)", POSITION_SCHEMA, POSITION_EXPECTATIONS),
    "loans": ("Bronze - loan and secured lending extracts (ACBS_LOANS, MUREX)", POSITION_SCHEMA, POSITION_EXPECTATIONS),
    "securities": ("Bronze - custody / securities inventory extracts (STATESTREET_CUSTODY)", POSITION_SCHEMA, POSITION_EXPECTATIONS),
    "derivatives": ("Bronze - trading, derivatives, collateral and FX extracts (MUREX, ALGO_COLLATERAL)", POSITION_SCHEMA, POSITION_EXPECTATIONS),
    "funding": ("Bronze - wholesale and secured funding extracts (QUANTUM_TREASURY, MUREX)", POSITION_SCHEMA, POSITION_EXPECTATIONS),
    "finance": ("Bronze - finance / regulatory calculation extracts (AXIOM_REGCALC, ORACLE_GL, BROKERAGE_BOOKS)", POSITION_SCHEMA, POSITION_EXPECTATIONS),
    "comments": ("Bronze - FR 2052a Comments table entries from the regulatory reporting workbench", COMMENTS_SCHEMA,
                 {"comment_present": "comments IS NOT NULL"}),
    "gl_balances": ("Bronze - GL control totals per legal entity and FR 2052a table (USD) for reconciliation", GL_SCHEMA,
                    {"balance_present": "gl_balance_usd IS NOT NULL"}),
    "customers": ("Bronze - KYC onboarding extract (customers known to the bank; classification is a steward decision)", CUSTOMER_SCHEMA,
                  {"customer_id_present": "customer_id IS NOT NULL"}),
    "collateral_links": ("Bronze - collateral placed / received per secured transaction (ALGO_COLLATERAL)", LINK_SCHEMA,
                         {"link_complete": "record_id IS NOT NULL AND collateral_id IS NOT NULL"}),
}


def make_bronze(feed: str, comment: str, schema: str, expectations: dict):
    @dp.table(
        name=feed,
        comment=comment,
        partition_cols=["as_of_date"],
        table_properties={"quality": "bronze", "fr2052a.source": feed},
    )
    @dp.expect_all(expectations)
    def _bronze():
        return (
            spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "csv")
            .option("header", "true")
            .option("escape", '"')
            .option("pathGlobFilter", "*.csv")
            .schema(schema)
            .load(f"{LANDING}/{feed}")
            .withColumn("_source_file", F.col("_metadata.file_path"))
            .withColumn("_ingested_at", F.current_timestamp())
        )


for _feed, (_comment, _schema, _expect) in FEEDS.items():
    make_bronze(_feed, _comment, _schema, _expect)
