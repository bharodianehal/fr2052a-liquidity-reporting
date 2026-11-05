# FR 2052a - QA issues: final list to fix (2026-11-02, senior QA review)

Source: the end-to-end suite `scripts/qa/e2e_qa.py` (62 cases; last run 48 PASS / 9 FAIL / 5 WARN, results in `evidence/qa_report.md`), then a
second review of every finding: re-checked against the code, the UI (is it reachable by a user?), the guards around it and the live data.
Run the suite: `/tmp/fr2052a-venv/bin/python scripts/qa/e2e_qa.py [--only ID,ID]`.

## Status after the fixes (2026-11-02): suite 57 PASS / 0 FAIL / 5 WARN (the 5 are the accepted / not-to-fix items below)

| # | Status | What was done | Retest |
|---|---|---|---|
| 1 | Fixed | v4 registered from the current code and promoted (champion + serving endpoint); nb15 checks the champion's packaged code against the app code ("champion code = app code" on Feb 23). Open: v4 is still packaged on Python 3.10 (a one-time job run of nb16 does not get the pipeline's 3.12 environment) - loads and runs fine on 3.12. The 10 Feb 27 proposals made by v3 this morning keep their label (history). | A03 (WARN: the 10 v3 proposals), nb15 output |
| 2 | Fixed | `ai_decide`: one decision per suggestion (409 on a second); `ai_decisions` append-only (nb07 revokes UPDATE / DELETE - applied by the Feb 23 run); AI decisions in the Audit timeline and the examiner export. | W07 PASS |
| 3 | Fixed | `validate/resolve`: open item of the day (404 / 409), note required for manual / explain, a saved correction behind a manual fix. | W06 PASS |
| 4 | Fixed | `app.check_dates` global dependency: 400 malformed, 404 not a reporting date; `pipeline/run` reporting dates only. | X13, X14, W08 PASS |
| 5 | Fixed | `fr2052a-daily` Feb 23 (run 228607557876723): 4 proposals by fr2052a_agents v4. | A01 PASS |
| 6 | Fixed (mechanism) | nb15 logs checker feedback for every date with decisions. Nothing logged yet because every decision so far is on a proposal from before tracing; the first decision on a traced proposal will be logged by the next run (verify in `uat.py` on Feb 24). | nb15 output |
| 7 | Fixed | `_decide` claims the break (`UPDATE ... WHERE status = 'PROPOSED' RETURNING`) before applying; reverts if the apply fails. | X16 PASS |
| 8 | Fixed | Plurals ("fixes") in Today's labels. | F04 PASS |
| 9 | Fixed | `email_notifications.on_failure` on the four jobs (+ on success for generate), applied with `update_jobs.sh`. | X20 PASS |

## To fix (as found)

| # | Severity | Issue | Verified evidence | Fix | Retest |
|---|---|---|---|---|---|
| 1 | **High** | **The registered agents model is stale, so the pipeline's proposals carry the wrong provenance.** `fr2052a_agents` v3 (champion, registered 2026-10-30 15:52) packages agents code from before "made by" was stored; today's 10 pipeline proposals say `databricks-claude-sonnet-4-6` instead of `fr2052a_agents v3`, and the checker sees that under "made by". Nothing detects that the champion's code lags the repo. v3 was also logged on Python 3.10 and runs on 3.12 (MLflow warns). | A03; `proposals.model`; nb15 output of run 115195682054710 | Register v4 from the current code with nb16 on the pipeline's serverless environment; evaluate with nb10; promote (champion + endpoint). In nb15, compare a hash of the champion's packaged `agents.py` / `workbench.py` / `app.py` with the workspace app code and warn on a mismatch. | A03, A04; rerun nb15 for one date -> new proposals "fr2052a_agents v4" |
| 2 | **High** | **The checker's decisions on AI suggestions are not on the audit trail and can be overwritten.** Accepting or rejecting a comment for the Fed or a new customer / product-code proposal (`ai_decide`) writes no audit event, and the Audit timeline does not read `ai_decisions`: the three decisions of 2026-10-27 (customers C0305 / C0306, product code FIS-CHK-PREMIER) are not in Feb 27's Audit "people". `ai_decisions` is upserted (`ON CONFLICT DO UPDATE`), so a second call replaces the first decision with no history. The UI hides the buttons once decided, but the API does not refuse. | W07; Audit API for Feb 27 (31 people events, none of the 3); `ai_decisions` rows | Refuse a second decision (409). Write every decision as an append-only audit event (like the checker's break decisions; revoke UPDATE / DELETE in nb07). Add `ai_decisions` to the Audit timeline and the examiner export. | W07; decide one comment on Feb 24 -> in Audit; second call -> 409 |
| 3 | Medium | **The server does not enforce what the Validate page enforces.** `validate/resolve` records a decision for any `rule_id` / `item_key` (no check that the exception exists on that date or is still open), and `manual` closes an exception with no correction behind it. The UI always saves a correction first, so this is only reachable through the API, but an exception can be closed without evidence. | W06 (code); `Validate.jsx` saves the correction, then `manual` | Look the item up in `validate_queue(date)` (404 absent, 409 decided); require a note for `explain` and `manual`, and for `manual` a correction of the item's position saved for that date. | W06 + probes with a non-existent item -> 404 |
| 4 | Medium | **Date handling: any date starts the pipeline, and a bad date crashes endpoints.** `POST /api/pipeline/run` only checks the date format, so a Sunday or 2030-01-01 starts `fr2052a-daily` and builds a non-reporting day into Delta. A malformed date returns 500 on 12 of 13 endpoints (`_check_date` raises `ValueError`, not 400); dates outside the reporting window return 200 with empty data. | W08 (code); X14; X13 (the three 500s are bad dates, not SQL injection: those queries are parameterised) | One date check used by every route (app.py and workbench.py): 400 for a malformed date, 404 for a date not in `/api/dates`; `pipeline/run`, `generate` and `revalidate` accept only reporting business days. | X14, W08 |
| 5 | Medium | **Feb 23 has no AI proposals:** its 4 open validation exceptions show "The AI agents have not proposed a fix for this item yet" (`agents_run: false`). Its last daily run (2026-10-28) predates notebook 15, so the agents never ran for that date. This is data state, not code: the app handles it correctly. | A01; review / suggest API for Feb 23 | Run `fr2052a-daily` for Feb 23 (ingest false) after fix 1, so the proposals come from v4. | A01 |
| 6 | Medium | **Checker feedback reaches MLflow only when the pipeline reruns that date.** nb15 logs the decisions as feedback on the traces at the start of the next run of the same date; decisions made after a date's last run (e.g. the release day's) are never logged, and none are logged yet (11 decisions, all on proposals from before tracing; today's 10 traced proposals have no decision yet). Notebook 10's evaluation from human feedback therefore has no data. | nb15 output: `traces 0, decisions 11, feedback_logged 0`; UC trace view: 10 Feb 27 traces, 0 assessments | Log the feedback for every date with decided, traced proposals in a scheduled task (nb10 or a small task at the end of `fr2052a-pipeline` / daily), not only for the date being run. | After one decision on a traced proposal: an assessment on its trace |
| 7 | Low | **A double click or two checkers can record a decision twice.** `_decide` reads the break status, applies the fix, then updates the status, without a lock, so two concurrent approvals of the same break both apply the fix and both write a decision. | Code (`agents._decide`) | Claim the break first: `UPDATE breaks SET status = ... WHERE break_id = %s AND status = 'PROPOSED' RETURNING`; if no row comes back -> 409; then apply. | Two parallel decide calls on a test break -> one 200, one 409 |
| 8 | Low | **Wording:** Today says "2 approved fixs wait for the re-run" ("fix" + "s"; and "1 ... wait"). The UI hides the label when the count is 0. | F04; `agents.review_state` `pl()` | Proper plural ("fixes") and verb agreement. | F04 |
| 9 | Low | **No alert when a job fails:** none of the four jobs notifies on failure, so a failed overnight run is only seen in the app. | X20 | `email_notifications.on_failure` (owner) in `deploy/job_*.json` + `update_jobs.sh`. | X20 |

Order: 1 -> 5 (needs v4) -> 2 -> 3 -> 4 -> 7 -> 6 -> 8 -> 9. Retest: rerun `e2e_qa.py` and `app_test.sh`, then `uat.py` on Feb 24 for the write paths of 2, 3 and 7.

## Reviewed and not to fix (with the reason)

| Finding | Why not |
|---|---|
| Break ids are COUNT(*)+1 per date (X16) | Two agent runs for the same date at once are prevented by the one-run-per-date guard on the jobs, and "Run the agent again" reuses the break's id. If ids ever collided, the primary key raises an error (the item is reported in the run's errors), so nothing is lost silently. |
| `submission_review` has no primary key (X17) | The sign-off transitions refuse a repeated action (APPROVED -> APPROVED is not allowed); only a race could duplicate a row, and the log is append-only by design. |
| 22 SQL-warehouse calls in `agents.py` (X01) | By design: the rule agent's independent re-check on Delta runs in the pipeline and on the serving endpoint; in the app only as the fallback when the endpoint is unavailable. |
| Feedback search found 0 traces at the end of today's run | The new traces become searchable a few minutes after they are written; they are in the UC trace tables (10 for Feb 27). The real gap is issue 6. |
| No unit tests (X21) | An engineering improvement, not a defect; backlog. |
| `source_position.internal_rating` in Lakebase (X11), serving cold start ~100 s (A04: 105.9 s) | Accepted 2026-11-01 (not now). |

## Not covered yet

The screens in a signed-in browser (layout, click-through), and the write paths on real items (accept / return / bulk approve / generate /
approve / submit), which write to the append-only audit trail: run `scripts/qa/uat.py` on Feb 24 when agreed (also the retest of 2, 3, 7).
