"""Lets the GUI (axon.server) drive the real runtime.

Same interface as the simulated axon.core.Runtime: snapshot(cursor), task_detail(id), command(payload).
"""

import hashlib
import json
import os
import re
import subprocess
import time
import threading
import tomllib
from pathlib import Path

from . import agent_options, brainstorm, integrate, runtime, sandbox, usage
from .core import ControlError, clean_text, normalize_scope

DONE = ("COMPLETED", "FAILED", "CANCELLED")
PROVIDERS = (("fake", "Fake agent", "Scripted test agent, sandboxed, no quota"),
             ("codex", "Codex", "Codex CLI adapter (unverified)"),
             ("claude", "Claude Code", "Claude Code CLI adapter (unverified)"),
             ("local", "Local model", "Local coding agent over a loopback model (tools: files + checks, no shell)"))
SETTINGS = (("slots.fake", "Fake agent slots", 1, 8), ("slots.codex", "Codex slots", 1, 4), ("slots.local", "Local model slots", 1, 2),
            ("slots.claude", "Claude Code slots", 1, 4), ("limits.attempt_timeout", "Attempt timeout (seconds)", 60, 86400))
HANDOFFS = {"review_with_claude": ("review", "claude"), "review_with_codex": ("review", "codex"),
            "continue_with_codex": ("continue", "codex"), "continue_with_claude": ("continue", "claude")}
MAX_DIFF, MAX_LOG, MAX_PROMPT, MAX_DIFFS = 200_000, 30_000, 20_000, 64
KINDS = {"status": "STATE", "attempt": "ATTEMPT", "tool": "TOOL", "check": "CHECK", "prepare": "PREPARE",
         "outcome": "OUTCOME", "error": "ERROR", "control": "CONTROL", "instruction": "INSTRUCTION",
         "leak": "LEAK", "stale-result-dropped": "STALE", "integrate": "INTEGRATE", "integrate-error": "INTEGRATE",
         "promote": "PROMOTE", "review": "REVIEW", "integration-discarded": "INTEGRATE", "ask": "INPUT",
         "applied": "APPLY", "apply-error": "APPLY"}


def message(kind, d):
    if kind == "status":
        return f"{d['status']}: {d.get('note') or ''}".rstrip(": ")
    return {"attempt": lambda: f"Attempt {d.get('n')} started on {d.get('agent')} from {str(d.get('base'))[:10]}",
            "ask": lambda: f"Agent asked: {d.get('question')}" + (f" [options: {' | '.join(d['options'])}]" if d.get("options") else ""),
            "tool": lambda: f"Agent called {d.get('tool')}",
            "check": lambda: f"Check {d.get('name')}: exit {d.get('rc')}",
            "prepare": lambda: f"Prepare {d.get('name')}: exit {d.get('rc')}",
            "outcome": lambda: f"Attempt outcome: {d.get('outcome')}",
            "error": lambda: f"Runtime error: {d.get('error')}",
            "control": lambda: "Dispatch paused; running attempts continue" if d.get("paused") else "Dispatch resumed",
            "instruction": lambda: "Instruction saved for the next attempt",
            "leak": lambda: "Agent credential found in a diff; result blocked",
            "stale-result-dropped": lambda: "Late result from a revoked attempt was dropped",
            "integrate": lambda: (f"Integrated into the integration branch at {str(d.get('commit'))[:10]}; checks passed" if d.get("ok")
                                  else f"Not integrated: checks failed on {str(d.get('commit'))[:10]}"),
            "integrate-error": lambda: f"Not integrated: {d.get('error')}",
            "promote": lambda: f"Your branch {d.get('branch')} fast-forwarded to {str(d.get('commit'))[:10]}",
            "review": lambda: f"Review of task {d.get('target')} by {d.get('reviewer')}: {d.get('verdict')}",
            "integration-discarded": lambda: f"Integration branch discarded (was {str(d.get('commit'))[:10]}); tasks stay completed",
            "applied": lambda: f"Written into {d.get('path')}: {', '.join(d.get('files') or [])}"[:300],
            "apply-error": lambda: f"Not written into your folder: {d.get('error')}",
            }.get(kind, lambda: kind)()


def dump_toml(cfg):
    """Config is only tables of scalars and number lists, so JSON syntax is valid TOML here."""
    out = []
    for section, values in cfg.items():
        out.append(f"[{section}]")
        out += [f"{k} = {json.dumps(v)}" for k, v in values.items()]
        out.append("")
    return "\n".join(out)


def memory_bytes(unit):
    uid = os.getuid()
    base = Path(f"/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service/app.slice/{unit}.scope")
    try:
        return int((base / "memory.current").read_text())
    except (OSError, ValueError):
        return None


class Bridge:
    def __init__(self, store=None, runner=True):
        # runner=False: GUI only; agents are started by a separate `axon-cli run` on the same store.
        self.runner = runner
        self.rt = runtime.Runtime(store)
        self.store = self.rt.store
        if runner:
            self.rt.start()
        self.diffs = {}
        self.integrating = {}  # project -> task id, while its checks run in a background thread
        self.lock = threading.Lock()
        self.limits, self.limits_at = {}, 0.0  # subscription windows per agent, refreshed in the background

    def refresh_limits(self):
        home = runtime.data_dir() / "agents"
        seen = []
        for f in (runtime.data_dir() / "claude-limits.json",   # headless: the Runner, from claude's stream
                  runtime.data_dir() / "agents" / "claude" / "axon-limits.json"):  # interactive: claude's status line
            try:
                seen.append(json.loads(f.read_text()))
            except (OSError, ValueError):
                pass
        claude = max(seen, key=lambda d: d.get("as_of", 0), default=None)
        self.limits = {"claude": claude, "codex": usage.codex_limits(home / "codex")}

    def close(self):
        if self.runner:
            self.rt.shutdown()

    def tick(self):
        if self.runner:
            self.rt.tick()

    # Reading

    def projects(self):
        out = []
        for f in sorted((runtime.config_dir() / "projects").glob("*.toml")):
            try:
                p = runtime.load_project(f.stem)
            except Exception as e:  # a broken config must not hide the other projects
                out.append({"id": f.stem, "name": f.stem, "path": "invalid", "description": f"Config error: {e}"[:200]})
                continue
            out.append({"id": f.stem, "name": f.stem, "path": p["path"], "checks": list(p["checks"]),
                        "description": f"{len(p['checks'])} check(s) / protected: {', '.join(p['protected']) or 'none'}"})
        return out

    def logged_in(self, name):
        if name == "local":  # no login: a role the user switches on in config.toml
            return bool(self.rt.cfg["local"]["coding"])
        f = runtime.LOGIN_FILE.get(name)
        return not f or (runtime.data_dir() / "agents" / name / f).exists()

    def providers(self, busy, cool):
        slots, out = self.rt.cfg["slots"], []
        for pid, name, desc in PROVIDERS:
            ok, until = self.logged_in(pid), cool.get(pid)
            until = until if until and until > time.time() else None
            out.append({"id": pid, "name": name, "ok": ok, "slots_used": busy.get(pid, 0), "slot_limit": slots.get(pid, 1),
                        "limits": self.limits.get(pid),
                        "status": "Unavailable" if not ok else "Cooldown" if until else "Busy" if busy.get(pid) else "Ready",
                        "cooldown_until": until, "capability": desc,
                        "reason": ("Local coding is off" if pid == "local" else "Not logged in") if not ok else None,
                        "message": (("Set coding = true under [local] in config.toml to allow local coding." if pid == "local" else
                                     "Log in this agent's Axon account once, outside the GUI (see the README). "
                                     "Your normal CLI login is not used.")) if not ok else
                                   "Provider cooldown starts when the CLI reports a quota or rate limit." if pid != "fake" else
                                   "Runs scripted scenarios inside the same sandbox as real agents."})
        return out

    def settings(self):
        cfg = self.rt.cfg
        return {"editable": True, "items": [{"key": k, "label": label, "type": "number", "min": lo, "max": hi, "required": True,
                                             "value": cfg[k.split(".")[0]][k.split(".")[1]]} for k, label, lo, hi in SETTINGS]}

    def diff(self, t, proj):
        """Full patch plus per-file scope/protected classification, cached per commit pair."""
        key = (t["project"], t["base"], t["head"], t["scope"])
        if key not in self.diffs:
            while len(self.diffs) >= MAX_DIFFS:  # bounded cache: drop the oldest entry
                self.diffs.pop(next(iter(self.diffs)))
            git = ["git", "-C", proj["path"]]
            patch = subprocess.run([*git, "diff", "--no-ext-diff", "--no-textconv", "--no-color", t["base"], t["head"]],
                                   capture_output=True, text=True, errors="replace").stdout
            if len(patch) > MAX_DIFF:
                patch = patch[:MAX_DIFF] + f"\n... patch truncated at {MAX_DIFF} characters; use git diff for the rest\n"
            scope = json.loads(t["scope"])
            files = [{"path": f, "out_of_scope": not any(runtime.under(f, sc) for sc in scope),
                      "protected": any(runtime.under(f, p) for p in proj["protected"])}
                     for f in sandbox.changed_files(proj["path"], t["base"], t["head"])]
            self.diffs[key] = (patch or "(no changes)", files)
        return self.diffs[key]

    def read(self, aid, name, limit):
        try:
            data = (runtime.data_dir() / "attempts" / aid / name).read_bytes()[-limit:]
        except OSError:
            return None
        return self.rt.redact(data.decode(errors="replace"))

    def readable(self, aid):
        path = runtime.data_dir() / "attempts" / aid / "agent.log"
        raw = self.read(aid, "agent.log", 400_000)
        if raw is None:
            return None
        if path.stat().st_size > 400_000:  # the tail starts mid-line
            raw = raw.split("\n", 1)[-1]
        return runtime.readable_log(raw, runtime.data_dir() / "attempts" / aid / "repo")[-MAX_LOG:]

    def exists(self, aid, name):
        return (runtime.data_dir() / "attempts" / aid / name).exists()

    def artifact(self, aid, kind, name, content=None, **extra):
        a = {"id": f"{kind}{aid}", "kind": kind, "name": name, "attempt_id": aid, "simulated": False, **extra}
        if content is not None:
            a |= {"content": content, "hash": hashlib.sha256(content.encode()).hexdigest()} | extra
        return a

    def artifacts(self, t, aid, evidence, full, projects):
        """Evidence for one task. `full` adds bodies; the poll only needs names and kinds."""
        arts = []
        for e in evidence:
            d = json.loads(e["data"])
            body = f"exit {d['rc']}\n{d.get('tail', '')}"
            a = self.artifact(e["attempt"], "verification", f"{e['kind']} {d['name']}", body if full else None, exit_code=d["rc"])
            arts.append(a | {"id": f"ev{e['id']}"})
        if t["head"] and t["head"] != t["base"]:
            if not full:
                arts.append(self.artifact(aid, "diff", "Code diff", hash=t["head"]))
            else:
                if t["project"] not in projects:
                    projects[t["project"]] = runtime.load_project(t["project"])
                patch, files = self.diff(t, projects[t["project"]])
                arts.append(self.artifact(aid, "diff", "Code diff", patch, files=files) | {"hash": t["head"]})
        if aid:
            for kind, file, label, limit in (("agent_log", "agent.log", "Agent output", MAX_LOG), ("prompt", "prompt.txt", "Prompt sent", MAX_PROMPT)):
                name = f"{label} / attempt {aid}"
                if full:
                    text = self.read(aid, file, limit)
                    if text is not None and kind == "agent_log":  # the conversation first, the raw JSON below it
                        pretty = self.readable(aid)
                        if pretty:
                            arts.append(self.artifact(aid, kind, f"Agent conversation / attempt {aid}", pretty))
                        arts.append(self.artifact(aid, kind, f"{label} (raw) / attempt {aid}", text) | {"id": f"agent_log_raw{aid}"})
                    elif text is not None:
                        arts.append(self.artifact(aid, kind, name, text))
                elif self.exists(aid, file):
                    arts.append(self.artifact(aid, kind, name))
        return arts

    def context(self):
        """Everything the task views share, read once per request."""
        s, now = self.store, time.time()
        rows = list(s.q("select * from tasks order by id"))
        attempts, latest = {}, {}
        for a in s.q("select * from attempts order by started"):
            attempts.setdefault(a["task"], []).append(a)
            latest[a["task"]] = a["id"]
        evidence, instr = {}, {}
        for e in s.q("select * from events where task is not null and kind in ('check', 'prepare', 'instruction') order by id"):
            (instr if e["kind"] == "instruction" else evidence).setdefault(e["task"], []).append(e)
        reviews = {}
        for e in s.q("select * from events where kind = 'review' order by id desc"):
            d = json.loads(e["data"])
            reviews.setdefault(d["target"], []).append({"reviewer": d["reviewer"], "implementer": d["implementer"], "verdict": d["verdict"],
                                                        "summary": d["summary"], "commit": d["commit"], "time": e["at"], "review_task_id": str(e["task"])})
        busy = {}
        for t in rows:
            if t["status"] == "RUNNING":
                busy[t["agent"]] = busy.get(t["agent"], 0) + 1
        return {"now": now, "rows": rows, "attempts": attempts, "latest": latest, "evidence": evidence, "instr": instr, "reviews": reviews, "by_id": {t["id"]: t for t in rows},
                "busy": busy, "cool": {r["agent"]: r["until"] for r in s.q("select * from cooldowns")},
                "touched": {r["task"]: r["m"] for r in s.q("select task, max(at) m from events where task is not null group by task")},
                "running": [t for t in rows if t["status"] == "RUNNING"], "paused": runtime.is_paused(s), "projects": {}}

    def task_view(self, t, c, full):
        slots, tid, aid = self.rt.cfg["slots"], t["id"], c["latest"].get(t["id"])
        state = "CANCELLING" if t["status"] == "RUNNING" and t["cancel"] else t["status"]
        reasons = []
        if state == "QUEUED":
            if c["paused"]:
                reasons.append({"code": "paused", "message": "Dispatch is paused"})
            if c["cool"].get(t["agent"], 0) > c["now"]:
                reasons.append({"code": "cooldown", "until": c["cool"][t["agent"]], "message": f"{t['agent']} is cooling down after a quota limit"})
            mine = json.loads(t["scope"])
            for o in c["running"]:
                if o["project"] == t["project"] and runtime.overlaps(mine, json.loads(o["scope"])):
                    reasons.append({"code": "scope", "task_id": str(o["id"]), "message": f"Scope held by {o['title'] or 'task ' + str(o['id'])}"})
            if c["busy"].get(t["agent"], 0) >= slots.get(t["agent"], 1):
                reasons.append({"code": "slot", "message": f"{t['agent']} slots full ({c['busy'][t['agent']]}/{slots.get(t['agent'], 1)})"})
            for dep in filter(None, (c["by_id"].get(i) for i in runtime.deps_of(t))):
                if dep["status"] != "COMPLETED":
                    reasons.append({"code": "dependency", "task_id": str(dep["id"]),
                                    "message": f"Waiting for task {dep['id']} to complete (it is {dep['status']})"})
            reasons = reasons or [{"code": "ready", "message": "Ready for the next dispatch tick"}]
        elif state == "WAITING_QUOTA":
            reasons.append({"code": "cooldown", "until": c["cool"].get(t["agent"], t["updated"]), "message": f"{t['agent']} quota cooldown"})
        live = {}
        if state in ("RUNNING", "CANCELLING") and aid:  # how long it runs and when the agent last wrote anything
            try:
                out = runtime.attempt_log(aid).stat().st_mtime
            except OSError:
                out = None
            live = {"running_since": c["attempts"][tid][-1]["started"], "last_output": out}
        pending, held = None, brainstorm.held(self.store, tid) if state == "WAITING_INPUT" and t["kind"] == "plan" else None
        if state in ("WAITING_INPUT", "WAITING_APPROVAL") and not held:  # REVIEW has no separate question; the UI shows the diff
            pending = {"id": f"{tid}:{aid}:{state}", "message": t["note"] or state, "attempt_id": aid,
                       "expires": t["updated"] + 86400, "payload_hash": "",
                       "options": runtime.ask_options(self.store, tid) if state == "WAITING_INPUT" else [],
                       "questions": runtime.ask_questions(self.store, tid) if state == "WAITING_INPUT" else []}
        return {
            "model": t["model"], "effort": t["effort"], "checks": json.loads(t["checks"]) if t["checks"] else None,
            "held_by": str(held) if held else None, "kind": t["kind"] or "task", "after": str(t["after"]) if t["after"] is not None else None, "needs": [str(i) for i in json.loads(t["needs"] or "[]")], "round": t["round"], "reviews": [r | {"stale": r["commit"] != t["head"]} for r in c["reviews"].get(tid, [])],
            "id": str(tid), "project_id": t["project"], "title": t["title"] or t["spec"][:80], "spec": t["spec"],
            "scope": json.loads(t["scope"]), "scenario": "real", "state": state, "backend": t["agent"],
            "attempt_id": aid, "pending": pending, "queue_reasons": reasons, "head": t["head"],
            "artifacts": self.artifacts(t, aid, c["evidence"].get(tid, []), full, c["projects"]),
            "due": c["cool"].get(t["agent"], t["updated"]) if state == "WAITING_QUOTA" else None,
            "activity": f"Waiting for your answer in Brainstorm #{held}: both agents' questions are merged there, answer them once" if held
            else t["note"] or state.replace("_", " ").title(),
            "result_ref": f"refs/axon/attempts/{aid}" if state == "COMPLETED" and t["head"] and aid else None,
            "source": json.loads(t["source"]) if t["source"] else None,
            "attempts": [{"id": a["id"], "started_at": a["started"], "ended_at": a["ended"], "backend": t["agent"],
                          "state": "RUNNING" if a["status"] == "running" else (a["outcome"] or "RUNNING"),
                          "memory_bytes": memory_bytes(a["unit"]) if a["status"] == "running" else None,
                          "model": a["model"], "effort": a["effort"], "prompt_bytes": a["prompt_bytes"],
                          "usage": json.loads(a["usage"]) if a["usage"] else None}
                         for a in c["attempts"].get(tid, [])],
            "instructions": [{"version": i + 1, "text": json.loads(e["data"])["text"], "time": e["at"]}
                             for i, e in enumerate(c["instr"].get(tid, []))],
            "created_at": t["created"], "updated_at": max(t["updated"], c["touched"].get(tid, 0), live.get("last_output") or 0),
            **live,
        }

    def event(self, r, projects, full):
        d = json.loads(r["data"])
        e = {"schema_version": 1, "seq": r["id"], "type": KINDS.get(r["kind"], r["kind"].upper()),
             "task_id": str(r["task"]) if r["task"] else None, "project_id": projects.get(r["task"]),
             "attempt_id": r["attempt"], "time": r["at"], "producer": "runtime", "message": message(r["kind"], d)}
        if full and "tail" in d:
            e["output"] = d["tail"]
        return e

    def snapshot(self, cursor=0):
        s, c = self.store, self.context()
        if c["now"] - self.limits_at > 60:  # at most once a minute, never blocking the poll
            self.limits_at = c["now"]
            threading.Thread(target=self.refresh_limits, daemon=True).start()
        slots = self.rt.cfg["slots"]
        proj_of = {t["id"]: t["project"] for t in c["rows"]}
        evs = list(s.q("select * from events where id > ? order by id limit 300", cursor))
        last = s.one("select coalesce(max(id), 0) m from events")["m"]
        names = [p[0] for p in PROVIDERS]
        return {"schema_version": 1, "mode": "real", "now": c["now"], "paused": c["paused"], "projects": self.projects(),
                "tasks": [self.task_view(t, c, False) for t in c["rows"]],
                "events": [self.event(r, proj_of, False) for r in evs],
                "cursor": evs[-1]["id"] if evs else cursor, "latest_cursor": last,
                "integration": self.integration(), "brainstorms": brainstorm.recent(s), "agent_options": self.agent_options(), "usage": self.usage(),
                "providers": self.providers(c["busy"], c["cool"]), "settings": self.settings(),
                "resources": {"slots": [{"backend": n, "used": c["busy"].get(n, 0), "limit": slots.get(n, 1)} for n in names],
                              "memory_available": True, "mode": "real"},
                "capabilities": {"fake": "scripted, sandboxed", "codex": "unverified", "claude": "unverified", "local": "not connected",
                                 "controls": {"graceful_stop": False},
                                 "handoff": {"claude_review": self.logged_in("claude"), "codex_continue": self.logged_in("codex"),
                                            "codex_review": self.logged_in("codex"), "claude_continue": self.logged_in("claude")}}}

    def usage(self, hours=24):
        """What attempts cost in the last day, per agent and kind (OD-012): only what the CLIs exposed."""
        rep = usage.report(self.store, time.time() - hours * 3600)
        return [{"agent": a, "kind": k, **{f: r[f] for f in ("attempts", "outcomes", "seconds", "prompt_bytes", "input", "cached",
                                                              "output", "cost_usd", "with_usage", "settings")}}
                for (a, k), r in rep.items()]

    def agent_options(self):
        """Per agent: the configured model/effort ('' = the CLI default) and what the GUI may offer."""
        cfg = self.rt.cfg["agents"]
        return {a: {"model": cfg[f"{a}_model"], "effort": cfg[f"{a}_effort"], "efforts": list(agent_options.EFFORTS[a]),
                    "models": agent_options.known_models(a, runtime.data_dir() / "agents")}
                for a in agent_options.AGENTS}

    def set_agent_options(self, p):
        agent = p.get("agent")
        try:
            model, effort = agent_options.save(runtime.config_dir() / "config.toml", agent, str(p.get("model") or ""),
                                               str(p.get("effort") or ""))
        except ValueError as e:
            raise ControlError(str(e))
        self.rt.cfg["agents"].update({f"{agent}_model": model, f"{agent}_effort": effort})
        return {"ok": True, "message": f"{agent}: model {model or 'default'}, effort {effort or 'default'}. Applies to attempts that start from now on."}

    def integration(self):
        out = []
        for p in self.projects():
            if p["path"] == "invalid":
                continue
            try:
                st = integrate.status(self.store, p["id"])
            except Exception:  # a repo that cannot be read must not break the poll
                continue
            busy = self.integrating.get(p["id"])
            if st["tasks"] or busy:
                out.append({**st, "project_id": st.pop("project"), "busy": str(busy) if busy else None})
        return out

    def task_detail(self, task_id):
        c = self.context()
        t = next((t for t in c["rows"] if str(t["id"]) == str(task_id)), None)
        if not t:
            raise ControlError("Task not found")
        proj_of = {t["id"]: t["project"] for t in c["rows"]}
        rows = self.store.q("select * from events where task = ? order by id", t["id"])
        return {"task": self.task_view(t, c, True), "events": [self.event(r, proj_of, True) for r in rows]}

    # Commands

    def chat(self, p):
        action = p["action"]
        if action == "chat_start":
            if p.get("project_id") not in {x["id"] for x in self.projects()}:
                raise ControlError("Unknown project")
            if p.get("agent") not in ("claude", "codex", "shell"):
                raise ControlError("Chat supports claude, codex and shell")
            label = p.get("label") or ""
            if not isinstance(label, str) or (label and not re.fullmatch(r"[A-Za-z0-9]{1,20}", label)):
                raise ControlError("Chat name: 1-20 letters or digits")
            try:
                return {"session": runtime.chat_start(p["project_id"], p["agent"], label)}
            except (RuntimeError, OSError, subprocess.CalledProcessError) as e:
                raise ControlError(f"Could not start the chat: {e}")
        sessions = runtime.chat_sessions()
        if action == "chat_list":
            return {"sessions": sessions}
        if p.get("session") not in sessions:
            raise ControlError("Unknown chat session")
        if action == "chat_close":
            runtime.chat_close(p["session"])
            return {"ok": True}
        raise ControlError("Unknown chat action")

    def chat_attach(self, session):
        if session not in runtime.chat_sessions():
            raise ControlError("Unknown chat session")
        return runtime.chat_attach(session)

    chat_resize = staticmethod(runtime.chat_resize)

    def chat_upload(self, session, ctype, data):
        if session not in runtime.chat_sessions():
            raise ControlError("Unknown chat session")
        try:
            return {"path": runtime.chat_upload(session, ctype, data)}
        except (ValueError, OSError, subprocess.CalledProcessError) as e:
            raise ControlError(str(e))

    def command(self, p):
        if not isinstance(p, dict) or not isinstance(p.get("action"), str):
            raise ControlError("Command must be an object with a text action")
        action, s = p["action"], self.store
        if action in ("pause", "resume"):
            runtime.set_paused(s, action == "pause")
            return {"ok": True}
        if action.startswith("chat_"):
            return self.chat(p)
        if action == "create_project":
            return self.create_project(p)
        if action == "browse_dir":
            return self.browse_dir(p.get("path"))
        if action == "brainstorm_start":
            if p.get("project_id") not in {x["id"] for x in self.projects()}:
                raise ControlError("Unknown project")
            opts = {r: {k: str(p.get(f"{r}_{k}") or "") for k in ("model", "effort", "light_model", "light_effort")} for r in ("lead", "other")}
            try:
                bid = brainstorm.start(s, p["project_id"], p.get("goal"), p.get("lead") or None, p.get("other") or None, opts)
            except (ValueError, subprocess.CalledProcessError) as e:
                raise ControlError(f"Cannot start: {e}"[:300])
            return {"brainstorm_id": str(bid)}
        if action in ("brainstorm_create_tasks", "brainstorm_expand", "brainstorm_stop", "brainstorm_answer"):
            try:
                bid = int(p.get("brainstorm_id"))
                if action == "brainstorm_answer":
                    brainstorm.answer_gate(s, bid, p.get("answers"))
                    return {"ok": True}
                if action == "brainstorm_stop":
                    brainstorm.cancel(s, bid)
                    return {"ok": True}
                if action == "brainstorm_expand":
                    brainstorm.expand(s, bid, p.get("phase") or None)
                    return {"ok": True}
                if not p.get("force") and (why := brainstorm.baseline_error(self.rt, bid)):
                    return {"warning": why}  # the screen asks the user whether to start anyway
                return {"task_ids": {k: str(v) for k, v in brainstorm.create_tasks(s, bid, p.get("phase") or None).items()}}
            except (TypeError, ValueError, subprocess.CalledProcessError) as e:
                raise ControlError(str(e)[:300])
        if action == "update_settings":
            return self.update_settings(p.get("values"))
        if action == "create_task":
            return self.create_task(p)
        if action == "set_agent_options":
            return self.set_agent_options(p)
        if action == "verify_integration":
            if p.get("project_id") not in {x["id"] for x in self.projects()}:
                raise ControlError("Unknown project")
            return self.start_verify(p["project_id"])
        if action in ("review_integration", "discard_integration"):
            if p.get("project_id") not in {x["id"] for x in self.projects()}:
                raise ControlError("Unknown project")
            try:
                if action == "discard_integration":
                    integrate.discard(s, p["project_id"], p.get("commit"))
                    return {"ok": True, "message": "Integration branch discarded. Completed tasks can be integrated again."}
                agent = p.get("agent") or "claude"
                if agent not in runtime.ADAPTERS or not self.logged_in(agent):
                    raise ControlError(f"{agent} is not available")
                rid, dup = runtime.request_integration_review(s, p["project_id"], agent)
            except (integrate.IntegrationError, ValueError) as e:
                raise ControlError(str(e)[:300])
            return {"task_id": str(dup or rid), "duplicate": bool(dup)}
        if action == "promote_integration":
            if p.get("project_id") not in {x["id"] for x in self.projects()}:
                raise ControlError("Unknown project")
            try:
                commit = integrate.promote(s, p["project_id"], p.get("commit"))
            except integrate.IntegrationError as e:
                raise ControlError(str(e)[:300])
            return {"ok": True, "message": f"Your branch was fast-forwarded to {commit[:10]}"}
        try:
            tid = int(p.get("task_id"))
        except (TypeError, ValueError):
            raise ControlError("Task not found")
        t = s.one("select * from tasks where id = ?", tid)
        if not t:
            raise ControlError("Task not found")
        last = s.one("select id from attempts where task = ? order by started desc limit 1", tid)
        aid = last["id"] if last else None
        if p.get("attempt_id") != aid:
            raise ControlError("Attempt changed. Refresh before controlling this task.")
        st, ok, out = t["status"], False, {"ok": True}
        if action in ("stop", "kill"):
            if st in DONE:
                raise ControlError("This task is already inactive")
            runtime.stop_task(s, tid)  # no graceful stop yet: the attempt's process tree is killed at once
            ok = True
        elif action == "retry":
            ok = runtime.retry(s, tid) if st in ("FAILED", "CANCELLED") else False
        elif action == "instruction":
            ok = runtime.instruct(s, tid, clean_text(p.get("text"), "Instruction", 2000))
        elif action in ("approve", "reject", "answer"):
            if st != "REVIEW" and p.get("pending_id") != f"{tid}:{aid}:{st}":
                raise ControlError("Request changed or has already been resolved")
            if action == "answer":
                try:
                    ok = st == "WAITING_INPUT" and runtime.answer(s, tid, clean_text(p.get("text"), "Answer", 4000))
                except ValueError as e:
                    raise ControlError(str(e)[:300])
            elif st in ("WAITING_APPROVAL", "REVIEW"):
                ok = (runtime.approve if action == "approve" else runtime.reject)(s, tid)
        elif action == "revise":
            try:
                rid, dup = runtime.revise(s, tid)
            except ValueError as e:
                raise ControlError(str(e)[:300])
            out, ok = {"task_id": str(dup or rid), "duplicate": bool(dup)}, st == "COMPLETED"
        elif action == "integrate":
            out, ok = self.start_integrate(t), st == "COMPLETED"
        elif action == "apply":
            try:
                files = runtime.apply_result(s, tid)
            except (ValueError, subprocess.CalledProcessError) as e:
                raise ControlError(str(e)[:600])
            out, ok = {"ok": True, "message": f"Written into your project folder (uncommitted): {', '.join(files)}"[:300]}, True
        elif action in HANDOFFS:
            mode, agent = HANDOFFS[action]
            out = self.hand_off(t, aid, agent, mode)
            ok = True
        else:
            raise ControlError("Unknown command")
        if not ok:
            raise ControlError(f"{action} is not possible while the task is {st}")
        return out

    def start_integrate(self, t):
        if t["status"] != "COMPLETED" or not t["head"]:
            raise ControlError("Only a completed task with a result can be integrated")
        if runtime.load_project(t["project"])["require_review"] and not runtime.review_approved(self.store, t["id"], t["head"]):
            raise ControlError("This project requires an approving review of this exact result first. Use Review with Claude.")
        with self.lock:
            if t["project"] in self.integrating:
                raise ControlError("An integration is already running for this project")
            self.integrating[t["project"]] = t["id"]

        def work():
            try:
                integrate.integrate(self.rt, t["id"])
            except integrate.IntegrationError:
                pass  # recorded as an event the GUI shows
            except Exception as e:
                self.store.log(t["id"], None, "integrate-error", error=f"unexpected: {e!r}"[:300])
            finally:
                with self.lock:
                    self.integrating.pop(t["project"], None)

        threading.Thread(target=work, daemon=True).start()
        return {"ok": True, "message": "Integrating; checks run on the merged commit. Watch the activity log."}

    def start_verify(self, project):
        with self.lock:
            if project in self.integrating:
                raise ControlError("An integration is already running for this project")
            self.integrating[project] = "verify"

        def work():
            try:
                integrate.verify(self.rt, project)
            except integrate.IntegrationError:
                pass  # recorded as an event the GUI shows
            except Exception as e:
                self.store.log(None, None, "integrate-error", error=f"unexpected: {e!r}"[:300])
            finally:
                with self.lock:
                    self.integrating.pop(project, None)

        threading.Thread(target=work, daemon=True).start()
        return {"ok": True, "message": "Running every check on the integration commit. Watch the activity log."}

    def hand_off(self, t, aid, agent, mode):
        if t["status"] != "COMPLETED" or not t["head"]:
            raise ControlError("Only a completed task with a result can be handed off")
        if not self.logged_in(agent):
            raise ControlError(f"{agent} is not logged in")
        title = t["title"] or t["spec"][:60]
        if mode == "review":  # an independent, read-only review of this exact result
            try:
                rid, dup = runtime.request_review(self.store, t["id"], agent)
            except ValueError as e:
                raise ControlError(str(e))
            return {"task_id": str(dup or rid), "duplicate": bool(dup)}
        spec = f"Continue the work from task {t['id']} ({title}): finish anything incomplete and keep to the scope."
        return self.create_task({"project_id": t["project"], "title": f"Continue: {title}"[:120],
                                 "spec": spec, "scope": ",".join(json.loads(t["scope"])), "agent": agent,
                                 "source_task_id": str(t["id"]), "source_attempt_id": aid})

    def create_task(self, p):
        project = p.get("project_id")
        if project not in {x["id"] for x in self.projects()}:
            raise ControlError("Unknown project")
        base, source = p.get("base") or "HEAD", None
        if p.get("source_task_id"):
            sid = str(p["source_task_id"])
            old = self.store.one("select * from tasks where id = ?", int(sid)) if sid.isdigit() else None
            last = old and self.store.one("select id from attempts where task = ? order by started desc limit 1", old["id"])
            if not old or old["project"] != project or old["status"] != "COMPLETED" or not old["head"]:
                raise ControlError("Source must be a completed task in the same project")
            if not last or p.get("source_attempt_id") != last["id"]:
                raise ControlError("Source attempt changed. Select the source again.")
            base = old["head"]
            source = {"task_id": str(old["id"]), "attempt_id": last["id"], "title": old["title"] or old["spec"][:80],
                      "artifacts": [{"name": "result commit", "hash": old["head"]}]}
        if not isinstance(base, str) or base.startswith("-") or len(base) > 200:
            raise ControlError("Invalid base")
        checks = p.get("checks")
        if checks in (None, "", []):
            checks = None
        elif not isinstance(checks, list) or not all(isinstance(c, str) for c in checks):
            raise ControlError("Checks must be a list of check names")
        after = p.get("after_task_id")
        if after not in (None, ""):
            if not str(after).isdigit():
                raise ControlError("Invalid dependency")
            after = int(after)
        else:
            after = None
        try:
            tid, dup = runtime.add_task(self.store, project, p.get("agent") or "fake",
                                        clean_text(p.get("spec"), "Task description"), normalize_scope(p.get("scope")),
                                        base, clean_text(p.get("title"), "Title", 120), source, after=after, checks=checks,
                                        model=str(p.get("model") or "") or None, effort=str(p.get("effort") or "") or None)
        except (ValueError, subprocess.CalledProcessError) as e:
            raise ControlError(f"Cannot queue task: {e}"[:300])
        return {"task_id": str(dup or tid), "duplicate": bool(dup)}

    def create_project(self, p):
        try:
            f = runtime.create_project(clean_text(p.get("name"), "Name", 60), clean_text(p.get("path"), "Repository path", 1000))
        except ValueError as e:
            raise ControlError(str(e))
        return {"id": f.stem}

    def browse_dir(self, raw):
        """Subfolders of `raw` (home when empty or not a folder), for the project folder picker."""
        d = Path(os.path.expanduser(str(raw or "~"))).resolve()
        if not d.is_dir():
            d = Path.home()
        dirs = []
        try:
            for c in sorted(d.iterdir(), key=lambda c: c.name.lower()):
                if not c.name.startswith(".") and c.is_dir():
                    dirs.append({"name": c.name, "git": (c / ".git").exists()})
        except OSError:
            pass
        return {"path": str(d), "parent": str(d.parent) if d.parent != d else None, "git": (d / ".git").exists(), "dirs": dirs}

    def update_settings(self, values):
        if not isinstance(values, dict):
            raise ControlError("Settings must be an object")
        known = {k: (lo, hi) for k, _, lo, hi in SETTINGS}
        if set(values) - set(known):
            raise ControlError("Unknown setting")
        new = {}
        for k, raw in values.items():
            try:
                v = int(str(raw))
            except ValueError:
                raise ControlError(f"{k} must be a whole number")
            if not known[k][0] <= v <= known[k][1]:
                raise ControlError(f"{k} must be between {known[k][0]} and {known[k][1]}")
            new[k] = v
        f = runtime.config_dir() / "config.toml"
        cfg = tomllib.loads(f.read_text()) if f.exists() else {}
        for k, v in new.items():
            sec, key = k.split(".")
            cfg.setdefault(sec, {})[key] = v
            self.rt.cfg[sec][key] = v
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(dump_toml(cfg))
        tmp.replace(f)
        return {"ok": True}
