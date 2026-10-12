# Open Decisions

เอกสารนี้เก็บสิ่งที่ **ยังไม่ได้ตัดสินใจ** และสถานะคำตัดสินที่เกี่ยวข้อง รายการที่ยืนยันแล้วอ้าง [Confirmed Decisions](DECISIONS.md); ข้อเสนอ acceptance อยู่ใน [MVP Contract](MVP_CONTRACT.md)

สถานะ (2026-10-08): ไม่มี OD ที่เปิดอยู่ (OD-019 ปิดแล้ว เหลือข้อเทาของ `claude -p`); นโยบายตัดสินแล้วแต่ enforcement ยังค้าง: OD-013 และช่องว่างที่รู้แล้วใน OD-023 และ OD-015 ข้ออื่นตัดสินแล้ว (D-015–D-032) บางข้อเป็นคำตัดสินว่า "ยังไม่สร้าง" พร้อมเงื่อนไขที่จะกลับมาดูใหม่

## OD-001 Core implementation language — RESOLVED

D-012: Python ≥ 3.11 ใช้ stdlib ก่อน

## OD-002 UI technology — RESOLVED

D-015: Browser UI ที่ Axon serve เอง (`axon/web`: HTML/CSS/JS ไม่มี framework หรือ build step, xterm.js สำหรับหน้า Chat) เปิดด้วย `python3 -m axon`
ไม่ทำ desktop wrapper (Tauri/Electron/Flutter) จนกว่าจะมีความต้องการที่ browser ทำไม่ได้ เช่น tray icon หรือ notification ของระบบ (Phase 5 ยังไม่พบ use case)

**แก้ 2026-10-08 (D-033):** ผู้ใช้ต้องการแอปมือถือ native จริง (ไม่ใช่เว็บ/PWA/WebView) → ทำ Flutter แอปแยกใน `mobile/` ต่อ API เดิม; browser UI ยังอยู่ ดู [MOBILE.md](MOBILE.md)

## OD-003 Runtime transport — RESOLVED

D-016:
- UI ↔ daemon: HTTP บน `127.0.0.1` (stdlib `ThreadingHTTPServer`, `axon/server.py`); หน้าจอ poll state ทุก 1.5 วินาที; WebSocket ใช้เฉพาะ terminal ของ Chat (`/api/chat/ws`)
- ยืนยันตัวตน: launch link token → session cookie และตรวจ Host/Origin (กัน DNS rebinding/CSRF); เข้าจากเครื่องอื่นได้เฉพาะผ่าน proxy บนเครื่องเดียวกันพร้อมรหัสผ่าน (OD-015)
- Agent ↔ Runtime: Unix socket ต่อ attempt (`io/axon.sock` mount แบบ read-only ใน sandbox) ผ่าน MCP server `axon/mcp.py`

เปลี่ยนเป็น SSE เมื่อ polling ทำให้ช้าหรือเปลืองจนวัดได้ ไม่ต้องตัดสินล่วงหน้า

## OD-004 Internal message persistence — RESOLVED

D-017: SQLite (stdlib `sqlite3`, WAL) เป็น state หลัก: ตาราง `tasks`, `attempts`, `events`, `meta`, `cooldowns` (`axon/store.py`); การเปลี่ยนสถานะเป็น compare-and-set และบันทึก event ทุกครั้ง (`Store.move`)
ข้อมูลใหญ่ของ attempt (log ของ agent, prompt, bundle) เป็นไฟล์ใน `~/.local/share/axon/attempts/<id>/` และลบตาม retention (`axon-cli gc`)

## OD-005 Protocol compatibility — RESOLVED

D-027: native schema (tasks/attempts/events ใน SQLite และ MCP tools ของ Axon สำหรับ agent) ไม่ใช้ A2A-compatible schema ตั้งแต่แรก
ทำ A2A bridge เมื่อต้องต่อ agent ที่ไม่ได้รันผ่าน CLI บนเครื่องนี้เท่านั้น ก่อนทำต้องเพิ่ม schema_version / correlation id / producer sequence ใน event (ช่องว่างข้อ 3 ของ OD-023)
เหตุผล: lifecycle กับ Codex/Claude/Local พิสูจน์แล้ว (Phase 1b–4) และยังไม่มี external agent ให้ต่อ (Phase 5 ไม่พบ use case)

## OD-006 Agent backend integration — RESOLVED

D-018: ใช้โหมด noninteractive แบบมีโครงสร้างของ CLI ทางการ ไม่ใช้ PTY หรือ app-server: Codex `codex exec --json`, Claude `claude -p --output-format stream-json`; agent ส่งผลกลับผ่าน MCP tools ของ Axon (`report_result`, `ask_user`, `delegate`, `run_check`) และ Runtime ตัดสินจาก tool call กับ exit code โดยไม่ parse stream

ผล probe ราย capability (codex-cli 0.160.1, claude 2.1.291, 2026-10-06) อยู่ใน [MVP Contract](MVP_CONTRACT.md) §2 และ [Roadmap](ROADMAP.md) Phase 1b สรุปได้ดังนี้:
- ส่งข้อความระหว่างรันไม่ได้ทั้งสองตัว คำสั่งใหม่จึงใช้ attempt ใหม่
- interrupt คือฆ่า process tree ทั้ง cgroup
- Runner ไม่พึ่ง resume ของ provider แต่ต่อจาก git snapshot
- ยังไม่ได้ทดสอบ: ข้อความ rate limit จริง

รัน `probes/adapter.py` ซ้ำเมื่ออัปเกรด CLI

## OD-007 Worktree strategy — RESOLVED

D-019: clone ต่อ attempt ด้วย `git clone --shared --no-checkout` แล้ว checkout branch `axon/<task>/<n>` จาก base (`sandbox.clone`) ไม่ใช้ worktree เพราะ worktree แชร์ `.git/config` และ `.git/hooks` กับ checkout หลัก ผลกลับเข้า repo หลักเป็น bundle ที่ `refs/axon/attempts/<id>` และลบ clone เมื่อ attempt จบ; ผล probe อยู่ใน [Execution Design](EXECUTION_DESIGN.md) §4
ยังต้องวัด overhead กับ project จริงขนาดใหญ่ (ที่วัดแล้วคือ VELA) (checkout ประมาณ 482 MB ต่อ clone) ซึ่งเป็นงานวัดผล ไม่ใช่คำตัดสินที่ค้าง

## OD-008 Who can merge — RESOLVED

D-014: ผู้ใช้เป็นผู้สั่ง; Runtime รวมงานบน integration branch ของ Axon (`refs/axon/integration/<project>`) แล้วรัน check ซ้ำบน commit สุดท้าย ผู้ใช้ fast-forward เข้า branch ของตัวเอง ไม่มี auto-merge
เหตุผล: เกณฑ์ Phase 2 (evidence ผูก exact commit, stale เมื่อ rebase) ทำได้ก็ต่อเมื่อ Runtime เป็นคนสร้าง integration commit; ปลายทางเป็น branch ของ Axon จึงไม่แตะ working tree ของผู้ใช้
เลื่อนไปก่อน: verifier + policy auto-merge (ต้องมีหลักฐานว่า verifier ตรงกับการตัดสินของผู้ใช้พอก่อน) และ config `merge` per project (เพิ่มเมื่อมีโหมดที่สองจริง)

## OD-009 Context Broker implementation — RESOLVED (ยังไม่สร้าง)

D-028: ยังไม่สร้าง Context Broker
**หลักฐานจาก Phase 3 ([PHASE3.md](PHASE3.md)):** prompt ที่ Axon ส่งเป็นเพียง ~1–4% ของ input tokens ในงานเล็ก (CLI อ่านไฟล์เองและ overhead ของ CLI ครองส่วนใหญ่) ลดได้มากสุดเท่านั้น

กลับมาดูเมื่อ: `axon-cli usage` กับงานจริงแสดงว่า PROMPT KB เป็นสัดส่วนสำคัญของ IN TOK (ราว 20% ขึ้นไป)
เมื่อสร้าง ให้เริ่มจาก deterministic Git/file retrieval (เลือกไฟล์จาก diff/scope) ไม่เริ่มจาก search index, embeddings หรือระบบ memory ที่ซับซ้อน แล้ววัดซ้ำด้วย `axon-cli usage`

## OD-010 Project configuration format — RESOLVED

D-020: TOML นอก repo: `~/.config/axon/config.toml` (ทั้งระบบ) และ `~/.config/axon/projects/<project>.toml` (ต่อ project; ตัวอย่างใน [Execution Design](EXECUTION_DESIGN.md) §9) ไม่มีส่วนไหน commit ลง repo ของ project (D-007)
ไฟล์คำสั่งที่ repo มีอยู่แล้ว (`CLAUDE.md`, `AGENTS.md`) เป็นข้อมูลของ project ตาม OD-013 ไม่ใช่ config ของ Axon

## OD-011 Agent identity and roles — RESOLVED

D-029: hybrid ตามที่ implement:
- ค่าเริ่มต้นอยู่ใน config: agent เริ่มต้นของงานคือ claude; model/effort ต่อ agent อยู่ที่ `[agents]` ใน `config.toml`
- เลือกต่องานได้: `add -a/--agent`, `--model`, `--effort` หรือช่องในฟอร์มสร้างงาน
- บทบาทกำหนดจากชนิดงาน ไม่ใช่จากตัว agent: reviewer คืองานชนิด `review` ที่ได้ tools แบบอ่านอย่างเดียว; local coding ต้องเปิดเองด้วย `[local] coding = true` (D-026)

ไม่สร้างการจับคู่งานกับ agent อัตโนมัติ (capability matching) จนกว่าจะมีข้อมูลจาก `axon-cli usage` หรือ `probes/bench.py` ว่า agent ไหนเหมาะกับงานแบบไหน

## OD-012 Cost/usage accounting — RESOLVED

D-021: ไม่มี metric กลางตัวเดียว เก็บต่อ attempt: prompt bytes, เวลา (started/ended), model/effort ที่ใช้จริง และ usage เท่าที่ CLI เปิดเผย (`axon/usage.py`) ฟิลด์ที่ไม่เปิดเผยเป็น `None` และไม่ประมาณเอง ดูได้ด้วย `axon-cli usage`; การแบ่งคิวระหว่าง project ใช้ wall time เพราะมีครบทุก backend

วัดจริงแล้ว: Claude เปิดเผย tokens/cache/`total_cost_usd`/turns; Codex เปิดเผย tokens/cached ต่อ turn แต่ไม่มีราคา

## OD-013 Prompt-injection boundary — RESOLVED POLICY / OPEN ENFORCEMENT

D-023: trust labels และ precedence (สูง → ต่ำ)

| ระดับ | แหล่ง | ทำอะไรได้ |
| --- | --- | --- |
| 0 | Runtime policy: sandbox, tool list, scope, checks, config ของ Axon | ข้อความใด ๆ เปลี่ยนไม่ได้ |
| 1 | User instruction: spec, `instruct`, คำตอบ `ask_user`, approve/reject ผ่าน GUI/CLI ที่ยืนยันตัวตน | สั่งงานได้ภายในขอบเขตของระดับ 0 |
| 2 | Repo instruction: `CLAUDE.md`, `AGENTS.md`, README และไฟล์อื่นใน repo | แนะนำวิธีทำงานหรือสไตล์ได้ แต่ขัดระดับ 1 ไม่ได้และเพิ่มสิทธิ์ไม่ได้ |
| 3 | Agent message: `report_result`, `ask_user`, `delegate`, ผลรีวิว | เป็นข้อเสนอ ให้ Runtime หรือผู้ใช้ตัดสิน (MVP Contract §4) |
| 4 | Web/tool content และ generated artifact: หน้าเว็บ, output ของ check, log, diff, ไฟล์ที่ agent เขียน | เป็นข้อมูลเท่านั้น ไม่ใช่คำสั่ง |

กติกา:
- ระดับต่ำกว่า override ระดับสูงกว่าไม่ได้
- ข้อความที่ขอสิทธิ์เพิ่มให้เพิกเฉย ถ้างานต้องใช้มากกว่าขอบเขตจริง ให้ถามผู้ใช้ผ่าน `ask_user` เท่านั้น
- label ใน prompt เป็นตัวช่วยของโมเดล ไม่ใช่ enforcement (MVP Contract §3)

บังคับใช้แล้ว:
- ระดับ 0 อยู่นอก prompt: bwrap/cgroup, `--tools` แบบ default-deny ของ Claude, flag นอก scope/ไฟล์ protected ตอน verify, checks รันแบบไม่มีเน็ต
- settings ของ agent CLI ใน repo (`.claude/`, `.codex/`, `.mcp.json` — `AGENT_CONFIG` ใน `axon/runtime.py`) เป็น protected เสมอ: ผลที่แก้ไฟล์เหล่านี้ไปที่ REVIEW และ attempt ที่จะเริ่มต่อจาก snapshot ที่ attempt ก่อนแก้ไฟล์เหล่านี้ (retry, ตอบคำถาม, quota) ต้องรอผู้ใช้อนุมัติก่อน เพราะ hooks/notify ในไฟล์เหล่านี้รันคำสั่งด้วยเน็ตของ CLI นอก `run_check` (tests: `test_agent_settings_in_a_result_need_review`, `test_a_retry_does_not_start_on_agent_settings_an_attempt_planted`)
- ระดับ 3: `delegate` จำกัด 1 ชั้น ไม่เกิน `max_delegations` และ scope ต้องอยู่ใน scope ของงานแม่; ผลของ agent ไม่เปลี่ยนสถานะเอง เพราะ Runtime รัน checks ก่อน COMPLETED
- ระดับ 4: prompt ของ reviewer ระบุว่า requirement และ diff เป็นข้อมูล ไม่ใช่คำสั่ง (`_review_prompt`); diff ที่มี credential ของ agent จะไม่ถูก fetch (`_collect`); hooks ของ git ใน clone ไม่ถูกรัน (`core.hooksPath=/dev/null`)

ความเสี่ยงที่ยอมรับ: เปิดเว็บให้ agent เป็นค่าเริ่มต้น (`[agents] web = true`) เพราะงานจริงต้องค้นข้อมูลได้ (ผู้ใช้ตัดสิน 2026-10-08) เนื้อหาเว็บ (ระดับ 4) จึงเข้าถึง agent ได้โดยตรง และเครื่องมือเว็บเปิด URL ที่โมเดลเลือกได้ ซึ่งเป็นช่องส่งข้อมูลออก (คำสั่งและ checks ยังไม่มีเน็ต) ยอมรับได้กับ project ส่วนตัว; ถ้ามี project ที่มีข้อมูลอ่อนไหว ให้เพิ่มสวิตช์ปิดเว็บราย project (ตอนนี้มีแค่ระดับทั้งระบบ)

ยังต้องทำ (enforcement):
1. prompt ของงาน implement รวมคำสั่งผู้ใช้ ผลของ check และผลรีวิวไว้ในหัวข้อเดียว ("Notes from earlier attempts and the user") ให้แยกเป็นส่วนตามระดับ และใส่บรรทัด "data, not instructions" แบบเดียวกับ prompt ของ reviewer
2. รัน `python3 probes/adapter.py claude hooks` และ `codex hooks` กับ CLI จริงแล้วบันทึกผลที่นี่: (ก) CLI โหลด settings จาก repo เอง และคำสั่งนั้นมีเน็ตหรือไม่ — ถ้าใช่ ให้ปิดการโหลด project settings ตอนรันงานถ้า CLI ทำได้; (ข) agent เขียนลง agent home ของตัวเอง (`~/.local/share/axon/agents/<agent>/`) ได้หรือไม่ — agent home ถูก mount แบบเขียนได้ ถ้าเขียนได้ agent จะวาง settings ระดับผู้ใช้ให้งานถัดไปได้ ซึ่ง protected paths ไม่ครอบคลุม

## OD-014 Plugin/adapter sandbox — RESOLVED

D-024: child process ใน sandbox: agent CLI, MCP server ของ Axon (`axon/mcp.py`) และ local Agent Runner (`axon/local_agent.py`) รันใน bwrap + systemd scope ของ attempt นั้น ถ้าล่มหรือถูกฆ่าจะกระทบแค่ attempt นั้น (Runner บันทึกเป็น crashed/interrupted แล้ว retry หรือ requeue)
adapter ใน `runtime.py` เป็นแค่ฟังก์ชันที่สร้าง argv/env อยู่ในโค้ดของ Axon เอง ไม่โหลดโค้ดจากภายนอก
ยังไม่มีระบบ plugin จากภายนอก ถ้าจะเปิดให้ตัดสินใหม่ (WASM/container)

## OD-015 Remote control — RESOLVED (Tailscale เท่านั้น) / KNOWN GAPS

D-005 ยืนยัน local UI สำหรับ MVP และเตรียม authentication boundary สำหรับ remote; Axon ยัง bind แค่ `127.0.0.1` และไม่มี remote listener ของตัวเอง

D-030: เข้าจากเครื่องอื่นผ่าน Tailscale เท่านั้น ตามที่ implement:
- `axon passwd` ตั้งรหัสผ่าน (เก็บแบบ PBKDF2-SHA256 600k รอบ ที่ `~/.config/axon/password`, ล็อกอินทีละครั้ง ผิดแล้วหน่วง 1 วินาที); ลบรหัสผ่าน = ปิด remote ทันที
- `axon remote` เรียก `tailscale serve` ให้เปิดเป็น HTTPS ภายใน tailnet และเพิ่มชื่อเครื่องใน `[server] hosts`; `axon remote --off` ปิด
- server ปฏิเสธ Host ที่ไม่อยู่ใน allowlist และปฏิเสธชื่อ remote ถ้ายังไม่มีรหัสผ่าน (`axon/server.py`)
- ห้ามเปิดออก internet สาธารณะ (เช่น Tailscale Funnel หรือ bind address อื่น)

ช่องว่างที่รู้แล้ว (ต้องทำก่อนใช้จากมือถือเป็นประจำ):
1. ทุกเครื่องที่ล็อกอินได้ session token เดียวกันต่อการรัน server ตัดสิทธิ์ทีละเครื่องไม่ได้ ต้องรีสตาร์ท Axon ซึ่งตัดทุกเครื่องพร้อมกัน และการเปลี่ยนรหัสผ่านไม่ทำให้ session เดิมหลุด → เพิ่ม token แยกต่อเครื่องที่เพิกถอนได้
2. ไม่มีระดับสิทธิ์: ล็อกอินแล้วทำได้ทุกอย่างรวมถึง Chat ที่มีเน็ต
3. หน้าจอยังไม่ได้ออกแบบสำหรับมือถือ → ตอบด้วยแอป native ([MOBILE.md](MOBILE.md)) ไม่ใช่การปรับ browser UI

## OD-016 Persistent agent relationships — RESOLVED

D-031: session ต่อ attempt สำหรับงาน (task) ตามที่ implement; ความต่อเนื่องมาจาก git snapshot, รายการงานที่เสร็จแล้วใน scope เดียวกัน และโน้ตจากรอบก่อนใน prompt ไม่ใช่จาก session ของ provider
- contamination: งานหนึ่งไม่เห็นบทสนทนาของอีกงาน
- crash recovery: ไม่ต้องพึ่ง resume ของ provider (Claude session หายถ้าถูก kill ก่อนบันทึก — Phase 1b)
- context bloat: ทุก attempt เริ่มจาก context ว่าง
- งานที่ต้องคุยต่อเนื่องใช้ Chat (session ยาวใน tmux ที่ผู้ใช้คุมเอง)

กลับมาดูเมื่อ: วัดได้ว่าแต่ละงานเสีย token ไปกับการอ่าน repo ซ้ำจนเป็นต้นทุนหลัก

## OD-017 Consensus mechanism — RESOLVED (ไม่สร้าง Debate)

D-032: ไม่สร้างระบบ Team/Debate; ใช้วงจร implement → review → revise ที่มีอยู่ (จำกัดรอบด้วย `limits.review_rounds`, ค่าเริ่มต้น 2) และผู้ใช้เป็นคนตัดสิน approve/reject
**หลักฐานจาก Phase 5 ([PHASE5.md](PHASE5.md)):** ลองวัด proposal → critique → implement กับ direct บนงานที่ spec มีกฎละเอียด: ผลต่างเห็นเฉพาะ semver (direct ล้ม 2/2, debate ผ่าน 1 และอีกรอบค้าง) ในราคา ~3× เวลา/token และ 2 จาก 6 รอบค้างรออนุมัติ

D-034 เพิ่มแค่การถามตอบระหว่าง Claude กับ Codex (`ask_peer`, ถามทีละข้อ ไม่มีรอบ proposal/critique และไม่มีการลงคะแนน) ไม่ใช่ Debate
D-035 (Brainstorm) เป็นการวางแผนก่อนลงมือ ไม่ใช่ Debate เรื่องโค้ด: อ่านอย่างเดียว ไม่โหวต และผู้ใช้กดสร้างงานและตัดสินข้อที่เห็นไม่ตรงกันเอง จึงยังเข้ากับเงื่อนไข "verifier + ผู้ใช้ตัดสิน" ด้านล่าง ต้นทุนประมาณ 7 รันสั้นต่อฝั่ง (มากกว่านั้นถ้า agent ถามผู้ใช้เพิ่ม); ยังไม่ได้วัดคุณภาพเทียบกับสั่งงานตรง ๆ

ถ้าจะสร้างในอนาคต: ใช้ verifier (checks ของ project) เป็นตัวตัดสินหลัก และส่งให้ผู้ใช้ตัดสินเมื่อไม่ลงตัว ห้ามใช้ majority vote อย่างเดียว
กลับมาดูเมื่อ: งานจริงล้มเป็นประจำในแบบที่ review → revise แก้ไม่ได้

## OD-018 First supported platforms — RESOLVED

D-002: Linux first ยืนยันแล้ว ระบบอื่นเป็นงานภายหลังและยังไม่อยู่ในเกณฑ์ผ่าน MVP

## OD-019 Provider policy compatibility — RESOLVED (อ่านเงื่อนไขแล้ว 2026-10-08 / เหลือข้อเทา 1 ข้อ)

หลักการ: ใช้ binary ทางการ (`codex`, `claude`) ด้วย login ของผู้ใช้เองบนเครื่องของผู้ใช้เอง ไม่ทำ browser scraping หรือ credential circumvention (D-018)

**Anthropic** ([Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance), [Consumer Terms](https://www.anthropic.com/legal/consumer-terms) มีผล 2025-10-08)
- OAuth ของแผน Free/Pro/Max ออกแบบเพื่อการใช้งานปกติของ Claude Code; ห้ามนักพัฒนา route request ผ่าน credential ของแผน subscription แทนผู้ใช้ และห้ามเก็บ/ส่งต่อ credential หรือ session token ของ Claude.ai; ผู้ใช้ล็อกอินใน binary ที่ไม่ได้ดัดแปลงด้วยบัญชีตัวเองได้
- ขีดจำกัดของ Pro/Max "ตั้งอยู่บนการใช้งานแบบปกติของแต่ละบุคคล"
- Consumer Terms ข้อ 3.7 ห้ามเข้าถึงด้วย "automated or non-human means ... bot, script" ยกเว้นผ่าน API key หรือที่ Anthropic อนุญาตชัดเจน; ข้อ 2 ห้ามแชร์ credential/account

**OpenAI** ([Codex auth](https://learn.chatgpt.com/docs/auth), [CI/CD auth](https://learn.chatgpt.com/docs/auth/ci-cd-auth))
- ล็อกอินด้วย ChatGPT หรือ API key ได้ทั้งคู่; API key เป็นค่าที่แนะนำสำหรับ automation/CI
- ChatGPT auth ใน automation ใช้ได้เฉพาะ "trusted private infrastructure": ห้ามกับ repo สาธารณะ, ห้ามแชร์ `auth.json` ข้าม job พร้อมกันหรือหลายเครื่อง
- Terms of Use และ Help Center ของ OpenAI อ่านจากต้นฉบับไม่ได้ (HTTP 403) ที่ได้เป็นแหล่งรอง: ห้าม extract data แบบ automated, ห้ามแชร์ credential, ห้าม circumvent rate limit — ควรอ่านที่ openai.com/terms อีกรอบ

**Axon เทียบกับเงื่อนไข (ตรวจกับโค้ด 2026-10-08; ไม่ใช่คำวินิจฉัยทางกฎหมาย)**
- สอดคล้อง: เรียก binary ทางการด้วย login ของผู้ใช้เอง (login ทำผ่าน `claude auth login` / `codex login` ใน agent home แยก), ไม่ scrape เว็บ, 1 slot ต่อ provider (D-009), rate limit เป็น WAITING_QUOTA พร้อม backoff, ใช้คนเดียวบนเครื่องส่วนตัว
- **แก้แล้ว:** เดิม `usage.claude_limits` อ่าน OAuth token จาก `.credentials.json` แล้วยิง `api.anthropic.com/api/oauth/usage` (endpoint ไม่เปิดเผย) เอง ซึ่งเข้าข่าย "collect/intermediate credentials" ตอนนี้ลบแล้ว: แถบ quota ของ Claude อ่านจาก `rate_limit_event.unifiedWindows` ที่ `claude` ส่งใน stream ของตัวเอง (Runner เขียนลง `claude-limits.json` หลังแต่ละ attempt; ตรวจกับ CLI จริง 2026-10-08) Axon ไม่แตะ token ของ Claude อีก ฝั่ง Codex อ่านไฟล์ session ในเครื่องที่ Codex เขียนเองอยู่แล้ว
- **เคยเทา → ลดแล้ว:** `claude -p` (non-interactive) ด้วย subscription: ข้อ 3.7 ห้าม "script" แต่ docs ของ Claude Code ไม่ได้ห้ามเรียก binary ทางการแบบ headless สองข้อไม่ตรงกันและโค้ดแก้คำตัดสินไม่ได้ จึงเปลี่ยนค่าเริ่มต้นของ Claude เป็น **interactive** (`[agents] claude_mode = "interactive"`): task เปิด `claude "<prompt>"` เป็น terminal จริงใน tmux session `axon-chat-task<id>` (sandbox/cgroup เดิม; เปิดดู/คุยต่อได้ในแท็บ Chat) งานจบเมื่อ agent เรียก `report_result`/`ask_user`, ผู้ใช้ปิด session, Stop หรือหมดเวลา Axon ไม่ฉีด keystroke ยกเว้น nudge หนึ่งครั้ง (D-036); ตอบ trust-folder ใน config ของ Claude เอง (`trust_folder`) ตรวจกับ `claude` จริง 2026-10-08 (`probes/adapter.py claude`: COMPLETED 6 s) แถบ quota ของ Claude มาจาก status line ที่ Claude Code รองรับเอง (`--settings statusLine` → `axon/statusline.py` เขียน `axon-limits.json` ใน agent home; ตรวจกับ `claude` จริงแล้ว) ข้อแลก: ไม่มี stream-json จึงไม่มี usage ต่อ attempt, ตรวจ quota จากข้อความใน terminal (`TUI_QUOTA_RE`, ยังไม่เคยเห็นข้อความจริง), agent ที่รอคุณ (ขออนุญาตหรือถามเป็นข้อความธรรมดา) ไม่มีสัญญาณเอง: Runner ตั้งโน้ตของงานเป็น `waiting for you: open Chat, task<id>` เมื่อ terminal เงียบเกิน `IDLE_SECONDS` (90) และล้างเมื่อขยับอีก `claude_mode = "headless"` ยังใช้ได้ถ้าต้องการออโตเมชันเต็มหรือใช้ API key (ยังไม่ทำ: ส่ง `ANTHROPIC_API_KEY` เข้า env ของ `claude_cmd`) ข้อสังเกตจากการรัน Brainstorm จริง 2026-10-12: (1) Claude บางครั้งเขียนคำตอบลงหน้าจอแล้วจบเทิร์นโดยไม่เรียก `report_result`, หรือเรียกไม่ได้เพราะเซิร์ฟเวอร์ MCP ของ Axon ยังเชื่อมต่อไม่เสร็จในเทิร์นแรก (prompt ที่ตอบได้ทันทีเจอบ่อย) แก้ด้วย D-036: Axon ส่ง nudge ข้อความคงที่หนึ่งครั้งหลังนิ่ง 90 วินาที (ไม่ส่งถ้าหน้าจอเป็นคำถามขอสิทธิ์) และมีประโยค "Required last step" ท้าย prompt ถ้ายังไม่เรียก โน้ต `waiting for you` รอผู้ใช้พิมพ์ในแท็บ Chat (ยังไม่เคยวัดว่า nudge ได้ผลกับ Claude จริง) (2) tmux ปฏิเสธคำสั่งยาวเกิน ~16 KB จึงรัน agent ผ่านไฟล์ `launch.sh` ใน attempt แทนการส่ง prompt ทาง argv ของ tmux

Codex ยังเป็น headless (OpenAI อนุญาต `codex exec` บนเครื่องส่วนตัวที่เชื่อถือได้); interactive ของ Codex รอดูว่าของ Claude ใช้ได้ดี
- **ห้ามเด็ดขาด:** ให้คนอื่นใช้ Axon ผ่าน subscription ของเรา หรือเปิดเป็น service (ทั้งสองฝั่งห้ามแชร์ account) — ถ้าจะทำต้องเปลี่ยนเป็น API key (ผูกกับ Phase 6 / OD-015)

## OD-020 Initial backend surface — RESOLVED

D-001: เริ่มจาก CLI/session ที่ Runtime จัดการ การเชื่อมแชทเดิมหรือ Project บนเว็บอยู่นอก MVP
Interface ราย backend ผ่าน feasibility probes ของ OD-006 แล้ว (D-018)

## OD-021 Initial execution scope — RESOLVED

D-003: อ่าน–แก้โค้ด–รันทดสอบภายใน assigned workspace

D-022: bwrap + systemd user scope ต่อ attempt (`axon/sandbox.py`)
- ไฟล์: เห็น `/` แบบ read-only; `$HOME`, `/tmp`, `/run` เป็น tmpfs ว่าง (ซ่อน credential และ host socket เช่น docker/dbus); เขียนได้เฉพาะ clone ของ attempt, agent home และโฟลเดอร์ `rw` ที่ project ตั้งไว้
- เน็ต: process ของ agent CLI ออกไป provider ได้ แต่คำสั่งที่ agent รันไม่มีเน็ต (Claude ไม่มี Bash และรันคำสั่งได้แค่ `run_check`; Codex ใช้ `workspace-write` ของตัวเองซ้อนข้างใน); checks รันด้วย `--unshare-net`; `prepare` (ติดตั้ง dependency ที่ project ตั้งไว้) มีเน็ต และถ้า attempt ก่อนหน้าแก้ไฟล์ dependency ต้องให้ผู้ใช้อนุมัติก่อน
- ทรัพยากรและ process: `MemoryMax` + `MemorySwapMax=0`; Stop ฆ่าทั้ง tree ใน cgroup

หลักฐาน: `probes/boundary.sh`, `probes/adapter.py codex|claude escape|stop|recover` (2026-10-06)
ข้อยกเว้นที่ตั้งใจ: Chat (`axon chat` / หน้า Chat) เป็น session ที่ผู้ใช้คุมเอง คำสั่งมีเน็ต และ mount config ของ CLI จริงของผู้ใช้ (`~/.claude`, `~/.codex`) จึงไม่อยู่ภายใต้ขอบเขตนี้
ยังไม่ได้ทดสอบ: Claude อ่าน credential ของตัวเองได้หรือไม่ (MVP Contract §2); ไม่อนุมานสิทธิ์ side effects นอก workspace

## OD-022 Initial Local LLM role — RESOLVED

D-004: เริ่มจากสรุป context และวิเคราะห์ log

D-026: backend คือ Ollama บน loopback (`127.0.0.1:11434`; Runner ปฏิเสธ URL อื่นและไม่ fail over ไป cloud) โมเดลเริ่มต้น `qwen2.5-coder:7b` ทั้ง helper และ `[local]`; ฮาร์ดแวร์คือเครื่องที่มีอยู่ (GTX 1660 Ti 6 GB) ไม่ตั้ง budget แยก
บทบาท coding ปิดเป็นค่าเริ่มต้น (`[local] coding = false`) และให้คงปิดไว้ เพราะ Phase 4 ไม่มีงานใดผ่านครบ ([PHASE4.md](PHASE4.md)) ประเมินใหม่เมื่อมีโมเดลหรือฮาร์ดแวร์ที่ดีกว่า ด้วย `probes/bench.py --configs local`

## OD-023 Lifecycle, evidence and controls — RESOLVED (ตามที่ implement) / KNOWN GAPS

D-025: กติกาที่ใช้จริงในโค้ด (`axon/runtime.py`, `axon/store.py`, `axon/integrate.py`) แทน baseline ใน MVP Contract §4–§5

สถานะ: `QUEUED → RUNNING → COMPLETED | REVIEW | WAITING_INPUT | WAITING_APPROVAL | WAITING_QUOTA | FAILED | CANCELLED`
- งานใหม่เริ่มที่ QUEUED (ไม่มี NEW/ASSIGNED); การรัน checks เกิดภายใน RUNNING (ไม่มีสถานะ VERIFY แยก); การหยุดงานที่กำลังรันใช้ flag `cancel` บน RUNNING แทนสถานะ CANCELLING
- REVIEW คือรอผู้ใช้ตัดสิน (แก้นอก scope, แก้ไฟล์ protected หรือ agent ไม่ report): approve → COMPLETED, reject → FAILED
- WAITING_INPUT → QUEUED เมื่อผู้ใช้ตอบ; WAITING_APPROVAL → QUEUED เมื่ออนุมัติ; WAITING_QUOTA → RUNNING หลัง cooldown (ไม่นับเป็น retry); FAILED/CANCELLED → QUEUED เมื่อผู้ใช้สั่ง retry (attempt ใหม่ต่อจาก snapshot ล่าสุด)
- agent crash หรือ check ล้ม → retry อัตโนมัติไม่เกิน `max_attempts` แล้วเป็น FAILED

Guards:
- ทุก transition เป็น compare-and-set (`Store.move` เปลี่ยนเฉพาะเมื่อสถานะปัจจุบันอยู่ในชุดที่อนุญาต) และบันทึก event `status`
- ผลจาก attempt ที่ไม่อยู่ในสถานะ `running` แล้วถูกทิ้ง (`stale-result-dropped`) และ tool call จาก attempt นั้นถูกปฏิเสธ
- Runner มีได้ตัวเดียว (file lock) แทน lease/heartbeat; `recover()` ฆ่า scope ที่ค้างแล้ว requeue
- instruction เปลี่ยนระหว่างรัน → ทิ้งผลแล้วรันใหม่
- task key ซ้ำไม่สร้างงานใหม่ (unique index) และงานที่ scope ทับกันไม่รันพร้อมกัน

Event schema: `events(id, task, attempt, kind, data JSON, at)` มี producer คือ Runtime ตัวเดียว

Action reconciliation: side effect ของ attempt จำกัดอยู่ที่ clone และ `refs/axon/attempts/<id>` ซึ่งเขียนซ้ำได้ จึง requeue ได้โดยไม่ replay ผลภายนอก; promote/discard ผูกกับ commit ที่ผู้ใช้เห็น (`expected`) และไม่รัน hooks

Approval และ evidence: approve ของ review ผูกกับ commit ที่ตรวจ (revision ไม่ได้รับ approval เดิม); promote ต้องมี checks ผ่านครบบน integration commit นั้นพอดี และต้องมี review ถ้า project บังคับ (`require_review`)

| Control | ที่ทำจริง |
| --- | --- |
| Pause / Resume | หยุดหรือเปิดการ dispatch ทั้งระบบ (`meta.paused`) งานที่รันอยู่ทำต่อ |
| Stop | งานที่ยังไม่รัน → CANCELLED ทันที; งานที่รันอยู่ → ตั้ง `cancel` แล้ว `systemctl --user stop` scope (SIGTERM แล้ว SIGKILL หลัง 10 วินาที) และเป็น CANCELLED เมื่อ process หมดจริง |
| Kill | ไม่มีปุ่มแยก เพราะ Stop ฆ่าทั้ง tree อยู่แล้ว |
| Retry | FAILED/CANCELLED → attempt ใหม่ต่อจาก snapshot ล่าสุด (ใช้แทน Reassign) |
| Add instruction | ต่อท้าย context เพื่อใช้ใน attempt ถัดไป ถ้าเปลี่ยนระหว่างรันจะทิ้งผลแล้วรันใหม่ |
| Rollback | `discard` ลบ integration branch โดยไม่ย้อน branch ของผู้ใช้ |

ช่องว่างกับ MVP Contract ที่รู้แล้ว (แก้เมื่อมีเหตุให้ต้องใช้):
1. การอนุมัติก่อนเริ่ม attempt ที่ต่อจาก snapshot (ไฟล์ dependency ที่ `prepare` ใช้เน็ต และ settings ของ agent ตาม OD-013 — ถามครั้งเดียวพร้อมเหตุผลทั้งหมด) ผูกกับ task (`approved = 1`) ไม่ได้ผูกกับ hash ของไฟล์ ถ้า attempt หลังแก้ไฟล์เหล่านั้นอีกจะไม่ถามซ้ำ ควรผูกกับ hash ของไฟล์ที่อนุมัติ
2. update สถานะกับ event `status` อยู่คนละ statement ไม่ใช่ transaction เดียว ถ้า crash ระหว่างนั้น event จะหายได้ (สถานะยังถูกต้อง)
3. event ไม่มี schema_version / correlation id / producer sequence ซึ่งพอสำหรับ Runtime ตัวเดียว แต่ต้องเพิ่มก่อนมี producer ที่สอง (remote หรือ A2A)

## OD-024 Project name — RESOLVED

D-011: Axon — ชื่อแรก "A2A" ชนกับ Agent2Agent (A2A) protocol ซึ่ง OD-005 อาจทำ bridge ไปหาในอนาคต; ชื่อที่สอง Navis ฟังคล้าย Jarvis จึงเปลี่ยนเป็น Axon (2026-10-07)
