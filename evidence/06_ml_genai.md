# ML / Gen AI - the AI agents (maker) with the person as checker

Captured 2026-11-05 18:14 UTC from `https://<workspace>.cloud.databricks.com` by `deploy/capture_evidence.py`.

The agents are an MLflow pyfunc model registered in Unity Catalog; notebook 15 runs its `@champion` in the pipeline for every open item, the app's "Run the agent again" calls it on a Model Serving endpoint. Each proposal is an MLflow trace in Unity Catalog; the checker's decision is logged on it as human feedback; notebook 10 evaluates the champion with `mlflow.genai.evaluate`.

## Registered model `<catalog>.ai_assist.fr2052a_agents`

champion = version 10

| version | status | created | source |
|---|---|---|---|
| 3 | READY | 2026-10-30 19:52 UTC | models:/m-70a3dba0b1294fd2847d18f87d88ebca |
| 4 | READY | 2026-11-02 17:17 UTC | models:/m-87160d03bf52453280f2e535a8070622 |
| 6 | READY | 2026-11-02 19:58 UTC | models:/m-256db669b2ce4d7daec286787d2258d3 |
| 7 | READY | 2026-11-02 20:15 UTC | models:/m-7645c8b1943e4d5998cadf0e3694e657 |
| 8 | READY | 2026-11-03 14:37 UTC | models:/m-c757bd0f066d4eb1bad859329b722310 |
| 9 | READY | 2026-11-03 23:10 UTC | models:/m-e8278984a24845e2b2e2406e27aaf236 |
| 10 | READY | 2026-11-04 14:25 UTC | models:/m-8cc4ba7d3bd44e738b16ff089bdcd2b7 |
| 11 | READY | 2026-11-05 14:15 UTC | models:/m-7803f8e17570406ba51283ff060d97e4 |

## Serving endpoint `fr2052a-agents`

| state | served entity | version | workload | scale to zero |
|---|---|---|---|---|
| {"ready": "READY", "config_update": "NOT_UPDATING", "suspend": "NOT_SUSPENDED", "system_update_failure": false} | <catalog>.ai_assist.fr2052a_agents | 10 | Small | True |

## A live prediction from the endpoint (130.7 s; nothing stored)

Input:

```json
{
 "dataframe_records": [
  {
   "kind": "validation",
   "as_of_date": "2026-02-26",
   "item_json": "{\"rule_id\": \"SPEC-V-06\", \"rule_name\": \"Unsecured derivative cash flows over the next 30 days are in I.O.1 / O.O.1 and in the I.O.7 / O.O.20 net\", \"rule_source\": \"Instructions\", \"severity\": \"ERROR\", \"status\": \"FAIL\", \"table_code\": \"ALL\", \"product_id\": \"I.O.7/O.O.20\", \"record_key\": null, \"position_id\": null, \"item_key\": \"ALL|I.O.7/O.O.20|net 30-day derivative -208.45 vs flows -602.72\", \"detail\": \"net 30-day derivative -208.45 vs flows -602.72\", \"state\": \"open\", \"decision\": null}"
  }
 ]
}
```

Output (the agents' proposal):

```json
{
 "break_type": "Validation failure",
 "agent": "Classifier",
 "confidence": 0.85,
 "summary": "No editable position fields are available in the record set provided, so no single field correction can be made programmatically. The discrepancy of 394.27 between the I.O.7/O.O.20 net (-208.45) and the I.O.1/O.O.1 gross flows (-602.72) must be resolved by reviewing the source trade population and aggregation logic to ensure all unsecured derivative cash flows within the 30-day window present in I.O.1/O.O.1 are fully and correctly reflected in the I.O.7/O.O.20 netting schedule, then resubmitting once the populations are reconciled.",
 "fields": [
  {
   "field": "explanation",
   "now": "net 30-day derivative -208.45 vs flows -602.72",
   "proposed": "No editable position fields are available in the record set provided, so no single field correction can be made programmatically. The discrepancy of 394.27 between the I.O.7/O.O.20 net (-208.45) and the I.O.1/O.O.1 gross flows (-602.72) must be resolved by reviewing the source trade population and aggregation logic to ensure all unsecured derivative cash flows within the 30-day window present in I.O.1/O.O.1 are fully and correctly reflected in the I.O.7/O.O.20 netting schedule, then resubmitting once the populations are reconciled.",
   "cites": [
    1,
    2
   ]
  }
 ],
 "rule_check": {
  "status": "n/a",
  "detail": "An explanation - nothing to re-check"
 },
 "impact": {
  "priced": false,
  "basis": "No change to the data - no LCR effect"
 },
 "sources": [
  {
   "n": 1,
   "title": "SPEC-V-06 - Unsecured derivative cash flows over the next 30 days are in I.O.1 / O.O.1 and in the I.O.7 / O.O.20 net",
   "system": "Instructions",
   "ref": "SPEC-V-06",
   "passage": "Unsecured derivative cash flows over the next 30 days are in I.O.1 / O.O.1 and in the I.O.7 / O.O.20 net"
  },
  {
   "n": 2,
   "title": "The exception",
   "system": "reg_2052a.gold_validation_detail",
   "ref": "ALL|I.O.7/O.O.20|net 30-day derivative -208.45 vs flows -602.72",
   "passage": "net 30-day derivative -208.45 vs flows -602.72"
  },
  {
   "n": 3,
   "title": "FR 2052a Instructions - O.O.20 Net 30-Day Derivative Payables",
   "system": "FR 2052a Instructions, page 62.0 - closest passage (Vector Search)",
   "ref": "INS-O.O.20",
   "passage": "O.O.20: Net 30-Day Derivative Payables Refers to the net derivative cash outflow amount, as set forth in the LRM Standards."
  },
  {
   "n": 4,
   "title": "FR 2052a Instructions - I.O.7 Net 30-Day Derivative Receivables",
   "system": "FR 2052a Instructions, page 42.0 - closest passage (Vector Search)",
   "ref": "INS-I.O.7",
   "passage": "I.O.7: Net 30-Day Derivative Receivables Refers to the net derivative cash inflow amount, as set forth in the LRM Standards. FR 2052a Instructions Page 43 of 105"
  }
 ],
 "trace": [
  {
   "agent": "Classifier",
   "step": "read the exception",
   "detail": "SPEC-V-06 Unsecured derivative cash flows over the next 30 days are in I.O.1 / O.O.1 and in the I.O.7 / O.O.20 net: net 30-day derivative -208.45 vs flows -602.72",
   "status": "ok",
   "seconds": 0.0
  },
  {
   "agent": "Classifier",
   "step": "proposed",
   "detail": "explain   ->  (confidence 0.85)",
   "status": "ok",
   "seconds": 3.6
  },
  {
   "agent": "Rule agent",
   "step": "checked independently",
   "detail": "An explanation - nothing to re-check",
   "status": "ok",
   "seconds": 0.0
  },
  {
   "agent": "Liquidity impact agent",
   "step": "priced",
   "detail": "No change to the data - no LCR effect",
   "status": "ok",
   "seconds": 0.0
  },
  {
   "agent": "Classifier",
   "step": "read the regulation",
   "detail": "0 product definition(s) I.O.7/O.O.20; 2 closest passage(s) by Vector Search",
   "status": "ok",
   "seconds": 2.4
  }
 ],
 "source_fix": {
  "owner": "Source system owner",
  "due": "2026-03-05",
  "text": "No source fix - the data is correct; the explanation is kept with the filing."
 }
}
```

## MLflow traces in Unity Catalog, by date and model version

```sql
SELECT tags['fr2052a.as_of_date'] AS as_of_date, tags['fr2052a.agents_model_version'] AS model_version, tags['fr2052a.source_kind'] AS kind, COUNT(*) AS traces, MIN(request_time) AS first, MAX(request_time) AS last FROM <catalog>.ai_assist.`<experiment-id>_trace_unified` GROUP BY ALL ORDER BY 1, 2
```

| as_of_date | model_version | kind | traces | first | last |
|---|---|---|---|---|---|
|  |  |  | 369 | 2026-10-30T19:27:14.486Z | 2026-11-04T19:27:56.463Z |
| 2026-02-23 | 10 | validate | 29 | 2026-11-04T14:26:55.021Z | 2026-11-04T22:22:12.327Z |
| 2026-02-23 | 10 | feed | 2 | 2026-11-04T20:14:31.345Z | 2026-11-04T22:20:59.977Z |
| 2026-02-23 | 10 | dq | 2 | 2026-11-04T20:14:31.380Z | 2026-11-04T22:21:00.012Z |
| 2026-02-23 | 4 | validate | 4 | 2026-11-02T17:55:19.216Z | 2026-11-02T17:55:40.857Z |
| 2026-02-23 | 6 | validate | 1 | 2026-11-02T20:09:45.337Z | 2026-11-02T20:09:45.337Z |
| 2026-02-23 | 7 | validate | 13 | 2026-11-03T14:32:35.288Z | 2026-11-03T14:33:27.041Z |
| 2026-02-23 | 7 | feed | 1 | 2026-11-03T14:32:15.986Z | 2026-11-03T14:32:15.986Z |
| 2026-02-23 | 7 | dq | 2 | 2026-11-03T14:32:16.034Z | 2026-11-03T14:32:26.913Z |
| 2026-02-23 | 8 | validate | 13 | 2026-11-03T20:35:01.324Z | 2026-11-03T20:35:44.308Z |
| 2026-02-23 | 8 | dq | 2 | 2026-11-03T20:34:42.538Z | 2026-11-03T20:34:53.837Z |
| 2026-02-23 | 8 | feed | 1 | 2026-11-03T20:34:42.488Z | 2026-11-03T20:34:42.488Z |
| 2026-02-24 | 10 | dq | 2 | 2026-11-04T20:19:30.937Z | 2026-11-04T22:27:41.074Z |
| 2026-02-24 | 10 | validate | 39 | 2026-11-04T14:26:55.584Z | 2026-11-04T22:28:45.601Z |
| 2026-02-24 | 10 | feed | 2 | 2026-11-04T20:19:30.901Z | 2026-11-04T22:27:41.027Z |
| 2026-02-24 | 7 | validate | 6 | 2026-11-03T14:37:56.183Z | 2026-11-03T14:38:46.412Z |
| 2026-02-24 | 7 | dq | 2 | 2026-11-03T14:37:34.229Z | 2026-11-03T14:37:44.500Z |
| 2026-02-24 | 7 | feed | 1 | 2026-11-03T14:37:34.175Z | 2026-11-03T14:37:34.175Z |
| 2026-02-24 | 8 | feed | 1 | 2026-11-03T20:17:46.515Z | 2026-11-03T20:17:46.515Z |
| 2026-02-24 | 8 | validate | 6 | 2026-11-03T20:17:56.800Z | 2026-11-03T20:18:18.909Z |
| 2026-02-24 | 8 | dq | 1 | 2026-11-03T20:17:46.559Z | 2026-11-03T20:17:46.559Z |
| 2026-02-25 |  | validate | 1 | 2026-10-30T19:24:52.499Z | 2026-10-30T19:24:52.499Z |
| 2026-02-25 | 10 | validate | 18 | 2026-11-04T20:31:16.670Z | 2026-11-04T22:44:24.186Z |
| 2026-02-25 | 10 | feed | 2 | 2026-11-04T20:30:51.122Z | 2026-11-04T22:43:37.557Z |
| 2026-02-25 | 10 | ai | 3 | 2026-11-04T19:09:14.626Z | 2026-11-04T22:43:54.998Z |
| 2026-02-25 | 10 | dq | 4 | 2026-11-04T20:30:51.164Z | 2026-11-04T22:43:46.613Z |
| 2026-02-25 | 7 | validate | 9 | 2026-11-03T14:22:13.606Z | 2026-11-03T14:22:44.284Z |
| 2026-02-25 | 7 | dq | 3 | 2026-11-03T14:21:25.543Z | 2026-11-03T14:22:00.164Z |
| 2026-02-25 | 7 | feed | 1 | 2026-11-03T14:21:25.483Z | 2026-11-03T14:21:25.483Z |
| 2026-02-25 | 8 | validate | 9 | 2026-11-03T20:13:15.035Z | 2026-11-03T20:13:45.140Z |
| 2026-02-25 | 8 | feed | 1 | 2026-11-03T20:12:32.857Z | 2026-11-03T20:12:32.857Z |
| 2026-02-25 | 8 | dq | 3 | 2026-11-03T20:12:32.900Z | 2026-11-03T20:13:03.478Z |
| 2026-02-26 | 10 | validate | 36 | 2026-11-04T14:26:56.492Z | 2026-11-05T15:46:41.481Z |
| 2026-02-26 | 10 | dq | 4 | 2026-11-04T20:24:57.308Z | 2026-11-04T22:38:12.524Z |
| 2026-02-26 | 10 | feed | 2 | 2026-11-04T20:24:57.258Z | 2026-11-04T22:38:03.670Z |
| 2026-02-26 | 10 | ai | 3 | 2026-11-04T19:14:54.974Z | 2026-11-04T22:38:21.682Z |
| 2026-02-26 | 7 | validate | 16 | 2026-11-02T23:32:26.611Z | 2026-11-03T14:28:09.223Z |
| 2026-02-26 | 7 | dq | 3 | 2026-11-03T14:26:30.849Z | 2026-11-03T14:26:52.751Z |
| 2026-02-26 | 7 | feed | 1 | 2026-11-03T14:26:30.808Z | 2026-11-03T14:26:30.808Z |
| 2026-02-26 | 7 | ai | 2 | 2026-11-03T14:27:03.207Z | 2026-11-03T14:27:08.714Z |
| 2026-02-26 | 8 | validate | 16 | 2026-11-03T20:24:20.324Z | 2026-11-03T21:58:50.914Z |
| 2026-02-26 | 8 | ai | 2 | 2026-11-03T20:24:10.159Z | 2026-11-03T20:24:15.405Z |
| 2026-02-26 | 8 | dq | 3 | 2026-11-03T20:23:41.322Z | 2026-11-03T20:24:00.741Z |
| 2026-02-26 | 8 | feed | 1 | 2026-11-03T20:23:41.284Z | 2026-11-03T20:23:41.284Z |
| 2026-02-27 | 10 | ai | 86 | 2026-11-04T14:26:52.016Z | 2026-11-05T14:26:33.798Z |
| 2026-02-27 | 10 | validate | 20 | 2026-11-04T14:44:11.137Z | 2026-11-04T23:06:02.061Z |
| 2026-02-27 | 10 | dq | 4 | 2026-11-04T20:08:40.220Z | 2026-11-04T22:33:09.884Z |
| 2026-02-27 | 10 | feed | 2 | 2026-11-04T20:08:40.168Z | 2026-11-04T22:33:01.195Z |
| 2026-02-27 | 3 | ai | 10 | 2026-11-02T14:31:23.975Z | 2026-11-02T14:31:31.014Z |
| 2026-02-27 | 7 | validate | 2 | 2026-11-02T20:31:18.012Z | 2026-11-02T23:22:12.512Z |
| 2026-02-27 | 8 | ai | 20 | 2026-11-03T14:43:31.566Z | 2026-11-03T20:30:14.224Z |
| 2026-02-27 | 8 | validate | 16 | 2026-11-03T14:43:40.064Z | 2026-11-03T20:30:03.652Z |
| 2026-02-27 | 8 | dq | 6 | 2026-11-03T14:42:59.004Z | 2026-11-03T20:29:17.455Z |
| 2026-02-27 | 8 | feed | 2 | 2026-11-03T14:42:58.954Z | 2026-11-03T20:28:59.852Z |
| 2026-02-27 | 9 | validate | 1 | 2026-11-04T14:17:20.890Z | 2026-11-04T14:17:20.890Z |

## The checker's decisions as human feedback on the traces

```sql
SELECT trace_id, tags['fr2052a.as_of_date'] AS as_of_date, tags['fr2052a.agents_model_version'] AS model_version, a.assessment_name, a.feedback.value AS value, a.source.source_type, a.source.source_id, a.rationale FROM <catalog>.ai_assist.`<experiment-id>_trace_unified` LATERAL VIEW explode(assessments) x AS a WHERE a.assessment_name = 'checker_decision' ORDER BY a.create_time
```

| trace_id | as_of_date | model_version | assessment_name | value | source_type | source_id | rationale |
|---|---|---|---|---|---|---|---|
| ac723bb33cdb720ca7d75333349975a4 | 2026-02-23 | 4 | checker_decision | approved | HUMAN | user1@example.com | RC-05 Feedback-loop test: large I.U.8 balance with a bank is explained - the data is right |
| c0bf3987ae6ce904e2b366bff13a469f | 2026-02-23 | 6 | checker_decision | approved | HUMAN | user1@example.com | RC-05 Feedback-loop test: re-checked; the data is right |
| 2e05eaf75bc564083f69da114a753646 | 2026-02-23 | 4 | checker_decision | returned | HUMAN | user1@example.com | RT-04 Feedback-loop test: re-check the PSV-14 threshold against the Instructions |
| ffc5a90c35dc4187d3ca1937706fba4d | 2026-02-25 | 7 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 04f7387769f76314e29d4a23ea73c2a4 | 2026-02-25 | 7 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 9e618a34fbb17e36213460a68be24958 | 2026-02-26 | 7 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 52636b9d42aeb09500033502baac8773 | 2026-02-26 | 7 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 68a0d35d7a36f69896f2ce832f9acd62 | 2026-02-26 | 7 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 5ce1ff00134670ef72ab59ae7e1131f5 | 2026-02-26 | 7 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 3323989cbeb768b3b8133d536cd52942 | 2026-02-26 | 7 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 99333fbeabfcbfbdec380d6b45f310cd | 2026-02-26 | 7 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| f867c6d85c568079c3b2d2adff32f695 | 2026-02-26 | 7 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| a65f38070f9cebc0d3684a9eac167e6a | 2026-02-23 | 7 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| db1a5236a7f993f0695497ccd51b24a0 | 2026-02-23 | 7 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 53b313001708e825b52d07e240d10b4a | 2026-02-23 | 7 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| ead8838937f2758547e9cc00713e18e7 | 2026-02-23 | 7 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 3436585a276e709952ad40e1ae6f93cc | 2026-02-23 | 7 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 3433abf9d329109fe22ddb256c5e83b5 | 2026-02-23 | 7 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 907b55baacc5e3d1887914a7d9435458 | 2026-02-23 | 7 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 6130cf74932c86e310934ec9b2d4a61b | 2026-02-23 | 7 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 32ebfc0d559c432aee0e812b6dc351a6 | 2026-02-24 | 7 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 5e491e48cc7c6deff9bf68dc2afaf18f | 2026-02-27 | 8 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 80ccc1418ff958892a1908ee5f15259a | 2026-02-25 | 8 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 1858b02a9dd0024e9d3867590246f291 | 2026-02-25 | 7 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 5b35ab08badaad9bf72167e0d6974368 | 2026-02-25 | 8 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 8a3d30f5bea5cd1208eb0fad0e92df0d | 2026-02-25 | 8 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 8d8c0b6066fd7cfdef31686b9cbf8515 | 2026-02-25 | 8 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| c01309e98b7260bed63f11dd6d89d17a | 2026-02-26 | 8 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| d5eef41faf3020debd828c5e65e77886 | 2026-02-26 | 8 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 3a6229f8ff99e1c13bcab017f12277ba | 2026-02-26 | 8 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| a4735547f4d56d3c67e4f59655de6df1 | 2026-02-26 | 8 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| c52c41d3b675e4eb2efd7c7486451907 | 2026-02-26 | 8 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 4ecc99cb37585289467a5a3a1268f63b | 2026-02-26 | 8 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 02634cd3ebcb4855d0f962e4e893b816 | 2026-02-26 | 8 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 17198ef09ae72854b55d52d7261385c5 | 2026-02-27 | 8 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| cf05ec26c388fba36c5c313511a7b0b7 | 2026-02-27 | 8 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| a244b7c43d0ad005b411b466c7f42ab6 | 2026-02-27 | 8 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 6dd448f1761730d8b2046adf8a7f4eca | 2026-02-23 | 8 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 85fbf0b647bad0e1be5050b505826da4 | 2026-02-23 | 7 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 1d73f732ac971f9ad376f7c66ad4b4bd | 2026-02-23 | 8 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 5735c0e7bda017381ceb9878cd5043d7 | 2026-02-23 | 8 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 99f9ef4277713c5b2c52c54313a82662 | 2026-02-23 | 8 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 50289dffade4d96a406348ddecf7c76f | 2026-02-23 | 8 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 1a7bb40a38c8127368abb54d38f4805b | 2026-02-23 | 8 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| d7d439ddd626fd073c38488f8661fc62 | 2026-02-23 | 8 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| ecfb100a595dd7507ea7737419a49f96 | 2026-02-27 | 8 | checker_decision | resolved_by_rerun | HUMAN | checker | RERUN Resolved by the re-run - no longer failing |
| 8535358623ecfb58e8ba94a4e527ae08 | 2026-02-27 | 8 | checker_decision | resolved_by_rerun | HUMAN | checker | RERUN Resolved by the re-run - no longer failing |
| c6cc3d77df0341786c71289a608c0aad | 2026-02-27 | 8 | checker_decision | resolved_by_rerun | HUMAN | checker | RERUN Resolved by the re-run - no longer failing |
| da94469f3e47b0168f8e384a665dacf4 | 2026-02-27 | 8 | checker_decision | resolved_by_rerun | HUMAN | checker | RERUN Resolved by the re-run - no longer failing |
| 2ea814350ed37b5995af37473dffec4d | 2026-02-27 | 8 | checker_decision | resolved_by_rerun | HUMAN | checker | RERUN Resolved by the re-run - no longer failing |
| a624bdd2e1c6e500abaadde81ac83695 | 2026-02-27 | 8 | checker_decision | resolved_by_rerun | HUMAN | checker | RERUN Resolved by the re-run - no longer failing |
| 914a663975316dca57949973c25f99be | 2026-02-27 | 8 | checker_decision | resolved_by_rerun | HUMAN | checker | RERUN Resolved by the re-run - no longer failing |
| b3a6b59b43481c9deac1f71d97087933 | 2026-02-27 | 8 | checker_decision | resolved_by_rerun | HUMAN | checker | RERUN Resolved by the re-run - no longer failing |
| 04a03030270d605676ec5c065deca3da | 2026-02-27 | 8 | checker_decision | resolved_by_rerun | HUMAN | checker | RERUN Resolved by the re-run - no longer failing |
| cde630c67c0215570466c71e6e7ca659 | 2026-02-27 | 8 | checker_decision | resolved_by_rerun | HUMAN | checker | RERUN Resolved by the re-run - no longer failing |
| 28c453c70809915653c6cb0a6d8ceb5e | 2026-02-27 | 8 | checker_decision | resolved_by_rerun | HUMAN | checker | RERUN Resolved by the re-run - no longer failing |
| bf61a7c7c5851f9d24a2dbbe762adc05 | 2026-02-27 | 8 | checker_decision | resolved_by_rerun | HUMAN | checker | RERUN Resolved by the re-run - no longer failing |
| feecd914aa81ca4fc2e481c630c3778f | 2026-02-27 | 8 | checker_decision | resolved_by_rerun | HUMAN | checker | RERUN Resolved by the re-run - no longer failing |
| d1050c16002499c96f65d5e454e83474 | 2026-02-27 | 8 | checker_decision | resolved_by_rerun | HUMAN | checker | RERUN Resolved by the re-run - no longer failing |
| ffa73e8d4f34c36d16485904803ff261 | 2026-02-27 | 8 | checker_decision | resolved_by_rerun | HUMAN | checker | RERUN Resolved by the re-run - no longer failing |
| a154b29b6e94c1db80437d14a76bd61c | 2026-02-27 | 8 | checker_decision | resolved_by_rerun | HUMAN | checker | RERUN Resolved by the re-run - no longer failing |
| a154b29b6e94c1db80437d14a76bd61c | 2026-02-27 | 8 | checker_decision | resolved_by_rerun | HUMAN | checker | RERUN Resolved by the re-run - no longer failing |
| a154b29b6e94c1db80437d14a76bd61c | 2026-02-27 | 8 | checker_decision | resolved_by_rerun | HUMAN | checker | RERUN Resolved by the re-run - no longer failing |
| 15a331445d5437a630a19e4130551679 | 2026-02-27 | 10 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| a2a76e5d2a0b041ec63eb02483642a6e | 2026-02-27 | 10 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| cdcd59394616f647314fa428894edc67 | 2026-02-23 | 10 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| aac77dfa674eeb61f8d1beeeb74432ad | 2026-02-23 | 10 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 83a39dd7cc8b8bd3b0904f55b2e63370 | 2026-02-23 | 10 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| ea56526e2ff89eac4f54c30017117d52 | 2026-02-23 | 10 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 7bcfeb4d34db0bb672b34f12cf1db15e | 2026-02-24 | 10 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 43a453014c0c6980b89dd1b4d43e4533 | 2026-02-26 | 10 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| bbbf70120b95e9427cd0b0e40852b83e | 2026-02-26 | 10 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 6199d570fa6fc439e71302c12edc7ea9 | 2026-02-26 | 10 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| bb29f71fe0e57584f6a0539493e598e7 | 2026-02-26 | 10 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| ea5bffa353a0106bba9ed20c0e3980ae | 2026-02-26 | 10 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| e57272b8b1b4ca4ab6f6096c9adefa71 | 2026-02-26 | 10 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| dfbfad8d941167e1c2f2e6b01f92368b | 2026-02-26 | 10 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 7c6ee3cbcf5c388e41cc708c59ada9d0 | 2026-02-26 | 10 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 4c82fce964221900147769c5e8276c86 | 2026-02-26 | 10 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |
| 5e0dd06c9fd879552b41d55eea882a86 | 2026-02-25 | 10 | checker_decision | approved | HUMAN | fr2052a agents (straight-through) | STP Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect |

## GenAI evaluation of the agents (ai_assist.evaluation, latest run)

```sql
SELECT eval_run, suggestion_type, metric, ROUND(value, 3) AS value, n FROM <catalog>.ai_assist.evaluation WHERE suggestion_type LIKE 'AGENT%' AND eval_run = (SELECT MAX(eval_run) FROM <catalog>.ai_assist.evaluation WHERE suggestion_type LIKE 'AGENT%') ORDER BY 2, 3
```

| eval_run | suggestion_type | metric | value | n |
|---|---|---|---|---|
| 20261104-192611 | AGENT:Classifier:Comment for the Fed | approved_without_edit_pct |  | 32 |
| 20261104-192611 | AGENT:Classifier:Comment for the Fed | decided | 0.0 | 32 |
| 20261104-192611 | AGENT:Classifier:Comment for the Fed | decided_on_step_page | 0.0 | 32 |
| 20261104-192611 | AGENT:Classifier:Comment for the Fed | edited_pct |  | 32 |
| 20261104-192611 | AGENT:Classifier:Comment for the Fed | pending | 16.0 | 32 |
| 20261104-192611 | AGENT:Classifier:Comment for the Fed | proposals | 32.0 | 32 |
| 20261104-192611 | AGENT:Classifier:Comment for the Fed | resolved_by_rerun | 16.0 | 32 |
| 20261104-192611 | AGENT:Classifier:Comment for the Fed | returned_pct |  | 32 |
| 20261104-192611 | AGENT:Classifier:Comment for the Fed | rule_agent_agrees_pct | 100.0 | 32 |
| 20261104-192611 | AGENT:Classifier:Data quality break | approved_without_edit_pct | 100.0 | 12 |
| 20261104-192611 | AGENT:Classifier:Data quality break | decided | 4.0 | 12 |
| 20261104-192611 | AGENT:Classifier:Data quality break | decided_on_step_page | 0.0 | 12 |
| 20261104-192611 | AGENT:Classifier:Data quality break | edited_pct | 0.0 | 12 |
| 20261104-192611 | AGENT:Classifier:Data quality break | pending | 8.0 | 12 |
| 20261104-192611 | AGENT:Classifier:Data quality break | proposals | 12.0 | 12 |
| 20261104-192611 | AGENT:Classifier:Data quality break | resolved_by_rerun | 0.0 | 12 |
| 20261104-192611 | AGENT:Classifier:Data quality break | returned_pct | 0.0 | 12 |
| 20261104-192611 | AGENT:Classifier:Data quality break | rule_agent_agrees_pct | 58.333 | 12 |
| 20261104-192611 | AGENT:Classifier:New customer | approved_without_edit_pct |  | 8 |
| 20261104-192611 | AGENT:Classifier:New customer | decided | 0.0 | 8 |
| 20261104-192611 | AGENT:Classifier:New customer | decided_on_step_page | 0.0 | 8 |
| 20261104-192611 | AGENT:Classifier:New customer | edited_pct |  | 8 |
| 20261104-192611 | AGENT:Classifier:New customer | pending | 8.0 | 8 |
| 20261104-192611 | AGENT:Classifier:New customer | proposals | 8.0 | 8 |
| 20261104-192611 | AGENT:Classifier:New customer | resolved_by_rerun | 0.0 | 8 |
| 20261104-192611 | AGENT:Classifier:New customer | returned_pct |  | 8 |
| 20261104-192611 | AGENT:Classifier:New customer | rule_agent_agrees_pct | 100.0 | 8 |
| 20261104-192611 | AGENT:Classifier:Validation failure | approved_without_edit_pct | 100.0 | 21 |
| 20261104-192611 | AGENT:Classifier:Validation failure | decided | 7.0 | 21 |
| 20261104-192611 | AGENT:Classifier:Validation failure | decided_on_step_page | 0.0 | 21 |
| 20261104-192611 | AGENT:Classifier:Validation failure | edited_pct | 0.0 | 21 |
| 20261104-192611 | AGENT:Classifier:Validation failure | pending | 14.0 | 21 |
| 20261104-192611 | AGENT:Classifier:Validation failure | proposals | 21.0 | 21 |
| 20261104-192611 | AGENT:Classifier:Validation failure | resolved_by_rerun | 0.0 | 21 |
| 20261104-192611 | AGENT:Classifier:Validation failure | returned_pct | 0.0 | 21 |
| 20261104-192611 | AGENT:Classifier:Validation failure | rule_agent_agrees_pct | 76.19 | 21 |
| 20261104-192611 | AGENT:Classifier:Validation warning | approved_without_edit_pct | 100.0 | 24 |
| 20261104-192611 | AGENT:Classifier:Validation warning | decided | 3.0 | 24 |
| 20261104-192611 | AGENT:Classifier:Validation warning | decided_on_step_page | 0.0 | 24 |
| 20261104-192611 | AGENT:Classifier:Validation warning | edited_pct | 0.0 | 24 |
| 20261104-192611 | AGENT:Classifier:Validation warning | pending | 21.0 | 24 |
| 20261104-192611 | AGENT:Classifier:Validation warning | proposals | 24.0 | 24 |
| 20261104-192611 | AGENT:Classifier:Validation warning | resolved_by_rerun | 0.0 | 24 |
| 20261104-192611 | AGENT:Classifier:Validation warning | returned_pct | 0.0 | 24 |
| 20261104-192611 | AGENT:Classifier:Validation warning | rule_agent_agrees_pct | 100.0 | 24 |
| 20261104-192611 | AGENT:Feed monitor:Feed incomplete | approved_without_edit_pct |  | 5 |
| 20261104-192611 | AGENT:Feed monitor:Feed incomplete | decided | 0.0 | 5 |
| 20261104-192611 | AGENT:Feed monitor:Feed incomplete | decided_on_step_page | 0.0 | 5 |
| 20261104-192611 | AGENT:Feed monitor:Feed incomplete | edited_pct |  | 5 |
| 20261104-192611 | AGENT:Feed monitor:Feed incomplete | pending | 5.0 | 5 |
| 20261104-192611 | AGENT:Feed monitor:Feed incomplete | proposals | 5.0 | 5 |
| 20261104-192611 | AGENT:Feed monitor:Feed incomplete | resolved_by_rerun | 0.0 | 5 |
| 20261104-192611 | AGENT:Feed monitor:Feed incomplete | returned_pct |  | 5 |
| 20261104-192611 | AGENT:Feed monitor:Feed incomplete | rule_agent_agrees_pct | 100.0 | 5 |
| 20261104-192611 | AGENT:Tie-out agent:GL tie-out | approved_without_edit_pct | 100.0 | 17 |
| 20261104-192611 | AGENT:Tie-out agent:GL tie-out | decided | 7.0 | 17 |
| 20261104-192611 | AGENT:Tie-out agent:GL tie-out | decided_on_step_page | 0.0 | 17 |
| 20261104-192611 | AGENT:Tie-out agent:GL tie-out | edited_pct | 0.0 | 17 |
| 20261104-192611 | AGENT:Tie-out agent:GL tie-out | pending | 10.0 | 17 |
| 20261104-192611 | AGENT:Tie-out agent:GL tie-out | proposals | 17.0 | 17 |
| 20261104-192611 | AGENT:Tie-out agent:GL tie-out | resolved_by_rerun | 0.0 | 17 |
| 20261104-192611 | AGENT:Tie-out agent:GL tie-out | returned_pct | 0.0 | 17 |
| 20261104-192611 | AGENT:Tie-out agent:GL tie-out | rule_agent_agrees_pct | 100.0 | 17 |
| 20261104-192611 | AGENT:all | cites_regulation.mean | 0.951 | 103 |
| 20261104-192611 | AGENT:all | grounded_in_evidence.mean | 0.903 | 103 |
| 20261104-192611 | AGENT:all | rule_agent_agrees.mean | 0.903 | 103 |

## AI Functions suggestions (ai_assist.suggestions, notebook 09)

```sql
SELECT as_of_date, suggestion_type, ai_function, model, subject_key, ROUND(confidence, 2) AS confidence, status, substr(suggestion, 1, 160) AS suggestion FROM <catalog>.ai_assist.suggestions WHERE as_of_date >= '2026-02-26' ORDER BY 1, 2 LIMIT 40
```

| as_of_date | suggestion_type | ai_function | model | subject_key | confidence | status | suggestion |
|---|---|---|---|---|---|---|---|
| 2026-02-26 | PID_EXCEPTION | ai_query | databricks-claude-sonnet-4-6 | LOA-2026-02-26-EXC02#1 | 0.95 | PROPOSED | {"product_id": "I.S.6 or I.S.8", "missing_attribute": "product_subtype", "fix": "Please populate the 'product_subtype' field with either 'REHYPOTHECATABLE' or ' |
| 2026-02-26 | PID_EXCEPTION | ai_query | databricks-claude-sonnet-4-6 | LOA-2026-02-26-EXC02#1 | 0.95 | PROPOSED | {"product_id": "I.S.6 or I.S.8", "missing_attribute": "product_subtype", "fix": "Please populate the 'product_subtype' field with either 'REHYPOTHECATABLE' or ' |
| 2026-02-26 | PID_EXCEPTION | ai_query | databricks-claude-sonnet-4-6 | LOA-2026-02-26-EXC02#1 | 0.95 | PROPOSED | {"product_id": "I.S.6 or I.S.8", "missing_attribute": "product_subtype", "fix": "Please populate the 'product_subtype' field with either 'REHYPOTHECATABLE' or ' |
| 2026-02-26 | RULE_EXPLANATION | ai_query | databricks-claude-sonnet-4-6 | SPEC-V-07 |  | PROPOSED | {"explanation": "The net 30-day derivative position reported in the I.O.7/O.O.20 section (-208.45) does not reconcile with the gross derivative collateral inflo |
| 2026-02-26 | RULE_EXPLANATION | ai_query | databricks-claude-sonnet-4-6 | PSV-14 |  | PROPOSED | {"explanation": "PSV-14 is a plausibility warning that flags unusually large balances in specific product/counterparty combinations across the FR 2052a tables,  |
| 2026-02-26 | RULE_EXPLANATION | ai_query | databricks-claude-sonnet-4-6 | SPEC-V-09 |  | PROPOSED | {"explanation": "The net 30-day derivative position reported in the Internal/Other flows (I.O.7 / O.O.20) shows -208.45, but the sum of forward purchase inflows |
| 2026-02-26 | RULE_EXPLANATION | ai_query | databricks-claude-sonnet-4-6 | SPEC-V-08 |  | PROPOSED | {"explanation": "SPEC-V-08 requires that the net 30-day cash flows from FX transactions reported in the derivative schedules (S.FX.1-3) must reconcile to the co |
| 2026-02-26 | RULE_EXPLANATION | ai_query | databricks-claude-sonnet-4-6 | RECON-GL |  | PROPOSED | {"explanation": "The General Ledger balances for Legal Entities LE02 and LE03 are significantly higher than what has been reported in the FR 2052a filing across |
| 2026-02-26 | RULE_EXPLANATION | ai_query | databricks-claude-sonnet-4-6 | SPEC-V-13 |  | PROPOSED | {"explanation": "Derivative record DER-2026-02-26-00006 represents collateral that has been called for receipt with an open maturity bucket, which requires it t |
| 2026-02-26 | RULE_EXPLANATION | ai_query | databricks-claude-sonnet-4-6 | SPEC-V-12 |  | PROPOSED | {"explanation": "The FR 2052a requires that outflow amounts for Loss of Rehypothecation Rights be non-decreasing across credit downgrade scenarios, meaning a 2- |
| 2026-02-26 | RULE_EXPLANATION | ai_query | databricks-claude-sonnet-4-6 | SPEC-V-06 |  | PROPOSED | {"explanation": "The net 30-day unsecured derivative position reported in the I.O.7/O.O.20 netting schedule (-208.45) does not reconcile to the sum of the indiv |
| 2026-02-26 | RULE_EXPLANATION | ai_query | databricks-claude-sonnet-4-6 | SPEC-V-11 |  | PROPOSED | {"explanation": "The FR 2052a validation requires that collateral required under a 1-notch credit rating downgrade scenario (O.O.13) must be less than or equal  |
| 2026-02-27 | COMMENT_DRAFT | ai_query | databricks-claude-sonnet-4-6 | 2026-02-27\|ENT001 O.D |  | PROPOSED | {"reporting_entity": "ENT001", "collection": "O.D", "product_id": null, "comments": "ENT001 Outflows-Deposits declined USD 41,989mm (-35.0%) day-over-day to USD |
| 2026-02-27 | COMMENT_DRAFT | ai_query | databricks-claude-sonnet-4-6 | 2026-02-27\|ENT002 O.D O.D.1 |  | PROPOSED | {"reporting_entity": "ENT002", "collection": "O.D", "product_id": "O.D.1", "comments": "ENT002 Outflows-Deposits O.D O.D.1 declined USD 17,218mm (-57.0%) to USD |
| 2026-02-27 | COMMENT_DRAFT | ai_query | databricks-claude-sonnet-4-6 | 2026-02-27\|ENT001 O.D O.D.1 |  | PROPOSED | {"reporting_entity": "ENT001", "collection": "O.D", "product_id": "O.D.1", "comments": "ENT001 Outflows-Deposits O.D.1 declined USD 17,217mm (-57.0%) day-over-d |
| 2026-02-27 | COMMENT_DRAFT | ai_query | databricks-claude-sonnet-4-6 | 2026-02-27\|ENT003 S.DC |  | PROPOSED | {"reporting_entity": "ENT003", "collection": "S.DC", "product_id": null, "comments": "ENT003 Supplemental-Derivatives & Collateral rose USD 11,845mm (+40.7%) to |
| 2026-02-27 | COMMENT_DRAFT | ai_query | databricks-claude-sonnet-4-6 | 2026-02-27\|ENT001 S.DC |  | PROPOSED | {"reporting_entity": "ENT001", "collection": "S.DC", "product_id": null, "comments": "ENT001 Supplemental-Derivatives & Collateral rose USD 11,845mm (+40.7%) to |
| 2026-02-27 | COMMENT_DRAFT | ai_query | databricks-claude-sonnet-4-6 | 2026-02-27\|ENT002 O.D |  | PROPOSED | {"reporting_entity": "ENT002", "collection": "O.D", "product_id": null, "comments": "ENT002 Outflows-Deposits declined USD 42,489mm (-35.2%) to USD 78,110mm on  |
| 2026-02-27 | COMMENT_DRAFT | ai_query | databricks-claude-sonnet-4-6 | 2026-02-27\|ENT001 S.B |  | PROPOSED | {"reporting_entity": "ENT001", "collection": "S.B", "product_id": null, "comments": "ENT001 Supplemental-Balance Sheet increased from USD -2,508mm to USD 42,410 |
| 2026-02-27 | COMMENT_DRAFT | ai_query | databricks-claude-sonnet-4-6 | 2026-02-27\|ENT001 O.O |  | PROPOSED | {"reporting_entity": "ENT001", "collection": "O.O", "product_id": null, "comments": "Outflows-Other increased USD 14,188mm (+41.2%) to USD 48,622mm, driven by f |
| 2026-02-27 | CUSTOMER_CLASSIFICATION | ai_classify + ai_similarity + ai_query | databricks-claude-sonnet-4-6 | C0305 |  | PROPOSED | {"counterparty": "Public Sector Entity", "gsib_parent": null, "affiliate_legal_entity_id": null, "has_relationship": false, "gsib_similarity": 0.514, "descripti |
| 2026-02-27 | CUSTOMER_CLASSIFICATION | ai_classify + ai_similarity + ai_query | databricks-claude-sonnet-4-6 | C0306 |  | PROPOSED | {"counterparty": "Non-regulated Fund", "gsib_parent": null, "affiliate_legal_entity_id": null, "has_relationship": false, "gsib_similarity": 0.647, "description |
| 2026-02-27 | PID_EXCEPTION | ai_query | databricks-claude-sonnet-4-6 | LOA-2026-02-27-EXC02#1 | 0.95 | PROPOSED | {"product_id": "I.S.6 or I.S.8", "missing_attribute": "product_subtype", "fix": "Please populate the 'product_subtype' field with either 'REHYPOTHECATABLE' or ' |
| 2026-02-27 | PID_EXCEPTION | ai_query | databricks-claude-sonnet-4-6 | LOA-2026-02-27-EXC02#1 | 0.95 | PROPOSED | {"product_id": "I.S.6 or I.S.8", "missing_attribute": "product_subtype", "fix": "Please populate the 'product_subtype' field with either 'REHYPOTHECATABLE' or ' |
| 2026-02-27 | PID_EXCEPTION | ai_query | databricks-claude-sonnet-4-6 | LOA-2026-02-27-EXC02#1 | 0.95 | PROPOSED | {"product_id": "I.S.6 or I.S.8", "missing_attribute": "product_subtype", "fix": "Please populate the 'product_subtype' field with either 'REHYPOTHECATABLE' or ' |
| 2026-02-27 | RULE_EXPLANATION | ai_query | databricks-claude-sonnet-4-6 | RECON-GL |  | PROPOSED | {"explanation": "The General Ledger balance for legal entity LE02's Off-Balance Sheet Drawdowns (O.D.) table is $121,079.7MM, but the FR 2052a filing only refle |
| 2026-02-27 | RULE_EXPLANATION | ai_query | databricks-claude-sonnet-4-6 | PSV-06 |  | PROPOSED | {"explanation": "PSV-06 checks that intercompany cash flows are reported symmetrically: when one legal entity records an internal inflow, the counterparty entit |
| 2026-02-27 | RULE_EXPLANATION | ai_query | databricks-claude-sonnet-4-6 | PSV-14 |  | PROPOSED | {"explanation": "PSV-14 flags unusually large balances in specific product/counterparty combinations across the FR 2052a schedules, triggering a WARNING that re |
| 2026-02-27 | VARIANCE_COMMENTARY | ai_forecast + ai_query | databricks-claude-sonnet-4-6 | 2026-02-27\|ENT001 O.O |  | PROPOSED | {"commentary": "Outflows-Other surged 41.2% day-over-day from USD 34,434mm to USD 48,622mm, breaching the upper bound of the AI forecast range of USD 26,752mm-4 |
| 2026-02-27 | VARIANCE_COMMENTARY | ai_forecast + ai_query | databricks-claude-sonnet-4-6 | 2026-02-27\|ENT001 O.D |  | PROPOSED | {"commentary": "ENT001 Outflows-Deposits dropped sharply from USD 120,109mm to USD 78,120mm (-35.0%), falling well outside the AI-forecast expected range of USD |
| 2026-02-27 | VARIANCE_COMMENTARY | ai_forecast + ai_query | databricks-claude-sonnet-4-6 | 2026-02-27\|ENT002 O.D |  | PROPOSED | {"commentary": "ENT002 Outflows-Deposits dropped sharply from USD 120,599mm to USD 78,110mm (-35.2%), falling well below the AI-forecast expected range of USD 1 |
| 2026-02-27 | VARIANCE_COMMENTARY | ai_forecast + ai_query | databricks-claude-sonnet-4-6 | 2026-02-27\|ENT003 S.DC |  | PROPOSED | {"commentary": "ENT003 Supplemental-Derivatives & Collateral increased USD 11,845mm (+40.7%) day-over-day to USD 40,967mm, breaching the upper bound of the AI f |
| 2026-02-27 | VARIANCE_COMMENTARY | ai_forecast + ai_query | databricks-claude-sonnet-4-6 | 2026-02-27\|ENT002 O.D O.D.1 |  | PROPOSED | {"commentary": "ENT002 Outflows-Deposits O.D O.D.1 dropped sharply from USD 30,190mm to USD 12,972mm (-57.0%), well outside the AI-forecast range of USD 30,115m |
| 2026-02-27 | VARIANCE_COMMENTARY | ai_forecast + ai_query | databricks-claude-sonnet-4-6 | 2026-02-27\|ENT001 S.B |  | PROPOSED | {"commentary": "ENT001 Supplemental-Balance Sheet surged from USD -2,508mm to USD 42,410mm (a -1,790.7% day-over-day swing), well outside the AI-forecast expect |
| 2026-02-27 | VARIANCE_COMMENTARY | ai_forecast + ai_query | databricks-claude-sonnet-4-6 | 2026-02-27\|ENT001 O.D O.D.1 |  | PROPOSED | {"commentary": "ENT001 Outflows-Deposits O.D.1 dropped sharply from USD 30,199mm to USD 12,982mm (-57.0%), falling well outside the AI-forecast expected range o |
| 2026-02-27 | VARIANCE_COMMENTARY | ai_forecast + ai_query | databricks-claude-sonnet-4-6 | 2026-02-27\|ENT001 S.DC |  | PROPOSED | {"commentary": "Supplemental-Derivatives & Collateral for ENT001 increased USD 11,845mm (+40.7%) day-over-day to USD 40,967mm, breaching the upper bound of the  |

