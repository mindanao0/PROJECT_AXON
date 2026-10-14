"""Scripted stand-in for an agent CLI (docs/EXECUTION_DESIGN.md §6).

Reads a TOML scenario from the prompt, after the '--- task ---' line:

    [[step]]
    do = "edit"          # edit, prompt, mcp, shell, sleep, read_line, hang, orphan, rate_limit, crash, garbage
    path = "src/x.py"
    attempt = 1          # optional: only run this step on that attempt number
    phase = "draft"      # optional, brainstorm tasks: only in that phase (clarify, draft, compare, merge, check)
    role = "lead"        # optional, brainstorm tasks: only for the lead or the other agent
    has = "text"         # optional: only when Axon's part of the prompt contains it (lacks: only when it does not)
"""

import json
import os
import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path

from .mcpclient import Mcp


def emit(**event):
    print(json.dumps(event), flush=True)


def main(prompt):
    scenario = tomllib.loads(prompt.split("--- task ---\n", 1)[1])
    n = int(os.environ.get("AXON_ATTEMPT", "1"))
    mcp = None
    head, tail = prompt.split("--- task ---\n", 1)
    asked = head.replace(tail.split("\n", 1)[-1], "")  # what Axon wrote: the scenario (also quoted as the goal) must not match its own filters
    here = {k: m.group(1) for k in ("phase", "role") if (m := re.search(rf"^Brainstorm {k}: (\w+)$", asked, re.M))}
    emit(type="start", attempt=n)
    for step in scenario.get("step", []):
        if (step.get("attempt", n) != n or any(step.get(k, v) != v for k, v in here.items())
                or step.get("has", asked) not in asked or ("lacks" in step and step["lacks"] in asked)):
            continue
        do = step["do"]
        if do in ("edit", "prompt"):
            p = Path(step["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a") as f:
                f.write(prompt if do == "prompt" else step.get("text", "x\n"))
        elif do == "mcp":
            mcp = mcp or Mcp(json.loads(os.environ["AXON_MCP"]))
            emit(type="tool", tool=step["tool"], result=mcp.call(step["tool"], step.get("args", {})))
        elif do == "shell":
            r = subprocess.run(step["cmd"], shell=True, capture_output=True, text=True)
            emit(type="shell", rc=r.returncode, out=r.stdout + r.stderr)
        elif do == "sleep":
            time.sleep(step.get("s", 1))
        elif do == "read_line":  # wait for one line typed into the session (a nudge)
            emit(type="input", line=sys.stdin.readline().strip())
        elif do == "hang":
            time.sleep(10**6)
        elif do == "orphan":
            # Escapes the agent's session; only the cgroup/pid namespace can still reach it.
            subprocess.Popen(["setsid", "sh", "-c",
                              f"while :; do date +%s%N >> '{step['path']}'; sleep 0.1; done"])
        elif do == "rate_limit":
            print("Error: rate limit reached, try again later", flush=True)
            sys.exit(1)
        elif do == "crash":
            sys.exit(step.get("code", 1))
        elif do == "garbage":
            print("{not json", flush=True)
    emit(type="end")


if __name__ == "__main__":
    main(sys.argv[1])
