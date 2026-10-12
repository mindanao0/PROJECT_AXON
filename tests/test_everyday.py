"""The everyday flow: a project found from the current folder, `axon init`, results written into your folder."""

import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from axon import cli, runtime, sandbox
from test_axon import DONE, AxonTest, edit, step


class Everyday(AxonTest):
    def test_project_is_found_from_any_folder_inside_it(self):
        self.assertEqual(runtime.project_for(self.proj / "src"), "p")
        self.assertEqual(runtime.project_for(self.proj), "p")
        self.assertIsNone(runtime.project_for(self.tmp))
        with mock.patch("os.getcwd", return_value=str(self.proj / "src")), contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            cli.main(["add", "-a", "fake", "make b"])
        tid = int(out.getvalue())
        self.assertEqual(self.task(tid)["project"], "p")
        self.assertEqual(self.task(tid)["scope"], '["."]')
        self.assertIn("nothing is running tasks", err.getvalue())  # no GUI or `axon run` holds the runner lock
        with mock.patch("os.getcwd", return_value=str(self.tmp)), self.assertRaises(SystemExit) as stop:
            cli.main(["add", "-a", "fake", "x"])
        self.assertIn("axon init", str(stop.exception))

    def test_init_registers_the_repository_you_are_in(self):
        other = self.tmp / "My Repo"
        (other / "sub").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(other)], check=True)
        with mock.patch("os.getcwd", return_value=str(other / "sub")), contextlib.redirect_stdout(io.StringIO()):
            os.chdir(other / "sub")
            try:
                cli.main(["init"])
                with self.assertRaises(SystemExit):
                    cli.main(["init"])  # already a project
            finally:
                os.chdir(self.tmp)
        self.assertEqual(runtime.project_for(other / "sub"), "My-Repo")

    def test_apply_writes_the_result_into_your_folder_all_or_nothing(self):
        tid = self.add(edit("src/a.py", "a = 2\n") + edit("src/new.py", "n = 1\n") + DONE)
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "COMPLETED")
        (self.proj / "docs/b.md").write_text("my own unsaved work\n")
        self.assertEqual(sorted(runtime.apply_result(self.store, tid)), ["src/a.py", "src/new.py"])
        for f in ("src/a.py", "src/new.py"):
            self.assertEqual((self.proj / f).read_text(), self.shown(f"{tid}-1", f))
        self.assertEqual((self.proj / "docs/b.md").read_text(), "my own unsaved work\n")
        self.assertIn("src/a.py", self.git("status", "--porcelain"))  # uncommitted, for you to look at
        with self.assertRaisesRegex(ValueError, "already"):
            runtime.apply_result(self.store, tid)
        # Your own edit on the same line: nothing is written, not even the file that would apply.
        self.git("checkout", "--", "src/a.py")
        (self.proj / "src/new.py").unlink()
        (self.proj / "src/a.py").write_text("a = 'mine'\n")  # the same line the agent's change follows
        with self.assertRaisesRegex(ValueError, "nothing was written"):
            runtime.apply_result(self.store, tid)
        self.assertEqual((self.proj / "src/a.py").read_text(), "a = 'mine'\n")
        self.assertFalse((self.proj / "src/new.py").exists())

    def test_auto_apply_after_verification(self):
        cfg = self.tmp / "cfg" / "projects" / "p.toml"
        cfg.write_text("auto_apply = true\n" + cfg.read_text())
        tid = self.add(edit("src/a.py", "a = 3\n") + DONE)
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "COMPLETED")
        self.assertEqual((self.proj / "src/a.py").read_text(), self.shown(f"{tid}-1", "src/a.py"))
        self.assertTrue(self.store.one("select 1 from events where task = ? and kind = 'applied'", tid))

    def test_runner_lock_is_visible(self):
        self.assertFalse(runtime.runner_active())
        self.rt.start()
        try:
            self.assertTrue(runtime.runner_active())
        finally:
            self.rt.shutdown()
        self.assertFalse(runtime.runner_active())


class OutsideFoldersAndWeb(AxonTest):
    def rw(self, *paths):
        cfg = self.tmp / "cfg" / "projects" / "p.toml"
        cfg.write_text(cfg.read_text() + "[sandbox]\nrw = [" + ", ".join(f'"{x}"' for x in paths) + "]\n")

    def test_unsafe_folders_are_refused(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        self.assertEqual(runtime.outside_dir(str(outside), self.proj), str(outside.resolve()))
        for bad in ("~", "/", str(Path.home().parent), "~/.ssh", str(self.tmp / "home"), str(self.tmp),
                    str(self.proj), str(self.proj / "src"), str(self.tmp / "missing")):
            with self.assertRaises(ValueError, msg=bad):
                runtime.outside_dir(bad, self.proj)

    def test_agent_edits_a_listed_folder_outside_the_repository_live(self):
        outside, other = self.tmp / "outside", self.tmp / "other"
        outside.mkdir()
        other.mkdir()
        self.rw(outside)
        tid = self.add(step("shell", cmd=f"echo from-agent > {outside}/note.txt; echo x > {other}/no.txt") + DONE)
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "COMPLETED", self.task(tid)["note"])
        self.assertEqual((outside / "note.txt").read_text(), "from-agent\n")
        self.assertFalse((other / "no.txt").exists(), "a folder that is not listed stays read-only")
        prompt = (runtime.data_dir() / "attempts" / f"{tid}-1" / "prompt.txt").read_text()
        self.assertIn(f"outside the repository: {outside.resolve()}", prompt)

    def test_web_tools_and_add_dir_reach_the_agent_clis(self):
        io_dir = Path(tempfile.mkdtemp(dir=self.tmp))
        with mock.patch.object(runtime, "_which", return_value=Path("/usr/bin/true")):
            argv, _, _ = runtime.claude_cmd("p", ["mcp"], self.tmp, io_dir, web=True, dirs=["/d1"])
            self.assertIn("WebFetch", argv[argv.index("--tools") + 1])
            self.assertNotIn("WebFetch", argv[argv.index("--disallowedTools") + 1])
            self.assertEqual(argv[-2:], ["--add-dir", "/d1"])
            argv, _, _ = runtime.claude_cmd("p", ["mcp"], self.tmp, io_dir, web=False)
            self.assertIn("WebFetch", argv[argv.index("--disallowedTools") + 1])
            argv, _, _ = runtime.codex_cmd("p", ["mcp"], self.tmp, io_dir, web=True, dirs=["/d1"])
            self.assertEqual(argv[1:3], ["--search", "exec"])  # codex takes --search only before the subcommand
            self.assertEqual(argv[-3:], ["--add-dir", "/d1", "p"])
            self.assertNotIn("--search", runtime.codex_cmd("p", ["mcp"], self.tmp, io_dir, web=False)[0])
        self.assertTrue(runtime.load_config()["agents"]["web"], "web research is on unless [agents] web = false")


@unittest.skipUnless(shutil.which("tmux"), "needs tmux")
class ShellChat(AxonTest):
    def test_shell_runs_in_the_project_folder_itself(self):
        sock = self.enterContext(tempfile.TemporaryDirectory(dir="/tmp"))
        self.enterContext(mock.patch.dict(os.environ, {"TMUX_TMPDIR": sock}))
        os.environ.pop("TMUX", None)
        self.addCleanup(subprocess.run, ["tmux", "kill-server"], capture_output=True)
        name = runtime.chat_start("p", "shell")
        self.addCleanup(runtime.chat_close, name)
        subprocess.run(["tmux", "send-keys", "-t", name, "-l",
                        f"pwd; touch x; echo HOME-$HOME; echo END-$((1+1))\n"], check=True)
        for _ in range(50):
            screen = subprocess.run(["tmux", "capture-pane", "-p", "-t", name], capture_output=True, text=True).stdout
            if "END-2" in screen:
                break
            time.sleep(0.1)
        self.assertIn(f"\n{self.proj}\n", screen)
        self.assertIn(f"HOME-{Path.home()}", screen, "your own home, not an empty one")
        self.assertTrue((self.proj / "x").exists(), "no clone in between: the shell edits your checkout")

    def test_a_command_over_the_memory_limit_does_not_end_the_chat(self):
        sock = self.enterContext(tempfile.TemporaryDirectory(dir="/tmp"))
        self.enterContext(mock.patch.dict(os.environ, {"TMUX_TMPDIR": sock}))
        os.environ.pop("TMUX", None)
        self.addCleanup(subprocess.run, ["tmux", "kill-server"], capture_output=True)
        (self.tmp / "cfg" / "config.toml").write_text("[limits]\nchat_memory = \"100M\"\n")
        name = runtime.chat_start("p", "shell")
        self.addCleanup(runtime.chat_close, name)
        subprocess.run(["tmux", "send-keys", "-t", name, "-l",
                        "python3 -c 'x = b\"x\" * (1500 * 2**20)'; echo AFTER-$((1+1))\n"], check=True)
        for _ in range(100):
            screen = subprocess.run(["tmux", "capture-pane", "-p", "-t", name], capture_output=True, text=True).stdout
            if "AFTER-2" in screen:
                break
            time.sleep(0.1)
        self.assertIn("AFTER-2", screen, "the hog was killed but the shell, and so the chat, lives on")
        self.assertIn(name, runtime.chat_sessions())


if __name__ == "__main__":
    unittest.main()
