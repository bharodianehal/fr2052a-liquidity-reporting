# Pipeline results by reporting date (Silver / Gold, SQL warehouse)

Captured 2026-11-05 15:44 UTC from `https://<workspace>.cloud.databricks.com` by `deploy/capture_evidence.py`.

## Data quality gate: assessment per date (dq.assessment_results)

```sql
SELECT as_of_date, COUNT(*) AS rules, SUM(CASE WHEN failed_records > 0 THEN 1 ELSE 0 END) AS rules_failing, SUM(failed_records) AS failed_records FROM <catalog>.dq.assessment_results WHERE as_of_date >= '2026-02-23' GROUP BY 1 ORDER BY 1
```

| as_of_date | rules | rules_failing | failed_records |
|---|---|---|---|
| 2026-02-23 | 12 | 1 | 1 |
| 2026-02-24 | 12 | 1 | 1 |
| 2026-02-25 | 12 | 2 | 2 |
| 2026-02-26 | 12 | 2 | 2 |
| 2026-02-27 | 12 | 2 | 2 |

## Quarantined records and PID exceptions

```sql
SELECT as_of_date, record_id, source_feed, failed_rules AS reason FROM <catalog>.dq.quarantine WHERE as_of_date >= '2026-02-23' UNION ALL SELECT as_of_date, record_id, source_feed, reason FROM <catalog>.dq.pid_exceptions WHERE as_of_date >= '2026-02-23' ORDER BY 1, 2
```

| as_of_date | record_id | source_feed | reason |
|---|---|---|---|
| 2026-02-23 | DEP-2026-02-23-DQ11 | deposits | DQ_011 |
| 2026-02-23 | LOA-2026-02-23-EXC02 | loans | No PID rule matched standard product type TERM-LOAN (subtype NULL, direction NULL, counterparty Non-Financial Corporate, collateral N-2) |
| 2026-02-24 | DEP-2026-02-24-00050 | deposits | Customer C0305 is onboarded but its FR 2052a classification is not approved yet |
| 2026-02-24 | DEP-2026-02-24-DQ11 | deposits | DQ_011 |
| 2026-02-24 | LOA-2026-02-24-EXC02 | loans | No PID rule matched standard product type TERM-LOAN (subtype NULL, direction NULL, counterparty Non-Financial Corporate, collateral N-2) |
| 2026-02-25 | DEP-2026-02-25-00050 | deposits | Customer C0305 is onboarded but its FR 2052a classification is not approved yet |
| 2026-02-25 | DEP-2026-02-25-DQ11 | deposits | DQ_011 |
| 2026-02-25 | DEP-2026-02-25-NEWCODE | deposits | DQ_006 |
| 2026-02-25 | LOA-2026-02-25-EXC02 | loans | No PID rule matched standard product type TERM-LOAN (subtype NULL, direction NULL, counterparty Non-Financial Corporate, collateral N-2) |
| 2026-02-26 | DEP-2026-02-26-00050 | deposits | Customer C0305 is onboarded but its FR 2052a classification is not approved yet |
| 2026-02-26 | DEP-2026-02-26-DQ11 | deposits | DQ_011 |
| 2026-02-26 | DEP-2026-02-26-NEWCODE | deposits | DQ_006 |
| 2026-02-26 | FUN-2026-02-26-00037 | funding | Customer C0306 is onboarded but its FR 2052a classification is not approved yet |
| 2026-02-26 | LOA-2026-02-26-EXC02 | loans | No PID rule matched standard product type TERM-LOAN (subtype NULL, direction NULL, counterparty Non-Financial Corporate, collateral N-2) |
| 2026-02-27 | DEP-2026-02-27-00050 | deposits | Customer C0305 is onboarded but its FR 2052a classification is not approved yet |
| 2026-02-27 | DEP-2026-02-27-DQ11 | deposits | DQ_011 |
| 2026-02-27 | DEP-2026-02-27-NEWCODE | deposits | DQ_006 |
| 2026-02-27 | FUN-2026-02-27-00037 | funding | Customer C0306 is onboarded but its FR 2052a classification is not approved yet |
| 2026-02-27 | LOA-2026-02-27-EXC02 | loans | No PID rule matched standard product type TERM-LOAN (subtype NULL, direction NULL, counterparty Non-Financial Corporate, collateral N-2) |

## PID derivation (audit.pid_derivation_summary)

```sql
SELECT as_of_date, source_records, positions, derived, exceptions, answer_key_checked, answer_key_mismatches, accuracy_pct FROM <catalog>.audit.pid_derivation_summary WHERE as_of_date >= '2026-02-23' ORDER BY 1
```

| as_of_date | source_records | positions | derived | exceptions | answer_key_checked | answer_key_mismatches | accuracy_pct |
|---|---|---|---|---|---|---|---|
| 2026-02-23 | 350 | 396 | 395 | 1 | 349 | 0 | 100.00 |
| 2026-02-24 | 349 | 395 | 393 | 2 | 347 | 0 | 100.00 |
| 2026-02-25 | 352 | 398 | 396 | 2 | 350 | 0 | 100.00 |
| 2026-02-26 | 341 | 388 | 385 | 3 | 338 | 0 | 100.00 |
| 2026-02-27 | 363 | 397 | 394 | 3 | 360 | 0 | 100.00 |

## LCR per entity (reg_lcr.calculation_results)

```sql
SELECT as_of_date, entity_id, ROUND(total_hqla, 1) AS hqla, ROUND(total_outflows, 1) AS outflows, ROUND(capped_inflows, 1) AS inflows_capped, ROUND(total_net_cash_outflows, 1) AS nco, ROUND(lcr_ratio * 100, 2) AS lcr_pct, lcr_compliant FROM <catalog>.reg_lcr.calculation_results WHERE as_of_date >= '2026-02-23' ORDER BY 1, 2
```

| as_of_date | entity_id | hqla | outflows | inflows_capped | nco | lcr_pct | lcr_compliant |
|---|---|---|---|---|---|---|---|
| 2026-02-23 | ENT001 | 51066.1 | 50270.4 | 15701.5 | 34568.9 | 147.72 | true |
| 2026-02-23 | ENT002 | 47839.3 | 37192.4 | 10032.2 | 27160.2 | 176.14 | true |
| 2026-02-24 | ENT001 | 33728.6 | 60757.9 | 15718.8 | 45769.0 | 73.69 | false |
| 2026-02-24 | ENT002 | 30477.7 | 38516.3 | 10047.9 | 28468.4 | 107.06 | true |
| 2026-02-25 | ENT001 | 50020.2 | 59415.9 | 10815.1 | 48600.8 | 102.92 | true |
| 2026-02-25 | ENT002 | 47569.0 | 37312.1 | 7074.3 | 30237.8 | 157.32 | true |
| 2026-02-26 | ENT001 | 51000.8 | 50956.8 | 14061.3 | 37123.1 | 137.38 | true |
| 2026-02-26 | ENT002 | 47691.1 | 34126.8 | 8381.5 | 25745.3 | 185.24 | true |
| 2026-02-27 | ENT001 | 50622.1 | 51249.6 | 14168.7 | 37583.4 | 134.69 | true |
| 2026-02-27 | ENT002 | 47289.8 | 28830.3 | 8500.2 | 20330.1 | 232.61 | true |

## Filing records by entity and table, 2026-02-27 (reg_2052a.v_filing_records)

```sql
SELECT reporting_entity, table_code, COUNT(*) AS records, ROUND(SUM(reported_amount_usd), 1) AS amount_usd FROM <catalog>.reg_2052a.v_filing_records WHERE as_of_date = '2026-02-27' GROUP BY 1, 2 ORDER BY 1, 2
```

| reporting_entity | table_code | records | amount_usd |
|---|---|---|---|
| ENT001 | I.A | 34 | 93875.6 |
| ENT001 | I.O | 15 | 9156.0 |
| ENT001 | I.S | 15 | 20286.3 |
| ENT001 | I.U | 18 | 35711.7 |
| ENT001 | O.D | 40 | 78119.5 |
| ENT001 | O.O | 33 | 48621.8 |
| ENT001 | O.S | 18 | 31220.1 |
| ENT001 | O.W | 28 | 40079.3 |
| ENT001 | S.B | 8 | 42409.5 |
| ENT001 | S.DC | 27 | 40967.2 |
| ENT001 | S.FX | 7 | 3693.8 |
| ENT001 | S.I | 6 | 24489.0 |
| ENT001 | S.L | 10 | 10296.2 |
| ENT002 | I.A | 34 | 93875.6 |
| ENT002 | I.O | 5 | 1088.3 |
| ENT002 | I.S | 3 | 3080.1 |
| ENT002 | I.U | 17 | 34705.4 |
| ENT002 | O.D | 40 | 78110.0 |
| ENT002 | O.O | 16 | 28809.7 |
| ENT002 | O.S | 4 | 7100.7 |
| ENT002 | O.W | 3 | 4114.0 |
| ENT002 | S.B | 2 | 7159.9 |
| ENT002 | S.L | 2 | 3.6 |
| ENT003 | I.O | 10 | 8067.7 |
| ENT003 | I.S | 13 | 18406.2 |
| ENT003 | I.U | 1 | 500.0 |
| ENT003 | O.O | 17 | 19812.1 |
| ENT003 | O.S | 15 | 25319.4 |
| ENT003 | O.W | 7 | 5362.6 |
| ENT003 | S.DC | 27 | 40967.2 |
| ENT003 | S.FX | 7 | 3693.8 |
| ENT003 | S.I | 4 | 16395.2 |

## Validation by source and status (reg_2052a.gold_validation)

```sql
SELECT as_of_date, rule_source, status, COUNT(*) AS rules FROM <catalog>.reg_2052a.gold_validation WHERE as_of_date >= '2026-02-23' GROUP BY ALL ORDER BY 1, 2, 3
```

| as_of_date | rule_source | status | rules |
|---|---|---|---|
| 2026-02-23 | 6G BR | PASS | 652 |
| 2026-02-23 | 6G BR General | NOT_APPLICABLE | 1 |
| 2026-02-23 | 6G BR General | PASS | 3 |
| 2026-02-23 | 6G XSD | PASS | 2 |
| 2026-02-23 | Fed PSV | PASS | 12 |
| 2026-02-23 | Fed PSV | WARNING | 2 |
| 2026-02-23 | Instructions | FAIL | 5 |
| 2026-02-23 | Instructions | PASS | 404 |
| 2026-02-23 | Reconciliation | PASS | 1 |
| 2026-02-23 | Reconciliation | WARNING | 1 |
| 2026-02-24 | 6G BR | PASS | 652 |
| 2026-02-24 | 6G BR General | NOT_APPLICABLE | 1 |
| 2026-02-24 | 6G BR General | PASS | 3 |
| 2026-02-24 | 6G XSD | PASS | 2 |
| 2026-02-24 | Fed PSV | PASS | 13 |
| 2026-02-24 | Fed PSV | WARNING | 1 |
| 2026-02-24 | Instructions | FAIL | 2 |
| 2026-02-24 | Instructions | PASS | 407 |
| 2026-02-24 | Reconciliation | PASS | 1 |
| 2026-02-24 | Reconciliation | WARNING | 1 |
| 2026-02-25 | 6G BR | PASS | 652 |
| 2026-02-25 | 6G BR General | NOT_APPLICABLE | 1 |
| 2026-02-25 | 6G BR General | PASS | 3 |
| 2026-02-25 | 6G XSD | PASS | 2 |
| 2026-02-25 | Fed PSV | PASS | 12 |
| 2026-02-25 | Fed PSV | WARNING | 2 |
| 2026-02-25 | Instructions | PASS | 409 |
| 2026-02-25 | Reconciliation | PASS | 1 |
| 2026-02-25 | Reconciliation | WARNING | 1 |
| 2026-02-26 | 6G BR | PASS | 652 |
| 2026-02-26 | 6G BR General | NOT_APPLICABLE | 1 |
| 2026-02-26 | 6G BR General | PASS | 3 |
| 2026-02-26 | 6G XSD | PASS | 2 |
| 2026-02-26 | Fed PSV | PASS | 13 |
| 2026-02-26 | Fed PSV | WARNING | 1 |
| 2026-02-26 | Instructions | FAIL | 7 |
| 2026-02-26 | Instructions | PASS | 402 |
| 2026-02-26 | Reconciliation | PASS | 1 |
| 2026-02-26 | Reconciliation | WARNING | 1 |
| 2026-02-27 | 6G BR | PASS | 652 |
| 2026-02-27 | 6G BR General | PASS | 4 |
| 2026-02-27 | 6G XSD | PASS | 3 |
| 2026-02-27 | Fed PSV | PASS | 12 |
| 2026-02-27 | Fed PSV | WARNING | 2 |
| 2026-02-27 | Instructions | PASS | 409 |
| 2026-02-27 | Reconciliation | PASS | 1 |
| 2026-02-27 | Reconciliation | WARNING | 1 |

## Rules not passing

```sql
SELECT as_of_date, entity_id, rule_id, severity, status, records_failed, substr(failure_details, 1, 120) AS details FROM <catalog>.reg_2052a.gold_validation WHERE status IN ('FAIL', 'WARNING') AND as_of_date >= '2026-02-23' ORDER BY 1, 2, 3
```

| as_of_date | entity_id | rule_id | severity | status | records_failed | details |
|---|---|---|---|---|---|---|
| 2026-02-23 | ENT001 | PSV-06 | WARNING | WARNING | 1 | unsecured: ENT002 internal inflows 700.00 vs ENT003 internal outflows 0.00 |
| 2026-02-23 | ENT001 | PSV-14 | WARNING | WARNING | 4 | ENT001 I.U.8 counterparty Bank: USD 1,473 mm; ENT001 O.S.11 counterparty Non-Financial Corporate: USD 1,275 mm; ENT002 I |
| 2026-02-23 | ENT001 | RECON-GL | WARNING | WARNING | 4 | GL vs LE00 O.W: GL 23,919.6 vs filing 17,541.5 USD mm (-26.66%) - GL-LE00-OW (ORACLE_GL) - tolerance 0.5%; GL vs LE03 O. |
| 2026-02-23 | ENT001 | SPEC-V-05 | ERROR | FAIL | 1 | SEC-2026-02-23-00062 not linked to O.W.1,O.W.2,O.W.3,O.W.4,O.W.5,O.W.6,O.W.7,O.S.1,O.S.2,O.S.3,O.S.4,O.S.5,O.S.6,O.S.11, |
| 2026-02-23 | ENT001 | SPEC-V-06 | ERROR | FAIL | 1 | net 30-day derivative -133.24 vs flows -664.34 |
| 2026-02-23 | ENT001 | SPEC-V-07 | ERROR | FAIL | 1 | net 30-day derivative -133.24 vs flows -664.34 |
| 2026-02-23 | ENT001 | SPEC-V-08 | ERROR | FAIL | 1 | net 30-day derivative -133.24 vs flows -664.34 |
| 2026-02-23 | ENT001 | SPEC-V-09 | ERROR | FAIL | 1 | net 30-day derivative -133.24 vs flows -664.34 |
| 2026-02-24 | ENT001 | PSV-14 | WARNING | WARNING | 4 | ENT001 I.U.8 counterparty Bank: USD 1,475 mm; ENT001 O.S.11 counterparty Non-Financial Corporate: USD 1,272 mm; ENT002 I |
| 2026-02-24 | ENT001 | RECON-GL | WARNING | WARNING | 2 | GL vs LE00 O.W: GL 23,976.2 vs filing 23,774.1 USD mm (-0.84%) - GL-LE00-OW (ORACLE_GL) - tolerance 0.5%; GL vs LE02 I.A |
| 2026-02-24 | ENT001 | SPEC-V-04 | ERROR | FAIL | 7 | LOA-2026-02-24-00016 not linked to I.A.1,I.A.2,I.A.7; LOA-2026-02-24-00020 not linked to I.A.1,I.A.2,I.A.7; LOA-2026-02- |
| 2026-02-24 | ENT001 | SPEC-V-21 | ERROR | FAIL | 2 | DER-2026-02-24-00015 not linked to I.A.1,I.A.2; DER-2026-02-24-00017 not linked to I.A.1,I.A.2 |
| 2026-02-25 | ENT001 | PSV-06 | WARNING | WARNING | 2 | secured: ENT003 internal inflows 0.00 vs ENT002 internal outflows 1,200.00; unsecured: ENT003 internal inflows 0.00 vs E |
| 2026-02-25 | ENT001 | PSV-14 | WARNING | WARNING | 2 | ENT001 O.S.11 counterparty Non-Financial Corporate: USD 1,277 mm; ENT003 O.S.11 counterparty Non-Financial Corporate: US |
| 2026-02-25 | ENT001 | RECON-GL | WARNING | WARNING | 5 | GL vs LE02 I.S: GL 3,062.3 vs filing 1,585.4 USD mm (-48.23%) - GL-LE02-IS (ORACLE_GL) - tolerance 0.5%; GL vs LE02 I.U: |
| 2026-02-26 | ENT001 | PSV-14 | WARNING | WARNING | 4 | ENT001 I.U.8 counterparty Bank: USD 1,467 mm; ENT001 O.S.11 counterparty Non-Financial Corporate: USD 1,271 mm; ENT002 I |
| 2026-02-26 | ENT001 | RECON-GL | WARNING | WARNING | 5 | GL vs LE02 I.O: GL 1,086.9 vs filing 569.6 USD mm (-47.60%) - GL-LE02-IO (ORACLE_GL) - tolerance 0.5%; GL vs LE02 O.O: G |
| 2026-02-26 | ENT001 | SPEC-V-06 | ERROR | FAIL | 1 | net 30-day derivative -208.45 vs flows -602.72 |
| 2026-02-26 | ENT001 | SPEC-V-07 | ERROR | FAIL | 1 | net 30-day derivative -208.45 vs flows -602.72 |
| 2026-02-26 | ENT001 | SPEC-V-08 | ERROR | FAIL | 1 | net 30-day derivative -208.45 vs flows -602.72 |
| 2026-02-26 | ENT001 | SPEC-V-09 | ERROR | FAIL | 1 | net 30-day derivative -208.45 vs flows -602.72 |
| 2026-02-26 | ENT001 | SPEC-V-11 | ERROR | FAIL | 1 | O.O.13 1,046.2 > O.O.14 0.0 |
| 2026-02-26 | ENT001 | SPEC-V-12 | ERROR | FAIL | 1 | O.O.10 366.2 > O.O.11 0.0 |
| 2026-02-26 | ENT001 | SPEC-V-13 | ERROR | FAIL | 1 | DER-2026-02-26-00006 not linked to S.DC.7,S.DC.10 |
| 2026-02-27 | ENT001 | PSV-06 | WARNING | WARNING | 1 | unsecured: ENT003 internal inflows 500.00 vs ENT002 internal outflows 0.00 |
| 2026-02-27 | ENT001 | PSV-14 | WARNING | WARNING | 6 | ENT001 I.U.8 counterparty Bank: USD 1,462 mm; ENT001 O.S.11 counterparty Non-Financial Corporate: USD 1,287 mm; ENT001 S |
| 2026-02-27 | ENT001 | RECON-GL | WARNING | WARNING | 1 | GL vs LE02 O.D: GL 121,079.7 vs filing 78,837.7 USD mm (-34.89%) - GL-LE02-OD (ORACLE_GL) - tolerance 0.5%; includes 727 |

## Reconciliation, 2026-02-27

```sql
SELECT entity_id, recon_type AS check_name, ROUND(gl_total, 1) AS expected, ROUND(pipeline_total, 1) AS actual, status FROM <catalog>.audit.gl_reconciliation WHERE as_of_date = '2026-02-27' UNION ALL SELECT entity_id, metric_name, ROUND(reg_lcr_value, 4), ROUND(reg_2052a_value, 4), status FROM <catalog>.audit.cross_metric_recon WHERE as_of_date = '2026-02-27' ORDER BY 1, 2
```

| entity_id | check_name | expected | actual | status |
|---|---|---|---|---|
| ENT001 | HQLA-eligible I.A market value (USD mm) | 50729.9261 | 50729.9260 | PASS |
| ENT001 | S.L.6 Liquidity Coverage Ratio | 1.3469 | 1.3469 | PASS |
| ENT002 | HQLA-eligible I.A market value (USD mm) | 50729.9261 | 50729.9260 | PASS |
| ENT002 | S.L.6 Liquidity Coverage Ratio | 2.3261 | 2.3261 | PASS |
| LE00 | GL vs LE00 O.W | 23288.8000 | 23312.8000 | PASS |
| LE00 | GL vs LE00 S.B | 35242.0000 | 35249.6000 | PASS |
| LE00 | GL vs LE00 S.I | 8103.3000 | 8093.8000 | PASS |
| LE02 | GL vs LE02 I.A | 93815.0000 | 93875.6000 | PASS |
| LE02 | GL vs LE02 I.O | 1087.9000 | 1088.3000 | PASS |
| LE02 | GL vs LE02 I.S | 3082.5000 | 3080.1000 | PASS |
| LE02 | GL vs LE02 I.U | 34738.7000 | 34705.4000 | PASS |
| LE02 | GL vs LE02 O.D | 121079.7000 | 78837.7000 | BREAK |
| LE02 | GL vs LE02 O.O | 28841.6000 | 28809.7000 | PASS |
| LE02 | GL vs LE02 O.S | 7106.5000 | 7100.7000 | PASS |
| LE02 | GL vs LE02 O.W | 4114.3000 | 4114.0000 | PASS |
| LE02 | GL vs LE02 S.B | 7153.7000 | 7159.9000 | PASS |
| LE03 | GL vs LE03 I.O | 8066.3000 | 8067.7000 | PASS |
| LE03 | GL vs LE03 I.S | 18407.0000 | 18406.2000 | PASS |
| LE03 | GL vs LE03 I.U | 499.4000 | 500.0000 | PASS |
| LE03 | GL vs LE03 O.O | 19789.6000 | 19812.1000 | PASS |
| LE03 | GL vs LE03 O.S | 25348.2000 | 25319.4000 | PASS |
| LE03 | GL vs LE03 O.W | 6088.7000 | 6093.9000 | PASS |
| LE03 | GL vs LE03 S.DC | 41006.1000 | 40967.2000 | PASS |
| LE03 | GL vs LE03 S.I | 16382.5000 | 16395.2000 | PASS |
| LE04 | GL vs LE04 I.U | 2390.0000 | 2388.4000 | PASS |
| LE04 | GL vs LE04 O.W | 1044.2000 | 1043.3000 | PASS |
| LE05 | GL vs LE05 O.W | 6954.4000 | 6946.7000 | PASS |

## 6G files of the latest run per date (reg_2052a.submission_files)

```sql
SELECT f.as_of_date, f.run_number, f.file_type, f.file_name, f.record_count, f.xsd_valid, f.xsd_errors, f.release_status FROM <catalog>.reg_2052a.submission_files f WHERE f.as_of_date >= '2026-02-23' AND f.run_number = (SELECT MAX(run_number) FROM <catalog>.reg_2052a.submission_files x WHERE x.as_of_date = f.as_of_date) ORDER BY 1, 3
```

| as_of_date | run_number | file_type | file_name | record_count | xsd_valid | xsd_errors | release_status |
|---|---|---|---|---|---|---|---|
| 2026-02-23 | 3 | Comment | 6G_ACME_02232026.COMMENT.xml | 2 | true | 0 | BLOCKED |
| 2026-02-23 | 3 | Primary | 6G_ACME_02232026.xml | 456 | true | 0 | BLOCKED |
| 2026-02-24 | 4 | Comment | 6G_ACME_02242026.COMMENT.xml | 2 | true | 0 | BLOCKED |
| 2026-02-24 | 4 | Primary | 6G_ACME_02242026.xml | 468 | true | 0 | BLOCKED |
| 2026-02-25 | 3 | Comment | 6G_ACME_02252026.COMMENT.xml | 2 | true | 0 | READY_FOR_REVIEW |
| 2026-02-25 | 3 | Primary | 6G_ACME_02252026.xml | 469 | true | 0 | READY_FOR_REVIEW |
| 2026-02-26 | 3 | Comment | 6G_ACME_02262026.COMMENT.xml | 2 | true | 0 | BLOCKED |
| 2026-02-26 | 3 | Primary | 6G_ACME_02262026.xml | 430 | true | 0 | BLOCKED |
| 2026-02-27 | 3 | Comment | 6G_ACME_02272026.COMMENT.xml | 3 | true | 0 | READY_FOR_REVIEW |
| 2026-02-27 | 3 | Primary | 6G_ACME_02272026.xml | 473 | true | 0 | READY_FOR_REVIEW |
| 2026-02-27 | 3 | Reduced | 6G_ACME_02272026.REDUCED.xml | 13 | true | 0 | READY_FOR_REVIEW |

## 6G Primary XML, 2026-02-27 (first 1,500 characters)

```sql
SELECT file_name, substr(xml_content, 1, 1500) AS xml_head FROM <catalog>.reg_2052a.submission_files WHERE as_of_date = '2026-02-27' AND file_type = 'Primary' AND run_number = (SELECT MAX(run_number) FROM <catalog>.reg_2052a.submission_files WHERE as_of_date = '2026-02-27')
```

| file_name | xml_head |
|---|---|
| 6G_ACME_02272026.xml | <?xml version='1.0' encoding='UTF-8'?> <sixGSubmission xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="6GSchema.xsd">   <header version="1" reportingFrequency="Primary">     <reporter listingExchange="XNYS">ACME</reporter>     <reportingDate>2026-02-27</reportingDate>   </header>   <assetInflowReport reportID="1" treasuryControl="true">     <reportScope>ACME - Bank</reportScope>     <assetProduct>Unencumbered Assets</assetProduct>     <marketValue converted="false" unit="USD" unitMultiplier="6">4777.99900000</marketValue>     <lendableValue converted="false" unit="USD" unitMultiplier="6">4539.09910000</lendableValue>     <maturityBucket>       <maturityStart>P1827D</maturityStart>     </maturityBucket>     <collateralClass>G-2-Q</collateralClass>     <accountingDesignation>Held to Maturity</accountingDesignation>     <businessLine>Treasury</businessLine>   </assetInflowReport>   <assetInflowReport reportID="2" treasuryControl="true">     <reportScope>ACME - Consolidated</reportScope>     <assetProduct>Unencumbered Assets</assetProduct>     <marketValue converted="false" unit="USD" unitMultiplier="6">3822.39920000</marketValue>     <lendableValue converted="false" unit="USD" unitMultiplier="6">3745.95120000</lendableValue>     <maturityBucket>       <maturityStart>P365D</maturityStart>       <maturityEnd>P730D</maturityEnd>     </maturityBucket>     <collateralClass>A-1-Q</collateralClass>     <accountingDesignation>Available for Sale</acco |

## Lineage, 2026-02-27 (audit.data_lineage)

```sql
SELECT pipeline_name, stage, source_table, target_table, records_read, records_written FROM <catalog>.audit.data_lineage WHERE as_of_date = '2026-02-27' ORDER BY run_timestamp
```

| pipeline_name | stage | source_table | target_table | records_read | records_written |
|---|---|---|---|---|---|
| DQ Gate | Bronze -> DQ-passed source positions | raw.{deposits,loans,securities,derivatives,funding,finance} | conformed.source_position | 365 | 363 |
| Calculation & PID | Source positions -> Silver positions | conformed.source_position | conformed.fact_liquidity_position | 363 | 394 |
| Entity scoping | Silver -> reporting entities | conformed.fact_liquidity_position | conformed.entity_position | 394 | 733 |
| LCR Calculation ENT001 | Entity positions -> LCR mart | conformed.v_entity_position | reg_lcr.calculation_results | 387 | 1 |
| LCR Calculation ENT002 | Entity positions -> LCR mart | conformed.v_entity_position | reg_lcr.calculation_results | 224 | 1 |
| Report Build | Entity positions -> FR 2052a tables | conformed.v_entity_position | reg_2052a (13 data tables + comments) | 733 | 486 |
| Validation & Submission | FR 2052a tables -> 6G XML | reg_2052a (13 data tables + comments) | reg_2052a.submission_files | 486 | 3 |
| DQ Gate | Bronze -> DQ-passed source positions | raw.{deposits,loans,securities,derivatives,funding,finance} | conformed.source_position | 365 | 363 |
| Calculation & PID | Source positions -> Silver positions | conformed.source_position | conformed.fact_liquidity_position | 363 | 394 |
| Entity scoping | Silver -> reporting entities | conformed.fact_liquidity_position | conformed.entity_position | 394 | 733 |
| LCR Calculation ENT001 | Entity positions -> LCR mart | conformed.v_entity_position | reg_lcr.calculation_results | 387 | 1 |
| LCR Calculation ENT002 | Entity positions -> LCR mart | conformed.v_entity_position | reg_lcr.calculation_results | 224 | 1 |
| Report Build | Entity positions -> FR 2052a tables | conformed.v_entity_position | reg_2052a (13 data tables + comments) | 733 | 486 |
| Validation & Submission | FR 2052a tables -> 6G XML | reg_2052a (13 data tables + comments) | reg_2052a.submission_files | 486 | 3 |
| DQ Gate | Bronze -> DQ-passed source positions | raw.{deposits,loans,securities,derivatives,funding,finance} | conformed.source_position | 365 | 363 |
| Calculation & PID | Source positions -> Silver positions | conformed.source_position | conformed.fact_liquidity_position | 363 | 394 |
| Entity scoping | Silver -> reporting entities | conformed.fact_liquidity_position | conformed.entity_position | 394 | 733 |
| LCR Calculation ENT001 | Entity positions -> LCR mart | conformed.v_entity_position | reg_lcr.calculation_results | 387 | 1 |
| LCR Calculation ENT002 | Entity positions -> LCR mart | conformed.v_entity_position | reg_lcr.calculation_results | 224 | 1 |
| Report Build | Entity positions -> FR 2052a tables | conformed.v_entity_position | reg_2052a (13 data tables + comments) | 733 | 486 |
| Validation & Submission | FR 2052a tables -> 6G XML | reg_2052a (13 data tables + comments) | reg_2052a.submission_files | 486 | 3 |

