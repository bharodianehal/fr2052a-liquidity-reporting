"""Build the firm (bank-owned) reference data that turns source-system records into FR 2052a data elements.

The Fed defines the 147 PIDs in prose; which PID a source record belongs to depends on the bank's own product catalogue
and on attributes of the record, the customer and the collateral. These CSVs are that mapping for the Acme synthetic
bank, and are what a bank would maintain under change control:

  ref_standard_product_type.csv   the bank's standard product types (one per regulatory product family)
  ref_source_product_map.csv      each source system's own product codes -> standard product type (reclassification)
  rules_pid_derivation.csv        PID derivation rules: per standard product type, ordered SQL conditions -> PID
  ref_legal_entity.csv            legal entities and the org structure (parent), affiliates for Internal Counterparty
  ref_customer_master.csv         approved customer master: FR 2052a Counterparty, G-SIB parent, affiliate legal entity
  ref_security_master.csv         security / collateral id -> Appendix III Collateral Class
  ref_lendable_haircuts.csv       lendable value haircut by pledge venue and HQLA level / asset class
  ref_generic_collateral_map.csv  generic issuer / product of substitutable collateral -> Collateral Class
  ref_expected_products.csv       products expected for each entity type (Fed post-submission check 9)

Rule conditions are Spark SQL over the enriched, calculated record (notebook 03): product_subtype, flow_direction,
counterparty, counterparty_category, collateral_class, hqla_level, encumbrance_type, sub_product, insured,
has_relationship, maturity_type. Rules are evaluated in priority order; the first match sets the PID.

Usage: python3 scripts/firm/build_firm_reference.py [reference_data]
"""
import csv
import os
import re
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "..", "reference_data")
RETAIL = "counterparty_category = 'Retail'"
WHOLESALE = "COALESCE(counterparty_category, '') <> 'Retail'"
SECURED = "collateral_class IS NOT NULL"   # direct collateral id or the linked (placed) collateral
RCV, PAY = "flow_direction = 'RECEIVE'", "flow_direction = 'PAY'"
sub = lambda v: f"product_subtype = '{v}'"
ALWAYS = "TRUE"

# source system, standard product type, description, requires customer, requires collateral,
#   [(condition, PID, rationale)]; the rationale gets the PID's definition page
CATALOG = [
    # ---- custody / securities inventory (I.A) ----
    ("STATESTREET_CUSTODY", "SEC-POS", "Securities position in custody", False, True, [
        ("encumbrance_type IS NOT NULL", "I.A.7", "Encumbered to a transaction - I.A.7 Encumbered Assets (p.34)"),
        ("sub_product IS NOT NULL", "I.A.2", "Pre-positioned at a central bank / FHLB - I.A.2 Capacity (p.33)"),
        (ALWAYS, "I.A.1", "Unencumbered - I.A.1 Unencumbered Assets (p.33)")]),
    ("STATESTREET_CUSTODY", "LOAN-POOL", "Whole loans held as assets at market value", False, True, [
        ("encumbrance_type IS NOT NULL", "I.A.7", "Encumbered loans - I.A.7 (p.34)"),
        ("sub_product IS NOT NULL", "I.A.2", "Loans pledged to the FRB discount window / FHLB - I.A.2 Capacity (p.33)"),
        (ALWAYS, "I.A.1", "Unencumbered loans - I.A.1 (p.33)")]),
    ("STATESTREET_CUSTODY", "CB-RES", "Balances at central banks", False, True, [
        (sub("RESTRICTED"), "I.A.4", "Reserve balances held to meet requirements - I.A.4 (p.34)"),
        (ALWAYS, "I.A.3", "Unrestricted reserve balances - I.A.3 (p.33)")]),
    ("STATESTREET_CUSTODY", "VAULT-CASH", "Currency and coin", False, True, [(ALWAYS, "I.A.3", "Currency and coin - I.A.3 (p.33)")]),
    ("STATESTREET_CUSTODY", "SEC-PURCH", "Executed, unsettled security purchase", False, True, [
        (sub("REGULAR_WAY"), "I.A.5", "Regular-way settlement - I.A.5 Unsettled Asset Purchases (p.34)"),
        (sub("FORWARD"), "I.A.6", "Settles outside regular way - I.A.6 Forward Asset Purchases (p.34)")]),
    # ---- loans and placements (I.U, I.S) ----
    ("ACBS_LOANS", "MM-PLACE", "Interbank money market placement", True, False, [
        (sub("ONSHORE"), "I.U.1", "Domestic currency placed onshore - I.U.1 (p.35)"),
        (sub("OFFSHORE"), "I.U.2", "Euro-market placement - I.U.2 (p.35)")]),
    ("ACBS_LOANS", "NOSTRO", "Balances held at other banks", True, False, [
        (sub("OPERATIONAL"), "I.U.3", "Minimum operational balance - I.U.3 (p.35)"),
        (sub("EXCESS"), "I.U.4", "Balance above the operational minimum - I.U.4 (p.35)")]),
    ("ACBS_LOANS", "RCF-DRAW", "Drawn revolving credit facility", True, False, [
        (SECURED, "I.S.7", "Secured revolver draw - I.S.7 (p.39)"),
        (ALWAYS, "I.U.5", "Unsecured revolver draw - I.U.5 (p.35)")]),
    ("ACBS_LOANS", "TERM-LOAN", "Term loan / mortgage / consumer loan", True, False, [
        (f"NOT ({SECURED})", "I.U.6", "Unsecured loan - I.U.6 Other Loans (p.36)"),
        (f"{SECURED} AND {sub('REHYPOTHECATABLE')}", "I.S.6", "Collateral contractually rehypothecatable - I.S.6 (p.39)"),
        (f"{SECURED} AND {sub('NON_REHYPOTHECATABLE')}", "I.S.8", "Collateral not rehypothecatable - I.S.8 (p.39)")]),
    ("ACBS_LOANS", "CIPC", "Cash items in the process of collection", True, False, [(ALWAYS, "I.U.7", "I.U.7 (p.36)")]),
    ("ACBS_LOANS", "ST-INV", "Short-term investment (CDs, time deposits placed)", True, False, [(ALWAYS, "I.U.8", "I.U.8 (p.36)")]),
    ("MUREX", "REVREPO", "Reverse repurchase agreement", True, True, [(ALWAYS, "I.S.1", "I.S.1 Reverse Repo (p.37)")]),
    ("MUREX", "SECBORROW", "Securities borrowed", True, True, [(ALWAYS, "I.S.2", "I.S.2 Securities Borrowing (p.37)")]),
    ("MUREX", "DOLLAR-ROLL", "TBA dollar roll", True, True, [
        (RCV, "I.S.3", "Cash lent leg - I.S.3 (p.38)"), (PAY, "O.S.3", "Cash borrowed leg - O.S.3 (p.51)")]),
    ("MUREX", "COLL-SWAP", "Collateral swap", True, True, [
        (RCV, "I.S.4", "Collateral received - I.S.4 (p.38)"), (PAY, "O.S.4", "Collateral delivered - O.S.4 (p.51)")]),
    ("MUREX", "MARGIN-LOAN", "Customer margin loan", True, True, [(ALWAYS, "I.S.5", "I.S.5 Margin Loans (p.38)")]),
    ("MUREX", "SYNTH-CUST-LONG", "Synthetic customer long (total return swap)", True, True, [(ALWAYS, "I.S.9", "I.S.9 (p.39)")]),
    ("MUREX", "SYNTH-FIRM-SRC", "Synthetic firm sourcing", True, True, [(ALWAYS, "I.S.10", "I.S.10 (p.40)")]),
    # ---- derivatives and other cash flows (I.O, O.O) ----
    ("MUREX", "DERIV-CF", "Derivative contractual cash flow", True, False, [
        (RCV, "I.O.1", "Derivative receivable - I.O.1 (p.40)"), (PAY, "O.O.1", "Derivative payable - O.O.1 (p.53)")]),
    ("MUREX", "COLL-CALL", "Collateral call", True, True, [
        (RCV, "I.O.2", "Called for receipt - I.O.2 (p.41)"), (PAY, "O.O.2", "Called for delivery - O.O.2 (p.53)")]),
    ("MUREX", "TBA", "To-be-announced MBS trade", True, True, [
        (RCV, "I.O.3", "TBA sale - I.O.3 (p.41)"), (PAY, "O.O.3", "TBA purchase - O.O.3 (p.53)")]),
    ("MUREX", "FAC-PURCH", "Committed facility purchased", True, False, [(ALWAYS, "I.O.4", "I.O.4 (p.41)")]),
    ("MUREX", "LOCKUP", "Lock-up balance", True, False, [(ALWAYS, "I.O.5", "I.O.5 (p.41)")]),
    ("MUREX", "INT-DIV", "Interest and dividends", False, False, [
        (RCV, "I.O.6", "Receivable - I.O.6 (p.42)"), (PAY, "O.O.19", "Payable - O.O.19 (p.56)")]),
    ("MUREX", "NET30", "Net 30-day derivative flows (Appendix V #6-9)", False, False, [
        (RCV, "I.O.7", "Net receivable - I.O.7 (p.42)"), (PAY, "O.O.20", "Net payable - O.O.20 (p.56)")]),
    ("MUREX", "SEC-PRIN", "Principal due on investment securities", False, True, [(ALWAYS, "I.O.8", "I.O.8 (p.42)")]),
    ("MUREX", "OTHER-CF", "Other contractual cash flow", False, False, [
        (RCV, "I.O.9", "Other cash inflow - I.O.9 (p.42)"), (PAY, "O.O.22", "Other cash outflow - O.O.22 (p.57)")]),
    ("MUREX", "COMMIT-CREDIT", "Undrawn credit facility", True, False, [(ALWAYS, "O.O.4", "O.O.4 Credit Facilities (p.54)")]),
    ("MUREX", "COMMIT-LIQ", "Undrawn liquidity facility", True, False, [(ALWAYS, "O.O.5", "O.O.5 Liquidity Facilities (p.54)")]),
    ("MUREX", "MORTG-COMMIT", "Retail mortgage commitment", True, False, [(ALWAYS, "O.O.6", "O.O.6 (p.54)")]),
    ("MUREX", "TRADE-FIN", "Trade finance instrument", True, False, [(ALWAYS, "O.O.7", "O.O.7 (p.54)")]),
    ("MUREX", "MTM-IMPACT", "Look-back MTM collateral outflow", False, False, [(ALWAYS, "O.O.8", "O.O.8 (p.55)")]),
    ("MUREX", "DOWNGRADE-REHYP", "Rehypothecation rights lost on downgrade", False, True, [
        (sub("NOTCH1"), "O.O.9", "1 notch - O.O.9 (p.55)"), (sub("NOTCH2"), "O.O.10", "2 notch - O.O.10 (p.55)"),
        (sub("NOTCH3"), "O.O.11", "3 notch - O.O.11 (p.55)"), (sub("FIN_CONDITION"), "O.O.12", "Change in financial condition - O.O.12 (p.55)")]),
    ("MUREX", "DOWNGRADE-COLL", "Collateral required on downgrade", False, True, [
        (sub("NOTCH1"), "O.O.13", "1 notch - O.O.13 (p.55)"), (sub("NOTCH2"), "O.O.14", "2 notch - O.O.14 (p.55)"),
        (sub("NOTCH3"), "O.O.15", "3 notch - O.O.15 (p.55)"), (sub("FIN_CONDITION"), "O.O.16", "Change in financial condition - O.O.16 (p.55)")]),
    ("MUREX", "EXCESS-MARGIN", "Customer excess margin", True, True, [(ALWAYS, "O.O.17", "O.O.17 (p.56)")]),
    ("MUREX", "UNFUNDED-MARGIN", "Unfunded term margin", True, False, [(ALWAYS, "O.O.18", "O.O.18 (p.56)")]),
    ("MUREX", "STRUCT-OTHER", "Other structured transaction outflow", False, False, [(ALWAYS, "O.O.21", "O.O.21 (p.57)")]),
    # ---- deposits (O.D) ----
    ("FISERV_DDA", "DDA", "Demand deposit account", True, False, [
        (RETAIL, "O.D.1", "Retail / small business demand deposit - O.D.1 Transactional (p.57)"),
        (f"{WHOLESALE} AND {sub('OPERATIONAL')}", "O.D.4", "Wholesale operational deposit - O.D.4 (p.58)"),
        (f"{WHOLESALE} AND {sub('EXCESS')}", "O.D.5", "Excess over the operational amount - O.D.5 (p.58)"),
        (WHOLESALE, "O.D.6", "Wholesale non-operational - O.D.6 (p.58)")]),
    ("FISERV_DDA", "SAV", "Savings / money market deposit account", True, False, [
        (f"{RETAIL} AND has_relationship", "O.D.2", "Depositor has another relationship - O.D.2 (p.57)"),
        (RETAIL, "O.D.3", "No other relationship - O.D.3 (p.58)"), (WHOLESALE, "O.D.6", "Wholesale non-operational - O.D.6 (p.58)")]),
    ("FISERV_DDA", "TD", "Term deposit", True, False, [
        (f"{RETAIL} AND has_relationship", "O.D.2", "O.D.2 (p.57)"), (RETAIL, "O.D.3", "O.D.3 (p.58)"),
        (WHOLESALE, "O.D.6", "O.D.6 (p.58)")]),
    ("FISERV_DDA", "ESCROW", "Operational escrow account", True, False, [(ALWAYS, "O.D.7", "O.D.7 (p.58)")]),
    ("FISERV_DDA", "BROKERED", "Brokered deposit (non-reciprocal)", True, False, [(ALWAYS, "O.D.8", "O.D.8 (p.59)")]),
    ("FISERV_DDA", "SWEEP-AFF", "Sweep from an affiliated broker-dealer", True, False, [
        ("insured = 'FDIC'", "O.D.9", "Fully insured - stable affiliated sweep O.D.9 (p.59)"),
        (ALWAYS, "O.D.10", "Not fully insured - O.D.10 (p.59)")]),
    ("FISERV_DDA", "SWEEP-NONAFF", "Sweep from a non-affiliated firm", True, False, [(ALWAYS, "O.D.11", "O.D.11 (p.59)")]),
    ("FISERV_DDA", "SWEEP-OTHER", "Sweep from other firm products", True, False, [(ALWAYS, "O.D.12", "O.D.12 (p.60)")]),
    ("FISERV_DDA", "RECIP", "Reciprocal deposit", True, False, [(ALWAYS, "O.D.13", "O.D.13 (p.60)")]),
    ("FISERV_DDA", "3P-DEP", "Other third-party deposit", True, False, [(ALWAYS, "O.D.14", "O.D.14 (p.60)")]),
    ("FISERV_DDA", "DEP-OTHER", "Other deposit account", True, False, [(ALWAYS, "O.D.15", "O.D.15 (p.60)")]),
    # ---- wholesale funding (O.W) ----
    ("QUANTUM_TREASURY", "ABCP", "Asset-backed commercial paper", False, True, [
        (sub("SINGLE_SELLER"), "O.W.1", "O.W.1 (p.46)"), (sub("MULTI_SELLER"), "O.W.2", "O.W.2 (p.46)")]),
    ("QUANTUM_TREASURY", "CCP-PAPER", "Collateralized commercial paper", False, True, [(ALWAYS, "O.W.3", "O.W.3 (p.46)")]),
    ("QUANTUM_TREASURY", "ABS", "Asset-backed securities issued", False, True, [(ALWAYS, "O.W.4", "O.W.4 (p.46)")]),
    ("QUANTUM_TREASURY", "COVERED-BOND", "Covered bonds issued", False, True, [(ALWAYS, "O.W.5", "O.W.5 (p.47)")]),
    ("QUANTUM_TREASURY", "TOB", "Tender option bonds", False, True, [(ALWAYS, "O.W.6", "O.W.6 (p.47)")]),
    ("QUANTUM_TREASURY", "OTHER-ABF", "Other asset-backed financing", False, True, [(ALWAYS, "O.W.7", "O.W.7 (p.47)")]),
    ("QUANTUM_TREASURY", "CP", "Commercial paper issued", False, False, [(ALWAYS, "O.W.8", "O.W.8 (p.47)")]),
    ("QUANTUM_TREASURY", "MM-BORROW", "Interbank money market borrowing", True, False, [
        (sub("ONSHORE"), "O.W.9", "Fed funds purchased / domestic - O.W.9 (p.47)"), (sub("OFFSHORE"), "O.W.10", "Euro-market - O.W.10 (p.48)")]),
    ("QUANTUM_TREASURY", "DEBT-ISS", "Debt securities issued", False, False, [
        (sub("UNSTRUCTURED_LTD"), "O.W.11", "O.W.11 (p.48)"), (sub("STRUCTURED_LTD"), "O.W.12", "O.W.12 (p.48)"),
        (sub("GOVT_SUPPORTED"), "O.W.13", "O.W.13 (p.48)"), (sub("NOTE"), "O.W.14", "O.W.14 (p.48)"),
        (sub("STRUCTURED_NOTE"), "O.W.15", "O.W.15 (p.48)")]),
    ("QUANTUM_TREASURY", "WCD", "Wholesale certificate of deposit", True, False, [(ALWAYS, "O.W.16", "O.W.16 (p.49)")]),
    ("QUANTUM_TREASURY", "LINE-DRAW", "Draw on a committed line", True, False, [(ALWAYS, "O.W.17", "O.W.17 (p.49)")]),
    ("QUANTUM_TREASURY", "FREE-CREDIT", "Customer free credit balance", True, False, [(ALWAYS, "O.W.18", "O.W.18 (p.49)")]),
    ("QUANTUM_TREASURY", "UNSEC-OTHER", "Other unsecured financing", True, False, [(ALWAYS, "O.W.19", "O.W.19 (p.49)")]),
    # ---- secured funding (O.S) ----
    ("MUREX", "REPO", "Repurchase agreement", True, True, [(ALWAYS, "O.S.1", "O.S.1 Repo (p.50)")]),
    ("MUREX", "SECLEND", "Securities lent", True, True, [(ALWAYS, "O.S.2", "O.S.2 (p.50)")]),
    ("MUREX", "SEC-BORROWING", "Secured borrowing facility", True, True, [
        ("counterparty = 'Government Sponsored Entity'", "O.S.5", "FHLB advance - O.S.5 (p.51)"),
        ("counterparty = 'Central Bank'", "O.S.6", "Central bank operation - O.S.6 (p.51)"),
        (ALWAYS, "O.S.11", "O.S.11 Other Secured Financing Transactions (p.52)")]),
    ("MUREX", "CUST-SHORT", "Customer short position", True, True, [(ALWAYS, "O.S.7", "O.S.7 (p.51)")]),
    ("MUREX", "FIRM-SHORT", "Firm short position", True, True, [(ALWAYS, "O.S.8", "O.S.8 (p.52)")]),
    ("MUREX", "SYNTH-CUST-SHORT", "Synthetic customer short", True, True, [(ALWAYS, "O.S.9", "O.S.9 (p.52)")]),
    ("MUREX", "SYNTH-FIRM-FIN", "Synthetic firm financing", True, True, [(ALWAYS, "O.S.10", "O.S.10 (p.52)")]),
    # ---- derivatives and collateral (S.DC) ----
    ("ALGO_COLLATERAL", "DERIV-MTM", "Gross derivative fair value", True, False, [
        (RCV, "S.DC.1", "Asset value - S.DC.1 (p.65)"), (PAY, "S.DC.2", "Liability value - S.DC.2 (p.65)")]),
    ("ALGO_COLLATERAL", "DERIV-SETTLE", "Derivative settlement payment", True, True, [
        (PAY, "S.DC.3", "Delivered - S.DC.3 (p.65)"), (RCV, "S.DC.4", "Received - S.DC.4 (p.65)")]),
    ("ALGO_COLLATERAL", "IM", "Initial margin", True, True, [
        (f"{PAY} AND {sub('HOUSE')}", "S.DC.5", "Posted, house - S.DC.5 (p.66)"),
        (f"{PAY} AND {sub('CUSTOMER')}", "S.DC.6", "Posted, customer - S.DC.6 (p.66)"), (RCV, "S.DC.7", "Received - S.DC.7 (p.66)")]),
    ("ALGO_COLLATERAL", "VM", "Variation margin", True, True, [
        (f"{PAY} AND {sub('HOUSE')}", "S.DC.8", "Posted, house - S.DC.8 (p.66)"),
        (f"{PAY} AND {sub('CUSTOMER')}", "S.DC.9", "Posted, customer - S.DC.9 (p.67)"), (RCV, "S.DC.10", "Received - S.DC.10 (p.67)")]),
    ("ALGO_COLLATERAL", "CCP-DF", "CCP default fund contribution", True, True, [(ALWAYS, "S.DC.11", "S.DC.11 (p.67)")]),
    ("ALGO_COLLATERAL", "CCP-OTHER", "Other CCP pledges", True, True, [(ALWAYS, "S.DC.12", "S.DC.12 (p.67)")]),
    ("ALGO_COLLATERAL", "COLL-DISPUTE", "Disputed collateral call", True, False, [
        (PAY, "S.DC.13", "Deliverable - S.DC.13 (p.67)"), (RCV, "S.DC.14", "Receivable - S.DC.14 (p.68)")]),
    ("ALGO_COLLATERAL", "SLEEPER", "Sleeper collateral", False, True, [
        (PAY, "S.DC.15", "Deliverable - S.DC.15 (p.68)"), (RCV, "S.DC.17", "Receivable - S.DC.17 (p.68)")]),
    ("ALGO_COLLATERAL", "REQ-COLL", "Required collateral deliverable", False, True, [(ALWAYS, "S.DC.16", "S.DC.16 (p.68)")]),
    ("ALGO_COLLATERAL", "COLL-SUB", "Collateral substitution exposure", False, False, [
        (sub("DERIV_RISK"), "S.DC.18", "S.DC.18 (p.68)"), (sub("DERIV_CAPACITY"), "S.DC.19", "S.DC.19 (p.69)"),
        (sub("OTHER_RISK"), "S.DC.20", "S.DC.20 (p.69)"), (sub("OTHER_CAPACITY"), "S.DC.21", "S.DC.21 (p.69)")]),
    # ---- finance / regulatory calculation (S.L, S.B, S.I) ----
    ("AXIOM_REGCALC", "SUB-LIQ", "Subsidiary HQLA (LCR)", False, True, [
        (sub("RESTRICTED"), "S.L.1", "Cannot be transferred - S.L.1 (p.70)"), (sub("TRANSFERABLE"), "S.L.2", "Available for transfer - S.L.2 (p.70)")]),
    ("AXIOM_REGCALC", "HEDGE-TERM", "Early termination outflows on HQLA hedges", False, True, [(ALWAYS, "S.L.3", "S.L.3 (p.70)")]),
    ("AXIOM_REGCALC", "PMM-DEBT", "Own debt > 30 days where firm is primary market maker", False, False, [
        (sub("NON_STRUCTURED"), "S.L.4", "S.L.4 (p.71)"), (sub("STRUCTURED"), "S.L.5", "S.L.5 (p.71)")]),
    ("AXIOM_REGCALC", "SUB-FUND", "Subsidiary stable funding (NSFR)", False, False, [
        (sub("RESTRICTED"), "S.L.7", "Cannot be transferred - S.L.7 (p.71)"), (sub("TRANSFERABLE"), "S.L.8", "Available for transfer - S.L.8 (p.71)")]),
    ("AXIOM_REGCALC", "OBS-REHYP", "Off-balance sheet rehypothecated assets", False, True, [(ALWAYS, "S.L.9", "S.L.9 (p.71)")]),
    ("AXIOM_REGCALC", "NSFR", "Net stable funding ratio", False, False, [(ALWAYS, "S.L.10", "S.L.10 (p.72)")]),
    ("ORACLE_GL", "REG-CAP", "Regulatory capital element", False, False, [(ALWAYS, "S.B.1", "S.B.1 (p.72)")]),
    ("ORACLE_GL", "OTHER-LIAB", "Other liabilities", False, False, [(ALWAYS, "S.B.2", "S.B.2 (p.72)")]),
    ("ORACLE_GL", "NPA", "Non-performing assets", True, True, [(ALWAYS, "S.B.3", "S.B.3 (p.73)")]),
    ("ORACLE_GL", "OTHER-ASSET", "Other assets", False, True, [(ALWAYS, "S.B.4", "S.B.4 (p.73)")]),
    ("ORACLE_GL", "CPTY-NETTING", "Balance sheet counterparty netting", True, True, [(ALWAYS, "S.B.5", "S.B.5 (p.73)")]),
    ("ORACLE_GL", "CARRY-ADJ", "Carrying value adjustment", False, False, [(ALWAYS, "S.B.6", "S.B.6 (p.73)")]),
    ("BROKERAGE_BOOKS", "CLIENT-LONG", "Client long market value", False, True, [(ALWAYS, "S.I.1", "S.I.1 (p.74)")]),
    ("BROKERAGE_BOOKS", "CLIENT-SHORT", "Client short market value", False, True, [(ALWAYS, "S.I.2", "S.I.2 (p.74)")]),
    ("BROKERAGE_BOOKS", "CLIENT-WIRE", "Client wires", False, True, [
        (RCV, "S.I.3", "Received - S.I.3 (p.74)"), (PAY, "S.I.4", "Paid - S.I.4 (p.74)")]),
    ("BROKERAGE_BOOKS", "FRB-23A", "Section 23A capacity", False, False, [(ALWAYS, "S.I.5", "S.I.5 (p.75)")]),
    ("BROKERAGE_BOOKS", "SUB-LIQ-NT", "Subsidiary liquidity not transferable", False, True, [(ALWAYS, "S.I.6", "S.I.6 (p.75)")]),
    # ---- foreign exchange (S.FX) ----
    ("MUREX", "FX-SPOT", "FX spot", True, False, [(ALWAYS, "S.FX.1", "S.FX.1 (p.77)")]),
    ("MUREX", "FX-FWD", "FX forward / future", True, False, [(ALWAYS, "S.FX.2", "S.FX.2 (p.77)")]),
    ("MUREX", "FX-SWAP", "FX swap", True, False, [(ALWAYS, "S.FX.3", "S.FX.3 (p.77)")]),
]

# Legal entities of the group (org structure). Reporting entities and their scope are in reference_data/ref_reporting_entity.csv.
LEGAL_ENTITIES = [  # id, legal name, entity type, parent, country
    ("LE00", "Acme Financial Holdings Inc", "BHC Parent", "", "US"),
    ("LE02", "Acme National Bank N.A.", "Lead Bank", "LE00", "US"),
    ("LE03", "Acme Securities LLC", "Broker Dealer", "LE00", "US"),
    ("LE04", "Acme Capital Markets Europe Ltd", "Foreign Broker Dealer", "LE03", "GB"),
    ("LE05", "Acme Funding Corp", "Funding Vehicle", "LE00", "US"),
]

# Customers (what onboarding / KYC knows) and the approved FR 2052a classification:
# id, name, country, NAICS, legal form, Counterparty (XSD spelling), G-SIB parent (BR 2020 list), affiliate legal entity,
# has_relationship, onboarded, approved (None = still pending steward approval -> its positions are held)
EXISTING = "2015-06-30"
CUSTOMERS = [
    ("C0001", "Retail depositors - relationship", "US", "", "Individuals", "Retail", "", "", True, EXISTING, EXISTING),
    ("C0002", "Retail depositors - no relationship", "US", "", "Individuals", "Retail", "", "", False, EXISTING, EXISTING),
    ("C0003", "Small business - relationship", "US", "", "Sole proprietorships and small companies", "Small Business", "", "", True, EXISTING, EXISTING),
    ("C0004", "Small business - no relationship", "US", "", "Sole proprietorships and small companies", "Small Business", "", "", False, EXISTING, EXISTING),
    ("C0010", "Globex Manufacturing Corp", "US", "332710", "Corporation", "Non-Financial Corporate", "", "", True, EXISTING, EXISTING),
    ("C0011", "Initech Holdings Inc", "US", "541511", "Corporation", "Non-Financial Corporate", "", "", True, EXISTING, EXISTING),
    ("C0020", "Republic of Freedonia", "FD", "921130", "Sovereign government", "Sovereign", "", "", False, EXISTING, EXISTING),
    ("C0021", "Federal Reserve Bank of New York", "US", "521110", "Central bank", "Central Bank", "", "", False, EXISTING, EXISTING),
    ("C0022", "Federal Home Loan Bank of New York", "US", "522292", "Government-sponsored enterprise", "Government Sponsored Entity", "", "", False, EXISTING, EXISTING),
    ("C0023", "Port Authority of Metro City", "US", "488310", "Public authority", "Public Sector Entity", "", "", False, EXISTING, EXISTING),
    ("C0024", "Metro City VRDN Program", "US", "921130", "Municipal VRDN issuer", "Municipalities for VRDN Structures", "", "", False, EXISTING, EXISTING),
    ("C0030", "State Teachers Pension Plan", "US", "525110", "Public pension plan", "Pension Fund", "", "", True, EXISTING, EXISTING),
    ("C0031", "Regional Community Bank", "US", "522110", "Commercial bank", "Bank", "", "", True, EXISTING, EXISTING),
    ("C0032", "Midwest Securities LLC", "US", "523120", "Registered broker-dealer", "Broker Dealer", "", "", True, EXISTING, EXISTING),
    ("C0033", "Vanguardia Asset Management", "US", "523920", "Registered investment adviser", "Investment Company or Advisor", "", "", True, EXISTING, EXISTING),
    ("C0034", "Depository Clearing Corp", "US", "522320", "Clearing agency", "Financial Market Utlility", "", "", False, EXISTING, EXISTING),
    ("C0035", "Harbor Receivables Funding LLC", "US", "525990", "Securitization SPV", "Debt Issuing Special Purpose Entity", "", "", False, EXISTING, EXISTING),
    ("C0036", "Blue Ridge Capital Partners Fund", "KY", "525990", "Private fund (hedge fund)", "Non-regulated Fund", "", "", True, EXISTING, EXISTING),
    ("C0037", "Structured Settlement Trusts", "US", "525920", "Trusts", "Other", "", "", False, EXISTING, EXISTING),
    ("C0101", "JPMorgan Chase Bank N.A.", "US", "522110", "Commercial bank", "Bank", "JP Morgan Chase", "", True, EXISTING, EXISTING),
    ("C0102", "Barclays Bank PLC", "GB", "522110", "Commercial bank", "Bank", "Barclays", "", True, EXISTING, EXISTING),
    ("C0103", "Citibank N.A.", "US", "522110", "Commercial bank", "Bank", "Citigroup", "", True, EXISTING, EXISTING),
    ("C0104", "Goldman Sachs Bank USA", "US", "522110", "Commercial bank", "Bank", "Goldman Sachs", "", True, EXISTING, EXISTING),
    ("C0105", "Wells Fargo Bank N.A.", "US", "522110", "Commercial bank", "Bank", "Wells Fargo", "", True, EXISTING, EXISTING),
    ("C0106", "Bank of America N.A.", "US", "522110", "Commercial bank", "Bank", "Bank of America", "", True, EXISTING, EXISTING),
    ("C0107", "Deutsche Bank AG", "DE", "522110", "Commercial bank", "Bank", "Deutsche Bank", "", True, EXISTING, EXISTING),
    ("C0108", "HSBC Bank PLC", "GB", "522110", "Commercial bank", "Bank", "HSBC", "", True, EXISTING, EXISTING),
    ("C0200", "Acme Financial Holdings Inc", "US", "551111", "Bank holding company (affiliate)", "Other", "", "LE00", True, EXISTING, EXISTING),
    ("C0201", "Acme Capital Markets Europe Ltd", "GB", "523120", "Investment firm (affiliate)", "Broker Dealer", "", "LE04", True, EXISTING, EXISTING),
    ("C0202", "Acme Securities LLC", "US", "523120", "Registered broker-dealer (affiliate)", "Broker Dealer", "", "LE03", True, EXISTING, EXISTING),
    ("C0203", "Acme National Bank N.A.", "US", "522110", "National bank (affiliate)", "Bank", "", "LE02", True, EXISTING, EXISTING),
    ("C0205", "Acme Funding Corp", "US", "525990", "Funding vehicle (affiliate)", "Debt Issuing Special Purpose Entity", "", "LE05", True, EXISTING, EXISTING),
    # onboarded during the reporting window - classified by AI, approved by the data steward
    ("C0301", "Northwind Logistics Inc", "US", "484121", "Corporation", "Non-Financial Corporate", "", "", True, "2026-01-12", "2026-01-13"),
    ("C0302", "Treasury of the Republic of Valdoria", "VD", "921130", "Sovereign government ministry", "Sovereign", "", "", False, "2026-01-20", "2026-01-21"),
    ("C0303", "Harbor Point Government Money Market Fund", "US", "525910", "Registered open-end fund (1940 Act)", "Investment Company or Advisor", "", "", True, "2026-02-02", "2026-02-03"),
    ("C0304", "UBS AG Stamford Branch", "US", "522110", "Foreign bank branch", "Bank", "UBS", "", True, "2026-02-09", "2026-02-10"),
    ("C0305", "Lakeside Regional Water Authority", "US", "221310", "Special-purpose public authority", "Public Sector Entity", "", "", False, "2026-02-24", None),
    ("C0306", "Cedar Creek Credit Opportunities Fund LP", "KY", "525990", "Private credit fund (limited partnership)", "Non-regulated Fund", "", "", True, "2026-02-26", None),
]

# Bank product codes per source system -> standard product type (the "standard product type reclassification")
SYSTEM_PREFIX = {"STATESTREET_CUSTODY": "SST", "ACBS_LOANS": "ACB", "MUREX": "MX", "FISERV_DDA": "FIS", "QUANTUM_TREASURY": "QTM",
                 "ALGO_COLLATERAL": "ALG", "AXIOM_REGCALC": "AXR", "ORACLE_GL": "OGL", "BROKERAGE_BOOKS": "BRK"}
EXTRA_CODES = {  # standard type -> additional bank product codes (several products of a system map to one standard type)
    "DDA": [("FIS-CHK-PERS", "Personal checking"), ("FIS-CHK-BUS", "Business checking"), ("FIS-ANLYS", "Commercial analysis checking")],
    "SAV": [("FIS-MMDA", "Money market deposit account"), ("FIS-STMT-SAV", "Statement savings")],
    "TD": [("FIS-CD-RET", "Retail certificate of deposit"), ("FIS-CD-JUMBO", "Jumbo certificate of deposit")],
    "TERM-LOAN": [("ACB-CRE-TERM", "Commercial real estate term loan"), ("ACB-MORT-RES", "Residential mortgage"), ("ACB-AUTO", "Auto loan")],
    "SEC-POS": [("SST-AFS", "Available-for-sale securities"), ("SST-HTM", "Held-to-maturity securities"), ("SST-TRD", "Trading securities")],
    "REPO": [("MX-REPO-TRI", "Tri-party repo"), ("MX-REPO-BIL", "Bilateral repo")],
    "REVREPO": [("MX-RREPO-TRI", "Tri-party reverse repo"), ("MX-RREPO-BIL", "Bilateral reverse repo")],
    "DERIV-CF": [("MX-IRS-CF", "Interest rate swap cash flow"), ("MX-CDS-CF", "Credit default swap cash flow")],
}

# Lendable value: discount-window / FHLB style margins by pledge venue and asset class (fraction of market value)
LENDABLE_HAIRCUTS = [  # venue, collateral class prefix or HQLA level, haircut
    ("ANY", "CASH", 0.0), ("Federal Reserve Bank", "Level 1", 0.01), ("Federal Reserve Bank", "Level 2A", 0.03),
    ("Federal Reserve Bank", "Level 2B", 0.08), ("Federal Reserve Bank", "L-", 0.28), ("Federal Reserve Bank", "Non-HQLA", 0.15),
    ("Federal Home Loan Bank", "L-1", 0.20), ("Federal Home Loan Bank", "L-", 0.30), ("Federal Home Loan Bank", "Level 1", 0.02),
    ("Federal Home Loan Bank", "Level 2A", 0.05), ("NONE", "Level 1", 0.02), ("NONE", "Level 2A", 0.05), ("NONE", "Level 2B", 0.15),
    ("NONE", "Non-HQLA", 0.30),
]
# Substitutable collateral: generic attributes in the contract -> Collateral Class (Oracle "substitutable collateral")
GENERIC_COLLATERAL = [("US_TREASURY", "BOND", "A-1-Q"), ("US_AGENCY_GUARANTEED", "MBS", "A-3-Q"), ("GSE", "MBS", "G-2-Q"),
                      ("SOVEREIGN_0RW", "BOND", "S-1-Q"), ("CORPORATE_IG", "BOND", "IG-1-Q"), ("CORPORATE_HY", "BOND", "N-2"),
                      ("EQUITY_RUSSELL_1000", "EQUITY", "E-1-Q"), ("CASH", "CASH", "A-0-Q")]
# Products expected by entity type (Fed post-submission check 9 "Missing required products by entity type")
EXPECTED_PRODUCTS = {
    "BHC": ["I.A.1", "I.A.3", "O.D.1", "O.W.11", "O.S.1", "S.L.6", "S.B.5", "S.DC.1", "S.DC.2"],
    "Lead Bank": ["I.A.1", "I.A.3", "I.U.6", "O.D.1", "O.D.4", "O.O.4", "S.L.6"],
    "Broker Dealer": ["I.S.1", "O.S.1", "S.I.1", "O.W.18"],
}


def write(name, header, rows):
    with open(os.path.join(OUT, name), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    print(f"  {name}: {len(rows)} rows")


def lei(i):
    return f"5493{i:014d}AC"[:20]


def main():
    products = list(csv.DictReader(open(os.path.join(OUT, "spec_products.csv"), encoding="utf-8")))
    page = {r["product_id"]: r["definition_page"] for r in products}
    catalog, rules, codes = [], [], []
    for system, code, desc, need_cp, need_coll, conds in CATALOG:
        catalog.append([code, system, desc, str(need_cp).lower(), str(need_coll).lower(), ",".join(dict.fromkeys(c[1] for c in conds))])
        for prio, (cond, pid, why) in enumerate(conds, 1):
            why = re.sub(r"\s*\(p\.\d+\)$", "", why) + f" (Instructions p.{page[pid]})"
            rules.append([f"PID-{code}-{prio}", code, prio, cond, pid, why])
        codes.append([system, f"{SYSTEM_PREFIX[system]}-{code}", code, desc])
        codes += [[system, c, code, d] for c, d in EXTRA_CODES.get(code, [])]
    write("ref_standard_product_type.csv", ["standard_product_type", "source_system", "description", "requires_customer",
                                            "requires_collateral", "candidate_product_ids"], catalog)
    write("ref_source_product_map.csv", ["source_system", "source_product_code", "standard_product_type", "description"], codes)
    write("rules_pid_derivation.csv", ["rule_id", "standard_product_type", "priority", "condition_sql", "product_id", "rationale"], rules)
    write("ref_legal_entity.csv", ["legal_entity_id", "legal_name", "entity_type", "parent_legal_entity_id", "country"], LEGAL_ENTITIES)
    approved = [c for c in CUSTOMERS if c[10]]
    write("ref_customer_master.csv", ["customer_id", "customer_name", "counterparty", "gsib_parent", "affiliate_legal_entity_id",
                                      "has_relationship", "approved_on", "approved_by"],
          [[c[0], c[1], c[5], c[6], c[7], str(c[8]).lower(), c[10], "initial load" if c[10] == EXISTING else "data steward"] for c in approved])
    # the onboarding (KYC) extract the bank lands daily, and the true classification of every customer (test oracle)
    write("ref_customer_onboarding.csv", ["customer_id", "customer_name", "country", "naics_code", "legal_form", "lei", "onboarded_on"],
          [[c[0], c[1], c[2], c[3], c[4], lei(i) if c[3] else "", c[9]] for i, c in enumerate(CUSTOMERS)])
    write("ref_customer_answer_key.csv", ["customer_id", "true_counterparty", "true_gsib_parent", "true_affiliate_legal_entity_id"],
          [[c[0], c[5], c[6], c[7]] for c in CUSTOMERS])
    classes = [r["collateral_class"] for r in csv.DictReader(open(os.path.join(OUT, "spec_asset_categories.csv"), encoding="utf-8"))]
    desc = {r["collateral_class"]: r["description"] for r in csv.DictReader(open(os.path.join(OUT, "spec_asset_categories.csv"), encoding="utf-8"))}
    write("ref_security_master.csv", ["collateral_id", "description", "collateral_class"],
          [[f"SM{i + 1:04d}", desc[c][:120], c] for i, c in enumerate(classes)])
    write("ref_lendable_haircuts.csv", ["pledge_venue", "asset_key", "haircut"], LENDABLE_HAIRCUTS)
    write("ref_generic_collateral_map.csv", ["generic_issuer_type", "generic_product", "collateral_class"], GENERIC_COLLATERAL)
    write("ref_expected_products.csv", ["entity_type", "product_id"], [[t, p] for t, ps in EXPECTED_PRODUCTS.items() for p in ps])
    pids = [r["product_id"] for r in products]
    covered = {r[4] for r in rules}
    missing = [p for p in pids if p not in covered and p != "S.L.6"]   # S.L.6 is computed by the LCR engine
    if missing:
        raise SystemExit(f"PIDs no source product can derive: {missing}")
    print(f"  {len(covered)} PIDs derivable from {len(catalog)} standard product types / {len(codes)} bank product codes")


if __name__ == "__main__":
    main()
