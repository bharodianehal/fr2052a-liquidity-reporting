import json, subprocess, psycopg2
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fr2052a_env import need
PROFILE = need("DATABRICKS_CONFIG_PROFILE")
def api(m, p, b=None):
    cmd = ["databricks", "api", m, p, "-p", PROFILE] + (["--json", json.dumps(b)] if b else [])
    return json.loads(subprocess.run(cmd, capture_output=True, text=True).stdout)
ep = "projects/fr2052a/branches/production/endpoints/primary"
conn = psycopg2.connect(host=api("get", f"/api/2.0/postgres/{ep}")["status"]["hosts"]["host"], port=5432, dbname="fr2052a",
                        user=json.loads(subprocess.run(["databricks", "current-user", "me", "-p", PROFILE], capture_output=True, text=True).stdout)["userName"],
                        password=api("post", "/api/2.0/postgres/credentials", {"endpoint": ep})["token"], sslmode="require",
                        options="-c search_path=app_serving,public")   # as the app: synced tables first
import sys
c=conn.cursor(); c.execute(sys.argv[1]); print([d[0] for d in c.description])
for r in c.fetchall(): print(r)
