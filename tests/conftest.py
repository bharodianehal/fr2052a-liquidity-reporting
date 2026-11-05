"""Offline unit tests of the app's rules: no workspace, no Lakebase, no SQL warehouse.

  /tmp/fr2052a-venv/bin/python -m pytest tests -q        (venv: see CLAUDE.md "Test"; + pytest)
"""
import contextlib
import datetime
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
os.environ.setdefault("FR2052A_AGENTS_BATCH", "1")   # no warm-up thread at import

import app as main        # noqa: E402
import workbench as wb    # noqa: E402
import agents             # noqa: E402

# Federal Reserve holidays the tests use (the app reads reference.ref_bank_holidays)
main._HOLIDAYS = {datetime.date(2026, 1, 1), datetime.date(2026, 1, 19), datetime.date(2026, 2, 16), datetime.date(2026, 12, 25)}
REPORTING = {"2026-02-23", "2026-02-24", "2026-02-25", "2026-02-26", "2026-02-27"}


class Request:
    def __init__(self, path=None, query=None, user="checker@bank.com"):
        self.path_params, self.query_params = path or {}, query or {}
        self.headers = {"X-Forwarded-Email": user}


class Cursor:
    """Records the SQL; fetchone() returns what the test queued."""
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None):
        self.conn.sql.append(" ".join(sql.split()))

    def fetchone(self):
        return self.conn.fetch.pop(0) if self.conn.fetch else None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Conn:
    def __init__(self, fetch=None):
        self.sql, self.fetch, self.commits, self.rollbacks = [], list(fetch or []), 0, 0

    def cursor(self):
        return Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class Deps:
    """Stands in for workbench._deps(): canned run_pg / run_wh answers by a keyword of the SQL, a recording Postgres connection."""
    def __init__(self, answers=None, fetch=None):
        self.answers, self.conn = answers or {}, Conn(fetch)

    def _answer(self, sql):
        return next((v for k, v in self.answers.items() if k in sql), [])

    def run_pg(self, sql, params=None):
        return self._answer(sql)

    def run_wh(self, sql, params=None):
        return self._answer(sql)

    @contextlib.contextmanager
    def get_pg(self):
        yield self.conn

    def is_business_day(self, d):
        return main.is_business_day(d)


@pytest.fixture
def deps(monkeypatch):
    def make(answers=None, fetch=None):
        d = Deps(answers, fetch)
        monkeypatch.setattr(wb, "_deps", lambda: d)
        return d
    return make


@pytest.fixture(autouse=True)
def reporting_dates(monkeypatch):
    monkeypatch.setattr(main, "_reporting_dates", lambda: REPORTING)
