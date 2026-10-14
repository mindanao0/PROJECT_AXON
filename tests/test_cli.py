import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from axon.__main__ import private_dir


class CLITests(unittest.TestCase):
    def test_private_state_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertEqual(private_dir(root), root)
            root.chmod(0o755)
            with self.assertRaises(SystemExit):
                private_dir(root)
            root.chmod(0o700)
            link = root / 'link'
            link.symlink_to(root, target_is_directory=True)
            with self.assertRaises(SystemExit):
                private_dir(link)

    def test_single_instance_and_launch_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            args = [sys.executable, '-m', 'axon', '--sim', '--no-browser', '--state-dir', folder]
            proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                launch = Path(folder) / 'launch.url'
                deadline = time.monotonic() + 30
                while not launch.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(launch.exists())
                self.assertEqual(launch.stat().st_mode & 0o777, 0o600)
                # A second `axon` opens the running one instead of failing.
                other = subprocess.run(args, capture_output=True, text=True, timeout=30)
                self.assertEqual(other.returncode, 0)
                self.assertIn('already running: ' + launch.read_text().strip(), other.stderr)
            finally:
                proc.send_signal(2)
                proc.communicate(timeout=30)
            self.assertFalse(launch.exists())
            self.assertTrue((Path(folder) / 'control.sqlite3').exists())


if __name__ == '__main__':
    unittest.main()
