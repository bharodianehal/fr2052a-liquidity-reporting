"""Loads the repo's gitignored .env (see .env.example) into the environment for the helper scripts; nothing workspace-specific is in code."""
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
for line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def need(name):
    v = os.environ.get(name, "").strip()
    if not v:
        raise SystemExit(f"{name} is not set - copy .env.example to .env and fill it in")
    return v
