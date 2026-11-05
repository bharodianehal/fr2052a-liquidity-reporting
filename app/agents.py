"""AI maker, human checker. The agents find every break of the day, make the change (a complete proposal: what changes, how sure,
an independent rule check, the LCR effect, the sources, the trace of how they got there, the source fix for the data owner),
and a person checks it - approves, approves with an edit, or returns it with a reason. Approving applies the change through the
same paths the step pages use, so the next re-run puts it in the report.

Lakebase tables (app-owned): breaks, proposals, break_decisions, agent_events, agent_runs.
"""
import datetime
import os
import json
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import uuid

from fastapi import APIRouter, HTTPException, Request

import workbench as wb

router = APIRouter(prefix="/api/wb/agents")

MODEL = "databricks-claude-sonnet-4-6"
VERSIONS = {"Classifier": "classifier v1.0", "Rule agent": "rule agent v1.0", "Liquidity impact agent": "impact agent v1.0",
            "Source-fix agent": "source-fix agent v1.0", "Feed monitor": "feed monitor v1.0", "Tie-out agent": "tie-out agent v1.0"}
REVIEW_THRESHOLD_USD_MM = 25.0          # a change moving net cash outflows by more than this is flagged for senior review
AUTO_CONFIDENCE = 0.95                  # bulk approval: only proposals at or above this, with the rule agent agreeing
REASON_CODES = {
    "approve": [("RC-01", "Data corrected - the record was wrong"), ("RC-02", "Instruction requires a different product / field"),
                ("RC-03", "Counterparty type per the customer master"), ("RC-04", "Maturity convention (business day)"),
                ("RC-05", "Explained - the data is right"), ("RC-06", "New product code mapped"), ("RC-07", "New customer classified"),
                ("RC-08", "Excluded - cannot be fixed from the data")],
    "return": [("RT-01", "Evidence does not support the proposal"), ("RT-02", "Wrong value proposed"), ("RT-03", "Needs the data owner first"),
               ("RT-04", "Re-check against the Instructions")],
}
DATA_OWNER = {"deposits": "Deposit data owner", "loans": "Loan data owner", "securities": "Securities data owner", "derivatives": "Derivatives data owner",
              "funding": "Funding data owner", "finance": "Finance data owner", "gl": "Controllership (GL)"}
CHECKER = "Liquidity reporting analyst"
# Straight-through processing: a proposal with confidence >= AUTO_CONFIDENCE, the rule agent agreeing and no material LCR effect (bulk_ok)
# is applied by the agents themselves and listed for the checker to spot-check (confirm / disagree) - no click needed to settle it.
AGENT_ACTOR = "fr2052a agents (straight-through)"
STP_CODE = "STP"
_RUNS = {}


# ─── small helpers ─────
def _now():
    return datetime.datetime.utcnow()


def _bdays(date, n):
    """n business days after date (weekends and Federal Reserve holidays, as the filing's due dates)."""
    d = datetime.date.fromisoformat(str(date))
    while n:
        d += datetime.timedelta(days=1)
        if wb._deps().is_business_day(d):
            n -= 1
    return d


def plural(n, word):
    """'1 approved fix', '2 approved fixes', '3 comments'."""
    return f"{n} {word}" if n == 1 else f"{n} {word}{'es' if word.endswith(('x', 's', 'ch', 'sh')) else 's'}"


def _event(m, date, actor_type, actor, action, subject, why="", evidence="", version=""):
    with m.get_pg() as conn:
        with conn.cursor() as c:
            c.execute("INSERT INTO agent_events VALUES (%s, %s, NOW(), %s, %s, %s, %s, %s, %s, %s)",
                      (str(uuid.uuid4())[:12], date, actor_type, actor, action[:500], subject[:200], why[:500], evidence[:500], version))
        conn.commit()


def _sql_str(v):
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


class Trace:
    """How the agents got here: each step, by which agent, what it found, how long it took."""
    def __init__(self):
        self.steps, self.t = [], time.time()

    def add(self, agent, step, detail, status="ok"):
        now = time.time()
        self.steps.append({"agent": agent, "step": step, "detail": str(detail)[:400], "status": status, "seconds": round(now - self.t, 1)})
        self.t = now


# ─── the liquidity impact agent: exact before / after of the LCR (consolidated) for a pending change ─────
def _lcr_row(m, date, entity="ENT001"):
    r = m.run_pg("SELECT * FROM calculation_results WHERE as_of_date = %s AND entity_id = %s ORDER BY calculation_timestamp DESC LIMIT 1", (date, entity))
    return r[0] if r else None


def _comparable_rate(m, date, where):
    """The LCR rate positions like this one got today (same bank product code or standard product type), from the engine's detail."""
    C = m.CATALOG
    r = m.run_sql(f"""SELECT d.flow_direction, d.rule_id, FIRST(d.rule_name) AS rule_name, SUM(d.weighted_amount_usd) / NULLIF(SUM(d.amount_usd), 0) AS rate,
                             COUNT(*) AS n
                      FROM {C}.reg_lcr.calculation_detail d JOIN {C}.conformed.fact_liquidity_position f ON f.as_of_date = d.as_of_date AND f.position_id = d.record_id
                      WHERE d.as_of_date = '{date}' AND d.entity_id = 'ENT001' AND d.flow_direction IN ('INFLOW', 'OUTFLOW') AND {where}
                      GROUP BY 1, 2 ORDER BY SUM(d.amount_usd) DESC LIMIT 1""")
    return r[0] if r else None


def _impact(m, date, d_out=0.0, d_in=0.0, basis="", rule=None):
    """Price a change in outflows / inflows (USD mm, weighted) as its effect on the consolidated LCR."""
    r = _lcr_row(m, date)
    if not r:
        return {"priced": False, "basis": "No LCR for this day"}
    f = lambda k: float(r.get(k) or 0)
    h, out, inf, add, adj = f("total_hqla"), f("total_outflows"), f("total_inflows"), f("maturity_mismatch_add_on"), f("outflow_adjustment_pct") or 1
    nco = lambda o, i: adj * (o - min(i, 0.75 * o) + add)
    n0, n1 = nco(out, inf), nco(out + d_out, inf + d_in)
    return {"priced": True, "entity": "ENT001", "nco_before": round(n0, 1), "nco_after": round(n1, 1), "nco_change": round(n1 - n0, 1),
            "lcr_before": round(h / n0, 4) if n0 else None, "lcr_after": round(h / n1, 4) if n1 else None,
            "outflow_change": round(d_out, 1), "inflow_change": round(d_in, 1), "basis": basis, "rule": rule,
            "review": abs(n1 - n0) > REVIEW_THRESHOLD_USD_MM, "threshold": REVIEW_THRESHOLD_USD_MM}


# ─── evidence: the FR 2052a Instructions and 12 CFR 249 passages behind a proposal (reference.reg_text_chunks + Vector Search) ─────
VS_INDEX = "reference.reg_text_index"


def _vs(m, query, k=3, doc=None):
    """Semantic search over the regulatory text: the Databricks Vector Search query API (falls back to SQL vector_search on the warehouse)."""
    try:
        r = m.get_ws().api_client.do("POST", f"/api/2.0/vector-search/indexes/{m.CATALOG}.{VS_INDEX}/query", body={
            "query_text": query[:500], "columns": ["chunk_id", "doc", "section", "pid", "page", "text"], "num_results": k * 3})
        cols = [c["name"] for c in r["manifest"]["columns"]]
        rows = [dict(zip(cols, x)) for x in r.get("result", {}).get("data_array", [])]
        for x in rows:
            x["search_score"] = x.pop("score", None)
    except Exception as e:
        print(f"[vs] query API failed, using SQL vector_search: {str(e)[:160]}")
        try:
            rows = m.run_sql(f"""SELECT chunk_id, doc, section, pid, page, text, search_score FROM vector_search(index => '{m.CATALOG}.{VS_INDEX}',
                                 query_text => {_sql_str(query[:500])}, num_results => {k * 3})""")
        except Exception:
            return []
    return [r for r in rows if not doc or str(r["doc"]).startswith(doc)][:k]


def _instructions(m, pids):
    """The FR 2052a Instructions definition of each product (PID) - looked up exactly, not searched."""
    pids = [p for p in dict.fromkeys(pids) if p]
    if not pids:
        return []
    return m.run_sql(f"""SELECT chunk_id, doc, section, pid, page, text FROM {m.CATALOG}.reference.reg_text_chunks
                         WHERE chunk_id IN ({",".join(_sql_str("INS-" + p) for p in pids)})""")


def _cfr_for_rule(m, rule_id):
    """The 12 CFR 249 paragraph behind an LCR rule (its section, e.g. 32(h)(1) -> the 249.32 passage that holds paragraph (h))."""
    import re
    if not rule_id:
        return []
    r = m.run_pg("SELECT rule_section, rule_name FROM rules_lcr_appendix_vi WHERE rule_id = %s", (rule_id,))
    mm = re.match(r"(\d+)\(?([a-z])?", (r[0]["rule_section"] if r else "") or "")
    if not mm:
        return []
    sec, para = mm.group(1), mm.group(2)
    rows = m.run_sql(f"""SELECT chunk_id, doc, section, pid, page, text FROM {m.CATALOG}.reference.reg_text_chunks
                         WHERE doc LIKE '12 CFR%' AND section LIKE '§ 249.{sec} %' ORDER BY chunk_id""")
    hit = [x for x in rows if para and f"({para})" in x["text"][:400]] or [x for x in rows if para and f"({para})" in x["text"]] or rows[:1]
    return hit[:1]


def _add_evidence(m, p, pids=(), query=None, trace=None):
    """Append the regulatory passages to a proposal's sources: the product definitions, the LCR paragraph, and the closest passages."""
    n = max([s["n"] for s in p["sources"]] or [0])
    seen = set()
    def add(rows, why):
        nonlocal n
        out = []
        for r in rows:
            if r["chunk_id"] in seen:
                continue
            seen.add(r["chunk_id"]); n += 1
            title = (f"FR 2052a Instructions - {r['section']}" if r["doc"].startswith("FR 2052a") else r["section"])
            p["sources"].append({"n": n, "title": title, "system": r["doc"] + (f", page {r['page']}" if r.get("page") else "") + f" - {why}",
                                 "ref": r["chunk_id"], "passage": r["text"][:2500]})
            out.append(n)
        return out
    ins = add(_instructions(m, pids), "product definition")
    cfr = add(_cfr_for_rule(m, (p.get("impact") or {}).get("rule")), "LCR rate")
    sim = add(_vs(m, query or p["title"], 2), "closest passage (Vector Search)") if (query or p.get("title")) else []
    if p["fields"]:
        p["fields"][0]["cites"] = list(dict.fromkeys((p["fields"][0].get("cites") or []) + ins[:2] + cfr[:1]))
    if trace is not None:
        trace.add("Classifier", "read the regulation", f"{len(ins)} product definition(s) {', '.join(x for x in pids if x)}; "
                  f"{'12 CFR 249 passage for the LCR rate; ' if cfr else ''}{len(sim)} closest passage(s) by Vector Search")
    return p


# ─── the makers: one per kind of break ─────
def _fx(m, ccy):
    r = m.run_sql(f"SELECT rate_to_usd FROM {m.CATALOG}.reference.ref_fx_rates WHERE currency_code = {_sql_str(ccy)}")
    return float(r[0]["rate_to_usd"]) if r else 1.0


def _make_dq(m, date, item):
    """A quarantined record: the Classifier proposes the fix (field, product mapping or exclusion); the Rule agent re-runs the
    failed data quality rules on the proposed record; the impact agent prices the record entering the report."""
    C, tr = m.CATALOG, Trace()
    rid = item["record_id"]
    rec = wb.collect_record(date, rid)
    vals, feed = rec["values"], item["source_feed"]
    tr.add("Classifier", "read the source", f"{feed} record {rid} from {(rec.get('source') or {}).get('landing_file', '')}; failed {item['rules']}")
    ai = wb.dq_suggest(date, rid)
    conf = float(ai.get("confidence") or 0)
    tr.add("Classifier", "proposed", f"{ai.get('action')} {ai.get('field') or ''} -> {ai.get('new_value')} (confidence {conf:.2f}): {ai.get('rationale', '')}")
    rules = {r["rule_id"]: r for r in m.run_sql(f"SELECT rule_id, rule_name, rule_description, fail_predicate FROM {C}.reference.rules_dq")}
    failed = [r for r in item["rules"].split(", ") if r]
    # Rule agent - independent and deterministic: the same rule SQL the pipeline runs, on the record as proposed
    check = {"status": "n/a", "detail": "No data change to check"}
    if ai.get("action") == "fix_field" and ai.get("field"):
        fld, val = wb._safe_id(ai["field"]), ai.get("new_value")
        res = []
        for rid_ in failed:
            pred = (rules.get(rid_) or {}).get("fail_predicate")
            if not pred or "v_dq_staging" in pred:
                continue
            pred = pred.replace("{catalog}", C).replace("{as_of}", date)
            # the record as quarantined (dq.quarantine.record_json - the app has no Bronze access), with the proposed value
            row = {**{k: v for k, v in vals.items() if k.replace("_", "").isalnum()}, fld: val}
            cols = ", ".join(f"{_sql_str(v)} AS {wb._safe_id(k)}" for k, v in row.items())
            q = f"SELECT CASE WHEN ({pred}) THEN 'fails' ELSE 'passes' END AS r FROM (SELECT {cols})"
            try:
                res.append((rid_, m.run_sql(q)[0]["r"]))
            except Exception as e:
                res.append((rid_, f"not evaluated ({str(e)[:60]})"))
        ok = res and all(r == "passes" for _, r in res)
        check = {"status": "agrees" if ok else "break", "detail": "; ".join(f"{r} {v} with {fld} = {val}" for r, v in res) or "no rule to re-run"}
    elif ai.get("action") == "map_code":
        std = ai.get("new_value")
        pid = m.run_sql(f"""SELECT ARRAY_JOIN(COLLECT_SET(product_id), ', ') AS pids FROM {C}.reference.rules_pid_derivation WHERE standard_product_type = {_sql_str(std)}""")
        valid = m.run_sql(f"""SELECT COUNT(*) AS n FROM {C}.reference.ref_standard_product_type WHERE source_system = {_sql_str(vals.get('source_system'))}
                              AND standard_product_type = {_sql_str(std)}""")[0]["n"]
        ok = int(valid) > 0 and bool(pid and pid[0]["pids"])
        check = {"status": "agrees" if ok else "break",
                 "detail": f"{std} is {'a' if int(valid) else 'NOT a'} standard product type of {vals.get('source_system')}; PID rules for it lead to {pid[0]['pids'] if pid else 'none'}"}
    elif ai.get("action") == "exclude":
        check = {"status": "agrees" if conf >= 0.8 else "break", "detail": "Nothing in the record or the masters can make it pass; excluding keeps the report consistent"}
    tr.add("Rule agent", "checked independently", check["detail"], "ok" if check["status"] != "break" else "warn")
    # Liquidity impact: the record enters the report (or stays out)
    amt = float(vals.get("principal_amount") or vals.get("market_value") or 0) * _fx(m, vals.get("currency"))
    imp = {"priced": False, "basis": "The record stays out of the report - no LCR effect"}
    if ai.get("action") in ("fix_field", "map_code"):
        where = (f"f.standard_product_type = {_sql_str(ai.get('new_value'))}" if ai["action"] == "map_code"
                 else f"f.source_product_code = {_sql_str(vals.get('source_product_code'))}")
        cmp_ = _comparable_rate(m, date, where)
        if cmp_:
            w = amt * float(cmp_["rate"] or 0)
            imp = _impact(m, date, d_out=w if cmp_["flow_direction"] == "OUTFLOW" else 0, d_in=w if cmp_["flow_direction"] == "INFLOW" else 0,
                          basis=f"USD {amt:,.1f} mm enters the report at the {float(cmp_['rate'] or 0):.0%} rate positions like it get today ({cmp_['rule_id']} {cmp_['rule_name']})",
                          rule=cmp_["rule_id"])
    tr.add("Liquidity impact agent", "priced", imp.get("basis"), "warn" if imp.get("review") else "ok")
    fields = []
    if ai.get("action") == "fix_field":
        fields.append({"field": ai["field"], "now": vals.get(ai["field"]), "proposed": ai.get("new_value"), "cites": [1, 2]})
    elif ai.get("action") == "map_code":
        fields.append({"field": "standard product type of " + str(vals.get("source_product_code")), "now": "(not mapped)", "proposed": ai.get("new_value"), "cites": [1, 2]})
    else:
        fields.append({"field": "record", "now": "quarantined", "proposed": "excluded from the report", "cites": [2]})
    sources = [{"n": 1, "title": f"Source record {rid}", "system": f"{vals.get('source_system') or 'source system missing'} - {feed} feed",
                "ref": (rec.get("source") or {}).get("landing_file", ""), "passage": json.dumps({k: v for k, v in vals.items() if v not in (None, "")}, default=str)[:1200]}]
    for i, r in enumerate(failed):
        if r in rules:
            sources.append({"n": 2 + i, "title": f"Data quality rule {r} - {rules[r]['rule_name']}", "system": "reference.rules_dq",
                            "ref": r, "passage": f"{rules[r]['rule_description']} Fails when: {rules[r]['fail_predicate']}"})
    owner = DATA_OWNER.get(feed, "Data owner")
    fix = {"owner": owner, "due": str(_bdays(date, 5)),
           "text": (f"In {vals.get('source_system') or ai.get('new_value') or feed}, set {ai.get('field')} to {ai.get('new_value')} on record {rid}; the override retires on the first run after the source is fixed."
                    if ai.get("action") == "fix_field" else
                    f"Add product code {vals.get('source_product_code')} to the product catalogue as {ai.get('new_value')}; the mapping applies from the next run."
                    if ai.get("action") == "map_code" else f"Investigate record {rid} in the {feed} extract; it stays out of the report until it is corrected or withdrawn.")}
    action = {"kind": "dq", "record_id": rid,
              "action": {"fix_field": "accept_ai", "map_code": "map_code", "exclude": "exclude"}.get(ai.get("action"), None),
              "edits": {ai["field"]: ai.get("new_value")} if ai.get("action") == "fix_field" else None, "new_value": ai.get("new_value"),
              "ai": ai}   # the AI's suggestion as made - the step page shows it (no second AI call)
    title = f"{rid} failed {', '.join(failed)}: {item.get('rule_names', '')[:120]} - USD {amt:,.1f} mm kept out of the report"
    std = ai.get("new_value") if ai.get("action") == "map_code" else (m.run_sql(f"""SELECT FIRST(standard_product_type) AS s FROM {C}.reference.v_source_product_map
                                                                               WHERE source_product_code = {_sql_str(vals.get('source_product_code'))}""") or [{}])[0].get("s")
    pids = [r["product_id"] for r in m.run_sql(f"SELECT DISTINCT product_id FROM {C}.reference.rules_pid_derivation WHERE standard_product_type = {_sql_str(std)} LIMIT 2")] if std else []
    out = {"break_type": "Data quality break", "table_code": None, "amount_usd": amt, "title": title, "detail": ai.get("rationale", ""),
           "source_kind": "dq", "source_ref": rid, "confidence": conf, "summary": ai.get("rationale", ""), "fields": fields, "rule_check": check,
           "impact": imp, "sources": sources, "trace": None, "source_fix": fix, "action": action, "agent": "Classifier"}
    _add_evidence(m, out, pids, f"{item.get('rule_names', '')} {vals.get('source_product_code')} {std or ''}", tr)
    out["trace"] = tr.steps
    return out


def _make_master(m, date, item):
    """A new customer or product code the masters do not know: the Classifier's proposal (from ai_classify / ai_query in notebook 09),
    the Rule agent's check of the proposal against the FR 2052a counterparty requirements, and the effect of the held positions entering."""
    C, tr = m.CATALOG, Trace()
    is_cust = item["kind"] == "New customer"
    sug = item.get("suggestion") or {}
    conf = float(item.get("confidence") or 0)
    tr.add("Classifier", "read the source", f"{item['kind']} {item['key']}: {item.get('context') or item['title']}")
    tr.add("Classifier", "proposed", f"{json.dumps({k: v for k, v in sug.items() if v})} (confidence {conf:.2f}): {str(item.get('rationale') or '')[:200]}")
    held = m.run_pg("SELECT * FROM pid_exceptions WHERE as_of_date = %s AND " + ("customer_id = %s" if is_cust else "source_product_code = %s"), (date, item["key"]))
    amt = sum(float(h.get("amount_usd") or 0) for h in held)
    if is_cust:
        pids = sorted({h["provisional_product_id"] for h in held if h.get("provisional_product_id")})
        cp = sug.get("counterparty")
        allowed = m.run_sql(f"""SELECT product_id, applicability FROM {C}.reference.spec_counterparty_requirements
                                WHERE product_id IN ({','.join(_sql_str(p) for p in pids) or "''"}) AND counterparty = {_sql_str(cp)}""") if pids else []
        bad = [p for p in pids if not any(a["product_id"] == p and a["applicability"] == "Applicable" for a in allowed)]
        need = m.run_sql(f"SELECT DISTINCT product_id FROM {C}.reference.spec_counterparty_requirements WHERE product_id IN ({','.join(_sql_str(p) for p in pids) or chr(39)*2})") if pids else []
        bad = [p for p in bad if any(n["product_id"] == p for n in need)]   # products with no counterparty requirement accept any
        check = {"status": "break" if bad or not cp else "agrees",
                 "detail": f"Counterparty {cp} is {'NOT ' if bad else ''}allowed for {', '.join(pids) or 'its products'} under the FR 2052a field requirements"}
    else:
        std = sug.get("standard_product_type")
        pid = m.run_sql(f"SELECT ARRAY_JOIN(COLLECT_SET(product_id), ', ') AS p FROM {C}.reference.rules_pid_derivation WHERE standard_product_type = {_sql_str(std)}")
        check = {"status": "agrees" if pid and pid[0]["p"] else "break", "detail": f"Standard product type {std} has PID rules leading to {pid[0]['p'] if pid else 'none'}"}
    tr.add("Rule agent", "checked independently", check["detail"], "ok" if check["status"] == "agrees" else "warn")
    imp = {"priced": False, "basis": "No positions held out today"}
    if held:
        p0 = held[0]
        cmp_ = _comparable_rate(m, date, f"f.product_id = {_sql_str(p0.get('provisional_product_id'))}" +
                                (f" AND f.counterparty = {_sql_str(sug.get('counterparty'))}" if is_cust and sug.get("counterparty") else ""))
        cmp_ = cmp_ or _comparable_rate(m, date, f"f.product_id = {_sql_str(p0.get('provisional_product_id'))}")
        if cmp_:
            w = amt * float(cmp_["rate"] or 0)
            imp = _impact(m, date, d_out=w if cmp_["flow_direction"] == "OUTFLOW" else 0, d_in=w if cmp_["flow_direction"] == "INFLOW" else 0,
                          basis=f"{len(held)} held-out position(s), USD {amt:,.1f} mm, enter the report at {float(cmp_['rate'] or 0):.0%} ({cmp_['rule_id']} {cmp_['rule_name']})",
                          rule=cmp_["rule_id"])
    tr.add("Liquidity impact agent", "priced", imp.get("basis"), "warn" if imp.get("review") else "ok")
    fields = ([{"field": "counterparty", "now": "(not classified - held out)", "proposed": sug.get("counterparty"), "cites": [1, 2]},
               {"field": "G-SIB parent", "now": "", "proposed": sug.get("gsib_parent"), "cites": [1]}] if is_cust else
              [{"field": "standard product type", "now": "(not in the catalogue)", "proposed": sug.get("standard_product_type"), "cites": [1, 2]}])
    sources = [{"n": 1, "title": ("Customer onboarding record " if is_cust else "Bank product code ") + item["key"],
                "system": "raw.customers (onboarding feed)" if is_cust else "source product catalogue", "ref": item["key"], "passage": str(item.get("context") or item["title"])[:800]},
               {"n": 2, "title": "AI classification rationale", "system": "ai_assist.suggestions (notebook 09)", "ref": item["id"], "passage": str(item.get("rationale") or "")[:1200]}]
    fix = {"owner": "Customer data owner (KYC / onboarding)" if is_cust else "Product data owner",
           "due": str(_bdays(date, 5)), "text": (f"Complete the FR 2052a classification of customer {item['key']} in the customer master (counterparty {sug.get('counterparty')})."
                                                 if is_cust else f"Add product code {item['key']} to the product catalogue as {sug.get('standard_product_type')}.")}
    return _master_out(m, item, is_cust, held, amt, conf, fields, check, imp, sources, tr, fix, sug)


def _master_out(m, item, is_cust, held, amt, conf, fields, check, imp, sources, tr, fix, sug):
    pids = sorted({h.get("provisional_product_id") for h in held if h.get("provisional_product_id")})
    if not is_cust and sug.get("standard_product_type"):
        pids += [r["product_id"] for r in m.run_sql(f"SELECT DISTINCT product_id FROM {m.CATALOG}.reference.rules_pid_derivation WHERE standard_product_type = {_sql_str(sug['standard_product_type'])} LIMIT 2")]
    out = {"break_type": "New customer" if is_cust else "New product code", "table_code": (held[0].get("provisional_product_id") or "")[:3] if held else None,
           "amount_usd": amt, "title": f"{item['title']}: {item['problem']}", "detail": item.get("affects", ""), "source_kind": "ai", "source_ref": item["id"],
           "confidence": conf, "summary": str(item.get("rationale") or "")[:600], "fields": fields, "rule_check": check, "impact": imp, "sources": sources,
           "trace": None, "source_fix": fix, "agent": "Classifier", "action": {"kind": "ai_decide", "suggestion_id": item["id"], "edits": {k: v for k, v in sug.items() if v}}}
    _add_evidence(m, out, pids, f"{item['kind']} {item.get('context') or item['title']} counterparty {sug.get('counterparty') or ''}", tr)
    out["trace"] = tr.steps
    return out


def _make_validation(m, date, item):
    """A validation exception: the agent proposes a correction of the position (or an explanation); the Rule agent re-checks the rule's
    condition on the proposed value; the impact agent prices the change; a GL break is a tie-out break with the explanation drafted."""
    C, tr = m.CATALOG, Trace()
    gl = item["rule_id"] == "RECON-GL"
    tr.add("Tie-out agent" if gl else "Classifier", "read the exception", f"{item['rule_id']} {item['rule_name']}: {item['detail']}")
    ai = wb.validate_suggest(date, item["rule_id"], item["item_key"])
    conf = float(ai.get("confidence") or 0)
    tr.add("Classifier", "proposed", f"{ai.get('action')} {ai.get('field') or ''} {ai.get('old_value') or ''} -> {ai.get('new_value') or ''} (confidence {conf:.2f})")
    amt, imp, check = 0.0, {"priced": False, "basis": "No change to the data - no LCR effect"}, {"status": "n/a", "detail": "An explanation - nothing to re-check"}
    pos = None
    if item.get("position_id"):
        r = m.run_sql(f"""SELECT f.position_id, f.product_id, f.maturity_date, f.maturity_bucket, COALESCE(f.principal_amount, f.market_value) * COALESCE(fx.rate_to_usd, 1) AS usd
                          FROM {C}.conformed.fact_liquidity_position f LEFT JOIN {C}.reference.ref_fx_rates fx ON fx.currency_code = f.currency
                          WHERE f.as_of_date = '{date}' AND f.position_id = {_sql_str(item['position_id'])}""")
        pos = r[0] if r else None
        amt = float(pos["usd"] or 0) if pos else 0.0
    if ai.get("action") == "correct" and ai.get("field") == "maturity_date" and ai.get("new_value"):
        d = datetime.date.fromisoformat(str(ai["new_value"])[:10])
        import app as main
        hol = d in main.holidays()
        ok = main.is_business_day(d) and d >= datetime.date.fromisoformat(date)
        check = {"status": "agrees" if ok else "break",
                 "detail": (f"{d} is a {d.strftime('%A')} and not a Federal Reserve holiday - a business day on or after the as-of date; "
                            f"PSV-01 (no flow on a weekend or bank holiday) passes with it") if ok else
                           f"{d} is not a business day ({'a Federal Reserve holiday' if hol else d.strftime('%A')})"}
        days_old = (datetime.date.fromisoformat(str(pos["maturity_date"])[:10]) - datetime.date.fromisoformat(date)).days if pos and pos.get("maturity_date") else None
        days_new = (d - datetime.date.fromisoformat(date)).days
        if days_old is not None and (days_old <= 30) != (days_new <= 30):
            cmp_ = _comparable_rate(m, date, f"f.product_id = {_sql_str(pos['product_id'])}")
            w = amt * float((cmp_ or {}).get("rate") or 0) * (1 if days_new <= 30 else -1)
            imp = _impact(m, date, d_out=w if (cmp_ or {}).get("flow_direction") == "OUTFLOW" else 0, d_in=w if (cmp_ or {}).get("flow_direction") == "INFLOW" else 0,
                          basis=f"The flow moves {'into' if days_new <= 30 else 'out of'} the 30-day window")
        else:
            imp = {"priced": True, **_impact(m, date, basis=f"The flow stays {'inside' if days_new <= 30 else 'outside'} the 30-day window (day {days_old} -> day {days_new}): "
                                                            "no change to outflows; the maturity mismatch add-on is recomputed at the re-run")}
    elif ai.get("action") == "correct":
        check = {"status": "agrees" if conf >= 0.8 else "break", "detail": f"{ai.get('field')} -> {ai.get('new_value')}; the rule is re-evaluated by the re-validation"}
    if gl:
        import re
        mm = re.search(r"GL ([\d,\.]+) vs filing ([\d,\.]+)", item["detail"] or "")
        amt = abs(float(mm.group(1).replace(",", "")) - float(mm.group(2).replace(",", ""))) if mm else 0.0
    tr.add("Rule agent", "checked independently", check["detail"], "ok" if check["status"] != "break" else "warn")
    tr.add("Liquidity impact agent", "priced", imp.get("basis"), "warn" if imp.get("review") else "ok")
    rule = (m.run_pg("SELECT validation_rule FROM rules_validation WHERE rule_id = %s", (item["rule_id"],)) or [{}])[0].get("validation_rule")
    psv = (m.run_pg("SELECT * FROM rules_fed_psv WHERE check_id = %s", (item["rule_id"],)) or [{}])[0]
    sources = [{"n": 1, "title": f"{item['rule_id']} - {item['rule_name']}", "system": {"Fed PSV": "Federal Reserve post-submission check", "Reconciliation": "Reconciliation rule"}.get(item["rule_source"], item["rule_source"]),
                "ref": item["rule_id"], "passage": str(rule or psv.get("description") or psv.get("check_description") or item["rule_name"])[:1200]},
               {"n": 2, "title": "The exception", "system": "reg_2052a.gold_validation_detail", "ref": item["item_key"], "passage": str(item["detail"])[:800]}]
    if pos:
        sources.append({"n": 3, "title": f"Position {pos['position_id']}", "system": "conformed.fact_liquidity_position", "ref": pos["position_id"],
                        "passage": f"PID {pos['product_id']}, maturity {pos['maturity_date']} ({pos['maturity_bucket']}), USD {amt:,.1f} mm"})
    fields = ([{"field": ai.get("field"), "now": ai.get("old_value"), "proposed": ai.get("new_value"), "cites": [1, 3] if pos else [1]}] if ai.get("action") == "correct" else
              [{"field": "explanation", "now": item["detail"], "proposed": ai.get("explanation"), "cites": [1, 2]}])
    fix = {"owner": "Controllership (GL)" if gl else "Source system owner", "due": str(_bdays(date, 5)),
           "text": ("Post or explain the GL difference for this account group; the break closes when the next run ties within tolerance." if gl else
                    f"Apply the business-day convention at source for {item.get('position_id')} ({ai.get('field')} {ai.get('new_value')})." if ai.get("action") == "correct" else
                    "No source fix - the data is correct; the explanation is kept with the filing.")}
    action = ({"kind": "validate", "rule_id": item["rule_id"], "item_key": item["item_key"], "record_key": item.get("record_key"), "action": "accept_ai",
               "position_id": ai.get("position_id"), "field": ai.get("field"), "new_value": ai.get("new_value"), "note": ai.get("explanation")}
              if ai.get("action") == "correct" else
              {"kind": "validate", "rule_id": item["rule_id"], "item_key": item["item_key"], "action": "explain", "note": ai.get("explanation")})
    action["ai"] = ai   # the AI's suggestion as made - the step page shows it (no second AI call)
    out = {"break_type": "GL tie-out" if gl else ("Validation failure" if item["status"] == "FAIL" else "Validation warning"),
            "table_code": item.get("table_code"), "amount_usd": amt, "title": f"{item['rule_id']} {item['rule_name']}: {item['detail']}"[:300],
            "detail": ai.get("explanation", ""), "source_kind": "validate", "source_ref": f"{item['rule_id']}|{item['item_key']}"[:400], "confidence": conf,
            "summary": ai.get("explanation", ""), "fields": fields, "rule_check": check, "impact": imp, "sources": sources, "trace": tr.steps,
            "source_fix": fix, "action": action, "agent": "Tie-out agent" if gl else "Classifier"}
    out["trace"] = None
    _add_evidence(m, out, [pos["product_id"]] if pos else [item.get("product_id")], f"{item['rule_name']} {item['detail']}", tr)
    out["trace"] = tr.steps
    return out


TABLE_NAMES = None


def _table_names(m):
    global TABLE_NAMES
    if TABLE_NAMES is None:
        TABLE_NAMES = {r["table_code"]: r["table_name"] for r in m.run_sql(f"SELECT table_code, table_name FROM {m.CATALOG}.reference.spec_tables")}
    return TABLE_NAMES


def _make_comment(m, date, q):
    """A comment the AI drafted for the Fed (S.C comment or variance commentary): the Rule agent checks that it names the FR 2052a
    table correctly and fits the 6G comment, and that every number it quotes is in the day's variance facts."""
    import re
    tr = Trace()
    g = q["suggestion"] if isinstance(q["suggestion"], dict) else json.loads(q["suggestion"] or "{}")
    key = "comments" if q["suggestion_type"] == "COMMENT_DRAFT" else "commentary"
    text = str(g.get(key) or "")
    entity, code = (q["subject"].split(" ") + [""])[:2]
    names = _table_names(m)
    official = names.get(code, "")
    tr.add("Classifier", "drafted", f"{'S.C comment' if key == 'comments' else 'variance commentary'} for {q['subject']} ({len(text)} characters)")
    problems = []
    # a Supplemental table is not a flow: calling S.B or S.L "secured / unsecured lending / borrowing" (the I.S / O.S tables) names it wrongly
    mis = re.search(r"\b(un)?secured\s+(borrowing|lending|funding)\b", text, re.I)
    if code.startswith("S.") and "secured" not in official.lower() and mis:
        called = mis.group(0).lower()
        problems.append(f"it describes {code} as {called} - {code} is {official}")
    if key == "comments" and len(text) > 4000:
        problems.append("longer than the 6G comment allows")
    check = {"status": "break" if problems else "agrees",
             "detail": ("; ".join(problems) if problems else f"{code} is {official}; the comment names it correctly and fits the 6G Comment file")}
    tr.add("Rule agent", "checked independently", check["detail"], "warn" if problems else "ok")
    var = m.run_pg("""SELECT amount_usd, prior_amount_usd, change_pct, lower_usd, upper_usd FROM variance WHERE as_of_date = %s AND reporting_entity = %s
                      AND table_code = %s AND series_level = 'TABLE' LIMIT 1""", (date, entity, code))
    sources = [{"n": 1, "title": f"{code} - {official}", "system": "FR 2052a table (reference.spec_tables)", "ref": code, "passage": f"{code} is the {official} table."}]
    if var:
        v = var[0]
        sources.append({"n": 2, "title": f"Movement of {entity} {code}", "system": "reg_2052a.variance (ai_forecast expected range)", "ref": q["subject_key"],
                        "passage": f"Prior day USD {float(v['prior_amount_usd'] or 0):,.1f} mm, today USD {float(v['amount_usd'] or 0):,.1f} mm "
                                   f"({float(v['change_pct'] or 0):+.1f}%); expected range USD {float(v['lower_usd'] or 0):,.1f} - {float(v['upper_usd'] or 0):,.1f} mm."})
    out = {"break_type": "Comment for the Fed", "table_code": code or None, "amount_usd": abs(float((var[0]["amount_usd"] or 0) - (var[0]["prior_amount_usd"] or 0))) if var else 0,
           "title": f"{'S.C comment' if key == 'comments' else 'Variance commentary'} for {q['subject']}{' - check the table name' if problems else ''}",
           "detail": text[:300], "source_kind": "ai", "source_ref": q["suggestion_id"], "confidence": float(q.get("confidence") or 0.8),
           "summary": text, "fields": [{"field": "S.C comment" if key == "comments" else "variance commentary", "now": "(none)", "proposed": text, "cites": [1, 2] if var else [1]}],
           "rule_check": check, "impact": {"priced": False, "basis": "A comment - no LCR effect"}, "sources": sources, "trace": None,
           "source_fix": {"owner": "Liquidity reporting analyst", "due": str(_bdays(date, 1)), "text": "Accepted comments go into the next run's 6G Comment file."},
           "action": {"kind": "ai_decide", "suggestion_id": q["suggestion_id"], "edits": {}, "text_key": key}, "agent": "Classifier"}
    _add_evidence(m, out, [], f"{official} {text[:200]}", tr)
    out["trace"] = tr.steps
    return out


def _decided(kind, ref, item, by, what, when=None):
    """A break that was already decided on a step page - in the register as decided, so the audit trail shows the whole day."""
    return {"break_type": kind, "table_code": item.get("table_code"), "amount_usd": float(item.get("amount") or 0) if str(item.get("amount") or "").replace(".", "").isdigit() else 0,
            "title": item.get("title") or ref, "detail": what, "source_kind": item["source_kind"], "source_ref": ref, "confidence": None, "summary": what,
            "fields": [{"field": "decision", "now": "", "proposed": what, "cites": []}], "rule_check": {"status": "n/a", "detail": "Decided on the step page"},
            "impact": {"priced": False, "basis": "Decided on the step page"}, "sources": [], "trace": [{"agent": "Checker", "step": "decided on the step page", "detail": f"{by}: {what}", "status": "ok", "seconds": 0}],
            "source_fix": {}, "action": {"kind": "none"}, "agent": "Classifier", "decided": True, "decided_by": by}


def _make_feed(m, date, f):
    tr = Trace()
    tr.add("Feed monitor", "checked the feed", f"{f['feed']}: {f['records']} records vs expected {f.get('expected_records')} - {f.get('details')}", "warn")
    return {"break_type": "Feed incomplete", "table_code": None, "amount_usd": 0, "title": f"Feed {f['feed']} is incomplete: {f.get('details')}",
            "detail": "The tables the feed populates are provisional until it arrives complete.", "source_kind": "feed", "source_ref": f["feed"], "confidence": 1.0,
            "summary": "Ask the source system to re-send the feed; the day re-runs with the re-sent file.", "fields": [{"field": "feed", "now": f"{f['records']} records", "proposed": f"~{f.get('expected_records')} expected", "cites": [1]}],
            "rule_check": {"status": "n/a", "detail": "Completeness check against the 5-day median"}, "impact": {"priced": False, "basis": "Not priced - the missing records are unknown"},
            "sources": [{"n": 1, "title": f"Feed monitor - {f['feed']}", "system": "dq.feed_monitor", "ref": f["feed"], "passage": str(f.get("details"))}],
            "trace": tr.steps, "source_fix": {"owner": DATA_OWNER.get(f["feed"], "Data owner"), "due": str(_bdays(date, 1)), "text": f"Re-send the complete {f['feed']} extract for {date}."},
            "action": {"kind": "none"}, "agent": "Feed monitor"}


# ─── the run: find the breaks of the day and make a proposal for each ─────
def _save(m, date, run_id, p, version=1, break_id=None):
    """Store (or re-propose) one break and its proposal; log the agents' events."""
    with m.get_pg() as conn:
        with conn.cursor() as c:
            if not break_id:
                c.execute("SELECT COUNT(*) FROM breaks WHERE as_of_date = %s", (date,))
                break_id = f"BRK-{date[5:7]}{date[8:10]}-{c.fetchone()[0] + 1:03d}"
                c.execute("""INSERT INTO breaks VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                             ON CONFLICT (as_of_date, source_kind, source_ref) DO NOTHING""",
                          (break_id, date, p["break_type"], p["table_code"], p["amount_usd"], p["title"][:500], (p["detail"] or "")[:1000], CHECKER,
                           datetime.datetime.combine(datetime.date.fromisoformat(str(wb._deps()._due_dates(date)["primary"])), datetime.time(12)),
                           "APPROVED" if p.get("decided") else "PROPOSED", p["source_kind"], p["source_ref"], run_id))
                if p.get("decided"):
                    c.execute("INSERT INTO break_decisions VALUES (%s, %s, %s, 'APPROVE', 'STEP', %s, NULL, %s, NOW())",
                              (str(uuid.uuid4())[:12], break_id, f"PR-{break_id[4:]}-v1", p["summary"][:1000], p["decided_by"] or "checker"))
            else:
                c.execute("UPDATE breaks SET status = 'PROPOSED', updated_at = NOW(), amount_usd = %s WHERE break_id = %s", (p["amount_usd"], break_id))
            pid = f"PR-{break_id[4:]}-v{version}"
            c.execute("""INSERT INTO proposals VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()) ON CONFLICT (proposal_id) DO NOTHING""",
                      (pid, break_id, version, p["agent"], p.get("model") or MODEL, p["confidence"], (p["summary"] or "")[:1000], json.dumps(p["fields"], default=str),
                       json.dumps(p["rule_check"], default=str), json.dumps(p["impact"], default=str), json.dumps(p["sources"], default=str),
                       json.dumps(p["trace"], default=str), json.dumps(p["source_fix"], default=str), json.dumps(p["action"], default=str)))
        conn.commit()
    if not p.get("decided"):
        for s in p["trace"]:
            _event(m, date, "AI", s["agent"], f"{s['step']}: {s['detail']}", break_id, why=p["break_type"],
                   evidence=", ".join(x["ref"] for x in p["sources"][:3]), version=VERSIONS.get(s["agent"], ""))
    return break_id


def propose(kind, date, item):
    """The maker: one open item of the day -> its proposal (the AI fix, the rule check, the LCR effect, the sources, the trace).
    This is what the registered MLflow model fr2052a_agents serves (app/agents_model.py)."""
    m = wb._deps()
    return {"feed": _make_feed, "dq": _make_dq, "master": _make_master, "validation": _make_validation, "comment": _make_comment}[kind](m, date, item)


# Who makes the proposals in _run: by default this module; notebook 15 points it at the registered MLflow model (models:/...@champion).
PROPOSE = propose


def _run(date, run_id, user):
    m = wb._deps()
    done, errors = [], []
    existing = {(r["source_kind"], r["source_ref"]) for r in m.run_pg("SELECT source_kind, source_ref FROM breaks WHERE as_of_date = %s", (date,))}
    work = []
    for f in m.run_pg("SELECT * FROM feed_monitor WHERE as_of_date = %s AND status <> 'PASS'", (date,)):
        work.append(("feed", f["feed"], lambda f=f: PROPOSE("feed", date, f)))
    dq = [r for r in wb.dq_queue(date) if r["state"] == "open"]
    dq_codes = {r.get("source_product_code") for r in dq}
    for r in dq:
        work.append(("dq", r["record_id"], lambda r=r: PROPOSE("dq", date, r)))
    for q in wb.enrich_queue(date):
        if q["status"] == "PROPOSED" and q["kind"] in ("New customer", "New product code") and not (q["kind"] == "New product code" and q["key"] in dq_codes):
            work.append(("ai", q["id"], lambda q=q: PROPOSE("master", date, q)))
    for v in wb.validate_queue(date):
        ref = f"{v['rule_id']}|{v['item_key']}"[:400]
        if v["state"] == "open":
            work.append(("validate", ref, lambda v=v: PROPOSE("validation", date, v)))
        else:
            d = v.get("decision") or {}
            work.append(("validate", ref, lambda v=v, d=d, ref=ref: _decided("GL tie-out" if v["rule_id"] == "RECON-GL" else "Validation warning" if v["status"] == "WARNING" else "Validation failure",
                ref, {"source_kind": "validate", "table_code": v.get("table_code"), "title": f"{v['rule_id']} {v['rule_name']}: {v['detail']}"[:300]},
                d.get("decided_by") or "checker", f"{v['state']} - {d.get('note') or ''}"[:300])))
    queued = {r["record_id"] for r in wb.dq_queue(date)}
    for f in m.run_pg("""SELECT DISTINCT ON (record_id) record_id, field, new_value, status, preparer, reason FROM dq_fixes
                         WHERE as_of_date = %s AND status IN ('APPLIED', 'DECIDED', 'RETIRED') ORDER BY record_id, created_at DESC""", (date,)):
        if f["record_id"] not in queued:   # fixed and back in the report: the record no longer fails, so it is not in the queue
            what = ("excluded" if f["field"] == "_exclude" else f"product code mapped to {f['new_value']}" if f["field"] == "_map_code"
                    else f"{f['field']} -> {f['new_value']}") + f" ({f['status'].lower()})"
            work.append(("dq", f["record_id"], lambda f=f, what=what: _decided("Data quality break", f["record_id"],
                {"source_kind": "dq", "title": f"{f['record_id']}: {what}"}, f["preparer"] or "checker", what)))
    for r in wb.dq_queue(date):
        if r["state"] not in ("open", "warning"):
            d = r.get("decision") or {}
            work.append(("dq", r["record_id"], lambda r=r, d=d: _decided("Data quality break", r["record_id"],
                {"source_kind": "dq", "amount": r.get("amount"), "title": f"{r['record_id']} failed {r['rules']}: {r.get('rule_names', '')[:100]}"},
                d.get("preparer") or "checker", f"{r['state']}: {d.get('field')} -> {d.get('new_value')}")))
    for q in wb.enrich_queue(date):
        if q["status"] in ("ACCEPTED", "REJECTED") and q["kind"] in ("New customer", "New product code"):
            work.append(("ai", q["id"], lambda q=q: _decided(q["kind"], q["id"], {"source_kind": "ai", "title": f"{q['title']}: {q['problem']}"},
                q.get("decided_by") or "checker", f"{q['status'].lower()}: {json.dumps({k: v for k, v in (q.get('suggestion') or {}).items() if v})}")))
    for q in wb.ai_queue(date):
        if q["suggestion_type"] in ("COMMENT_DRAFT", "VARIANCE_COMMENTARY"):
            if q["status"] == "PROPOSED":
                work.append(("ai", q["suggestion_id"], lambda q=q: PROPOSE("comment", date, q)))
            else:
                work.append(("ai", q["suggestion_id"], lambda q=q: _decided("Comment for the Fed", q["suggestion_id"], {"source_kind": "ai", "title": f"Comment for {q['subject']}"},
                    q.get("decided_by") or "checker", q["status"].lower())))
    todo = [w for w in work if (w[0], w[1]) not in existing]
    _RUNS[run_id].update(total=len(todo), skipped=len(work) - len(todo))
    for kind, ref, make in todo:
        try:
            done.append(_save(m, date, run_id, make()))
        except Exception as e:
            errors.append(f"{kind} {ref}: {str(e)[:160]}")
        _RUNS[run_id]["done"] = len(done)
    summary = {"breaks_found": len(work), "new_proposals": len(done), "already_proposed": len(work) - len(todo), "errors": errors}
    with m.get_pg() as conn:
        with conn.cursor() as c:
            c.execute("UPDATE agent_runs SET finished_at = NOW(), status = %s, summary = %s WHERE run_id = %s",
                      ("FAILED" if errors and not done else "DONE", json.dumps(summary), run_id))
        conn.commit()
    _event(m, date, "AI", "Agents", f"Run finished: {len(work)} break(s) found, {len(done)} new proposal(s)", run_id, why="agent run", version="agents v1.0")
    _RUNS[run_id].update(status="DONE", summary=summary)



def _safe_run(date, run_id, user):
    try:
        _run(date, run_id, user)
    except Exception as e:
        _RUNS[run_id].update(status="FAILED", error=str(e)[:300])



# ─── the checker: the breaks, one break in full, and the decision ─────
def _latest(m, break_ids):
    if not break_ids:
        return {}
    rows = m.run_pg("""SELECT DISTINCT ON (break_id) * FROM proposals WHERE break_id = ANY(%s) ORDER BY break_id, version DESC""", (list(break_ids),))
    return {r["break_id"]: r for r in rows}


def _decided_on_step(m, date, p):
    k, ref = p["source_kind"], p["source_ref"]
    if k == "dq":
        return bool(m.run_pg("SELECT 1 FROM dq_fixes WHERE as_of_date = %s AND record_id = %s AND status <> 'WITHDRAWN' LIMIT 1", (date, ref)))
    if k == "ai":
        return bool(m.run_pg("SELECT 1 FROM ai_decisions WHERE suggestion_id = %s LIMIT 1", (ref,)))
    if k == "validate":
        rule, key = ref.split("|", 1)
        return bool(m.run_pg("SELECT 1 FROM validation_decisions WHERE as_of_date = %s AND rule_id = %s AND item_key = %s LIMIT 1", (date, rule, key)))
    return False


def _sync(m, date):
    """A break still PROPOSED whose item was decided on the step page is marked decided there - the register never disagrees with the steps."""
    prop = m.run_pg("SELECT break_id, source_kind, source_ref FROM breaks WHERE as_of_date = %s AND status = 'PROPOSED'", (date,))
    if not prop:
        return
    open_ = {("dq", r["record_id"]) for r in wb.dq_queue(date) if r["state"] == "open"}
    open_ |= {("ai", q["id"]) for q in wb.enrich_queue(date) if q["status"] == "PROPOSED"}
    open_ |= {("ai", q["suggestion_id"]) for q in wb.ai_queue(date) if q["status"] == "PROPOSED"}
    open_ |= {("validate", f"{v['rule_id']}|{v['item_key']}"[:400]) for v in wb.validate_queue(date) if v["state"] == "open"}
    open_ |= {("feed", f["feed"]) for f in m.run_pg("SELECT feed FROM feed_monitor WHERE as_of_date = %s AND status <> 'PASS'", (date,))}
    gone = [p for p in prop if (p["source_kind"], p["source_ref"]) not in open_]
    if gone:
        with m.get_pg() as conn:
            with conn.cursor() as c:
                for p in gone:
                    c.execute("UPDATE breaks SET status = 'APPROVED', updated_at = NOW() WHERE break_id = %s", (p["break_id"],))
                    # decided on the step page if a decision exists there; otherwise the re-run resolved it (e.g. the date now rolls to its settlement day)
                    how, code = ("Decided on the step page", "STEP") if _decided_on_step(m, date, p) else ("Resolved by the re-run - no longer failing", "RERUN")
                    c.execute("INSERT INTO break_decisions VALUES (%s, %s, NULL, 'APPROVE', %s, %s, NULL, 'checker', NOW())",
                              (str(uuid.uuid4())[:12], p["break_id"], code, how))
            conn.commit()


@router.get("/{date}/breaks")
def breaks(date: str, sync: bool = True):
    """Every break of the day with its latest proposal in brief - the checker's queue."""
    wb._check_date(date)
    m = wb._deps()
    if sync:
        _sync(m, date)
    b = m.run_pg("SELECT * FROM breaks WHERE as_of_date = %s ORDER BY (status = 'PROPOSED') DESC, amount_usd DESC NULLS LAST", (date,))
    p = _latest(m, [x["break_id"] for x in b])
    how = {r["break_id"]: r["reason_code"] for r in m.run_pg("SELECT DISTINCT ON (break_id) break_id, reason_code FROM break_decisions WHERE break_id = ANY(%s) ORDER BY break_id, decided_at DESC", ([x["break_id"] for x in b],))} if b else {}
    on_step = {k for k, v in how.items() if v == "STEP"}
    for x in b:
        pr = p.get(x["break_id"]) or {}
        imp = pr.get("impact") or {}
        x.update(decided_on_step=(pr.get("rule_check") or {}).get("detail") == "Decided on the step page" or x["break_id"] in on_step,
                 resolved_by_rerun=how.get(x["break_id"]) == "RERUN",
                 proposal_id=pr.get("proposal_id"), confidence=pr.get("confidence"), rule_status=(pr.get("rule_check") or {}).get("status"),
                 nco_change=imp.get("nco_change"), lcr_before=imp.get("lcr_before"), lcr_after=imp.get("lcr_after"), review=imp.get("review"),
                 summary=pr.get("summary"), version=pr.get("version"),
                 bulk_ok=bool(pr) and float(pr.get("confidence") or 0) >= AUTO_CONFIDENCE and (pr.get("rule_check") or {}).get("status") in ("agrees", "n/a")
                 and not imp.get("review") and (pr.get("action") or {}).get("kind") not in (None, "none"))
    return b


@router.get("/{date}/item")
def item_break(date: str, kind: str, ref: str):
    """The agent's break for one step-queue item (dq record, enrichment / comment suggestion, validation exception), with its evidence -
    the step page shows it next to the item, where the checker decides. Empty when the agents have not looked at the item."""
    wb._check_date(date)
    m = wb._deps()
    b = m.run_pg("SELECT break_id FROM breaks WHERE as_of_date = %s AND source_kind = %s AND source_ref = %s", (date, kind, ref[:400]))
    return break_detail(b[0]["break_id"]) if b else {}


@router.get("/break/{break_id}")
def break_detail(break_id: str):
    m = wb._deps()
    b = m.run_pg("SELECT * FROM breaks WHERE break_id = %s", (wb._safe_id(break_id),))
    if not b:
        raise HTTPException(404, "No such break")
    props = m.run_pg("SELECT * FROM proposals WHERE break_id = %s ORDER BY version DESC", (break_id,))
    dec = m.run_pg("SELECT * FROM break_decisions WHERE break_id = %s ORDER BY decided_at DESC", (break_id,))
    ev = m.run_pg("SELECT * FROM agent_events WHERE subject = %s ORDER BY ts", (break_id,))
    return {"break": b[0], "proposal": props[0] if props else None, "history": props[1:], "decisions": dec, "events": ev,
            "reason_codes": REASON_CODES, "thresholds": {"review_usd_mm": REVIEW_THRESHOLD_USD_MM, "bulk_confidence": AUTO_CONFIDENCE}}


def _apply(date, action, edits, note, request):
    """Apply the approved proposal through the step's own path (the same as a decision on the step page)."""
    kind = action.get("kind")
    if kind == "dq":
        body = {"record_id": action["record_id"], "action": action["action"], "reason": note}
        if action["action"] == "accept_ai":
            body["edits"] = edits or action.get("edits") or {}
            body["action"] = "manual" if edits else "accept_ai"
        if action["action"] == "map_code":
            body["new_value"] = (edits or {}).get("standard_product_type", action.get("new_value"))
        return wb.dq_resolve(date, body, request)
    if kind == "ai_decide":
        ed = {**(action.get("edits") or {}), **(edits or {})}
        if action.get("text_key") and "new_value" in ed:
            ed = {action["text_key"]: ed.pop("new_value")}
        return wb.ai_decide(action["suggestion_id"], {"decision": "ACCEPTED", "note": note, "edits": ed}, request)
    if kind == "validate":
        body = {k: action.get(k) for k in ("rule_id", "item_key", "record_key", "action", "position_id", "field", "new_value")}
        if edits and "new_value" in edits:
            body["new_value"] = edits["new_value"]
        body["note"] = note or action.get("note") or "Approved"
        return wb.validate_resolve(date, body, request)
    return {"applied": False}


def _decide(break_id, data, request):
    m = wb._deps()
    b = m.run_pg("SELECT * FROM breaks WHERE break_id = %s", (wb._safe_id(break_id),))
    if not b:
        raise HTTPException(404, "No such break")
    b = b[0]
    pr = _latest(m, [break_id]).get(break_id)
    act, code, note, edits = data.get("action"), data.get("reason_code"), (data.get("note") or "").strip(), data.get("edits") or None
    if b["status"] != "PROPOSED":
        raise HTTPException(409, f"The break is {b['status'].lower()} - nothing to decide")
    valid = {c for c, _ in REASON_CODES["approve" if act == "approve" else "return"]}
    user = wb._user(request)
    if code == STP_CODE and user == AGENT_ACTOR and act == "approve":
        pass   # the agents applying a proposal straight through (straight_through), never a person
    elif code not in valid:
        raise HTTPException(400, f"Choose a reason code: {', '.join(sorted(valid))}")
    date = str(b["as_of_date"])
    if act == "approve":
        if (pr.get("action") or {}).get("kind") == "none":
            raise HTTPException(400, "Nothing to apply - the data owner fixes the source; return it or wait for the feed")
        status = "APPROVED"
    elif act == "return":
        if not note:
            raise HTTPException(400, "Say why it goes back to the agent")
        status = "RETURNED"
    else:
        raise HTTPException(400, "action must be approve or return")

    def claim(new, old):
        with m.get_pg() as conn:
            with conn.cursor() as c:
                c.execute("UPDATE breaks SET status = %s, updated_at = NOW() WHERE break_id = %s AND status = %s RETURNING break_id", (new, break_id, old))
                ok = c.fetchone() is not None
            conn.commit()
        return ok

    # claim the break first, so a double click or two checkers at once decide it only once
    if not claim(status, "PROPOSED"):
        raise HTTPException(409, "The break was just decided by someone else - nothing to decide")
    if act == "approve":
        try:
            _apply(date, pr["action"], edits, f"{code} {note}".strip(), request)
        except Exception:
            claim("PROPOSED", status)
            raise
    with m.get_pg() as conn:
        with conn.cursor() as c:
            c.execute("INSERT INTO break_decisions VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())",
                      (str(uuid.uuid4())[:12], break_id, pr["proposal_id"], act.upper() + ("_WITH_EDIT" if edits else ""), code, note[:1000],
                       json.dumps(edits) if edits else None, user))
        conn.commit()
    _event(m, date, "AI" if user == AGENT_ACTOR else "PERSON", user,
           (f"Applied {pr['proposal_id']} straight through - for the checker to spot-check" if code == STP_CODE else
            f"{'Approved' if act == 'approve' else 'Returned'} {pr['proposal_id']} as checker" + (" with an edit" if edits else "")),
           break_id, why=f"{code} {note}".strip(), evidence=", ".join(s["ref"] for s in (pr.get("sources") or [])[:3]))
    return {"break_id": break_id, "status": status}


@router.post("/break/{break_id}/decide")
def decide(break_id: str, data: dict, request: Request):
    """The checker's decision: approve (optionally with an edit of the proposed value) or return to the agent with a reason."""
    return _decide(break_id, data, request)


@router.post("/{date}/approve-bulk")
def approve_bulk(date: str, data: dict, request: Request):
    """Approve several proposals at once - only those with confidence >= 0.95, the rule agent agreeing and no material LCR effect."""
    ok = {b["break_id"] for b in breaks(date, sync=False) if b["bulk_ok"] and b["status"] == "PROPOSED"}
    ids = [i for i in data.get("break_ids") or [] if i in ok]
    out, failed = [], []
    for i in ids:   # one failure does not stop the others
        try:
            out.append(_decide(i, {"action": "approve", "reason_code": data.get("reason_code") or "RC-01", "note": data.get("note") or "Bulk approval"}, request))
        except HTTPException as e:
            failed.append({"break_id": i, "error": e.detail})
    return {"approved": len(out), "failed": failed, "skipped": len(data.get("break_ids") or []) - len(ids)}


# "Run the agent again" calls the registered model on its Model Serving endpoint - the same fr2052a_agents@champion version the
# pipeline (notebook 15) uses; the agents' code in the app is only the fallback when the endpoint cannot be reached.
AGENTS_ENDPOINT = os.environ.get("AGENTS_ENDPOINT", "fr2052a-agents")
_SERVED = {}


def _served_version(m):
    if time.time() - _SERVED.get("t", 0) > 300:
        try:
            e = m.get_ws().api_client.do("GET", f"/api/2.0/serving-endpoints/{AGENTS_ENDPOINT}")["config"]["served_entities"][0]
            _SERVED.update(t=time.time(), v=f"{e['entity_name'].rsplit('.', 1)[1]} v{e['entity_version']}")
        except Exception:
            _SERVED.update(t=time.time(), v=None)
    return _SERVED.get("v")


def _remake(m, kind, date, item):
    try:
        r = m.get_ws().api_client.do("POST", f"/serving-endpoints/{AGENTS_ENDPOINT}/invocations", body={
            "dataframe_records": [{"kind": kind, "as_of_date": date, "item_json": json.dumps(item, default=str)}]})
        p = json.loads(r["predictions"][0])
        p["model"] = f"{_served_version(m) or 'fr2052a_agents'} (endpoint {AGENTS_ENDPOINT})"
        return p
    except Exception as e:
        print(f"[agents] serving endpoint {AGENTS_ENDPOINT} unavailable, using the app's agents code: {str(e)[:200]}")
        p = propose(kind, date, item)
        p["model"] = "agents code in the app (endpoint unavailable)"
        return p


@router.post("/break/{break_id}/rerun")
def rerun(break_id: str, request: Request):
    """Run the agents again on one break (after a return): a new version of the proposal, with the checker's note in view."""
    m = wb._deps()
    b = m.run_pg("SELECT * FROM breaks WHERE break_id = %s", (wb._safe_id(break_id),))
    if not b:
        raise HTTPException(404, "No such break")
    b = b[0]
    date, kind, ref = str(b["as_of_date"]), b["source_kind"], b["source_ref"]
    if kind == "dq":
        wb._DQ_SUGGEST.pop((date, ref), None)
        item = next((r for r in wb.dq_queue(date) if r["record_id"] == ref), None)
        p = _remake(m, "dq", date, item) if item else None
    elif kind == "ai":
        item = next((q for q in wb.enrich_queue(date) if q["id"] == ref), None)
        p = _remake(m, "master", date, item) if item else None
    elif kind == "validate":
        rule, key = ref.split("|", 1)
        wb._VAL_SUGGEST.pop((date, rule, key), None)
        item = next((v for v in wb.validate_queue(date) if v["rule_id"] == rule and v["item_key"] == key), None)
        p = _remake(m, "validation", date, item) if item else None
    else:
        p = None
    if not p:
        raise HTTPException(409, "The break is no longer open at its source - nothing to re-propose")
    ver = int((_latest(m, [break_id]).get(break_id) or {}).get("version") or 0) + 1
    _save(m, date, None, p, version=ver, break_id=break_id)
    return {"break_id": break_id, "version": ver}



@router.post("/break/{break_id}/ask")
def ask(break_id: str, data: dict, request: Request):
    """Ask about one break: the answer uses only the proposal, its sources and the closest regulatory passages, and cites them."""
    q = (data.get("question") or "").strip()
    if not q:
        raise HTTPException(400, "Ask a question")
    d = break_detail(break_id)
    m, p, b = wb._deps(), d["proposal"] or {}, d["break"]
    srcs = list(p.get("sources") or [])
    n = max([x["n"] for x in srcs] or [0])
    for r in _vs(m, q + " " + b["title"], 3):
        if r["chunk_id"] not in {x["ref"] for x in srcs}:
            n += 1
            srcs.append({"n": n, "title": (f"FR 2052a Instructions - {r['section']}" if r["doc"].startswith("FR 2052a") else r["section"]), "system": r["doc"], "ref": r["chunk_id"], "passage": r["text"][:2000]})
    prompt = ("You are the FR 2052a Classifier agent answering the checker about one break. Use ONLY the break, the proposal and the numbered sources; "
              "cite sources inline as [n]; if they do not answer the question, say so. Two to four sentences. Break: " + json.dumps({k: b[k] for k in ("break_id", "break_type", "title")}, default=str) +
              ". Proposal: " + json.dumps({k: p.get(k) for k in ("summary", "fields", "rule_check", "impact")}, default=str) +
              ". Sources: " + json.dumps([{"n": x["n"], "title": x["title"], "text": x["passage"][:1500]} for x in srcs], default=str) +
              '. Question: ' + q + '. Answer ONLY JSON: {"answer": "...", "cited": [n, ...]}')
    try:
        out = wb._ai_json(m, prompt, 500)
    except Exception as e:
        raise HTTPException(502, f"The agent could not answer: {str(e)[:150]}")
    used = [x for x in srcs if x["n"] in (out.get("cited") or [])]
    _event(m, str(b["as_of_date"]), "PERSON", wb._user(request), f"Asked: {q[:200]}", break_id, why="Ask about this break")
    _event(m, str(b["as_of_date"]), "AI", "Classifier", f"Answered: {str(out.get('answer'))[:300]}", break_id, evidence=", ".join(x["ref"] for x in used), version=VERSIONS["Classifier"])
    return {"answer": out.get("answer"), "sources": used}


# ─── Today: the run at a glance - feeds, what the agents did, the maturity river with the breaks on it, the breaks of the day ─────
RIVER_BUCKETS = [("Open", 0, 0), ("Day 1", 1, 1), ("Days 2-7", 2, 7), ("Days 8-30", 8, 30), ("Days 31-60", 31, 60), ("Days 61-90", 61, 90),
                 ("Days 91-180", 91, 180), ("Days 181-365", 181, 364), ("1-2 yrs", 365, 730), ("2-3 yrs", 731, 1095), ("3-4 yrs", 1096, 1460),
                 ("4-5 yrs", 1461, 1826), ("> 5 yrs", 1827, 99999)]
RIVER_TABLES = {"I.A": "Assets", "I.U": "Unsecured", "I.S": "Secured", "I.O": "Other", "O.D": "Deposits", "O.W": "Wholesale", "O.S": "Secured", "O.O": "Other"}
SUPPLEMENTAL = {"S.DC": "Derivatives & Collateral", "S.L": "Liquidity Risk Measurement", "S.B": "Balance Sheet", "S.I": "Informational", "S.FX": "Foreign Exchange"}


def _bucket_dates(date, lo, hi):
    """The calendar dates a river bucket covers, counted from the as-of date, and whether they are all weekend days."""
    if lo == 0:
        return {"label": "no contractual maturity (demand / open)", "weekend": False}
    d0 = datetime.date.fromisoformat(date)
    a, b = d0 + datetime.timedelta(days=lo), d0 + datetime.timedelta(days=min(hi, 40000))
    span = [d0 + datetime.timedelta(days=i) for i in range(lo, min(hi, lo + 7) + 1)]
    fmt = lambda d: d.strftime("%a %b %-d, %Y")
    return {"label": fmt(a) if lo == hi else (f"{fmt(a)} to {fmt(b)}" if hi < 40000 else f"from {fmt(a)}"),
            "weekend": hi - lo < 7 and all(x.weekday() >= 5 for x in span)}


def _bucket_group(day_start):
    if day_start is None:
        return "> 5 yrs"
    return next(label for label, lo, hi in RIVER_BUCKETS if lo <= int(day_start) <= hi)


@router.get("/{date}/today")
def today_view(date: str, entity: str = "ENT001"):
    wb._check_date(date)
    m = wb._deps()
    e = wb._safe_id(entity)
    rows = wb._wh_rows(m, f"river|{e}", date, f"""SELECT v.table_code, b.day_start, SUM(v.reported_amount_usd) AS usd FROM filing_records v
                         LEFT JOIN ref_maturity_bucket b ON b.bucket_label = v.maturity_bucket
                         WHERE v.as_of_date = '{date}' AND v.reporting_entity = '{e}' AND v.table_code ~ '^[IO]\\.' GROUP BY 1, 2""")
    river = {label: {t: 0.0 for t in RIVER_TABLES} for label, _, _ in RIVER_BUCKETS}
    for r in rows:
        if r["table_code"] in RIVER_TABLES:
            river[_bucket_group(r["day_start"])][r["table_code"]] += float(r["usd"] or 0) / 1000
    totals = {t: round(sum(river[b][t] for b in river), 1) for t in RIVER_TABLES}
    feeds = m.run_pg("SELECT feed, records, expected_records, status, details FROM feed_monitor WHERE as_of_date = %s ORDER BY feed", (date,))
    bad = [f for f in feeds if f["status"] != "PASS"]
    fed = m.run_wh(f"""SELECT s.source_feed, array_to_string(array_agg(DISTINCT f.table_code), ', ') AS tables FROM fact_liquidity_position f
                        JOIN source_position s ON s.as_of_date = f.as_of_date AND s.record_id = f.record_id WHERE f.as_of_date = '{date}' GROUP BY 1""") if bad else []
    provisional = sorted({t.strip() for x in fed if x["source_feed"] in {f["feed"] for f in bad} for t in (x["tables"] or "").split(",")})
    brks = breaks(date, sync=False)
    refs = {b["break_id"]: b["source_ref"].split("|")[-1] for b in brks if b["source_kind"] == "validate" and "#" in b["source_ref"].split("|")[-1]}
    at = {}
    if refs:   # pin each break on the river where its position sits - one query for all of them
        ids = ", ".join(sorted({_sql_str(r) for r in refs.values()}))
        at = {r["position_id"]: r for r in wb._wh_rows(m, f"pins|{hash(ids)}", date, f"""SELECT f.position_id, f.table_code, mb.day_start
                 FROM fact_liquidity_position f LEFT JOIN ref_maturity_bucket mb ON mb.bucket_label = f.maturity_bucket
                 WHERE f.as_of_date = '{date}' AND f.position_id IN ({ids})""")}
    for b in brks:
        b["bucket"], b["river_table"] = None, b["table_code"] if b["table_code"] in RIVER_TABLES else None
        r = at.get(refs.get(b["break_id"]))
        if r:
            b["bucket"], b["river_table"] = _bucket_group(r["day_start"]), r["table_code"]
    run = m.run_pg("SELECT * FROM agent_runs WHERE as_of_date = %s ORDER BY started_at DESC LIMIT 1", (date,))
    pid = (m.run_pg("SELECT source_records, positions, derived FROM pid_derivation_summary WHERE as_of_date = %s", (date,)) or [{}])[0]
    val = (m.run_pg("""SELECT COUNT(*) AS checks, COUNT(*) FILTER (WHERE status IN ('FAIL', 'WARNING')) AS not_passing FROM gold_validation WHERE as_of_date = %s""", (date,)) or [{}])[0]
    sup_bad = {r["table_code"] for r in m.run_pg("SELECT DISTINCT table_code FROM gold_validation WHERE as_of_date = %s AND status = 'FAIL'", (date,))}
    return {"date": date, "entity": e, "due": m._due_dates(date), "feeds": {"total": len(feeds), "incomplete": bad, "provisional_tables": provisional},
            "agents": {"last_run": run[0] if run else None, "positions": pid.get("positions"), "classified": pid.get("derived"),
                       "checks": val.get("checks"), "checks_not_passing": val.get("not_passing"),
                       "breaks_open": sum(1 for b in brks if b["status"] == "PROPOSED"), "breaks_total": len(brks)},
            "river": {"buckets": [label for label, _, _ in RIVER_BUCKETS], "tables": RIVER_TABLES, "values": river, "totals": totals,
                      "dates": {label: _bucket_dates(date, lo, hi) for label, lo, hi in RIVER_BUCKETS}},
            "supplemental": [{"table_code": t, "name": n, "status": "provisional" if t in provisional else ("failing" if t in sup_bad else "ok")} for t, n in SUPPLEMENTAL.items()],
            "breaks": brks}


# ─── Audit: who did what, when, why and with which evidence - people and agents - and the examiner pack ─────
def _timeline(m, date):
    """agent_events (append-only: the app cannot update or delete them) and every decision recorded elsewhere in the app, as one timeline."""
    ev = m.run_pg("""SELECT ts, actor_type, actor, action, subject, why, evidence, version, 'agent_events' AS source FROM agent_events WHERE as_of_date = %s""", (date,))
    other = m.run_pg("""
      SELECT created_at AS ts, 'PERSON' AS actor_type, preparer AS actor,
             CASE field WHEN '_exclude' THEN 'Excluded the record' WHEN '_map_code' THEN 'Mapped product code ' || COALESCE(old_value, '') || ' to ' || COALESCE(new_value, '')
                  ELSE 'Fixed ' || field || ': ' || COALESCE(old_value, '(empty)') || ' -> ' || COALESCE(new_value, '') END || ' (' || status || ')' AS action,
             record_id AS subject, reason AS why, 'dq_fixes ' || fix_id AS evidence, '' AS version, 'dq_fixes' AS source FROM dq_fixes WHERE as_of_date = %s
      UNION ALL SELECT created_at, 'PERSON', preparer, 'Corrected ' || field || ': ' || COALESCE(old_value, '') || ' -> ' || COALESCE(new_value, '') || ' (' || status || ')',
             position_id, reason, 'position_corrections ' || correction_id, '', 'position_corrections' FROM position_corrections WHERE as_of_date = %s
      UNION ALL SELECT decided_at, 'PERSON', decided_by, CASE action WHEN 'explain' THEN 'Explained the exception' ELSE 'Resolved the exception (' || action || ')' END,
             rule_id || ' ' || LEFT(item_key, 60), note, 'validation_decisions ' || decision_id, '', 'validation_decisions' FROM validation_decisions WHERE as_of_date = %s
      UNION ALL SELECT action_timestamp, CASE WHEN action = 'GENERATED' THEN 'AI' ELSE 'PERSON' END, actor, 'Reporting run ' || run_number || ' v' || version || ': ' || action,
             'run ' || run_number, note, 'submission_review', '', 'submission_review' FROM submission_review WHERE as_of_date = %s
      UNION ALL SELECT d.decided_at, 'PERSON', d.decided_by, CASE d.decision WHEN 'ACCEPTED' THEN 'Accepted' ELSE 'Rejected' END || ' the AI suggestion ('
             || LOWER(REPLACE(s.suggestion_type, '_', ' ')) || ')', s.subject_key, d.note, 'ai_decisions ' || d.suggestion_id, '', 'ai_decisions'
             FROM ai_decisions d JOIN ai_suggestions s USING (suggestion_id) WHERE s.as_of_date = %s""", (date, date, date, date, date))
    rows = sorted(ev + other, key=lambda r: str(r["ts"]), reverse=True)
    return rows


@router.get("/{date}/audit")
def audit(date: str, who: str = "all"):
    wb._check_date(date)
    rows = _timeline(wb._deps(), date)
    if who == "agents":
        rows = [r for r in rows if r["actor_type"] == "AI"]
    elif who == "people":
        rows = [r for r in rows if r["actor_type"] == "PERSON"]
    elif who == "decisions":
        rows = [r for r in rows if r["actor_type"] == "PERSON" and r["source"] != "agent_events" or (r["source"] == "agent_events" and r["action"].startswith(("Approved", "Returned")))]
    return {"events": rows[:500], "total": len(rows)}


@router.get("/{date}/source-fixes")
def source_fixes(date: str):
    """The source fixes of the approved breaks: the data owner, what to fix, the due date, the age, and whether the override has retired."""
    wb._check_date(date)
    m = wb._deps()
    b = [x for x in breaks(date, sync=False) if x["status"] == "APPROVED"]
    p = _latest(m, [x["break_id"] for x in b])
    retired = {r["record_id"] for r in m.run_pg("SELECT record_id FROM dq_fixes WHERE as_of_date = %s AND status = 'RETIRED'", (date,))}
    latest = (m.run_pg("SELECT MAX(as_of_date) AS d FROM calculation_results") or [{}])[0].get("d") or date
    out = []
    for x in b:
        fx = (p.get(x["break_id"]) or {}).get("source_fix") or {}
        if not fx:
            continue
        age = sum(1 for i in range((datetime.date.fromisoformat(str(latest)) - datetime.date.fromisoformat(date)).days) if (datetime.date.fromisoformat(date) + datetime.timedelta(days=i + 1)).weekday() < 5)
        status = "RETIRED - fixed at source" if x["source_ref"] in retired else ("OVERDUE" if str(latest) > fx.get("due", "9999") else "OPEN")
        out.append({"break_id": x["break_id"], "break_type": x["break_type"], "owner": fx.get("owner"), "text": fx.get("text"), "due": fx.get("due"),
                    "age_business_days": age, "status": status})
    return out


def _masker(m):
    import hashlib, re
    names = [r["customer_name"] for r in m.run_wh(f"SELECT DISTINCT customer_name FROM ref_customer_master WHERE customer_name IS NOT NULL")]
    names = sorted({n for n in names if len(n) > 3}, key=len, reverse=True)
    def mask(v):
        if v is None:
            return v
        s = str(v)
        s = re.sub(r"\bC\d{4}\b", lambda mm: "CUST-" + hashlib.sha1(mm.group(0).encode()).hexdigest()[:6], s)
        for n in names:
            s = s.replace(n, "[customer name masked]")
        return s
    return mask


@router.get("/{date}/audit/export")
def audit_export(date: str, request: Request, audience: str = "Federal Reserve examiners"):
    """The audit pack for one run: decisions with reason codes and checker signatures, proposals with their sources, breaks and source fixes
    with aging, agent and model versions, lineage counts - customer identifiers masked, marked confidential, with a SHA-256 manifest."""
    import csv, hashlib, io, zipfile
    from fastapi.responses import StreamingResponse
    wb._check_date(date)
    m = wb._deps()
    mask = _masker(m)
    brk = breaks(date, sync=False)
    props = m.run_pg("SELECT * FROM proposals WHERE break_id = ANY(%s) ORDER BY break_id, version", ([b["break_id"] for b in brk],)) if brk else []
    decs = m.run_pg("SELECT * FROM break_decisions WHERE break_id = ANY(%s) ORDER BY decided_at", ([b["break_id"] for b in brk],)) if brk else []
    files = {
        "01_decisions.csv": [{k: mask(d[k]) for k in ("break_id", "proposal_id", "action", "reason_code", "note", "decided_by", "decided_at")} for d in decs],
        "02_breaks.csv": [{k: mask(b.get(k)) for k in ("break_id", "break_type", "table_code", "amount_usd", "title", "status", "confidence", "rule_status", "nco_change", "lcr_before", "lcr_after", "due_at")} for b in brk],
        "03_proposals_with_sources.csv": [{"proposal_id": p["proposal_id"], "break_id": p["break_id"], "version": p["version"], "agent": p["agent"], "model": p["model"],
                                           "confidence": p["confidence"], "summary": mask(p["summary"]), "fields": mask(json.dumps(p["fields"], default=str)),
                                           "rule_check": json.dumps(p["rule_check"]), "liquidity_effect": json.dumps(p["impact"]),
                                           "sources": mask(json.dumps([{"n": s["n"], "title": s["title"], "system": s["system"], "ref": s["ref"]} for s in (p["sources"] or [])]))} for p in props],
        "04_source_fixes.csv": [{k: mask(v) for k, v in s.items()} for s in source_fixes(date)],
        "05_audit_trail.csv": [{k: mask(e[k]) for k in ("ts", "actor_type", "actor", "action", "subject", "why", "evidence", "version")} for e in _timeline(m, date)],
        "06_agent_versions.csv": [{"agent": a, "version": v, "model": MODEL, "registered_model": _served_version(m) or ""} for a, v in VERSIONS.items()],
        "07_lineage_counts.csv": m.run_wh(f"""SELECT reporting_entity, table_code, COUNT(DISTINCT record_key) AS reported_records, COUNT(*) AS positions, round(CAST(SUM(amount) AS NUMERIC), 2) AS amount
                                               FROM record_lineage WHERE as_of_date = '{date}' GROUP BY 1, 2 ORDER BY 1, 2"""),
        "08_release_memo.csv": [{k: mask(v) for k, v in r.items()} for r in m.run_pg("""SELECT run_number, made_by, created_at, memo FROM release_memos
                                                                                       WHERE as_of_date = %s ORDER BY run_number""", (date,))],
    }
    readme = (f"FR 2052a audit pack - {date}\nAudience: {audience}\nGenerated: {_now().isoformat(timespec='seconds')}Z by the FR 2052a app\n\n"
              "CONFIDENTIAL. FR 2052a data receives confidential treatment (12 CFR 261). Customer identifiers and names are masked; no BSA/AML case information "
              "is held in this solution.\n\nContents: decisions with reason codes and checker signatures; breaks; every proposal with its agent, model, confidence, "
              "rule check, liquidity effect and sources; source fixes with aging; the audit trail of agents and people; agent and model versions; lineage counts "
              "from each FR 2052a table to its positions; the release memo given to the approver.\n\nThe AI agents are the maker; a named person is the checker for every change. Derived LCR figures are "
              "internal estimates before the re-run, not filed figures.\n")
    buf, manifest = io.BytesIO(), {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, rows in files.items():
            s = io.StringIO()
            if rows:
                wr = csv.DictWriter(s, fieldnames=list(rows[0].keys()))
                wr.writeheader(); wr.writerows(rows)
            data = s.getvalue().encode()
            manifest[name] = {"rows": len(rows), "sha256": hashlib.sha256(data).hexdigest()}
            z.writestr(name, data)
        z.writestr("README.txt", readme)
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
    pack = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    _event(m, date, "PERSON", wb._user(request), f"Exported the audit pack for {audience}", f"FR2052A-{date}-EX", why="examiner export", evidence=f"manifest sha256 {pack[:16]}")
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": f"attachment; filename=FR2052A-{date}-audit-pack.zip", "X-Pack-SHA256": pack})


# ─── Review: one source of truth for "what is left for me" - every count is the step page's own queue ─────


def review_state(date):
    """For each step: what the AI agent already did, and what is left for the checker - counted from the same queue the step page shows."""
    m = wb._deps()
    one = lambda sql: (m.run_pg(sql, (date,)) or [{}])[0]
    # the queues and counts are independent: read them in parallel (two of them go to the SQL warehouse)
    jobs = {
        "feeds": lambda: m.run_pg("SELECT feed, status, details, files, records FROM feed_monitor WHERE as_of_date = %s", (date,)),
        "dq": lambda: wb.dq_queue(date),
        "rules": lambda: one("SELECT COUNT(*) AS n FROM assessment_results WHERE as_of_date = %s").get("n"),
        "enr": lambda: wb.enrich_queue(date),
        "pid": lambda: one("SELECT source_records, positions, derived FROM pid_derivation_summary WHERE as_of_date = %s"),
        "vq": lambda: wb.validate_queue(date),
        "checks": lambda: one("""SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE status = 'FAIL') AS failed, COUNT(*) FILTER (WHERE status = 'WARNING') AS warnings
                                 FROM gold_validation WHERE as_of_date = %s"""),
        "ai": lambda: wb.ai_queue(date),
        "sub": lambda: m.get_submission(date),
        "brk": lambda: m.run_pg("SELECT status, COUNT(*) AS n FROM breaks WHERE as_of_date = %s GROUP BY 1", (date,)),
        "agents_run": lambda: bool(m.run_pg("SELECT 1 FROM agent_runs WHERE as_of_date = %s LIMIT 1", (date,))),
        "gl": lambda: m.run_pg("SELECT status, COUNT(*) AS n FROM gl_reconciliation WHERE as_of_date = %s GROUP BY 1", (date,)),
        "lcr_tie": lambda: m.run_pg("SELECT status, COUNT(*) AS n FROM cross_metric_recon WHERE as_of_date = %s GROUP BY 1", (date,)),
        "gen": lambda: wb.generate_status(date),
    }
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        fut = {k: ex.submit(f) for k, f in jobs.items()}
        got = {k: f.result() for k, f in fut.items()}
    feeds, dq, rules, enr, pid, vq, checks = (got[k] for k in ("feeds", "dq", "rules", "enr", "pid", "vq", "checks"))
    sub, brk, agents_run, gl, lcr_tie = (got[k] for k in ("sub", "brk", "agents_run", "gl", "lcr_tie"))
    bad_feeds = [f for f in feeds if f["status"] != "PASS"]
    dq_open = [r for r in dq if r["state"] == "open"]
    dq_rerun = [r for r in dq if r["state"] in ("fix pending re-run", "mapped")]
    enr_open = [q for q in enr if q["status"] == "PROPOSED"]
    v_open = [x for x in vq if x["state"] == "open"]
    v_rerun = [x for x in vq if x["state"] == "corrected - re-run"]
    comments = [q for q in got["ai"] if q["suggestion_type"] in ("COMMENT_DRAFT", "VARIANCE_COMMENTARY")]
    c_open = [q for q in comments if q["status"] == "PROPOSED"]
    files = sub.get("files", [])
    run_status = sub.get("status") or "NOT_GENERATED"
    proposed = sum(b["n"] for b in brk if b["status"] == "PROPOSED")
    pl = plural
    n_of = lambda rows, st: sum(r["n"] for r in rows if r["status"] == st)
    received = sum(int(f.get("records") or 0) for f in feeds)
    pos_feeds = [f for f in feeds if f["feed"] not in ("customers", "collateral_links", "gl_balances", "comments")]   # feeds that carry positions
    held = [r for r in dq if r["state"] != "warning"]
    dq_done = [r for r in held if r["state"] in ("fixed", "excluded")]
    n_checks, n_fail, n_warn = int(checks.get("n") or 0), int(checks.get("failed") or 0), int(checks.get("warnings") or 0)
    v_done = [x for x in vq if x["state"] not in ("open", "corrected - re-run")]
    by_type = {}
    for f in files:
        by_type[f["file_type"]] = by_type.get(f["file_type"], 0) + int(f.get("record_count") or 0)
    n_drafts = sum(1 for q in comments if q["suggestion_type"] == "COMMENT_DRAFT")
    done = {
        "collect": [f"Received {pl(len(feeds), 'source feed')} ({pl(sum(int(f.get('files') or 0) for f in feeds), 'file')}): {sum(int(f.get('records') or 0) for f in pos_feeds):,} "
                    f"position records from {pl(len(pos_feeds), 'position feed')}, plus {received - sum(int(f.get('records') or 0) for f in pos_feeds):,} supporting records "
                    "(customers, collateral links, GL balances, comments).",
                    "Every feed arrived complete - its volume is in line with its 5-day median." if not bad_feeds else
                    f"{pl(len(bad_feeds), 'feed')} short of its 5-day median: " + ", ".join(f["feed"] for f in bad_feeds) + "."],
        "dq": [f"Checked the {int(pid.get('source_records') or 0) + len(held):,} position records against {pl(int(rules or 0), 'data quality rule')} (completeness, valid values, dates, amounts).",
               (f"{pl(len(held), 'record')} failed and was held back; the AI proposed a fix for each ({len(dq_done)} already decided)." if held else
                "No record failed - all of them went on to PID enrichment.")],
        "enrich": [f"Split {int(pid.get('source_records') or 0):,} source records into {int(pid.get('positions') or 0):,} FR 2052a positions (e.g. insured / uninsured deposits).",
                   f"Gave {int(pid.get('derived') or 0):,} of {int(pid.get('positions') or 0):,} positions their FR 2052a product (PID) by rule, with counterparty, "
                   "G-SIB, collateral class, HQLA level and maturity bucket (maturities on holidays rolled to the next business day).",
                   (f"Found {len(enr)} new customers / product codes and proposed how to classify each ({len(enr) - len(enr_open)} decided)." if enr
                    else "No new customers or product codes.")],
        "validate": [f"Ran {n_checks:,} checks: the FR 2052a Instructions, the Fed's 6G business rules and schema, the Fed's 14 post-submission checks and the reconciliations.",
                     f"{n_checks - n_fail - n_warn:,} passed" + (f", {n_fail} failed" if n_fail else "") + (f", {n_warn} gave a warning" if n_warn else "") + "."
                     + (f" The AI proposed a correction or an explanation for each of the {pl(len(vq), 'record')} affected ({len(v_done)} decided)." if vq else ""),
                     f"General ledger: {n_of(gl, 'PASS')} of {sum(r['n'] for r in gl)} balances tie within 0.5%; FR 2052a vs LCR engine: "
                     f"{n_of(lcr_tie, 'PASS')} of {sum(r['n'] for r in lcr_tie)} tie.",
                     (f"Drafted {pl(len(comments), 'comment')} for the Fed ({n_drafts} S.C comments, {len(comments) - n_drafts} variance commentaries) "
                      f"and checked each names its FR 2052a table ({len(comments) - len(c_open)} decided)." if comments else "No comment for the Fed was needed today.")],
        "release": [],   # set below: it depends on steps 1-4
    }
    steps = [
        {"key": "collect", "n": 1, "title": "Collect", "to": "/collect",
         "agent": f"Checked {pl(len(feeds), 'source feed')} against their 5-day median.",
         "open": len(bad_feeds), "open_label": f"{pl(len(bad_feeds), 'feed')} incomplete - ask the source to re-send",
         "detail": "; ".join(f"{f['feed']}: {f['details']}" for f in bad_feeds)},
        {"key": "dq", "n": 2, "title": "Data quality", "to": "/dq",
         "agent": f"Ran {pl(int(rules or 0), 'rule')} on every record and proposed a fix for each record that failed.",
         "open": len(dq_open), "open_label": f"{pl(len(dq_open), 'record')} to review",
         "waiting": len(dq_rerun), "waiting_label": f"{pl(len(dq_rerun), 'approved fix')} wait for the re-run from data quality"},
        {"key": "enrich", "n": 3, "title": "PID enrichment", "to": "/enrich",
         "agent": f"Classified {int(pid.get('derived') or 0):,} of {int(pid.get('positions') or 0):,} positions by a PID rule and proposed the new customers and product codes.",
         "open": len(enr_open), "open_label": f"{pl(len(enr_open), 'proposal')} to review"},
        {"key": "validate", "n": 4, "title": "Validate", "to": "/validate",
         "agent": f"Ran {int(checks.get('n') or 0):,} checks and proposed a correction or an explanation for each exception "
                  f"({pl(len(vq), 'exception')} from {pl(int(checks.get('failed') or 0) + int(checks.get('warnings') or 0), 'check')} not passing).",
         "open": len(v_open) + len(c_open),
         "open_label": ", ".join(x for x in (f"{pl(len(v_open), 'exception')}" if v_open else "", f"{pl(len(c_open), 'comment')}" if c_open else "") if x) + " to review",
         "waiting": len(v_rerun), "waiting_label": f"{pl(len(v_rerun), 'approved correction')} wait for the re-run of the validation",
         "blocking": sum(1 for x in v_open if x["status"] == "FAIL")},
        {"key": "release", "n": 5, "title": "Generate 6G & release", "to": "/release",
         "agent": (f"Generated {pl(len(files), '6G file')} ({'all valid' if files and all(f['xsd_valid'] for f in files) else 'XSD errors'} against the Fed XSD) "
                   ) if files else "No 6G file yet - the run has not been generated.",
         "open": 0},
    ]
    # Step 5 depends on steps 1-4: it starts when they have nothing open and nothing waiting for a re-run; then a person generates the
    # 6G files for release (fr2052a-generate), the approver approves and a second person marks the filing submitted.
    rel = steps[4]
    left = [f"{s['title']} ({s['open_label'] if s['open'] else s.get('waiting_label')})" for s in steps[:4] if s["open"] or s.get("waiting")]
    gen = got["gen"] or {}
    generating = gen.get("state") in ("PENDING", "QUEUED", "RUNNING", "BLOCKED")
    released = bool(files) and bool(sub.get("released_by"))
    when = str(sub.get("generated_at") or "")[:16].replace("T", " ")
    file_line = ("Generated the 6G files for release" + (f" ({sub.get('released_by')}, {when})" if released else "") + ": "
                 + ", ".join(f"{t} ({n:,} {'comments' if t == 'Comment' else 'records'})" for t, n in
                             sorted(by_type.items(), key=lambda x: ["Primary", "Reduced", "Comment"].index(x[0]) if x[0] in ("Primary", "Reduced", "Comment") else 9))
                 + (" - all valid against the Fed XSD." if not any(not f["xsd_valid"] for f in files) else " - XSD errors."))
    if left:
        rel.update(state="waiting", close_label="Waits for steps 1-4", tone="wait",
                   done=["Starts when steps 1-4 have nothing left: " + "; ".join(left) + ".",
                         "Then: generate the 6G files, approve, and a second person marks the filing submitted."])
    elif generating:
        rel.update(state="waiting", close_label="Generating the 6G files...", tone="wait",
                   done=[f"Steps 1-4 are complete. The 6G files are being generated ({gen.get('by') or 'requested'}) - about 15 minutes."])
    elif not released or run_status in ("REJECTED", "REPORTING_REQUESTED"):
        failed = gen.get("result") not in (None, "SUCCESS") and gen.get("state") == "TERMINATED"
        rel.update(state="review", close_label="Generate the 6G files", tone="act",
                   done=["Steps 1-4 are complete." + (" The last generation failed - generate again." if failed else
                         " The run was rejected - generate again." if run_status == "REJECTED" else ""),
                         "Next: generate the 6G files for release (Primary, Reduced at month-end, Comment), then approve and submit."])
    else:
        nxt = {"READY_FOR_REVIEW": ("Approve", "act", "Waiting for the approver's sign-off, then a second person submits."),
               "OVERRIDE_REQUESTED": ("Approve the override", "act", "An override was requested - someone else approves it."),
               "BLOCKED": ("Blocked - see the files", "act", "Blocked by a failing check or an XSD error - fix it in Validate and generate again."),
               "APPROVED": ("Mark submitted", "act", "Approved - a second person marks the filing submitted."),
               "SUBMITTED": ("Submitted", "done", "Submitted to the Federal Reserve.")}.get(run_status, ("Approve", "act", ""))
        rel.update(state="done" if run_status == "SUBMITTED" else "review", close_label=nxt[0], tone=nxt[1], done=[file_line, nxt[2]])
    done["release"] = rel["done"]

    # the sign-off is not an item to review: it is the next step in the workflow, shown as a note
    signoff = (None if run_status == "SUBMITTED" and released else
               "finish steps 1-4, then generate the 6G files in step 5" if left else
               f"{rel['close_label'].rstrip('.').lower()} in step 5 (Generate 6G & release)" if not generating else None)
    xsd_bad = any(not f["xsd_valid"] for f in files)
    blocked = run_status in ("BLOCKED", "REJECTED") or xsd_bad or steps[3]["blocking"] > 0
    to_review = sum(s["open"] for s in steps)
    status = ("submitted" if run_status == "SUBMITTED" else "blocked" if blocked else "not_run" if not files else
              "signoff" if to_review == 0 else "review")
    for s in steps[:4]:
        s["done"] = done[s["key"]]
        s["state"] = "done" if s["open"] == 0 and not s.get("waiting") else ("waiting" if s["open"] == 0 else "review")
    label = ", ".join(s["open_label"].replace(" to review", "") for s in steps if s["open"])
    return {"date": date, "due": m._due_dates(date), "status": status, "to_review": to_review, "to_review_label": label,
            "next": (f"Next: {signoff}." if signoff else None), "steps": steps,
            "approvals": {"agents_run": agents_run, "waiting": proposed}, "agents": agents_summary(m, date),
            "run": {"number": sub.get("run_number"), "status": run_status, "files": len(files), "xsd_valid": bool(files) and not xsd_bad}}


@router.get("/{date}/review")
def review(date: str):
    """Where it stands: per step, what was done and what is left - counted from each step page's own queue."""
    wb._check_date(date)
    return review_state(date)


def _warm():
    """At start-up, read every reporting day once so the first person to open Today or a step page does not wait for the warehouse."""
    time.sleep(5)
    try:
        for d in wb._deps().get_dates():
            for f in (review_state, today_view):
                try:
                    f(d)
                except Exception as e:
                    print(f"[warm] {f.__name__} {d}: {str(e)[:120]}")
    except Exception as e:
        print(f"[warm] {str(e)[:120]}")


if not os.environ.get("FR2052A_AGENTS_BATCH"):
    threading.Thread(target=_warm, daemon=True).start()


# ─── AI-first: straight-through processing, the agents' headline, the release memo, the learning loop, the agents' accuracy ─────
class _AgentRequest:
    headers = {"X-Forwarded-Email": AGENT_ACTOR}


STP_NOTE = "Straight through: confidence >= 95%, the rule agent agrees, no material LCR effect"


def straight_through(date):
    """The agents apply every proposal that qualifies (the bulk-approval test) through the step's own path, as themselves - each is in the
    audit trail as applied by the agents and listed on Today for the checker to spot-check. Called by notebook 15 after the run."""
    applied, failed = [], []
    for b in breaks(date, sync=False):
        if b["status"] == "PROPOSED" and b["bulk_ok"]:
            try:
                _decide(b["break_id"], {"action": "approve", "reason_code": STP_CODE, "note": STP_NOTE}, _AgentRequest())
                applied.append(b["break_id"])
            except HTTPException as e:
                failed.append({"break_id": b["break_id"], "error": e.detail})
    return {"applied": applied, "failed": failed}


@router.post("/break/{break_id}/spot-check")
def spot_check(break_id: str, data: dict, request: Request):
    """The checker's spot check of an item the agents applied straight through: confirm, or disagree with a reason (then fix it on the
    step page). One spot check per item, append-only; it is the agents' feedback (notebook 10)."""
    m = wb._deps()
    b = m.run_pg("SELECT * FROM breaks WHERE break_id = %s", (wb._safe_id(break_id),))
    if not b:
        raise HTTPException(404, "No such break")
    dec = m.run_pg("SELECT * FROM break_decisions WHERE break_id = %s ORDER BY decided_at", (break_id,))
    stp = next((d for d in dec if d["reason_code"] == STP_CODE), None)
    if not stp:
        raise HTTPException(409, "Only an item the agents applied straight through is spot-checked")
    if any(str(d["action"]).startswith("SPOT_CHECK") for d in dec):
        raise HTTPException(409, "This item is already spot-checked")
    verdict, note, user = data.get("verdict"), (data.get("note") or "").strip(), wb._user(request)
    if verdict not in ("confirm", "disagree"):
        raise HTTPException(400, "verdict must be confirm or disagree")
    if verdict == "disagree" and not note:
        raise HTTPException(400, "Say what is wrong")
    if user == AGENT_ACTOR:
        raise HTTPException(403, "The agents cannot spot-check their own work")
    with m.get_pg() as conn:
        with conn.cursor() as c:
            c.execute("INSERT INTO break_decisions VALUES (%s, %s, %s, %s, 'SC', %s, NULL, %s, NOW())",
                      (str(uuid.uuid4())[:12], break_id, stp["proposal_id"], "SPOT_CHECK_" + verdict.upper(), note[:1000], user))
        conn.commit()
    _event(m, str(b[0]["as_of_date"]), "PERSON", user, f"Spot-checked {stp['proposal_id']} (applied straight through): "
           + ("confirmed" if verdict == "confirm" else "disagreed - to be corrected on the step page"), break_id, why=note)
    return {"break_id": break_id, "verdict": verdict,
            "next": "Correct it on the step page (Fix manually) and re-run; your reason is the agents' feedback." if verdict == "disagree" else None}


def agents_summary(m, date):
    """Today's headline: what the agents did and what is left for the checker (the step pages' counts stay the source of the to-review numbers)."""
    b = m.run_pg("SELECT break_id, status, title, break_type, source_kind, source_ref FROM breaks WHERE as_of_date = %s", (date,))
    if not b:
        return {"headline": None, "spot_check": []}
    dec = m.run_pg("""SELECT d.break_id, d.action, d.reason_code, d.decided_by FROM break_decisions d JOIN breaks b USING (break_id)
                      WHERE b.as_of_date = %s""", (date,))
    by = {}
    for d in dec:
        by.setdefault(d["break_id"], []).append(d)
    stp = [x for x in b if any(d["reason_code"] == STP_CODE for d in by.get(x["break_id"], []))]
    pending = [x for x in stp if not any(str(d["action"]).startswith("SPOT_CHECK") for d in by.get(x["break_id"], []))]
    person = [x for x in b if x not in stp and any(d["reason_code"] not in ("STEP", "RERUN", "SC") and str(d["action"]).startswith("APPROVE")
                                                   for d in by.get(x["break_id"], []))]
    # a waiting proposal whose item was already decided on its step page is settled there (the register catches up at its next sync):
    # the headline never says more is left than the step pages do
    on_page = {x["break_id"] for x in b if x["status"] in ("PROPOSED", "RETURNED") and _decided_on_step(m, date, x)}
    step = [x for x in b if x not in stp and x not in person and (x["status"] == "APPROVED" or x["break_id"] in on_page)]
    open_ = [x for x in b if x["status"] in ("PROPOSED", "RETURNED") and x["break_id"] not in on_page]
    parts = [f"{len(stp)} applied straight through" + (f" ({len(pending)} to spot-check)" if pending else "") if stp else "",
             f"{len(person)} approved by the checker" if person else "", f"{len(step)} settled on the step pages" if step else ""]
    head = f"The agents worked on {plural(len(b), 'item')} today: " + ", ".join(p for p in parts if p)
    head = head.rstrip(": ") + (f"; {len(open_)} wait for you." if open_ else "; nothing waits for you.")
    return {"headline": head, "total": len(b), "straight_through": len(stp), "by_checker": len(person), "on_step_pages": len(step), "open": len(open_),
            "spot_check": [{"break_id": x["break_id"], "title": x["title"], "break_type": x["break_type"]} for x in pending]}


def _memo_facts(m, date, sub):
    prior = (m.run_pg("SELECT MAX(as_of_date) AS d FROM calculation_results WHERE as_of_date < %s", (date,)) or [{}])[0].get("d")
    lcr = m.run_pg("""SELECT as_of_date, entity_id, ROUND(lcr_ratio::NUMERIC, 4) AS lcr, ROUND(total_hqla::NUMERIC, 1) AS hqla,
                             ROUND(total_net_cash_outflows::NUMERIC, 1) AS nco FROM calculation_results
                      WHERE as_of_date IN (%s, %s) ORDER BY entity_id, as_of_date""", (date, prior or date))
    tables = m.run_pg("""SELECT table_code, as_of_date, COUNT(*) AS records, ROUND(SUM(reported_amount_usd)::NUMERIC, 1) AS amount_usd FROM filing_records
                         WHERE as_of_date IN (%s, %s) GROUP BY 1, 2 ORDER BY 1, 2""", (date, prior or date))
    people = m.run_pg("""SELECT b.break_type, b.title, d.action, d.reason_code, d.note, d.decided_by FROM break_decisions d JOIN breaks b USING (break_id)
                         WHERE b.as_of_date = %s ORDER BY d.decided_at""", (date,))
    counts = lambda sql: (m.run_pg(sql, (date,)) or [{}])[0].get("n") or 0
    return {"as_of_date": date, "prior_date": str(prior) if prior else None,
            "release": {"run": sub.get("run_number"), "status": sub.get("status"), "released_by": sub.get("released_by"),
                        "files": [{"type": f["file_type"], "records": f.get("record_count"), "xsd_valid": f.get("xsd_valid")} for f in sub.get("files") or []]},
            "lcr": lcr, "tables": tables, "agents": agents_summary(m, date),
            "decisions": [{k: d[k] for k in ("break_type", "title", "action", "reason_code", "note", "decided_by")} for d in people][:40],
            "explained_exceptions": counts("SELECT COUNT(*) AS n FROM validation_decisions WHERE as_of_date = %s AND action = 'explain'"),
            "corrections": counts("SELECT COUNT(*) AS n FROM position_corrections WHERE as_of_date = %s AND status <> 'WITHDRAWN'"),
            "dq_fixes": counts("SELECT COUNT(*) AS n FROM dq_fixes WHERE as_of_date = %s AND status <> 'WITHDRAWN'"),
            "overrides": m.run_pg("SELECT actor, note FROM submission_review WHERE as_of_date = %s AND action = 'OVERRIDE_REQUESTED'", (date,))}


@router.get("/{date}/release-memo")
def release_memo(date: str, refresh: bool = False):
    """The release memo for the approver (step 5): what is released, what changed since the prior reporting day, how every item was settled,
    overrides - written by the AI from those facts only, kept per reporting run and put into the examiner pack."""
    m = wb._deps()
    sub = m.get_submission(date)
    run = sub.get("run_number")
    if run is None:
        raise HTTPException(404, "No reporting run for this date")
    if not refresh:
        got = m.run_pg("SELECT memo, facts, made_by, created_at FROM release_memos WHERE as_of_date = %s AND run_number = %s", (date, run))
        if got:
            return {"run_number": run, **got[0]}
    facts = _memo_facts(m, date, sub)
    prompt = ("You write the release memo for the approver of the Federal Reserve FR 2052a filing below, before they approve it. Use ONLY the facts in "
              "the JSON - never add a number, product, rule or name that is not in it. Plain text, short bullet points under these headings: "
              "1. What is released (run, files, records, XSD). 2. What changed since the prior reporting day (LCR per entity, HQLA, net cash outflows, the "
              "tables that moved most). 3. How the open items were settled (straight through by the agents, by the checker, on the step pages, explained "
              "exceptions, corrections). 4. Overrides and points for the approver (say 'none' if there are none). At most 220 words.\n\nFACTS:\n"
              + json.dumps(facts, default=str))
    memo = wb._ai_text(m, prompt, tokens=700).strip()
    with m.get_pg() as conn:
        with conn.cursor() as c:
            c.execute("""INSERT INTO release_memos VALUES (%s, %s, %s, %s, %s, NOW()) ON CONFLICT (as_of_date, run_number)
                         DO UPDATE SET memo = EXCLUDED.memo, facts = EXCLUDED.facts, made_by = EXCLUDED.made_by, created_at = NOW()""",
                      (date, run, memo, json.dumps(facts, default=str), wb.AI_MODEL))
        conn.commit()
    return {"run_number": run, "memo": memo, "facts": facts, "made_by": wb.AI_MODEL, "created_at": _now().isoformat(timespec="seconds")}


@router.get("/learning")
def learning():
    """The learning loop: the same fix made on several reporting days -> the agents propose the permanent fix at the source
    (master data, product map, source system, rule calibration), for the data owner."""
    m = wb._deps()
    out = []
    for r in m.run_pg("""SELECT field, old_value, new_value, COUNT(*) AS n, ARRAY_AGG(DISTINCT as_of_date ORDER BY as_of_date) AS days FROM dq_fixes
                         WHERE status <> 'WITHDRAWN' AND field NOT IN ('_exclude') GROUP BY 1, 2, 3 HAVING COUNT(DISTINCT as_of_date) >= 2"""):
        what = (f"product code {r['old_value']} is mapped to {r['new_value']} again and again" if r["field"] == "_map_code" else
                f"{r['field']} {r['old_value'] or '(empty)'} is corrected to {r['new_value']} again and again")
        out.append({"kind": "Data quality fix", "pattern": what, "days": [str(d) for d in r["days"]], "count": r["n"],
                    "proposal": "Make the mapping permanent in the product map" if r["field"] == "_map_code" else
                                f"Correct {r['field']} in the source system (or the customer / security master) so the record arrives right",
                    "owner": "Source system owner"})
    for r in m.run_pg("""SELECT field, new_value, COUNT(*) AS n, ARRAY_AGG(DISTINCT as_of_date ORDER BY as_of_date) AS days FROM position_corrections
                         WHERE status <> 'WITHDRAWN' GROUP BY 1, 2 HAVING COUNT(DISTINCT as_of_date) >= 2"""):
        out.append({"kind": "Position correction", "pattern": f"{r['field']} is corrected to {r['new_value']} on several days", "days": [str(d) for d in r["days"]],
                    "count": r["n"], "proposal": f"Fix {r['field']} at the source (or in the enrichment rules) instead of correcting the report each day",
                    "owner": "Source system owner"})
    for r in m.run_pg("""SELECT v.rule_id, MAX(r.check_name) AS rule_name, COUNT(*) AS n, ARRAY_AGG(DISTINCT v.as_of_date ORDER BY v.as_of_date) AS days
                         FROM validation_decisions v LEFT JOIN rules_fed_psv r ON r.check_id = v.rule_id WHERE v.action = 'explain'
                         GROUP BY 1 HAVING COUNT(DISTINCT v.as_of_date) >= 2"""):
        out.append({"kind": "Explained exception", "pattern": f"{r['rule_id']} {r['rule_name'] or ''} is explained as correct on several days".replace("  ", " "),
                    "days": [str(d) for d in r["days"]], "count": r["n"],
                    "proposal": f"Recalibrate {r['rule_id']} (threshold / scope) or record a standing explanation, so the same exception does not come back daily",
                    "owner": "Regulatory reporting (rule owner)"})
    return sorted(out, key=lambda x: (-len(x["days"]), -x["count"]))


@router.get("/accuracy")
def accuracy():
    """How the agents do, from the checker's decisions (Lakebase) and the latest GenAI evaluation of the champion (notebook 10)."""
    m = wb._deps()
    rows = m.run_pg("""SELECT p.agent, COUNT(DISTINCT p.proposal_id) AS proposals,
                              COUNT(*) FILTER (WHERE d.action = 'APPROVE' AND d.reason_code NOT IN ('STEP', 'RERUN', 'STP', 'SC')) AS approved,
                              COUNT(*) FILTER (WHERE d.action = 'APPROVE_WITH_EDIT') AS edited,
                              COUNT(*) FILTER (WHERE d.action = 'RETURN') AS returned,
                              COUNT(*) FILTER (WHERE d.reason_code = 'STP') AS straight_through,
                              COUNT(*) FILTER (WHERE d.action = 'SPOT_CHECK_CONFIRM') AS spot_confirmed,
                              COUNT(*) FILTER (WHERE d.action = 'SPOT_CHECK_DISAGREE') AS spot_disagreed
                       FROM proposals p LEFT JOIN break_decisions d ON d.proposal_id = p.proposal_id
                       WHERE COALESCE(p.rule_check ->> 'detail', '') <> 'Decided on the step page' GROUP BY 1 ORDER BY 2 DESC""")
    for r in rows:
        judged = r["approved"] + r["edited"] + r["returned"]
        r["acceptance"] = round((r["approved"] + r["edited"]) / judged, 3) if judged else None
        r["edit_rate"] = round(r["edited"] / judged, 3) if judged else None
        spot = r["spot_confirmed"] + r["spot_disagreed"]
        r["spot_agreement"] = round(r["spot_confirmed"] / spot, 3) if spot else None
    try:
        ev = m.run_pg("""SELECT metric, value, n, eval_run FROM ai_evaluation WHERE suggestion_type = 'AGENT:all'
                           AND eval_run = (SELECT MAX(eval_run) FROM ai_evaluation WHERE suggestion_type = 'AGENT:all') ORDER BY metric""")
    except HTTPException:
        ev = []
    return {"agents": rows, "evaluation": ev, "model": _served_version(m)}
