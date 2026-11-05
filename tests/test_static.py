"""Code checks that need no running system: the frontend calls only routes that exist, the SQL sent to Lakebase is Postgres, the app
runs on the Apps runtime (Python < 3.12), the wording rules."""
import ast
import glob
import os
import re

import pytest

from conftest import ROOT, main, wb, agents

APP = {f: open(f).read() for f in glob.glob(os.path.join(ROOT, "app", "*.py"))}
FRONTEND = {f: open(f).read() for f in glob.glob(os.path.join(ROOT, "app", "frontend", "src", "**", "*.js*"), recursive=True)}


def routes():
    out = set()
    for r in list(main.app.routes) + list(wb.router.routes) + list(agents.router.routes):
        for m in getattr(r, "methods", None) or []:
            out.add((m, re.sub(r"\{[^}]+\}", "{}", r.path)))
    return out


def test_every_frontend_call_has_a_backend_route():
    have = routes()
    api = FRONTEND[os.path.join(ROOT, "app", "frontend", "src", "api.js")]
    calls = [("POST" if fn == "postJson" else "GET", u) for fn, u in re.findall(r"(fetchJson|postJson)\(`([^`]+)`", api)]
    calls += [("GET", u) for u in re.findall(r"=> `\$\{BASE\}([^`]+)`", api)] + [("GET", u.replace("/api", "", 1)) for u in re.findall(r"=> `(/api[^`]+)`", api)]
    calls += [("GET", u.replace("/api", "", 1)) for f, s in FRONTEND.items() for u in re.findall(r"fetch\('(/api/[^']+)'\)", s)]
    calls += [("POST" if fn == "postJson" else "GET", u) for fn, u in re.findall(r"(fetchJson|postJson)\('([^']+)'", api)]
    missing = []
    for method, url in calls:
        path = "/api" + re.sub(r"\$\{[^}]+\}", "{}", url).split("?")[0]
        path = re.sub(r"\{\}[^/]*", "{}", path) if not path.endswith("{}") or path.count("{}") else path
        path = re.sub(r"(?<=[a-z])\{\}$", "", path)   # a template suffix (e.g. ${refresh ? '?refresh=true' : ''}) is not a path segment
        if (method, path) not in have:
            missing.append(f"{method} {path}")
    assert len(calls) > 60, f"only {len(calls)} calls parsed from api.js"
    assert not missing, missing


SPARK_ONLY = re.compile(r"\bQUALIFY\b|GROUP BY ALL|COLLECT_SET|ARRAY_JOIN|get_json_object|\bRLIKE\b|\{C\}\.|\{CATALOG\}\.|\bFIRST\(|\bNVL\(")


def sql_of(call):
    a = call.args[0] if call.args else None
    if isinstance(a, ast.Constant) and isinstance(a.value, str):
        return a.value
    if isinstance(a, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{" + ast.unparse(v.value) + "}" for v in a.values)
    return ""


def test_sql_sent_to_lakebase_is_postgres():
    bad = []
    for f, src in APP.items():
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) in ("run_wh", "run_pg"):
                sql = sql_of(node)
                if SPARK_ONLY.search(sql):
                    bad.append(f"{os.path.basename(f)}:{node.lineno} {SPARK_ONLY.search(sql).group(0)}")
    assert not bad, bad


def test_no_backslash_in_fstring_expressions():   # the Apps runtime is Python < 3.12
    hits = []
    for f, src in APP.items():
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.JoinedStr):
                for v in node.values:
                    if isinstance(v, ast.FormattedValue) and "\\" in (ast.get_source_segment(src, v.value) or ""):
                        hits.append(f"{os.path.basename(f)}:{node.lineno}")
    assert not hits, hits


def test_wording_rules():
    hits = [f"{os.path.basename(f)}:{i}" for f, s in {**APP, **FRONTEND}.items() for i, l in enumerate(s.splitlines(), 1) if re.search("copilot", l, re.I)]
    assert not hits, hits


def test_audit_tables_are_append_only_in_notebook_07():
    nb07 = open(os.path.join(ROOT, "notebooks", "07_Lakebase_Sync.py")).read()
    revoke = next(l for l in nb07.splitlines() if "REVOKE UPDATE, DELETE" in l)
    for t in ("agent_events", "break_decisions", "ai_decisions"):
        assert f"public.{t}" in revoke


def test_app_never_updates_or_deletes_the_audit_trail():
    hits = [f"{os.path.basename(f)}" for f, s in APP.items() for t in ("agent_events", "break_decisions", "ai_decisions")
            if re.search(rf"(UPDATE|DELETE FROM)\s+(public\.)?{t}\b", s)]
    assert not hits, hits
