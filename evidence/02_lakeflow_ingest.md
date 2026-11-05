# Lakeflow ingest - pipeline fr2052a-bronze-ingest

Captured 2026-11-05 15:44 UTC from `https://<workspace>.cloud.databricks.com` by `deploy/capture_evidence.py`.

`pipelines/bronze_ingest.py`: a Lakeflow Declarative Pipeline with Auto Loader reading the synthetic source-system extracts (CSV) from the volume `raw.landing/<source>/<date>/` into the Bronze tables `raw.*`, with expectations.

## Updates

| update id | state | full refresh | created |
|---|---|---|---|
| <uuid-2> | COMPLETED | False | 2026-11-04 20:45 UTC |
| <uuid-3> | COMPLETED | True | 2026-11-04 18:07 UTC |
| <uuid-4> | COMPLETED | False | 2026-11-03 18:55 UTC |
| <uuid-5> | COMPLETED | True | 2026-11-03 12:29 UTC |
| <uuid-6> | COMPLETED | False | 2026-11-02 13:50 UTC |
| <uuid-7> | COMPLETED | False | 2026-10-27 20:00 UTC |
| <uuid-8> | COMPLETED | True | 2026-10-26 15:50 UTC |
| <uuid-9> | COMPLETED | True | 2026-10-26 14:39 UTC |
| <uuid-10> | COMPLETED | True | 2026-10-26 14:14 UTC |
| <uuid-11> | COMPLETED | True | 2026-10-23 22:20 UTC |

## Latest completed update `<uuid-2>`: rows and expectations per flow

| flow | status | output rows | dropped | expectations |
|---|---|---|---|---|
| collateral_links | COMPLETED | 0 | 0 |  |
| comments | COMPLETED | 0 | 0 |  |
| customers | COMPLETED | 0 | 0 |  |
| deposits | COMPLETED | 0 | 0 |  |
| derivatives | COMPLETED | 0 | 0 |  |
| finance | COMPLETED | 0 | 0 |  |
| funding | COMPLETED | 0 | 0 |  |
| gl_balances | COMPLETED | 0 | 0 |  |
| loans | COMPLETED | 0 | 0 |  |
| securities | COMPLETED | 20 | 0 | amount_present: passed 20, failed 0; as_of_date_present: passed 20, failed 0; record_id_present: passed 20, failed 0; source_product_code_present: passed 20, failed 0 |

## Bronze tables (`raw.*`), reporting dates

```sql
SELECT 'deposits' AS source, as_of_date, COUNT(*) AS records, COUNT(DISTINCT _source_file) AS files FROM <catalog>.raw.deposits WHERE as_of_date >= '2026-02-23' GROUP BY ALL UNION ALL SELECT 'loans' AS source, as_of_date, COUNT(*) AS records, COUNT(DISTINCT _source_file) AS files FROM <catalog>.raw.loans WHERE as_of_date >= '2026-02-23' GROUP BY ALL UNION ALL SELECT 'securities' AS source, as_of_date, COUNT(*) AS records, COUNT(DISTINCT _source_file) AS files FROM <catalog>.raw.securities WHERE as_of_date >= '2026-02-23' GROUP BY ALL UNION ALL SELECT 'derivatives' AS source, as_of_date, COUNT(*) AS records, COUNT(DISTINCT _source_file) AS files FROM <catalog>.raw.derivatives WHERE as_of_date >= '2026-02-23' GROUP BY ALL UNION ALL SELECT 'funding' AS source, as_of_date, COUNT(*) AS records, COUNT(DISTINCT _source_file) AS files FROM <catalog>.raw.funding WHERE as_of_date >= '2026-02-23' GROUP BY ALL ORDER BY source, as_of_date
```

| source | as_of_date | records | files |
|---|---|---|---|
| deposits | 2026-02-23 | 66 | 1 |
| deposits | 2026-02-24 | 67 | 1 |
| deposits | 2026-02-25 | 68 | 1 |
| deposits | 2026-02-26 | 69 | 1 |
| deposits | 2026-02-27 | 50 | 1 |
| derivatives | 2026-02-23 | 102 | 1 |
| derivatives | 2026-02-24 | 102 | 1 |
| derivatives | 2026-02-25 | 102 | 1 |
| derivatives | 2026-02-26 | 72 | 1 |
| derivatives | 2026-02-27 | 102 | 1 |
| funding | 2026-02-23 | 44 | 1 |
| funding | 2026-02-24 | 62 | 1 |
| funding | 2026-02-25 | 62 | 1 |
| funding | 2026-02-26 | 63 | 1 |
| funding | 2026-02-27 | 63 | 1 |
| loans | 2026-02-23 | 58 | 1 |
| loans | 2026-02-24 | 58 | 1 |
| loans | 2026-02-25 | 41 | 1 |
| loans | 2026-02-26 | 58 | 1 |
| loans | 2026-02-27 | 58 | 1 |
| securities | 2026-02-23 | 67 | 1 |
| securities | 2026-02-24 | 47 | 1 |
| securities | 2026-02-25 | 67 | 1 |
| securities | 2026-02-26 | 67 | 1 |
| securities | 2026-02-27 | 67 | 1 |

