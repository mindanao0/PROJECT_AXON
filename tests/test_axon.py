"""Acceptance scenarios (docs/MVP_CONTRACT.md §8) run against fake-agent.

Needs Linux with bwrap, git and a systemd user session. Run: python -m unittest -v
"""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from axon import runtime, sandbox

DONE = '[[step]]\ndo = "mcp"\ntool = "report_result"\nargs = {status = "done", summary = "ok"}\n'
TOKEN = "FAKE-SECRET-0123456789abcdefghij"


def toml(v):
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k} = {toml(x)}" for k, x in v.items()) + "}"
    if isinstance(v, list):
        return "[" + ", ".join(toml(x) for x in v) + "]"
    return json.dumps(v)


def step(do, **kw):
    body = "".join(f"{k} = {toml(v)}\n" for k, v in kw.items())
    return f'[[step]]\ndo = "{do}"\n{body}'


def edit(path, text="x\n", attempt=None):
    return step("edit", path=path, text=text, **({"attempt": attempt} if attempt else {}))


def sandbox_works():
    """bwrap + a systemd user scope: absent on most CI runners, so these tests skip there."""
    try:
        for cmd in (["bwrap", "--ro-bind", "/", "/", "true"], ["systemd-run", "--user", "--scope", "-q", "true"]):
            if subprocess.run(cmd, capture_output=True, timeout=20).returncode:
                return False
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


@unittest.skipUnless(sandbox_works(), "needs bubblewrap and a systemd user session")
class AxonTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="axon-test-"))
        os.environ["AXON_HOME"] = str(self.tmp / "home")
        os.environ["AXON_CONFIG"] = str(self.tmp / "cfg")
        self.proj = self.tmp / "proj"
        for f, text in {"src/a.py": "a = 1\n", "docs/b.md": "doc\n", "tests/t.sh": "true\n"}.items():
            (self.proj / f).parent.mkdir(parents=True, exist_ok=True)
            (self.proj / f).write_text(text)
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        (self.tmp / "cfg" / "projects").mkdir(parents=True)
        (self.tmp / "cfg" / "config.toml").write_text(
            "[limits]\nattempt_timeout = 30\nmax_attempts = 2\nquota_backoff = [0.5]\n[slots]\nfake = 2\n")
        self.project()
        home = self.tmp / "home" / "agents" / "fake"
        home.mkdir(parents=True)
        (home / ".credentials.json").write_text(json.dumps({"token": TOKEN}))
        self.store = runtime.open_store()
        self.rt = runtime.Runtime(self.store)

    def tearDown(self):
        for a in self.store.q("select unit from attempts"):
            sandbox.stop_unit(a["unit"])
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.proj), *args], capture_output=True, text=True).stdout

    def project(self, checks=None, protected=("tests/",)):
        checks = checks or {"ok": "true"}
        lines = [f'path = "{self.proj}"', f"protected = {json.dumps(list(protected))}", "[checks]"]
        lines += [f"{k} = {json.dumps(v)}" for k, v in checks.items()]
        (self.tmp / "cfg" / "projects" / "p.toml").write_text("\n".join(lines) + "\n")

    def add(self, spec, scope=("src",)):
        tid, dup = runtime.add_task(self.store, "p", "fake", spec, scope)
        self.assertIsNone(dup)
        return tid

    def task(self, tid):
        return self.store.one("select * from tasks where id = ?", tid)

    def run_all(self, timeout=60):
        self.assertTrue(self.rt.run_until_idle(timeout), "runtime did not become idle")

    def shown(self, aid, path):
        return self.git("show", f"refs/axon/attempts/{aid}:{path}")

    def outcomes(self, tid):
        return [r["outcome"] for r in self.store.q("select outcome from attempts where task = ? order by n", tid)]

    def wait(self, cond, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            if cond():
                return
            time.sleep(0.1)
        self.fail("condition not reached")


class Completion(AxonTest):
    def test_done_task_is_verified_and_fetched(self):
        tid = self.add(edit("src/new.py", "print(1)") + DONE)
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "COMPLETED")
        self.assertEqual(self.shown(f"{tid}-1", "src/new.py"), "print(1)")
        self.assertFalse((self.proj / "src/new.py").exists(), "project checkout must not change")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.git("rev-parse", "HEAD"))

    def test_checks_have_no_network_or_host_sockets(self):
        self.project({"nonet": "! curl -s -m3 https://example.com",
                      "nosock": "test ! -S /var/run/docker.sock",
                      "nohome": f"test ! -e {Path.home()}/.ssh"})
        tid = self.add(step("mcp", tool="run_check", args={"name": "nonet"}) + DONE)
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "COMPLETED", self.task(tid)["note"])

    def test_edit_outside_scope_needs_review(self):
        tid = self.add(edit("docs/b.md") + DONE, scope=["src"])
        self.run_all()
        t = self.task(tid)
        self.assertEqual(t["status"], "REVIEW")
        self.assertIn("outside scope: docs/b.md", t["note"])
        self.assertTrue(runtime.approve(self.store, tid))
        self.assertEqual(self.task(tid)["status"], "COMPLETED")

    def test_protected_path_needs_review(self):
        tid = self.add(edit("tests/t.sh") + DONE, scope=["."])
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "REVIEW")
        self.assertIn("protected: tests/t.sh", self.task(tid)["note"])

    def test_failing_checks_retry_with_feedback_then_fail(self):
        self.project({"unit": "echo boom; false"})
        tid = self.add(step("prompt", path="src/prompt.txt", attempt=2) + DONE)
        self.run_all()
        t = self.task(tid)
        self.assertEqual((t["status"], t["attempts"]), ("FAILED", 2))
        self.assertIn("check unit failed (exit 1):\nboom", self.shown(f"{tid}-2", "src/prompt.txt"))

    def test_unreported_exit_needs_review(self):
        tid = self.add(edit("src/x.py"))
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "REVIEW")

    def test_crash_retries_then_fails(self):
        tid = self.add(step("garbage") + step("crash", code=3))
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "FAILED")
        self.assertEqual(self.outcomes(tid), ["crashed", "crashed"])

    def test_ask_user_then_answer_resumes_from_snapshot(self):
        spec = (edit("src/one.py", attempt=1)
                + step("mcp", tool="ask_user", args={"question": "which color?"}, attempt=1)
                + step("prompt", path="src/prompt.txt", attempt=2)
                + step("mcp", tool="report_result", args={"status": "done", "summary": "ok"}, attempt=2))
        tid = self.add(spec)
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "WAITING_INPUT")
        self.assertTrue(runtime.answer(self.store, tid, "blue"))
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "COMPLETED")
        self.assertIn("Q: which color?\nA: blue", self.shown(f"{tid}-2", "src/prompt.txt"))
        self.assertEqual(self.shown(f"{tid}-2", "src/one.py"), "x\n")


class Scheduling(AxonTest):
    def test_duplicate_task_is_not_queued(self):
        tid = self.add(DONE)
        self.assertEqual(runtime.add_task(self.store, "p", "fake", DONE, ["src"]), (None, tid))
        runtime.stop_task(self.store, tid)
        self.assertIsNotNone(runtime.add_task(self.store, "p", "fake", DONE, ["src"])[0])

    def test_overlapping_scopes_never_run_together(self):
        work = step("sleep", s=1) + DONE
        a = self.add(work, ["src"])
        b = self.add(work + "# b\n", ["src/sub"])
        c = self.add(work + "# c\n", ["docs"])
        self.run_all()
        span = {r["task"]: (r["started"], r["ended"]) for r in self.store.q("select * from attempts")}
        self.assertTrue(span[b][0] >= span[a][1], "b overlaps a and must wait")
        self.assertTrue(span[c][0] < span[a][1], "c is disjoint and should run alongside a")
        self.assertEqual({self.task(i)["status"] for i in (a, b, c)}, {"COMPLETED"})

    def test_completed_work_is_listed_in_later_prompts(self):
        first = self.add(edit("src/a2.py") + DONE)
        self.run_all()
        tid = self.add(step("prompt", path="src/prompt.txt") + DONE)
        self.run_all()
        self.assertIn(f"- task {first} at", self.shown(f"{tid}-1", "src/prompt.txt"))

    def test_quota_waits_for_cooldown_without_using_a_retry(self):
        tid = self.add(step("rate_limit", attempt=1) + edit("src/q.py", attempt=2) + DONE)
        self.run_all()
        t = self.task(tid)
        self.assertEqual((t["status"], t["attempts"]), ("COMPLETED", 0))
        self.assertEqual(self.outcomes(tid), ["quota", "done"])

    def test_clear_cooldown_ends_it_for_one_or_all_agents(self):
        for a in ("claude", "codex"):
            self.store.x("insert into cooldowns(agent, until, strikes) values (?, ?, 2)", a, time.time() + 3600)
        self.assertEqual(runtime.clear_cooldown(self.store, "codex"), ["codex"])
        self.assertEqual(runtime.clear_cooldown(self.store), ["claude"])
        self.assertEqual(runtime.clear_cooldown(self.store), [])
        self.assertEqual(self.store.one("select count(*) n from cooldowns")["n"], 0)


class Safety(AxonTest):
    def test_stop_kills_orphaned_processes(self):
        tid = self.add(step("orphan", path="orphan.log") + step("hang"))
        runner = threading.Thread(target=self.rt.run_until_idle, kwargs={"timeout": 60})
        runner.start()
        log = self.tmp / "home" / "attempts" / f"{tid}-1" / "repo" / "orphan.log"
        self.wait(log.exists)
        unit = self.store.one("select unit from attempts where task = ?", tid)["unit"]
        runtime.stop_task(self.store, tid)
        runner.join(30)
        self.assertEqual(self.task(tid)["status"], "CANCELLED")
        self.assertFalse(sandbox.active(unit))
        lines = len(self.shown(f"{tid}-1", "orphan.log").splitlines())
        self.assertGreater(lines, 0)
        time.sleep(0.5)
        self.assertEqual(subprocess.run(["pgrep", "-f", str(log)], capture_output=True).returncode, 1)

    def test_credential_in_diff_blocks_fetch_and_is_redacted(self):
        spec = (step("shell", cmd='cat "$AXON_AGENT_HOME/.credentials.json" > src/leak.txt')
                + step("mcp", tool="report_result", args={"status": "done", "summary": f"token {TOKEN}"}))
        tid = self.add(spec)
        self.run_all()
        t = self.task(tid)
        self.assertEqual(t["status"], "FAILED")
        self.assertIn("credential", t["note"])
        self.assertEqual(self.git("rev-parse", "--verify", "-q", f"refs/axon/attempts/{tid}-1"), "")
        events = " ".join(e["data"] for e in self.store.q("select data from events"))
        self.assertNotIn(TOKEN, events)
        self.assertIn("[REDACTED]", events)

    def test_agent_cannot_reach_host_secrets_or_control_state(self):
        other = self.tmp / "home" / "agents" / "codex"
        other.mkdir(parents=True)
        (other / "auth.json").write_text("{}")
        outside = Path.home() / f".axon-escape-{os.getpid()}"
        probes = {
            "real_home": f"touch {outside}",
            "project_objects": f"touch {self.proj}/.git/objects/x",
            "project_checkout": f"cat {self.proj}/docs/b.md",
            "other_agent": f"cat {other}/auth.json",
            "axon_db": f"cat {self.tmp}/home/axon.db",
            "docker": "test -S /var/run/docker.sock",
            "user_bus": f"test -S /run/user/{os.getuid()}/bus",
            "dns_config": "cat /etc/resolv.conf",  # agents need DNS to reach their provider
        }
        cmd = "; ".join(f'({c}) >/dev/null 2>&1 && echo "{k} OPEN" || echo "{k} closed"' for k, c in probes.items())
        tid = self.add(step("shell", cmd=f"{{ {cmd}; }} > src/probe.txt") + DONE)
        self.run_all()
        report = self.shown(f"{tid}-1", "src/probe.txt")
        self.assertFalse(outside.exists())
        self.assertFalse((self.proj / ".git/objects/x").exists())
        self.assertIn("dns_config OPEN", report)
        for k in probes:
            if k in ("real_home", "dns_config"):
                continue  # real_home writes land in the sandbox's private tmpfs; checked above
            self.assertIn(f"{k} closed", report)

    def test_runner_restart_requeues_and_rejects_stale_result(self):
        tid = self.add(step("hang"))
        self.rt.tick()  # the old runner starts the attempt, then stops scheduling ("crashes")
        self.wait(lambda: (self.tmp / "home" / "attempts" / f"{tid}-1" / "agent.log").exists())  # agent started
        time.sleep(0.3)
        runtime.Runtime(self.store).recover()  # a new runner after the crash
        for th in self.rt.threads:
            th.join(30)  # the old attempt thread still reports in, too late
        self.assertEqual(self.task(tid)["status"], "QUEUED")
        self.assertEqual(self.outcomes(tid), ["interrupted"])
        kinds = [e["kind"] for e in self.store.q("select kind from events where task = ?", tid)]
        self.assertIn("stale-result-dropped", kinds)
        runtime.stop_task(self.store, tid)

    def test_crash_after_fetch_before_recording_is_rerun_once(self):
        tid = self.add(edit("src/x.py") + DONE)
        self.rt._finish = lambda *a, **k: None  # the runner dies after the result was fetched
        self.rt.tick()
        for th in self.rt.threads:
            th.join(30)
        self.assertTrue(self.git("rev-parse", "--verify", f"refs/axon/attempts/{tid}-1").strip())
        self.assertEqual(self.task(tid)["status"], "RUNNING")
        rt = runtime.Runtime(self.store)  # the next runner
        rt.recover()
        self.assertEqual(self.task(tid)["status"], "QUEUED")
        self.assertTrue(rt.run_until_idle(60))
        self.assertEqual(self.task(tid)["status"], "COMPLETED")
        self.assertEqual(self.outcomes(tid), ["interrupted", "done"])
        self.assertEqual(self.store.q("select 1 from attempts where status = 'running'"), [])
        self.assertNotIn("x.py", self.git("ls-files"))  # the project checkout was never touched

    def test_instruction_during_an_attempt_discards_its_result(self):
        tid = self.add(step("sleep", s=2, attempt=1) + step("prompt", path="src/prompt.txt", attempt=2) + DONE)
        self.rt.tick()
        self.wait(lambda: (self.tmp / "home" / "attempts" / f"{tid}-1" / "agent.log").exists())
        self.assertTrue(runtime.instruct(self.store, tid, "use blue"))
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "COMPLETED")
        self.assertEqual(self.outcomes(tid), ["done", "done"])  # attempt 1 finished, but its result was not accepted
        self.assertIn("User instruction: use blue", self.shown(f"{tid}-2", "src/prompt.txt"))
        self.assertEqual(self.task(tid)["attempts"], 0)  # no retry spent
        self.assertIn("instruction changed", " ".join(
            r["data"] for r in self.store.q("select data from events where task = ? and kind = 'status'", tid)))

    def test_process_over_the_memory_limit_is_killed_even_with_swap_available(self):
        (self.tmp / "cfg" / "config.toml").write_text(
            "[limits]\nagent_memory = \"100M\"\nattempt_timeout = 30\nmax_attempts = 2\n[slots]\nfake = 2\n")
        self.rt = runtime.Runtime(self.store)
        tid = self.add(step("shell", cmd="python3 -c 'x = b\"x\" * (1500 * 2**20); print(\"survived\")'") + DONE)
        t0 = time.time()
        self.run_all()
        self.assertLess(time.time() - t0, 25)  # the cgroup answered, not the 30 s attempt timeout
        logs = "".join(f.read_text() for f in (self.tmp / "home" / "attempts").glob("*/agent.log"))
        # Either the hog or the whole scope dies (kernel OOM or systemd-oomd); without MemorySwapMax=0 it swaps and survives.
        self.assertNotIn("survived", logs)
        self.assertFalse(any(sandbox.active(a["unit"]) for a in self.store.q("select unit from attempts")))

    def test_task_stays_pinned_to_its_base_when_the_project_moves(self):
        base = self.git("rev-parse", "HEAD").strip()
        tid = self.add(edit("src/x.py") + DONE)
        (self.proj / "docs/b.md").write_text("changed later\n")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "moved")
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "COMPLETED")
        self.assertEqual(self.task(tid)["base"], base)
        self.assertEqual(self.git("rev-parse", f"refs/axon/attempts/{tid}-1~1").strip(), base)

    def test_hooks_and_config_planted_in_the_clone_never_run_on_the_host(self):
        marker = self.tmp / "ran-on-host"
        plant = (f"echo '#!/bin/sh' > .git/hooks/post-commit; echo 'touch {marker}' >> .git/hooks/post-commit; "
                 f"chmod +x .git/hooks/post-commit; git config core.hooksPath .git/hooks; "
                 f"git config core.fsmonitor 'touch {marker}; :'")
        tid = self.add(step("shell", cmd=plant) + edit("src/x.py") + DONE)
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "COMPLETED", self.task(tid)["note"])
        self.assertFalse(marker.exists())
        self.assertEqual(sorted(p.name for p in (self.proj / ".git/hooks").glob("post-commit")), [])

    def test_agent_settings_in_a_result_need_review(self):
        tid = self.add(edit(".claude/settings.json", '{"hooks": {}}\n') + DONE, scope=["."])
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "REVIEW")
        self.assertIn("protected: .claude/settings.json", self.task(tid)["note"])

    def test_a_retry_does_not_start_on_agent_settings_an_attempt_planted(self):
        self.project({"unit": "false"})
        tid = self.add(edit(".codex/config.toml", 'notify = ["true"]\n', attempt=1) + DONE, scope=["."])
        self.run_all()
        t = self.task(tid)
        self.assertEqual(t["status"], "WAITING_APPROVAL")
        self.assertIn("agent settings changed (.codex/config.toml)", t["note"])
        self.assertEqual(self.outcomes(tid), ["done", "needs-approval"])
        self.assertTrue(runtime.approve(self.store, tid))
        self.run_all()
        self.assertEqual(self.outcomes(tid), ["done", "needs-approval", "done"])


class AgentConfig(unittest.TestCase):
    def test_agent_settings_are_always_protected_and_their_changes_found(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"AXON_CONFIG": f"{d}/cfg"}):
            proj = Path(d, "proj")
            git = ["git", "-C", str(proj), "-c", "user.name=t", "-c", "user.email=t@t"]
            (proj / "src").mkdir(parents=True)
            (proj / "src/x.py").write_text("x = 1\n")
            subprocess.run(["git", "init", "-q", str(proj)], check=True)
            subprocess.run([*git, "add", "-A"], check=True)
            subprocess.run([*git, "commit", "-qm", "a"], check=True)
            for f in (".claude/settings.json", ".mcp.json", "src/.claude/notes.md", "src/x.py"):
                (proj / f).parent.mkdir(parents=True, exist_ok=True)
                (proj / f).write_text("changed\n")
            subprocess.run([*git, "add", "-A"], check=True)
            subprocess.run([*git, "commit", "-qm", "b"], check=True)
            Path(d, "cfg/projects").mkdir(parents=True)
            Path(d, "cfg/projects/p.toml").write_text(f'path = "{proj}"\nprotected = ["tests/", ".claude"]\n')
            self.assertEqual(runtime.load_project("p")["protected"], [".claude", ".codex", ".mcp.json", "tests"])
            self.assertEqual(runtime.agent_config_changes(str(proj), "HEAD~1", "HEAD"), [".claude/settings.json", ".mcp.json"])


class Adapters(unittest.TestCase):
    @unittest.skipUnless(shutil.which("codex"), "codex not installed")
    def test_codex_runs_in_its_workspace_sandbox(self):
        argv, env, _ = runtime.codex_cmd("p", ["py", "mcp.py", "s"], Path("/h"), Path("/io"))
        self.assertIn("workspace-write", argv)
        self.assertEqual(env, {"CODEX_HOME": "/h"})

    @unittest.skipUnless(shutil.which("claude"), "claude not installed")
    def test_claude_has_no_shell_and_web_only_when_allowed(self):
        with tempfile.TemporaryDirectory() as io:
            argv, env, _ = runtime.claude_cmd("p", ["py", "mcp.py", "s"], Path("/h"), Path(io))
        self.assertIn("Bash,Task,WebFetch,WebSearch", argv)
        self.assertIn("--strict-mcp-config", argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Edit,Write,Glob,Grep")
        self.assertEqual(env, {"CLAUDE_CONFIG_DIR": "/h"})


if __name__ == "__main__":
    unittest.main()
