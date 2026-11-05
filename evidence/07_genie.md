# Genie Agent - FR 2052a Liquidity Risk Genie

Captured 2026-11-05 15:46 UTC from `https://<workspace>.cloud.databricks.com` by `deploy/capture_evidence.py`.

Space `<object-id-1>` on the UC metric views, asked through the Genie Conversation API: the answer, the SQL it generated and the result.

## Q: What is the LCR ratio for each reporting entity on the latest reporting date and is it compliant?

status: COMPLETED

**Genie:** You want to see the Liquidity Coverage Ratio (LCR) for each reporting entity on the most recent reporting date, along with whether each entity meets the compliance threshold of having an LCR of at least 1.

```sql
SELECT
  `as_of_date`,
  `entity_id`,
  MEASURE(`lcr`) AS `lcr_ratio`,
  CASE WHEN MEASURE(`lcr`) >= 1 THEN true ELSE false END AS `is_compliant`
FROM `<catalog>`.`reg_lcr`.`fr2052a_lcr_metrics`
WHERE `as_of_date` = (
  SELECT MAX(`as_of_date`)
  FROM `<catalog>`.`reg_lcr`.`calculation_results`
)
GROUP BY ALL
ORDER BY `entity_id`
```

| as_of_date | entity_id | lcr_ratio | is_compliant |
|---|---|---|---|
| 2026-02-27 | ENT001 | 1.346924 | true |
| 2026-02-27 | ENT002 | 2.326095 | true |

**Genie:** On the latest reporting date, **2026-02-27**, both reporting entities shown are **compliant** with an LCR ratio above 100%.
- **ENT001:** **134.69%** — **compliant**
- **ENT002:** **232.61%** — **compliant**

Across the 2 entities returned, **ENT002** has the higher liquidity coverage ratio.

## Q: Show the LCR ratio, total HQLA and net cash outflows for ENT001 for every reporting date

status: COMPLETED

**Genie:** You want to see the Liquidity Coverage Ratio (LCR), total High-Quality Liquid Assets (HQLA), and net cash outflows for the entity ENT001 for each reporting date.

```sql
SELECT `as_of_date`, MEASURE(`lcr`) AS `lcr`, MEASURE(`hqla_usd_mm`) AS `hqla_usd_mm`, MEASURE(`net_cash_outflows_usd_mm`) AS `net_cash_outflows_usd_mm`
FROM `<catalog>`.`reg_lcr`.`fr2052a_lcr_metrics`
WHERE `entity_id` = 'ENT001'
GROUP BY ALL
ORDER BY `as_of_date` ASC
```

| as_of_date | lcr | hqla_usd_mm | net_cash_outflows_usd_mm |
|---|---|---|---|
| 2026-02-23 | 1.477228 | 51066.1334 | 34568.8915 |
| 2026-02-24 | 0.736930 | 33728.5639 | 45768.9997 |
| 2026-02-25 | 1.029205 | 50020.2253 | 48600.8306 |
| 2026-02-26 | 1.373830 | 51000.7985 | 37123.0834 |
| 2026-02-27 | 1.346924 | 50622.0584 | 37583.4473 |

**Genie:** For **ENT001**, the LCR ratio, total HQLA, and net cash outflows are shown for **5 reporting dates**:
- **2026-02-23**: **LCR 147.72%**, **HQLA $51,066.1M**, **net cash outflows $34,568.9M**
- **2026-02-24**: **LCR 73.69%**, **HQLA $33,728.6M**, **net cash outflows $45,769.0M**
- **2026-02-25**: **LCR 102.92%**, **HQLA $50,020.2M**, **net cash outflows $48,600.8M**
- **2026-02-26**: **LCR 137.38%**, **HQLA $51,000.8M**, **net cash outflows $37,123.1M**
- **2026-02-27**: **LCR 134.69%**, **HQLA $50,622.1M**, **net cash outflows $37,583.4M**

Across these dates, **2026-02-24** is the weakest day, with the **lowest LCR** and **lowest HQLA**, while **2026-02-25** has the **highest net cash outflows**.

## Q: Break down reported outflows by FR 2052a table for the latest date

status: COMPLETED

**Genie:** You want to see the breakdown of reported outflows by FR 2052a table for the latest date for the ENT001 reporting entity.

```sql
SELECT `reporting_entity`, `table_code`, `table_name`, MEASURE(`outflows_usd_mm`) AS `outflows_usd_mm`, MEASURE(`records`) AS `records`, MEASURE(`positions`) AS `positions`
FROM `<catalog>`.`reg_2052a`.`fr2052a_metrics`
WHERE `as_of_date` = (SELECT MAX(`as_of_date`) FROM `<catalog>`.`reg_2052a`.`v_filing_records`)
  AND `flow_side` = 'Outflow'
  AND `reporting_entity` = 'ENT001'
  AND `table_code` IS NOT NULL
  AND `table_name` IS NOT NULL
GROUP BY ALL
ORDER BY `outflows_usd_mm` DESC
```

| reporting_entity | table_code | table_name | outflows_usd_mm | records | positions |
|---|---|---|---|---|---|
| ENT001 | O.D | Outflows-Deposits | 78119.544888000 | 40 | 78 |
| ENT001 | O.O | Outflows-Other | 48621.785800000 | 33 | 40 |
| ENT001 | O.W | Outflows-Wholesale | 40079.320497800 | 28 | 36 |
| ENT001 | O.S | Outflows-Secured | 31220.072500000 | 18 | 24 |

**Genie:** For the latest date shown, **ENT001** reported outflows across **4** FR 2052a tables, led by **O.D (Outflows-Deposits)** at **$78,119.54M**. Outflows then step down through the other tables, with deposits clearly the largest category and secured outflows the smallest.

- **O.D — Outflows-Deposits:** **$78,119.54M** across **40** records and **78** positions
- **O.O — Outflows-Other:** **$48,621.79M** across **33** records and **40** positions
- **O.W — Outflows-Wholesale:** **$40,079.32M** across **28** records and **36** positions
- **O.S — Outflows-Secured:** **$31,220.07M** across **18** records and **24** positions

## Q: Which validation rules failed or warned on the latest date?

status: COMPLETED

**Genie:** You want to see the validation rules that either failed or issued warnings on the most recent date available in the data.

```sql
SELECT
  `rule_id`,
  `rule_source`,
  `table_code`,
  `rule_name`,
  `severity`,
  `status`,
  `records_failed`,
  `failure_details`
FROM `<catalog>`.`reg_2052a`.`gold_validation`
WHERE `as_of_date` = (
  SELECT MAX(`as_of_date`)
  FROM `<catalog>`.`reg_2052a`.`gold_validation`
)
  AND `status` IN ('FAIL', 'WARNING')
  AND `status` IS NOT NULL
  AND `rule_id` IS NOT NULL
ORDER BY `status` ASC, `rule_id` ASC
```

| rule_id | rule_source | table_code | rule_name | severity | status | records_failed | failure_details |
|---|---|---|---|---|---|---|---|
| PSV-06 | Fed PSV | ALL | Symmetry of intercompany transactions | WARNING | WARNING | 1 | unsecured: ENT003 internal inflows 500.00 vs ENT002 internal outflows 0.00 |
| PSV-14 | Fed PSV | ALL | Large other product or counterparty balance | WARNING | WARNING | 6 | ENT001 I.U.8 counterparty Bank: USD 1,462 mm; ENT001 O.S.11 counterparty Non-Financial Corporate: USD 1,287 mm; ENT001 S.B.4 counterparty None: USD 6,226 mm; ENT002 I.U.8 counterparty Bank: USD 1,462 mm; ENT002 S.B.4 counterparty None: USD 6,226 mm |
| RECON-GL | Reconciliation |  | General ledger vs the filing, by legal entity and table (tolerance 0.5%) | WARNING | WARNING | 1 | GL vs LE02 O.D: GL 121,079.7 vs filing 78,837.7 USD mm (-34.89%) - GL-LE02-OD (ORACLE_GL) - tolerance 0.5%; includes 727.6 held for customer approval |

**Genie:** On the latest date in the validation results, there were **3** rules with issues, and **all 3 were warnings**; no failed rules are shown in the data.

- **PSV-06** (**Fed PSV**, table **ALL**): **Symmetry of intercompany transactions** — **1** record flagged
- **PSV-14** (**Fed PSV**, table **ALL**): **Large other product or counterparty balance** — **6** records flagged
- **RECON-GL** (**Reconciliation**): **General ledger vs the filing, by legal entity and table (tolerance 0.5%)** — **1** record flagged

This sample shows the latest issues were concentrated in **warnings only**, with **PSV-14** affecting the most records.

