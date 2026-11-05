#!/bin/zsh
# 6G XML (latest run) vs the report tables: records and amounts per reporting entity x table.
set -a; . "$(cd "$(dirname "$0")/../.." && pwd)/.env"; set +a   # settings: the repo's .env (see .env.example)
C=$FR2052A_CATALOG
DATES=(2026-02-23 2026-02-24 2026-02-25 2026-02-26 2026-02-27); (( $# )) && DATES=("$@")
for d in $DATES; do
  for t in Primary Reduced; do bash "$(dirname "$0")/q.sh" "SELECT xml_content FROM $C.reg_2052a.submission_files WHERE as_of_date='$d' AND file_type='$t' AND run_number=(SELECT max(run_number) FROM $C.reg_2052a.submission_files WHERE as_of_date='$d')" | tail -n +2 > x_${d}_$t.xml; done
  bash "$(dirname "$0")/q.sh" "SELECT reporting_entity, table_code, count(*) n, round(sum(reported_amount),4) amt FROM $C.reg_2052a.v_filing_records WHERE as_of_date='$d' GROUP BY 1,2 ORDER BY 1,2" > db_$d.txt
  python3 -I "$(dirname "$0")/xmlcheck.py" $d | grep -v scopes
done
