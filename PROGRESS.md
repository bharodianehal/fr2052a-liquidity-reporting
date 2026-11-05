# PROGRESS - FR 2052a + LCR

## Where it stands (2026-11-05) - done

- Built and running end to end: Lakeflow ingest -> DQ -> PID enrichment -> LCR -> FR 2052a report -> validation + 6G XML -> Lakebase ->
  AI agents (MLflow model on Model Serving, traces + checker feedback, GenAI evaluation) -> Genie Agent (embedded) -> Databricks App.
- Deployed with two Databricks Asset Bundles that hold every asset: the platform bundle (schemas, volumes, Lakeflow pipeline, jobs,
  Lakebase project / endpoint / database, secret scope, Vector Search endpoint, dashboards) and the app bundle (the app, Genie space,
  Vector Search index, agents' serving endpoint and Lakebase role). Bundle jobs create what is not a resource type: the agents' service
  principal and OAuth secret, the Lakebase synced tables, the regulatory text, the Genie One skills. The existing workspace objects
  are bound to the bundles; `bundle plan` shows no changes. Runbook: README "Deploy to a new workspace" (not tested on a fresh
  workspace, by choice).
- Verified by a full rebuild and the demo reset: live QA 63 pass / 5 accepted warnings / 0 fail, 62 unit tests pass, app endpoints
  return 200; evidence re-captured (`evidence/`).
- Demo dates Feb 23-27, 2026: every date has work at each step (a short feed, quarantined records, a record with no PID rule and new
  customers / product codes, check exceptions and comments). Demo-only controls: the send icon in the header (the source re-sends a
  short feed) and the faint "reset" link in the sidebar (job `fr2052a-demo-reset`, about 45-60 minutes; one day re-runs in about 40).
- The repo and the workspace hold only what is in use. Agents model versions with traces / proposals stay (audit lineage).
- Evidence for the submission: `evidence/` (text) and `dashboards/`; `main` = the full build. Re-captured 2026-11-05 after the bundle
  changes: notebooks 07, 08, 12, 16 and the bundle-only tasks (agents_identity, regulatory_text, genie_skills) from runs of the current code;
  repaired runs carry their cause; personal e-mail addresses are masked (userN@example.com) by `capture_evidence.py`.
- In git so a clone deploys as is: the Fed's two 6G XSDs (`schema_6g/`) and the built frontend (`app/static/`, rebuild after a frontend change).

## Open

- Published as a public repository (single scrubbed snapshot, no workspace values, ids or personal data); submit that link.
- Not done by choice: production sizing, regulatory gaps (NSFR, SB $1.5M, 6:30 pm FX), bank inputs, masking
  `source_position.internal_rating`, the serving endpoint cold start (~80 s), a visual walk-through of every screen, a deploy to a
  fresh workspace.
- Known data quirk: passage id `INS-I.A.2` appears twice in `reference_data/regtext/reg_text_chunks.jsonl` (the index keeps one).
- Possible: speed up a day's run (PID derivation ~12 min, validation ~7 min, Lakebase sync ~6 min).
