# Initial Roadmap

> ขอบเขต MVP ยืนยันแล้วใน [Confirmed Decisions](DECISIONS.md); implementation และเกณฑ์ผ่านด้านล่างยังเป็นข้อเสนอ รายละเอียดอยู่ใน [MVP Contract](MVP_CONTRACT.md)

## Phase 0 — Linux boundary feasibility (ไม่ใช้ quota)

Boundary probes: `probes/boundary.sh` (ผ่านแล้ว 2026-10-06)
สร้าง `fake-agent` ก่อน adapter จริง เพื่อให้ acceptance scenarios ทดสอบได้โดยไม่ใช้ quota (D-013)
Core language: Python (D-012)
Exit: sandbox, cgroup และ git isolation ใช้งานได้บนเครื่องจริง

## สถานะรวม (2026-10-08)

- **merge แล้ว:** Phase 0–3 (Phase 1b ทดสอบเฉพาะบางส่วน ดูด้านล่าง), Phase 4 ที่สร้างแล้วแต่ปิดไว้, Phase 5 ที่วัดแล้ว, การเปลี่ยนชื่อเป็น Axon (PR #26)
- **ค้างตาม roadmap:** Phase 1b ยังไม่ทดสอบ quota จริง, ข้อความ rate limit จริง และ credential leak กับ CLI จริง; OD-019 (นโยบาย provider) ปิดแล้วโดยเหลือข้อเทาของ `claude -p`; งาน enforcement ที่ค้าง: OD-013 (probe hooks กับ CLI จริง), OD-015 (token ต่อเครื่อง, ระดับสิทธิ์) และ OD-023 (event schema ก่อนมี producer ที่สอง) (ดู [Open Decisions](OPEN_DECISIONS.md)); การวัด overhead บน VELA (OD-007); Context Broker ยังไม่สร้างจนกว่าจะมีงานจริงที่ prompt ใหญ่ (OD-009)
- **Local coding ปิดเป็นค่าเริ่มต้น** และยังไม่มีโมเดลที่ผ่านงานทดสอบ

## GUI foundation ที่มีแล้ว (ยังไม่ปิด Phase 1)

`python3 -m axon` เปิด local control GUI พร้อม in-process simulated agent, SQLite snapshot/events, task board, user requests และ lifecycle controls ดู [GUI Guide](GUI.md) สำหรับผลทดสอบและข้อจำกัด

หลังจากนั้น fake-agent, Runner, adapter ของ Codex/Claude/local, MCP และ integration/review มีแล้ว (ดู Phase 1–2); หลักฐานของ execution/boundary/process-tree มาจากการทดสอบ runtime จริงใน Phase 1 และ 1b ไม่ใช่จากผล UI simulation

## Phase 1 — Single-agent MVP foundations

สร้าง daemon, project/agent registry, adapter interface, durable task/attempt state, CLI และ UI เล็กบนเครื่องเดียว

ก่อนให้ coding agent เขียนไฟล์ ต้องมี:
- assigned workspace และ execution boundary สำหรับไฟล์/process/network/secrets
- worktree/resource ownership และ shared Git operation controls
- scoped policy/approvals; repo config ยกระดับสิทธิ์ไม่ได้
- bounded queues, loop/timeout/retry limits
- Stop/Kill และ cancellation propagation
- crash reconciliation, action IDs และ stale-result rejection
- immutable artifact refs, deterministic context baseline และ verifier evidence
- local client authorization boundary; remote listener ปิด
- scope claim, task dedup, slot และ cgroup limits (D-008)
- WAITING_QUOTA และ provider cooldown (D-009)

UI แสดงงาน สถานะ backend ผลลัพธ์/diff สิ่งที่รอผู้ใช้ และปุ่มควบคุม
Local helper สรุป context/วิเคราะห์ log เท่านั้น ไม่มี write/exec tools
Exit: single-agent, boundary, controls, recovery และ local UI acceptance cases ผ่านกับ `fake-agent` พร้อม evidence

### Phase 1 evidence (`python3 -m pytest`, 65 ผ่าน, 2026-10-06; fake-agent ผ่าน runtime จริง: bwrap + systemd scope)

| Scenario (MVP_CONTRACT §8) | Evidence | สถานะ |
| --- | --- | --- |
| Single-agent coding | `test_done_task_is_verified_and_fetched` | ผ่าน |
| Boundary escape / host socket | `test_agent_cannot_reach_host_secrets_or_control_state`, `test_checks_have_no_network_or_host_sockets`, `test_hooks_and_config_planted_in_the_clone_never_run_on_the_host` (hook/fsmonitor ที่ agent วางใน clone รันได้เฉพาะใน sandbox), `probes/boundary.sh` | ผ่าน |
| Scope / protected paths | `test_edit_outside_scope_needs_review`, `test_protected_path_needs_review` | ผ่าน |
| Stop/Kill | `test_stop_kills_orphaned_processes` | ผ่าน |
| Crash/restart, late result | `test_runner_restart_requeues_and_rejects_stale_result` | ผ่าน |
| Approval race | `test_review_approval_is_bound_to_the_observed_attempt`, `test_stop_is_bound_to_the_observed_attempt` | ผ่าน |
| Credential leak | `test_credential_in_diff_blocks_fetch_and_is_redacted` | ผ่าน |
| Quota limit | `test_quota_waits_for_cooldown_without_using_a_retry` | ผ่าน |
| Scope overlap / duplicate | `test_overlapping_scopes_never_run_together`, `test_duplicate_task_is_not_queued` | ผ่าน |
| Local/remote boundary | `tests/test_server.py` (401/403, Origin, loopback only) | ผ่าน |
| UI disconnect | `tests/gui-smoke.cjs` (simulation, 2026-10-08 ผ่าน); `tests/gui-real-smoke.cjs` (runtime จริงกับ fake-agent, 2026-10-08 ผ่าน: create → integrate → discard → integrate → fast-forward) | ผ่าน (ทั้งสองโหมด) |
| Stale context | `test_instruction_during_an_attempt_discards_its_result` (instruction เปลี่ยนระหว่างรัน → ทิ้งผล, รันใหม่โดยไม่เสีย retry), `test_task_stays_pinned_to_its_base_when_the_project_moves` (task ผูก base commit); stale integration commit เป็นงาน Phase 2 เพราะ Phase 1 ไม่ merge | ผ่าน (ขอบเขต Phase 1) |
| Unknown outcome | `test_crash_after_fetch_before_recording_is_rerun_once` (ผล fetch แล้วแต่ไม่ได้บันทึก → requeue, รันซ้ำครั้งเดียว, ไม่แตะ checkout ของ project); reconciliation เต็มรูปแบบเลื่อนไป Phase 2 ที่มี effect ภายนอก | ผ่าน (ตามเกณฑ์ที่แก้) |
| Local helper | `tests/test_helper.py` (4 เคส: อ้าง source ref และจับ ref ที่แต่งขึ้น, ไม่ส่ง tools/credentials, ปฏิเสธ URL ที่ไม่ใช่ loopback, ไม่ผ่าน proxy); ลองกับ Ollama `qwen2.5-coder:7b` จริงผ่าน `axon-cli summarize <id>` ใช้เวลา ~10 วินาที | ผ่าน (CLI เท่านั้น ยังไม่มีปุ่มใน GUI) |
| Two-agent collaboration | — | Phase 2 |
| cgroup MemoryMax | `test_process_over_the_memory_limit_is_killed_even_with_swap_available`; test นี้เจอว่า MemoryMax อย่างเดียวไม่เป็นเพดานจริงเมื่อมี swap (allocate 1.5 GB ใน limit 100M ยังรอด) จึงเพิ่ม `MemorySwapMax=0` | ผ่าน |

## Phase 1b — Real backend probes (ใช้ quota)

หลัง Phase 1 ผ่านกับ fake แล้วจึงรัน probes ใน [Execution Design](EXECUTION_DESIGN.md) §10 กับ Codex, Claude Code และ local backend หนึ่งตัว
ทดสอบ start, task/result, streaming, interrupt, resume, crash/restart, approval/enforcement และ usage visibility
เก็บ compatibility matrix พร้อมเวอร์ชัน, test commands และ evidence; capability ที่ไม่ผ่านให้ unsupported/limited ไม่จำลองว่ารองรับ
Exit: adapter จริงผ่าน acceptance scenarios ชุดเดียวกับ fake

### Phase 1b status (2026-10-06; codex-cli 0.160.1, claude 2.1.291)

ผ่าน: single-agent coding กับ Codex และ Claude จริงผ่าน Runner (`python3 probes/adapter.py codex|claude`), tool list ของ Claude ไม่มี Bash, resume ของ Codex หลัง kill -9, boundary escape กับทั้งสอง (`probes/adapter.py codex|claude escape`: อ่าน secret/state/checkout ไม่ได้, เน็ตของคำสั่งปิด, ไม่มีไฟล์เกิดบน host, canary ไม่รั่ว), Stop และ runner-crash recovery กลางงานกับทั้งสอง (`probes/adapter.py codex|claude stop|recover`: process tree หายหมดรวม orphan `setsid`, scope inactive, late result ถูกปฏิเสธ)
เจอจาก probe: `codex exec` ต้อง pre-approve MCP tools; Claude ต้องใช้ `--tools` เพื่อ default-deny; Claude session หายถ้า kill ก่อนบันทึก (Runner ไม่พึ่ง session ของ provider)
ยังไม่ผ่าน/ไม่ได้ทดสอบ: quota และ credential leak กับ CLI จริง (leak ไม่ได้ให้ agent จริงคัดลอก token จริงลง diff; ผ่านกับ fake-agent แล้ว), ข้อความ rate limit จริง (ไม่เผา quota เพื่อทดสอบ), local backend ใน matrix มีเฉพาะ summarize ไม่ใช่ coding

### Interactive mode (2026-10-08)

Claude ทำงานเป็น terminal session จริงแทน `claude -p` ตามค่าเริ่มต้น (`[agents] claude_mode`, ดู OD-019); `codex_mode` ยังเป็น `headless`

## Phase 2 — Two-agent collaboration and integration

เพิ่ม proposal/critique/delegate/review, task dependencies และ bounded conversation rounds
Codex implements -> Claude independently reviews -> verifier checks integration commit
สลับบทบาทได้ตาม capability ที่พิสูจน์แล้ว

เพิ่ม merge/integration queue, conflict handling และ rollback ของ managed workspace
Review/test ต้องผูก exact commit; rebase/merge แล้วต้องตรวจ final integration commit ใหม่
Merge authority ตาม D-014: Runtime รวมงานบน `refs/axon/integration/<project>` ผู้ใช้ fast-forward เอง; MVP ไม่ auto push/merge/deploy

Exit: สอง agent ไม่เขียน workspace/resource ชนกัน; late result และ stale evidence ไม่ถูกยอมรับ

### Phase 2 status

มีแล้ว: integration branch ตาม D-014 (`axon/integrate.py`): `axon-cli integrate <task>` รวมผล task ที่ COMPLETED บน `refs/axon/integration/<project>` ด้วย `git merge-tree` (ไม่แตะ working tree), รัน check ใน clone ของ commit ที่รวมแล้ว และเลื่อน ref ก็ต่อเมื่อผ่าน; `axon-cli integration <project>` ดูสถานะ; `axon-cli promote <project>` (หรือปุ่ม **Fast-forward** ใน GUI โหมด real และปุ่ม **Add to integration branch** ในรายละเอียดงาน) fast-forward branch ของผู้ใช้ โดยปฏิเสธเมื่อ working tree สกปรก, HEAD ไม่ใช่ branch, branch ขยับไปจาก integration, หรือไม่มี check ที่ผ่านบน commit นั้นพอดี และไม่รัน hooks
Review (`axon-cli review <task> -a codex|claude|fake`, ปุ่ม **Review with Claude**): review task แบบอ่านอย่างเดียวบน commit ผลพอดี reviewer เห็น requirement + diff + ผล check ของ Runtime ไม่เห็นบันทึกของ implementer, verdict ผูก commit, ถ้า reviewer แก้ไฟล์ verdict เป็นโมฆะ; config `require_review = true` ใน project toml ทำให้ integrate ต้องมี review ที่ approve commit นั้น ลองกับของจริงทั้งสองทิศ (`python3 probes/adapter.py codex|claude review`: Codex เขียน → Claude รีวิว 8 s; Claude เขียน → Codex รีวิว 23 s; reviewer ของ Claude มี tool เพียง Glob/Grep/Read + axon)
เพิ่มแล้ว (รอบสุดท้ายของ Phase 2):
- **Task dependency:** `axon-cli add --after <task>` (หรือ `after_task_id` ใน bridge) งานรอจน task นั้น COMPLETED แล้วเริ่มจากผลของมัน; ถ้า dependency ล้ม งานค้าง QUEUED พร้อมเหตุผลใน GUI; integrate งานที่ต่อยอดต้อง integrate ต้นทางก่อน
- **Revision แบบจำกัดรอบ:** `axon-cli revise <task>` / ปุ่ม **Revise from review**: เริ่มจาก commit ที่ถูกรีวิว พก findings เป็น context; จำกัดด้วย `[limits] review_rounds` (ค่าเริ่มต้น 2) เกินแล้วต้องตัดสินใจเอง
- **Delegate:** MCP tool `delegate(title, spec, scope)` ให้ agent แตกงานต่อ: scope ต้องอยู่ใน scope ของตัวเอง, ลึก 1 ชั้น (task ที่ถูก delegate ไม่ delegate ต่อ), ไม่เกิน `[limits] max_delegations` (ค่าเริ่มต้น 3), เริ่มหลัง parent จบจากผลของ parent; review task ไม่ delegate; `request_review` ไม่ใช่ tool ของ agent (ผู้ใช้หรือ policy เป็นคนสั่ง เพื่อไม่ให้ implementer เลือก reviewer ของตัวเอง)
- **Review ของ integration commit สุดท้าย:** `axon-cli review-integration <project> -a ...` / ปุ่มในแถบ integration; เมื่อ `require_review = true` promote ต้องมี review ที่ approve commit รวมนั้นพอดี (fast-forward ของ commit ที่ approve แล้วไม่ต้องรีวิวซ้ำ; รวมงานเพิ่มแล้ว commit เปลี่ยน approval เดิมใช้ไม่ได้)
- **Rollback:** `axon-cli discard <project>` / ปุ่ม **Discard** ลบ integration branch (task ยัง COMPLETED และ integrate ใหม่ได้; branch ของผู้ใช้ไม่ถูกแตะ)
- review task ไม่จอง scope และไม่ถูกนับเป็น "งานที่ทำแล้ว ห้ามทำซ้ำ" ของ agent อื่น

### Phase 2 evidence (2026-10-06; pytest 97 เคสผ่าน; agent จริง: codex-cli 0.160.1, claude 2.1.291)

| เกณฑ์ | Evidence | สถานะ |
| --- | --- | --- |
| สอง agent ทำงานพร้อมกันโดยไม่ชนกัน | `python3 probes/adapter.py codex pair`: Codex กับ Claude รันพร้อมกัน 7 s บน scope แยกกัน clone แยกกัน แล้ว integrate ได้ commit เดียวที่มีไฟล์ของทั้งคู่และ check ผ่านบน commit รวม; scope ทับกันไม่รันพร้อมกัน (`test_overlapping_scopes_never_run_together`) | ผ่าน |
| Codex implement → Claude review และสลับบทบาท | `adapter.py codex\|claude review` ทั้งสองทิศ | ผ่าน |
| Reviewer จับบั๊กได้จริง และ revision แก้ได้ | `adapter.py claude loop`: ฝังบั๊ก (`a - b`, ไม่จัดการ None, ไม่มี test) → Claude CHANGES ครบสามข้อ → Codex revise (แก้ + เขียน test) → Claude APPROVE | ผ่าน |
| รอบที่ไม่ลู่เข้าถูกจำกัด | `adapter.py codex loop`: Codex เป็น reviewer เข้มกว่า (จับว่า `or 0` ผิดกับค่า falsy อื่น) รอบ revise แรกจึงยัง CHANGES — ระบบหยุดที่ `review_rounds`, ไม่วนไม่จบ (`test_rounds_are_bounded_...`) | ผ่าน (พฤติกรรมตามออกแบบ) |
| Review/test ผูก exact commit และ stale เมื่อ commit เปลี่ยน | `test_review_gate_blocks_integration_until_the_exact_commit_is_approved`, `test_a_change_request_blocks_and_new_integration_makes_the_approval_stale`, `test_promote_is_bound_to_the_commit_the_user_saw_and_runs_no_hooks` | ผ่าน |
| Late result / stale evidence ไม่ถูกยอมรับ | Phase 1: `test_runner_restart_requeues_and_rejects_stale_result`, `test_instruction_during_an_attempt_discards_its_result`; Phase 2: revision ไม่ได้รับ approval ของ commit เดิม (`test_rounds_are_bounded_and_an_old_approval_does_not_cover_the_revision`) | ผ่าน |
| Conflict handling | `test_conflicting_result_is_rejected_and_the_ref_stays`, `test_checks_run_on_the_merged_commit_and_a_failure_does_not_advance_the_ref` | ผ่าน |
| Rollback ของ workspace ที่ Axon จัดการ | `test_discard_drops_the_integration_branch_and_tasks_can_be_integrated_again`; GUI: `tests/gui-real-smoke.cjs` | ผ่าน |

ข้อจำกัดที่ยังเหลือ: คุณภาพของ review วัดจากบั๊กที่ฝังเองกรณีเดียว (ไม่ใช่ชุดเปรียบเทียบ); Debate/consensus หลายรอบแบบ proposal/critique ระหว่าง agent โดยไม่ผ่านผู้ใช้เป็นงาน Phase 5 (OD-017); dependency มีต้นทางเดียว (ไม่มี fan-in หลาย dependency); ฟอร์มสร้างงานใน GUI มีช่อง **Start after task** แล้ว (ดู [GUI Guide](GUI.md)) แต่ยังเลือกได้ต้นทางเดียว; การประเมิน quota รวมของวงจร implement→review→revise ยังไม่ได้วัด (ใช้ token จริงทุกรอบ)

## Phase 3 — Context and resource optimization

เพิ่ม Git-aware retrieval, conversation delta, versioned summaries, invalidation, bounded caches และ budgets
วัดเทียบ single-agent baseline: completion quality, retry/failure rate, elapsed time, context bytes และ provider usage เมื่อ expose
ไม่ถือว่า context fingerprint เท่ากับ provider cache hit
กำหนด retention/cleanup และ project scheduling fairness ตาม usage จริง

### Phase 3 status (2026-10-06)

มีแล้ว: usage accounting ต่อ attempt (`axon-cli usage`), fair scheduling ระหว่าง project ตาม usage จริง, retention (`axon-cli gc`), bounded cache และ benchmark เทียบ agent เดี่ยวกับ implement → review (`probes/bench.py`) — ผลและข้อจำกัดอยู่ใน [Phase 3 measurements](PHASE3.md)
ผลหลัก: ในงานเล็ก 3 งานทุก config ได้คะแนนเต็ม (วัดคุณภาพไม่แยก), pipeline ใช้เวลา ~4× และ input tokens ~2.8× ของ Claude เดี่ยว, และ context ที่ Axon ส่งเป็นเพียง ~1–4% ของ input tokens (overhead ของ CLI ครองส่วนใหญ่) จึงเลื่อน Context Broker ออกไปจนกว่าจะวัดงานจริงที่ prompt ใหญ่

### Model และ effort ต่อ agent

ตั้งได้ที่ `[agents] claude_model / claude_effort / codex_model / codex_effort` ใน `config.toml` (ว่าง = ค่าเริ่มต้นของ CLI), หน้า Settings, `axon-cli agent-options`, และ override ต่องานด้วย `add --model --effort` หรือช่องในฟอร์มสร้างงาน ส่งเป็น `--model/--effort` (Claude) และ `-m` กับ `-c model_reasoning_effort=...` (Codex); ค่าที่ใช้จริงบันทึกต่อ attempt (`axon-cli usage` แสดงคอลัมน์ SETTINGS)
ยืนยันกับ CLI จริงที่ค่าต่ำสุด: Claude ใช้ Haiku (`claude-haiku-4-5-20251001`) ตามที่ตั้งจริง (ดูจาก `modelUsage` ใน log) เทียบกับค่าเริ่มต้น `claude-sonnet-5-5`; Codex ยอมรับ `model_reasoning_effort="low"` และงานผ่าน แต่ **ยืนยันไม่ได้ว่า effort เปลี่ยนพฤติกรรม** (ค่าปลอมไม่ทำให้ Codex ฟ้อง ใช้พิสูจน์ไม่ได้ และ log ไม่แสดง effort) ตามคำสั่งให้ทดสอบที่ค่าต่ำสุดจึงไม่ได้ลองระดับสูง

## Phase 4 — Optional local coding

สร้าง/ขยาย Agent Runner: tool loop, validation, permission enforcement, bounded turns, cancellation และ recovery
เปิด local coding หลังผ่าน tool/permissions/workspace acceptance tests และมีการอนุญาตบทบาทนั้น
ไม่บังคับให้ local helper เปลี่ยนเป็น coder เพื่อให้ MVP เสร็จ

### Phase 4 status (2026-10-06)

Agent Runner ของ local model สร้างและทดสอบแล้ว (`axon/local_agent.py`, adapter `local`): tool loop ที่จำกัดรอบ/คำสั่งผิด/คำสั่งซ้ำ/ความยาวต่อรอบ, permission enforcement (ไม่มี shell, path ถูกตรวจกับ workspace, ห้าม `.git`, symlink ออกนอกไม่ได้), cancellation และ recovery ผ่าน cgroup/Runner เดิม — ทุกเกณฑ์ของ MVP Contract มี test
**บทบาทปิดเป็นค่าเริ่มต้น และแนะนำให้คงปิด:** ผลวัดกับโมเดล 7B ไม่มีงานใดจาก 3 งานผ่านครบ (cloud ผ่านครบ) และรอบ revision ที่ Claude รีวิวก็ไม่ช่วย รายละเอียดและวิธีเปิดอยู่ใน [Phase 4](PHASE4.md)

## Phase 5 — Advanced orchestration and UI

เพิ่ม Team/Debate, dynamic scheduling, capability matching, adversarial review, multi-project scheduling และ A2A bridge เมื่อมี use case ที่พิสูจน์แล้ว
ค่อยขยาย UI/พิจารณา desktop wrapper; framework ยังไม่ล็อก

### Phase 5 status — Debate (วัดก่อนสร้าง)

ยังไม่สร้างระบบ Team/Debate: ทดลองวัดด้วยงานที่ต่อกันจากของเดิม (`probes/debate.py`) ผลสรุปอยู่ใน [Phase 5](PHASE5.md) — เห็นความต่างเฉพาะ spec ที่มีกฎตรวจ/ข้อผิดพลาดยาว (semver) ในราคา ~3× เวลาและ token และ 2 จาก 6 รอบค้างรออนุมัติ จึงเลื่อนไว้ A2A bridge, desktop wrapper และ adversarial review ไม่ทำ (ยังไม่มี use case)

ที่ทำแล้ว: ปิดช่องว่าง GUI (dependency, check ต่องาน, reviewer, usage); agent `auto` พร้อม reroute เมื่อชน quota (ยังไม่เคยชน quota จริง ทดสอบด้วย agent จำลอง); เปลี่ยนชื่อโปรเจกต์เป็น Axon (D-011)

## Phase 6 — Remote control

เป็นงานในอนาคต ไม่อยู่ใน MVP
เพิ่ม authenticated clients, authorization, secure transport, revocation และ mobile-friendly UI
ทดสอบ remote boundary ก่อนเปิด listener; ไม่ expose provider/model/shell endpoint โดยตรง

## สิ่งที่ไม่อยู่ใน MVP

- takeover แชทเดิม/Project บนเว็บ หรือ browser scraping
- autonomous swarm จำนวนมาก
- memory/vector DB ขนาดใหญ่
- local coding ก่อน Agent Runner ผ่าน tests
- auto push/merge/deploy
- unrestricted execution เมื่อ adapter enforce policy ไม่ได้
- remote listener และ desktop UI หนัก
