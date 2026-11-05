"""Build the FR 2052a spec reference data (reference_data/spec_*.csv) from the Fed instructions PDF and the
Fed 6G schema package.

Sources:
  * FR 2052a Instructions (federalreserve.gov reporting forms, 106 printed pages). Page numbers below are the
    printed "Page N of 106" numbers. Business meaning: tables, fields, PIDs, appendices.
  * 6G Schema and Sample Files (6GSchema.xsd + 6G Business Requirements workbook, 2021-12-28). This is what the
    Fed's FRS application validates, so every value that goes into the XML comes from here: product names,
    enumeration spellings, maturity bucket durations, Appendix II-a combinations, the G-SIB list, the XSD element
    layout and the 652 business-requirement rules. The build fails if the two sources disagree on structure.

  spec_tables.csv                       Appendix I (p.80-85)  - the 13 data tables + Comments
  spec_table_fields.csv                 Data Tables (p.84-85) - extracted: field order and type, red = Mandatory, blue = Dependent
  spec_products.csv                     Table of contents (p.3-7) - extracted: all 147 PIDs
  spec_subproducts.csv                  Appendix II-a (p.86-87) + S.DC product definitions (p.64-65)
  spec_counterparty_requirements.csv    Appendix II-b (p.88-90)
  spec_collateral_class_requirements.csv Appendix II-c (p.91-94) - extracted from the check-mark grid
  spec_forward_start_exclusions.csv     Appendix II-d (p.95-97)
  spec_asset_categories.csv             Appendix III (p.98-100)
  spec_maturity_buckets.csv             Appendix IV-a (p.101) + tailoring aggregates from IV-b
  spec_maturity_tailoring.csv           Appendix IV-b (p.102)
  spec_double_counting.csv              Appendix V (p.103-105)
  spec_field_values.csv                 Field Definitions (p.16-32)
  spec_counterparties.csv               Field Definitions - Counterparty (p.17-21), XSD spellings
  spec_xsd_layout.csv                   6GSchema.xsd - ordered elements / attributes per report type
  rules_validation_6g.csv               6G Business Requirements - the 652 rules on the 15 report / header tabs
  rules_stwf_appendix_vii.csv           Appendix VII - FR Y-15 Schedule G (STWF) items from FR 2052a data elements
  ref_stwf_mdrm.csv / ref_mdrm_items.csv  Fed MDRM codes of the FR Y-15 Schedule G items (RISIY838-889); FR 2052a has none (PIDs)

Usage: python -I scripts/spec/build_reference_data.py <instructions.pdf> <6G folder> <out_dir> [MDRM_CSV.csv]
Requires pymupdf, lxml, openpyxl. Run scripts/spec/check_reference_data.py afterwards.
"""
import csv
import html
import json
import os
import re
import sys

import openpyxl
import pymupdf
from lxml import etree

# ---------------------------------------------------------------------------
# Appendix I: the 13 data tables + Comments, with the 6G XML report type and product element
# names used by the Fed 6G business requirements (reference_data/rules_validation_6g.csv).
# ---------------------------------------------------------------------------
TABLES = [
    # code, name, section, gold table, xml report type, product element, sub-product element, primary amount column
    ("I.A", "Inflows-Assets", "Inflows", "i_a_assets", "assetInflowReport", "assetProduct", "assetSource", "market_value"),
    ("I.U", "Inflows-Unsecured", "Inflows", "i_u_unsecured", "unsecuredInflowReport", "unsecuredProduct", "", "maturity_amount"),
    ("I.S", "Inflows-Secured", "Inflows", "i_s_secured", "securedInflowReport", "securedInflowProduct", "pledgeLevelAndLongHedging", "maturity_amount"),
    ("I.O", "Inflows-Other", "Inflows", "i_o_other", "otherInflowReport", "otherInflowProduct", "", "maturity_amount"),
    ("O.D", "Outflows-Deposits", "Outflows", "o_d_deposits", "depositsOutflowReport", "depositsProduct", "", "maturity_amount"),
    ("O.W", "Outflows-Wholesale", "Outflows", "o_w_wholesale", "wholesaleOutflowReport", "wholesaleOutflowProduct", "", "maturity_amount"),
    ("O.S", "Outflows-Secured", "Outflows", "o_s_secured", "securedOutflowReport", "securedOutflowProduct", "securedOutflowCounterpartyOrCoverage", "maturity_amount"),
    ("O.O", "Outflows-Other", "Outflows", "o_o_other", "otherOutflowReport", "otherOutflowProduct", "", "maturity_amount"),
    ("S.DC", "Supplemental-Derivatives & Collateral", "Supplemental", "s_dc_derivatives_collateral", "derivativesAndCollateralSupReport", "derivativesAndCollateralSupProduct", "segregationCategory", "market_value"),
    ("S.L", "Supplemental-Liquidity Risk Measurement", "Supplemental", "s_l_liquidity_risk_measurement", "liquidityRiskMeasurementSupReport", "liquidityRiskMeasurementSupProduct", "", "market_value"),
    ("S.B", "Supplemental-Balance Sheet", "Supplemental", "s_b_balance_sheet", "balanceSheetSupReport", "balanceSheetSupProduct", "", "market_value"),
    ("S.I", "Supplemental-Informational", "Supplemental", "s_i_informational", "informationalSupplementalReport", "supplementalInformationProduct", "", "market_value"),
    ("S.FX", "Supplemental-Foreign Exchange", "Supplemental", "s_fx_foreign_exchange", "foreignExchangeSupplementalReport", "foreignExchangeProduct", "", "maturity_amount_currency_1"),
    ("S.C", "Comments", "Comments", "s_c_comments", "sixGComments", "product", "subProduct", ""),
]

# Data Tables page, table header text -> table code (pages are 0-based PDF index + 1)
TABLE_HEADERS = {
    (85, "Inflows", "Assets"): "I.A", (85, "Inflows", "Unsecured"): "I.U",
    (85, "Inflows", "Secured"): "I.S", (85, "Inflows", "Other"): "I.O",
    (85, "Outflows", "Deposits"): "O.D", (85, "Outflows", "Wholesale"): "O.W",
    (85, "Outflows", "Secured"): "O.S", (85, "Outflows", "Other"): "O.O",
    (86, "S1", "Informational"): "S.I", (86, "S1", "Derivatives & Collateral"): "S.DC",
    (86, "S1", "Liquidity Risk Measurement"): "S.L", (86, "S2", "Balance Sheet"): "S.B",
    (86, "S2", "Foreign Exchange"): "S.FX", (86, "S2", "Comments"): "S.C",
}
RED = (0.9, 0.72, 0.72)

# Spec field name -> (gold column, 6G XML element). Flag fields are stored as BOOLEAN.
FIELD_MAP = {
    "Reporting Entity": ("reporting_entity", "reportScope"),
    "Product": ("product_id", None),  # table-specific product element
    "Sub-Product": ("sub_product", None),  # table-specific sub-product element
    "Sub-Product2": ("sub_product_2", "executionAndClearingMechanism"),
    "Market Value": ("market_value", "marketValue"),
    "Lendable Value": ("lendable_value", "lendableValue"),
    "Maturity Amount": ("maturity_amount", "maturityValue"),
    "Maturity Bucket": ("maturity_bucket", "maturityBucket"),
    "Forward Start Amount": ("forward_start_amount", "forwardStartValue"),
    "Forward Start Bucket": ("forward_start_bucket", "forwardStartBucket"),
    "Collateral Class": ("collateral_class", "collateralClass"),
    "Collateral Value": ("collateral_value", "collateralValue"),
    "Treasury Control": ("treasury_control", "treasuryControl"),
    "Accounting Designation": ("accounting_designation", "accountingDesignation"),
    "Effective Maturity Bucket": ("effective_maturity_bucket", "effectiveMaturityBucket"),
    "Encumbrance Type": ("encumbrance_type", "encumbranceType"),
    "Internal": ("internal", "internal"),
    "Internal Counterparty": ("internal_counterparty", "internalCounterparty"),
    "Business Line": ("business_line", "businessLine"),
    "Counterparty": ("counterparty", "counterpartySector"),
    "G-SIB": ("gsib", "gsib"),
    "Maturity Optionality": ("maturity_optionality", "maturityOptionality"),
    "Risk Weight": ("risk_weight", "riskWeight"),
    "Unencumbered": ("unencumbered", "unencumbered"),
    "Settlement": ("settlement", "settlementMechanism"),
    "Insured": ("insured", "insured"),
    "Trigger": ("trigger_flag", "trigger"),
    "Rehypothecated": ("rehypothecated", "rehypothecated"),
    "Loss Absorbency": ("loss_absorbency", "lossAbsorbency"),
    "Collateral Level": ("collateral_level", "collateralLevel"),
    "Netting Eligible": ("netting_eligible", "nettingEligible"),
    "Collection Reference": ("collection_reference", "collectionReference"),
    "Product Reference": ("product_reference", "productReference"),
    "Sub-Product Reference": ("sub_product_reference", "subProductReference"),
    "Maturity Amount Currency 1": ("maturity_amount_currency_1", "baseMaturityValue"),
    "Maturity Amount Currency 2": ("maturity_amount_currency_2", "targetMaturityValue"),
    "Foreign Exchange Option Direction": ("fx_option_direction", "foreignExchangeOptionDirection"),
    "Forward Start Amount Currency 1": ("forward_start_amount_currency_1", "baseForwardMaturityValue"),
    "Forward Start Amount Currency 2": ("forward_start_amount_currency_2", "targetForwardMaturityValue"),
    "Collection": ("collection", "reportTypes"),
    "Comments": ("comments", "text"),
}
FLAG_FIELDS = {"Treasury Control", "Internal", "Unencumbered", "Trigger", "Rehypothecated", "Netting Eligible"}

# Footnote 16 (p.84): Currency and Converted attributes are required for each value field.
# They are not drawn in the figure; they are added to every table that has a numeric field.
CURRENCY_ATTRS = {
    "default": [("Currency", "currency", "text"), ("Converted", "converted", "flag")],
    "S.FX": [("Currency 1", "currency_1", "text"), ("Currency 2", "currency_2", "text"), ("Converted", "converted", "flag")],
}

# ---------------------------------------------------------------------------
# Appendix II-a (p.86-87). S.DC: Sub-Product applies to S.DC.3-S.DC.10 and Sub-Product 2 to S.DC.1-S.DC.10,
# per the S.DC general guidance (p.64-65) which the appendix table summarises.
# ---------------------------------------------------------------------------
CENTRAL_BANKS = ["Federal Reserve Bank", "Swiss National Bank", "Bank of England", "European Central Bank",
                 "Bank of Japan", "Reserve Bank of Australia", "Bank of Canada", "Other Central Bank"]
SUBPRODUCTS = [
    (["I.A.2"], "Sub-Product", CENTRAL_BANKS + ["Federal Home Loan Bank", "Other Government Sponsored Entity"], "Appendix II-a p.86"),
    (["I.A.3", "I.A.4"], "Sub-Product", CENTRAL_BANKS + ["Currency and Coin"], "Appendix II-a p.86"),
    (["I.S.4"], "Sub-Product", ["Level 1 Pledged", "Level 2a Pledged", "Level 2b Pledged", "Non-HQLA Pledged", "No Collateral Pledged"], "Appendix II-a p.86"),
    (["O.S.4"], "Sub-Product", ["Level 1 Received", "Level 2a Received", "Level 2b Received", "Non-HQLA Received", "No Collateral Received"], "Appendix II-a p.86"),
    (["O.S.6"], "Sub-Product", CENTRAL_BANKS + ["Covered Federal Reserve Facility Funding"], "Appendix II-a p.86"),
    (["O.S.7", "O.S.8"], "Sub-Product", ["External Cash Transactions", "External Non-Cash Transactions", "Firm Longs",
                                          "Customer Longs", "Unsettled - Regular Way", "Unsettled - Forward"], "Appendix II-a p.87"),
    (["O.S.9", "O.S.10"], "Sub-Product", ["Firm Short", "Synthetic Customer Long", "Synthetic Firm Sourcing", "Futures", "Other", "Unhedged"], "Appendix II-a p.87"),
    (["I.S.9", "I.S.10"], "Sub-Product", ["Physical Long Position", "Synthetic Customer Short", "Synthetic Firm Financing", "Futures", "Other", "Unhedged"], "Appendix II-a p.87"),
    ([f"S.DC.{n}" for n in range(3, 11)], "Sub-Product", ["Rehypothecateable Collateral Unencumbered", "Rehypothecateable Collateral Encumbered",
                                                          "Non-Rehypothecateable Collateral", "Segregated Cash", "Non-Segregated Cash"], "Appendix II-a p.87; S.DC guidance p.64"),
    ([f"S.DC.{n}" for n in range(1, 11)], "Sub-Product2", ["OTC - Bilateral", "OTC - Centralized (Principal)", "OTC - Centralized (Agent)",
                                                           "Exchange-traded (Principal)", "Exchange-traded (Agent)"], "Appendix II-a p.87; S.DC guidance p.64-65"),
]

# ---------------------------------------------------------------------------
# Counterparty types (Field Definitions p.17-21; Municipalities for VRDN Structures is O.O.5 only, footnote 8).
# Spelled as in the 6G XSD counterpartySector enumerations ("Financial Market Utlility" is the Fed's spelling).
# ---------------------------------------------------------------------------
COUNTERPARTIES = [
    ("Retail", "Retail", False), ("Small Business", "Retail", False),
    ("Non-Financial Corporate", "Wholesale Non-Financial", False), ("Sovereign", "Wholesale Non-Financial", False),
    ("Central Bank", "Wholesale Non-Financial", False), ("Government Sponsored Entity", "Wholesale Non-Financial", False),
    ("Public Sector Entity", "Wholesale Non-Financial", False), ("Multilateral Development Bank", "Wholesale Non-Financial", False),
    ("Other Supranational", "Wholesale Non-Financial", False), ("Pension Fund", "Financial", True), ("Bank", "Financial", True),
    ("Broker Dealer", "Financial", True), ("Investment Company or Advisor", "Financial", True),
    ("Financial Market Utlility", "Financial", True), ("Other Supervised Non-Bank Financial Entity", "Financial", True),
    ("Debt Issuing Special Purpose Entity", "Financial", True), ("Non-regulated Fund", "Financial", True),
    ("Municipalities for VRDN Structures", "Wholesale Non-Financial", False), ("Other", "Other", False),
]
ALL_CPTY = [c[0] for c in COUNTERPARTIES]
MUNI = "Municipalities for VRDN Structures"

# Appendix II-b (p.88-90): products that REQUIRE a counterparty, with the applicable values.
CPTY_GROUPS = [
    (["O.O.5"], ALL_CPTY, "p.88"),
    (["I.U.5", "I.U.6", "I.S.5", "I.S.6", "I.S.7", "I.S.8"] + [f"O.D.{n}" for n in range(7, 16)]
     + ["O.S.7", "O.W.18", "O.O.4", "S.DC.1", "S.DC.2"] + [f"S.DC.{n}" for n in range(5, 11)] + ["S.B.5"],
     [c for c in ALL_CPTY if c != MUNI], "p.88"),
    (["I.S.1", "I.S.2", "I.S.3", "I.S.4", "I.S.9", "I.S.10", "I.U.1", "I.U.2", "I.U.3", "I.U.4", "I.U.7", "I.U.8",
      "O.D.4", "O.D.5", "O.D.6", "O.S.1", "O.S.2", "O.S.3", "O.S.4", "O.S.9", "O.S.10", "O.S.11", "O.W.9", "O.W.10",
      "S.FX.1", "S.FX.2", "S.FX.3"],
     [c for c in ALL_CPTY if c not in ("Retail", "Small Business", MUNI)], "p.89"),
    (["O.D.1", "O.D.2", "O.D.3"], ["Retail", "Small Business"], "p.89"),
    (["O.S.5"], ["Government Sponsored Entity"], "p.89"),
    (["O.S.6"], ["Central Bank"], "p.90"),
]

# ---------------------------------------------------------------------------
# Appendix II-d (p.95-97): products that must not carry Forward Start Bucket / Forward Start Amount.
# (p.97 heads the S.B rows "Supplemental - Informational"; they are the S.B products.)
# ---------------------------------------------------------------------------
FWD_EXCLUDED = (["I.A.1", "I.A.2", "I.A.3", "I.A.4", "I.A.7", "I.U.3", "I.U.4", "I.U.7", "I.U.8"]
                + [f"I.O.{n}" for n in range(1, 10)] + ["O.W.18"] + [f"O.D.{n}" for n in range(1, 16)]
                + [f"O.O.{n}" for n in range(1, 23)] + [f"S.DC.{n}" for n in range(1, 22)]
                + [f"S.L.{n}" for n in range(1, 11)] + [f"S.B.{n}" for n in range(1, 7)] + [f"S.I.{n}" for n in range(1, 7)])

# ---------------------------------------------------------------------------
# Appendix III (p.98-100): asset categories
# ---------------------------------------------------------------------------
_Q = [
    ("A-0-Q", "Cash", "Level 1"),
    ("A-1-Q", "Debt issued by the U.S. Treasury", "Level 1"),
    ("A-2-Q", "U.S. Government Agency-issued debt (excluding the US Treasury) with a US Government guarantee", "Level 1"),
    ("A-3-Q", "Vanilla debt (including pass-through MBS) guaranteed by a U.S. Government Agency, where the U.S. Government Agency has a full U.S. Government guarantee", "Level 1"),
    ("A-4-Q", "Structured debt (excluding pass-through MBS) guaranteed by a U.S. Government Agency, where the U.S. Government Agency has a full U.S. Government guarantee", "Level 1"),
    ("A-5-Q", "Other debt with a U.S. Government guarantee", "Level 1"),
    ("S-1-Q", "Debt issued by non-U.S. Sovereigns (excluding central banks) with a 0% RW", "Level 1"),
    ("S-2-Q", "Debt issued by multilateral development banks or other supranationals with a 0% RW", "Level 1"),
    ("S-3-Q", "Debt with a non-U.S. sovereign (excluding central banks) or multilateral development bank or other supranational guarantee, where guaranteeing entity has a 0% RW", "Level 1"),
    ("S-4-Q", "Debt issued or guaranteed by a non-U.S. Sovereign (excluding central banks) that does not have a 0% RW, but supports outflows that are in the same jurisdiction of the sovereign and are denominated in the home currency of the sovereign", "Level 1"),
    ("CB-1-Q", "Securities issued or guaranteed by a central bank with a 0% RW", "Level 1"),
    ("CB-2-Q", "Securities issued or guaranteed by a non-U.S. central bank that does not have a 0% RW, but supports outflows that are in the same jurisdiction of the central bank and are denominated in the home currency of the central bank", "Level 1"),
    ("G-1-Q", "Senior to preferred debt issued by a U.S. Government Sponsored Entity (GSE)", "Level 2A"),
    ("G-2-Q", "Vanilla debt (including pass-through MBS) guaranteed by a U.S. GSE", "Level 2A"),
    ("G-3-Q", "Structured debt (excluding pass-through MBS) guaranteed by a U.S. GSE", "Level 2A"),
    ("S-5-Q", "Debt issued by non-U.S. Sovereigns (excluding central banks) with a 20% RW, not otherwise included", "Level 2A"),
    ("S-6-Q", "Debt issued by multilateral development banks or other supranationals with a 20% RW, not otherwise included", "Level 2A"),
    ("S-7-Q", "Debt with a non-U.S. sovereign (excluding central banks) or multilateral development bank or other supranational guarantee, where guaranteeing entity has a 20% RW, not otherwise included", "Level 2A"),
    ("CB-3-Q", "Securities issued or guaranteed by a non-U.S. central bank with a 20% RW, not otherwise included", "Level 2A"),
    ("E-1-Q", "U.S. equities - Russell 1000", "Level 2B"),
    ("E-2-Q", "Non-U.S. Equities listed on a foreign index designated to by the local supervisor as qualifying for the LCR, and denominated in USD or the currency of outflows that the foreign entity is supporting", "Level 2B"),
    ("IG-1-Q", "Investment grade corporate debt", "Level 2B"),
    ("IG-2-Q", "Investment grade municipal obligations", "Level 2B"),
]
_NON_Q_OVERRIDES = {"IG-2": "Investment grade U.S. municipal general obligations"}
_OTHER = [
    ("S-8", "All other debt issued by sovereigns (excluding central banks) and supranational entities, not otherwise included"),
    ("CB-4", "All other securities issued by central banks, not otherwise included"),
    ("G-4", "Debt, other than senior or preferred, issued by a U.S. GSE"),
    ("E-3", "All other U.S.-listed common equity securities"), ("E-4", "All other non-US-listed common equity securities"),
    ("E-5", "ETFs listed on US exchanges"), ("E-6", "ETFs listed on non-US exchanges"),
    ("E-7", "US mutual fund shares"), ("E-8", "Non-US mutual fund shares"),
    ("E-9", "All other US equity investments (including preferred shares, warrants and options)"),
    ("E-10", "All other non-US equity investments (including preferred shares, warrants and options)"),
    ("IG-3", "Investment grade Vanilla ABS"), ("IG-4", "Investment grade Structured ABS"),
    ("IG-5", "Investment grade Private label Pass-thru CMBS/RMBS"), ("IG-6", "Investment grade Private label Structured CMBS/RMBS"),
    ("IG-7", "Investment grade covered bonds"), ("IG-8", "Investment grade obligations of municipals/PSEs (excluding U.S. general obligations)"),
    ("N-1", "Non-investment grade general obligations issued by U.S. municipals/PSEs"), ("N-2", "Non-investment grade corporate debt"),
    ("N-3", "Non-investment grade Vanilla ABS"), ("N-4", "Non-investment grade structured ABS"),
    ("N-5", "Non-investment grade Private label Pass-thru CMBS/RMBS"), ("N-6", "Non-investment grade Private label Structured CMBS/RMBS"),
    ("N-7", "Non-investment grade covered bonds"), ("N-8", "Non-investment grade obligations of municipals/PSEs (excluding U.S. general obligations)"),
    ("L-1", "GSE-eligible conforming residential mortgages"), ("L-2", "Other GSE-eligible loans"),
    ("L-3", "Other 1-4 family residential mortgages"), ("L-4", "Other multi family residential mortgages"),
    ("L-5", "Home equity loans"), ("L-6", "Credit card loans"), ("L-7", "Auto loans and leases"),
    ("L-8", "Other consumer loans and leases"), ("L-9", "Commercial real estate loans"),
    ("L-10", "Commercial and industrial loans"), ("L-11", "All other loans, except loans guaranteed by U.S. government agencies"),
    ("L-12", "Loans guaranteed by U.S. government agencies"),
    ("Y-1", "Debt issued by reporting firm - parent"), ("Y-2", "Debt issued by reporting firm - bank"),
    ("Y-3", "Debt issued by reporting firm - all other (incl. conduits)"), ("Y-4", "Equity investment in affiliates"),
    ("C-1", "Commodities"), ("P-1", "Residential property"), ("P-2", "All other physical property"),
    ("LC-1", "Letters of credit issued by a GSE"), ("LC-2", "All other letters of credit, including bankers' acceptances"),
    ("Z-1", "All other assets"),
]
HAIRCUT = {"Level 1": "0.0000", "Level 2A": "0.1500", "Level 2B": "0.5000"}

# ---------------------------------------------------------------------------
# Appendix IV-a (p.101): 76 maturity buckets. maturity_start / maturity_end are the 6G <maturityStart> /
# <maturityEnd> durations ("Maturity bucket values" tab): >4-5 Yr ends at P1826D and >5 Yr starts at P1827D.
# ---------------------------------------------------------------------------
def maturity_buckets():
    rows = [("Open", "P0D", "P0D", 0, 0, "Open")]
    rows += [(f"Day {d}", f"P{d}D", f"P{d}D", d, d, "Daily") for d in range(1, 61)]
    for label, a, b, typ in [("61 - 67 Days", 61, 67, "Weekly"), ("68 - 74 Days", 68, 74, "Weekly"),
                             ("75 - 82 Days", 75, 82, "Weekly"), ("83 - 90 Days", 83, 90, "Weekly"),
                             ("91 - 120 Days", 91, 120, "30-Day"), ("121 - 150 Days", 121, 150, "30-Day"),
                             ("151 - 179 Days", 151, 179, "30-Day"), ("180 - 270 Days", 180, 270, "90-Day"),
                             ("271 - 364 Days", 271, 364, "90-Day")]:
        rows.append((label, f"P{a}D", f"P{b}D", a, b, typ))
    rows += [(">= 1 Yr <= 2 Yr", "P365D", "P730D", 365, 730, "Yearly"),
             (">2 Yr <= 3 Yr", "P731D", "P1095D", 731, 1095, "Yearly"),
             (">3 Yr <= 4 Yr", "P1096D", "P1460D", 1096, 1460, "Yearly"),
             (">4 Yr <= 5 Yr", "P1461D", "P1826D", 1461, 1826, "Yearly"),
             (">5 Yr", "P1827D", "", 1827, 99998, "Yearly"),
             ("Perpetual", "P99999D", "", None, None, "Perpetual")]
    out = []
    for seq, (label, ms, me, a, b, typ) in enumerate(rows):
        out.append([seq, label, ms, me, "" if a is None else a, "" if b is None else b, typ,
                    "true" if a is not None and b is not None and b <= 30 else "false", "true"])
    # IV-b (3)(b): Category IV <$50B wSTWF may split I.U.6 / I.S.7 loan cash flows into two aggregate buckets.
    # The 6G XSD has no durations for these two aggregates; they are not used by the CAT_I_II profile.
    out.append([76, "<= 30 Days", "", "", 1, 30, "Tailored aggregate", "true", "false"])
    out.append([77, "> 30 Days", "", "", 31, 99998, "Tailored aggregate", "false", "false"])
    return out


def tailoring(buckets):
    std = [b[1] for b in buckets if b[8] == "true"]
    within_1y = std[:70]  # Open + 60 daily + 4 weekly + 3 thirty-day + 2 ninety-day
    rows = []
    def add(profile, desc, scope, labels):
        for lab in labels:
            rows.append([profile, desc, scope, lab])
    p1 = ("CAT_I_II", "U.S. Category I/II; FBO Category II - all products use the 76 maturity buckets (IV-b (1))")
    add(*p1, "ALL", std)
    p2 = ("CAT_III_IV_GE50", "U.S./FBO Category III or IV with wSTWF >= $50B (IV-b (2))")
    add(*p2, "OUTFLOW_SUPPLEMENTAL", within_1y + [">= 1 Yr <= 2 Yr", "Perpetual"])
    add(*p2, "INFLOW", within_1y + [">5 Yr", "Perpetual"])
    p3 = ("CAT_IV_LT50", "U.S./FBO Category IV with wSTWF < $50B (IV-b (3))")
    add(*p3, "I.A.1,I.A.2,I.A.7", ["Open", "271 - 364 Days", ">5 Yr", "Perpetual"])
    add(*p3, "I.U.6,I.S.7", ["<= 30 Days", "> 30 Days"])
    add(*p3, "INFLOW", within_1y + [">5 Yr", "Perpetual"])
    add(*p3, "OUTFLOW_SUPPLEMENTAL", within_1y + [">= 1 Yr <= 2 Yr", "Perpetual"])
    return rows

# ---------------------------------------------------------------------------
# Appendix V (p.103-105): double counting. check_type drives notebook 04:
#   LINKED   - every products_a position (comparison ALL) or every Open-bucket products_a position (OPEN) must carry a
#              link_id that also appears on a products_b position; TAGGED - products_a positions that carry a link_id
#              must resolve to products_b and be reported with Unencumbered = false
#   NET30    - I.O.7 / O.O.20 must equal the net of the listed <=30-day derivative-type flows
#   MONOTONIC- cumulative downgrade amounts must be non-decreasing in the listed order
#   SUBSET   - products_a total must not exceed products_b total
#   ENTITY   - consolidated vs subsidiary reporting entities
# ---------------------------------------------------------------------------
DOUBLE_COUNTING = [
    (1, "Third-party exposures at subsidiaries that are reporting entities are reported for the consolidated entity and the subsidiary reporting entity", "ENTITY", "", "", ""),
    (2, "Collateral swaps are reported in both Inflows-Secured and Outflows-Secured", "LINKED", "I.S.4", "O.S.4", "ALL"),
    (3, "Collateral received via secured lending and pre-positioned at a central bank or GSE appears in I.S (Unencumbered = false) and I.A.2 Capacity", "LINKED", "I.S.1,I.S.2,I.S.3,I.S.5,I.S.6,I.S.7,I.S.8", "I.A.2", "TAGGED"),
    (4, "Loans and leases are reported in I.U / I.S by counterparty and in the I.A table at market value", "LINKED", "I.U.5,I.U.6,I.S.5,I.S.6,I.S.7,I.S.8", "I.A.1,I.A.2,I.A.7", "ALL"),
    (5, "Encumbered assets are reported under I.A.7 and under the product they are encumbered to in O.W, O.S or S.DC (Collateral Value / Market Value)", "LINKED", "I.A.7", "O.W.1,O.W.2,O.W.3,O.W.4,O.W.5,O.W.6,O.W.7,O.S.1,O.S.2,O.S.3,O.S.4,O.S.5,O.S.6,O.S.11,S.DC.5,S.DC.8,S.DC.11,S.DC.12", "ALL"),
    (6, "Unsecured derivative cash flows over the next 30 days are in I.O.1 / O.O.1 and in the I.O.7 / O.O.20 net", "NET30", "I.O.1", "O.O.1", ""),
    (7, "Derivative collateral flows over the next 30 days are in I.O.2 / O.O.2 and in the I.O.7 / O.O.20 net", "NET30", "I.O.2", "O.O.2", ""),
    (8, "FX transactions maturing over the next 30 days are in S.FX.1-3 and in the I.O.7 / O.O.20 net", "NET30", "S.FX.1,S.FX.2,S.FX.3", "S.FX.1,S.FX.2,S.FX.3", ""),
    (9, "Forward purchases (I.A.6) and sales (O.S.8 Unsettled - Forward) over the next 30 days are in the I.O.7 / O.O.20 net", "NET30", "O.S.8", "I.A.6", ""),
    (10, "Debt maturing beyond 30 days where the firm is primary market maker is in O.W and in S.L.4 / S.L.5", "LINKED", "S.L.4,S.L.5", "O.W.11,O.W.12,O.W.14,O.W.15", "ALL"),
    (11, "O.O.13-O.O.16 Total Collateral Required are cumulative: 1 notch <= 2 notch <= 3 notch <= change in financial condition", "MONOTONIC", "O.O.13,O.O.14,O.O.15,O.O.16", "", ""),
    (12, "O.O.9-O.O.12 Loss of Rehypothecation Rights are cumulative: 1 notch <= 2 notch <= 3 notch <= change in financial condition", "MONOTONIC", "O.O.9,O.O.10,O.O.11,O.O.12", "", ""),
    (13, "I.O.2 Collateral Called for Receipt with Maturity Bucket Open is also in the stock of S.DC.7 / S.DC.10", "LINKED", "I.O.2", "S.DC.7,S.DC.10", "OPEN"),
    (14, "O.O.2 Collateral Called for Delivery with Maturity Bucket Open is also in the stock of S.DC.5 / S.DC.6 / S.DC.8 / S.DC.9", "LINKED", "O.O.2", "S.DC.5,S.DC.6,S.DC.8,S.DC.9", "OPEN"),
    (15, "S.DC.14 Collateral Disputes Receivables is also reflected in I.O.2", "LINKED", "S.DC.14", "I.O.2", "ALL"),
    (16, "S.DC.13 Collateral Disputes Deliverables is also reflected in O.O.2", "LINKED", "S.DC.13", "O.O.2", "ALL"),
    (17, "S.DC.17 Sleeper Collateral Receivables is included in S.DC.5 / S.DC.6 / S.DC.8 / S.DC.9", "SUBSET", "S.DC.17", "S.DC.5,S.DC.6,S.DC.8,S.DC.9", ""),
    (18, "S.DC.15 Sleeper Collateral Deliverables is included in S.DC.7 / S.DC.10", "SUBSET", "S.DC.15", "S.DC.7,S.DC.10", ""),
    (19, "S.L.1, S.L.2, S.L.7, S.L.8 and S.I.6 correspond to amounts reported elsewhere in the submission", "LINKED", "S.L.1,S.L.2,S.L.7,S.L.8,S.I.6", "I.A.1,I.A.2,I.A.3,O.D.1,O.D.2,O.D.3,O.D.4,O.D.5,O.D.6,O.W.9,O.W.11", "ALL"),
    (20, "O.D.12 Other Product Sweep Accounts are also reported in the product the funds are swept into", "LINKED", "O.D.12", "O.D.1,O.D.2,O.D.3,O.D.4,O.D.5,O.D.6,O.D.9,O.D.10,O.D.11,O.W.8,O.W.16,O.W.19", "ALL"),
    (21, "I.O.8 Principal Payments on Unencumbered Investment Securities: the securities are also in I.A.1 / I.A.2", "LINKED", "I.O.8", "I.A.1,I.A.2", "ALL"),
]

# ---------------------------------------------------------------------------
# 6G schema package: XSD layout, enumerations and the Business Requirements workbook
# ---------------------------------------------------------------------------
XS = "{http://www.w3.org/2001/XMLSchema}"
XNS = {"xs": XS[1:-1]}
BR_FILE = "6G Business Requirements_for distribution_2021.12.28.xlsx"
# Report-type tabs in the BR workbook (tab names are truncated by Excel)
BR_TABS = {"assetInflowReport": "I.A", "unsecuredInflowReport": "I.U", "securedInflowReport": "I.S", "otherInflowReport": "I.O",
           "depositsOutflowReport": "O.D", "wholesaleOutflowReport": "O.W", "securedOutflowReport": "O.S", "otherOutflowReport": "O.O",
           "informationalSupplementalReport": "S.I", "derivativesAndCollateraSuReport": "S.DC", "liquidityRiskMeasurementSup": "S.L",
           "balanceSheetSupReport": "S.B", "foreignExchangeSupplementalRepo": "S.FX", "sixGComments": "S.C", "header": ""}
# Spec field names whose 6G element name is not the generic FIELD_MAP one
XML_OVERRIDES = {("S.FX", "Forward Start Bucket"): "forwardMaturityBucket"}
# XSD types whose values are firm specific (firm include XSD) or covered by their own reference table
FIRM_TYPES = {"reportScope", "internalCounterparty", "businessLine", "reporterList", "exchangeList"}
OWN_TABLE_TYPES = {"collateralClass", "productReference", "subProductReference"}


class Schema6G:
    """Reads 6GSchema.xsd and the Business Requirements workbook."""

    def __init__(self, folder):
        self.xsd = etree.parse(os.path.join(folder, "6GSchema.xsd"))
        self.wb = openpyxl.load_workbook(os.path.join(folder, BR_FILE), read_only=True, data_only=True)

    def tab(self, name):
        rows = list(self.wb[name].iter_rows(values_only=True))
        return [[("" if c is None else str(c).strip()) for c in r] for r in rows[1:] if r and r[0] is not None]

    def simple(self, name):
        return self.xsd.find(f".//xs:simpleType[@name='{name}']", XNS)

    def enum(self, name):
        """Enumeration values of a simple type (following unions); None if it is not an enumerated type."""
        st = self.simple(name)
        if st is None:
            return None
        vals = [e.get("value") for e in st.findall("xs:restriction/xs:enumeration", XNS)]
        u = st.find("xs:union", XNS)
        if u is not None:
            for m in u.get("memberTypes").split():
                vals += self.enum(m) or []
        return vals or None

    def layout(self, report_type):
        """Ordered (kind, name, xsd type, required) for a report element: reportBase first, then the extension."""
        el = self.xsd.find(f"./xs:element[@name='{report_type}']", XNS)
        out = []
        def walk(node):
            for c in node:
                if not isinstance(c.tag, str):
                    continue
                tag = etree.QName(c).localname
                if tag == "element":
                    out.append(("element", c.get("name"), c.get("type"), c.get("minOccurs", "1") != "0"))
                elif tag == "attribute":
                    out.append(("attribute", c.get("name"), c.get("type"), c.get("use") == "required"))
                elif tag == "extension":
                    walk(self.xsd.find(f".//xs:complexType[@name='{c.get('base')}']", XNS))
                    walk(c)
                else:
                    walk(c)
        walk(el)
        return out

    def value_kind(self, xsd_type):
        if xsd_type == "valueType":
            return "amount"
        if xsd_type == "anyValueType":
            return "signed_amount"
        if xsd_type == "maturityBucket":
            return "bucket"
        if xsd_type == "xs:boolean":
            return "boolean"
        if xsd_type in ("xs:decimal", "decimalValue"):
            return "decimal"
        if xsd_type in FIRM_TYPES:
            return "firm_enum"
        if xsd_type in ("xs:string", "xs:date"):
            return xsd_type.split(":")[1]
        if xsd_type == "tenDigitPositiveIntegerType":
            return "report_id"
        return "enum" if self.enum(xsd_type) else "string"


def xsd_layout_rows(g6):
    rows = []
    for code, _, _, _, rt, *_ in TABLES:
        if code == "S.C":
            continue
        for seq, (kind, name, typ, req) in enumerate(g6.layout(rt), 1):
            rows.append([code, rt, seq, kind, name, typ, "true" if req else "false", g6.value_kind(typ)])
    return rows


def field_values_6g(g6, fields):
    """Allowed values per table and field, from the XSD enumerations of each report type (+ G-SIB from the BR)."""
    names = {(f[0], f[4]): f[2] for f in fields}
    out, seen = [], set()
    for code, _, _, _, rt, prod_el, sub_el, _ in TABLES:
        if code == "S.C":
            continue
        for kind, el, typ, _ in g6.layout(rt):
            field = names.get((code, el))
            if field is None or el in (prod_el, sub_el, "executionAndClearingMechanism") or typ in FIRM_TYPES | OWN_TABLE_TYPES:
                continue
            for v in g6.enum(typ) or []:
                if (field, code, v) not in seen:
                    seen.add((field, code, v))
                    out.append([field, code, v, f"6GSchema.xsd {typ}"])
    for v in g6.enum("currencyUnit"):
        out.append(["Currency", "ALL", v, "6GSchema.xsd currencyUnit - other currencies are converted to USD with Converted = true (p.16)"])
    for r in g6.tab("Enumerations"):
        if r[2] == "gsib":
            out.append(["G-SIB", "ALL", r[5], "6G BR Enumerations - FSB 2020 G-SIB list (enforced by FRS, not the XSD)"])
    return out


def subproducts_6g(g6, pids_by_name):
    """Appendix II-a combinations from the BR 'Prod-SubProd-SubProd2' tab. required_by_instructions marks the products
    whose Sub-Product the Instructions require (FRS itself only rejects unexpected values)."""
    required = {pid for plist, field, _, _ in SUBPRODUCTS if field == "Sub-Product" and not plist[0].startswith("S.DC") for pid in plist}
    rt_code = {t[4]: t[0] for t in TABLES}
    out = []
    for r in g6.tab("Prod-SubProd-SubProd2"):
        code = rt_code[r[1]]
        pid = f"{code}.{r[2]}"
        assert pids_by_name[pid] == r[3], (pid, r[3])
        for field, v in (("Sub-Product", r[4]), ("Sub-Product2", r[5] if len(r) > 5 else "")):
            if v and v != "No dependency on Sub-Product":
                out.append([pid, field, v, "true" if field == "Sub-Product" and pid in required else "false",
                            "6G BR Prod-SubProd-SubProd2; Appendix II-a p.86-87"])
    return out


BR_CATEGORIES = [  # (pattern in the rule text, category, enforced_by)
    ("not Empty", "NOT_EMPTY", "XSD"), ("is Positive", "POSITIVE", "XSD"), ("max length", "MAX_LENGTH", "XSD"),
    ("reportID is unique", "UNIQUE_ID", "FRS"), ("boolean", "BOOLEAN", "XSD"), ("not Negative", "NON_NEGATIVE", "XSD"),
    ("Max value", "MAX_AMOUNT", "FRS"), ("Converted is true", "CONVERTED_USD", "FRS"), ("value = 6", "UNIT_MULTIPLIER", "XSD"),
    ("Comment Text", "COMMENT_CHARS", "FRS"), ("Range combination", "MATURITY_RANGE", "FRS"),
    ("Less or Equal", "FORWARD_MATURITY", "FRS"), ("= ZERO", "ZERO_REJECTION", "FRS"), ("Appendix II", "COLLATERAL_REQUIRED", "FRS"),
    ("'Counterparty Required'", "COUNTERPARTY_REQUIRED", "FRS"), ("G-SIB value is provided", "GSIB_WITH_COUNTERPARTY", "FRS"),
    ("Financial Stability Board", "GSIB_LIST", "FRS"), ("Risk Weight", "RISK_WEIGHT", "FRS"), ("Category 1 Firms", "BUSINESS_LINE", "FRS"),
    ("Collection Reference' field, File", "REFERENCE_NEEDS_COLLECTION", "FRS"), ("Sub-Product Reference field", "SUBPRODUCT_REFERENCE", "FRS"),
    ("Product Reference field", "PRODUCT_REFERENCE", "FRS"), ("Sub-Product is provided", "SUBPRODUCT_COMBINATION", "FRS"),
    ("Sub-Product 2 is provided", "SUBPRODUCT_COMBINATION", "FRS"), ("expected Sub-Product", "ENUMERATION", "XSD"),
    ("expected Product", "ENUMERATION", "XSD"), ("correspond to the reported Collection", "PRODUCT_MATCH", "FRS"),
    ("Enumeration list", "ENUMERATION", "XSD"),
]


def br_rules(g6):
    """The 652 rules on the 15 BR report / header tabs, classified by what checks them: XSD = schema validation of the
    generated file, FRS = Fed application rule implemented in the validation notebook."""
    out = []
    for tab, code in BR_TABS.items():
        hdr = [("" if c is None else " ".join(str(c).split())) for c in next(g6.wb[tab].iter_rows(values_only=True))]
        pos = lambda prefix, nth=0: [i for i, h in enumerate(hdr) if h.startswith(prefix)][nth] if sum(h.startswith(prefix) for h in hdr) > nth else None
        col = {"name": pos("XML Element or Attribute"), "type": pos("XML Element or Attribute", 1), "child": pos("XML Child Element"),
               "required": pos("Required"), "rule": pos("Validation rule"), "enum": pos("Enumeration list")}
        cell = lambda r, k: r[col[k]] if col[k] is not None and col[k] < len(r) else ""
        for r in g6.tab(tab):
            text = cell(r, "rule")
            cat, by = next(((c, b) for pat, c, b in BR_CATEGORIES if pat.lower() in text.lower()), ("SCHEMA", "XSD"))
            if cat == "ENUMERATION" and cell(r, "type") in FIRM_TYPES:
                by = "XSD"   # firm include XSD enumeration
            rejects = "reject" in text.lower() or by == "XSD" or cat in ("UNIQUE_ID", "MATURITY_RANGE", "FORWARD_MATURITY")
            prefix = ("CHDR" if "commentsHeader" in r[1] else "HDR") if tab == "header" else code.replace(".", "")
            out.append([f"BR-{prefix}-{int(r[0]):03d}", r[1], code, int(r[0]), r[2], cell(r, "name"), cell(r, "child"),
                        cell(r, "required"), cell(r, "type"), text, cell(r, "enum"), cat, by, "ERROR" if rejects else "WARNING", "6G"])
    return out



# ---------------------------------------------------------------------------
# Appendix VII (STWF to FR 2052a mapping): FR Y-15 Schedule G items computed from FR 2052a data elements
# ---------------------------------------------------------------------------
STWF_ITEMS = {  # item -> (Y-15 Schedule G name, tier weight per 12 CFR 217.406 category, first MDRM item code of columns A-D)
    "1.a": ("Funding secured by level 1 liquid assets", 0.25, 838), "1.b": ("Retail brokered deposits and sweeps", 0.25, 842),
    "1.c": ("Unsecured wholesale funding obtained outside the financial sector", 0.25, 846),
    "1.d": ("Firm short positions involving level 2B liquid assets or non-HQLA", 0.25, 850),
    "2.a": ("Funding secured by level 2A liquid assets", 0.50, 858), "2.b": ("Covered asset exchanges (level 1 to level 2A)", 0.50, 862),
    "3.a": ("Funding secured by level 2B liquid assets", 0.75, 870), "3.b": ("Other covered asset exchanges", 0.75, 874),
    "3.c": ("Unsecured wholesale funding obtained within the financial sector", 0.75, 878),
    "4": ("All other components of short-term wholesale funding", 1.00, 886),
}
STWF_TOTALS = {"1": 854, "2": 866, "3": 882}
CP_ALIASES = {"GSE": "Government Sponsored Entity", "PSE": "Public Sector Entity", "MDB": "Multilateral Development Bank",
              "Debt Issuing SPE": "Debt Issuing Special Purpose Entity", "Broker-Dealer": "Broker Dealer",
              "Financial Market Utility": "Financial Market Utlility", "Non- Regulated Fund": "Non-regulated Fund",
              "Non-Regulated Fund": "Non-regulated Fund"}
SUB_ALIASES = {"External Cash Transaction": "External Cash Transactions", "External Non-Cash Transaction": "External Non-Cash Transactions",
               "Level 2b Pledged": "Level 2b Pledged", "Non-HQLA Pledged": "Non-HQLA Pledged"}


def _appendix_vii_blocks(doc):
    pages = [doc[i].get_text() for i in range(len(doc))]
    norm = lambda t: t.replace("‐", "-").replace("‐", "-")
    start = next(i for i, t in enumerate(pages) if "APPENDIX VII: Short" in norm(t))
    end = next(i for i, t in enumerate(pages) if i > start and "APPENDIX VIII: NSFR" in norm(t))
    lines = [l.strip() for l in norm("\n".join(pages[start:end])).split("\n")]
    fields = sorted(["Reporting Entity", "PID", "Product", "Sub-product", "Sub-Product", "Counterparty", "G-SIB", "Maturity Amount",
                     "Maturity Bucket", "Maturity Optionality", "Forward Start Amount", "Forward Start Bucket", "Collateral Class",
                     "Collateral Value", "Treasury Control", "Internal Counterparty", "Internal", "Risk Weight", "Business Line", "Settlement",
                     "Rehypothecated", "Effective Maturity Bucket", "Market Value", "Lendable Value", "Encumbrance Type", "Trigger", "Insured",
                     "Loss Absorbency", "Unencumbered", "CID"], key=len, reverse=True)
    blocks, cur, field = [], None, None
    for l in lines:
        m = re.match(r"\((\d+)\) ([A-Z]\.[A-Z]+)\.? PIDs for item ([0-9.a-d]+)", l)
        if m:
            cur = {"table": int(m.group(1)), "collection": m.group(2), "item": m.group(3), "fields": {}}
            blocks.append(cur)
            field = None
            continue
        if cur is None or not l or l == "Field Value" or re.fullmatch(r"\d+", l) or l.startswith("Item "):
            continue
        f = next((f for f in fields if l.startswith(f + " ") or l == f), None)
        if f:
            field = "Sub-Product" if f == "Sub-product" else f
            cur["fields"][field] = l[len(f):].strip()
        elif field:
            cur["fields"][field] += " " + l
    return [b for b in blocks if b["item"] in STWF_ITEMS]


def _pids(text, collection):
    out = []
    for part in re.split(r",|\band\b", text.replace(collection + ".", "")):
        part = part.strip()
        if re.fullmatch(r"\d+\s*-\s*\d+", part):
            a, b = [int(x) for x in re.split(r"\s*-\s*", part)]
            out += [f"{collection}.{n}" for n in range(a, b + 1)]
        elif part.isdigit():
            out.append(f"{collection}.{part}")
    return out


def _cp_cond(text):
    text = re.sub(r"\s+", " ", text.strip().rstrip(")")).strip()
    text = re.sub(r"#.*$", "#", text) if text.startswith("#") else text
    if text in ("", "#"):
        return None
    if text == "Not Retail or Small Business":
        return "COALESCE(counterparty, '') NOT IN ('Retail', 'Small Business')"
    if text == "Retail or Small Business":
        return "counterparty IN ('Retail', 'Small Business')"
    allow_null = text.endswith("or NULL")
    names = [n.strip() for n in re.split(r",\s*", text.replace(", or NULL", "").replace(" or NULL", "")) if n.strip()]
    names = [CP_ALIASES.get(n, n) for n in names]
    cond = "counterparty IN (" + ", ".join(f"'{n}'" for n in names) + ")"
    return f"({cond} OR counterparty IS NULL)" if allow_null else cond


def _cc_cond(text):
    t = re.sub(r"\s+", " ", text.strip())
    return {"Level 1 HQLA": "hqla_level = 'Level 1'", "Level 2A HQLA": "hqla_level = 'Level 2A'", "Level 2B HQLA": "hqla_level = 'Level 2B'",
            "Level 2B HQLA or Non-HQLA": "(hqla_level = 'Level 2B' OR (collateral_class IS NOT NULL AND NOT is_hqla))",
            # "Other" read as Appendix III class Z-1 (All other assets); "Non-HQLA" as the remaining non-HQLA classes
            "NULL or Other": "(collateral_class IS NULL OR collateral_class = 'Z-1')", "Other": "collateral_class = 'Z-1'",
            "Non-HQLA": "(collateral_class IS NOT NULL AND NOT is_hqla AND collateral_class <> 'Z-1')", "#": None, "": None}[t]


def stwf_rules(doc):
    """One row per Appendix VII table (split where the appendix gives conditions per sub-product or PID group)."""
    rows = []
    for b in _appendix_vii_blocks(doc):
        f = {k: re.sub(r"\s+", " ", v).strip() for k, v in b["fields"].items()}
        coll = b["collection"]
        pid_sets = [(None, _pids(f["PID"], coll))]
        cps = [_cp_cond(f.get("Counterparty", "#"))]
        if f.get("Counterparty", "").startswith("For O.W.1 - 8"):   # table 19: counterparty condition differs by PID group
            unrestricted = [p for p in pid_sets[0][1] if int(p.rsplit(".", 1)[1]) in list(range(1, 9)) + list(range(11, 17))]
            pid_sets = [("a", unrestricted), ("b", [p for p in pid_sets[0][1] if p not in unrestricted])]
            cps = [None, _cp_cond(f["Counterparty"].split("19:", 1)[1])]
        conds = []
        sub = f.get("Sub-Product", "#")
        if sub.startswith("For O.S.7"):
            conds.append("(product_id <> 'O.S.7' OR COALESCE(sub_product, '') NOT IN ('Unsettled - Regular Way', 'Unsettled - Forward'))")
        elif sub not in ("#", "") and not f.get("Collateral Class", "").startswith("For Sub-Product"):
            names = [SUB_ALIASES.get(n.strip(), n.strip()) for n in sub.split(",")]
            conds.append("sub_product IN (" + ", ".join(f"'{n}'" for n in names) + ")")
        if f.get("Forward Start Amount") == "NULL":
            conds.append("forward_start_amount IS NULL")
        if f.get("Collateral Value") == "NULL":
            conds.append("collateral_value IS NULL")
        amount = "collateral_value" if f.get("Collateral Value", "").startswith("*") else "maturity_amount"
        cc = f.get("Collateral Class", "#")
        variants = []
        if cc.startswith("For Sub-Product"):   # table 17: collateral received depends on what was pledged
            variants = [("x", "sub_product = 'Level 2b Pledged' AND hqla_level IN ('Level 1', 'Level 2A')"),
                        ("y", "sub_product = 'Non-HQLA Pledged' AND is_hqla")]
        else:
            variants = [(None, _cc_cond(cc))]
        for (suffix, pids), cp in zip(pid_sets, cps):
            for vsuffix, ccc in variants:
                rid = f"STWF-{b['table']:02d}{suffix or ''}{vsuffix or ''}"
                where = " AND ".join(c for c in [cp, ccc] + conds if c) or "TRUE"
                rows.append([rid, b["item"], STWF_ITEMS[b["item"]][0], b["table"], coll, ",".join(pids), where, amount,
                             STWF_ITEMS[b["item"]][1], f"Appendix VII table ({b['table']})", json.dumps(f)])
    return rows


def mdrm_rows(mdrm_csv):
    """Active MDRM items of FR Y-15 Schedule G (STWF, mnemonic RISI, Y838-Y889) - the items derived from FR 2052a data.
    The FR 2052a itself has no MDRM codes: the 6G XSD and the Instructions identify every value by its PID and field values.
    (The MDRM dictionary still lists the pre-2015 FR 2052a line-item template, mnemonic LMMA; it is not what firms file.)"""
    if not mdrm_csv or not os.path.exists(mdrm_csv):
        return None
    fh = open(mdrm_csv, encoding="latin-1")
    next(fh)
    out = []
    for x in csv.DictReader(fh):
        if not x["End Date"].startswith("12/31/9999"):
            continue
        code = x["Item Code"]
        if x["Reporting Form"] == "FR Y-15" and x["Mnemonic"] == "RISI" and code.startswith("Y") and 838 <= int(code[1:]) <= 889:
            desc = html.unescape(re.sub(r"\s+", " ", x["Description"] or ""))[:400]
            out.append([x["Mnemonic"] + code, x["Mnemonic"], code, x["Reporting Form"], x["Item Name"].strip(), x["Start Date"].split(" ")[0],
                        x["ItemType"], desc])
    return out


def stwf_mdrm_rows():
    cols = ["A", "B", "C", "D"]
    out = [[item, col, f"RISIY{base + i}", f"Item {item} column {col}"] for item, (_, _, base) in STWF_ITEMS.items() for i, col in enumerate(cols)]
    out += [[f"{tier} total", col, f"RISIY{base + i}", f"Tier {tier} total column {col}"] for tier, base in STWF_TOTALS.items() for i, col in enumerate(cols)]
    return out

def table_fields(doc):
    """Extract the Data Tables figures (p.84-85): field order, type and Mandatory (red) / Dependent (blue)."""
    rows = []
    order = [t[0] for t in TABLES]
    for pno in (85, 86):
        page = doc[pno - 1]
        rects = [(d["rect"], tuple(round(c, 2) for c in d["fill"])) for d in page.get_drawings() if d.get("fill")]
        grouped = {}
        for w in page.get_text("words"):
            grouped.setdefault((w[5], w[6]), []).append(w)
        lines = []
        for ws in grouped.values():
            ws.sort(key=lambda w: w[0])
            x0, x1 = ws[0][0], ws[-1][2]
            cy = (min(w[1] for w in ws) + max(w[3] for w in ws)) / 2
            fill = None
            for r, f in rects:
                if r.x0 <= x0 + 1 <= r.x1 and r.y0 <= cy <= r.y1 and r.width < 300:
                    fill = f
            lines.append((x0, x1, cy, " ".join(w[4] for w in ws), fill))
        split_y = 360 if pno == 85 else 330
        headers = [(x0, x1, cy, t) for x0, x1, cy, t, f in lines
                   if f is None and any(k[0] == pno and k[2] == t for k in TABLE_HEADERS)]
        for x0, x1, cy, text, fill in lines:
            if fill is None or text in ("text", "numeric", "percent"):
                continue
            hdr = min((h for h in headers if h[2] < cy and h[0] - 60 <= x0 <= h[1] + 40 and (h[2] < split_y) == (cy < split_y)),
                      key=lambda h: (cy - h[2]) + abs(h[0] - x0), default=None)
            if hdr is None:
                continue
            half = ("Inflows" if cy < split_y else "Outflows") if pno == 85 else ("S1" if cy < split_y else "S2")
            code = TABLE_HEADERS[(pno, half, hdr[3])]
            ftype = next((t for a, b, c, t, f in lines if t in ("text", "numeric", "percent") and abs(c - cy) < 2 and 0 < a - x0 < 240), "text")
            rows.append((code, cy, text, ftype, "Mandatory" if fill == RED else "Dependent"))
    rows.sort(key=lambda r: (order.index(r[0]), r[1]))
    tables = {t[0]: t for t in TABLES}
    out, seq = [], {}
    for code, _, name, ftype, cls in rows:
        seq[code] = seq.get(code, 0) + 1
        col, xml = FIELD_MAP[name]
        if name == "Product":
            xml = tables[code][5]
        elif name == "Sub-Product":
            xml = tables[code][6]
        xml = XML_OVERRIDES.get((code, name), xml)
        dtype = "flag" if name in FLAG_FIELDS else ftype
        out.append([code, seq[code], name, col, xml, ftype, dtype, cls, "Data Tables p.84-85"])
    for code in order:
        if code == "S.C":
            continue
        for name, col, dtype in CURRENCY_ATTRS.get(code, CURRENCY_ATTRS["default"]):
            seq[code] += 1
            out.append([code, seq[code], name, col, "unit" if dtype == "text" else "converted", dtype, dtype,
                        "Mandatory", "Footnote 16 p.84 / Field Definitions p.16-17"])
    return out


def products(doc, g6):
    """All 147 PIDs from the table of contents (p.3-7). product_name is the 6G XSD enumeration value (the XSD lists each
    table's products in PID order); instructions_name keeps the PDF wording where it differs."""
    toc = "".join(doc[i].get_text() for i in range(1, 9))
    rows = re.findall(r"^([IOS])\.(A|U|S|O|D|W|DC|L|B|I|FX)\.(\d+)\s*:\s*(.+?)\s*\.{3,}\s*(\d+)\s*$", toc, re.M)
    names = {t[0]: t[1] for t in TABLES}
    seen, out = set(), []
    for sec, tab, n, name, page in rows:
        pid = f"{sec}.{tab}.{n}"
        if pid in seen:
            continue
        seen.add(pid)
        code = f"{sec}.{tab}"
        out.append([pid, code, sec, int(n), re.sub(r"\s+", " ", name).replace("–", "-").strip(), names[code], int(page)])
    order = [t[0] for t in TABLES]
    out.sort(key=lambda r: (order.index(r[1]), r[3]))
    product_type = {t[0]: dict((n, ty) for _, n, ty, _ in g6.layout(t[4]))[t[5]] for t in TABLES if t[0] != "S.C"}
    for r in out:
        xsd_names = g6.enum(product_type[r[1]])
        r.insert(5, r[4])
        r[4] = xsd_names[r[3] - 1]
    for code, ptype in product_type.items():
        if len(g6.enum(ptype)) != sum(1 for r in out if r[1] == code):
            raise SystemExit(f"{code}: XSD lists {len(g6.enum(ptype))} products, the Instructions {sum(1 for r in out if r[1] == code)}")
    return out


def collateral_requirements(doc):
    """Appendix II-c (p.91-94): the check marks are glyphs located by column x position."""
    pid_re = re.compile(r"^[IOS]\.(A|U|S|O|D|W|DC|L|B|I|FX)\.\d+$")
    out = {}
    for pno in range(92, 96):
        page = doc[pno - 1]
        words = page.get_text("words")
        dep = next((w for w in words if w[4] == "Dependent"), None)
        if dep is None:
            continue
        hdr = {w[4]: (w[0] + w[2]) / 2 for w in words
               if w[4] in ("Required", "Dependent", "Applicable") and abs(w[1] - dep[1]) < 3}
        cols = {"Required": hdr["Required"], "Dependent": hdr["Dependent"], "Not Applicable": hdr["Applicable"]}
        ticks = [pymupdf.Rect(w[:4]) for w in words if w[4] in ("", "ü", "✓", "✓")]
        ticks += [d["rect"] for d in page.get_drawings() if d["rect"].width < 12 and d["rect"].height < 12
                  and d["rect"].x0 > min(cols.values()) - 40]
        for w in words:
            if not pid_re.match(w[4]):
                continue
            cy = (w[1] + w[3]) / 2
            hit = [k for k, x in cols.items() for t in ticks
                   if abs((t.y0 + t.y1) / 2 - cy) < 5 and abs((t.x0 + t.x1) / 2 - x) < 30]
            out.setdefault(w[4], hit[0] if hit else "")
    return [[pid, req, "Appendix II-c p.91-94"] for pid, req in out.items()]


def write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    print(f"  {os.path.basename(path)}: {len(rows)} rows")


def main(pdf, g6_dir, out_dir, mdrm_csv=None):
    doc = pymupdf.open(pdf)
    g6 = Schema6G(g6_dir)
    os.makedirs(out_dir, exist_ok=True)
    p = lambda name: os.path.join(out_dir, name)

    write(p("spec_tables.csv"), ["table_code", "table_name", "section", "gold_table", "xml_report_type",
                                 "product_element", "sub_product_element", "primary_amount_column"], TABLES)
    fields = table_fields(doc)
    layout = xsd_layout_rows(g6)
    xsd_by = {(r[0], r[4]): r for r in layout}
    for f in fields:   # XSD kind / type / required for each spec field (unit and converted are value attributes)
        x = xsd_by.get((f[0], f[4]))
        if f[0] != "S.C" and f[4] not in ("unit", "converted") and x is None:
            raise SystemExit(f"{f[0]} {f[2]}: element {f[4]} is not in 6GSchema.xsd")
        f += [x[3], x[5], x[6]] if x else (["attribute", "xs:boolean" if f[4] == "converted" else "currencyUnit", "true"] if f[0] != "S.C" else ["", "", ""])
    missing = [(r[0], r[4]) for r in layout if r[4] not in ("reportID", "comment") and (r[0], r[4]) not in {(f[0], f[4]) for f in fields}]
    if missing:
        raise SystemExit(f"XSD elements without a spec field: {missing}")
    write(p("spec_table_fields.csv"), ["table_code", "seq", "field_name", "column_name", "xml_element", "spec_type",
                                       "data_type", "field_class", "source", "xml_kind", "xsd_type", "xsd_required"], fields)
    write(p("spec_xsd_layout.csv"), ["table_code", "report_type", "seq", "xml_kind", "xml_name", "xsd_type", "xsd_required",
                                     "value_kind"], layout)
    prods = products(doc, g6)
    write(p("spec_products.csv"), ["product_id", "table_code", "section_code", "product_number", "product_name",
                                   "instructions_name", "table_name", "definition_page"], prods)
    pids = [r[0] for r in prods]
    name_of = {r[0]: r[4] for r in prods}

    write(p("spec_subproducts.csv"), ["product_id", "field_name", "allowed_value", "required_by_instructions", "source"],
          subproducts_6g(g6, name_of))

    cp_rows = []
    for plist, applicable, page in CPTY_GROUPS:
        for pid in plist:
            for c in ALL_CPTY:
                cp_rows.append([pid, c, "Applicable" if c in applicable else "Not Applicable", f"Appendix II-b {page}"])
    br_cp = {f"{t[0]}.{r[2]}" for r in g6.tab("Counterparty Required") for t in TABLES if t[4] == r[1]}
    if br_cp != {r[0] for r in cp_rows}:
        raise SystemExit(f"Counterparty Required differs from the BR tab: {sorted(br_cp ^ {r[0] for r in cp_rows})}")
    xsd_cp = set(g6.enum("counterpartySectorWithRetailAndMunicipalities"))
    if xsd_cp != set(ALL_CPTY):
        raise SystemExit(f"Counterparty spellings differ from the XSD: {sorted(xsd_cp ^ set(ALL_CPTY))}")
    write(p("spec_counterparty_requirements.csv"), ["product_id", "counterparty", "applicability", "source"], cp_rows)

    coll = collateral_requirements(doc)
    br_coll = {r[3] for r in g6.tab("Collateral Class Required")}
    if br_coll != {c[0] for c in coll if c[1] == "Required"}:
        raise SystemExit(f"Collateral Class Required differs from the BR tab: {sorted(br_coll ^ {c[0] for c in coll if c[1] == 'Required'})}")
    write(p("spec_collateral_class_requirements.csv"), ["product_id", "requirement", "source"], coll)
    write(p("spec_forward_start_exclusions.csv"), ["product_id", "source"], [[pid, "Appendix II-d p.95-97"] for pid in FWD_EXCLUDED])

    ac = []
    for code, desc, lvl in _Q:
        ac.append([code, desc, lvl, "HQLA " + lvl, HAIRCUT[lvl], "true"])
    for code, desc, _ in _Q[2:]:  # A-0 (cash) and A-1 (Treasuries) have no non-qualifying variant
        base = code[:-2]
        ac.append([base, _NON_Q_OVERRIDES.get(base, desc), "Non-HQLA", "Non-HQLA (fails asset-specific tests of Reg WW section 20)", "", "false"])
    for code, desc in _OTHER:
        ac.append([code, desc, "Non-HQLA", "Non-HQLA other", "", "false"])
    xsd_cc = set(g6.enum("collateralClass"))
    if xsd_cc != {a[0] for a in ac}:
        raise SystemExit(f"Asset categories differ from the XSD collateralClass: {sorted(xsd_cc ^ {a[0] for a in ac})}")
    write(p("spec_asset_categories.csv"), ["collateral_class", "description", "hqla_level", "category_group",
                                           "lcr_haircut_pct", "is_hqla"], ac)

    buckets = maturity_buckets()
    br_b = [(r[2], "" if r[3] == "N/A" else r[3]) for r in g6.tab("Maturity bucket values")]
    if br_b != [(b[2], b[3]) for b in buckets if b[8] == "true"]:
        raise SystemExit("Maturity buckets differ from the BR 'Maturity bucket values' tab")
    write(p("spec_maturity_buckets.csv"), ["bucket_seq", "bucket_label", "maturity_start", "maturity_end", "day_start",
                                           "day_end", "bucket_type", "is_within_30d", "is_standard"], buckets)
    write(p("spec_maturity_tailoring.csv"), ["profile_code", "profile_description", "product_scope", "bucket_label"], tailoring(buckets))
    write(p("spec_double_counting.csv"), ["item_no", "description", "check_type", "products_a", "products_b", "comparison"],
          DOUBLE_COUNTING)
    write(p("spec_field_values.csv"), ["field_name", "table_scope", "allowed_value", "source"], field_values_6g(g6, fields))
    write(p("spec_counterparties.csv"), ["counterparty", "counterparty_category", "is_financial", "source"],
          [[c, cat, str(fin).lower(), "Field Definitions p.17-21; 6GSchema.xsd counterpartySector" + ("; footnote 8: O.O.5 only" if c == MUNI else "")]
           for c, cat, fin in COUNTERPARTIES])
    write(p("rules_validation_6g.csv"), ["rule_id", "report_type", "schedule_code", "seq_num", "business_field", "xml_element",
                                         "xml_child_element", "required_by_schema", "xml_data_type", "validation_rule", "enumeration_ref",
                                         "rule_category", "enforced_by", "severity", "reg_version"], br_rules(g6))

    stwf = stwf_rules(doc)
    write(p("rules_stwf_appendix_vii.csv"), ["rule_id", "stwf_item", "item_name", "appendix_table", "collection", "product_ids",
                                             "condition_sql", "amount_column", "tier_weight", "source", "appendix_fields"], stwf)
    write(p("ref_stwf_mdrm.csv"), ["stwf_item", "maturity_column", "mdrm", "description"], stwf_mdrm_rows())
    mdrm = mdrm_rows(mdrm_csv)
    if mdrm is not None:   # the MDRM download is optional; keep the committed extract otherwise
        write(p("ref_mdrm_items.csv"), ["mdrm", "mnemonic", "item_code", "reporting_form", "item_name", "start_date", "item_type",
                                        "description"], mdrm)
    missing = [x for plist, *_ in CPTY_GROUPS for x in plist if x not in pids]
    missing += [x for r in stwf for x in r[5].split(",") if x not in pids]
    missing += [x for plist, *_ in SUBPRODUCTS for x in plist if x not in pids]
    missing += [x for x in FWD_EXCLUDED if x not in pids]
    if missing:
        raise SystemExit(f"Unknown PIDs referenced: {missing}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
