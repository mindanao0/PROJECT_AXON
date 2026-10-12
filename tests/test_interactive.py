"""Interactive mode: the agent runs as a real terminal session (tmux) instead of one `-p` prompt."""

import json
import subprocess
import threading
import unittest
from pathlib import Path
from unittest import mock

from axon import runtime
from tests.test_axon import DONE, AxonTest, edit, step


def sessions():
    return runtime.chat_sessions()


class Interactive(AxonTest):
    def setUp(self):
        super().setUp()
        with open(self.tmp / "cfg" / "config.toml", "a") as f:
            f.write('[agents]\nfake_mode = "interactive"\n')
        self.rt = runtime.Runtime(self.store)

    def test_a_session_that_stays_open_ends_when_the_agent_reports(self):
        tid = self.add(edit("src/new.py", "print(1)") + DONE + step("hang"))  # a TUI does not exit by itself
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "COMPLETED")
        self.assertEqual(self.shown(f"{tid}-1", "src/new.py"), "print(1)")
        self.assertNotIn(f"axon-chat-task{tid}", sessions())
        self.assertTrue(self.store.one("select 1 from events where task = ? and kind = 'interactive'", tid))

    def test_a_prompt_too_long_for_a_tmux_command_line_still_starts(self):
        tid = self.add(edit("src/new.py", "print(1)") + DONE + "# " + "ก" * 20000 + "\n")  # ~60 KB of UTF-8 in the prompt
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "COMPLETED")

    def test_a_session_that_goes_quiet_without_reporting_gets_one_nudge(self):
        tid = self.add(step("read_line") + step("mcp", tool="report_result", args={"status": "done", "summary": "after the nudge"}))
        with mock.patch.object(runtime, "IDLE_SECONDS", 2):
            self.run_all()
        self.assertEqual(self.task(tid)["status"], "COMPLETED")
        self.assertEqual(len(self.store.q("select 1 from events where task = ? and kind = 'nudge'", tid)), 1)
        self.assertIn("call report_result", runtime.attempt_log(f"{tid}-1").read_text())  # what it was sent

    def test_a_nudge_goes_to_a_prompt_box_never_to_a_permission_question(self):
        self.assertTrue(runtime.can_nudge("done\n❯ \n  ⏵⏵ accept edits on"))
        for ask in ("Do you want to proceed?\n❯ 1. Yes\n  2. No", "Allow this tool to run? (y/n)"):
            self.assertFalse(runtime.can_nudge(ask))

    def test_stop_ends_the_session_and_its_processes(self):
        tid = self.add(step("hang"))
        runner = threading.Thread(target=self.rt.run_until_idle, kwargs={"timeout": 60})
        runner.start()
        self.wait(lambda: f"axon-chat-task{tid}" in sessions())
        runtime.stop_task(self.store, tid)
        runner.join(30)
        self.assertEqual(self.task(tid)["status"], "CANCELLED")
        self.assertNotIn(f"axon-chat-task{tid}", sessions())

    def test_the_user_closing_the_session_files_it_as_unreported(self):
        tid = self.add(step("hang"))
        runner = threading.Thread(target=self.rt.run_until_idle, kwargs={"timeout": 60})
        runner.start()
        self.wait(lambda: f"axon-chat-task{tid}" in sessions())
        subprocess.run(["tmux", "kill-session", "-t", f"=axon-chat-task{tid}"])
        runner.join(30)
        self.assertEqual(self.outcomes(tid), ["unreported"])
        self.assertEqual(self.task(tid)["status"], "REVIEW")

    def test_the_usage_limit_text_in_the_terminal_files_quota_and_a_later_attempt_finishes(self):
        tid = self.add(step("shell", cmd="echo '5-hour limit reached, resets 3pm'", attempt=1) + step("hang", attempt=1)
                       + edit("src/q.py", attempt=2) + DONE)
        self.run_all()
        self.assertEqual(self.outcomes(tid), ["quota", "done"])
        self.assertEqual(self.task(tid)["status"], "COMPLETED")

    def test_the_limit_text_is_found_when_the_terminal_places_words_with_cursor_codes(self):
        raw = "5-hour limit\x1b[3Greached \x1b[1m· resets 3pm"
        self.assertTrue(runtime.TUI_QUOTA_RE.search(runtime.ANSI_RE.sub(" ", raw)))
        self.assertFalse(runtime.TUI_QUOTA_RE.search("the rate limit module handles a quota"))

    def test_a_quiet_session_is_flagged_as_waiting_for_the_user_and_cleared_when_it_moves(self):
        tid = self.add(step("sleep", s=5) + step("shell", cmd="echo back") + step("hang"))
        runner = threading.Thread(target=self.rt.run_until_idle, kwargs={"timeout": 60})
        runner.start()
        with mock.patch.object(runtime, "IDLE_SECONDS", 2):
            self.wait(lambda: (self.task(tid)["note"] or "").startswith("waiting for you"), 15)
            self.assertIn(f"task{tid}", self.task(tid)["note"])
            self.wait(lambda: not self.task(tid)["note"], 15)
        runtime.stop_task(self.store, tid)
        runner.join(30)

    def test_the_status_line_records_the_subscription_windows(self):
        import os, sys
        env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.tmp)}
        def feed(d):
            subprocess.run([sys.executable, "-m", "axon.statusline"], input=json.dumps(d), text=True, env=env, check=True,
                           cwd=Path(runtime.__file__).parent.parent)
        feed({"model": {}})  # no rate_limits (API key, or before the first answer): nothing written
        self.assertFalse((self.tmp / "axon-limits.json").exists())
        feed({"rate_limits": {"five_hour": {"used_percentage": 23.5, "resets_at": 1738425600},
                              "seven_day": {"used_percentage": 41.2, "resets_at": 1738857600}}})
        got = json.loads((self.tmp / "axon-limits.json").read_text())
        self.assertEqual([(w["window"], w["used"], w["resets_at"]) for w in got["windows"]],
                         [("5h", 23.5, 1738425600), ("week", 41.2, 1738857600)])

    def test_claude_opens_with_the_prompt_instead_of_dash_p(self):
        argv, _, _ = runtime.claude_cmd("p", ["mcp"], self.tmp, self.tmp, interactive=True)
        self.assertNotIn("-p", argv)
        self.assertEqual(argv[1], "p")
        self.assertIn("axon.statusline", argv[argv.index("--settings") + 1])
        argv, _, _ = runtime.claude_cmd("p", ["mcp"], self.tmp, self.tmp)
        self.assertEqual(argv[1:3], ["-p", "p"])

    def test_trusting_a_clone_keeps_claudes_other_settings_and_drops_gone_clones(self):
        home, gone = self.tmp / "h", runtime.data_dir() / "attempts" / "9-1" / "repo"
        home.mkdir()
        (home / ".claude.json").write_text('{"theme": "dark", "projects": {"%s": {"hasTrustDialogAccepted": true}, "/x": {}}}' % gone)
        runtime.trust_folder(home, self.tmp / "clone")
        d = __import__("json").loads((home / ".claude.json").read_text())
        self.assertEqual(d["theme"], "dark")
        self.assertEqual(sorted(d["projects"]), sorted(["/x", str(self.tmp / "clone")]))
        self.assertTrue(d["projects"][str(self.tmp / "clone")]["hasTrustDialogAccepted"])

if __name__ == "__main__":
    unittest.main()
