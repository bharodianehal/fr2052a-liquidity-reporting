# Databricks notebook source
# MAGIC %md
# MAGIC # FR 2052a Validation & 6G Submission Files (v9)
# MAGIC ## Owned by: Regulatory Reporting Team
# MAGIC
# MAGIC Produces what is filed with the Federal Reserve for one as-of date and checks it the way FRS will:
# MAGIC
# MAGIC | Step | What | Source of the rules |
# MAGIC |---|---|---|
# MAGIC | 1 | Appendix rules on the data tables (Silver for the Appendix V link checks) | `reference.rules_spec` (Instructions Appendices II-V, Field Definitions) |
# MAGIC | 1b | The Fed's 14 FR 2052a **post-submission validation checks** (weekend flows, internal on consolidated, lendable > market, third-party vs consolidated, intercompany symmetry, large haircuts, ...) | `reference.rules_fed_psv` |
# MAGIC | 2 | Assign 6G `reportID`s and generate **Primary**, **Reduced** (month-end) and **Comment** XML | `reference.spec_xsd_layout` (6GSchema.xsd), firm include XSD from `reference.ref_firm_schema_values` |
# MAGIC | 3 | **XSD validation** of every file against the official 6G schemas | 6GSchema.xsd / 6GCommentSchema.xsd |
# MAGIC | 4 | The **652 Business Requirements rules** - XSD-enforced ones from step 3, FRS application rules evaluated on the XML - plus the BR General file rules (duplicate report key, file content, naming) | `reference.rules_validation` (6G BR workbook) |
# MAGIC | 5 | Release status, version, files in the Volume, review log | ERROR failures block release until fixed; otherwise the submission waits for business sign-off in the app |

# COMMAND ----------

# MAGIC %pip install lxml psycopg2-binary --quiet

# COMMAND ----------

dbutils.widgets.text("as_of_date", "2026-02-27")
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema_dir", "", "Folder with 6GSchema.xsd and 6GCommentSchema.xsd (default: <repo>/schema_6g)")
AS_OF = dbutils.widgets.get("as_of_date")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA_DIR = dbutils.widgets.get("schema_dir").strip()
# Set only by fr2052a-generate (step 5 in the app): the person who generated the files for release. Pipeline runs leave it empty -
# their files are the working copy that Validate checks; only a release generation can be approved.
dbutils.widgets.text("released_by", "")
RELEASED_BY = dbutils.widgets.get("released_by").strip().replace("'", "")

import collections, json, os, re, shutil, tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from lxml import etree
from pyspark.sql import functions as F

if not SCHEMA_DIR:
    nb_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
    SCHEMA_DIR = "/Workspace" + os.path.dirname(os.path.dirname(nb_path)) + "/schema_6g"
spark.sql(f"USE CATALOG {CATALOG}")
RUN_TS = datetime.now()
entity = spark.table(f"{CATALOG}.reference.ref_reporting_entity").where("scope_type = 'CONSOLIDATED'").first()   # the filer
firm = collections.defaultdict(list)
for r in spark.table(f"{CATALOG}.reference.ref_firm_schema_values").collect():
    firm[r.list_name].append(r.value)
TICKER, EXCHANGE = firm["reporterList"][0], firm["exchangeList"][0]
d = date.fromisoformat(AS_OF)
HOLIDAYS = {r.holiday_date for r in spark.table(f"{CATALOG}.reference.ref_bank_holidays").collect()}
nxt = d + timedelta(days=1)
while nxt.weekday() >= 5 or nxt in HOLIDAYS:
    nxt += timedelta(days=1)
IS_MONTH_END = nxt.month != d.month   # last business day of the month (weekends and Federal Reserve holidays)
CAT_I = entity.fed_category == "Category I"
print(f"{AS_OF} - {entity.entity_name} ({entity.fed_category}); reporter {TICKER}/{EXCHANGE}; month-end: {IS_MONTH_END}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Review decisions from the app
# MAGIC Sign-off actions (APPROVED / REJECTED / SUBMITTED) are recorded by the app in Lakebase; bring them into Delta first so a
# MAGIC submitted version is never overwritten - regenerating after submission creates the next version (a resubmission).

# COMMAND ----------

dbutils.widgets.text("lakebase_endpoint", "projects/fr2052a/branches/production/endpoints/primary")
dbutils.widgets.text("lakebase_db", "fr2052a")
try:
    import psycopg2
    from databricks.sdk import WorkspaceClient
    _w = WorkspaceClient()
    _ep = dbutils.widgets.get("lakebase_endpoint")
    _conn = psycopg2.connect(host=_w.api_client.do("GET", f"/api/2.0/postgres/{_ep}")["status"]["hosts"]["host"], port=5432,
                             database=dbutils.widgets.get("lakebase_db"), user=_w.current_user.me().user_name, sslmode="require",
                             password=_w.api_client.do("POST", "/api/2.0/postgres/credentials", body={"endpoint": _ep})["token"])
    with _conn.cursor() as cur:
        cur.execute("SELECT as_of_date, run_number, version, action, status, actor, note, action_timestamp FROM submission_review "
                    "WHERE as_of_date = %s AND action <> 'GENERATED'", (AS_OF,))
        app_actions = cur.fetchall()
    _conn.close()
except Exception as e:   # first run: no Lakebase table yet
    app_actions = []
    print(f"No review actions read from Lakebase ({str(e)[:120]})")
if app_actions:
    spark.createDataFrame(app_actions, "as_of_date DATE, run_number INT, version INT, action STRING, status STRING, actor STRING, note STRING, action_timestamp TIMESTAMP") \
        .createOrReplaceTempView("v_app_review")
    spark.sql(f"""MERGE INTO {CATALOG}.reg_2052a.submission_review t USING v_app_review s
                  ON t.as_of_date = s.as_of_date AND t.run_number = s.run_number AND t.action = s.action AND t.action_timestamp = s.action_timestamp
                  WHEN NOT MATCHED THEN INSERT *""")
print(f"{len(app_actions)} review action(s) from the app for {AS_OF}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Reference data

# COMMAND ----------

TABLE_ORDER = ["I.A", "I.U", "I.S", "I.O", "O.D", "O.W", "O.S", "O.O", "S.DC", "S.L", "S.B", "S.I", "S.FX"]
tables = {r.table_code: r for r in spark.table(f"{CATALOG}.reference.spec_tables").collect()}
fields = collections.defaultdict(list)
for f in spark.table(f"{CATALOG}.reference.spec_table_fields").orderBy("table_code", "seq").collect():
    fields[f.table_code].append(f)
layout = collections.defaultdict(list)
for r in spark.table(f"{CATALOG}.reference.spec_xsd_layout").orderBy("table_code", "seq").collect():
    layout[r.table_code].append(r)
products = {r.product_id: r for r in spark.table(f"{CATALOG}.reference.ref_product").collect()}
pid_by_name = {(r.table_code, r.product_name): r.product_id for r in products.values()}
buckets = {r.bucket_label: r for r in spark.table(f"{CATALOG}.reference.ref_maturity_bucket").where("is_standard").collect()}
bucket_days = lambda code: int(code[1:-1])
valid_pairs = {(b.maturity_start, b.maturity_end or None) for b in buckets.values()}
scope_of = {r.entity_id: r.report_scope for r in spark.table(f"{CATALOG}.reference.ref_reporting_entity").collect()}
br_rules = spark.table(f"{CATALOG}.reference.rules_validation").collect()
gsib_list = {r.allowed_value for r in spark.table(f"{CATALOG}.reference.spec_field_values").where("field_name = 'G-SIB'").collect()}
cp_required = {r.product_id for r in spark.table(f"{CATALOG}.reference.spec_counterparty_requirements").collect()}
coll_required = {r.product_id for r in spark.table(f"{CATALOG}.reference.spec_collateral_class_requirements").where("requirement = 'Required'").collect()}
subproducts = collections.defaultdict(set)
for r in spark.table(f"{CATALOG}.reference.spec_subproducts").collect():
    subproducts[(r.product_id, r.field_name)].add(r.allowed_value)
NSFR = {"S.L.7", "S.L.8", "S.L.9", "S.L.10"}
def is_reduced(pid):
    """6G BR General #3-5: the Reduced file has the S.L NSFR products and S.B (except S.B.5 for Category I firms)."""
    return pid in NSFR or (pid.startswith("S.B.") and not (CAT_I and pid == "S.B.5"))
gold = {code: tables[code].gold_table for code in TABLE_ORDER + ["S.C"]}
RT = {code: tables[code].xml_report_type for code in TABLE_ORDER}
CODE_OF_RT = {v: k for k, v in RT.items()}

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Appendix rules (`reference.rules_spec`)

# COMMAND ----------

results, details = [], []

def record(rule_id, source, appendix, table_code, name, category, severity, checked, failures, status=None, note=None):
    """failures: list of (table_code, record_key, product_id, detail)."""
    st = status or ("PASS" if not failures else ("FAIL" if severity == "ERROR" else "WARNING"))
    sample = "; ".join(sorted({f[3] for f in failures if f[3]})[:5]) or note
    results.append((date.fromisoformat(AS_OF), entity.entity_id, rule_id, source, appendix, table_code, name[:500], category, severity, st,
                    int(checked), len(failures), (sample or "")[:1000], RUN_TS))
    for t, key, pid, det in failures[:500]:
        details.append((date.fromisoformat(AS_OF), t, key, pid, rule_id, source, (det or "")[:500], RUN_TS))

def g(code):
    return f"{CATALOG}.reg_2052a.{gold[code]}"

def rows_failing(code, predicate, detail_sql="''", joins=""):
    q = f"SELECT g.record_key, g.product_id, {detail_sql} AS detail FROM {g(code)} g {joins} WHERE g.as_of_date = '{AS_OF}' AND ({predicate})"
    return [(code, r.record_key, r.product_id, r.detail) for r in spark.sql(q).collect()]

def sql_list(values):
    return "(" + ", ".join("'" + str(v).replace("'", "''") + "'" for v in values) + ")" if values else "(NULL)"

table_rows = {code: spark.sql(f"SELECT COUNT(*) AS n FROM {g(code)} WHERE as_of_date = '{AS_OF}'").first().n for code in TABLE_ORDER}
table_rows["S.C"] = spark.sql(f"SELECT COUNT(*) AS n FROM {CATALOG}.reg_2052a.s_c_comments WHERE as_of_date = '{AS_OF}'").first().n
native = [r.currency_code for r in spark.table(f"{CATALOG}.reference.ref_fx_rates").where("is_fr2052a_currency").collect()]
labels = list(buckets)
SUBSIDIARY_PRODUCTS = ("S.L.1", "S.L.2", "S.L.7", "S.L.8", "S.I.5", "S.I.6")

def check_spec(r, code, p):
    ct = r.check_type
    if ct == "MANDATORY_FIELD":
        return rows_failing(code, f"g.{p['column']} IS NULL", f"'{p['field']} missing'")
    if ct == "CONVERTED_CURRENCY":
        out = []
        for c in p["currency_columns"]:
            conv = "g.converted_2" if c == "currency_2" else "g.converted"
            out += rows_failing(code, f"({conv} AND g.{c} <> 'USD') OR g.{c} NOT IN {sql_list(native)}", f"CONCAT('{c} ', g.{c})")
        return out
    if ct == "FIELD_DOMAIN":
        vals = [v.allowed_value for v in spark.table(f"{CATALOG}.reference.spec_field_values")
                .where(f"field_name = '{p['field']}' AND table_scope = '{p['scope']}'").collect()]
        return rows_failing(code, f"g.{p['column']} IS NOT NULL AND g.{p['column']} NOT IN {sql_list(vals)}", f"CONCAT('{p['field']} = ', g.{p['column']})")
    if ct == "REFERENCE_VALUE":
        rt, rc = p["reference"].split(".")
        where = f" WHERE {p['where']}" if p.get("where") else ""
        return rows_failing(code, f"g.{p['column']} IS NOT NULL AND g.{p['column']} NOT IN (SELECT {rc} FROM {CATALOG}.reference.{rt}{where})",
                            f"CONCAT('{p['column']} = ', g.{p['column']})")
    if ct == "PRODUCT_IN_TABLE":
        if code == "S.C":   # a comment's product belongs to the table named in its Collection field
            return rows_failing(code, f"g.product_id IS NOT NULL AND g.product_id NOT IN (SELECT product_id FROM {CATALOG}.reference.ref_product p WHERE p.table_code = g.collection)",
                                "CONCAT(g.product_id, ' not in ', g.collection)")
        return rows_failing(code, f"g.product_id NOT IN (SELECT product_id FROM {CATALOG}.reference.ref_product WHERE table_code = '{code}')")
    if ct == "BUCKET_VALUE":
        return rows_failing(code, f"g.{p['column']} IS NOT NULL AND g.{p['column']} NOT IN {sql_list(labels)}", f"g.{p['column']}")
    if ct == "MATURITY_TAILORING":
        scope = "INFLOW" if code.startswith("I.") else "OUTFLOW_SUPPLEMENTAL"
        out = []
        for c in p["columns"]:
            out += rows_failing(code, f"""g.{c} IS NOT NULL AND g.{c} NOT IN (SELECT bucket_label FROM {CATALOG}.reference.spec_maturity_tailoring
                WHERE profile_code = '{entity.tailoring_profile}' AND (product_scope IN ('ALL', '{scope}') OR ARRAY_CONTAINS(SPLIT(product_scope, ','), g.product_id)))""",
                                f"CONCAT('{c} ', g.{c})")
        return out
    if ct == "SUBPRODUCT":
        out = []
        for col, field, has in (("sub_product", "Sub-Product", p["has_sub"]), ("sub_product_2", "Sub-Product2", p["has_sub2"])):
            if has:
                out += rows_failing(code, f"""g.{col} IS NOT NULL AND (g.product_id, g.{col}) NOT IN
                    (SELECT product_id, allowed_value FROM {CATALOG}.reference.spec_subproducts WHERE field_name = '{field}')""",
                                    f"CONCAT('{field} ', g.{col})")
        return out
    if ct == "SUBPRODUCT_REQUIRED":
        return rows_failing(code, f"""g.sub_product IS NULL AND g.product_id IN
            (SELECT product_id FROM {CATALOG}.reference.spec_subproducts WHERE required_by_instructions)""", "'Sub-Product missing'")
    if ct == "COUNTERPARTY_REQ":
        return rows_failing(code, f"""g.product_id IN (SELECT product_id FROM {CATALOG}.reference.spec_counterparty_requirements) AND (g.counterparty IS NULL
            OR (g.product_id, g.counterparty) NOT IN (SELECT product_id, counterparty FROM {CATALOG}.reference.spec_counterparty_requirements
                                                      WHERE applicability = 'Applicable'))""", "CONCAT('Counterparty ', COALESCE(g.counterparty, 'missing'))")
    if ct == "COLLATERAL_REQ":
        return rows_failing(code, f"g.collateral_class IS NULL AND g.product_id IN {sql_list(sorted(coll_required))}", "'Collateral Class missing'")
    if ct == "FORWARD_START_EXCL":
        return rows_failing(code, f"""g.product_id IN (SELECT product_id FROM {CATALOG}.reference.spec_forward_start_exclusions)
            AND ({' OR '.join(f'g.{c} IS NOT NULL' for c in p['columns'])})""", "'Forward Start reported for an excluded product'")
    if ct == "FORWARD_START_PAIR":
        return rows_failing(code, f"(g.{p['amount']} IS NULL) <> (g.forward_start_bucket IS NULL)", "'Forward Start Amount / Bucket not paired'")
    if ct == "FORWARD_BEFORE_MATURITY":
        return rows_failing(code, "mf.bucket_seq > mm.bucket_seq", "CONCAT(g.forward_start_bucket, ' after ', g.maturity_bucket)",
                            f"""JOIN {CATALOG}.reference.ref_maturity_bucket mf ON mf.bucket_label = g.forward_start_bucket
                                JOIN {CATALOG}.reference.ref_maturity_bucket mm ON mm.bucket_label = g.maturity_bucket""")
    if ct == "INTERNAL_COUNTERPARTY":
        return rows_failing(code, f"""(g.internal AND g.internal_counterparty IS NULL)
            OR (NOT g.internal AND g.internal_counterparty IS NOT NULL AND g.product_id NOT IN {sql_list(SUBSIDIARY_PRODUCTS)})""",
                            "CONCAT('internal ', g.internal, ' / ', COALESCE(g.internal_counterparty, 'none'))")
    if ct == "GSIB_WITH_COUNTERPARTY":
        return rows_failing(code, "g.gsib IS NOT NULL AND g.counterparty IS NULL", "CONCAT('G-SIB ', g.gsib)")
    if ct == "RISK_WEIGHT_RANGE":
        return rows_failing(code, "g.risk_weight < 0 OR g.risk_weight > 12.5", "CAST(g.risk_weight AS STRING)")
    if ct == "MIN_AMOUNT":
        return rows_failing(code, f"ABS(ROUND(COALESCE(g.{p['column']}, 0), 2)) < 0.01 AND g.product_id NOT IN ('S.L.6', 'S.L.10')",
                            f"CAST(g.{p['column']} AS STRING)")
    if ct == "FIELD_PRODUCT_SCOPE":
        allowed = p.get("allowed_elsewhere") or []
        extra = f" AND g.{p['column']} NOT IN {sql_list(allowed)}" if allowed else ""
        return rows_failing(code, f"g.{p['column']} IS NOT NULL AND g.product_id NOT IN {sql_list(p['products'])}{extra}", f"g.{p['column']}")
    if ct == "SINGLE_USD_VALUE":
        out = rows_failing(code, f"g.product_id IN {sql_list(p['products'])} AND g.currency <> 'USD'", "'not USD'")
        for x in spark.sql(f"""SELECT reporting_entity, product_id, COUNT(*) AS n FROM {g(code)} WHERE as_of_date = '{AS_OF}'
                               AND product_id IN {sql_list(p['products'])} GROUP BY reporting_entity, product_id HAVING COUNT(*) > 1""").collect():
            out.append((code, None, x.product_id, f"{x.reporting_entity}: {x.n} records"))
        return out
    if ct == "RATIO_PRECISION":
        return rows_failing(code, f"g.product_id IN {sql_list(p['products'])} AND g.market_value <> ROUND(g.market_value, 4)", "CAST(g.market_value AS STRING)")
    if ct == "PRODUCT_PRESENT":
        if (p.get("entity_flag") and not getattr(entity, p["entity_flag"])) or (p.get("entity_category") and entity.fed_category != p["entity_category"]):
            return None
        have = {x.product_id for x in spark.sql(f"SELECT DISTINCT product_id FROM {g(code)} WHERE as_of_date = '{AS_OF}'").collect()}
        return [(code, None, pid, f"{pid} not reported") for pid in p["products"] if pid not in have]
    if ct == "SUBSIDIARY_INTERNAL":
        return rows_failing(code, f"g.product_id IN {sql_list(p['products'])} AND (g.internal_counterparty IS NULL OR g.internal)",
                            "CONCAT('internal ', g.internal, ' / ', COALESCE(g.internal_counterparty, 'none'))")
    if ct == "SB5_NETTING":
        out = rows_failing(code, "g.product_id = 'S.B.5' AND g.market_value >= 0", "'S.B.5 not negative'")
        n = spark.sql(f"SELECT COUNT(DISTINCT collection_reference) AS n FROM {g(code)} WHERE as_of_date = '{AS_OF}' AND product_id = 'S.B.5'").first().n
        if 0 < n < 2:
            out.append((code, None, "S.B.5", "S.B.5 reported for one side only"))
        return out
    if ct == "MONTH_END_PRODUCTS":
        have = {x.product_id for x in spark.sql(f"SELECT DISTINCT product_id FROM {g('S.B')} WHERE as_of_date = '{AS_OF}' UNION SELECT DISTINCT product_id FROM {g('S.L')} WHERE as_of_date = '{AS_OF}'").collect()}
        if IS_MONTH_END:
            return [(code, None, pid, f"{pid} missing at month-end") for pid in p["products"] if pid not in have]
        return [(code, None, pid, f"{pid} reported on a non month-end date") for pid in p["products"] if pid in have]
    if ct == "FX_CURRENCY_PAIR":
        return rows_failing(code, "g.currency_1 = g.currency_2 AND NOT g.converted AND NOT g.converted_2", "CONCAT(g.currency_1, '/', g.currency_2)")
    if ct == "OTHER_HAS_COMMENT":
        out = []
        for c in TABLE_ORDER:
            cols = {f.column_name for f in fields[c]}
            conds = [f"g.{x} = 'Other'" for x in ("counterparty", "encumbrance_type") if x in cols]
            if conds:
                out += rows_failing(c, f"({' OR '.join(conds)}) AND g.product_id NOT IN (SELECT product_id FROM {CATALOG}.reg_2052a.s_c_comments "
                                       f"WHERE as_of_date = '{AS_OF}' AND product_id IS NOT NULL)", "'Other without a comment'")
        return out
    raise NotImplementedError(ct)

# ---- Appendix V double counting: the linked positions are compared in Silver, where each position keeps its link ids ----
spark.sql(f"""CREATE OR REPLACE TEMP VIEW v_links AS
SELECT f.record_id, f.product_id, f.maturity_bucket, f.unencumbered, EXPLODE(SPLIT(f.link_id, '[|]')) AS link
FROM {CATALOG}.conformed.fact_liquidity_position f WHERE f.as_of_date = '{AS_OF}' AND f.link_id IS NOT NULL""")
silver_view = f"(SELECT * FROM {CATALOG}.conformed.fact_liquidity_position WHERE as_of_date = '{AS_OF}')"

def net30_difference():
    q = f"""WITH s AS (SELECT f.*, COALESCE(fx.rate_to_usd, 1) AS r1, COALESCE(fx2.rate_to_usd, 1) AS r2,
                         COALESCE(mb.is_within_30d, true) AS mat30, COALESCE(fb.is_within_30d, false) AS fwd30
                  FROM {silver_view} f
                  LEFT JOIN {CATALOG}.reference.ref_fx_rates fx ON fx.currency_code = f.currency
                  LEFT JOIN {CATALOG}.reference.ref_fx_rates fx2 ON fx2.currency_code = f.currency_2
                  LEFT JOIN {CATALOG}.reference.ref_maturity_bucket mb ON mb.bucket_label = f.maturity_bucket
                  LEFT JOIN {CATALOG}.reference.ref_maturity_bucket fb ON fb.bucket_label = f.forward_start_bucket)
    SELECT
      SUM(CASE WHEN product_id IN ('I.O.1', 'I.O.2') AND mat30 THEN principal_amount * r1
               WHEN product_id IN ('O.O.1', 'O.O.2') AND mat30 THEN -principal_amount * r1
               WHEN product_id = 'I.A.6' AND fwd30 THEN -forward_start_amount * r1
               WHEN product_id = 'O.S.8' AND sub_product = 'Unsettled - Forward' AND fwd30 THEN forward_start_amount * r1 ELSE 0 END)
      + SUM(CASE WHEN product_id LIKE 'S.FX.%' AND maturity_date IS NOT NULL AND DATEDIFF(maturity_date, as_of_date) <= 30
                 THEN COALESCE(principal_amount, 0) * r1 - COALESCE(principal_amount_2, 0) * r2 ELSE 0 END)
      + SUM(CASE WHEN product_id LIKE 'S.FX.%' AND forward_start_date IS NOT NULL AND DATEDIFF(forward_start_date, as_of_date) <= 30
                 THEN COALESCE(forward_start_amount_2, 0) * r2 - COALESCE(forward_start_amount, 0) * r1 ELSE 0 END) AS expected,
      SUM(CASE WHEN product_id = 'I.O.7' THEN principal_amount WHEN product_id = 'O.O.20' THEN -principal_amount ELSE 0 END) AS reported
    FROM s"""
    r = spark.sql(q).first()
    return float(r.expected or 0), float(r.reported or 0)

def check_double_count(r, p):
    ct, a, b, cmp = r.check_type, p["products_a"], p["products_b"], p.get("comparison")
    if ct == "DOUBLE_COUNT_ENTITY":   # every third-party position of a subsidiary reporting entity is also in the consolidated report
        rows = spark.sql(f"""
          SELECT s.reporting_entity, s.position_id, f.product_id, c.relationship AS consolidated_as
          FROM {CATALOG}.conformed.entity_position s
          JOIN {CATALOG}.reference.ref_reporting_entity re ON re.entity_id = s.reporting_entity AND re.scope_type = 'SOLO'
          JOIN {CATALOG}.conformed.fact_liquidity_position f ON f.as_of_date = s.as_of_date AND f.position_id = s.position_id
          LEFT JOIN (SELECT e.* FROM {CATALOG}.conformed.entity_position e JOIN {CATALOG}.reference.ref_reporting_entity r
                     ON r.entity_id = e.reporting_entity AND r.scope_type = 'CONSOLIDATED') c
            ON c.as_of_date = s.as_of_date AND c.position_id = s.position_id
          WHERE s.as_of_date = '{AS_OF}' AND s.relationship = 'EXTERNAL'
            AND f.report_for_entity IS NULL   -- entity-specific measures (e.g. a solo entity's S.L ratios) are not third-party exposures""").collect()
        fails = [("ALL", x.position_id, x.product_id, f"{x.reporting_entity} {x.position_id} third-party, but {x.consolidated_as or 'missing'} in the consolidated report")
                 for x in rows if x.consolidated_as != "EXTERNAL"]
        return None, fails, f"{len(rows)} subsidiary third-party positions checked"
    if ct == "DOUBLE_COUNT_LINKED":
        open_only = " AND f.maturity_bucket = 'Open'" if cmp == "OPEN" else ""
        tagged = " AND f.link_id IS NOT NULL" if cmp == "TAGGED" else ""
        q = f"""SELECT f.record_id, f.product_id, f.unencumbered,
                       EXISTS (SELECT 1 FROM v_links la JOIN v_links lb ON lb.link = la.link
                               WHERE la.record_id = f.record_id AND lb.product_id IN {sql_list(b)}) AS linked
                FROM {silver_view} f WHERE f.product_id IN {sql_list(a)}{open_only}{tagged}"""
        rows = spark.sql(q).collect()
        if cmp == "TAGGED":   # only the positions actually linked to products_b are in scope; they must be Unencumbered = false
            fails = [("ALL", x.record_id, x.product_id, f"{x.record_id} pre-positioned at {','.join(b)} but Unencumbered = true")
                     for x in rows if x.linked and x.unencumbered]
        else:
            fails = [("ALL", x.record_id, x.product_id, f"{x.record_id} not linked to {','.join(b)}") for x in rows if not x.linked]
        return None, fails, f"{len(rows)} positions checked"
    if ct == "DOUBLE_COUNT_NET30":
        exp, rep = net30_difference()
        ok = abs(exp - rep) < 0.01
        return None, [] if ok else [("ALL", None, "I.O.7/O.O.20", f"net 30-day derivative {rep:,.2f} vs flows {exp:,.2f}")], f"net {rep:,.2f}"
    totals = {x.product_id: float(x.v) for x in spark.sql(f"""SELECT product_id, SUM(COALESCE(principal_amount, market_value, 0)) AS v
              FROM {silver_view} WHERE product_id IN {sql_list(a + b)} GROUP BY product_id""").collect()}
    if ct == "DOUBLE_COUNT_MONOTONIC":
        vals = [totals.get(x, 0.0) for x in a]
        bad = [f"{a[i]} {vals[i]:,.1f} > {a[i + 1]} {vals[i + 1]:,.1f}" for i in range(len(vals) - 1) if vals[i] > vals[i + 1] + 0.005]
        return None, [("ALL", None, None, m) for m in bad], " <= ".join(f"{v:,.0f}" for v in vals)
    if ct == "DOUBLE_COUNT_SUBSET":
        sa, sb = sum(totals.get(x, 0.0) for x in a), sum(totals.get(x, 0.0) for x in b)
        return None, [] if sa <= sb + 0.005 else [("ALL", None, None, f"{','.join(a)} {sa:,.1f} > {','.join(b)} {sb:,.1f}")], f"{sa:,.1f} <= {sb:,.1f}"
    raise NotImplementedError(ct)

for r in spark.table(f"{CATALOG}.reference.rules_spec").orderBy("rule_id").collect():
    p = json.loads(r.params)
    if r.check_type.startswith("DOUBLE_COUNT_"):
        status, fails, note = check_double_count(r, p)
        record(r.rule_id, "Instructions", r.appendix, r.table_code, r.rule_name, r.check_type, r.severity, len(fails) or 1, fails, status, note)
        continue
    code = r.table_code
    fails = check_spec(r, code, p)
    if fails is None:
        record(r.rule_id, "Instructions", r.appendix, code, r.rule_name, r.check_type, r.severity, 0, [], "NOT_APPLICABLE", "Not applicable to the reporting entity")
    else:
        record(r.rule_id, "Instructions", r.appendix, code, r.rule_name, r.check_type, r.severity, table_rows.get(code, 0), fails)
spec_fail = sum(1 for x in results if x[9] == "FAIL")
print(f"Appendix rules: {len(results)} evaluated, {spec_fail} FAIL, {sum(1 for x in results if x[9] == 'WARNING')} WARNING")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1b. Fed FR 2052a post-submission validation checks (14)
# MAGIC The checks the Federal Reserve runs on every received FR 2052a submission (`reference.rules_fed_psv`), run here before
# MAGIC filing on the records as filed and on the reporting-entity positions behind them.

# COMMAND ----------

psv = {r.check_no: r for r in spark.table(f"{CATALOG}.reference.rules_fed_psv").collect()}
entities = {r.entity_id: r for r in spark.table(f"{CATALOG}.reference.ref_reporting_entity").collect()}
legal = {r.legal_entity_id: r.legal_name for r in spark.table(f"{CATALOG}.reference.ref_legal_entity").collect()}
EPV = f"(SELECT * FROM {CATALOG}.conformed.v_entity_position WHERE as_of_date = '{AS_OF}')"
CONSOL = [e for e, r in entities.items() if r.scope_type == "CONSOLIDATED"]
psv_checked = sum(v for k, v in table_rows.items() if k != "S.C")

def psv_record(no, failures, checked=None, note=None):
    c = psv[no]
    record(c.check_id, "Fed PSV", c.approach, "ALL", c.check_name, f"PSV-{no:02d}", c.severity,
           psv_checked if checked is None else checked, failures, None, note)

def across_tables(predicate, detail, cols_needed=(), tables_=None):
    out = []
    for code in tables_ or TABLE_ORDER:
        cols = {f.column_name for f in fields[code]}
        if all(c in cols for c in cols_needed):
            out += rows_failing(code, predicate, detail)
    return out

# 1 weekend maturities (positions behind the records)
rows_ = spark.sql(f"""SELECT reporting_entity, table_code, product_id, position_id, maturity_date FROM {EPV} WHERE weekend_flow""").collect()
psv_record(1, [(r.table_code, None, r.product_id, f"{r.reporting_entity} {r.position_id} flows on {r.maturity_date} (weekend or bank holiday)") for r in rows_])
# 2 internal on the consolidated entity
psv_record(2, across_tables(f"g.internal AND g.reporting_entity IN {sql_list(CONSOL)}", "CONCAT(g.reporting_entity, ' internal with ', COALESCE(g.internal_counterparty, '?'))", ("internal",)))
# 3 internal without internal counterparty
psv_record(3, across_tables("g.internal AND g.internal_counterparty IS NULL", "CONCAT(g.reporting_entity, ' internal without counterparty')", ("internal", "internal_counterparty")))
# 4 lendable value above market value
psv_record(4, rows_failing("I.A", "g.lendable_value > g.market_value", "CONCAT(g.reporting_entity, ' lendable ', g.lendable_value, ' > market ', g.market_value)"))
# 5 third-party exposures: first-tier reporting entities + non-reporting legal entities = consolidated
reporting_roots = {r.root_legal_entity_id for r in entities.values() if r.scope_type == "SOLO"}
third = spark.sql(f"""SELECT reporting_entity, booking_entity,
       SUM(COALESCE(principal_amount, 0)) AS maturity_v, SUM(COALESCE(collateral_value, 0)) AS collateral_v,
       SUM(COALESCE(lendable_value, 0)) AS lendable_v, SUM(COALESCE(market_value, 0)) AS market_v
FROM {EPV} WHERE relationship = 'EXTERNAL' AND report_for_entity IS NULL GROUP BY ALL""").collect()
fails5 = []
for cons in CONSOL:
    for m in ("maturity_v", "collateral_v", "lendable_v", "market_v"):
        c_total = sum(getattr(r, m) or 0 for r in third if r.reporting_entity == cons)
        parts_total = sum(getattr(r, m) or 0 for r in third if r.reporting_entity != cons and r.reporting_entity not in CONSOL) + \
                      sum(getattr(r, m) or 0 for r in third if r.reporting_entity == cons and r.booking_entity not in reporting_roots)
        if abs(float(c_total) - float(parts_total)) > 0.01:
            fails5.append(("ALL", None, None, f"{m}: consolidated {float(c_total):,.2f} vs first-tier + other {float(parts_total):,.2f}"))
psv_record(5, fails5, checked=4 * len(CONSOL))
# 6 symmetry of intercompany transactions between reporting entities (unsecured and secured groupings)
sym = spark.sql(f"""SELECT reporting_entity, internal_counterparty,
       SUM(CASE WHEN table_code = 'I.U' THEN principal_amount END) AS unsec_in, SUM(CASE WHEN table_code IN ('O.W', 'O.D') THEN principal_amount END) AS unsec_out,
       SUM(CASE WHEN table_code = 'I.S' THEN principal_amount END) AS sec_in, SUM(CASE WHEN table_code = 'O.S' THEN principal_amount END) AS sec_out
FROM {EPV} WHERE internal GROUP BY ALL""").collect()
name_of = {e: legal[r.root_legal_entity_id] for e, r in entities.items() if r.scope_type == "SOLO"}
fails6, pairs = [], 0
for a_ent, a_name in name_of.items():
    for b_ent, b_name in name_of.items():
        if a_ent >= b_ent:
            continue
        ab = next((r for r in sym if r.reporting_entity == a_ent and r.internal_counterparty == b_name), None)
        ba = next((r for r in sym if r.reporting_entity == b_ent and r.internal_counterparty == a_name), None)
        if not ab and not ba:
            continue
        pairs += 1
        v = lambda r, k: float(getattr(r, k) or 0) if r else 0.0
        for grp, x_in, x_out in (("unsecured", "unsec_in", "unsec_out"), ("secured", "sec_in", "sec_out")):
            for src, dst, s_name, d_name in ((ab, ba, a_ent, b_ent), (ba, ab, b_ent, a_ent)):
                if abs(v(src, x_in) - v(dst, x_out)) > 0.01:
                    fails6.append(("ALL", None, None, f"{grp}: {s_name} internal inflows {v(src, x_in):,.2f} vs {d_name} internal outflows {v(dst, x_out):,.2f}"))
psv_record(6, sorted(set(fails6)), checked=pairs)
# 7 large haircuts on secured transactions
psv_record(7, across_tables("g.maturity_amount > 0 AND g.collateral_value IS NOT NULL AND ABS(1 - g.collateral_value / g.maturity_amount) > 0.5",
                            "CONCAT(g.reporting_entity, ' haircut ', ROUND(100 * (1 - g.collateral_value / g.maturity_amount), 1), '%')",
                            ("maturity_amount", "collateral_value"), ["I.S", "O.S"]))
# 8 mismatched currency reporting (converted values must be USD; currencies one of the 6G currencies)
psv_record(8, across_tables(f"(g.converted AND g.currency <> 'USD') OR g.currency NOT IN {sql_list(native)}", "CONCAT(g.reporting_entity, ' ', g.currency)", ("currency", "converted")))
# 9 missing required products by entity type
exp = spark.table(f"{CATALOG}.reference.ref_expected_products").collect()
have = {(r.reporting_entity, r.product_id) for r in spark.sql(f"SELECT DISTINCT reporting_entity, product_id FROM {CATALOG}.reg_2052a.v_filing_records WHERE as_of_date = '{AS_OF}'").collect()}
fails9 = [("ALL", None, x.product_id, f"{e} ({r.entity_type}) does not report {x.product_id}") for e, r in entities.items()
          for x in exp if x.entity_type == r.entity_type and (e, x.product_id) not in have
          and not (x.product_id == "S.L.6" and not r.lcr_standalone)]
psv_record(9, fails9, checked=len([1 for e, r in entities.items() for x in exp if x.entity_type == r.entity_type]))
# 10 improper intra-entity consolidation: Internal Counterparty = the reporting entity itself
own = " OR ".join(f"(g.reporting_entity = '{e}' AND g.internal_counterparty = '{legal[r.root_legal_entity_id]}')" for e, r in entities.items())
psv_record(10, across_tables(f"g.internal AND ({own})", "CONCAT(g.reporting_entity, ' internal with itself')", ("internal", "internal_counterparty")))
# 11 duplicate records (same report key twice)
dups = []
for code in TABLE_ORDER:
    for x in spark.sql(f"SELECT record_key, COUNT(*) AS n FROM {g(code)} WHERE as_of_date = '{AS_OF}' GROUP BY record_key HAVING COUNT(*) > 1").collect():
        dups.append((code, x.record_key, None, f"{x.n} records share a report key"))
psv_record(11, dups)
# 12 invalid or missing counterparty
cp_fail = []
for code in TABLE_ORDER:
    if "counterparty" in {f.column_name for f in fields[code]}:
        cp_fail += rows_failing(code, f"""g.product_id IN (SELECT product_id FROM {CATALOG}.reference.spec_counterparty_requirements)
            AND (g.counterparty IS NULL OR (g.product_id, g.counterparty) NOT IN (SELECT product_id, counterparty FROM {CATALOG}.reference.spec_counterparty_requirements
                 WHERE applicability = 'Applicable'))""", "CONCAT(g.reporting_entity, ' counterparty ', COALESCE(g.counterparty, 'missing'))")
psv_record(12, cp_fail)
# 13 collateral class missing where required, or reported where not applicable
na = sorted(r.product_id for r in spark.table(f"{CATALOG}.reference.spec_collateral_class_requirements").where("requirement = 'Not Applicable'").collect())
psv_record(13, across_tables(f"(g.collateral_class IS NULL AND g.product_id IN {sql_list(sorted(coll_required))}) OR (g.collateral_class IS NOT NULL AND g.product_id IN {sql_list(na)})",
                             "CONCAT(g.reporting_entity, ' collateral ', COALESCE(g.collateral_class, 'missing'))", ("collateral_class",)))
# 14 large Other product or counterparty balance (>= USD 1bn per legal entity)
OTHER_PIDS = ("I.O.9", "O.O.22", "O.W.19", "O.S.11", "O.D.15", "I.U.8", "S.B.4")
big = spark.sql(f"""SELECT reporting_entity, table_code, product_id, counterparty, SUM(reported_amount_usd) AS usd FROM {CATALOG}.reg_2052a.v_filing_records
                    WHERE as_of_date = '{AS_OF}' AND (counterparty = 'Other' OR product_id IN {sql_list(OTHER_PIDS)}) GROUP BY ALL HAVING SUM(reported_amount_usd) >= 1000""").collect()
psv_record(14, [(r.table_code, None, r.product_id, f"{r.reporting_entity} {r.product_id} counterparty {r.counterparty}: USD {r.usd:,.0f} mm") for r in big])
print(f"Fed PSV: {sum(1 for x in results if x[3] == 'Fed PSV' and x[9] != 'PASS')} of 14 checks not passing")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1c. Reconciliations (built by notebook 05) as rules, so every check is worked in one place
# MAGIC * **RECON-GL** - each GL account group vs the filing by legal entity and table (tolerance 0.5%). WARNING: a break is explained
# MAGIC   (or fixed at source) before release; it does not block the file.
# MAGIC * **RECON-LCR** - the reported S.L.6 and the HQLA-eligible I.A vs the LCR engine. ERROR: the report must tie to the LCR.

# COMMAND ----------

gl = spark.sql(f"""SELECT entity_id, recon_type, gl_total, pipeline_total, difference_pct, status, details FROM {CATALOG}.audit.gl_reconciliation
                    WHERE as_of_date = '{AS_OF}'""").collect()
record("RECON-GL", "Reconciliation", None, None, "General ledger vs the filing, by legal entity and table (tolerance 0.5%)", "Reconciliation", "WARNING", len(gl),
       [(r.recon_type.split(' ')[-1], None, None, f"{r.recon_type}: GL {float(r.gl_total):,.1f} vs filing {float(r.pipeline_total):,.1f} USD mm "
         f"({float(r.difference_pct):+.2f}%) - {r.details}") for r in gl if r.status != "PASS"])
xm = spark.sql(f"""SELECT entity_id, metric_name, reg_lcr_value, reg_2052a_value, status FROM {CATALOG}.audit.cross_metric_recon
                    WHERE as_of_date = '{AS_OF}'""").collect()
record("RECON-LCR", "Reconciliation", None, "S.L", "FR 2052a vs the LCR engine (reported S.L.6 and HQLA-eligible I.A)", "Reconciliation", "ERROR", len(xm),
       [("S.L", None, "S.L.6", f"{r.entity_id} {r.metric_name}: LCR engine {r.reg_lcr_value} vs filing {r.reg_2052a_value}") for r in xm if r.status != "PASS"])
print(f"Reconciliations: {sum(1 for r in gl if r.status != 'PASS')} GL break(s), {sum(1 for r in xm if r.status != 'PASS')} LCR break(s)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. reportIDs and the 6G XML files

# COMMAND ----------

def gold_rows(code):
    return [x.asDict() for x in spark.sql(f"SELECT * FROM {g(code)} WHERE as_of_date = '{AS_OF}' ORDER BY product_id, record_key").collect()]

# reportID: unique per report type within each file (6G BR General #21), restarting at 1 in each file
report_ids = {}
for code in TABLE_ORDER:
    seq = collections.Counter()
    pid_num = lambda pid: int(pid.rsplit(".", 1)[1])
    for row in sorted(gold_rows(code), key=lambda x: (pid_num(x["product_id"]), x["record_key"])):
        ftype = "Reduced" if is_reduced(row["product_id"]) else "Primary"
        seq[ftype] += 1
        report_ids[(code, row["record_key"])] = (ftype, seq[ftype])
    if seq:
        ids = spark.createDataFrame([(k[1], v[1]) for k, v in report_ids.items() if k[0] == code], "record_key STRING, report_id INT")
        ids.createOrReplaceTempView("v_ids")
        spark.sql(f"""MERGE INTO {g(code)} t USING v_ids s ON t.as_of_date = '{AS_OF}' AND t.record_key = s.record_key
                      WHEN MATCHED THEN UPDATE SET t.report_id = s.report_id""")

col_of = {}
for code in TABLE_ORDER:
    for f in fields[code]:
        if f.xml_element not in ("unit", "converted"):
            col_of[(code, f.xml_element)] = f.column_name

def fmt_amount(v):
    return f"{Decimal(str(v)).quantize(Decimal('0.00000001')):f}"

def fmt_decimal(v):
    return f"{Decimal(str(v)).normalize():f}"

xml_issues = collections.Counter()

def to_xml(code, row, report_id):
    el = etree.Element(RT[code], reportID=str(report_id))
    for x in layout[code]:
        if x.xml_kind != "attribute" or x.xml_name == "reportID":
            continue
        v = row.get(col_of.get((code, x.xml_name)))
        if v is None:
            if x.xsd_required:
                xml_issues[f"{code} {x.xml_name} required attribute missing -> false"] += 1
                el.set(x.xml_name, "false")
            continue
        el.set(x.xml_name, ("true" if v else "false") if x.value_kind == "boolean" else str(v))
    for x in layout[code]:
        if x.xml_kind != "element" or x.xml_name == "comment":
            continue
        if x.xml_name == "reportScope":
            etree.SubElement(el, "reportScope").text = scope_of[row["reporting_entity"]]
            continue
        col = col_of[(code, x.xml_name)]
        v = row.get(col)
        if v is None:
            if x.xsd_required:
                xml_issues[f"{code} {x.xml_name} required element missing"] += 1
            continue
        if x.value_kind in ("amount", "signed_amount"):
            target = x.xml_name.startswith("target")
            unit = row["currency_2"] if target else row.get("currency_1", row.get("currency"))
            conv = row.get("converted_2") if target else row["converted"]
            if row["product_id"] in ("S.L.6", "S.L.10"):
                unit, conv = "USD", False   # ratios: unit attributes are ignored by FRS (6G BR)
            c = etree.SubElement(el, x.xml_name, converted="true" if conv else "false", unit=unit, unitMultiplier="6")
            c.text = fmt_amount(v)
        elif x.value_kind == "bucket":
            b = buckets[v]
            c = etree.SubElement(el, x.xml_name)
            etree.SubElement(c, "maturityStart").text = b.maturity_start
            if b.maturity_end:
                etree.SubElement(c, "maturityEnd").text = b.maturity_end
        elif col == "product_id":
            etree.SubElement(el, x.xml_name).text = products[v].product_name
        elif col == "product_reference":
            etree.SubElement(el, x.xml_name).text = products[v].product_name
        elif x.value_kind == "decimal":
            etree.SubElement(el, x.xml_name).text = fmt_decimal(v)
        else:
            etree.SubElement(el, x.xml_name).text = str(v)
    return el

def submission(freq, version):
    root = etree.Element("sixGSubmission", nsmap={"xsi": "http://www.w3.org/2001/XMLSchema-instance"})
    root.set("{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation", "6GSchema.xsd")
    h = etree.SubElement(root, "header", version=str(version), reportingFrequency=freq)
    etree.SubElement(h, "reporter", listingExchange=EXCHANGE).text = TICKER
    etree.SubElement(h, "reportingDate").text = AS_OF
    n = 0
    for code in TABLE_ORDER:
        for row in sorted(gold_rows(code), key=lambda x: report_ids[(code, x["record_key"])][1]):
            ftype, rid = report_ids[(code, row["record_key"])]
            if ftype == freq:
                root.append(to_xml(code, row, rid))
                n += 1
    return root, n

def comments_file(version):
    rows = spark.sql(f"SELECT * FROM {CATALOG}.reg_2052a.s_c_comments WHERE as_of_date = '{AS_OF}' ORDER BY record_key").collect()
    if not rows:
        return None, 0
    root = etree.Element("sixGComments", nsmap={"xsi": "http://www.w3.org/2001/XMLSchema-instance"})
    root.set("{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation", "6GCommentSchema.xsd")
    h = etree.SubElement(root, "commentsHeader", version=str(version))
    etree.SubElement(h, "reporter", listingExchange=EXCHANGE).text = TICKER
    etree.SubElement(h, "reportingDate").text = AS_OF
    cs = etree.SubElement(root, "comments")
    for r in rows:
        c = etree.SubElement(cs, "comment", reportingFrequency="Reduced" if r.product_id and is_reduced(r.product_id) else "Primary")
        etree.SubElement(c, "reportScope").text = scope_of[r.reporting_entity]
        rep = etree.SubElement(c, "report", type=RT[r.collection])
        if r.product_id:
            etree.SubElement(rep, "product").text = products[r.product_id].product_name
        if r.sub_product:
            etree.SubElement(rep, "subProduct").text = r.sub_product
        etree.SubElement(c, "text").text = r.comments
    return root, len(rows)

# Every generation is a new reporting run; the 6G header version is one more than the number of versions already
# submitted to the Fed for this date (a resubmission), otherwise 1.
last_submitted = spark.sql(f"""SELECT MAX(version) AS v FROM {CATALOG}.reg_2052a.submission_review
                               WHERE as_of_date = '{AS_OF}' AND status = 'SUBMITTED'""").first().v
VERSION = (last_submitted or 0) + 1
RUN = (spark.sql(f"SELECT MAX(run_number) AS r FROM {CATALOG}.reg_2052a.submission_files WHERE as_of_date = '{AS_OF}'").first().r or 0) + 1
template = spark.sql(f"""SELECT * FROM {CATALOG}.reference.ref_report_template WHERE report_code = 'FR 2052a' AND activated_on <= '{AS_OF}'
                         AND (retired_on IS NULL OR retired_on > '{AS_OF}') ORDER BY activated_on DESC""").first()
TEMPLATE = template.template_version if template else "6G"
print(f"Run {RUN}, 6G header version {VERSION}, template {TEMPLATE}")
stamp = f"{d.month:02d}{d.day:02d}{d.year}"
files = {}
primary, n_primary = submission("Primary", VERSION)
files["Primary"] = (f"6G_{TICKER}_{stamp}.xml", primary, n_primary)
if IS_MONTH_END:
    reduced, n_reduced = submission("Reduced", VERSION)
    if n_reduced:
        files["Reduced"] = (f"6G_{TICKER}_{stamp}.REDUCED.xml", reduced, n_reduced)
comment_root, n_comments = comments_file(VERSION)
if comment_root is not None:
    files["Comment"] = (f"6G_{TICKER}_{stamp}.COMMENT.xml", comment_root, n_comments)
print({k: (v[0], v[2]) for k, v in files.items()}, dict(xml_issues))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. XSD validation
# MAGIC
# MAGIC The Fed's schemas `xs:include` the firm-specific schema (reporter, exchange, reportScope, internalCounterparty,
# MAGIC businessLine); it is generated from `reference.ref_firm_schema_values` under the file name the 6G schema includes.

# COMMAND ----------

work = tempfile.mkdtemp()
for name in ("6GSchema.xsd", "6GCommentSchema.xsd"):
    shutil.copyfile(f"{SCHEMA_DIR}/{name}", f"{work}/{name}")
include = re.search(r'<xs:include schemaLocation="([^"]+)"', open(f"{work}/6GSchema.xsd").read()).group(1)
inc = ['<?xml version="1.0" encoding="UTF-8"?>',
       '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" elementFormDefault="qualified" attributeFormDefault="unqualified">']
for name in ("reporterList", "exchangeList", "reportScope", "internalCounterparty", "businessLine"):
    vals = "".join(f'<xs:enumeration value="{v}"/>' for v in firm[name])
    inc.append(f'<xs:simpleType name="{name}"><xs:restriction base="xs:string">{vals}</xs:restriction></xs:simpleType>')
inc.append("</xs:schema>")
open(f"{work}/{include}", "w").write("\n".join(inc))
schemas = {"data": etree.XMLSchema(etree.parse(f"{work}/6GSchema.xsd")), "comment": etree.XMLSchema(etree.parse(f"{work}/6GCommentSchema.xsd"))}

xsd = {}
for ftype, (fname, root, n) in files.items():
    content = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    doc = etree.fromstring(content)
    schema = schemas["comment" if ftype == "Comment" else "data"]
    ok = schema.validate(etree.ElementTree(doc))
    errors = [(e.line, e.message) for e in schema.error_log]
    xsd[ftype] = (ok, errors, content, doc)
    print(f"{fname}: {'VALID' if ok else 'INVALID'} ({n} records, {len(errors)} XSD errors)")
    for line, msg in errors[:10]:
        print(f"   line {line}: {msg[:200]}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. The 652 Business Requirements rules + BR General file rules

# COMMAND ----------

def xml_records(doc):
    """(report type, reportID, attributes, {child name: element}) for every record in a data file."""
    out = []
    for rec in doc:
        if not isinstance(rec.tag, str) or rec.tag == "header":
            continue
        kids = {c.tag: c for c in rec if isinstance(c.tag, str)}
        out.append((rec.tag, rec.get("reportID"), dict(rec.attrib), kids))
    return out

data_docs = {k: v[3] for k, v in xsd.items() if k != "Comment"}
recs = {k: xml_records(doc) for k, doc in data_docs.items()}
all_recs = [(ft, *r) for ft, rs in recs.items() for r in rs]
key_of = {}   # (file type, report type, reportID) -> gold record_key
for (code, key), (ftype, rid) in report_ids.items():
    key_of[(ftype, RT[code], str(rid))] = key

def fail_of(ft, rt, rid, detail):
    code = CODE_OF_RT[rt]
    return (code, key_of.get((ft, rt, rid)), None, f"{ft} {rt} #{rid}: {detail}")

def product_of(rt, kids):
    code = CODE_OF_RT[rt]
    el = kids.get(tables[code].product_element)
    return pid_by_name.get((code, el.text)) if el is not None else None

def br_check(rule):
    """Evaluate one FRS application rule; returns (records checked, failures)."""
    cat, rt, elname = rule.rule_category, rule.report_type, rule.xml_element
    rs = [x for x in all_recs if x[1] == rt]
    fails = []
    if cat == "UNIQUE_ID":
        for ft in recs:
            c = collections.Counter(x[2] for x in rs if x[0] == ft)
            fails += [fail_of(ft, rt, rid, f"reportID {rid} used {n} times") for rid, n in c.items() if n > 1]
    elif cat == "MAX_AMOUNT":
        fails = [fail_of(ft, rt, rid, f"{elname} {k[elname].text}") for ft, _, rid, a, k in rs
                 if elname in k and abs(Decimal(k[elname].text)) > Decimal("99999999999999")]
    elif cat == "CONVERTED_USD":
        fails = [fail_of(ft, rt, rid, f"{elname} converted but unit {k[elname].get('unit')}") for ft, _, rid, a, k in rs
                 if elname in k and k[elname].get("converted") == "true" and k[elname].get("unit") != "USD"]
    elif cat == "COMMENT_CHARS":   # 6G BR General #29: ASCII 32-126 only
        bad = lambda t: any(not 32 <= ord(ch) <= 126 for ch in (t or ""))
        if rt == "sixGComments":
            cdoc = xsd.get("Comment", (None, None, None, None))[3]
            texts = [c.text for c in cdoc.iter("text")] if cdoc is not None else []
            return len(texts), [("S.C", None, None, f"comment text has invalid characters: {t[:60]}") for t in texts if bad(t)]
        fails = [fail_of(ft, rt, rid, "invalid characters") for ft, _, rid, a, k in rs if "comment" in k and bad(k["comment"].text)]
    elif cat == "MATURITY_RANGE":
        for ft, _, rid, a, k in rs:
            b = k.get(elname)
            if b is not None:
                pair = (b.findtext("maturityStart"), b.findtext("maturityEnd"))
                if pair not in valid_pairs:
                    fails.append(fail_of(ft, rt, rid, f"{elname} {pair}"))
    elif cat == "FORWARD_MATURITY":
        fwd_el = "forwardMaturityBucket" if rt == "foreignExchangeSupplementalReport" else "forwardStartBucket"
        for ft, _, rid, a, k in rs:
            if fwd_el in k and "maturityBucket" in k and \
               bucket_days(k[fwd_el].findtext("maturityStart")) > bucket_days(k["maturityBucket"].findtext("maturityStart")):
                fails.append(fail_of(ft, rt, rid, "forward start bucket after maturity bucket"))
    elif cat == "ZERO_REJECTION":
        code = CODE_OF_RT[rt]
        req = [x.xml_name for x in layout[code] if x.value_kind in ("amount", "signed_amount") and x.xsd_required]
        for ft, _, rid, a, k in rs:
            vals = [Decimal(k[n].text) for n in req if n in k]
            if product_of(rt, k) in ("S.L.6", "S.L.10"):
                continue
            zero = any(v == 0 for v in vals) if code == "S.FX" else (vals and all(v == 0 for v in vals))
            if zero:
                fails.append(fail_of(ft, rt, rid, "required amount(s) zero"))
    elif cat == "COLLATERAL_REQUIRED":
        fails = [fail_of(ft, rt, rid, f"{product_of(rt, k)} without collateralClass") for ft, _, rid, a, k in rs
                 if product_of(rt, k) in coll_required and "collateralClass" not in k]
    elif cat == "COUNTERPARTY_REQUIRED":
        fails = [fail_of(ft, rt, rid, f"{product_of(rt, k)} without counterpartySector") for ft, _, rid, a, k in rs
                 if product_of(rt, k) in cp_required and "counterpartySector" not in k]
    elif cat == "GSIB_WITH_COUNTERPARTY":
        fails = [fail_of(ft, rt, rid, "gsib without counterpartySector") for ft, _, rid, a, k in rs if "gsib" in k and "counterpartySector" not in k]
    elif cat == "GSIB_LIST":
        fails = [fail_of(ft, rt, rid, f"gsib '{k['gsib'].text}' not on the FSB 2020 list") for ft, _, rid, a, k in rs
                 if "gsib" in k and k["gsib"].text not in gsib_list]
    elif cat == "RISK_WEIGHT":
        fails = [fail_of(ft, rt, rid, f"riskWeight {k['riskWeight'].text}") for ft, _, rid, a, k in rs
                 if "riskWeight" in k and not Decimal("0") <= Decimal(k["riskWeight"].text) <= Decimal("12.5")]
    elif cat == "BUSINESS_LINE":
        if CAT_I:
            fails = [fail_of(ft, rt, rid, "businessLine missing (Category I)") for ft, _, rid, a, k in rs if "businessLine" not in k]
    elif cat == "REFERENCE_NEEDS_COLLECTION":
        fails = [fail_of(ft, rt, rid, f"{elname} without collectionReference") for ft, _, rid, a, k in rs
                 if elname in k and "collectionReference" not in k]
    elif cat == "PRODUCT_REFERENCE":
        for ft, _, rid, a, k in rs:
            if "productReference" in k and "collectionReference" in k:
                code = k["collectionReference"].text
                if (code, k["productReference"].text) not in pid_by_name:
                    fails.append(fail_of(ft, rt, rid, f"productReference '{k['productReference'].text}' is not a {code} product"))
    elif cat == "SUBPRODUCT_REFERENCE":
        for ft, _, rid, a, k in rs:
            if "subProductReference" in k:
                pid = pid_by_name.get((k["collectionReference"].text if "collectionReference" in k else "", k["productReference"].text if "productReference" in k else ""))
                if k["subProductReference"].text not in subproducts.get((pid, "Sub-Product"), set()):
                    fails.append(fail_of(ft, rt, rid, f"subProductReference '{k['subProductReference'].text}'"))
    elif cat == "SUBPRODUCT_COMBINATION":
        field = "Sub-Product2" if elname == "executionAndClearingMechanism" else "Sub-Product"
        for ft, _, rid, a, k in rs:
            if elname in k and k[elname].text not in subproducts.get((product_of(rt, k), field), set()):
                fails.append(fail_of(ft, rt, rid, f"{elname} '{k[elname].text}' not allowed for {product_of(rt, k)}"))
    elif cat == "PRODUCT_MATCH":   # comments file: product belongs to the report type, sub-product to the product
        cdoc = xsd.get("Comment", (None, None, None, None))[3]
        reports = list(cdoc.iter("report")) if cdoc is not None else []
        for c in reports:
            p, sp = c.findtext("product"), c.findtext("subProduct")
            pid = pid_by_name.get((CODE_OF_RT[c.get("type")], p))
            if elname == "product" and p and pid is None:
                fails.append(("S.C", None, None, f"comment product '{p}' is not a {c.get('type')} product"))
            if elname == "subProduct" and sp and sp not in subproducts.get((pid, "Sub-Product"), set()):
                fails.append(("S.C", None, None, f"comment sub-product '{sp}' does not belong to '{p}'"))
        return len(reports), fails
    else:
        raise NotImplementedError(cat)
    return len(rs), fails

xsd_errors_by_name = collections.defaultdict(list)
for ftype, (ok, errors, _, _) in xsd.items():
    for line, msg in errors:
        m = re.search(r"Element '([^']+)'|attribute '([^']+)'", msg)
        name = (m.group(1) or m.group(2)) if m else "?"
        xsd_errors_by_name[("comment" if ftype == "Comment" else "data", name.split("}")[-1])].append(f"{ftype} line {line}: {msg[:200]}")

for rule in br_rules:
    file_kind = "comment" if rule.schedule_code == "S.C" or rule.rule_id.startswith("BR-CHDR") else "data"
    name = f"{rule.business_field or rule.xml_element}: {rule.validation_rule or 'schema'}"
    if rule.enforced_by == "XSD":
        errs = xsd_errors_by_name.get((file_kind, rule.xml_element), []) + xsd_errors_by_name.get((file_kind, rule.xml_child_element), [])
        present = file_kind == "data" or "Comment" in xsd
        record(rule.rule_id, "6G BR", rule.report_type, rule.schedule_code, name, rule.rule_category, rule.severity,
               len(all_recs) if file_kind == "data" else n_comments, [(rule.schedule_code or "ALL", None, None, e) for e in errs],
               None if present else "NOT_APPLICABLE", "checked by XSD validation" if present else "no comments file")
    else:
        checked, fails = br_check(rule)
        record(rule.rule_id, "6G BR", rule.report_type, rule.schedule_code, name, rule.rule_category, rule.severity, checked, fails)

# BR General: file-level rules
dup = []
for ft, rs in recs.items():
    keys = collections.Counter()
    for rt, rid, attrs, kids in rs:
        k = [rt] + sorted((n, v) for n, v in attrs.items() if n != "reportID")
        for n, el in kids.items():
            if n == "comment":
                continue
            k.append((n, el.get("unit"), el.get("converted")) if el.get("unitMultiplier") else (n, etree.tostring(el)))
        keys[tuple(k)] += 1
    dup += [(CODE_OF_RT[k[0]], None, None, f"{ft}: {n} records share a report key") for k, n in keys.items() if n > 1]
record("BR-GEN-020", "6G BR General", "General #20", "ALL", "Duplicate report key in the same data file rejects the file", "DUPLICATE_KEY", "ERROR", len(all_recs), dup)
content = []
for ft, rs in recs.items():
    for rt, rid, a, k in rs:
        pid = product_of(rt, k)
        if (ft == "Reduced") != is_reduced(pid):
            content.append(fail_of(ft, rt, rid, f"{pid} does not belong in the {ft} file"))
record("BR-GEN-003", "6G BR General", "General #3-5", "ALL", "Primary / Reduced files contain only their report types and products", "FILE_CONTENT", "ERROR", len(all_recs), content)
names = [(f"{ft}: {v[0]}") for ft, v in files.items() if not re.fullmatch(rf"6G_{TICKER}_\d{{8}}(\.REDUCED|\.COMMENT)?\.xml", v[0])]
record("BR-GEN-013", "6G BR General", "General #13", "ALL", "File naming convention 6G_<ticker>_MMDDYYYY[.REDUCED|.COMMENT].xml", "FILE_NAME", "ERROR", len(files),
       [("ALL", None, None, n) for n in names])
missing_reduced = IS_MONTH_END and "Reduced" not in files
record("BR-GEN-004", "6G BR General", "General #1, #4", "S.L", "Reduced schedule file produced at month-end", "REDUCED_SCHEDULE",
       "WARNING", 1, [("S.L", None, None, "no Reduced file at month-end")] if missing_reduced else [], None if IS_MONTH_END else "NOT_APPLICABLE",
       None if IS_MONTH_END else "not a month-end as-of date")
for ftype, (ok, errors, _, _) in xsd.items():
    record(f"XSD-{ftype.upper()}", "6G XSD", "6GSchema.xsd" if ftype != "Comment" else "6GCommentSchema.xsd", "ALL",
           f"{files[ftype][0]} is valid against the 6G schema", "XSD", "ERROR", files[ftype][2],
           [("ALL", None, None, f"line {l}: {m[:300]}") for l, m in errors])

br = [x for x in results if x[3].startswith("6G")]
print(f"6G rules: {len(br)} evaluated ({sum(1 for x in br if x[3] == '6G BR')} BR), {sum(1 for x in br if x[9] == 'FAIL')} FAIL, "
      f"{sum(1 for x in br if x[9] == 'WARNING')} WARNING, {sum(1 for x in br if x[9] == 'NOT_APPLICABLE')} not applicable")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Persist: validation, files, header, review log

# COMMAND ----------

failed_errors = [x for x in results if x[9] == "FAIL"]
all_valid = all(v[0] for v in xsd.values())
release = "READY_FOR_REVIEW" if all_valid and not failed_errors else "BLOCKED"

spark.sql(f"DELETE FROM {CATALOG}.reg_2052a.gold_validation WHERE as_of_date = '{AS_OF}'")
spark.createDataFrame(results, """as_of_date DATE, entity_id STRING, rule_id STRING, rule_source STRING, appendix STRING, table_code STRING,
    rule_name STRING, rule_category STRING, severity STRING, status STRING, records_checked INT, records_failed INT, failure_details STRING,
    run_timestamp TIMESTAMP""").write.mode("append").saveAsTable(f"{CATALOG}.reg_2052a.gold_validation")
spark.sql(f"DELETE FROM {CATALOG}.reg_2052a.gold_validation_detail WHERE as_of_date = '{AS_OF}'")
if details:
    spark.createDataFrame(details, """as_of_date DATE, table_code STRING, record_key STRING, product_id STRING, rule_id STRING, rule_source STRING,
        failure_detail STRING, run_timestamp TIMESTAMP""").write.mode("append").saveAsTable(f"{CATALOG}.reg_2052a.gold_validation_detail")

# per-record status on the data tables
for code in TABLE_ORDER + ["S.C"]:
    gt = tables[code].gold_table
    spark.sql(f"""MERGE INTO {CATALOG}.reg_2052a.{gt} t
    USING (SELECT record_key, CONCAT_WS(',', COLLECT_SET(rule_id)) AS issues FROM {CATALOG}.reg_2052a.gold_validation_detail d
           WHERE as_of_date = '{AS_OF}' AND record_key IS NOT NULL
             AND rule_id IN (SELECT rule_id FROM {CATALOG}.reg_2052a.gold_validation WHERE as_of_date = '{AS_OF}' AND status = 'FAIL')
           GROUP BY record_key) s
    ON t.as_of_date = '{AS_OF}' AND t.record_key = s.record_key
    WHEN MATCHED THEN UPDATE SET t.validation_status = 'FAIL', t.validation_issues = s.issues""")
    spark.sql(f"UPDATE {CATALOG}.reg_2052a.{gt} SET validation_status = 'PASS', validation_issues = NULL "
              f"WHERE as_of_date = '{AS_OF}' AND (validation_status IS NULL OR validation_status <> 'FAIL')")

out_dir = f"/Volumes/{CATALOG}/reg_2052a/xml_filings/{AS_OF}/run{RUN:03d}"
os.makedirs(out_dir, exist_ok=True)
file_rows = []
for ftype, (fname, root, n) in files.items():
    ok, errors, content, doc = xsd[ftype]
    with open(f"{out_dir}/{fname}", "wb") as fh:
        fh.write(content)
    rtypes = len({r.tag for r in doc if isinstance(r.tag, str) and r.tag not in ("header", "commentsHeader", "comments")}) if ftype != "Comment" else 0
    br_failed = sum(1 for x in results if x[9] == "FAIL")
    file_rows.append((date.fromisoformat(AS_OF), entity.entity_id, ftype, fname, RUN, VERSION, ftype if ftype != "Comment" else None, rtypes, n,
                      ok, len(errors), "; ".join(m[:200] for _, m in errors[:3]) or None, br_failed, release,
                      content.decode("utf-8"), len(content), f"{out_dir}/{fname}", RUN_TS))
spark.createDataFrame(file_rows, """as_of_date DATE, entity_id STRING, file_type STRING, file_name STRING, run_number INT, version INT, reporting_frequency STRING,
    report_types INT, record_count INT, xsd_valid BOOLEAN, xsd_errors INT, xsd_error_sample STRING, br_rules_failed INT, release_status STRING,
    xml_content STRING, xml_size_bytes INT, file_path STRING, generated_timestamp TIMESTAMP""").write.mode("append").saveAsTable(f"{CATALOG}.reg_2052a.submission_files")

note = (f"{len(files)} file(s); XSD {'valid' if all_valid else 'INVALID'}; {len(failed_errors)} ERROR rule failure(s); "
        f"{sum(1 for x in results if x[9] == 'WARNING')} warning(s)")
spark.sql(f"""INSERT INTO {CATALOG}.reg_2052a.submission_review VALUES
  ('{AS_OF}', {RUN}, {VERSION}, 'GENERATED', '{release}', '{RELEASED_BY or "fr2052a pipeline"}',
   '{("Generated for release - " if RELEASED_BY else "") + note}', current_timestamp())""")

totals = spark.sql(f"""SELECT
  SUM(CASE WHEN table_code LIKE 'I.%' THEN reported_amount_usd ELSE 0 END) AS inflows,
  SUM(CASE WHEN table_code LIKE 'O.%' THEN reported_amount_usd ELSE 0 END) AS outflows,
  SUM(CASE WHEN table_code LIKE 'S.%' AND product_id NOT IN ('S.L.6', 'S.L.10') THEN reported_amount_usd ELSE 0 END) AS supplemental,
  COUNT(*) AS records, COUNT(DISTINCT table_code) AS tables, COUNT(DISTINCT product_id) AS products
FROM {CATALOG}.reg_2052a.v_filing_records WHERE as_of_date = '{AS_OF}'""").first()
spark.sql(f"DELETE FROM {CATALOG}.reg_2052a.gold_header WHERE as_of_date = '{AS_OF}'")
spark.sql(f"""INSERT INTO {CATALOG}.reg_2052a.gold_header VALUES ('{AS_OF}', '{entity.entity_id}', '{entity.entity_name}', '{TEMPLATE} v{VERSION} run {RUN}',
  '{entity.fed_category}', '{entity.tailoring_profile}', {totals.inflows}, {totals.outflows}, {totals.supplemental}, {totals.records},
  {totals.tables}, {totals.products}, '{release}', {len(results)}, {len(failed_errors)}, current_timestamp(), '{out_dir}')""")
spark.sql(f"""INSERT INTO {CATALOG}.audit.data_lineage VALUES ('{AS_OF}', 'Validation & Submission', 'FR 2052a tables -> 6G XML',
  'reg_2052a (13 data tables + comments)', 'reg_2052a.submission_files', {totals.records}, {len(files)}, current_timestamp())""")
print(f"Submission {AS_OF} run {RUN} (6G v{VERSION}): {release} - {note}")

# COMMAND ----------

display(spark.sql(f"""SELECT rule_source, status, COUNT(*) AS rules FROM {CATALOG}.reg_2052a.gold_validation
WHERE as_of_date = '{AS_OF}' GROUP BY ALL ORDER BY 1, 2"""))
display(spark.sql(f"""SELECT rule_id, rule_source, table_code, severity, status, records_failed, failure_details
FROM {CATALOG}.reg_2052a.gold_validation WHERE as_of_date = '{AS_OF}' AND status IN ('FAIL', 'WARNING') ORDER BY severity, rule_id"""))
display(spark.sql(f"SELECT file_type, file_name, version, record_count, xsd_valid, xsd_errors, release_status FROM {CATALOG}.reg_2052a.submission_files WHERE as_of_date = '{AS_OF}' AND run_number = {RUN}"))
