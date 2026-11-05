# Databricks App - API responses

Captured 2026-11-05 15:49 UTC from `https://<workspace>.cloud.databricks.com` by `deploy/capture_evidence.py`.

App: https://fr2052a-<workspace-id>.aws.databricksapps.com (FastAPI + React; reads Lakebase; calls Genie, the agents' serving endpoint and the jobs as its service principal).

## GET /api/dates -> 200 (0.25 s)

```json
[
 "2026-02-27",
 "2026-02-26",
 "2026-02-25",
 "2026-02-24",
 "2026-02-23"
]
```

## GET /api/wb/agents/2026-02-27/review -> 200 (1.30 s)

```json
{
 "date": "2026-02-27",
 "due": {
  "primary": "2026-03-03",
  "reduced": "2026-03-14"
 },
 "status": "review",
 "to_review": 31,
 "to_review_label": "1 feed incomplete - ask the source to re-send, 2 records, 4 proposals, 8 exceptions, 16 comments",
 "next": "Next: finish steps 1-4, then generate the 6G files in step 5.",
 "steps": [
  {
   "key": "collect",
   "n": 1,
   "title": "Collect",
   "to": "/collect",
   "agent": "Checked 10 source feeds against their 5-day median.",
   "open": 1,
   "open_label": "1 feed incomplete - ask the source to re-send",
   "detail": "deposits: 50 records vs trailing median 67",
   "done": [
    "Received 10 source feeds (10 files): 365 position records from 6 position feeds, plus 76 supporting records (customers, collateral links, GL balances, comments).",
    "1 feed short of its 5-day median: deposits."
   ],
   "state": "review"
  },
  {
   "key": "dq",
   "n": 2,
   "title": "Data quality",
   "to": "/dq",
   "agent": "Ran 12 rules on every record and proposed a fix for each record that failed.",
   "open": 2,
   "open_label": "2 records to review",
   "waiting": 0,
   "waiting_label": "0 approved fixes wait for the re-run from data quality",
   "done": [
    "Checked the 365 position records against 12 data quality rules (completeness, valid values, dates, amounts).",
    "2 records failed and was held back; the AI proposed a fix for each (0 already decided)."
   ],
   "state": "review"
  },
  {
   "key": "enrich",
   "n": 3,
   "title": "PID enrichment",
   "to": "/enrich",
   "agent": "Classified 394 of 397 positions by a PID rule and proposed the new customers and product codes.",
   "open": 4,
   "open_label": "4 proposals to review",
   "done": [
    "Split 363 source records into 397 FR 2052a positions (e.g. insured / uninsured deposits).",
    "Gave 394 of 397 positions their FR 2052a product (PID) by rule, with counterparty, G-SIB, collateral class, HQLA level and maturity bucket (maturities on holidays rolled to the next business day).",
    "Found 4 new customers / product codes and proposed how to classify each (0 decided)."
   ],
   "state": "review"
  },
  {
   "key": "validate",
   "n": 4,
   "title": "Validate",
   "to": "/validate",
   "agent": "Ran 1,084 checks and proposed a correction or an explanation for each exception (8 exceptions from 3 checks not passing).",
   "open": 24,
   "open_label": "8 exceptions, 16 comments to review",
   "waiting": 0,
   "waiting_label": "0 approved corrections wait for the re-run of the validation",
   "blocking": 0,
   "done": [
    "Ran 1,084 checks: the FR 2052a Instructions, the Fed's 6G business rules and schema, the Fed's 14 post-submission checks and the reconciliations.",
    "1,081 passed, 3 gave a warning. The AI proposed a correction or an explanation for each of the 8 records affected (0 decided).",
    "General ledger: 22 of 23 balances tie within 0.5%; FR 2052a vs LCR engine: 4 of 4 tie.",
    "Drafted 16 comments for the Fed (8 S.C comments, 8 variance commentaries) and checked each names its FR 2052a table (0 decided)."
   ],
   "state": "review"
  },
  {
   "key": "release",
   "n": 5,
   "title": "Generate 6G & release",
   "to": "/release",
   "agent": "Generated 3 6G files (all valid against the Fed XSD) ",
   "open": 0,
   "state": "waiting",
   "close_label": "Waits for steps 1-4",
   "tone": "wait",
   "done": [
    "Starts when steps 1-4 have nothing left: Collect (1 feed incomplete - ask the source to re-send); Data quality (2 records to review); PID enrichment (4 proposals to review); Validate (8 exceptions, 16 comments to review).",
    "Then: generate the 6G files, approve, and a second person marks the filing submitted."
   ]
  }
 ],
 "approvals": {
  "agents_run": true,
  "waiting": 45
 },
 "agents": {
  "headline": "The agents worked on 61 items today: 16 settled on the step pages; 45 wait for you.",
  "total": 61,
  "straight_through": 0,
  "by_checker": 0,
  "on_step_pages": 16,
  "open": 45,
  "spot_check": []
 },
 "run": {
  "number": 3,
  "status": "READY_FOR_REVIEW",
  "files": 3,
  "xsd_valid": true
 }
}
```

## GET /api/filing/2026-02-27/summary -> 200 (0.22 s)

```json
[
 {
  "section_name": "I.A Inflows-Assets",
  "direction": "Inflow",
  "record_count": 68,
  "total_amount": 187751.2773116
 },
 {
  "section_name": "I.O Inflows-Other",
  "direction": "Inflow",
  "record_count": 30,
  "total_amount": 18311.9248
 },
 {
  "section_name": "I.S Inflows-Secured",
  "direction": "Inflow",
  "record_count": 31,
  "total_amount": 41772.6316
 },
 {
  "section_name": "I.U Inflows-Unsecured",
  "direction": "Inflow",
  "record_count": 36,
  "total_amount": 70917.027455
 },
 {
  "section_name": "O.D Outflows-Deposits",
  "direction": "Outflow",
  "record_count": 80,
  "total_amount": 156229.589776
 },
 {
  "section_name": "O.O Outflows-Other",
  "direction": "Outflow",
  "record_count": 66,
  "total_amount": 97243.5716
 },
 {
  "section_name": "O.S Outflows-Secured",
  "direction": "Outflow",
  "record_count": 37,
  "total_amount": 63640.145
 },
 {
  "section_name": "O.W Outflows-Wholesale",
  "direction": "Outflow",
  "record_count": 38,
  "total_amount": 49555.8941978
 },
 {
  "section_name": "S.B Balance Sheet",
  "direction": "Supplemental",
  "record_count": 10,
  "total_amount": 49569.414
 },
 {
  "section_name": "S.DC Derivatives & Collateral",
  "direction": "Supplemental",
  "record_count": 54,
  "total_amount": 81934.4306
 },
 {
  "section_name": "S.FX Foreign Exchange",
  "direction": "Supplemental",
  "record_count": 14,
  "total_amount": 7387.57534248
 },
 {
  "section_name": "S.I Informational",
  "direction": "Supplemental",
  "record_count": 10,
  "total_amount": 40884.1302
 },
 {
  "section_name": "S.L Liquidity Risk Measurement",
  "direction": "Supplemental",
  "record_count": 12,
  "total_amount": 10293.6693
 }
]
```

## GET /api/submission/2026-02-27 -> 200 (0.32 s)

```json
{
 "run_number": 3,
 "version": 1,
 "status": "READY_FOR_REVIEW",
 "runs": [
  {
   "run_number": 3,
   "version": 1,
   "release_status": "READY_FOR_REVIEW",
   "generated": "2026-11-04T22:06:11.839518+00:00"
  },
  {
   "run_number": 2,
   "version": 1,
   "release_status": "READY_FOR_REVIEW",
   "generated": "2026-11-04T19:53:35.544176+00:00"
  },
  {
   "run_number": 1,
   "version": 1,
   "release_status": "READY_FOR_REVIEW",
   "generated": "2026-11-04T18:39:39.125827+00:00"
  }
 ],
 "files": [
  {
   "file_type": "Reduced",
   "file_name": "6G_ACME_02272026.REDUCED.xml",
   "run_number": 3,
   "version": 1,
   "reporting_frequency": "Reduced",
   "report_types": 2,
   "record_count": 13,
   "xsd_valid": true,
   "xsd_errors": 0,
   "xsd_error_sample": null,
   "br_rules_failed": 0,
   "release_status": "READY_FOR_REVIEW",
   "xml_size_bytes": 6316,
   "file_path": "/Volumes/<catalog>/reg_2052a/xml_filings/2026-02-27/run003/6G_ACME_02272026.REDUCED.xml",
   "generated_timestamp": "2026-11-04T22:06:11.839518+00:00"
  },
  {
   "file_type": "Primary",
   "file_name": "6G_ACME_02272026.xml",
   "run_number": 3,
   "version": 1,
   "reporting_frequency": "Primary",
   "report_types": 13,
   "record_count": 473,
   "xsd_valid": true,
   "xsd_errors": 0,
   "xsd_error_sample": null,
   "br_rules_failed": 0,
   "release_status": "READY_FOR_REVIEW",
   "xml_size_bytes": 299225,
   "file_path": "/Volumes/<catalog>/reg_2052a/xml_filings/2026-02-27/run003/6G_ACME_02272026.xml",
   "generated_timestamp": "2026-11-04T22:06:11.839518+00:00"
  },
  {
   "file_type": "Comment",
   "file_name": "6G_ACME_02272026.COMMENT.xml",
   "run_number": 3,
   "version": 1,
   "reporting_frequency": null,
   "report_types": 0,
   "record_count": 3,
   "xsd_valid": true,
   "xsd_errors": 0,
   "xsd_error_sample": null,
   "br_rules_failed": 0,
   "release_status": "READY_FOR_REVIEW",
   "xml_size_bytes": 1508,
   "file_path": "/Volumes/<catalog>/reg_2052a/xml_filings/2026-02-27/run003/6G_ACME_02272026.COMMENT.xml",
   "generated_timestamp": "2026-11-04T22:06:11.839518+00:00"
  }
 ],
 "released_by": null,
 "generated_at": "2026-11-04T22:14:06.364516",
 "review_log": [
  {
   "as_of_date": "2026-02-27",
   "run_number": 3,
   "version": 1,
   "action": "GENERATED",
   "status": "READY_FOR_REVIEW",
   "actor": "fr2052a pipeline",
   "note": "3 file(s); XSD valid; 0 ERROR rule failure(s); 3 warning(s)",
   "action_timestamp": "2026-11-04T22:14:06.364516"
  }
 ],
 "validation_summary": [
  {
   "rule_source": "6G BR",
   "status": "PASS",
   "rules": 652
  },
  {
   "rule_source": "6G BR General",
   "status": "PASS",
   "rules": 4
  },
  {
   "rule_source": "6G XSD",
   "status": "PASS",
   "rules": 3
  },
  {
   "rule_source": "Fed PSV",
   "status": "PASS",
   "rules": 12
  },
  {
   "rule_source": "Fed PSV",
   "status": "WARNING",
   "rules": 2
  },
  {
   "rule_source": "Instructions",
   "status": "PASS",
   "rules": 409
  },
  {
   "rule_source": "Reconciliation",
   "status": "PASS",
   "rules": 1
  },
  {
   "rule_source": "Reconciliation",
   "status": "WARNING",
   "rules": 1
  }
 ],
 "issues": [
  {
   "rule_id": "PSV-06",
   "rule_source": "Fed PSV",
   "appendix": "Data Transformation",
   "table_code": "ALL",
   "rule_name": "Symmetry of intercompany transactions",
   "rule_category": "PSV-06",
   "severity": "WARNING",
   "status": "WARNING",
   "records_failed": 1,
   "failure_details": "unsecured: ENT003 internal inflows 500.00 vs ENT002 internal outflows 0.00"
  },
  {
   "rule_id": "PSV-14",
   "rule_source": "Fed PSV",
   "appendix": "Data Transformation",
   "table_code": "ALL",
   "rule_name": "Large other product or counterparty balance",
   "rule_category": "PSV-14",
   "severity": "WARNING",
   "status": "WARNING",
   "records_failed": 6,
   "failure_details": "ENT001 I.U.8 counterparty Bank: USD 1,462 mm; ENT001 O.S.11 counterparty Non-Financial Corporate: USD 1,287 mm; ENT001 S.B.4 counterparty None: USD 6,226 mm; ENT002 I.U.8 counterparty Bank: USD 1,462 mm; ENT002 S.B.4 counterparty None: USD 6,226 mm"
  },
  {
   "rule_id": "RECON-GL",
   "rule_source": "Reconciliation",
   "appendix": null,
   "table_code": null,
   "rule_name": "General ledger vs the filing, by legal entity and table (tolerance 0.5%)",
   "rule_category": "Reconciliation",
   "severity": "WARNING",
   "status": "WARNING",
   "records_failed": 1,
   "failure_details": "GL vs LE02 O.D: GL 121,079.7 vs filing 78,837.7 USD mm (-34.89%) - GL-LE02-OD (ORACLE_GL) - tolerance 0.5%; includes 727.6 held for customer approval"
  }
 ],
 "recon": [
  {
   "name": "GL vs LE05 O.W",
   "expected": 6954.352,
   "actual": 6946.658,
   "difference_pct": -0.1106,
   "status": "PASS",
   "details": "GL-LE05-OW (ORACLE_GL) - tolerance 0.5%"
  },
  {
   "name": "GL vs LE02 O.S",
   "expected": 7106.4852,
   "actual": 7100.701,
   "difference_pct": -0.0814,
   "status": "PASS",
   "details": "GL-LE02-OS (ORACLE_GL) - tolerance 0.5%"
  },
  {
   "name": "GL vs LE02 I.A",
   "expected": 93815.015,
   "actual": 93875.6387,
   "difference_pct": 0.0646,
   "status": "PASS",
   "details": "GL-LE02-IA (ORACLE_GL) - tolerance 0.5%"
  },
  {
   "name": "GL vs LE03 I.U",
   "expected": 499.4025,
   "actual": 500.0,
   "difference_pct": 0.1196,
   "status": "PASS",
   "details": "GL-LE03-IU (ORACLE_GL) - tolerance 0.5%"
  },
  {
   "name": "GL vs LE00 O.W",
   "expected": 23288.8472,
   "actual": 23312.7736,
   "difference_pct": 0.1027,
   "status": "PASS",
   "details": "GL-LE00-OW (ORACLE_GL) - tolerance 0.5%"
  },
  {
   "name": "GL vs LE03 O.S",
   "expected": 25348.1863,
   "actual": 25319.3715,
   "difference_pct": -0.1137,
   "status": "PASS",
   "details": "GL-LE03-OS (ORACLE_GL) - tolerance 0.5%"
  },
  {
   "name": "GL vs LE02 O.W",
   "expected": 4114.2702,
   "actual": 4114.0188,
   "difference_pct": -0.0061,
   "status": "PASS",
   "details": "GL-LE02-OW (ORACLE_GL) - 
... (truncated)
```

## GET /api/wb/validate/2026-02-27/queue -> 200 (0.24 s)

```json
[
 {
  "rule_id": "PSV-06",
  "rule_name": "Symmetry of intercompany transactions",
  "rule_source": "Fed PSV",
  "severity": "WARNING",
  "status": "WARNING",
  "table_code": "ALL",
  "product_id": null,
  "record_key": null,
  "position_id": null,
  "item_key": "ALL|None|unsecured: ENT003 internal inflows 500.00 vs ENT002 internal outflows 0.00",
  "detail": "unsecured: ENT003 internal inflows 500.00 vs ENT002 internal outflows 0.00",
  "state": "open",
  "decision": null
 },
 {
  "rule_id": "PSV-14",
  "rule_name": "Large other product or counterparty balance",
  "rule_source": "Fed PSV",
  "severity": "WARNING",
  "status": "WARNING",
  "table_code": "I.U",
  "product_id": "I.U.8",
  "record_key": null,
  "position_id": null,
  "item_key": "I.U|I.U.8|ENT001 I.U.8 counterparty Bank: USD 1,462 mm",
  "detail": "ENT001 I.U.8 counterparty Bank: USD 1,462 mm",
  "state": "open",
  "decision": null
 },
 {
  "rule_id": "PSV-14",
  "rule_name": "Large other product or counterparty balance",
  "rule_source": "Fed PSV",
  "severity": "WARNING",
  "status": "WARNING",
  "table_code": "I.U",
  "product_id": "I.U.8",
  "record_key": null,
  "position_id": null,
  "item_key": "I.U|I.U.8|ENT002 I.U.8 counterparty Bank: USD 1,462 mm",
  "detail": "ENT002 I.U.8 counterparty Bank: USD 1,462 mm",
  "state": "open",
  "decision": null
 },
 {
  "rule_id": "PSV-14",
  "rule_name": "Large other product or counterparty balance",
  "rule_source": "Fed PSV",
  "severity": "WARNING",
  "status": "WARNING",
  "table_code": "O.S",
  "product_id": "O.S.11",
  "record_key": null,
  "position_id": null,
  "item_key": "O.S|O.S.11|ENT001 O.S.11 counterparty Non-Financial Corporate: USD 1,287 mm",
  "detail": "ENT001 O.S.11 counterparty Non-Financial Corporate: USD 1,287 mm",
  "state": "open",
  "decision": null
 },
 {
  "rule_id": "PSV-14",
  "rule_name": "Large other product or counterparty balance",
  "rule_source": "Fed PSV",
  "severity": "WARNING",
  "status": "WARNING",
  "table_code": "O.S",
  "product_id": "O.S.11",
  "record_key": null,
  "position_id": null,
  "item_key": "O.S|O.S.11|ENT003 O.S.11 counterparty Non-Financial Corporate: USD 1,287 mm",
  "detail": "ENT003 O.S.11 counterparty Non-Financial Corporate: USD 1,287 mm",
  "state": "open",
  "decision": null
 },
 {
  "rule_id": "PSV-14",
  "rule_name": "Large other product or counterparty balance",
  "rule_source": "Fed PSV",
  "severity": "WARNING",
  "status": "WARNING",
  "table_code": "S.B",
  "product_id": "S.B.4",
  "record_key": null,
  "position_id": null,
  "item_key": "S.B|S.B.4|ENT001 S.B.4 counterparty None: USD 6,226 mm",
  "detail": "ENT001 S.B.4 counterparty None: USD 6,226 mm",
  "state": "open",
  "decision": null
 },
 {
  "rule_id": "PSV-14",
  "rule_name": "Large other product or counterparty balance",
  "rule_source": "Fed PSV",
  "severity": "WARNING",
  "status": "WARNING",
  "table_code": "S.B",
  "product_id": "S.B.4",
  "record_key": null,
  "position_id": null,
  "item_key": "S.B|S.B.4|ENT002 S.B.4 counterparty None: USD 6,226 mm",
  "detail": "ENT002 S.B.4 counterparty None: USD 6,226 mm",
  "state": "open",
  "decision": null
 },
 {
  "rule_id": "RECON-GL",
  "rule_name": "General ledger vs the filing, by legal entity and table (tolerance 0.5%)",
  "rule_source": "Reconciliation",
  "severity": "WARNING",
  "status": "WARNING",
  "table_code": "O.D",
  "product_id": null,
  "record_key": null,
  "position_id": null,
  "item_key": "O.D|None|GL vs LE02 O.D: GL 121,079.7 vs filing 78,837.7 USD mm (-34.89%) - GL-LE02-OD (O",
  "detail": "GL vs LE02 O.D: GL 121,079.7 vs filing 78,837.7 USD mm (-34.89%) - GL-LE02-OD (ORACLE_GL) - tolerance 0.5%; includes 727.6 held for customer approval",
  "state": "open",
  "decision": null
 }
]
```

## GET /api/wb/agents/accuracy -> 200 (2.30 s)

```json
{
 "agents": [
  {
   "agent": "Classifier",
   "proposals": 105,
   "approved": 0,
   "edited": 0,
   "returned": 0,
   "straight_through": 11,
   "spot_confirmed": 0,
   "spot_disagreed": 0,
   "acceptance": null,
   "edit_rate": null,
   "spot_agreement": null
  },
  {
   "agent": "Tie-out agent",
   "proposals": 17,
   "approved": 0,
   "edited": 0,
   "returned": 0,
   "straight_through": 4,
   "spot_confirmed": 0,
   "spot_disagreed": 0,
   "acceptance": null,
   "edit_rate": null,
   "spot_agreement": null
  },
  {
   "agent": "Feed monitor",
   "proposals": 5,
   "approved": 0,
   "edited": 0,
   "returned": 0,
   "straight_through": 0,
   "spot_confirmed": 0,
   "spot_disagreed": 0,
   "acceptance": null,
   "edit_rate": null,
   "spot_agreement": null
  }
 ],
 "evaluation": [
  {
   "metric": "cites_regulation.mean",
   "value": 0.9514563106796117,
   "n": 103,
   "eval_run": "20261104-192611"
  },
  {
   "metric": "grounded_in_evidence.mean",
   "value": 0.9029126213592233,
   "n": 103,
   "eval_run": "20261104-192611"
  },
  {
   "metric": "rule_agent_agrees.mean",
   "value": 0.9029126213592233,
   "n": 103,
   "eval_run": "20261104-192611"
  }
 ],
 "model": "fr2052a_agents v10"
}
```

## GET /api/wb/agents/learning -> 200 (0.24 s)

```json
[
 {
  "kind": "Explained exception",
  "pattern": "RECON-GL is explained as correct on several days",
  "days": [
   "2026-02-24",
   "2026-02-26"
  ],
  "count": 4,
  "proposal": "Recalibrate RECON-GL (threshold / scope) or record a standing explanation, so the same exception does not come back daily",
  "owner": "Regulatory reporting (rule owner)"
 },
 {
  "kind": "Explained exception",
  "pattern": "PSV-06 Symmetry of intercompany transactions is explained as correct on several days",
  "days": [
   "2026-02-23",
   "2026-02-25"
  ],
  "count": 3,
  "proposal": "Recalibrate PSV-06 (threshold / scope) or record a standing explanation, so the same exception does not come back daily",
  "owner": "Regulatory reporting (rule owner)"
 },
 {
  "kind": "Explained exception",
  "pattern": "SPEC-V-07 is explained as correct on several days",
  "days": [
   "2026-02-23",
   "2026-02-26"
  ],
  "count": 2,
  "proposal": "Recalibrate SPEC-V-07 (threshold / scope) or record a standing explanation, so the same exception does not come back daily",
  "owner": "Regulatory reporting (rule owner)"
 },
 {
  "kind": "Explained exception",
  "pattern": "SPEC-V-08 is explained as correct on several days",
  "days": [
   "2026-02-23",
   "2026-02-26"
  ],
  "count": 2,
  "proposal": "Recalibrate SPEC-V-08 (threshold / scope) or record a standing explanation, so the same exception does not come back daily",
  "owner": "Regulatory reporting (rule owner)"
 },
 {
  "kind": "Explained exception",
  "pattern": "SPEC-V-09 is explained as correct on several days",
  "days": [
   "2026-02-23",
   "2026-02-26"
  ],
  "count": 2,
  "proposal": "Recalibrate SPEC-V-09 (threshold / scope) or record a standing explanation, so the same exception does not come back daily",
  "owner": "Regulatory reporting (rule owner)"
 }
]
```

## GET /api/wb/agents/2026-02-24/release-memo -> 200 (0.29 s)

```json
{
 "run_number": 4,
 "memo": "**FR 2052a Release Memo \u2014 As-of Date 2026-02-24 | Run 4**\n*Status: BLOCKED \u2014 awaiting approver action*\n\n---\n\n**1. What is released**\n- Run 4, as-of date 2026-02-24\n- Primary file: 468 records, XSD valid\n- Comment file: 2 records, XSD valid\n\n---\n\n**2. What changed since 2026-02-23**\n- ENT001 LCR fell from 1.4772 to 0.7369; HQLA down 33,728.6 from 51,066.1; net cash outflows up to 45,769.0 from 34,568.9\n- ENT002 LCR fell from 1.7614 to 1.0706; HQLA down to 30,477.7 from 47,839.3; net cash outflows 28,468.4 vs 27,160.2\n- Largest movers: I.A dropped 60,573.2 (records fell 68\u219258); O.S up 18,576.8 (records 25\u219237); O.W up 14,995.6 (records 28\u219238); O.D up 6,410.7\n\n---\n\n**3. How open items were settled**\n- 17 agent items total: 1 settled straight through (confidence \u2265 95%, rule agent agreed, no material LCR effect) \u2014 spot-check flagged: BRK-0224-016, GL vs LE02 I.A, GL 95,009.3 vs filing 64,679.8 (\u221231.92%)\n- 16 items remain open; 0 resolved by checker, 0 on step pages\n- 1 explained exception; 0 corrections; 0 DQ fixes\n\n---\n\n**4. Overrides and points for the approver**\n- None\n- **Note:** 16 agent items are still open and the run is BLOCKED \u2014 approver action required before release",
 "facts": {
  "lcr": [
   {
    "lcr": "1.4772",
    "nco": "34568.9",
    "hqla": "51066.1",
    "entity_id": "ENT001",
    "as_of_date": "2026-02-23"
   },
   {
    "lcr": "0.7369",
    "nco": "45769.0",
    "hqla": "33728.6",
    "entity_id": "ENT001",
    "as_of_date": "2026-02-24"
   },
   {
    "lcr": "1.7614",
    "nco": "27160.2",
    "hqla": "47839.3",
    "entity_id": "ENT002",
    "as_of_date": "2026-02-23"
   },
   {
    "lcr": "1.0706",
    "nco": "28468.4",
    "hqla": "30477.7",
    "entity_id": "ENT002",
    "as_of_date": "2026-02-24"
   }
  ],
  "agents": {
   "open": 16,
   "total": 17,
   "headline": "The agents worked on 17 items today: 1 applied straight through (1 to spot-check); 16 wait for you.",
   "by_checker": 0,
   "spot_check": [
    {
     "title": "RECON-GL General ledger vs the filing, by legal entity and table (tolerance 0.5%): GL vs LE02 I.A: GL 95,009.3 vs filing 64,679.8 USD mm (-31.92%) - GL-LE02-IA (ORACLE_GL) - tolerance 0.5%",
     "break_id": "BRK-0224-016",
     "break_type": "GL tie-out"
    }
   ],
   "on_step_pages": 0,
   "straight_through": 1
  },
  "tables": [
   {
    "records": 68,
    "amount_usd": "189932.9",
    "as_of_date": "2026-02-23",
    "table_code": "I.A"
   },
   {
    "records": 58,
    "amount_usd": "129359.7",
    "as_of_date": "2026-02-24",
    "table_code": "I.A"
   },
   {
    "records": 30,
    "amount_usd": "18559.3",
    "as_of_date": "2026-02-23",
    "table_code": "I.O"
   },
   {
    "records": 30,
    "amount_usd": "18514.2",
    "as_of_date": "2026-02-24",
    "table_code": "I.O"
   },
   {
    "records": 31,
    "amount_usd": "40743.6",
    "as_of_date": "2026-02-23",
    "table_code": "I.S"
   },
   {
    "records": 31,
    "amount_usd": "40939.5",
    "as_of_date": "2026-02-24",
    "table_code": "I.S"
   },
   {
    "records": 36,
    "amount_usd": "71457.2",
    "as_of_date": "2026-02-23",
    "table_code": "I.U"
   },
   {
    "records": 36,
    "amount_usd": "71580.6",
    "as_of_date": "2026-02-24",
    "table_code": "I.U"
   },
   {
    "records": 85,
    "amount_usd": "238288.2",
    "as_of_date": "2026-02-23",
    "table_code": "O.D"
   },
   {
    "records": 85,
    "amount_usd": "244698.9",
    "as_of_date": "2026-02-24",
    "table_code": "O.D"
   },
   {
    "records": 66,
    "amount_usd": "95153.0",
    "as_of_date": "2026-02-23",
    "table_code": "O.O"
   },
   {
    "records": 66,
    "amount_usd": "95651.8",
    "as_of_date": "2026-02-24",
    "table_code": "O.O"
   },
   {
    "records": 25,
    "amount_usd": "44309.7",
    "as_of_date": "2026-02-23",
    "table_code": "O.S"
   },
   {
    "records": 37,
    "amount_usd": "62886.5",
    "as_of_date": "2026-02-24",
    "table_code": "O.S"
   },
   {
    "records": 28,
    "amount_usd": "35527.1",
    "as_of_date": "2026-02-23",
    "table_code": "O.W"
   },
   {
    "records": 38,
    "amount_usd": "50522.7",
    "as_of_date": "2026-02-24",
    "table_code": "O.W"
   },
   {
    "records": 2,
    "amount_usd": "-2455.1",
    "as_of_date": "2026-02-23",
    "table_code": "S.B"
   },
   {
    "records": 2,
    "amount_usd": "-2456.6",
    "as_of_date": "2026-02-24",
    "table_code": "S.B"
   },
   {
    "records": 54,
    "amount_usd": "80804.7",
    "as_of_date": "2026-02-23",
    "table_code": "S.DC"
   },
   {
    "records": 54,
    "amount_usd": "80852.6",
    "as_of_date": "2026-02-24",
    "table_code": "S.DC"
   },
   {
    "records": 14,
    "amount_usd": "7282.9",
    "as_of_date": "2026-02-23",
    "table_code": "S.FX"
   },
   {
    "records": 14,
    "amount_usd": "7287.3",
    "as_of_date": "2026-02-24",
    "table_code": "S.FX"
   },
   {
    "records": 10,
    "amount_usd": "40304.8",
    "as_of_date": "2026-02-23",
    "table_code": "S.I"
   },
   {
    "records": 10,
    "amount_usd": "40329.4",
    "as_of_date": "2026-02-24",
    "table_code": "S.I"
   },
   {
    "records": 7,
    "amount_usd": "5343.1",
    "as_of_date": "2026-02-23",
    "table_code": "S.L"
   },
   {
    "records": 7,
    "amount_usd": "5344.9",
    "as_of_date": "2026-02-24",
    "table_code": "S.L"
   }
  ],
  "release": {
   "run": 4,
   "files": [
    {
     "type": "Primary",
     "records": 468,
     "xsd_valid": true
    },
    {
     "type": "Comment",
     "records": 2,
     "xsd_valid": true
    }
   ],
   "status": "BLOCKED",
   "released_by": null
  },
  "dq_fixes": 0,
  "decisions": [
   {
    "note": "Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect",
    "title": "RECON-GL General ledger vs the filing, by legal entity and table (tolerance 0.5%): GL vs LE02 I.A: GL 95,009.3 vs filing 64,679.8 USD mm (-31.92%) - GL-LE02-IA (ORACLE_GL) - to
... (truncated)
```

## GET /api/wb/lcr/2026-02-27/explain?entity=ENT001 -> 200 (0.21 s)

```json
{
 "entity": "ENT001",
 "date": "2026-02-27",
 "prior_date": "2026-02-26",
 "lcr_prior": 1.3738,
 "lcr_today": 1.3469,
 "attribution": [
  {
   "driver": "HQLA",
   "prior": 51000.7985,
   "today": 50622.0584,
   "change": -378.74009999999544,
   "lcr_effect": -0.01020228023408194
  },
  {
   "driver": "Retail deposits",
   "prior": 4430.784,
   "today": 3055.0239,
   "change": -1375.7600999999995,
   "lcr_effect": 0.04991623912283789
  },
  {
   "driver": "Wholesale unsecured funding",
   "prior": 33798.1071,
   "today": 27464.2434,
   "change": -6333.863700000002,
   "lcr_effect": 0.22980943772149148
  },
  {
   "driver": "Secured funding",
   "prior": 4767.1945,
   "today": 4827.8464,
   "change": 60.65190000000075,
   "lcr_effect": -0.00220061240593799
  },
  {
   "driver": "Derivatives",
   "prior": 1725.2257,
   "today": 3828.7002,
   "change": 2103.4745000000003,
   "lcr_effect": -0.07631965495349945
  },
  {
   "driver": "Commitments",
   "prior": 3599.9211,
   "today": 6163.655,
   "change": 2563.7338999999997,
   "lcr_effect": -0.09301909133701856
  },
  {
   "driver": "Other outflows",
   "prior": 2635.5252,
   "today": 5910.1798,
   "change": 3274.6546,
   "lcr_effect": -0.11881318702170611
  },
  {
   "driver": "Inflows counted",
   "prior": 14061.2917,
   "today": 14168.6879,
   "change": 107.39620000000104,
   "lcr_effect": 0.0038966200575842953
  },
  {
   "driver": "Maturity mismatch add-on",
   "prior": 227.6175,
   "today": 502.4865,
   "change": 274.86899999999997,
   "lcr_effect": -0.009972979105481639
  }
 ],
 "movers": [
  {
   "rule_id": "LCR-O54",
   "rule_name": "Downgrade - 3 notches (cumulative)",
   "flow_direction": "OUTFLOW",
   "change": 3263.421
  },
  {
   "rule_id": "LCR-O14",
   "rule_name": "Non-operational wholesale - financial",
   "flow_direction": "OUTFLOW",
   "change": -2296.2824
  },
  {
   "rule_id": "LCR-O53",
   "rule_name": "Derivative valuation changes",
   "flow_direction": "OUTFLOW",
   "change": 2105.4329
  },
  {
   "rule_id": "LCR-O13",
   "rule_name": "Non-operational wholesale - non-financial",
   "flow_direction": "OUTFLOW",
   "change": -1807.6733
  },
  {
   "rule_id": "LCR-O11",
   "rule_name": "Operational deposits",
   "flow_direction": "OUTFLOW",
   "change": -1805.3203
  },
  {
   "rule_id": "LCR-O47",
   "rule_name": "Facilities - debt issuing SPEs",
   "flow_direction": "OUTFLOW",
   "change": 1584.2843
  }
 ],
 "headline": "",
 "explanation": "AI explanation not available ('NoneType' object has no attribute 'group')",
 "generated_by": "ai_query (databricks-claude-sonnet-4-6) over the attribution computed from reg_lcr.calculation_results"
}
```

