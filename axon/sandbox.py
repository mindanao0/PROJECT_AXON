"""bwrap / systemd scope wrappers and git helpers (docs/EXECUTION_DESIGN.md §2-§4, §7)."""

import glob
import os
import subprocess
import sys
from pathlib import Path

HOME = str(Path.home())
PKG = Path(__file__).resolve().parent
PY = os.path.realpath(sys.executable)
# The interpreter and axon itself must stay visible once $HOME is hidden.
BASE_RO = [str(PKG)] + [p for p in {sys.base_prefix, sys.prefix} if p.startswith(HOME + "/")]
# e.g. Fedora: /etc/resolv.conf -> /run/systemd/resolve/stub-resolv.conf, hidden with /run
RESOLV = os.path.realpath("/etc/resolv.conf")
GIT = ["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=axon",
       "-c", "user.email=axon@localhost"]


def bwrap(cwd, rw=(), ro=(), net=True, env=None):
    """argv prefix for a sandbox that sees / read-only, but not $HOME, /tmp or /run.
    /run must be hidden: a read-only mount does not stop connect() to docker.sock.
    GPU device nodes come along (CUDA, Blender renders); --dev /dev alone has none."""
    a = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
         "--tmpfs", "/tmp", "--tmpfs", "/run", "--tmpfs", HOME]
    for p in [*glob.glob("/dev/nvidia*"), *glob.glob("/dev/dri"), *glob.glob("/dev/kfd")]:
        a += ["--dev-bind", p, p]
    for p in [*BASE_RO, *ro]:
        if os.path.exists(p):
            a += ["--ro-bind", str(p), str(p)]
    for p in rw:  # a path, or (source, where the sandbox sees it)
        src, dst = p if isinstance(p, tuple) else (p, p)
        a += ["--bind", str(src), str(dst)]
    if net and RESOLV.startswith("/run/"):
        a += ["--ro-bind", RESOLV, RESOLV]  # only the file: DNS works, other /run sockets stay hidden
    if not net:
        a.append("--unshare-net")
    a += ["--unshare-pid", "--die-with-parent", "--chdir", str(cwd), "--clearenv"]
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": HOME, "LANG": "C.UTF-8",
           "TERM": "dumb", "PYTHONPATH": str(PKG.parent), **(env or {})}
    for k, v in env.items():
        a += ["--setenv", k, str(v)]
    return a + ["--"]


def scope(unit, memory, argv, survive_oom=False):
    """Run argv in its own cgroup: memory limit (swap included: without MemorySwapMax=0 a 1.5 GB
    allocation survives a 100M MemoryMax by swapping), and `stop` kills the whole tree.
    survive_oom: the kernel kills only the process over the limit; by default systemd stops the whole scope."""
    return ["systemd-run", "--user", "--scope", "--quiet", "--collect", f"--unit={unit}",
            "-p", f"MemoryMax={memory}", "-p", "MemorySwapMax=0", "-p", "TimeoutStopSec=10",
            *(["-p", "OOMPolicy=continue"] if survive_oom else []), "--", *argv]


def stop_unit(unit):
    subprocess.run(["systemctl", "--user", "stop", f"{unit}.scope"], capture_output=True)


def active(unit):
    return subprocess.run(["systemctl", "--user", "is-active", "--quiet", f"{unit}.scope"]).returncode == 0


def clone(project, repo, base, branch):
    """Per-attempt clone sharing the project's objects; never a worktree (shared hooks).
    No global git config, like inside the sandbox: user filters (e.g. git-lfs smudge) would
    otherwise make untouched files look modified to the sandboxed snapshot."""
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null"}
    subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", project, str(repo)], check=True, env=env)
    subprocess.run([*GIT, "-C", str(repo), "checkout", "-q", "-b", branch, base], check=True, env=env)


def fetch(project, bundle, ref):
    subprocess.run(["git", "-C", project, "-c", "fetch.fsckObjects=true", "fetch", "-q",
                    str(bundle), f"+HEAD:{ref}"], check=True)


def changed_files(project, a, b):
    r = subprocess.run(["git", "-C", project, "diff", "--name-only", "-z", "--no-ext-diff", a, b],
                       capture_output=True, text=True, check=True)
    return [f for f in r.stdout.split("\0") if f]


def removed_files(project, a, b):
    """Files that exist in a and not in b (a moved file counts under its old name)."""
    r = subprocess.run(["git", "-C", project, "diff", "--name-only", "--diff-filter=D", "--no-renames", "-z", "--no-ext-diff", a, b],
                       capture_output=True, text=True, check=True)
    return [f for f in r.stdout.split("\0") if f]


def inputs_changed(project, a, b, paths):
    return subprocess.run(["git", "-C", project, "diff", "--quiet", a, b, "--", *paths]).returncode != 0
