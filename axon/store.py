"""SQLite state for tasks, attempts, events and provider cooldowns."""

import json
import sqlite3
import time

SCHEMA = """
create table if not exists tasks(
  id integer primary key, project text not null, agent text not null, spec text not null,
  title text not null default '', source text not null default '',
  scope text not null, key text not null, base text not null, head text,
  status text not null, attempts integer not null default 0,
  note text not null default '', context text not null default '',
  cancel integer not null default 0,
  created real not null, updated real not null);
-- One live task per key: work that is queued, running or done is never queued twice (D-008).
create unique index if not exists task_key on tasks(key) where status not in ('FAILED', 'CANCELLED');
create table if not exists attempts(
  id text primary key, task integer not null, n integer not null, unit text not null,
  base text not null, head text, status text not null, outcome text,
  started real not null, ended real);
create table if not exists events(
  id integer primary key, task integer, attempt text, kind text not null,
  data text not null, at real not null);
-- A brainstorm: Claude and Codex plan together before any code is written (axon/brainstorm.py). `data` is its JSON state.
create table if not exists brainstorms(
  id integer primary key, project text not null, goal text not null, phase text not null,
  status text not null, data text not null, created real not null, updated real not null);
create table if not exists meta(key text primary key, value text not null);
create table if not exists cooldowns(
  agent text primary key, until real not null, strikes integer not null);
"""


class Store:
    def __init__(self, path):
        self.path = str(path)
        c = self._conn()
        try:
            c.executescript(SCHEMA)
            for table, cols in (("tasks", (("kind", "text not null default ''"), ("target", "integer"), ("after", "integer"),
                                           ("parent", "integer"), ("round", "integer not null default 0"), ("checks", "text"),
                                           ("model", "text"), ("effort", "text"), ("needs", "text"),
                                           ("approved_commit", "text"), ("feedback", "text not null default ''"))),
                                ("attempts", (("prompt_bytes", "integer"), ("usage", "text"),
                                              ("model", "text"), ("effort", "text")))):
                have = {r["name"] for r in c.execute(f"pragma table_info({table})")}
                for col, ddl in cols:
                    if col not in have:  # databases created before the column existed
                        c.execute(f"alter table {table} add column {col} {ddl}")
                        if col == "feedback":  # OD-013: context was the user's words mixed with agent and check output
                            c.execute("update tasks set feedback = context, context = ''")
        finally:
            c.close()

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("pragma journal_mode=wal")
        return c

    def q(self, sql, *args):
        c = self._conn()
        try:
            return c.execute(sql, args).fetchall()
        finally:
            c.close()

    def one(self, sql, *args):
        rows = self.q(sql, *args)
        return rows[0] if rows else None

    def x(self, sql, *args):
        """Run one statement; returns (rowcount, lastrowid)."""
        c = self._conn()
        try:
            cur = c.execute(sql, args)
            return cur.rowcount, cur.lastrowid
        finally:
            c.close()

    def log(self, task, attempt, kind, **data):
        self.x("insert into events(task, attempt, kind, data, at) values (?,?,?,?,?)",
               task, attempt, kind, json.dumps(data), time.time())

    def move(self, task, new, frm, **fields):
        """Compare-and-set a task's status. False means someone else changed it first.
        `context_add` / `feedback_add` append to that column instead of replacing it."""
        sets = "".join(f", {k[:-4]} = {k[:-4]} || ?" if k.endswith("_add") else f", {k} = ?"
                       for k in fields)
        marks = ",".join("?" * len(frm))
        c = self._conn()
        try:
            with c:  # the status and its event commit together (OD-023)
                c.execute("begin immediate")
                n = c.execute(f"update tasks set status = ?, updated = ?{sets} where id = ? and status in ({marks})",
                              (new, time.time(), *fields.values(), task, *frm)).rowcount
                if n:
                    c.execute("insert into events(task, attempt, kind, data, at) values (?,?,?,?,?)",
                              (task, None, "status", json.dumps({"status": new, "note": fields.get("note", "")}), time.time()))
        finally:
            c.close()
        return n == 1
