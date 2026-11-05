---
name: fr2052a-daily-review
description: FR 2052a daily filing review. Gives the liquidity reporting team one page on whether a day's FR 2052a (6G) filing is ready to sign off - run and sign-off state, failed checks (6G business rules, appendix rules, the Fed's 14 post-submission checks), GL breaks, LCR per entity, unusual movements and open AI suggestions. Use when someone asks whether the FR 2052a / 2052a filing is ready, what blocks sign-off, or for the daily 2052a review.
---

# FR 2052a Daily Filing Review

*Owner: Regulatory Reporting (liquidity). Purpose: one consistent page the reviewer reads before approving a reporting run.*

## What to use

Only these governed Unity Catalog table functions (USD millions; dates are business days, 2026-01-02 to 2026-02-27):

| Function | Returns |
|---|---|
| `${catalog}.ai_assist.filing_status(DATE'yyyy-mm-dd')` | run number, sign-off status, records, positions, fails, warnings, Fed PSV not passing, GL breaks, open AI suggestions |
| `${catalog}.ai_assist.validation_issues(DATE'yyyy-mm-dd')` | every check that did not pass, with the AI explanation |
| `${catalog}.ai_assist.lcr_summary(DATE'yyyy-mm-dd')` | LCR per LCR entity (ENT001 consolidated BHC, ENT002 bank) |
| `${catalog}.ai_assist.variance_anomalies(DATE'yyyy-mm-dd')` | movements outside the ai_forecast range, with drafted commentary |
| `${catalog}.ai_assist.open_suggestions(DATE'yyyy-mm-dd')` | AI suggestions waiting for a human decision |

If the user gives no date, use the latest: `SELECT MAX(as_of_date) FROM ${catalog}.reg_2052a.gold_validation`.

## The report (always in this order)

### 1. Verdict
One line: **Ready to sign off**, **Ready with warnings**, or **Not ready**. It is *Not ready* when there is any FAIL with
severity ERROR, any Fed post-submission check (rule_source = 'Fed PSV') not passing with severity ERROR, or any GL break.
State the run number and the current sign-off status.

### 2. Scorecard
A markdown table: records, positions, validation fails, warnings, Fed PSV not passing, GL breaks, open AI suggestions.

### 3. What blocks sign-off
One bullet per FAIL (ERROR first): rule id, table, records failed, the plain-English explanation, and the fix.
Say which team owns the fix: source system owner (data), master data (customer / product), rules (PID), or the
reviewer (adjustment).

### 4. LCR
A table per LCR entity: HQLA, outflows, capped inflows, net cash outflows, LCR. Flag an LCR below 100%.

### 5. Unusual movements
Up to five rows from `variance_anomalies`, biggest move first, with the commentary.

### 6. Decisions waiting
Counts of open suggestions by type, and a reminder that they are accepted or rejected in the FR 2052a app
(Enrichment, PID and Review pages). Never accept or reject them yourself.

## Rules
- Do not invent numbers; every figure comes from the functions above.
- Amounts are USD millions; LCR is a decimal ratio - show it as a percentage.
- This is a synthetic demo firm; no real customer data.
