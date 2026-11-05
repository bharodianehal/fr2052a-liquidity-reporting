#!/bin/zsh
# QA helper: run from any directory; settings from the repo's .env.
# usage: q.sh "<sql>"
set -a; . "$(cd "$(dirname "$0")/../.." && pwd)/.env"; set +a   # settings: the repo's .env (see .env.example)
body=$(python3 -I -c 'import json,sys,os;print(json.dumps({"warehouse_id":os.environ["FR2052A_WAREHOUSE"],"statement":sys.argv[1],"wait_timeout":"50s","catalog":os.environ["FR2052A_CATALOG"]}))' "$1")
databricks api post /api/2.0/sql/statements -p $DATABRICKS_CONFIG_PROFILE --json "$body" | python3 -I -c '
import json,sys;r=json.load(sys.stdin);s=r.get("status",{})
if s.get("state")!="SUCCEEDED": print(s); sys.exit()
cols=[c["name"] for c in r["manifest"]["schema"]["columns"]];print(" | ".join(cols))
for row in r.get("result",{}).get("data_array",[]): print(" | ".join(str(x) for x in row))'
