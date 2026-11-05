---
name: fr2052a-variance-explainer
description: Explains a day-over-day FR 2052a movement. For a reporting entity and table (or product ID) it shows the change against the ai_forecast expected range and drills from the filed records to the source positions that moved. Use when someone asks why an FR 2052a table, product, or the LCR moved, or asks to explain a 2052a variance or anomaly.
---

# FR 2052a Variance Explainer

*Owner: Regulatory Reporting (liquidity). Purpose: answer "why did this move?" with the records behind it.*

## What to use
- `${catalog}.ai_assist.variance_anomalies(DATE'yyyy-mm-dd')` - flagged movements and the expected range.
- `${catalog}.reg_2052a.variance` - every series (`series_level` TABLE or PID) per date, with `amount_usd`,
  `prior_amount_usd`, `change_pct`, `lower_usd`, `upper_usd`, `is_anomaly`.
- `${catalog}.reg_2052a.v_filing_records` - the filed records (`reporting_entity`, `table_code`, `product_id`,
  `counterparty`, `maturity_bucket`, `reported_amount_usd`, `record_key`).
- `${catalog}.ai_assist.record_drilldown(DATE'yyyy-mm-dd', '<record_key>')` - the positions and source records behind one record.
- `${catalog}.ai_assist.pid_rule_lookup('<PID>')` - what the product is and which rules assign it.

## Steps
1. Find the movement in `reg_2052a.variance` for the date, entity and table / PID. If the user named none, take the
   largest anomaly from `variance_anomalies`.
2. Compare the two dates in `v_filing_records` grouped by `product_id`, `counterparty` and `maturity_bucket`; list the
   five groups that moved most.
3. For the largest group, take its biggest record and call `record_drilldown` on both dates to name the source system,
   product code and positions that changed.
4. Write the answer.

## The answer
- **Headline:** entity, table / PID, prior -> current (USD mm and %), and whether it is inside the expected range.
- **Driver table:** the five groups that moved most.
- **Source:** which source system and positions drove it.
- **Assessment:** business-as-usual movement, a data issue (point to the check in `validation_issues`), or a planted
  control test; suggest an S.C comment only if the movement needs explaining to the Federal Reserve
  (plain ASCII, one sentence).
