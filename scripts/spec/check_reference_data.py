"""Consistency checks for reference_data/*.csv against counts stated in the FR 2052a instructions and the 6G package.

Usage: python3 scripts/spec/check_reference_data.py [reference_data]
"""
import csv
import os
import sys
from collections import Counter

d = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "..", "reference_data")
load = lambda name: list(csv.DictReader(open(os.path.join(d, name), encoding="utf-8")))
failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


tables = load("spec_tables.csv")
fields = load("spec_table_fields.csv")
products = load("spec_products.csv")
pids = {p["product_id"] for p in products}

check(len(tables) == 14, "Appendix I: 13 data tables + Comments")
spec_fields = [f for f in fields if f["source"].startswith("Data Tables")]
per_table = Counter(f["table_code"] for f in spec_fields)
expected = {"I.A": 15, "I.U": 15, "I.S": 21, "I.O": 14, "O.D": 15, "O.W": 15, "O.S": 18, "O.O": 13,
            "S.I": 7, "S.DC": 16, "S.L": 6, "S.B": 17, "S.FX": 15, "S.C": 5}
check(dict(per_table) == expected, f"Data Tables p.84-85 field counts per table ({sum(per_table.values())} fields)")
check(all(f["column_name"] for f in fields), "every spec field maps to a gold column")
check(len({(f["table_code"], f["column_name"]) for f in fields}) == len(fields), "gold column names unique per table")

counts = Counter(p["table_code"] for p in products)
check(len(products) == 147, "147 products in the table of contents")
check(dict(counts) == {"I.A": 7, "I.U": 8, "I.S": 10, "I.O": 9, "O.D": 15, "O.W": 19, "O.S": 11, "O.O": 22,
                       "S.DC": 21, "S.L": 10, "S.B": 6, "S.I": 6, "S.FX": 3}, "product counts per table")

coll = load("spec_collateral_class_requirements.csv")
check({c["product_id"] for c in coll} == pids, "II-c covers every product")
check(all(c["requirement"] in ("Required", "Dependent", "Not Applicable") for c in coll), "II-c every product classified")

for name, key in [("spec_subproducts.csv", "product_id"), ("spec_counterparty_requirements.csv", "product_id"),
                  ("spec_forward_start_exclusions.csv", "product_id")]:
    rows = load(name)
    check(all(r[key] in pids for r in rows), f"{name}: all PIDs exist")

cps = load("spec_counterparties.csv")
check(len(cps) == 19, "19 counterparty types")
cpr = load("spec_counterparty_requirements.csv")
check(all(r["counterparty"] in {c["counterparty"] for c in cps} for r in cpr), "II-b uses only defined counterparty types")
muni = [r for r in cpr if r["counterparty"] == "Municipalities for VRDN Structures" and r["applicability"] == "Applicable"]
check({r["product_id"] for r in muni} == {"O.O.5"}, "Municipalities for VRDN Structures applicable to O.O.5 only")

ac = load("spec_asset_categories.csv")
check(len(ac) == 91 and len({a["collateral_class"] for a in ac}) == 91, "Appendix III: 91 distinct asset categories")
check(Counter(a["hqla_level"] for a in ac) == Counter({"Level 1": 12, "Level 2A": 7, "Level 2B": 4, "Non-HQLA": 68}),
      "Appendix III HQLA levels (12 L1, 7 L2A, 4 L2B)")

mb = load("spec_maturity_buckets.csv")
std = [b for b in mb if b["is_standard"] == "true"]
check(len(std) == 76, "Appendix IV-a: 76 maturity buckets")
check(sum(1 for b in std if b["bucket_type"] == "Daily") == 60, "60 daily buckets (Day 1 - Day 60)")
check(all(b["maturity_start"].startswith("P") for b in std), "every standard bucket has a 6G maturityStart duration")
check({b["bucket_label"]: (b["maturity_start"], b["maturity_end"]) for b in std}[">5 Yr"] == ("P1827D", ""), "6G: >5 Yr starts at P1827D, no maturityEnd")
days = [(int(b["day_start"]), int(b["day_end"])) for b in std if b["day_start"]]
check(all(a[1] + 1 == b[0] for a, b in zip(days, days[1:])), "bucket day ranges are contiguous with no gaps or overlaps")
tl = load("spec_maturity_tailoring.csv")
check(all(t["bucket_label"] in {b["bucket_label"] for b in mb} for t in tl), "IV-b tailoring uses defined buckets")
check(sum(1 for t in tl if t["profile_code"] == "CAT_I_II") == 76, "IV-b Category I/II: 76 buckets")

dc = load("spec_double_counting.csv")
check(len(dc) == 21, "Appendix V: 21 double-counting items")
for r in dc:
    for pid in filter(None, (r["products_a"] + "," + r["products_b"]).split(",")):
        if pid not in pids:
            failures.append(f"Appendix V item {r['item_no']}: unknown PID {pid}")

val = load("rules_validation_6g.csv")
check(len(val) == 652, "Fed 6G business requirements: 652 validation rules")
check(all(v["enforced_by"] in ("XSD", "FRS") for v in val), "every BR rule is assigned to XSD validation or an FRS check")
check(len({v["rule_id"] for v in val}) == 652, "BR rule ids unique")

lay = load("spec_xsd_layout.csv")
check(len({l["table_code"] for l in lay}) == 13, "XSD layout for the 13 report types")
xml_names = {(f["table_code"], f["xml_element"]) for f in fields}
check(all((l["table_code"], l["xml_name"]) in xml_names for l in lay if l["xml_name"] not in ("reportID", "comment")),
      "every XSD element / attribute maps to a spec field")
check(all(p["product_name"] for p in products) and sum(p["product_name"] != p["instructions_name"] for p in products) == 7,
      "product names from the XSD (7 differ from the Instructions wording)")
sp = load("spec_subproducts.csv")
check(len(sp) == 183 and all(r["product_id"] in pids for r in sp), "Appendix II-a: 183 BR product / sub-product combinations")
fv = load("spec_field_values.csv")
check(sum(1 for v in fv if v["field_name"] == "G-SIB") == 30, "G-SIB: FSB 2020 list (30) from the BR")
check({c["counterparty"] for c in cps} >= {"Broker Dealer", "Financial Market Utlility", "Non-regulated Fund"}, "counterparty types use the XSD spellings")

firm = load("ref_firm_schema_values.csv")
ent = load("ref_reporting_entity.csv")
check({e["report_scope"] for e in ent} <= {f["value"] for f in firm if f["list_name"] == "reportScope"}, "every reporting entity has a firm reportScope")

cat = load("ref_standard_product_type.csv")
pmap = load("ref_source_product_map.csv")
pr = load("rules_pid_derivation.csv")
check(all(r["product_id"] in pids for r in pr), "PID derivation rules only produce defined PIDs")
check({c["standard_product_type"] for c in cat} == {r["standard_product_type"] for r in pr}, "every standard product type has derivation rules")
check({m["standard_product_type"] for m in pmap} == {c["standard_product_type"] for c in cat}, "every standard type has bank product codes")
check(len({m["source_product_code"] for m in pmap}) == len(pmap), "bank product codes are unique")
check({r["product_id"] for r in pr} == pids - {"S.L.6"}, "every PID except S.L.6 (LCR engine) is derivable from a source product")
les = load("ref_legal_entity.csv")
le_ids = {l["legal_entity_id"] for l in les}
check(all(not l["parent_legal_entity_id"] or l["parent_legal_entity_id"] in le_ids for l in les), "org structure parents exist")
check({l["legal_name"] for l in les} == {f["value"] for f in firm if f["list_name"] == "internalCounterparty"}, "every legal entity is a firm internal counterparty")
check(all(e["root_legal_entity_id"] in le_ids for e in ent), "every reporting entity is rooted in a legal entity")
cust = load("ref_customer_master.csv")
check(all(c["counterparty"] in {x["counterparty"] for x in cps} for c in cust), "customer master uses the XSD counterparty values")
gs = {v["allowed_value"] for v in fv if v["field_name"] == "G-SIB"}
check(all(not c["gsib_parent"] or c["gsib_parent"] in gs for c in cust), "customer G-SIB parents are on the BR G-SIB list")
check(all(not c["affiliate_legal_entity_id"] or c["affiliate_legal_entity_id"] in le_ids for c in cust), "affiliates are group legal entities")
onb = load("ref_customer_onboarding.csv")
check({c["customer_id"] for c in cust} <= {o["customer_id"] for o in onb}, "every approved customer was onboarded")
sec = load("ref_security_master.csv")
check({s["collateral_class"] for s in sec} == {a["collateral_class"] for a in ac}, "security master covers every Appendix III class")
psv = load("rules_fed_psv.csv")
check(len(psv) == 14, "Fed post-submission validation checks: 14")
stwf = load("rules_stwf_appendix_vii.csv")
check({r["appendix_table"] for r in stwf} == {str(n) for n in range(1, 25)}, "Appendix VII: all 24 tables mapped")
check(all(p in pids for r in stwf for p in r["product_ids"].split(",")), "Appendix VII PIDs exist")
sm = load("ref_stwf_mdrm.csv")
mi = {m["mdrm"] for m in load("ref_mdrm_items.csv")}
check(all(m["mdrm"] in mi for m in sm), "every FR Y-15 Schedule G item has an active MDRM code")

print(f"\n{'FAILED' if failures else 'PASSED'}: {len(failures)} failure(s)")
sys.exit(1 if failures else 0)
