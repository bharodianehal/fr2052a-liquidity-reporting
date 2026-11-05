"""MLflow Tracing for the AI agents (the maker) and the checker's decisions as human feedback.

Used by notebook 15 (the agents run in the pipeline) and notebook 10 (evaluation); the app does not import it.
Traces go to the experiment fr2052a_agents, bound to Unity Catalog trace tables in <catalog>.ai_assist.

  instrument(agents, wb)            one trace per proposal: the agent (root), the AI call, the regulatory search, the LCR effect
  log_checker_feedback(m, date, x)  each checker decision (approve / edit / return, on the step page or by the re-run) on its trace
"""
import datetime
import functools
import json
import os
import time

import mlflow
from mlflow.entities import AssessmentSource, SpanType
from mlflow.entities.trace_location import UnityCatalog

EXPERIMENT = "/Users/{user}/fr2052a_agents"
MODEL = {}   # the registered model version making the proposals (set by notebook 15)
MAKERS = {"_make_dq": "data quality", "_make_master": "master data", "_make_validation": "validation", "_make_comment": "comment for the Fed",
          "_make_feed": "feed"}


def setup(user, catalog, warehouse_id):
    """Point MLflow at the agents' experiment (Unity Catalog trace storage in <catalog>.ai_assist); returns the experiment id."""
    os.environ["MLFLOW_TRACING_SQL_WAREHOUSE_ID"] = warehouse_id
    mlflow.set_tracking_uri("databricks")
    exp = mlflow.set_experiment(experiment_name=EXPERIMENT.format(user=user),
                                trace_location=UnityCatalog(catalog_name=catalog, schema_name="ai_assist"))
    return exp.experiment_id


def _short(v, n=2000):
    s = v if isinstance(v, str) else json.dumps(v, default=str)
    return s[:n]


def instrument(agents, wb):
    """Wrap the agents' functions in MLflow spans (module attributes, so every call made by agents._run is traced)."""
    def maker(name, fn):
        @functools.wraps(fn)
        def run(m, date, item):
            ref = item.get("record_id") or item.get("id") or item.get("suggestion_id") or item.get("feed") or f"{item.get('rule_id')}|{item.get('item_key')}"
            with mlflow.start_span(name=f"agent: {MAKERS[name]}", span_type=SpanType.AGENT) as span:
                span.set_inputs({"as_of_date": date, "item": _short({k: v for k, v in item.items() if k != "decision"})})
                out = fn(m, date, item)
                span.set_outputs({"break_type": out.get("break_type"), "proposal": out.get("summary"), "fields": out.get("fields"),
                                  "confidence": out.get("confidence"), "rule_check": out.get("rule_check"), "impact": out.get("impact"),
                                  "action": {k: v for k, v in (out.get("action") or {}).items() if k != "ai"}})
                mlflow.update_current_trace(tags={
                    "fr2052a.as_of_date": date, "fr2052a.source_kind": out.get("source_kind", ""), "fr2052a.source_ref": str(out.get("source_ref") or ref)[:400],
                    "fr2052a.break_type": out.get("break_type", ""), "fr2052a.agent": out.get("agent", ""),
                    "fr2052a.agent_version": agents.VERSIONS.get(out.get("agent"), ""), "fr2052a.model": agents.MODEL,
                    "fr2052a.rule_check": str((out.get("rule_check") or {}).get("status")),
                    "fr2052a.agents_model": MODEL.get("name", ""), "fr2052a.agents_model_version": MODEL.get("version", "")})
                return out
        return run

    def span(fn, name, kind, inputs):
        @functools.wraps(fn)
        def run(*a, **k):
            with mlflow.start_span(name=name, span_type=kind) as s:
                s.set_inputs(inputs(*a, **k))
                out = fn(*a, **k)
                s.set_outputs(out if isinstance(out, (dict, list, str)) else _short(out))
                return out
        return run

    for name in MAKERS:
        setattr(agents, name, maker(name, getattr(agents, name)))
    wb._ai_text = span(wb._ai_text, "llm: foundation model", SpanType.LLM, lambda m, prompt, tokens=900: {"model": wb.AI_MODEL, "prompt": _short(prompt, 6000), "max_tokens": tokens})
    agents._vs = span(agents._vs, "retrieve: FR 2052a Instructions / 12 CFR 249 (Vector Search)", SpanType.RETRIEVER,
                      lambda m, query, k=3, doc=None: {"query": query[:500], "k": k, "doc": doc})
    agents._instructions = span(agents._instructions, "retrieve: PID definitions", SpanType.RETRIEVER, lambda m, pids: {"pids": list(pids)})
    agents._cfr_for_rule = span(agents._cfr_for_rule, "retrieve: 12 CFR 249 paragraph", SpanType.RETRIEVER, lambda m, rule_id: {"rule_id": rule_id})
    agents._impact = span(agents._impact, "tool: exact LCR effect", SpanType.TOOL,
                          lambda m, date, d_out=0.0, d_in=0.0, basis="", rule=None: {"date": date, "d_outflows": d_out, "d_inflows": d_in, "rule": rule})


DECISION = {"APPROVE": "approved", "APPROVE_WITH_EDIT": "edited", "RETURN": "returned"}


def log_checker_feedback(m, date, experiment_id):
    """The checker's decision on each proposal of the day, as human feedback on the proposal's trace (once per decision)."""
    since = int((time.time() - 45 * 86400) * 1000)
    traces = mlflow.search_traces(locations=[experiment_id], return_type="list", include_spans=False, max_results=2000,
                                  filter_string=f"trace.timestamp_ms >= {since}")
    by_ref = {}
    for t in traces:
        tags = t.info.tags or {}
        if tags.get("fr2052a.as_of_date") != date:
            continue
        by_ref.setdefault((tags.get("fr2052a.source_kind"), tags.get("fr2052a.source_ref")), []).append(t)
    rows = m.run_pg("""SELECT b.source_kind, b.source_ref, d.decision_id, d.action, d.reason_code, d.note, d.decided_by, d.edits, d.decided_at
                       FROM breaks b JOIN break_decisions d ON d.break_id = b.break_id WHERE b.as_of_date = %s ORDER BY d.decided_at""", (date,))
    logged = 0
    for r in rows:
        # the decision belongs to the proposal the checker saw: the item's latest trace made BEFORE the decision (a return is feedback on
        # the proposal it returned, not on the one the agent made afterwards)
        ts = r["decided_at"]
        at = int((ts if ts.tzinfo else ts.replace(tzinfo=datetime.timezone.utc)).timestamp() * 1000) if hasattr(ts, "timestamp") else None   # Lakebase NOW() is UTC
        t = max((x for x in by_ref.get((r["source_kind"], r["source_ref"]), []) if at is None or x.info.request_time <= at),
                key=lambda x: x.info.request_time, default=None)
        if not t or any((a.metadata or {}).get("decision_id") == r["decision_id"] for a in (t.info.assessments or [])):
            continue
        how = "resolved_by_rerun" if r["reason_code"] == "RERUN" else "decided_on_step_page" if r["reason_code"] == "STEP" else DECISION.get(r["action"], r["action"].lower())
        mlflow.log_feedback(trace_id=t.info.trace_id, name="checker_decision", value=how,
                            rationale=f"{r['reason_code']} {r['note'] or ''}".strip(),
                            source=AssessmentSource(source_type="HUMAN", source_id=r["decided_by"] or "checker"),
                            metadata={"decision_id": r["decision_id"], "edits": json.dumps(r["edits"], default=str) if r["edits"] else ""})
        logged += 1
    return {"traces": sum(len(v) for v in by_ref.values()), "decisions": len(rows), "feedback_logged": logged}
