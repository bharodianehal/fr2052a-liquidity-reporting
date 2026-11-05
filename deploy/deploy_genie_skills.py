"""Upload the FR 2052a Genie One skills to the current user's skills folder, filling ${catalog}.

  deploy/deploy_genie_skills.py --catalog <catalog>            (task genie_skills of job fr2052a-pipeline; add --profile locally)

Target: /Workspace/Users/<you>/.assistant/skills/<name>/ (Genie One picks them up; start a new chat after updating).
"""
import argparse
import base64
import pathlib

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.workspace import ImportFormat

ap = argparse.ArgumentParser()
ap.add_argument("--profile", default=None, help="CLI profile (omit inside a job)")
ap.add_argument("--catalog", required=True)
ap.add_argument("--root", default=None, help="the repo / bundle root (a job passes ${workspace.file_path}: no __file__ in a serverless Python task)")
args = ap.parse_args()
w = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
root = (pathlib.Path(args.root) if args.root else pathlib.Path(__file__).resolve().parent.parent) / "genie" / "skills"
me = w.current_user.me().user_name
for skill in sorted(p for p in root.iterdir() if (p / "SKILL.md").exists()):
    target = f"/Workspace/Users/{me}/.assistant/skills/{skill.name}"
    for path in sorted(p for p in skill.rglob("*") if p.is_file()):
        rel = path.relative_to(skill).as_posix()
        w.workspace.mkdirs(str(pathlib.PurePosixPath(f"{target}/{rel}").parent))
        w.workspace.import_(f"{target}/{rel}", content=base64.b64encode(path.read_text().replace("${catalog}", args.catalog).encode()).decode(),
                            format=ImportFormat.RAW, overwrite=True)
    print(f"uploaded {skill.name} -> {target}")
