# Tests

Captured 2026-11-05 18:17 UTC from `https://<workspace>.cloud.databricks.com` by `deploy/capture_evidence.py`.

## Offline unit tests (`python -m pytest tests -v`)

```
============================= test session starts ==============================
platform darwin -- Python 3.14.5, pytest-9.2.0, pluggy-1.7.0 -- /private/tmp/frpg/bin/python
rootdir: /Users/<user>/fr2052a
plugins: anyio-4.15.1
collecting ... collected 62 items

tests/test_controls.py::test_validate_resolve_refuses_and_writes_nothing[body0-queue0-400] PASSED [  1%]
tests/test_controls.py::test_validate_resolve_refuses_and_writes_nothing[body1-queue1-404] PASSED [  3%]
tests/test_controls.py::test_validate_resolve_refuses_and_writes_nothing[body2-queue2-409] PASSED [  4%]
tests/test_controls.py::test_validate_resolve_refuses_and_writes_nothing[body3-queue3-400] PASSED [  6%]
tests/test_controls.py::test_validate_resolve_refuses_and_writes_nothing[body4-queue4-400] PASSED [  8%]
tests/test_controls.py::test_validate_resolve_refuses_and_writes_nothing[body5-queue5-409] PASSED [  9%]
tests/test_controls.py::test_validate_manual_with_its_correction_is_recorded PASSED [ 11%]
tests/test_controls.py::test_ai_decision_is_insert_only PASSED           [ 12%]
tests/test_controls.py::test_second_ai_decision_is_refused PASSED        [ 14%]
tests/test_controls.py::test_ai_decision_input[data0-400] PASSED         [ 16%]
tests/test_controls.py::test_ai_decision_input[data1-400] PASSED         [ 17%]
tests/test_controls.py::test_decision_claims_the_break_before_applying PASSED [ 19%]
tests/test_controls.py::test_two_checkers_at_once_only_one_decides PASSED [ 20%]
tests/test_controls.py::test_failed_apply_puts_the_break_back PASSED     [ 22%]
tests/test_controls.py::test_decision_input[data0-brk0-400] PASSED       [ 24%]
tests/test_controls.py::test_decision_input[data1-brk1-400] PASSED       [ 25%]
tests/test_controls.py::test_decision_input[data2-brk2-409] PASSED       [ 27%]
tests/test_controls.py::test_identifiers_are_whitelisted PASSED          [ 29%]
tests/test_controls.py::test_only_the_agents_use_the_straight_through_code PASSED [ 30%]
tests/test_controls.py::test_straight_through_applies_only_qualifying_proposals PASSED [ 32%]
tests/test_controls.py::test_spot_check_refuses[decisions0-data0-checker@bank.com-409] PASSED [ 33%]
tests/test_controls.py::test_spot_check_refuses[decisions1-data1-checker@bank.com-409] PASSED [ 35%]
tests/test_controls.py::test_spot_check_refuses[decisions2-data2-checker@bank.com-400] PASSED [ 37%]
tests/test_controls.py::test_spot_check_refuses[decisions3-data3-checker@bank.com-400] PASSED [ 38%]
tests/test_controls.py::test_spot_check_refuses[decisions4-data4-fr2052a agents (straight-through)-403] PASSED [ 40%]
tests/test_controls.py::test_spot_check_is_recorded PASSED               [ 41%]
tests/test_controls.py::test_feedback_goes_on_the_trace_before_the_decision PASSED [ 43%]
tests/test_controls.py::test_resend_only_a_short_position_feed[funding-PASS-409] PASSED [ 45%]
tests/test_controls.py::test_resend_only_a_short_position_feed[comments-FAIL-404] PASSED [ 46%]
tests/test_controls.py::test_resend_only_a_short_position_feed[nosuch-FAIL-404] PASSED [ 48%]
tests/test_controls.py::test_resend_reruns_the_day_with_the_feed PASSED  [ 50%]
tests/test_rules.py::test_primary_due_is_t_plus_2_business_days[2026-02-27-2026-03-03] PASSED [ 51%]
tests/test_rules.py::test_primary_due_is_t_plus_2_business_days[2026-02-24-2026-02-26] PASSED [ 53%]
tests/test_rules.py::test_primary_due_is_t_plus_2_business_days[2026-02-12-2026-02-17] PASSED [ 54%]
tests/test_rules.py::test_primary_due_is_t_plus_2_business_days[2026-12-23-2026-12-28] PASSED [ 56%]
tests/test_rules.py::test_reduced_due_is_t_plus_15_calendar_days PASSED  [ 58%]
tests/test_rules.py::test_source_fix_due_dates_skip_fed_holidays PASSED  [ 59%]
tests/test_rules.py::test_check_dates_refuses[path0-query0-400] PASSED   [ 61%]
tests/test_rules.py::test_check_dates_refuses[path1-query1-400] PASSED   [ 62%]
tests/test_rules.py::test_check_dates_refuses[path2-query2-404] PASSED   [ 64%]
tests/test_rules.py::test_check_dates_refuses[path3-query3-404] PASSED   [ 66%]
tests/test_rules.py::test_check_dates_refuses[path4-query4-400] PASSED   [ 67%]
tests/test_rules.py::test_check_dates_accepts_a_reporting_date_and_routes_without_dates PASSED [ 69%]
tests/test_rules.py::test_workbench_check_date_is_a_400_not_a_500 PASSED [ 70%]
tests/test_rules.py::test_pipeline_run_only_for_reporting_dates PASSED   [ 72%]
tests/test_rules.py::test_submitted_only_from_approved_and_final PASSED  [ 74%]
tests/test_rules.py::test_approval_only_from_ready_or_override PASSED    [ 75%]
tests/test_rules.py::test_review_submission_input[data0-400] PASSED      [ 77%]
tests/test_rules.py::test_review_submission_input[data1-400] PASSED      [ 79%]
tests/test_rules.py::test_review_submission_input[data2-400] PASSED      [ 80%]
tests/test_rules.py::test_generate_waits_for_steps_1_to_4 PASSED         [ 82%]
tests/test_rules.py::test_plural[1-approved fix-1 approved fix] PASSED   [ 83%]
tests/test_rules.py::test_plural[2-approved fix-2 approved fixes] PASSED [ 85%]
tests/test_rules.py::test_plural[0-comment-0 comments] PASSED            [ 87%]
tests/test_rules.py::test_plural[3-exception-3 exceptions] PASSED        [ 88%]
tests/test_rules.py::test_plural[2-class-2 classes] PASSED               [ 90%]
tests/test_static.py::test_every_frontend_call_has_a_backend_route PASSED [ 91%]
tests/test_static.py::test_sql_sent_to_lakebase_is_postgres PASSED       [ 93%]
tests/test_static.py::test_no_backslash_in_fstring_expressions PASSED    [ 95%]
tests/test_static.py::test_wording_rules PASSED                          [ 96%]
tests/test_static.py::test_audit_tables_are_append_only_in_notebook_07 PASSED [ 98%]
tests/test_static.py::test_app_never_updates_or_deletes_the_audit_trail PASSED [100%]

============================== 62 passed in 1.96s ==============================

```

## Live QA suite (`scripts/qa/e2e_qa.py`) - full results in [qa_report.md](qa_report.md)

# FR 2052a end-to-end QA - 2026-11-04 18:09

68 test cases: PASS 63, WARN 5


## User acceptance test of the write paths - see [uat_2026-02-24.md](uat_2026-02-24.md)
