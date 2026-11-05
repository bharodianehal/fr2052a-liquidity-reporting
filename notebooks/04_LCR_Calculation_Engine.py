# Databricks notebook source
# MAGIC %md
# MAGIC # LCR Calculation Engine (v9) - per reporting entity
# MAGIC ## Owned by: Treasury / ALM Team
# MAGIC
# MAGIC Computes the Liquidity Coverage Ratio (12 CFR 249) from Silver with the rules in `reference.rules_lcr_appendix_vi`
# MAGIC (FR 2052a Appendix VI mapping). Each rule matches positions on product, sub-product, counterparty, counterparty
# MAGIC category, collateral HQLA level, insured, the 30-day window and an optional SQL condition; the lowest
# MAGIC `rule_priority` that matches applies. The ratio feeds **S.L.6 Liquidity Coverage Ratio** in the FR 2052a report
# MAGIC (notebook 05), so this runs before the report build.

# COMMAND ----------

dbutils.widgets.text("as_of_date", "2026-02-27")
dbutils.widgets.text("catalog", "")
AS_OF = dbutils.widgets.get("as_of_date")
CATALOG = dbutils.widgets.get("catalog")
spark.sql(f"USE CATALOG {CATALOG}")

# 249.30 outflow adjustment: Category I/II use the full outflow amount; Category III with < $75B wSTWF 85%, Category IV 70%.
print(f"LCR for {AS_OF}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## LCR per reporting entity subject to the LCR on a standalone basis
# MAGIC Each entity's positions come from `conformed.v_entity_position` (its scope, intercompany eliminated, affiliate flows
# MAGIC Internal), so the consolidated BHC and the bank get their own LCR - each reported as that entity's S.L.6.

# COMMAND ----------

AMOUNT = {"maturity_amount": "f.principal_amount", "market_value": "f.market_value", "collateral_value": "f.collateral_value"}
rules = spark.table(f"{CATALOG}.reference.rules_lcr_appendix_vi").collect()

def in_list(col, csv_values):
    vals = ", ".join("'" + v.strip().replace("'", "''") + "'" for v in csv_values.split(","))
    return f"{col} IN ({vals})"

def hqla_cond(v):
    conds = []
    for level in v.split(","):
        level = level.strip()
        conds.append("col.is_hqla" if level == "HQLA" else ("NOT COALESCE(col.is_hqla, false)" if level == "Non-HQLA" else f"col.hqla_level = '{level}'"))
    return "(" + " OR ".join(conds) + ")"


# Categories in the maturity mismatch add-on (12 CFR 249.30(b)): outflows and inflows with a contractual maturity -
# unsecured wholesale funding and debt, secured funding and asset exchange, net derivative cash flows, other contractual
# flows; unsecured and secured lending, net derivative cash inflow, securities and other contractual inflows.
MATURITY_MISMATCH_RULES = ("('LCR-O20','LCR-O21','LCR-O22','LCR-O23','LCR-O30','LCR-O31','LCR-O32','LCR-O33','LCR-O34','LCR-O36','LCR-O37',"
                           "'LCR-O38','LCR-O52','LCR-O57','LCR-I01','LCR-I02','LCR-I03','LCR-I04','LCR-I06','LCR-I10','LCR-I11','LCR-I12',"
                           "'LCR-I13','LCR-I14','LCR-I15','LCR-I16','LCR-I22','LCR-I23','LCR-I24')")


def run_lcr(entity):
    ADJ = 1.0 if entity.fed_category in ("Category I", "Category II") else (0.85 if entity.fed_category == "Category III" else 0.70)
    SRC = f"(SELECT * FROM {CATALOG}.conformed.v_entity_position WHERE as_of_date = '{AS_OF}' AND reporting_entity = '{entity.entity_id}')"
    matches = []
    for r in rules:
        conds = [in_list("f.product_id", r.applicable_product_ids)]
        if r.sub_product_condition:
            conds.append(in_list("f.sub_product", r.sub_product_condition))
        if r.counterparty_condition:
            conds.append(in_list("f.counterparty", r.counterparty_condition))
        if r.counterparty_category_condition:
            conds.append(in_list("f.counterparty_category", r.counterparty_category_condition))
        if r.collateral_hqla_condition:
            conds.append(hqla_cond(r.collateral_hqla_condition))
        if r.insured_condition:
            conds.append(f"f.insured = '{r.insured_condition}'")
        if r.maturity_condition == "<=30":
            conds.append("COALESCE(mb.is_within_30d, true)")
        if r.other_condition:
            conds.append(f"({r.other_condition})")
        rate = r.inflow_rate if r.flow_direction == "INFLOW" else (r.outflow_rate if r.flow_direction == "OUTFLOW" else r.inflow_rate)
        matches.append(f"""SELECT f.position_id AS record_id, '{r.rule_id}' AS rule_id, {r.rule_priority} AS rule_priority, '{r.flow_direction}' AS flow_direction,
          '{r.rule_name.replace("'", "''")}' AS rule_name, CAST({AMOUNT[r.amount_basis]} AS DECIMAL(22,4)) AS amount,
          CAST({rate} AS DECIMAL(5,4)) AS rate
        FROM {SRC} f
        LEFT JOIN {CATALOG}.reference.ref_maturity_bucket mb ON mb.bucket_label = f.maturity_bucket
        LEFT JOIN {CATALOG}.reference.ref_collateral col ON col.collateral_class = f.collateral_class
        WHERE {' AND '.join(conds)}""")

    spark.sql(f"""
    CREATE OR REPLACE TEMP VIEW v_lcr_detail AS
    WITH m AS ({' UNION ALL '.join(matches)}),
    best AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY record_id, CASE WHEN flow_direction LIKE 'HQLA%' THEN 'H' ELSE flow_direction END
                                          ORDER BY rule_priority, rule_id) AS rn FROM m)
    SELECT f.as_of_date, f.position_id AS record_id, f.product_id, b.flow_direction, b.rule_id, b.rule_name, f.counterparty, f.collateral_class,
           col.hqla_level, CAST(COALESCE(b.amount, 0) * COALESCE(fx.rate_to_usd, 1) AS DECIMAL(22,4)) AS amount_usd, b.rate,
           CAST(COALESCE(b.amount, 0) * COALESCE(fx.rate_to_usd, 1) * b.rate AS DECIMAL(22,4)) AS weighted_amount_usd,
           COALESCE(col.lcr_haircut_pct, 0) AS haircut, f.counterparty_category
    FROM best b
    JOIN {SRC} f ON f.position_id = b.record_id
    LEFT JOIN {CATALOG}.reference.ref_collateral col ON col.collateral_class = f.collateral_class
    LEFT JOIN {CATALOG}.reference.ref_fx_rates fx ON fx.currency_code = f.currency
    WHERE b.rn = 1
    """)

    # Positions maturing beyond 30 days are outside the LCR by design; only <= 30-day inflows / outflows must match a rule.
    unmatched = spark.sql(f"""
    SELECT COUNT(*) AS n FROM {SRC} f
    LEFT JOIN {CATALOG}.reference.ref_maturity_bucket mb ON mb.bucket_label = f.maturity_bucket
    WHERE (f.product_id LIKE 'O.%' OR (f.product_id LIKE 'I.%' AND f.product_id NOT LIKE 'I.A.%'))
      AND COALESCE(mb.is_within_30d, true)
      AND f.position_id NOT IN (SELECT record_id FROM v_lcr_detail WHERE flow_direction IN ('INFLOW', 'OUTFLOW'))""").first().n
    print(f"{entity.entity_id}: matched {spark.table('v_lcr_detail').count()} position/rule pairs; {unmatched} <= 30-day inflow/outflow position(s) without a rule")

    t = spark.sql("""
    SELECT
      SUM(CASE WHEN flow_direction = 'HQLA' AND hqla_level = 'Level 1' THEN amount_usd ELSE 0 END) AS l1,
      SUM(CASE WHEN flow_direction = 'HQLA' AND hqla_level = 'Level 2A' THEN amount_usd ELSE 0 END) AS l2a,
      SUM(CASE WHEN flow_direction = 'HQLA' AND hqla_level = 'Level 2A' THEN amount_usd * (1 - haircut) ELSE 0 END) AS l2a_adj,
      SUM(CASE WHEN flow_direction = 'HQLA' AND hqla_level = 'Level 2B' THEN amount_usd ELSE 0 END) AS l2b,
      SUM(CASE WHEN flow_direction = 'HQLA' AND hqla_level = 'Level 2B' THEN amount_usd * (1 - haircut) ELSE 0 END) AS l2b_adj,
      SUM(CASE WHEN flow_direction = 'HQLA_EXCLUDED' THEN amount_usd ELSE 0 END) AS excluded,
      SUM(CASE WHEN flow_direction = 'OUTFLOW' THEN weighted_amount_usd ELSE 0 END) AS outflows,
      SUM(CASE WHEN flow_direction = 'OUTFLOW' AND product_id LIKE 'O.D.%' AND counterparty_category = 'Retail' THEN weighted_amount_usd ELSE 0 END) AS retail,
      SUM(CASE WHEN flow_direction = 'OUTFLOW' AND (product_id LIKE 'O.W.%' OR (product_id LIKE 'O.D.%' AND COALESCE(counterparty_category, '') <> 'Retail'))
               THEN weighted_amount_usd ELSE 0 END) AS wholesale,
      SUM(CASE WHEN flow_direction = 'OUTFLOW' AND product_id LIKE 'O.S.%' THEN weighted_amount_usd ELSE 0 END) AS secured,
      SUM(CASE WHEN flow_direction = 'OUTFLOW' AND product_id IN ('O.O.1','O.O.2','O.O.8','O.O.20') THEN weighted_amount_usd ELSE 0 END) AS derivative,
      SUM(CASE WHEN flow_direction = 'OUTFLOW' AND product_id IN ('O.O.4','O.O.5','O.O.6') THEN weighted_amount_usd ELSE 0 END) AS commitment,
      SUM(CASE WHEN flow_direction = 'INFLOW' THEN weighted_amount_usd ELSE 0 END) AS inflows
    FROM v_lcr_detail""").first()
    f = lambda v: float(v or 0)
    # S.L.1 subsidiary HQLA that cannot be transferred (HQLA_EXCLUDED) is taken out of Level 1; then the 249.21 caps
    l1, l2a, l2a_adj, l2b, l2b_adj = f(t.l1) - f(t.excluded), f(t.l2a), f(t.l2a_adj), f(t.l2b), f(t.l2b_adj)
    l2_cap_excess = max(0.0, l2a_adj + l2b_adj - (40 / 60) * l1)
    l2b_cap_excess = max(0.0, l2b_adj - (15 / 85) * (l1 + l2a_adj))
    total_hqla = l1 + l2a_adj + l2b_adj - max(l2_cap_excess, l2b_cap_excess)
    outflows, inflows = f(t.outflows), f(t.inflows)
    capped_inflows = min(inflows, 0.75 * outflows)
    # 12 CFR 249.30(b) maturity mismatch add-on: for each of the 30 days, the net cumulative maturity outflow (outflows less
    # inflows with a contractual maturity in the categories of 249.30(b), cumulated to that day, floored at zero); the add-on
    # is the largest of those over the 30 days less the amount on day 30. Non-maturity (open) items are not part of it.
    mm = spark.sql(f"""
      SELECT b.day_end AS d, SUM(CASE WHEN v.flow_direction = 'OUTFLOW' THEN v.weighted_amount_usd ELSE -v.weighted_amount_usd END) AS net
      FROM v_lcr_detail v JOIN {SRC} f ON f.position_id = v.record_id
      JOIN {CATALOG}.reference.ref_maturity_bucket b ON b.bucket_label = f.maturity_bucket
      WHERE v.rule_id IN {MATURITY_MISMATCH_RULES} AND b.bucket_type = 'Daily' AND b.day_end BETWEEN 1 AND 30 GROUP BY 1""").collect()
    by_day = {int(r.d): float(r.net or 0) for r in mm}
    cum, ncmo = 0.0, []
    for d in range(1, 31):
        cum += by_day.get(d, 0.0)
        ncmo.append(max(0.0, cum))
    add_on = max(ncmo) - ncmo[-1]
    peak_day = 1 + ncmo.index(max(ncmo))
    net_outflows = ADJ * (outflows - capped_inflows + add_on)
    print(f"maturity mismatch add-on {add_on:,.1f} (peak day {peak_day}: {max(ncmo):,.1f}; day 30: {ncmo[-1]:,.1f})")
    lcr = round(total_hqla / net_outflows, 4) if net_outflows > 0 else None
    other = outflows - f(t.retail) - f(t.wholesale) - f(t.secured) - f(t.derivative) - f(t.commitment)
    print(f"HQLA {total_hqla:,.0f}  outflows {outflows:,.0f}  inflows {inflows:,.0f} (capped {capped_inflows:,.0f})  "
          f"net {net_outflows:,.0f}  LCR {lcr:.4f}" if lcr is not None else "No net cash outflows")

    spark.sql(f"DELETE FROM {CATALOG}.reg_lcr.calculation_results WHERE as_of_date = '{AS_OF}' AND entity_id = '{entity.entity_id}'")
    spark.sql(f"""
    INSERT INTO {CATALOG}.reg_lcr.calculation_results VALUES (
      'LCR-{entity.entity_id}-{AS_OF}', '{AS_OF}', '{entity.entity_id}', 'BAU',
      {l1}, {l2a}, {l2a_adj}, {l2b}, {l2b_adj}, {l2_cap_excess}, {l2b_cap_excess}, {f(t.excluded)}, {total_hqla},
      {outflows}, {f(t.retail)}, {f(t.wholesale)}, {f(t.secured)}, {f(t.derivative)}, {f(t.commitment)}, {other},
      {inflows}, {0.75 * outflows}, {capped_inflows}, {add_on}, {ADJ}, {net_outflows}, {lcr if lcr is not None else 'NULL'},
      {str(lcr is not None and lcr >= 1.0).lower()}, {unmatched}, current_timestamp())""")
    spark.sql(f"DELETE FROM {CATALOG}.reg_lcr.calculation_detail WHERE as_of_date = '{AS_OF}' AND entity_id = '{entity.entity_id}'")
    spark.sql(f"""INSERT INTO {CATALOG}.reg_lcr.calculation_detail
    SELECT as_of_date, '{entity.entity_id}', record_id, product_id, flow_direction, rule_id, rule_name, counterparty, collateral_class, hqla_level,
           amount_usd, rate, weighted_amount_usd FROM v_lcr_detail""")
    silver = spark.sql(f"SELECT COUNT(*) AS n FROM {SRC} f").first().n
    spark.sql(f"""INSERT INTO {CATALOG}.audit.data_lineage VALUES ('{AS_OF}', 'LCR Calculation {entity.entity_id}', 'Entity positions -> LCR mart',
      'conformed.v_entity_position', 'reg_lcr.calculation_results', {silver}, 1, current_timestamp())""")
    return lcr


results = {e.entity_id: run_lcr(e) for e in spark.table(f"{CATALOG}.reference.ref_reporting_entity").where("lcr_standalone").collect()}
print(results)

# COMMAND ----------

display(spark.sql(f"""
SELECT entity_id, flow_direction, rule_id, rule_name, COUNT(*) AS positions, ROUND(SUM(amount_usd), 1) AS amount_usd,
       MAX(rate) AS rate, ROUND(SUM(weighted_amount_usd), 1) AS weighted_usd
FROM {CATALOG}.reg_lcr.calculation_detail WHERE as_of_date = '{AS_OF}' GROUP BY ALL ORDER BY entity_id, flow_direction, rule_id"""))
