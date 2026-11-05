# UAT driver: the analyst's day for one date through the app's API (the same calls the screens make).
# usage: uat.py <date> <phase>   phase A = steps 1-3 + re-run enrichment, R = the checker on the agents' proposals (return, run the agent
# again, two checkers at once, bulk approve), B = step 4 (exceptions + comments) + re-run validation, C = step 5 (Generate, approve, four eyes)
import concurrent.futures
import json, subprocess, sys, time, urllib.parse, urllib.request
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fr2052a_env import need
PROFILE = need("DATABRICKS_CONFIG_PROFILE")

D, PHASE = sys.argv[1], sys.argv[2]
U = need("FR2052A_APP_URL") + "/api"
TOK = json.loads(subprocess.run(["databricks", "auth", "token", "-p", PROFILE], capture_output=True, text=True).stdout)["access_token"]
ok_all = True


def call(method, path, body=None, expect=200):
    req = urllib.request.Request(U + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {TOK}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            code, out = r.status, json.loads(r.read() or "null")
    except urllib.error.HTTPError as e:
        code, out = e.code, json.loads(e.read() or "null")
    if code != expect:
        check(False, f"{method} {path} -> {code} (expected {expect}): {str(out)[:200]}")
    return out


def check(cond, msg):
    global ok_all
    ok_all &= bool(cond)
    print(("  PASS " if cond else "  FAIL ") + msg)


def steps():
    return {s["key"]: s for s in call("GET", f"/wb/today/{D}")["steps"]}


if PHASE == "A":
    print(f"UAT {D} - Today")
    st = steps()
    print("  steps:", {k: v["state"] for k, v in st.items()})
    b = call("GET", f"/wb/agents/{D}/review")   # Today > Where it stands
    check(b.get("status") in ("review", "signoff", "blocked", "submitted", "not_run"), f"where it stands: '{b.get('status')}' - to review: {b.get('to_review_label') or 'nothing'}")

    print("Step 1 Collect")
    c = call("GET", f"/wb/collect/{D}")
    bad = [m for m in c["monitor"] if m.get("status") != "PASS"]
    check(len(c["monitor"]) == 10 and not bad, f"{len(c['monitor'])} feeds received, {len(bad)} incomplete vs the 5-day median; {sum(int(f['bronze']) for f in c['feeds'])} position records in Bronze")

    print("Step 2 Data quality")
    q = call("GET", f"/wb/dq/{D}/queue")
    opn = [r for r in q if r["state"] == "open"]
    check(len(q) == int(st["dq"]["facts"].get("quarantined") or 0) + sum(1 for r in q if r["state"] == "warning"),
          f"queue {len(q)} item(s) = quarantined {st['dq']['facts'].get('quarantined')} (+ warnings)")
    for r in opn:
        ai = call("GET", f"/wb/dq/{D}/suggest/{urllib.parse.quote(r['record_id'])}")
        print(f"    {r['record_id']} {r['rules']}: AI {ai.get('action')} {ai.get('field')}={ai.get('new_value')} ({ai.get('confidence')})")
        body = ({"action": "map_code", "new_value": ai["new_value"]} if ai.get("action") == "map_code" else
                {"action": "exclude"} if ai.get("action") == "exclude" else
                {"action": "accept_ai", "edits": {ai["field"]: ai["new_value"]}})
        call("POST", f"/wb/dq/{D}/resolve", {"record_id": r["record_id"], "reason": f"UAT: AI fix accepted - {ai.get('rationale', '')[:150]}", **body})
    q2 = call("GET", f"/wb/dq/{D}/queue")
    check(not [r for r in q2 if r["state"] == "open"], f"every quarantined record resolved ({len(opn)} resolved now)")

    print("Step 3 PID enrichment")
    s = call("GET", f"/wb/enrich/{D}")
    e = call("GET", f"/wb/enrich/{D}/queue")
    todo = [x for x in e if x["status"] == "PROPOSED"]
    print(f"    {len(s['tables'])} tables enriched; {len(todo)} item(s) to review: {[x['kind'] + ' ' + x['title'] for x in todo]}")
    for x in todo:
        call("POST", f"/wb/ai/{x['id']}/decide", {"decision": "ACCEPTED", "note": "UAT: AI suggestion accepted"})
    e2 = call("GET", f"/wb/enrich/{D}/queue")
    check(not [x for x in e2 if x["status"] == "PROPOSED"], "every enrichment suggestion decided")
    if opn or todo:
        r = call("POST", f"/wb/rerun-from-dq/{D}", {})
        check(bool(r.get("run_id")), f"Re-run from data quality started: job run {r.get('run_id')}")
        open(f"uat_{D}_rerun.txt", "w").write(str(r.get("run_id")))
    else:
        print("  nothing changed in steps 2-3: no re-run needed")
        open(f"uat_{D}_rerun.txt", "w").write("")

elif PHASE == "R":
    print(f"UAT {D} - the checker on the agents' proposals")
    brk = call("GET", f"/wb/agents/{D}/breaks?sync=false")
    prop = [b for b in brk if b["status"] == "PROPOSED"]
    check(prop, f"{len(prop)} proposal(s) waiting for the checker")
    one = next((b for b in prop if not b.get("bulk_ok")), None)
    if one:
        bid = one["break_id"]
        r = call("POST", f"/wb/agents/break/{bid}/decide", {"action": "return", "reason_code": "RT-04", "note": "UAT: re-check against the Instructions"})
        check(r.get("status") == "RETURNED", f"{bid} returned to the agent (RT-04)")
        call("POST", f"/wb/agents/break/{bid}/decide", {"action": "return", "reason_code": "RT-04", "note": "again"}, expect=409)
        check(True, "a second decision on the returned break is refused (409)")
        t = time.time()
        r = call("POST", f"/wb/agents/break/{bid}/rerun", {})
        b2 = call("GET", f"/wb/agents/break/{bid}")
        pr = b2.get("proposal") or {}
        check(b2["break"]["status"] == "PROPOSED", f"run the agent again: new proposal {pr.get('proposal_id')} made by {pr.get('model')} in {time.time() - t:.0f}s")
        # two checkers approve the same proposal at the same moment: exactly one decision
        with concurrent.futures.ThreadPoolExecutor(2) as ex:
            codes = []
            def both():
                req = urllib.request.Request(U + f"/wb/agents/break/{bid}/decide", method="POST", headers={"Authorization": f"Bearer {TOK}", "Content-Type": "application/json"},
                                             data=json.dumps({"action": "approve", "reason_code": "RC-05", "note": "UAT: two checkers at once"}).encode())
                try:
                    with urllib.request.urlopen(req, timeout=180) as x:
                        return x.status
                except urllib.error.HTTPError as e:
                    return e.code
            codes = sorted(ex.map(lambda _: both(), range(2)))
        check(codes == [200, 409], f"two checkers at once: {codes} (one decision, one refused)")
    bulk = [b["break_id"] for b in call("GET", f"/wb/agents/{D}/breaks?sync=false") if b["status"] == "PROPOSED" and b.get("bulk_ok")]
    if bulk:
        r = call("POST", f"/wb/agents/{D}/approve-bulk", {"break_ids": bulk, "reason_code": "RC-05", "note": "UAT: bulk approval"})
        check(r.get("approved") == len(bulk) and not r.get("failed"), f"bulk approval: {r}")
    ev = call("GET", f"/wb/agents/{D}/audit?who=decisions")["events"]
    check(len(ev) > 0, f"Audit shows {len(ev)} decision event(s); latest: {ev[0]['action'][:80] if ev else '-'}")

elif PHASE == "B":
    print(f"UAT {D} - after the re-run")
    st = steps()
    print("  steps:", {k: v["state"] for k, v in st.items()})
    f = st["enrich"]["facts"]
    check(int(f.get("customer_pending") or 0) == 0 and int(f.get("no_rule") or 0) == 0, f"enrichment: {f.get('derived')} of {f.get('positions')} positions with a PID, none held out")
    check(st["dq"]["state"] == "done", f"data quality step: {st['dq']['state']}")
    print("Step 4 Validate")
    q = call("GET", f"/wb/validate/{D}/queue")
    opn = [x for x in q if x["state"] == "open"]
    print(f"    {len(q)} exception(s), {len(opn)} open: {sorted({x['rule_id'] for x in opn})}")
    n_fix = n_expl = 0
    for x in opn:
        ai = call("GET", f"/wb/validate/{D}/suggest?rule_id={urllib.parse.quote(x['rule_id'])}&item_key={urllib.parse.quote(x['item_key'])}")
        if ai.get("action") == "correct":
            call("POST", f"/wb/validate/{D}/resolve", {"rule_id": x["rule_id"], "item_key": x["item_key"], "record_key": x["record_key"], "action": "accept_ai",
                                                       "position_id": ai["position_id"], "field": ai["field"], "new_value": ai["new_value"], "note": "UAT: " + ai.get("explanation", "")[:300]})
            n_fix += 1
            print(f"    {x['rule_id']} {x['item_key'][:40]}: corrected {ai['field']} {ai.get('old_value')} -> {ai['new_value']}")
        else:
            call("POST", f"/wb/validate/{D}/resolve", {"rule_id": x["rule_id"], "item_key": x["item_key"], "action": "explain",
                                                       "note": "UAT: " + (ai.get("explanation") or "Reviewed; the data is correct.")[:300]})
            n_expl += 1
    q2 = call("GET", f"/wb/validate/{D}/queue")
    check(not [x for x in q2 if x["state"] == "open"], f"every exception resolved: {n_fix} corrected (AI), {n_expl} explained")
    com = [x for x in call("GET", f"/wb/ai/{D}") if x["suggestion_type"] in ("COMMENT_DRAFT", "VARIANCE_COMMENTARY") and x["status"] == "PROPOSED"]
    for x in com:
        call("POST", f"/wb/ai/{x['suggestion_id']}/decide", {"decision": "ACCEPTED", "note": "UAT: comment accepted"})
    if com:
        call("POST", f"/wb/ai/{com[0]['suggestion_id']}/decide", {"decision": "REJECTED", "note": "UAT: second decision"}, expect=409)
    check(True, f"{len(com)} comment(s) for the Fed accepted; a second decision is refused")
    if n_fix:
        r = call("POST", f"/wb/revalidate/{D}", {})
        check(bool(r.get("run_id")), f"Re-run validation started: job run {r.get('run_id')}")
        open(f"uat_{D}_reval.txt", "w").write(str(r.get("run_id")))
    else:
        open(f"uat_{D}_reval.txt", "w").write("")

elif PHASE == "C":
    print(f"UAT {D} - after re-validation")
    st = steps()
    print("  steps:", {k: v["state"] for k, v in st.items()})
    q = call("GET", f"/wb/validate/{D}/queue")
    print(f"    validate queue: {len(q)} item(s), states {sorted({x['state'] for x in q})}")
    check(not [x for x in q if x["state"] == "open"], "no open exception after the re-run")
    print("Step 5 Generate 6G & release")
    sub = call("GET", f"/submission/{D}")
    files = sub.get("files", [])
    check(files and all(x["xsd_valid"] for x in files), f"run {sub.get('run_number')} v{sub.get('version')}: {len(files)} 6G files, all valid against the Fed XSD: {[x['file_type'] + ' ' + str(x['record_count']) for x in files]}")
    b = call("GET", f"/wb/agents/{D}/review")
    check(not any(s_["open"] or s_.get("waiting") for s_ in b["steps"][:4]), f"steps 1-4 settled; step 5: {b['steps'][4].get('state')}")
    r = call("POST", f"/wb/generate/{D}", {})
    check(bool(r.get("run_id")), f"Generate 6G for release started: job run {r.get('run_id')}")
    while True:
        g = call("GET", f"/wb/generate/{D}")
        if g.get("state") in ("TERMINATED", "INTERNAL_ERROR", "SKIPPED"):
            break
        time.sleep(30)
    check(g.get("result") == "SUCCESS", f"generation {g.get('result')} (released by {g.get('by')})")
    sub = call("GET", f"/submission/{D}")
    files = sub.get("files", [])
    check(files and all(x["xsd_valid"] for x in files), f"release run {sub.get('run_number')}: {len(files)} 6G files valid against the Fed XSD")
    check(sub.get("status") == "READY_FOR_REVIEW", f"run status {sub.get('status')}")
    call("POST", f"/submission/{D}/review", {"action": "APPROVED", "note": "UAT: reviewed and approved"})
    check(call("GET", f"/submission/{D}").get("status") == "APPROVED", "approved")
    call("POST", f"/submission/{D}/review", {"action": "SUBMITTED", "note": "UAT: four-eyes test"}, expect=409)
    check(call("GET", f"/submission/{D}").get("status") == "APPROVED", "the approver cannot also mark it submitted (four eyes): refused, still APPROVED")
    b = call("GET", f"/wb/agents/{D}/review")
    print(f"  where it stands: {b.get('status')} - step 5: {b['steps'][4].get('close_label')}")

print("UAT phase", PHASE, "RESULT:", "PASS" if ok_all else "FAIL")
