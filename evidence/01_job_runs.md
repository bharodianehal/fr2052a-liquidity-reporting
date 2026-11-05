# Job runs

Captured 2026-11-05 18:17 UTC from `https://<workspace>.cloud.databricks.com` by `deploy/capture_evidence.py`.

The pipeline runs as Lakeflow Jobs on serverless compute. `fr2052a-daily` builds one reporting date end to end (app decisions -> Lakeflow ingest -> DQ -> PID enrichment -> LCR -> report -> validation + 6G XML -> AI assist -> Lakebase sync -> the AI agents).

## fr2052a-daily (job 539794379637862)

| run id | started | result | as_of_date / promote | minutes | tasks |
|---|---|---|---|---|---|
| 621752240825534 | 2026-11-05 14:30 UTC | SUCCESS | 2026-02-27 | 6.9 | run_ingest=DISABLED, pid_derivation=DISABLED, report_build=DISABLED, validation_submission=DISABLED, dq_gate=DISABLED, lcr_engine=DISABLED, lakebase_sync=SUCCESS, app_decisions=DISABLED, ai_assist=DISABLED, ingest=DISABLED, run_2052a=DISABLED, run_agents=DISABLED |
| 775943883436932 | 2026-11-04 21:43 UTC | SUCCESS | 2026-02-26 | 56.6 | app_decisions=SUCCESS, run_ingest=SUCCESS, ingest=EXCLUDED, dq_gate=SUCCESS, pid_derivation=SUCCESS, lcr_engine=SUCCESS, run_2052a=SUCCESS, report_build=SUCCESS, validation_submission=SUCCESS, ai_assist=SUCCESS, lakebase_sync=SUCCESS, run_agents=SUCCESS |
| 200326912049707 | 2026-11-04 21:43 UTC | SUCCESS | 2026-02-27 | 51.3 | app_decisions=SUCCESS, run_ingest=SUCCESS, ingest=EXCLUDED, dq_gate=SUCCESS, pid_derivation=SUCCESS, lcr_engine=SUCCESS, run_2052a=SUCCESS, report_build=SUCCESS, validation_submission=SUCCESS, ai_assist=SUCCESS, lakebase_sync=SUCCESS, run_agents=SUCCESS |
| 83987489818440 | 2026-11-04 21:43 UTC | SUCCESS | 2026-02-25 | 61.9 | app_decisions=SUCCESS, run_ingest=SUCCESS, ingest=EXCLUDED, dq_gate=SUCCESS, pid_derivation=SUCCESS, lcr_engine=SUCCESS, run_2052a=SUCCESS, report_build=SUCCESS, validation_submission=SUCCESS, ai_assist=SUCCESS, lakebase_sync=SUCCESS, run_agents=SUCCESS |
| 866844688422832 | 2026-11-04 21:43 UTC | SUCCESS | 2026-02-24 | 45.8 | app_decisions=SUCCESS, run_ingest=SUCCESS, ingest=EXCLUDED, dq_gate=SUCCESS, pid_derivation=SUCCESS, lcr_engine=SUCCESS, run_2052a=SUCCESS, report_build=SUCCESS, validation_submission=SUCCESS, ai_assist=SUCCESS, lakebase_sync=SUCCESS, run_agents=SUCCESS |
| 819860667567324 | 2026-11-04 21:43 UTC | SUCCESS | 2026-02-23 | 38.9 | app_decisions=SUCCESS, run_ingest=SUCCESS, ingest=EXCLUDED, dq_gate=SUCCESS, pid_derivation=SUCCESS, lcr_engine=SUCCESS, run_2052a=SUCCESS, report_build=SUCCESS, validation_submission=SUCCESS, ai_assist=SUCCESS, lakebase_sync=SUCCESS, run_agents=SUCCESS |


## fr2052a-revalidate (job 609610710310142)

| run id | started | result | as_of_date / promote | minutes | tasks |
|---|---|---|---|---|---|
| 1114120802429385 | 2026-10-28 15:56 UTC | SUCCESS | 2026-02-27 | 45.5 | apply_corrections=SUCCESS, lcr_engine=SUCCESS, report_build=SUCCESS, validation_submission=SUCCESS, ai_explanations=SUCCESS, lakebase_sync=SUCCESS |
| 542113777141485 | 2026-10-28 15:56 UTC | SUCCESS | 2026-02-26 | 44.6 | apply_corrections=SUCCESS, lcr_engine=SUCCESS, report_build=SUCCESS, validation_submission=SUCCESS, ai_explanations=SUCCESS, lakebase_sync=SUCCESS |
| 889437440505084 | 2026-10-28 15:56 UTC | SUCCESS | 2026-02-25 | 24.4 | apply_corrections=SUCCESS, lcr_engine=SUCCESS, report_build=SUCCESS, validation_submission=SUCCESS, ai_explanations=SUCCESS, lakebase_sync=SUCCESS |
| 184435402462965 | 2026-10-28 15:56 UTC | SUCCESS | 2026-02-24 | 24.4 | apply_corrections=SUCCESS, lcr_engine=SUCCESS, report_build=SUCCESS, validation_submission=SUCCESS, ai_explanations=SUCCESS, lakebase_sync=SUCCESS |
| 798432286110612 | 2026-10-28 15:56 UTC | SUCCESS | 2026-02-23 | 24.4 | apply_corrections=SUCCESS, lcr_engine=SUCCESS, report_build=SUCCESS, validation_submission=SUCCESS, ai_explanations=SUCCESS, lakebase_sync=SUCCESS |
| 634867403175908 | 2026-10-27 19:36 UTC | SUCCESS | 2026-02-27 | 18.5 | apply_corrections=SUCCESS, lcr_engine=SUCCESS, report_build=SUCCESS, validation_submission=SUCCESS, ai_explanations=SUCCESS, lakebase_sync=SUCCESS |


## fr2052a-generate (job 791977089273711)

| run id | started | result | as_of_date / promote | minutes | tasks |
|---|---|---|---|---|---|
| 1129432483744 | 2026-11-02 18:22 UTC | SUCCESS | 2026-02-24 | 23.5 | app_decisions=SUCCESS, apply_corrections=SUCCESS, lcr_engine=SUCCESS, report_build=SUCCESS, validation_submission=SUCCESS, lakebase_sync=SUCCESS |
| 643339301746156 | 2026-10-29 21:29 UTC | SUCCESS | 2026-02-24 | 18.3 | app_decisions=FAILED, app_decisions=SUCCESS, apply_corrections=SUCCESS, lcr_engine=SUCCESS, report_build=SUCCESS, validation_submission=SUCCESS, lakebase_sync=SUCCESS |

- Run `643339301746156` was repaired: a task failed, the run was repaired and every task then succeeded.

## fr2052a-register-agents (job 102315269843868)

| run id | started | result | as_of_date / promote | minutes | tasks |
|---|---|---|---|---|---|
| 40499021638394 | 2026-11-05 14:13 UTC | SUCCESS | false | 1.9 | agents_identity=SUCCESS, register=SUCCESS |
| 387319122297983 | 2026-11-05 03:40 UTC | SUCCESS | false | 0.6 | agents_identity=SUCCESS, register=DISABLED |
| 237301115059261 | 2026-11-04 14:24 UTC | SUCCESS | true | 1.3 | register=SUCCESS |
| 713745894331693 | 2026-11-03 23:09 UTC | SUCCESS | true | 1.2 | register=SUCCESS |
| 586909089203358 | 2026-11-03 14:36 UTC | SUCCESS | true | 1.4 | register=SUCCESS |
| 1008129093941149 | 2026-11-02 20:14 UTC | SUCCESS | true | 1.2 | register=SUCCESS |


### Task `agents_identity` (`deploy/agents_identity.py`), run `40499021638394` (2026-11-05 14:13 UTC): output

```
service principal fr2052a-agents exists: <agents-service-principal>
OAuth secret already in scope fr2052a
CAN_USE on warehouse b8959d0a65ca07c8
agents_sp_client_id = <agents-service-principal>
```

## fr2052a-pipeline (job 359995530517944)

| run id | started | result | as_of_date / promote | minutes | tasks |
|---|---|---|---|---|---|
| 228032469489210 | 2026-11-05 14:13 UTC | SUCCESS |  | 16.2 | ingest_full_refresh=DISABLED, setup=DISABLED, genie_skills=SUCCESS, regulatory_text=SUCCESS, lakebase_tables=DISABLED, daily_all_dates=DISABLED, ai_variance_latest=SUCCESS, ai_evaluation=DISABLED, ai_tools=DISABLED, metric_views=DISABLED, governance=SUCCESS |
| 899312113474890 | 2026-11-05 03:47 UTC | SUCCESS |  | 0.9 | ingest_full_refresh=DISABLED, governance=DISABLED, setup=DISABLED, genie_skills=SUCCESS, regulatory_text=SUCCESS, lakebase_tables=DISABLED, ai_tools=DISABLED, ai_evaluation=DISABLED, metric_views=DISABLED, daily_all_dates=DISABLED, ai_variance_latest=DISABLED |
| 614749418398430 | 2026-11-05 03:40 UTC | FAILED |  | 1.3 | genie_skills=FAILED, regulatory_text=FAILED, ingest_full_refresh=DISABLED, governance=DISABLED, setup=DISABLED, ai_tools=DISABLED, ai_evaluation=DISABLED, metric_views=DISABLED, lakebase_tables=DISABLED, daily_all_dates=DISABLED, ai_variance_latest=DISABLED, genie_skills=FAILED, regulatory_text=FAILED |
| 540452625223577 | 2026-11-04 17:55 UTC | SUCCESS |  | 94.4 | setup=SUCCESS, ingest_full_refresh=SUCCESS, lakebase_tables=FAILED, lakebase_tables=FAILED, daily_all_dates=UPSTREAM_FAILED, ai_variance_latest=UPSTREAM_FAILED, ai_evaluation=UPSTREAM_FAILED, ai_tools=UPSTREAM_FAILED, metric_views=UPSTREAM_FAILED, governance=UPSTREAM_FAILED, lakebase_tables=SUCCESS, daily_all_dates=SUCCESS, ai_variance_latest=SUCCESS, ai_evaluation=SUCCESS, ai_tools=SUCCESS, metric_views=SUCCESS, governance=SUCCESS |
| 366493961509803 | 2026-11-04 14:36 UTC | SUCCESS |  | 3.2 | setup=DISABLED, ingest_full_refresh=DISABLED, metric_views=DISABLED, ai_tools=DISABLED, ai_evaluation=SUCCESS, lakebase_tables=DISABLED, daily_all_dates=DISABLED, ai_variance_latest=DISABLED, governance=DISABLED |
| 287243122326585 | 2026-11-03 14:38 UTC | SUCCESS |  | 13.5 | ingest_full_refresh=DISABLED, setup=DISABLED, serving_full_refresh=DISABLED, daily_all_dates=DISABLED, ai_variance_latest=SUCCESS, ai_tools=SUCCESS, ai_evaluation=SUCCESS, metric_views=SUCCESS, governance=SUCCESS |

- Run `228032469489210` ran only these tasks: ai_variance_latest, genie_skills, governance, regulatory_text (the rest were not selected).
- Run `899312113474890` ran only these tasks: genie_skills, regulatory_text (the rest were not selected).
- Run `540452625223577` was repaired: lakebase_tables failed twice on `sys.exit(0)` in deploy/lakebase_synced_tables.py (any SystemExit fails a serverless Python task); fixed in the script, then the run was repaired and every task succeeded.
- Run `366493961509803` ran only these tasks: ai_evaluation (the rest were not selected).
- Run `287243122326585` ran only these tasks: ai_evaluation, ai_tools, ai_variance_latest, governance, metric_views (the rest were not selected).

### Task `regulatory_text` (`deploy/regulatory_text_index.py`), run `228032469489210` (2026-11-05 14:13 UTC): output

```
chunks: 475
index <catalog>.reference.reg_text_index sync started
```

### Task `genie_skills` (`deploy/deploy_genie_skills.py`), run `228032469489210` (2026-11-05 14:13 UTC): output

```
uploaded fr2052a-daily-review -> /Workspace/Users/user1@example.com/.assistant/skills/fr2052a-daily-review
uploaded fr2052a-variance-explainer -> /Workspace/Users/user1@example.com/.assistant/skills/fr2052a-variance-explainer
```

### Task `lakebase_tables` (`deploy/lakebase_synced_tables.py`), run `540452625223577` (2026-11-04 18:14 UTC): output

```
58 source views
pipeline <uuid-1> - notebook 07 refreshes it after each run; first load: start an update of the pipeline
```

## fr2052a-demo-reset (job 7323102778502)

| run id | started | result | as_of_date / promote | minutes | tasks |
|---|---|---|---|---|---|
| 307189600281558 | 2026-11-04 21:42 UTC | SUCCESS |  | 77.0 | reset=SUCCESS, daily_all_dates=SUCCESS, ai_variance_latest=SUCCESS |
| 318006524160513 | 2026-11-04 19:30 UTC | SUCCESS |  | 72.0 | reset=SUCCESS, daily_all_dates=SUCCESS, ai_variance_latest=SUCCESS |
| 370987964212308 | 2026-11-03 19:34 UTC | SUCCESS |  | 72.8 | reset=SUCCESS, daily_all_dates=SUCCESS, ai_variance_latest=SUCCESS |
| 197814401927615 | 2026-11-03 12:09 UTC | SUCCESS |  | 2.1 | reset=FAILED, reset=SUCCESS, daily_all_dates=DISABLED, ai_variance_latest=DISABLED |

- Run `197814401927615` was repaired: a task failed, the run was repaired and every task then succeeded.

