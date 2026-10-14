# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Axon runs several coding agents (Claude Code, Codex, a local LLM) as separate, sandboxed tasks on a user's git projects, with a local web GUI and a CLI. Linux only, single user, Python ≥ 3.11, **standard library only** (no runtime dependencies; keep it that way). The README and `docs/` are written in Thai.

## Commands

```bash
python3 -m pip install --user -e .          # installs `axon` (GUI + CLI) and `axon-cli`
python3 -m unittest discover -s tests -v    # whole suite (what CI runs)
python3 -m unittest tests.test_axon.<Class>.<test> -v   # one test
node --check axon/web/app.js && node tests/test-ui.cjs  # frontend syntax + UI contract test (CI)
python3 -m axon --sim --no-browser          # GUI on a fake in-memory runtime: no repos, no sandbox
python3 -m axon gui --no-browser            # the real runtime + runner (default state: ~/.local/state/axon)
axon doctor                                 # tries the real sandbox, agent logins and each project's checks
```

- Tests that need `bwrap` and a systemd *user* session skip themselves where those are missing (`sandbox_works()` in `tests/test_axon.py`). They are the ones that exercise the real sandbox; a green run on a machine without bwrap proves little about it.
- `tests/gui-smoke.cjs` / `gui-real-smoke.cjs` need Playwright + Chromium installed outside the repo (see `docs/GUI.md`); they are not in CI.
- Env overrides for isolation: `AXON_HOME` (data), `AXON_CONFIG` (config), `--state-dir` (GUI state). Config lives in `~/.config/axon/config.toml` and `projects/<name>.toml`; attempts, agent homes and the SQLite DB in `~/.local/share/axon`.
- There is no build step for the frontend: `axon/web/` is vanilla JS/CSS plus vendored xterm.js, served by `axon/server.py` with `Cache-Control: no-store` (edit, reload the page). Python changes need the server restarted.

## Architecture

Two runtimes sit behind one GUI contract (`snapshot(cursor)`, `task_detail(id)`, `command(payload)`):

- `axon/core.py` — **simulation only** (`--sim`): a UI contract fixture, never executes anything. Do not add real behaviour here.
- `axon/bridge.py` — adapts the real runtime to that same contract; GUI actions arrive as `command({"action": ...})` and are routed here. New GUI features usually need: an action in `bridge.py`, logic in `runtime.py`/`cli.py`, UI in `axon/web/app.js`.
- `axon/server.py` — authenticated loopback HTTP + WebSocket transport (token in URL fragment locally, password for the `tailscale serve` remote path). It binds `127.0.0.1` only.

Real runtime (`axon/runtime.py`, ~1200 lines, the centre of the project):

- State is SQLite (`store.py`): tasks, attempts, events, provider cooldowns. `Runtime.tick()` (called every 250 ms by the GUI worker thread, or `axon run`) picks QUEUED tasks with per-agent slots, per-project fairness, scope overlap (tasks with overlapping `scope` don't run together), `after` dependencies and cooldowns, and runs each attempt on its own thread.
- One attempt (`_attempt`): `git clone --shared` of the project into a per-attempt dir (never a worktree: shared hooks/config would let an agent run code in the user's checkout) → optional `prepare` step (network, needs approval if lockfiles changed) → agent CLI inside `bwrap` inside a `systemd-run --user --scope` → snapshot commit and `git bundle` produced *inside* the sandbox, then fetched outside into `refs/axon/attempts/<id>` → `_verify` runs the project's `[checks]` in a no-network sandbox → task state transitions. The agent's only channel back is the per-attempt Unix socket → `axon/mcp.py` (tools `report_result`, `ask_user`, `run_check`, `delegate`, `ask_peer`, and for Claude only `delete_file`/`move_file`, D-040); the socket is the attempt's identity, model-written text is never parsed as commands.
- Agents are adapters in `ADAPTERS` (`fake`, `codex`, `claude`, `local`), each returning `(argv, env, extra_ro)`. Claude is launched with default-deny `--tools` and **no Bash**; commands run only through `run_check`. Claude defaults to *interactive* mode (a real TUI in a tmux session `axon-chat-task<id>`, visible in the Chat tab; Axon types nothing into it except one fixed nudge when the session goes quiet without reporting, D-036) with `claude_mode = "headless"` (`claude -p`) as the alternative; Codex is headless only. Claude's quota bar comes from its own status line (`axon/statusline.py`).
- `integrate.py` merges finished tasks on `refs/axon/integration/<project>` via `git merge-tree` + `commit-tree` (no working tree), runs checks on that exact commit, and only `promote()` touches the user's checkout (refuses a dirty tree). `apply_result` / `axon apply` writes a result into the user's folder as uncommitted changes, all-or-nothing.
- `brainstorm.py` runs Claude+Codex planning (read-only `plan` tasks: ask the user → draft alone → compare → merge → check) from `Runtime.tick()`; state is in the `brainstorms` table, and only `create_tasks` (user-triggered) makes real tasks (D-035). `ask_peer` (D-034) lets one agent put a read-only question to the other mid-task.
- `local_agent.py` is a bounded tool loop against a loopback model; `helper.py` summarises logs with a local model (no tools). `usage.py`, `retention.py`, `agent_options.py` (model/effort per agent) are small support modules.

Sandbox (`axon/sandbox.py`): bwrap sees `/` read-only, with `$HOME`, `/tmp`, `/run` replaced by empty tmpfs (hides credentials and docker.sock); writable only for the attempt clone, the agent home and a project's `[sandbox] rw` folders. The agent CLI itself has network (it must reach its provider); commands it runs do not (Codex's own `workspace-write` sandbox nests inside; checks use `--unshare-net`). **Chat is deliberately not sandboxed** (D-022): `runtime.chat_start` runs the agent as the user in the real project folder, wrapped only in a systemd scope for a memory limit. The browser terminal is xterm.js over a WebSocket attached to `tmux attach` on a pty (`chat_attach`).

## Docs and decisions

`docs/DECISIONS.md` (D-nnn, confirmed) and `docs/OPEN_DECISIONS.md` (OD-nnn, with RESOLVED ones) record why things are the way they are; code comments cite them. `docs/EXECUTION_DESIGN.md` is the sandbox/git/network design with probe evidence (`probes/boundary.sh`, `probes/adapter.py` need real agent logins and some use quota). Parts of EXECUTION_DESIGN still describe `claude -p`; the interactive default in OPEN_DECISIONS supersedes it. When behaviour changes, update the decision docs and `README.md`/`docs/GUI.md` rather than leaving them stale.
