# Confirmed Decisions

วันที่ยืนยัน: 2026-10-06

เอกสารนี้บันทึกขอบเขตที่ผู้ใช้เลือกแล้ว ส่วนรายละเอียด implementation ที่ยังไม่เลือกอยู่ใน [Open Decisions](OPEN_DECISIONS.md) ข้อเสนอเกณฑ์ผ่านอยู่ใน [MVP Contract](MVP_CONTRACT.md) และการออกแบบที่ implement ได้อยู่ใน [Execution Design](EXECUTION_DESIGN.md)

| ID | คำตัดสินที่ยืนยันแล้ว | ผลต่อ MVP |
| --- | --- | --- |
| D-001 | เริ่มจาก CLI/session | Runtime จัดการ session ของ Codex/Claude Code; การเชื่อมแชทเดิมหรือ Project บนเว็บอยู่นอก MVP |
| D-002 | Linux first | พิสูจน์ process lifecycle และ execution boundaries บน Linux ก่อน; ระบบอื่นยังไม่อยู่ในเกณฑ์ผ่านรุ่นแรก |
| D-003 | อ่าน–แก้โค้ด–รันทดสอบได้ภายใน workspace | Agent ทำงานใน workspace ที่จัดสรรให้; ไม่อนุมานสิทธิ์เข้าถึงไฟล์อื่น ติดตั้งระบบ push merge หรือ deploy |
| D-004 | Local LLM เริ่มจากสรุป context และวิเคราะห์ log | ไม่มีเครื่องมือเขียนไฟล์หรือรันคำสั่งให้ local helper; coding เปิดได้ภายหลังเมื่อ Agent Runner ผ่านเกณฑ์ทดสอบและอนุญาตบทบาทนั้น |
| D-005 | UI บนเครื่องเดียวก่อน แต่เตรียม authentication boundary สำหรับ remote | MVP ไม่มี remote listener; ออกแบบ client identity และขอบเขตการอนุญาตก่อนเพิ่ม remote |
| D-006 | ผู้ใช้คนเดียว | ไม่มี multi-user/role; control socket ของผู้ใช้ใน `$XDG_RUNTIME_DIR` เป็น local boundary และ sandbox มองไม่เห็น |
| D-007 | รองรับหลาย project; ใช้ PROJECT_VELA (Python 3.11 + uv + pytest/ruff/mypy) เป็นตัวทดสอบแรก (ไม่ใช่ project เดียวอีกต่อไป) | ไม่เพิ่มไฟล์ใน repo ของ project; project config อยู่นอก repo เป็น TOML |
| D-008 | เป้าหมายหลัก: แบ่งงานชัด ไม่ทับกัน ไม่ทำงานที่ทำไปแล้วซ้ำ และแบ่งทรัพยากรเครื่อง | scope claim, task dedup, slot และ cgroup limits เป็นงาน Phase 1 ([Execution Design](EXECUTION_DESIGN.md) §8) |
| D-009 | ใช้ subscription ของ provider (ไม่ใช้ API key) | ไม่เกิน 1 session ต่อ provider; quota หมดเป็นสถานะปกติ (WAITING_QUOTA) ไม่ใช่ error |
| D-010 | Runtime commit ได้ใน clone ของ attempt | snapshot อยู่ใน clone และ `refs/axon/*` ของ repo หลักเท่านั้น; branch ของผู้ใช้, push, merge และ deploy ยังเป็นของผู้ใช้ |
| D-011 | ชื่อโปรเจกต์คือ Axon (เดิม Navis, เปลี่ยน 2026-10-07 เพราะฟังคล้าย Jarvis) | repo/folder ชื่อ `PROJECT_AXON`; CLI, config dir, refs และ systemd units ใช้ `axon` |
| D-012 | Core เขียนด้วย Python | Python ≥ 3.11 (ตรงกับ project ทดสอบแรก) ใช้ stdlib ก่อน |
| D-013 | สร้างและทดสอบกับ `fake-agent` ให้เสร็จก่อนใช้ CLI จริง | probes ที่ใช้ quota (Execution Design §10) เลื่อนไปหลัง Runtime ผ่าน acceptance scenarios กับ fake แล้ว |
| D-014 | Merge: ผู้ใช้สั่ง, Runtime รวมงานบน integration branch ของ Axon | Runtime rebase/merge ผลของ task บน `refs/axon/integration/<project>` แล้วรัน check ซ้ำบน commit สุดท้าย; ผู้ใช้ fast-forward เข้า branch ของตัวเองเอง (CLI ก่อน, GUI ภายหลัง) Runtime ไม่แตะ branch หรือ working tree ของผู้ใช้ และไม่มี auto-merge ใน MVP (OD-008) |

### ยืนยันเพิ่ม 2026-10-08 (บันทึกตามที่ implement แล้ว)

| ID | คำตัดสินที่ยืนยันแล้ว | ผลต่อ MVP |
| --- | --- | --- |
| D-015 | UI เป็น browser UI ที่ Axon serve เอง | `axon/web` ไม่มี framework/build step; ไม่ทำ desktop wrapper จนกว่าจะมีความต้องการที่ browser ทำไม่ได้ (OD-002) |
| D-016 | Transport: HTTP บน loopback + polling, WebSocket เฉพาะ terminal ของ Chat, Unix socket ต่อ attempt สำหรับ agent | เปลี่ยนเป็น SSE เมื่อ polling ช้าหรือเปลืองจนวัดได้ (OD-003) |
| D-017 | Storage: SQLite (WAL) เป็น state หลัก ไฟล์ของ attempt อยู่ข้าง ๆ | ไม่ใช้ embedded DB อื่น (OD-004) |
| D-018 | Adapter ใช้โหมด noninteractive แบบมีโครงสร้างของ CLI ทางการ + MCP tools ของ Axon | ไม่ใช้ PTY/app-server; Runner ไม่พึ่ง resume ของ provider (OD-006) |
| D-019 | Clone ต่อ attempt (`git clone --shared`) ไม่ใช้ worktree | ผลกลับเป็น bundle ที่ `refs/axon/attempts/<id>` (OD-007) |
| D-020 | Project config เป็น TOML นอก repo ทั้งหมด | ไม่มีส่วนไหน commit ลง repo ของ project (OD-010) |
| D-021 | Usage accounting ต่อ attempt: prompt bytes, เวลา, model/effort และ usage เท่าที่ CLI เปิดเผย | ค่าที่ไม่เปิดเผยเป็น `None`; fair scheduling ใช้ wall time (OD-012) |
| D-022 | Sandbox: bwrap + systemd user scope ต่อ attempt | คำสั่งของ agent และ checks ไม่มีเน็ต; Chat ไม่มี sandbox เลย (รันเป็นผู้ใช้ในโฟลเดอร์จริง; เหลือแค่ memory scope) เพราะ clone ทำให้ agent หาไฟล์ ignored/นอกโปรเจกต์ไม่เจอ (OD-021) |
| D-023 | Trust precedence: Runtime policy > ผู้ใช้ > repo instruction > agent message > web/tool content และ artifact | label ใน prompt ไม่ใช่ enforcement; settings ของ agent CLI ใน repo เป็น protected เสมอ; เปิดเว็บให้ agent ต่อโดยยอมรับความเสี่ยง; งานที่ค้างอยู่ใน OD-013 |
| D-024 | Adapter/agent รันเป็น child process ใน sandbox ของ attempt | ไม่มีระบบ plugin จากภายนอก (OD-014) |
| D-025 | Lifecycle/controls ตามที่ implement ใน Runtime | ช่องว่างกับ MVP Contract ที่รู้แล้วอยู่ใน OD-023 |
| D-026 | Local backend คือ Ollama บน loopback, โมเดลเริ่มต้น `qwen2.5-coder:7b`; local coding คงปิด | ประเมินใหม่เมื่อมีโมเดล/ฮาร์ดแวร์ที่ดีกว่า (OD-022, Phase 4) |
| D-027 | Protocol ภายในเป็น native schema; ทำ A2A bridge เมื่อมี external agent เท่านั้น | ต้องเพิ่ม schema_version/correlation id ใน event ก่อนทำ bridge (OD-005) |
| D-028 | ยังไม่สร้าง Context Broker | กลับมาดูเมื่อ prompt ของ Axon เป็นสัดส่วนสำคัญของ token ในงานจริง; เริ่มจาก deterministic Git/file retrieval (OD-009) |
| D-029 | Roles แบบ hybrid: ค่าเริ่มต้นใน config, เลือก agent/model/effort ต่องานได้, บทบาทมาจากชนิดงาน | ไม่สร้าง capability matching อัตโนมัติจนกว่าจะมีข้อมูล (OD-011) |
| D-030 | Remote ผ่าน Tailscale (`axon remote`) พร้อมรหัสผ่านเท่านั้น; Axon bind แค่ loopback | ห้ามเปิดออก internet สาธารณะ; token ต่อเครื่องและระดับสิทธิ์เป็นงานค้าง (OD-015) |
| D-031 | Session ต่อ attempt สำหรับงาน; ความต่อเนื่องมาจาก git snapshot และโน้ตใน prompt | งานที่ต้องคุยต่อเนื่องใช้ Chat (OD-016) |
| D-032 | ไม่สร้าง Team/Debate; ใช้ implement → review → revise ที่จำกัดรอบ | ถ้าสร้างในอนาคต ใช้ verifier + ผู้ใช้ตัดสิน ไม่ใช้ majority vote อย่างเดียว (OD-017) |
| D-033 | (พักไว้ รอ Tether จบ) แอปมือถือ native: Flutter, Android ก่อน, อยู่ใน `mobile/` ของ repo นี้; browser UI ยังอยู่ต่อ | ไม่ใช้ WebView/PWA/Capacitor; ใช้ API เดิมของ `axon/server.py` ผ่าน Tailscale; iOS รอ Mac/cloud build + Apple account ([MOBILE](MOBILE.md), แก้ OD-002) |
| D-034 | Claude กับ Codex ถามกันระหว่างรันได้ผ่าน MCP tool `ask_peer(question)`: เป็น task ชนิด `ask` ที่ read-only บน commit ที่ attempt เริ่ม (ไม่เห็นงานที่ยังไม่ snapshot) ผู้ถามรอคำตอบ ไม่เกิน `max_asks` (3) ต่องานและ `ask_timeout` (900 วินาที) ต่อคำถาม | ไม่ใช่ Debate (D-032 ยังอยู่): คำตอบเป็นข้อมูลให้ผู้ถามตัดสินเอง ไม่ใช่ verdict; ผู้ตอบถามต่อไม่ได้; ผู้ใช้ยังเป็นคนสั่ง review |
| D-035 | **Brainstorm** (`axon/brainstorm.py`): Claude กับ Codex วางแผนด้วยกันก่อนเขียนโค้ด: ถามผู้ใช้ให้ครบ → ร่างแผนแยกกัน (ไม่เห็นกัน) → เปรียบเทียบข้าม → `lead` รวมเป็นแผน JSON → อีกฝั่งตรวจ (ค้านได้ `rounds` รอบ) → ผู้ใช้กดสร้างงานเอง ทุกขั้นเป็น task ชนิด `plan` แบบอ่านอย่างเดียว | ห้ามเดา: ทุกขั้นถามผู้ใช้ได้ไม่จำกัด (`ask_user`) คำตอบเก็บใน Q&A log ของ brainstorm ไปอยู่ใน prompt ของทั้งสองฝั่ง; แผนสุดท้ายต้องมี `unknowns` ว่าง ไม่งั้นรวมใหม่ (สูงสุด 3 ครั้ง) ไม่ใช่ Debate (D-032) เพราะไม่มีโหวตและผู้ใช้ตัดสินข้อที่เห็นไม่ตรงกัน; model/effort แยกขั้นเบา (ถาม/ตรวจ) กับขั้นหนัก (ร่าง/เปรียบเทียบ/รวม) ใน `[brainstorm]` |
| D-036 | Axon ส่ง nudge **หนึ่งครั้งต่อ attempt** เข้า session interactive ที่นิ่งเกิน `IDLE_SECONDS` (90 วินาที) โดยยังไม่เรียก `report_result`/`ask_user`: พิมพ์ข้อความคงที่ (`runtime.NUDGE`) แล้วกด Enter | แก้ข้อ "Axon ไม่ฉีด keystroke" ของ OD-019 เฉพาะกรณีนี้: ข้อความคงที่ไม่มีเนื้อหาจากโมเดล และไม่ส่งถ้าหน้าจอเป็นคำถามขอสิทธิ์ (`can_nudge`); บันทึกเป็น event `nudge`; Brainstorm ใช้ภาษาอังกฤษสำหรับแผน/วิเคราะห์/spec (คำถามถึงผู้ใช้ใช้ภาษาของเป้าหมาย) |
| D-037 | แผนของ Brainstorm มีแหล่งข้อมูลจริงชุดเดียว (JSON) และ Axon สร้างมุมมองจากมัน: คน = การ์ด/CLI ที่เรนเดอร์จาก JSON, agent ผู้ทำ = **brief** Markdown ที่ `brainstorm.brief()` ประกอบจากฟิลด์ของงาน (`objective, context, files, steps, constraints, acceptance, report`) และเป็น `spec` ของ task ที่สร้าง ส่วนขั้นวิเคราะห์/เปรียบเทียบเป็นข้อความอิสระ | สิ่งที่ผู้ใช้อนุมัติ = สิ่งที่ agent ผู้ทำได้อ่านจริง (ไม่มี AI เขียนเอกสารสำหรับคนแยกอีกฉบับให้ไม่ตรงกัน); `acceptance` และ `steps` ต้องไม่ว่าง ไม่งั้น `parse_plan` ปฏิเสธและขั้นรวมต้องทำใหม่; แผนที่เก็บไว้ก่อนมีฟิลด์เหล่านี้ (มีแค่ `spec`) ยังแสดงและสร้างงานได้ |
| D-038 | **ด่านรวมคำถาม** ในขั้นถามของ Brainstorm: เมื่อ Claude และ Codex ถามพร้อมกัน Axon รันขั้น `gate` (task `plan` ของ lead ใช้ค่ารุ่นเบา `*_gate_*` แล้วถอยไป `*_light_*`) รวมคำถามที่ซ้ำเป็นฟอร์มเดียว ผู้ใช้ตอบครั้งเดียว (`answer_gate`) คำตอบเก็บใน Q&A log ครั้งเดียวและแจกกลับให้แต่ละ agent ตามข้อที่มันถาม | ซ้ำ = ตอบข้อหนึ่งแล้วอีกข้อได้คำตอบครบ; ไม่แน่ใจให้แยก (ถามซ้ำถูกกว่าทำคำถามหาย); `parse_gate` ตรวจว่าทุกคำถามเดิมถูกอ้างอย่างน้อยหนึ่งครั้ง; ผู้ถามคนแรกรอคนที่สองไม่เกิน `GATE_WAIT` (120 วินาที); ถ้ารวมไม่ได้ (ล้ม, ทำคำถามหาย 2 ครั้ง, หรือถามคนเดียว) แสดงคำถามของแต่ละ agent ตามเดิม ผู้ใช้ไม่ถูกบล็อก; ขั้นอื่นไม่มีด่านนี้ |
| D-039 | หลัง Brainstorm ถึง READY Axon เขียน **สองไฟล์จากแผน JSON ตัวเดียว** ที่ `data_dir()/plans/<id>/`: `PLAN.md` (คน) กับ `plan.json` (agent: JSON พร้อม `read_me`, `decisions` = คำตอบของผู้ใช้, `tasks` ที่มี `after`/`acceptance`) และ brief ของทุกงานมีหัวข้อ `## Plan` (เป้าหมาย รายการงานทั้งหมด คำตอบผู้ใช้) เพื่อให้ agent รู้ว่าตัวเองอยู่ตรงไหน; แผนเป็น **โครงใหญ่แบบ phase** (`design` + `phases[]`; phase เรียงต่อกัน) ถ้างานทั้งหมดไม่เกิน `PHASE_CAP` (25) งาน brainstorm เขียน task ให้ครบ ถ้าใหญ่กว่านั้นเขียนแค่ phase แล้วเว้น `tasks` ว่าง และเมื่อ phase ก่อนหน้าเสร็จครบ ผู้ใช้กด **Break into tasks** → lead ตัวเดียว (ใช้ model/effort ระดับเดียวกับขั้น merge) อ่านโค้ดปัจจุบัน + ผลสรุปของ phase ก่อน แล้วเขียน task ของ phase นั้นไม่เกิน 25 (ขั้น `expand`, ลองซ้ำได้ `MERGE_TRIES` ครั้ง ถ้าไม่ผ่านแผนเดิมไม่เสีย) แล้วผู้ใช้ตรวจและกด Start ทีละ phase; หน้า **Plans** เป็นกระดาน To do/In progress/Done/Stuck ที่คำนวณจาก task จริงที่แผนสร้าง ไม่เก็บสถานะซ้ำ; ตัดหน้าที่ซ้ำ: Overview รวมกับ Task board, Resources รวมเข้า Agents, ลบ Artifacts (หลักฐานอยู่ในหน้ารายละเอียดงานอยู่แล้ว); กด Start แล้ว Axon รัน checks ของโปรเจกต์บน HEAD ก่อน ถ้าแดงอยู่แล้วทุกงานจะล้มตาม จึงเตือนและให้ยืนยัน (`--force` / ถามในหน้า Plans) task หนึ่งรอได้หลายงาน (`after` เป็นลิสต์: งานแรกคือ `tasks.after` ที่เหลืออยู่ใน `tasks.needs`) เริ่มได้เมื่อทุกงานที่รอ COMPLETED และเริ่มจากผลของทั้งหมดที่ merge กัน (`git merge-tree`; ถ้าชนกันงานนั้น FAILED พร้อมชื่อไฟล์) งานที่ไม่มี `after` ใน phase จะต่อจากผลของทั้ง phase ก่อนหน้า (ไม่ต้อง integrate/promote ก่อน) phase แรกเริ่มจาก HEAD ณ ตอนกด Start ถ้า task ใน phase ล้ม/ถูกหยุด ปุ่ม **Retry phase** (`--approve --phase ID` ที่ phase ที่เริ่มแล้ว) สร้างใหม่เฉพาะงานที่ล้ม/ถูกหยุด งานที่เสร็จคงเดิม และ task ในแผนใส่ `checks` (ชุดย่อยของ checks ของโปรเจกต์) ได้ | ยังคงหลักของ D-037 (ไม่มี AI เขียนเอกสารคนแยกจนไม่ตรงกัน: ทั้งสองไฟล์ render จาก JSON เดียวกัน); เขียนไว้นอก project เพื่อไม่ทำให้ checkout สกปรก (`promote()` ปฏิเสธ tree ที่ไม่สะอาด); ไม่เก็บสถานะในไฟล์ เพราะ DB เป็นแหล่งจริงของ state งานอยู่แล้ว |

## ข้อเสนอที่ยังไม่ได้ล็อก

- ผู้ใช้เป็นผู้สั่ง push/merge/deploy ช่วงแรก; local commit ใน clone ของ attempt ยืนยันแล้วใน D-010 ส่วนการรวมงานยืนยันแล้วใน D-014
- เป้าหมายเดิมคือไม่บังคับ cloud API-key workflow; การเรียก local endpoint และ structured CLI protocol ยังใช้ได้ตาม draft เดิม หากต้องการห้าม interface เหล่านี้ด้วยต้องตัดสินแยก

ความสามารถจริงของแต่ละ backend ดูจากผล probe ใน [MVP Contract](MVP_CONTRACT.md) §2 ไม่ใช่จากคำตัดสินในเอกสารนี้
