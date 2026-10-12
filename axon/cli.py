"""axon command line. `axon` alone opens the GUI; `axon <command>` works from any folder, and a project
is the one whose repository holds the current folder unless -p names another."""

import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import agent_options, brainstorm, helper, integrate, retention, runtime, sandbox, usage

DONE = ("COMPLETED", "FAILED", "CANCELLED")
NEEDS_YOU = {"WAITING_INPUT": "answer it: axon answer {id}", "WAITING_APPROVAL": "approve it: axon approve {id}",
             "REVIEW": "look at it in the GUI, then: axon approve {id} / axon reject {id}"}


def ago(seconds):
    seconds = int(seconds)
    return f"{seconds}s" if seconds < 60 else f"{seconds // 60}m{seconds % 60:02d}s" if seconds < 3600 else f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"


def project_arg(name):
    """-p, else the project of the current folder."""
    name = name or runtime.project_for(os.getcwd())
    if not name:
        sys.exit("this folder is not in a Axon project: run `axon init` in the repository, or pass -p NAME")
    return name


def show_tasks(store):
    rows = store.q("select * from tasks order by id")
    print(f"{'ID':>4}  {'STATUS':<16} {'AGENT':<7} {'PROJECT':<10} {'SCOPE':<14} NOTE")
    now = time.time()
    for t in rows:
        scope = ",".join(json.loads(t["scope"]))
        note = t["note"].splitlines()[0][:60] if t["note"] else ""
        if t["status"] == "RUNNING":  # is it moving? time since start and since the agent last wrote output
            a = store.one("select id, started from attempts where task = ? order by started desc limit 1", t["id"])
            log = runtime.attempt_log(a["id"]) if a else None
            out = f", output {ago(now - log.stat().st_mtime)} ago" if log and log.exists() else ", no output yet"
            note = f"running {ago(now - a['started'])}{out}" if a else note
        print(f"{t['id']:>4}  {t['status']:<16} {t['agent']:<7} {t['project']:<10} {scope[:14]:<14} {note}")


def show_task(store, tid):
    t = store.one("select * from tasks where id = ?", tid)
    if not t:
        sys.exit(f"no task {tid}")
    for k in ("id", "status", "project", "agent", "scope", "base", "head", "attempts", "note"):
        print(f"{k:>9}: {t[k]}")
    print(f"{'spec':>9}: {t['spec']}")
    print("\nevents:")
    for e in store.q("select * from events where task = ? order by id", tid):
        at = time.strftime("%H:%M:%S", time.localtime(e["at"]))
        print(f"  {at} {e['attempt'] or '-':<6} {e['kind']:<12} {e['data'][:200]}")


def chat(project, agent, label=""):
    """Interactive claude/codex in the sandbox, kept alive in tmux; run again to re-attach.
    No MCP tools and no task: you talk to the agent directly (slash commands, questions, menus)."""
    new = runtime.chat_name(project, agent, label) not in runtime.chat_sessions()
    name = runtime.chat_start(project, agent, label)
    if new:
        print(f"started {agent} ; detach with Ctrl-b d")
    os.execvp("tmux", ["tmux", "attach", "-t", name])


def logs(store, tid, follow):
    """Readable agent output of the latest attempt. With -f: live, with status changes, until the task is done
    or needs you; a line every minute the agent stays silent, so a hang is visible."""
    done, aid, status, quiet = 0, None, None, time.time()
    while True:
        t = store.one("select status, note from tasks where id = ?", tid)
        if not t:
            sys.exit(f"no task {tid}")
        if follow and t["status"] != status:
            status = t["status"]
            print(f"[{time.strftime('%H:%M:%S')}] {status}" + (f": {t['note'].splitlines()[0][:200]}" if t["note"] else ""), flush=True)
        a = store.one("select id, started from attempts where task = ? order by started desc limit 1", tid)
        if a and a["id"] != aid:
            aid, done, quiet = a["id"], 0, time.time()
            print(f"--- attempt {aid}", flush=True)
        path = runtime.attempt_log(aid or "-")
        lines = path.read_text(errors="replace").splitlines() if path.exists() else []
        root = runtime.data_dir() / "attempts" / (aid or "-") / "repo"
        for line in lines[done:]:
            text = runtime.readable_log(line, root)
            if text:
                print(text, flush=True)
                quiet = time.time()
        done = len(lines)
        if not follow or t["status"] in DONE or t["status"] in NEEDS_YOU:
            if follow and t["status"] in NEEDS_YOU:
                print(NEEDS_YOU[t["status"]].format(id=tid))
            return
        if t["status"] == "RUNNING" and a and time.time() - quiet >= 60:
            print(f"… still running ({ago(time.time() - a['started'])}), no output for {ago(time.time() - quiet)}", flush=True)
            quiet = time.time()
        time.sleep(0.5)


def save_server(**values):
    """Change [server] keys in config.toml, keeping everything else."""
    import tomllib
    from .bridge import dump_toml
    f = runtime.config_dir() / "config.toml"
    cfg = tomllib.loads(f.read_text()) if f.exists() else {}
    cfg.setdefault("server", {}).update(values)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(dump_toml(cfg))


def passwd():
    from .server import hash_password
    f = runtime.config_dir() / "password"
    pw = getpass.getpass("New Axon password (empty removes it and turns remote access off): ")
    if not pw:
        f.unlink(missing_ok=True)
        print("password removed")
        return
    if len(pw) < 8:
        sys.exit("use at least 8 characters")
    if getpass.getpass("Again: ") != pw:
        sys.exit("the passwords differ")
    f.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(f, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write(hash_password(pw) + "\n")
    print("password set; the GUI asks for it when you have no launch link (a running Axon picks it up at once)")


def remote(off):
    """Reach the GUI from your other devices on any network: `tailscale serve` puts it on https://<this machine>
    inside your tailnet (not the public internet), and Axon allows that name once a password is set."""
    if not shutil.which("tailscale"):
        sys.exit("install Tailscale on this machine and your other devices first: https://tailscale.com/download")
    port = runtime.load_config()["server"]["port"]
    if off:
        subprocess.run(["tailscale", "serve", "--https=443", "off"])
        save_server(hosts=[])
        print("remote access off")
        return
    if not (runtime.config_dir() / "password").exists():
        sys.exit("set a password first: axon passwd")
    st = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True)
    try:
        host = json.loads(st.stdout)["Self"]["DNSName"].rstrip(".")
    except (ValueError, KeyError, TypeError):
        sys.exit(f"tailscale is not connected: {st.stderr.strip() or 'run `sudo tailscale up`'}")
    if subprocess.run(["tailscale", "serve", "--bg", str(port)]).returncode:
        sys.exit("tailscale serve failed. If it says access denied, run once: sudo tailscale set --operator=$USER\n"
                 "If it asks to enable HTTPS, open the link it printed, then run axon remote again.")
    save_server(hosts=[host])
    if subprocess.run(["systemctl", "--user", "try-restart", "axon"], capture_output=True).returncode == 0:
        print("restarted the axon service with the new address")
    else:
        print("restart Axon if it is running, so it accepts the new address")
    print(f"open https://{host} on any device signed in to your tailnet (phone: the Tailscale app), then sign in")


UNIT = """[Unit]
Description=Axon: coding agents and their control GUI (127.0.0.1:{port})
After=network-online.target

[Service]
ExecStart={py} -m axon gui --no-browser
Environment=PATH={path}
Environment=PYTHONPATH={pkg}
Restart=on-failure
# Only Axon itself stops; chats (tmux) and agents (their own scopes) are not killed with it.
KillMode=process

[Install]
WantedBy=default.target
"""


def service(action):
    """Run Axon in the background as a systemd user service: the GUI and the runner stay up without a terminal."""
    unit = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user" / "axon.service"
    ctl = ["systemctl", "--user"]
    if action == "remove":
        subprocess.run([*ctl, "disable", "--now", "axon"])
        unit.unlink(missing_ok=True)
        subprocess.run([*ctl, "daemon-reload"])
        print("axon service removed")
        return
    unit.parent.mkdir(parents=True, exist_ok=True)
    port = runtime.load_config()["server"]["port"]
    unit.write_text(UNIT.format(port=port, py=sys.executable, path=os.environ.get("PATH", "/usr/bin:/bin"), pkg=sandbox.PKG.parent))
    subprocess.run([*ctl, "daemon-reload"], check=True)
    if subprocess.run([*ctl, "enable", "--now", "axon"]).returncode:
        sys.exit(f"could not start it; see: journalctl --user -u axon -e")
    print(f"axon runs in the background on http://127.0.0.1:{port}; `axon` opens it, logs: journalctl --user -u axon -f")
    linger = subprocess.run(["loginctl", "show-user", getpass.getuser(), "-p", "Linger", "--value"], capture_output=True, text=True)
    if linger.stdout.strip() != "yes":
        print("to keep it running after you log out and start it at boot, run once: loginctl enable-linger")


def doctor(name):
    """Try what tasks need, inside the real sandbox, before a task fails on it."""
    bad = 0

    def report(label, ok, hint=""):
        nonlocal bad
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {label}" + (f"\n     {hint}" if hint and not ok else ""))

    for tool in ("git", "bwrap", "systemd-run", "tmux", "setsid"):
        report(tool, shutil.which(tool), "install it with your package manager")
    if bad:
        return 1
    r = subprocess.run(sandbox.scope(f"axon-doctor-{os.getpid()}", "256M", sandbox.bwrap("/", net=False) + ["true"]),
                       capture_output=True, text=True)
    report("sandbox (bwrap in a systemd scope)", r.returncode == 0, r.stderr.strip()[-300:])
    for agent in ("claude", "codex"):
        exe = shutil.which(agent)
        if not exe:
            report(f"{agent}: CLI on PATH", False, "not installed (fine if you do not use it)")
            continue
        exe = Path(exe).resolve()
        home = runtime.data_dir() / "agents" / agent
        home.mkdir(parents=True, exist_ok=True)
        extra = str(exe.parent if agent == "claude" else exe.parent.parent)
        r = subprocess.run(sandbox.bwrap("/", rw=[home], ro=[extra]) + [str(exe), "--version"], capture_output=True, text=True, timeout=60)
        report(f"{agent}: runs inside the sandbox", r.returncode == 0, (r.stderr or r.stdout).strip()[-300:])
        report(f"{agent}: logged in for Axon", (home / runtime.LOGIN_FILE[agent]).exists(),
               "run: " + ("CLAUDE_CONFIG_DIR=~/.local/share/axon/agents/claude claude auth login" if agent == "claude"
                          else "CODEX_HOME=~/.local/share/axon/agents/codex codex login --device-auth"))
    names = [name] if name else [runtime.project_for(os.getcwd())] if runtime.project_for(os.getcwd()) else \
        sorted(f.stem for f in (runtime.config_dir() / "projects").glob("*.toml"))
    rt = runtime.Runtime(runtime.open_store())
    for p in names:
        try:
            proj = runtime.load_project(p)
        except Exception as e:
            report(f"project {p}: config", False, str(e)[:300])
            continue
        if not proj["checks"]:
            report(f"project {p}: has checks", False, f"no [checks] in {runtime.config_dir() / 'projects' / (p + '.toml')}: results are not verified")
            continue
        head = subprocess.run(["git", "-C", proj["path"], "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        try:
            results = integrate.run_checks(rt, {"id": "doctor", "project": p, "checks": None, "approved": 1}, proj, head, head)
        except Exception as e:
            report(f"project {p}: checks", False, str(e)[:300])
            continue
        for check, rc, tail in results:
            hint = tail[-400:]
            missing = re.search(r"(\S+): (?:command )?not found", tail)
            found = missing and shutil.which(missing.group(1))
            if found and found.startswith(sandbox.HOME + "/"):  # hidden with $HOME inside the sandbox
                hint = (f"{missing.group(1)} lives in your home folder, which the sandbox hides; add under [sandbox] in the project file:\n"
                        f"     ro = [{json.dumps(str(Path(found).resolve().parent))}]  (and any folder it needs, e.g. its cache)")
            report(f"project {p}: check {check} passes in the sandbox (on HEAD {head[:10]})", rc == 0,
                   hint if found else f"(not a sandbox problem if your code at HEAD really fails it)\n{hint}")
    print("all good" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


def show_brainstorm(store, bid):
    b = brainstorm.describe(store, bid)
    if not b:
        sys.exit(f"no brainstorm {bid}")
    print(f"brainstorm {b['id']}  {b['status']}  phase {b['phase']}  {b['project_id']}  lead {b['agents']['lead']}, other {b['agents']['other']}")
    print(f"goal: {b['goal'].strip().splitlines()[0][:200]}")
    if b["why"]:
        print(f"why: {b['why']}")
    if b["collecting"]:
        print("\ncollecting questions from both agents, so you answer each thing once ...")
    for q in b["questions"]:
        if q.get("gate"):
            print(f"\n{q['agent']} asked; merged into one list:\n{q['question']}\n  answer with: axon brainstorm {b['id']} --answer")
            continue
        opts = f"  options: {' | '.join(q['options'])}" if q["options"] else ""
        print(f"\n{q['agent']} asks: {q['question']}{opts}\n  answer with: axon answer {q['task_id']}")
    if b["qa"]:
        print("\nanswers so far:", *[f"  Q ({x['by']}): {x['q']}\n  A: {x['a']}" for x in b["qa"]], sep="\n")
    plan = b["plan"]
    if plan:
        print(f"\nplan: {plan.get('summary', '')}")
        for t in plan["tasks"]:
            print(f"  {t['id']}  [{t['agent']}, by {t.get('by', '?')}]  {t['title']}  scope {','.join(t['scope'])}"
                  + (f"  after {t['after']}" if t.get("after") else ""))
        for dsg in plan.get("disagreements") or []:
            print(f"  disagree: {dsg.get('topic')}\n    claude: {dsg.get('claude')}\n    codex: {dsg.get('codex')}")
        for r in plan.get("risks") or []:
            print(f"  risk: {r}")
        if b["objections"]:
            print(f"\nthe checker still objects:\n{b['objections']}")
        if b["status"] == "READY":
            print("\nwhat each agent will be given (approve means exactly this):")
            for t in plan["tasks"]:
                print(f"\n[{t['id']}] " + t["brief"].replace("\n", "\n    "))
            print(f"\ncreate these tasks: axon brainstorm {b['id']} --approve")
        elif b["created"]:
            print("\ncreated tasks:", ", ".join(f"{k} -> {v}" for k, v in b["created"].items()))


def brainstorm_cmd(store, a):
    if not a.target:
        for b in brainstorm.recent(store, 20):
            print(f"{b['id']:>4}  {b['status']:<9} {b['phase']:<8} {b['project_id']:<12} {b['goal'].strip().splitlines()[0][:70]}")
        return
    if a.target.isdigit():
        bid = int(a.target)
        try:
            if a.stop:
                brainstorm.cancel(store, bid)
                print("stopped")
            elif a.answer:
                gate = next((q for q in brainstorm.describe(store, bid)["questions"] if q.get("gate")), None)
                if not gate:
                    sys.exit("no merged questions are waiting for an answer")
                answers = []
                for i, q in enumerate(gate["questions"], 1):
                    print(f"{i}) {q['question']}\n   (asked by: {'; '.join(q['from'])})")
                    print(*(f"     {j}. {o}" for j, o in enumerate(q["options"], 1)), sep="\n")
                    x = input("   answer" + (" (number or text): " if q["options"] else ": ")).strip()
                    answers.append(q["options"][int(x) - 1] if q["options"] and x.isdigit() and 1 <= int(x) <= len(q["options"]) else x)
                brainstorm.answer_gate(store, bid, answers)
                print("sent to both agents")
            elif a.approve:
                print("queued:", ", ".join(f"{k} -> task {v}" for k, v in brainstorm.create_tasks(store, bid).items()))
            else:
                show_brainstorm(store, bid)
        except ValueError as e:
            sys.exit(str(e))
        return
    goal = sys.stdin.read() if a.target == "-" else a.target
    opts = {r: {k: getattr(a, f"{r}_{k}") for k in ("model", "effort", "light_model", "light_effort")} for r in ("lead", "other")}
    try:
        bid = brainstorm.start(store, project_arg(a.project), goal, a.lead, a.other, opts)
    except (ValueError, subprocess.CalledProcessError) as e:
        sys.exit(str(e))
    print(bid)
    if not runtime.runner_active():
        print("note: nothing is running tasks yet; open `axon` (GUI) or run `axon service install` once", file=sys.stderr)
    print(f"the agents may ask you questions: axon brainstorm {bid}   shows them and the progress", file=sys.stderr)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv = ["gui", *argv]  # `axon` alone (or with GUI flags) opens the GUI
    ap = argparse.ArgumentParser(prog="axon", description="Run coding agents on separate, sandboxed tasks. "
                                 "`axon` alone opens the GUI. Inside a project folder -p is not needed.",
                                 epilog="start here: axon init (in a repository), axon add \"what to change\", axon logs -f ID")
    sub = ap.add_subparsers(dest="cmd", metavar="command")
    from .__main__ import gui_args
    gui_args(sub.add_parser("gui", help="open the control GUI (the default); starts it if it is not running"))
    i = sub.add_parser("init", help="make the Git repository you are in a Axon project")
    i.add_argument("name", nargs="?", help="default: the folder name")
    a = sub.add_parser("add", help="queue a task: axon add \"fix the login bug\"")
    a.add_argument("-p", "--project", help="default: the project of the current folder")
    a.add_argument("-a", "--agent", default="claude", choices=sorted(runtime.ADAPTERS), help="default: claude")
    a.add_argument("-s", "--scope", action="append", default=[], help="path prefix the task may edit (repeatable; default: everything)")
    a.add_argument("--base", default="HEAD", help="commit to start from")
    a.add_argument("--after", type=int, help="start only after this task is COMPLETED, from its result")
    a.add_argument("--model", help="model for this task only (default: the [agents] setting, else the CLI default)")
    a.add_argument("--effort", help="effort for this task only")
    a.add_argument("--check", action="append", dest="checks", metavar="NAME",
                   help="verify this task with only these project checks (repeatable); integration still runs all")
    a.add_argument("-f", "--follow", action="store_true", help="then show the agent's output live, as `axon logs -f`")
    a.add_argument("spec", help="what to do (short is fine), or - to read it from stdin")
    bs = sub.add_parser("brainstorm", help="Claude and Codex plan together first: axon brainstorm \"goal\" | ID [--approve|--stop] | (list)")
    bs.add_argument("target", nargs="?", help="the goal (text, or - for stdin) to start one, or the id of one to show; omit to list")
    bs.add_argument("-p", "--project", help="default: the project of the current folder")
    bs.add_argument("--lead", choices=sorted(runtime.ADAPTERS), help="asks first and writes the merged plan (default: [brainstorm] lead)")
    bs.add_argument("--other", choices=sorted(runtime.ADAPTERS), help="the second planner and the checker (default: [brainstorm] other)")
    for role in ("lead", "other"):
        for k in ("model", "effort", "light-model", "light-effort"):
            bs.add_argument(f"--{role}-{k}", default="", help=f"{k.replace('-', ' ')} for the {role} in this brainstorm only"
                            + (" (the steps that only ask and check)" if "light" in k else ""))
    bs.add_argument("--approve", action="store_true", help="turn a finished plan into queued tasks")
    bs.add_argument("--answer", action="store_true", help="answer the merged questions both agents are waiting on")
    bs.add_argument("--stop", action="store_true", help="stop a running brainstorm")
    sub.add_parser("ls", help="list tasks (running ones show how long and when they last wrote output)")
    sub.add_parser("run", help="run tasks in this terminal, without the GUI (one runner per machine)")
    for name, help_ in [("show", "task details and events"), ("stop", "stop or cancel a task"),
                        ("approve", "approve a task waiting for approval or in review"),
                        ("reject", "reject a task in review"),
                        ("apply", "write a completed task's changes into your project folder (uncommitted)")]:
        sub.add_parser(name, help=help_).add_argument("id", type=int)
    sub.add_parser("summarize", help="summarize a task with the local model (sources cited)").add_argument("id", type=int)
    sub.add_parser("integrate", help="merge a completed task into the integration branch (checks run on the result)").add_argument("id", type=int)
    rv = sub.add_parser("review", help="queue a read-only review of a completed task's exact result")
    rv.add_argument("id", type=int)
    rv.add_argument("-a", "--agent", default="claude", choices=sorted(runtime.ADAPTERS), help="default: claude")
    rv2 = sub.add_parser("revise", help="queue a bounded follow-up round that addresses a review's findings")
    rv2.add_argument("id", type=int)
    rv2.add_argument("-a", "--agent", choices=sorted(runtime.ADAPTERS), help="default: the original agent")
    ri = sub.add_parser("review-integration", help="queue a read-only review of the merged integration commit")
    ri.add_argument("project", nargs="?")
    ri.add_argument("-a", "--agent", default="claude", choices=sorted(runtime.ADAPTERS), help="default: claude")
    sub.add_parser("discard", help="roll back: drop a project's integration branch").add_argument("project", nargs="?")
    u = sub.add_parser("usage", help="what attempts cost: time, context bytes and the tokens the CLIs exposed")
    u.add_argument("-p", "--project")
    u.add_argument("--hours", type=float, default=24 * 7)
    g = sub.add_parser("gc", help="delete old attempt directories of finished tasks")
    g.add_argument("--days", type=int, help="default: [limits] retention_days (30)")
    g.add_argument("--dry-run", action="store_true")
    sub.add_parser("verify-integration", help="run every check on a project's integration commit").add_argument("project", nargs="?")
    ao = sub.add_parser("agent-options", help="show or set the model and effort an agent runs with (empty = the CLI default)")
    ao.add_argument("agent", nargs="?", choices=agent_options.AGENTS)
    ao.add_argument("--model")
    ao.add_argument("--effort")
    sub.add_parser("integration", help="show a project's integration branch").add_argument("project", nargs="?")
    sub.add_parser("promote", help="fast-forward your checked-out branch to the integration branch").add_argument("project", nargs="?")
    an = sub.add_parser("answer", help="answer the agent's question")
    an.add_argument("id", type=int)
    an.add_argument("text", nargs="?", help="your answer, or the number of an offered option; omit to be asked")
    lg = sub.add_parser("logs", help="what the agent said and did in the latest attempt (-f: live)")
    lg.add_argument("id", type=int)
    lg.add_argument("-f", "--follow", action="store_true")
    ch = sub.add_parser("chat", help="talk to claude/codex interactively in the sandbox (tmux; run again to re-attach)")
    ch.add_argument("project", nargs="?", help="default: the project of the current folder")
    ch.add_argument("-a", "--agent", default="claude", choices=["claude", "codex", "shell"],
                    help="default: claude; shell = plain bash in the same sandbox")
    ch.add_argument("-n", "--name", default="", help="extra chat on the same project and agent (own clone)")
    sub.add_parser("passwd", help="set the password the GUI asks for (needed for remote access)")
    rm = sub.add_parser("remote", help="open the GUI to your other devices through Tailscale (any network)")
    rm.add_argument("--off", action="store_true")
    sv = sub.add_parser("service", help="keep Axon running in the background (systemd user service)")
    sv.add_argument("action", choices=["install", "remove"])
    sub.add_parser("doctor", help="check the sandbox, agent logins and each project's checks before real tasks").add_argument("project", nargs="?")
    args = ap.parse_args(argv)
    if args.cmd == "gui":
        from .__main__ import run_gui
        return run_gui(args)
    if args.cmd in ("chat", "review-integration", "discard", "verify-integration", "integration", "promote"):
        args.project = project_arg(args.project)
    if args.cmd == "chat":
        return chat(args.project, args.agent, args.name)
    if args.cmd == "init":
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if top.returncode:
            sys.exit("run this inside a Git repository (git init first if it is a new folder)")
        root = Path(top.stdout.strip())
        if runtime.project_for(root) and runtime.project_for(root) != args.name:
            sys.exit(f"already a project: {runtime.project_for(root)}")
        try:
            f = runtime.create_project(args.name or re.sub(r"[^A-Za-z0-9._-]", "-", root.name).lstrip("._-") or "project", str(root))
        except ValueError as e:
            sys.exit(str(e))
        print(f"project {f.stem} -> {root}\nadd your test commands under [checks] in {f} so results are verified\n"
              f"then: axon doctor   and   axon add \"what to change\"")
        return
    if args.cmd == "passwd":
        return passwd()
    if args.cmd == "remote":
        return remote(args.off)
    if args.cmd == "service":
        return service(args.action)
    if args.cmd == "doctor":
        return doctor(args.project)

    store = runtime.open_store()
    if args.cmd == "add":
        spec = sys.stdin.read() if args.spec == "-" else args.spec
        project = project_arg(args.project)
        try:
            tid, dup = runtime.add_task(store, project, args.agent, spec, args.scope, args.base, after=args.after,
                                          checks=args.checks, model=args.model, effort=args.effort)
        except (ValueError, subprocess.CalledProcessError) as e:
            sys.exit(str(e))
        if dup:
            sys.exit(f"duplicate of task {dup}; not queued")
        print(tid)
        if not runtime.runner_active():
            print("note: nothing is running tasks yet; open `axon` (GUI) or run `axon service install` once", file=sys.stderr)
        if args.follow:
            logs(store, tid, True)
        else:
            print(f"queued for {args.agent} on {project}; watch it live: axon logs -f {tid}", file=sys.stderr)
    elif args.cmd == "brainstorm":
        brainstorm_cmd(store, args)
    elif args.cmd == "ls":
        show_tasks(store)
    elif args.cmd == "show":
        show_task(store, args.id)
    elif args.cmd == "run":
        runtime.Runtime(store).run_forever()
    elif args.cmd == "summarize":
        try:
            r = helper.summarize(store, args.id)
        except (ValueError, OSError) as e:
            sys.exit(f"summarize failed: {e}")
        print(r["text"], f"\ncited: {', '.join(r['cited']) or 'none'}",
              *([f"unverified refs: {', '.join(r['unknown_refs'])}"] if r["unknown_refs"] else []), sep="\n")
    elif args.cmd == "integrate":
        rt = runtime.Runtime(store)
        try:
            commit = integrate.integrate(rt, args.id)
        except integrate.IntegrationError as e:
            sys.exit(f"not integrated: {e}")
        print(f"integrated at {commit[:10]}; checks passed")
    elif args.cmd == "review":
        try:
            rid, dup = runtime.request_review(store, args.id, args.agent)
        except ValueError as e:
            sys.exit(str(e))
        if dup:
            sys.exit(f"duplicate of review task {dup}; not queued")
        print(rid)
    elif args.cmd == "revise":
        try:
            rid, dup = runtime.revise(store, args.id, args.agent)
        except ValueError as e:
            sys.exit(str(e))
        print(f"duplicate of task {dup}; not queued" if dup else rid)
    elif args.cmd == "review-integration":
        try:
            rid, dup = runtime.request_integration_review(store, args.project, args.agent)
        except ValueError as e:
            sys.exit(str(e))
        print(f"duplicate of review task {dup}; not queued" if dup else rid)
    elif args.cmd == "discard":
        try:
            print(f"discarded integration branch at {integrate.discard(store, args.project)[:10]}")
        except integrate.IntegrationError as e:
            sys.exit(str(e))
    elif args.cmd == "agent-options":
        if args.agent and (args.model is not None or args.effort is not None):
            cur = runtime.load_config()["agents"]
            try:
                m, e = agent_options.save(runtime.config_dir() / "config.toml", args.agent,
                                          cur[f"{args.agent}_model"] if args.model is None else args.model,
                                          cur[f"{args.agent}_effort"] if args.effort is None else args.effort)
            except ValueError as err:
                sys.exit(str(err))
        cfg = runtime.load_config()
        for agent in ([args.agent] if args.agent else agent_options.AGENTS):
            m, e = agent_options.effective(cfg, agent)
            print(f"{agent:<7} model {m or 'default':<28} effort {e or 'default':<8} "
                  f"(efforts: {', '.join(agent_options.EFFORTS[agent])})")
    elif args.cmd == "usage":
        rep = usage.report(store, time.time() - args.hours * 3600, args.project)
        print(f"last {args.hours:g} h{' / ' + args.project if args.project else ''}")
        print(f"{'AGENT':<7} {'KIND':<10} {'ATT':>3} {'OUTCOMES':<30} {'SECS':>6} {'PROMPT KB':>9} {'IN TOK':>9} {'CACHED':>9} {'OUT TOK':>8} {'COST $':>7}  SETTINGS")
        for (agent, kind), r in rep.items():
            outcomes = ",".join(f"{k}:{v}" for k, v in sorted(r["outcomes"].items()))
            tokens = (f"{r['input']:>9} {r['cached']:>9} {r['output']:>8} {r['cost_usd']:>7.3f}" if r["with_usage"]
                      else f"{'-':>9} {'-':>9} {'-':>8} {'-':>7}")
            print(f"{agent:<7} {kind:<10} {r['attempts']:>3} {outcomes:<30} {r['seconds']:>6.0f} {r['prompt_bytes'] / 1024:>9.1f} {tokens}  {','.join(r['settings'])}")
        if not rep:
            print("no finished attempts in this window")
    elif args.cmd == "gc":
        r = retention.gc(store, args.days, args.dry_run)
        print(f"{'would remove' if r['dry_run'] else 'removed'} {r['attempt_dirs']} attempt directories "
              f"({r['bytes'] / 1e6:.1f} MB) older than {r['days']} days")
    elif args.cmd == "verify-integration":
        try:
            print(f"all checks passed at {integrate.verify(runtime.Runtime(store), args.project)[:10]}")
        except integrate.IntegrationError as e:
            sys.exit(f"not verified: {e}")
    elif args.cmd == "integration":
        st = integrate.status(store, args.project)
        print(f"branch {st['branch'] or '(detached)'} @ {st['head'][:10]}; integration @ {(st['commit'] or 'none')[:10]}")
        print(f"tasks: {', '.join(map(str, st['tasks'])) or 'none'}; checks: " +
              (", ".join(f"{c['name']} {'ok' if not c['rc'] else 'FAILED'}" for c in st["checks"]) or "none"))
        print("can promote" if st["can_promote"] else f"cannot promote: {st['reason']}")
    elif args.cmd == "promote":
        try:
            commit = integrate.promote(store, args.project)
        except integrate.IntegrationError as e:
            sys.exit(f"not promoted: {e}")
        print(f"fast-forwarded to {commit[:10]}")
    elif args.cmd == "stop":
        print(runtime.stop_task(store, args.id))
    elif args.cmd == "apply":
        try:
            files = runtime.apply_result(store, args.id)
        except (ValueError, subprocess.CalledProcessError) as e:
            sys.exit(f"not applied: {e}")
        print("written into your project folder (uncommitted):", *files, sep="\n  ")
    elif args.cmd == "logs":
        logs(store, args.id, args.follow)
    elif args.cmd == "answer":
        t = store.one("select status, note from tasks where id = ?", args.id)
        if not t or t["status"] != "WAITING_INPUT":
            sys.exit(f"task {args.id} is not waiting for input")
        if bid := brainstorm.held(store, args.id):
            sys.exit(f"these questions were merged with the other agent's: answer them with axon brainstorm {bid} --answer")
        options, text, qs = runtime.ask_options(store, args.id), args.text, runtime.ask_questions(store, args.id)
        if text is None and qs:  # several questions: one at a time, each with its own numbered choices
            answers = []
            for i, q in enumerate(qs, 1):
                print(f"{i}) {q['question']}")
                print(*(f"     {j}. {o}" for j, o in enumerate(q["options"], 1)), sep="\n")
                a = input("   answer" + (" (number or text): " if q["options"] else ": ")).strip()
                answers.append(q["options"][int(a) - 1] if q["options"] and a.isdigit() and 1 <= int(a) <= len(q["options"]) else a)
            text = "\n".join(f"{i}) {a}" for i, a in enumerate(answers, 1)) if all(answers) else ""
        elif text is None:  # ask here, with the agent's own choices numbered
            print(t["note"])
            print(*(f"  {i}) {o}" for i, o in enumerate(options, 1)), sep="\n")
            text = input("answer" + (" (number or text): " if options else ": ")).strip()
        if options and text.isdigit() and 1 <= int(text) <= len(options):
            text = options[int(text) - 1]
        try:
            answered = bool(text) and runtime.answer(store, args.id, text)
        except ValueError as e:
            sys.exit(str(e))
        if not answered:
            sys.exit(f"task {args.id} is not waiting for input" if text else "empty answer")
    elif args.cmd == "approve":
        if not runtime.approve(store, args.id):
            sys.exit(f"task {args.id} is not waiting for approval or review")
    elif args.cmd == "reject":
        if not runtime.reject(store, args.id):
            sys.exit(f"task {args.id} is not in review")


if __name__ == "__main__":
    main()
