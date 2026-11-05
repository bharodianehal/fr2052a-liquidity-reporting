"""Load the regulatory text the AI agents cite - the FR 2052a Instructions (by product definition and by page) and 12 CFR 249
(Regulation WW, by section), in passages - into the UC volume reference.docs and the Delta table reference.reg_text_chunks
(CDF on), then sync the Vector Search index reference.reg_text_index (managed embeddings, databricks-gte-large-en).

The passages are in the repo: reference_data/regtext/reg_text_chunks.jsonl (rebuild them with scripts/regtext/chunk_instructions.py
and chunk_cfr249.py when the documents change). The endpoint fr2052a-vs is in the platform bundle (resources/ai.yml); the index
is in the app bundle (it needs this table) - on the first build it does not exist yet and the sync is skipped.

Runs as task regulatory_text of job fr2052a-pipeline:
  deploy/regulatory_text_index.py --catalog <catalog> --warehouse <warehouse id> --root <bundle file path>
"""
import argparse
import pathlib
import time

from databricks.sdk import WorkspaceClient

ap = argparse.ArgumentParser()
ap.add_argument("--catalog", required=True)
ap.add_argument("--warehouse", required=True)
ap.add_argument("--profile", default=None, help="CLI profile (omit inside a job)")
ap.add_argument("--root", default=None, help="the repo / bundle root (a job passes ${workspace.file_path}: no __file__ in a serverless Python task)")
a = ap.parse_args()
C = a.catalog
w = WorkspaceClient(profile=a.profile) if a.profile else WorkspaceClient()
ROOT = pathlib.Path(a.root) if a.root else pathlib.Path(__file__).resolve().parent.parent
CHUNKS = ROOT / "reference_data" / "regtext" / "reg_text_chunks.jsonl"


def sql(q):
    st = w.statement_execution.execute_statement(warehouse_id=a.warehouse, statement=q, wait_timeout="50s")
    while st.status.state.value in ("PENDING", "RUNNING"):
        time.sleep(2)
        st = w.statement_execution.get_statement(st.statement_id)
    if st.status.state.value != "SUCCEEDED":
        raise RuntimeError(f"{q[:80]}: {st.status.error.message if st.status.error else st.status.state}")
    return st


vol = f"/Volumes/{C}/reference/docs"
with open(CHUNKS, "rb") as fh:
    w.files.upload(f"{vol}/reg_text_chunks.jsonl", fh, overwrite=True)
sql(f"""CREATE OR REPLACE TABLE {C}.reference.reg_text_chunks (chunk_id STRING NOT NULL, doc STRING, section STRING, pid STRING, page INT, text STRING)
        TBLPROPERTIES (delta.enableChangeDataFeed = true) COMMENT 'FR 2052a Instructions and 12 CFR 249 in passages - the evidence the agents cite'""")
sql(f"""INSERT INTO {C}.reference.reg_text_chunks SELECT chunk_id, doc, section, pid, CAST(page AS INT), text
        FROM read_files('{vol}/reg_text_chunks.jsonl', format => 'json', schema => 'chunk_id STRING, doc STRING, section STRING, pid STRING, page INT, text STRING')""")
n = sql(f"SELECT COUNT(*) FROM {C}.reference.reg_text_chunks").result.data_array[0][0]
print("chunks:", n)

idx = f"{C}.reference.reg_text_index"
try:
    w.vector_search_indexes.get_index(idx)
except Exception:
    print(f"index {idx} not there yet - the app bundle creates it (first build); nothing to sync")
else:
    w.vector_search_indexes.sync_index(idx)
    print("index", idx, "sync started")
