"""The identity the agents' serving endpoint runs as: service principal fr2052a-agents with an OAuth secret in the secret scope
fr2052a (agents-client-id / agents-client-secret; the scope is in the platform bundle, resources/ai.yml) and CAN_USE on the
SQL warehouse. Idempotent: an existing principal and a stored secret that belongs to it are kept.

Service principals are not a bundle resource type, so this runs as the first task (agents_identity) of the job
fr2052a-register-agents. It prints the client id: put it into the platform overrides as agents_sp_client_id - notebooks 07
and 08 then grant it read on Delta and Lakebase, and the app bundle gives it its Lakebase role.

  deploy/agents_identity.py --warehouse <warehouse id>
"""
import argparse

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import iam, sql

NAME, SCOPE = "fr2052a-agents", "fr2052a"

ap = argparse.ArgumentParser()
ap.add_argument("--warehouse", required=True)
ap.add_argument("--profile", default=None, help="CLI profile (omit inside a job)")
a = ap.parse_args()
w = WorkspaceClient(profile=a.profile) if a.profile else WorkspaceClient()

sp = next(iter(w.service_principals.list(filter=f'displayName eq "{NAME}"')), None)
if sp is None:
    sp = w.service_principals.create(display_name=NAME, active=True,
                                     entitlements=[iam.ComplexValue(value="workspace-access"), iam.ComplexValue(value="databricks-sql-access")])
    print("created service principal", NAME, sp.application_id)
else:
    print("service principal", NAME, "exists:", sp.application_id)


def stored(key):
    try:
        import base64
        return base64.b64decode(w.secrets.get_secret(SCOPE, key).value).decode()
    except Exception:
        return None


if stored("agents-client-id") == sp.application_id and stored("agents-client-secret"):
    print(f"OAuth secret already in scope {SCOPE}")
else:
    secret = w.service_principal_secrets_proxy.create(sp.id)
    w.secrets.put_secret(SCOPE, "agents-client-id", string_value=sp.application_id)
    w.secrets.put_secret(SCOPE, "agents-client-secret", string_value=secret.secret)
    print(f"new OAuth secret stored in scope {SCOPE}")

w.warehouses.update_permissions(a.warehouse, access_control_list=[
    sql.WarehouseAccessControlRequest(service_principal_name=sp.application_id, permission_level=sql.WarehousePermissionLevel.CAN_USE)])
print("CAN_USE on warehouse", a.warehouse)
print(f"agents_sp_client_id = {sp.application_id}")
