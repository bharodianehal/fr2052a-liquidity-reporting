#!/usr/bin/env bash
# Calls every GET endpoint the frontend uses for one date; prints status + first bytes. Usage: app_test.sh [date]
set -a; . "$(cd "$(dirname "$0")/../.." && pwd)/.env"; set +a   # settings: the repo's .env (see .env.example)
D=${1:-2026-02-27}
T=$(databricks auth token -p $DATABRICKS_CONFIG_PROFILE | python3 -I -c "import json,sys;print(json.load(sys.stdin)['access_token'])")
U=$FR2052A_APP_URL
RK=$(curl -s -H "Authorization: Bearer $T" "$U/api/filing/$D/table/O.D" | python3 -c "import json,sys; d=json.load(sys.stdin); r=d if isinstance(d,list) else d.get('rows',[]); print(r[0]['record_key'] if r else 'x')" 2>/dev/null)
BRK=$(curl -s -H "Authorization: Bearer $T" "$U/api/wb/agents/$D/breaks" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[0]['break_id'] if d else 'x')" 2>/dev/null)
for p in /api/dates /api/tables /api/filing/$D/summary /api/filing/$D/table/O.D /api/submission/$D /api/submission-history /api/validation/$D \
  /api/config/products /api/config/standard-products /api/config/source-products /api/config/pid-rules /api/config/customers /api/config/legal-entities \
  /api/config/fed-psv /api/config/templates /api/config/stwf-rules /api/config/counterparties /api/config/collateral /api/config/maturity-buckets \
  /api/config/header /api/config/firm-schema /api/config/dq-rules /api/config/lcr-rules /api/config/validation-rules /api/config/spec-rules \
  /api/pipeline/runs /api/workspace-url \
  /api/wb/calendar /api/wb/today/$D /api/wb/collect/$D /api/wb/collect/$D/record/DEP-$D-00001 /api/wb/ai/$D /api/wb/entity-summary/$D /api/wb/variance/$D \
  /api/wb/lineage/$D/record/$RK "/api/wb/lineage/$D/position/DEP-$D-00014%23UNI" /api/wb/lineage/$D/source/DEP-$D-00002 \
  /api/wb/rerun-from-dq/$D /api/wb/dq/$D/queue /api/wb/enrich/$D /api/wb/enrich/$D/table/O.D/pids "/api/wb/enrich/$D/positions?code=O.D" /api/wb/enrich/$D/queue \
  "/api/wb/correct/$D?record_key=$RK" /api/wb/revalidate/$D /api/wb/generate/$D /api/wb/validate/$D/queue "/api/wb/metadata?q=O.D" \
  /api/wb/lcr/reference /api/wb/lcr/$D/mapping "/api/wb/lcr/$D/calculation?entity=ENT001" "/api/wb/lcr/disclosure?start=2026-02-23&end=$D&entity=ENT001" \
  "/api/wb/lcr/disclosure/draft?start=2026-02-23&end=$D&entity=ENT001" \
  /api/wb/agents/$D/breaks /api/wb/agents/break/$BRK /api/wb/agents/$D/today /api/wb/agents/$D/audit /api/wb/agents/$D/source-fixes /api/wb/agents/$D/review; do
  out=$(curl -s -o ${TMPDIR:-/tmp}/app_test_body -w "%{http_code}" -H "Authorization: Bearer $T" "$U$p")
  printf "%s %-45s %s\n" "$out" "$p" "$(head -c 140 ${TMPDIR:-/tmp}/app_test_body | tr '\n' ' ')"
done
