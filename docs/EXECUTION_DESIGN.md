# Execution Design — แก้จุดบอดหลัก

> ข้อเสนอระดับที่ implement ได้ ส่วนที่ระบุว่า **verified** ทดสอบแล้วบนเครื่อง dev (Fedora, kernel 7.2, bubblewrap 0.12, systemd user cgroup v2, codex-cli 0.160.1) วันที่ 2026-10-06 ด้วย [`probes/boundary.sh`](../probes/boundary.sh) ซึ่งไม่ใช้ quota ส่วนที่ต้องใช้ quota จริงอยู่ใน §10

## 0. ภาพรวมหนึ่ง attempt

```text
Runtime (สิทธิ์ผู้ใช้, อยู่นอก sandbox)
 └─ systemd-run --user --scope  axon-<attempt>.scope   ← จำกัด RAM/CPU/PIDs; Kill = stop ทั้ง cgroup
     └─ bwrap (attempt sandbox)                        ← เห็นเฉพาะ clone ของ attempt + agent home
         └─ agent CLI: codex exec / claude -p          ← ออกเน็ตไป provider ได้
             ├─ MCP stdio: axon mcp ──Unix socket ของ attempt──▶ Runtime
             └─ คำสั่งที่ agent รัน
                  Codex : sandbox ของ Codex (workspace-write) — ไม่มีเน็ต เขียนได้เฉพาะ workspace
                  Claude: ไม่มี Bash — รันได้เฉพาะ run_check ผ่าน MCP
                          └─ Runtime รัน check ใน bwrap --unshare-net
```

## 1. ช่องทาง agent → Runtime (MCP)

Runtime เป็น MCP stdio server ต่อ attempt; ไม่ parse ข้อความอิสระของ model เป็นคำสั่ง

- Claude: `claude -p --output-format stream-json --mcp-config <attempt>/mcp.json --strict-mcp-config`
- Codex: `codex exec --json -c 'mcp_servers.axon.command="axon"' -c 'mcp_servers.axon.args=["mcp"]'`
- Config ทุกไฟล์อยู่ใน state dir ของ Runtime ไม่เขียนลง repo ของ project

Tools Phase 1 แทน message types 14 แบบ:

| Tool | ผล |
| --- | --- |
| `report_result(status, summary)` | status = done / blocked / failed; Runtime ทำ snapshot commit เองแล้วส่งเข้า VERIFY |
| `ask_user(question)` | task → WAITING_INPUT ถามหลายข้อพร้อมกันได้: `questions=[{question, options}]` แต่ละข้อมีตัวเลือกของตัวเอง (GUI ให้คลิกเติมช่อง พิมพ์เองได้ ส่งทีเดียว; `axon answer` ถามทีละข้อ) คำตอบกลับไปเป็นรายการเลขข้อ `1) …\n2) …` |
| `run_check(name)` | รันเฉพาะ check ที่ตั้งไว้ใน project config (§9) คืน exit code กับท้าย output; output เต็มเก็บเป็น artifact |
| `delegate(title, spec, scope)` | (Phase 2) queue งานต่อที่เริ่มหลัง attempt นี้จบจากผลของมัน: scope ต้องอยู่ใน scope ตัวเอง, ลึก 1 ชั้น, ไม่เกิน `max_delegations`; review task ใช้ไม่ได้ |
| `ask_peer(question)` | (D-034) ถาม agent อีกตัว (Claude ↔ Codex) แล้วรอคำตอบ: Runtime สร้าง task `ask` read-only บน commit ที่ attempt นี้เริ่ม (ไม่เห็นงานที่ยังไม่ snapshot จึงต้องใส่โค้ดในคำถาม) ผู้ตอบ `report_result` คำตอบกลับมาเป็นผลของ tool; ไม่เกิน `max_asks`, รอไม่เกิน `ask_timeout`; task `ask`/`review` ถามต่อไม่ได้; task `ask` ไม่ claim scope, ไม่ใช่ผลที่ review/integrate/apply ได้; Codex ตั้ง `tool_timeout_sec` ให้เกินเวลารอ (ค่าเริ่มต้นของ Codex คือ 60 วินาที) |

Phase 2 เพิ่ม `delegate(title, spec, scope)` ส่วนการขอ review เป็นคำสั่งของผู้ใช้/policy ไม่ใช่ tool ของ agent (implementer ไม่เลือก reviewer ของตัวเอง) message types อื่นเป็น event type ใน log ไม่ใช่สิ่งที่ agent ต้องรู้

**Brainstorm (D-035):** task ชนิด `plan` ใช้ tool ชุดเดียวกัน (`report_result`, `ask_user`) แบบอ่านอย่างเดียวเหมือน `review`/`ask` (ไม่ claim scope, ตรวจว่าไม่มีไฟล์เปลี่ยน, delegate/`ask_peer` ไม่ได้) `axon/brainstorm.py` เลื่อนขั้นจาก `Runtime.tick()` ตามสถานะใน SQLite (ตาราง `brainstorms`) จึงเดินต่อได้หลัง runner รีสตาร์ต ขั้น: `clarify` (ทั้งสองฝั่งถามผู้ใช้ จนรอบหนึ่งไม่มีคำถามใหม่ ไม่เกิน 10 รอบ; ถ้าทั้งคู่ถามพร้อมกัน คำถามผ่านขั้น `gate` รวมเป็นฟอร์มเดียวก่อนถึงผู้ใช้ D-038) → `draft` (แยกกัน ไม่เห็นกัน) → `compare` → `merge` (lead, JSON ตาม schema ใน `brainstorm.py`: `unknowns` ต้องว่าง และทุกงานต้องมี `objective`, `steps`, `acceptance`; D-037) → `check` → READY ผู้ใช้เท่านั้นที่ทำให้เกิด task จริง (`create_tasks` ผ่าน `add_task` เดิม) แผน JSON เป็นข้อมูลให้ผู้ใช้ดูก่อน ไม่มีอะไรรันเองจากข้อความของโมเดล task ที่สร้างได้ `spec` เป็น brief Markdown ที่ Axon ประกอบจากฟิลด์ (`brainstorm.brief`) ซึ่งคือข้อความเดียวกับที่หน้าจอให้ผู้ใช้เห็นก่อนอนุมัติ

- Identity: Runtime สร้าง Unix socket แยกต่อ attempt และ bind เข้า sandbox ของ attempt นั้นเท่านั้น สิ่งที่ต่อเข้ามาทาง socket นี้คือ attempt นั้น ไม่เชื่อชื่อที่ model เขียน
- Attempt จบหรือถูก reassign → ปิด socket; late result ส่งเข้ามาไม่ได้
- Process จบโดยไม่เรียก `report_result` → result = `unreported`; ข้อความสุดท้ายใน stream เป็นหมายเหตุเท่านั้น ไม่นับว่าเสร็จ

## 2. Network

| ผู้ใช้เน็ต | เน็ต | วิธีบังคับ | สถานะ |
| --- | --- | --- | --- |
| process ของ agent CLI | ออกได้ เพราะต้องคุยกับ provider | ไม่จำกัดใน MVP (limitation ที่ยอมรับ) | — |
| คำสั่งของ Codex | ไม่มี | Codex sandbox `workspace-write` | verified ผ่าน `codex sandbox -P :workspace`; เส้นทาง `codex exec` รอ §10 |
| คำสั่งของ Claude | ไม่มี | ปิด Bash และ subagent tool; รันได้เฉพาะ `run_check` | รอ §10 |
| ค้นเว็บ/อ่านหน้าเว็บของ agent | มี (ปิดได้) | `[agents] web = true` (ค่าเริ่มต้น): Claude ได้ WebSearch/WebFetch, Codex ได้ `--search`; `web = false` = ปิดทั้งคู่ | — |
| `run_check` / verifier | ไม่มี | bwrap `--unshare-net` | verified |
| `prepare` (ติดตั้ง dependency) | มี | step แยก; auto-allow เฉพาะเมื่อ lockfile ไม่เปลี่ยนจาก base นอกนั้น WAITING_APPROVAL | — |

- Claude ใช้ `--permission-mode acceptEdits`, `--allowedTools` เฉพาะ Read/Edit/Write/Glob/Grep และ `mcp__axon`, ส่วน tool อื่น disallow; ตรวจรายการ tool จริงจาก init event ของ stream
- Check ใช้ dependency ที่ `prepare` ติดตั้งไว้แบบ offline (VELA: `uv run --offline --frozen`); uv cache bind แบบ rw เฉพาะตอน `prepare`
- Web research: เปิดตามคำขอผู้ใช้ (2026-10-07) ผ่าน tool ค้น/อ่านเว็บของ CLI เท่านั้น; คำสั่งของ agent และ checks ยังไม่มีเน็ต ความเสี่ยงที่ยอมรับ: หน้าเว็บอาจมีคำสั่งแฝง (prompt injection) และ agent อาจส่งโค้ดออกผ่าน URL ได้ ปิดด้วย `[agents] web = false`
- Folder นอก repo: `[sandbox] rw = [...]` ในไฟล์ project bind แบบเขียนได้ให้ attempt และ chat (+`--add-dir` ให้ CLI) แก้แบบสดโดยไม่ผ่าน diff/review/apply และ Axon ย้อนให้ไม่ได้; ปฏิเสธ home หรือสูงกว่า, state ของ Axon, ตัว repo เอง และ folder credential (`.ssh`, `.gnupg`, `.aws`, …); review task ไม่ได้สิทธิ์นี้

## 3. Credentials

- Agent home แยกจาก home ผู้ใช้: `CODEX_HOME=<state>/agents/codex`, `CLAUDE_CONFIG_DIR=<state>/agents/claude`; login ครั้งเดียวต่อ dir
- Sandbox ใช้ tmpfs ทับ `$HOME` แล้ว bind เฉพาะ agent home ของตัวเอง: `~/.ssh`, history/plugins/hooks ส่วนตัว, project อื่น และ credential ของ agent อีกเจ้ามองไม่เห็น (verified)
- `bwrap --clearenv` แล้วส่งเฉพาะ PATH, LANG, HOME, TERM และตัวแปร agent home; ไม่ inject secret ของ project
- Limitation (verified): คำสั่งใน Codex sandbox อ่าน `auth.json` ของตัวเองได้ และ Read tool ของ Claude อ่าน credential ของตัวเองได้ ลดความเสี่ยงโดย
  1. คำสั่งไม่มีเน็ต (§2)
  2. Runtime อ่านค่า token ของทุก agent แล้ว scan แบบ exact match ในทุก diff/artifact/message ที่ออกจาก attempt ก่อนส่งให้ agent อื่น, local LLM หรือ log; เจอ → block และ escalate

## 4. Git: clone ต่อ attempt แทน worktree

Worktree แชร์ `.git/config` และ `.git/hooks` กับ checkout หลัก agent ที่เขียน hook ได้จะรันโค้ดใน checkout ของผู้ใช้ จึงไม่ใช้ worktree กับ agent

1. `git clone --shared <project> <state>/attempts/<id>/repo` แล้ว checkout branch `axon/<task>/<attempt>` จาก base commit — objects แชร์ผ่าน alternates ไม่ copy
2. Sandbox: repo หลัก ro-bind (alternates ต้องอ่าน), clone rw; เขียน hooks/objects ของ repo หลัก → read-only (verified)
3. Snapshot: `git -c core.hooksPath=/dev/null commit` รัน **ใน sandbox เดียวกัน** เพราะ config/hooks ของ clone เป็น untrusted (verified)
4. ส่งผลออก: `git bundle create out.bundle <base>..HEAD` ใน sandbox แล้ว Runtime ข้างนอก `git fetch out.bundle HEAD:refs/axon/attempts/<id>`; ไม่รัน git ใน clone จากนอก sandbox (verified)
5. Merge เข้า branch ของผู้ใช้เป็นของผู้ใช้ (OD-008)
6. ลบ clone หลัง fetch ผลแล้วตาม retention

VELA: checkout ไฟล์ที่ track ประมาณ 482 MB ต่อ clone; `.git` 371 MB แชร์ไม่ copy; env ของ prototypes ที่ไม่ได้ track ไม่ถูก copy — `prepare` สร้าง `.venv` ต่อ clone จาก uv cache

## 5. Quota (subscription)

- Slot: codex 1, claude 1 session พร้อมกัน
- Rate limit ที่ตรวจจาก exit/stream error → provider เข้า COOLDOWN จนถึงเวลา reset ถ้า CLI บอก ไม่บอกใช้ backoff 15 → 30 → 60 นาที; task → WAITING_QUOTA ไม่นับ retry
- หลัง cooldown: resume session ถ้า backend รองรับ ไม่งั้นสร้าง attempt ใหม่จาก snapshot ล่าสุด
- ประหยัด: Solo เป็น default; Claude review เฉพาะ task ที่ `review = true` หรือ diff แตะ `protected` paths; local LLM สรุป log ยาวก่อนส่ง cloud (D-004)
- บันทึกต่อ provider: turns, wall time, attempts, cooldowns (token count ไม่น่าเชื่อถือ — OD-012)

## 6. Fake agent สำหรับทดสอบ Runtime

`fake-agent` เป็น CLI ที่ adapter เรียกแบบเดียวกับของจริง อ่าน scenario TOML ทีละ step:
`edit`, `mcp` (เรียก tool), `sleep`, `crash` (exit code), `hang`, `orphan` (setsid child เขียนไฟล์ทุกวินาที), `rate_limit` (error text เดียวกับของจริง), `garbage` (stream line เสีย)

- Scenario ใน [MVP Contract §8](MVP_CONTRACT.md#8-acceptance-scenarios) รันกับ fake ก่อน: deterministic, ไม่ใช้ quota
- CLI จริงรัน contract probes สั้น ๆ (§10) เมื่อเปลี่ยนเวอร์ชันเท่านั้น; ปิด auto-update ใน agent home และบันทึกเวอร์ชันใน attempt

## 7. Host sockets / Docker

Verified: ผู้ใช้อยู่ในกลุ่ม `docker`; sandbox ที่มีแค่ `--ro-bind / /` ยังเรียก docker API ได้ (HTTP 200) ซึ่งเท่ากับสิทธิ์ root เพราะ read-only mount ไม่กัน `connect()` ไป Unix socket

- ทุก sandbox ใช้ `--tmpfs /run` ซึ่งครอบ `/var/run/docker.sock` และ `/run/user/<uid>/bus` (verified)
- Bind เข้าจาก `/run` ได้เฉพาะ socket ของ attempt ตัวเอง; control socket ของ Runtime/UI อยู่ใน `$XDG_RUNTIME_DIR` ซึ่ง sandbox มองไม่เห็น — agent อนุมัติงานตัวเองผ่าน UI ไม่ได้
- Codex sandbox ชั้นในกัน docker socket ได้เองด้วย แต่ไม่พึ่งชั้นเดียว
- Test ที่ต้องใช้ container ไม่อยู่ใน MVP (test ของ VELA ไม่ใช้); ถ้าต้องใช้ภายหลังให้ Runtime รัน `podman run --network=none` เป็น check โดย agent ไม่ได้ socket

## 8. แบ่งงาน ไม่ทับ ไม่ทำซ้ำ แบ่งทรัพยากร (D-008)

- **ไม่ทับ:** task ประกาศ `scope` (path prefixes); scheduler ไม่รันสอง task ที่ scope ทับกันพร้อมกัน; diff ออกนอก scope → ไม่ผ่าน VERIFY จนผู้ใช้อนุมัติ
- **ไม่ทำซ้ำ:** task key = hash(spec ที่ normalize แล้ว + scope); ถ้ามี key เดียวกันที่ QUEUED/RUNNING/COMPLETED → ไม่สร้างใหม่ แสดงอันเดิม; context baseline ใส่รายการ task ที่ COMPLETED ใน scope เดียวกันหลัง base commit
- **ทรัพยากร:** slot ต่อประเภท + cgroup ต่อ attempt (verified: MemoryMax และ Kill ทั้ง tree รวม process ที่ setsid หนี) ค่าเริ่มต้นสำหรับ RAM 15 GB / GTX 1660 Ti 6 GB: agent 3G, check 4G, local LLM 1 slot (`OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`); ปรับได้ใน config
- จับงานซ้ำแบบ similarity (embedding) ยังไม่ทำ จนกว่าจะเจองานซ้ำที่ hash จับไม่ได้จริง

## 9. Project config (ตัวอย่าง)

อยู่นอก repo ที่ `~/.config/axon/projects/vela.toml` — ไม่เพิ่มไฟล์ใน repo ของ project (ตัวอย่างนี้ project ห้ามไฟล์ `.json`)

```toml
path = "~/code/PROJECT_VELA"
protected = ["tests/contract/", "Implementation_Governance/", "pyproject.toml", "uv.lock"]   # + .claude/ .codex/ .mcp.json เสมอ (OD-013)
require_review = true   # integrate ต้องมี review ที่ approve commit ผลของ task นั้นพอดี (ไม่ใส่ = ไม่บังคับ)

[prepare]   # มีเน็ต; auto-allow เมื่อ pyproject.toml/uv.lock ไม่เปลี่ยนจาก base
sync = "uv sync --frozen --extra dev"

[checks]    # ไม่มีเน็ต; run_check และ verifier ใช้ชุดเดียวกัน
unit  = "uv run --offline --frozen pytest -q tests"
lint  = "uv run --offline --frozen ruff check src tests"
types = "uv run --offline --frozen mypy"

[slots]
codex = 1
claude = 1
local_llm = 1
checks = 1
```

## 10. Probes ที่ต้องใช้ quota (Phase 1b)

รันหลัง Runtime ผ่าน acceptance scenarios กับ `fake-agent` แล้ว (D-013)

1. `codex exec --json --sandbox workspace-write` ใน attempt sandbox พร้อมเรียก MCP tool
2. `claude -p` ด้วย `CLAUDE_CONFIG_DIR` ใน attempt sandbox: login, รายการ tool ใน init event, เรียก MCP tool, ยืนยันว่าไม่มี Bash
3. Error text/exit code ตอนโดน rate limit — เก็บเมื่อเกิดขึ้นจริง ไม่เผา quota เพื่อทดสอบ
4. Resume session หลัง Kill
