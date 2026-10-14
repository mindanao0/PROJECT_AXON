# Axon Local GUI

สถานะ: **GUI foundation / simulation only** — ทำหน้าควบคุมและ state contract ที่ลองใช้งานได้ก่อนมี production Agent Runner ตาม D-012/D-013

ธีม: **Cybernetics ดำ–แดง** — โลโก้ AXON (`axon-wordmark.svg`) วาดเป็น SVG ตามสไตล์โลโก้อ้างอิงเดิม (ตัวหนาเหลี่ยม รอยแยก glitch แนวนอน เศษแดง) ใช้ทั้ง sidebar และ command masthead, พื้นดำลึก, แดงสด, circuit traces, กรอบ HUD และแสงแดง; สถานะ connection/mode/dispatch อ่านจาก runtime จริง วง HUD หมุนช้าและหยุดเมื่อ offline/pause หรือผู้ใช้เปิด reduced motion; asset ทั้งหมดอยู่ในโปรเจกต์ ไม่โหลด font หรือภาพจากภายนอก

ไม่ใช่รายงานว่า Phase 1 ผ่านแล้ว: ไม่มี provider CLI, sandbox, cgroup, workspace clone, MCP, local inference หรือ real verifier ใน implementation นี้ `fake-agent` ใน GUI เป็น in-process simulation ไม่ใช่ fake-agent CLI ที่มี edit/orphan/crash scenarios ใน Execution Design §6

## เปิดใช้งานบน Linux

ต้องมี Python 3.11 ขึ้นไป ไม่ต้องติดตั้ง Python dependencies, Node หรือ frontend build tool เพื่อเปิด GUI จาก source:

```bash
git clone https://github.com/mindanao0/PROJECT_AXON.git
cd PROJECT_AXON
python3 -m axon --sim   # simulation; ไม่ใส่ --sim = runtime จริง (ดู README)
```

ระบบเปิด browser พร้อม launch link ของ instance นั้น ถ้าเครื่องไม่เปิด browser อัตโนมัติ:

```bash
python3 -m axon --sim --no-browser
```

คัดลอก **link เต็มที่พิมพ์ใน terminal** ไปเปิดบน browser ของเครื่องเดียวกัน ห้ามแชร์ launch link เพราะมีสิทธิ์ควบคุม instance นั้นผ่าน token ใน fragment

เลือก port ได้ (โหมดจริง default 8765 จาก `[server] port`; simulation สุ่ม) แต่เลือก bind address ไม่ได้ (ล็อกเป็น `127.0.0.1`):

```bash
python3 -m axon --port 8765
```

ใช้ state สำหรับทดลองแยกจาก state ปกติ:

```bash
python3 -m axon --sim --state-dir ~/.local/state/axon-demo
```

Directory ต้องเป็นของผู้ใช้ปัจจุบันและ permission `0700`; path ที่ไม่ปลอดภัยจะถูกปฏิเสธ ไม่แก้ permission ของ directory เดิมอัตโนมัติ ข้อมูล default อยู่ใน `$XDG_STATE_HOME/axon` หรือ `~/.local/state/axon` เมื่อไม่ตั้งตัวแปร instance เดียวใช้ state dir ได้ครั้งละหนึ่งตัว

ถ้าต้องการติดตั้งคำสั่ง `axon` ใช้ virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
axon
```

ปิดด้วย Ctrl+C ใน terminal ที่รันอยู่ ข้อมูล task/event ยังอยู่ แต่ token จะเปลี่ยนทุกครั้งที่เปิด และ launch file จะถูกลบเมื่อปิดปกติ

## หน้าจอและวิธีใช้

### Operator controls

- **Ctrl+K / Cmd+K** หรือปุ่ม Command เปิด command palette: ค้นหาคำสั่ง, task title/ID/state และ project; ใช้ ↑/↓ เลือก, Enter เปิด และ Esc ปิด
- **Alt+N** เปิด New task และ **Alt+1…7** เปลี่ยนหน้าตามลำดับเมนู (Tasks, Plans, Brainstorm, Agent chat, Agents, Activity, Settings) คีย์ลัดเหล่านี้ไม่ทำงานขณะกรอกข้อมูลหรือมี dialog เปิดอยู่
- คลิก statistic tile เพื่อเปิดหน้า Tasks พร้อม task-group filter; selector แสดง filter ที่เลือก และเปลี่ยนกลับ All tasks ได้
- **Operator required** รวมงานรอ input/approval/review ใน project ที่เลือก เรียงตามเวลาที่อัปเดตเก่าสุดก่อน เปิด request/diff ทีละงานก่อนตอบหรืออนุมัติ
- Agent fleet ในโหมด real ใช้ provider/status/slot/cooldown ที่ runtime ส่งมาในหน้า Agents; ไม่สร้าง worker จำลองหรือสถานะ login เอง
- Completed แสดง progress จากจำนวนงานที่เสร็จ/งานทั้งหมด; footer แสดงเวลาท้องถิ่นและสถานะ sync โดยยืนยัน LIVE หลังรับ snapshot สำเร็จเท่านั้น ปุ่มคำสั่งที่ต้องเชื่อม runtime ถูกปิดเมื่อ offline


| หน้า | ใช้ทำอะไร |
| --- | --- |
| Control room (Tasks) | จำนวนงาน, งานรอผู้ใช้, task board พร้อมค้นหา/filter สถานะ/เลือก project, เปิดรายละเอียดงาน (หน้าแรก; เดิมแยกเป็น Overview กับ Task board ที่ซ้ำกัน) |
| Plans | (เฉพาะ real) ตามแผนจาก Brainstorm ทีละงาน แยกเป็น To do / In progress / Done / Stuck ตาม state ของ task จริง พร้อม progress `n / N done` (D-039) |
| Brainstorm | ถาม-ตอบและขั้นของการวางแผน (เฉพาะ real) |
| Agent chat | terminal จริง (เฉพาะ real) |
| Agents | provider, login, slot, cooldown, limit ที่เหลือ รวมถึง dispatch capacity และ usage 24 ชม. (เดิมแยกเป็นหน้า Resources) |
| Activity log | ดู event ที่ Runtime บันทึกพร้อม task/attempt และ cursor |
| Runtime settings | ดูขอบเขต local transport, recovery และความสามารถที่ยังไม่มี |

1. กด **New task** ใส่ชื่อ, description/acceptance, project และ scope ที่เป็น relative path เช่น `src/, tests/`
2. เลือก scenario แล้วสร้าง task ระบบเริ่ม QUEUED และ dispatch เมื่อไม่ pause และ fake slot ว่าง
3. คลิก card เพื่อดู task/attempt, activity, pending request, instruction history, artifacts และ attempt history
4. กด **+** ข้าง PROJECTS เพื่อสร้าง project จำลอง ไม่มีการอ่าน/เชื่อม repository ตามชื่อที่ใส่
5. งานใหม่ที่ description normalize และ scope ตรงกับงานเดิมใน project เดียวกันจะแสดงงานเดิม ไม่สร้างซ้ำ (ใช้ title/scenario ต่างกันอย่างเดียวไม่ทำให้เป็นงานใหม่)
6. **Start from completed task** เลือกงานที่เสร็จใน project เดียวกัน หรือกด **Continue from this task** ในรายละเอียดงาน เก็บ source task, attempt และสำเนา artifacts ของ attempt นั้น; source ที่ไม่เสร็จหรือ attempt เปลี่ยนแล้วถูกปฏิเสธ ยังไม่มีการส่งต่อระหว่าง provider หรือสร้าง Git ref
7. ในรายละเอียดงานเลือก Results, Code diff, Agent output, Prompt / instructions หรือ Attempts ผลเต็มคัดลอกได้; เมื่อ clipboard ใช้ไม่ได้จะมีช่องข้อความให้เลือกคัดลอกเอง

| Scenario | สิ่งที่ทดลองได้ |
| --- | --- |
| Successful result | RUNNING → VERIFY → COMPLETED; ใช้ fake verifier เท่านั้น |
| Ask for user input | WAITING_INPUT → ส่งคำตอบ → RUNNING |
| Wait for approval | WAITING_APPROVAL → Approve หรือ Reject; request ผูก attempt/payload และหมดอายุหลัง 10 นาที |
| Quota cooldown | WAITING_QUOTA 15 วินาที → QUEUED; ปล่อย fake slot; ไม่ใช้ quota จริง |
| Agent failure | FAILED; กด Retry เพื่อสร้าง attempt ใหม่ |
| Verification failure | เข้า VERIFY แล้ว FAILED; evidence มี fake exit code 1 |
| Long-running | ไม่จบเอง; ใช้ทดลอง Stop/Kill |

### ความหมายปุ่ม

- **Pause dispatch**: หยุดการเริ่มงานใหม่ งานจำลองที่กำลังทำยังเดินต่อ
- **Resume dispatch**: เปิดการเริ่มงานใหม่
- **Stop**: มีหน้าต่างยืนยันก่อนส่งคำสั่ง งาน active เข้า CANCELLING ก่อน จากนั้น simulation acknowledge แล้ว CANCELLED; queued/quota task ยกเลิกทันทีเพราะไม่มี worker active
- **Kill simulation**: มีหน้าต่างยืนยันก่อน revoke simulated attempt ไม่มี OS process ให้ kill และไม่ใช่หลักฐานว่า production process-tree kill ผ่านแล้ว หน้าต่างยืนยันจับ attempt ที่ผู้ใช้เห็นก่อนเปิด; ถ้า attempt เปลี่ยนแล้ว server ปฏิเสธคำสั่ง ไม่ส่งไปฆ่า attempt ใหม่
- **Retry as new attempt**: ใช้กับ FAILED/CANCELLED/BLOCKED; เก็บ attempt/artifact เดิมและเริ่ม attempt ใหม่
- **Save instruction**: บันทึก versioned guidance; simulated result ระบุ instruction version ไม่มี model รับข้อความจริง
- **Approve/Reject/Send answer**: ใช้กับ request และ attempt ที่หน้าจอเห็นเท่านั้น; payload เก่าหรือ request ที่แก้ไปแล้วถูกปฏิเสธ

ยังไม่มี Reassign, Rollback, dependency graph, diff ของ Git, Take over, real resource usage และ token budget จึงไม่แสดงปุ่มที่อ้างว่าทำงานเหล่านี้ได้

## Persistence และ reconnect

Core อยู่ใน `axon/core.py` แยกจาก UI/HTTP; SQLite transaction เดียวบันทึก snapshot และ event เมื่อคำสั่งสำเร็จ ข้อมูลอยู่ใน `control.sqlite3` ไม่เขียน config ลง repo ของ project

UI poll snapshot/event ทุก 1.5 วินาที; event ใช้ cursor และส่งครั้งละไม่เกิน 300 รายการเพื่อ backpressure snapshot ไม่ส่ง artifact body หรือ full event output; เมื่อเปิด task UI ขอ `/api/tasks/<task_id>` เพื่ออ่าน evidence และ output ของ task นั้น และจะขอใหม่เมื่อ `updated_at` เปลี่ยน UI แสดง event ล่าสุด 1,000 รายการ แต่ event เก่ายังอยู่ใน database การ disconnect browser ไม่ยกเลิก task และเมื่อเชื่อมใหม่ในหน้าเดิมจะอ่านต่อจาก cursor เดิม

ถ้า Runtime restart งานที่ active/รอ input/approval/quota จะเป็น BLOCKED และ revoke attempt เดิม ไม่ replay side effects หรือ resume จำลองเงียบ ๆ ผู้ใช้ต้อง Retry เอง งาน QUEUED ยังคงรอ dispatch ตาม pause state เดิม

เมื่อเปิด launch link ครั้งแรก UI ส่ง bearer ไป `POST /api/session` แล้วลบ bearer ออกจาก memory หลังสำเร็จ server ออก **HttpOnly, SameSite=Strict session cookie** แยกจาก launch token; cookie มี Path `/api/` และชื่อผูก port เพื่อไม่ชน instance อีก port ไม่มี token ใน localStorage/sessionStorage Refresh และเปิด tab ใหม่บน origin เดิมใช้ session ได้จน browser session สิ้นสุดหรือ Runtime restart (browser บางตัว restore session cookie เมื่อเปิดใหม่ แต่ cookie เดิมใช้กับ Runtime ที่ restart ไม่ได้) หลัง restart ให้เปิด launch link เต็มอีกครั้งจาก terminal หรือ `launch.url` ใน state dir ถ้า network connection ล้ม UI แสดง stale-state warning และปิดปุ่มควบคุม

## Local authorization boundary

- HTTP bind `127.0.0.1` เท่านั้น; เข้าจากเครื่องอื่นได้ทาง proxy บนเครื่องนี้ (`tailscale serve`, ดู `axon remote`) ซึ่งต้องตั้งรหัสผ่านก่อน (`axon passwd`) และ sign in ที่หน้า login: `POST /api/login` ตรวจ PBKDF2-SHA256 (600k รอบ) ทีละครั้ง ผิดแล้วหน่วง 1 วินาที สำเร็จได้ session cookie แบบเดียวกับ launch link (+`Secure` เมื่อผ่าน https)
- API ทั้งอ่านและเขียนต้องมี per-launch random bearer token หรือ browser session cookie ของ instance ปัจจุบัน; session bootstrap ต้องใช้ bearer และ exact Origin, cookie อย่างเดียว bootstrap ไม่ได้
- Host ต้องตรง `127.0.0.1:<port>`/`localhost:<port>` หรือชื่อใน `[server] hosts` (ที่ `axon remote` ใส่ให้); ป้องกัน DNS rebinding; ชื่อ remote ใช้ไม่ได้ถ้ายังไม่มีรหัสผ่าน
- POST ต้องมี exact same Origin และ JSON content type; ไม่มี permissive CORS
- ขนาด request ไม่เกิน 16 KiB; task/project/text มีขีดจำกัด
- Static assets เป็น allowlist และมี CSP, no-store, no-referrer, frame-ancestors none
- State dir `0700`, DB/launch file `0600`, advisory process lock ป้องกันสอง instance
- ไม่มี endpoint สำหรับ shell, file access, push, merge หรือ deploy; Agent chat (`/api/chat/ws`) เป็น WebSocket เข้า tmux session `axon-chat-*` ที่ agent รัน; chat ไม่มี sandbox (agent รันเป็นผู้ใช้ในโฟลเดอร์โปรเจกต์จริง) จึงต้องมี session + exact Origin เท่านั้น
- CSP อนุญาต inline style (xterm.js เขียน `<style>` เอง) แต่ script/connect/img ยังเป็น `self` เท่านั้น

Boundary นี้เป็น local single-user GUI foundation ไม่ได้พิสูจน์ production authentication ของ agent sockets เมื่อเพิ่ม sandbox/agent processes ต้องซ่อน control socket/transport จาก attempt และทำ authorization ตาม MVP Contract ห้ามเปิด remote ด้วยการแก้ bind addressเฉย ๆ

## รายการ UI ที่ปรับและขอบเขตที่ยังรอ runner จริง

| รายการ | รุ่นนี้ทำได้ / ข้อจำกัด |
| --- | --- |
| Diff และ policy ต่อไฟล์ | เตรียม viewer สำหรับ artifact `kind=diff`: full patch พร้อมรายการ `files` ที่มี `path`, `out_of_scope`, `protected`; unknown ไม่ถูกแสดงเป็น safe รุ่น simulation ไม่มี patch จริงหรือ REVIEW gate |
| ส่งต่องาน | เลือกงานต้นทางจาก dropdown และ Continue task ได้ใน simulation; Claude/Codex buttons disabled เพราะยังไม่มี adapters |
| เหตุผลรอคิว | snapshot ส่งเหตุผล paused, scope พร้อม task ที่บล็อก, slot เต็ม, ready และ cooldown; UI เปิด blocking task ได้ |
| Output / prompt | แสดง full artifacts `kind=agent_log` / `kind=prompt` เมื่อ Runtime ส่งมา; รุ่นนี้ไม่มีไฟล์เหล่านี้ จึงแสดง runtime messages และ task instructions พร้อมบอกว่าไม่ใช่ model output/prompt |
| ผลและ merge | Copy full result; Copy merge command แสดงเฉพาะ real-mode completed task ที่ส่ง `result_ref` เป็น `refs/axon/attempts/...` แบบไม่มี shell metacharacters ไม่มี endpoint execute/merge และ simulation ไม่สร้าง ref |
| Quota | Countdown ใน task/card และ fake-agent row; แยก task cooldown จาก provider cooldown จริงที่ยังไม่มีข้อมูล |
| Resources | Slot และ active attempts จาก snapshot; RAM เป็น Not measured ไม่แสดงค่าที่เดา |
| Add project | ซ่อนเมื่อ snapshot mode เป็น real; simulation ยังใช้ได้ |
| Stop/Kill | Native confirmation dialog, Cancel ไม่ส่ง command, ยึด observed attempt |
| Event | filter task/type และเปิด full `output` ถ้า event มี field นี้; simulation ยังไม่มี prepare/check stdout จริง |
| Real runtime controls | Banner เปลี่ยนตาม mode; REVIEW เปิด diff โดยตรงและแสดง approval; WAITING_INPUT แสดง input หรือแจ้งเมื่อ runtime ยังไม่ส่ง prompt; handoff เปิดเมื่อ `capabilities.handoff` ระบุพร้อมใช้งาน |
| Integration (real) | งานที่ COMPLETED มีปุ่ม **Add to integration branch**: Runtime รวมผลบน `refs/axon/integration/<project>` และรัน check บน commit ที่รวมแล้ว; แถบ **Fast-forward <branch>** ในหน้า Overview/Task board เปิดเมื่อมี check ผ่านบน commit นั้นพอดี, working tree สะอาด และ branch ไม่ขยับ พร้อม dialog ยืนยัน (ไม่ push, ไม่รัน hooks) ไม่มีในโหมด simulation; ทดสอบด้วย `tests/gui-real-smoke.cjs` |
| Model และ effort (real) | Settings มีแผง **Model and effort** ต่อ agent (Claude, Codex): ช่อง model (มีรายการแนะนำ รับ id อื่นที่รูปแบบถูกต้อง) และ effort ตามระดับที่ CLI นั้นรองรับ (Claude: low–max; Codex: low–ultra); ว่าง = ค่าเริ่มต้นของ CLI ใช้กับ attempt ที่เริ่มหลังบันทึก; ฟอร์มสร้างงานมีช่อง Model/Effort แบบเลือกได้เพื่อ override เฉพาะงานนั้น (ลำดับ: override ของงาน > การตั้งค่า > ค่าเริ่มต้นของ CLI); รายละเอียดงานแสดง model/effort ที่ใช้ CLI: `axon-cli agent-options [claude\|codex] [--model M] [--effort E]`, `axon-cli add --model --effort` |
| Dependency, check ต่องาน, reviewer, usage (real) | ฟอร์มสร้างงานมี **Start after task** (งานรอจน task นั้น COMPLETED แล้วเริ่มจากผลของมัน) และ **Verified by** (ติ๊ก check ที่ใช้ตรวจเฉพาะงานนี้ สำหรับงานขนานที่ check ต้องใช้ไฟล์ของอีกฝั่ง; integrate ยังรันทุก check); รายละเอียดงานมี Review with Claude / Codex และ Continue with Codex / Claude (เปิดเมื่อ agent นั้น login), แสดง Verified by / Starts after, และแท็บ Attempts แสดง model·effort กับ token/ราคาที่ CLI เปิดเผยต่อ attempt; แถบ integration มีปุ่มรีวิวทั้งสอง agent; หน้า **Resources** มีตาราง Usage 24 ชั่วโมงต่อ agent × kind (ฟิลด์ที่ CLI ไม่เปิดเผยเป็น `-` ไม่ใช่ 0) |
| Rollback, review ของ integration, revision, dependency (real) | แถบ integration มี **Discard** (ลบ integration branch; task ยัง COMPLETED) และ **Review with Claude** เมื่อ project ตั้ง `require_review` และ commit รวมยังไม่ได้รับ approve; งานที่ COMPLETED และถูกรีวิวว่า `changes` มี **Revise from review** (จำกัดรอบด้วย `limits.review_rounds`); งานที่รอ dependency แสดงเหตุผล `Waiting for task N` ใน queue reasons; สร้าง dependency ผ่าน CLI `add --after` หรือ bridge `after_task_id` (ยังไม่มีช่องในฟอร์ม) |
| Provider/resource/settings | Agents อ่าน `providers` และ `cooldown_until`; Resources อ่าน `attempt.memory_bytes` หรือ `resources.attempt_memory_bytes`; Settings อ่าน `settings.editable/items` และส่ง `update_settings` เมื่อ runtime รองรับ |
| Project setup | Add project เปิดใน real mode พร้อม path field และส่ง `create_project`; Runtime เป็นผู้ตรวจสิทธิ์และจัดเก็บ path |
| Attention | Tab title แสดงจำนวน pending requests; browser notification เป็น opt-in ใช้เมื่อแท็บอยู่เบื้องหลังและยังเปิดอยู่ ไม่ทำ background/service-worker notifications และบาง mobile browser ไม่รองรับ |
| Refresh | HttpOnly session cookie; Runtime restart หมุนทั้ง bearer/session และต้องเปิด launch link ใหม่ |

Task board แสดง 12 cards ต่อ column ก่อนและมี Show more; Activity แสดง 100 events ก่อน (ถือไว้ไม่เกิน 1,000) เพื่อลดจำนวน DOM พร้อมกัน หน้าจอมือถือมี navigation แบบเลื่อนแนวนอน, responsive panels, touch targets, skip link, live announcements และ task-evidence tabs ใช้ arrow-key navigation. ยังไม่ได้ตรวจ rendering, keyboard/screen-reader กับ browser จริง หรือทำ performance benchmark ของ task จำนวนมาก. Runtime รุ่นนี้ยังเป็น simulation จึงไม่มี agent log, provider prompt, real cgroup samples, real handoff หรือ config writer; UI จะแสดง unavailable/error ตามความสามารถที่ runtime รายงานและไม่สร้างค่า telemetry เอง

## โหมด real (`axon`, ค่าเริ่มต้น)

GUI เดียวกัน แต่ขับ runtime จริงผ่าน `axon/bridge.py` (interface `snapshot` / `task_detail` / `command` เดียวกับ simulation) งานรันใน sandbox (bwrap + cgroup) บน clone ของ project ผลลง `refs/axon/attempts/*` ไม่มี endpoint ที่ merge/push

| ส่วนของ UI | ข้อมูลจริงที่ bridge ส่ง |
| --- | --- |
| Poll (`/api/snapshot`) | task และ artifact เฉพาะ metadata (ชื่อ/kind/hash) ไม่มีเนื้อหา; `updated_at` ของ task ขยับเมื่อมี event ใหม่หรือ agent เขียน output (งานที่วิ่งอยู่จึงอัปเดต Agent output สด); งาน RUNNING มี `running_since`/`last_output` ให้การ์ดแสดงเวลาที่วิ่งและเงียบไปนานเท่าไร |
| Task evidence (`/api/tasks/<id>`) | full patch (`git diff base head` ตัดที่ 200,000 ตัวอักษร) พร้อม `files[]` แยก `out_of_scope`/`protected`; `agent.log` (ท้าย 30,000 ไบต์) และ prompt จริงของ attempt ล่าสุด (redact credential แล้ว); output เต็มของ check/prepare |
| Agents | `providers[]` พร้อมสถานะ login, slot และ `cooldown_until` จาก quota จริง |
| Resources | slot ที่ใช้/ทั้งหมด และ `memory_bytes` ของ attempt ที่กำลังรัน อ่านจาก `memory.current` ของ cgroup |
| Settings | แก้ slot ต่อ agent และ attempt timeout ได้ (เขียน `~/.config/axon/config.toml`; จำนวน slot ของ checks ต้อง restart) |
| Add project | ชื่อ + path ที่เป็นรากของ Git repo; สร้าง `~/.config/axon/projects/<ชื่อ>.toml` โดย **ยังไม่มี check** ต้องเพิ่มเองในไฟล์ ไม่งั้นงานที่จบไม่ถูก verify ด้วยอะไรเลย |
| Review with Claude | สร้าง **review task แบบอ่านอย่างเดียว** บน commit ผลพอดี: reviewer เห็น requirement, diff ที่ไม่เปลี่ยนแปลง และผล check ของ Runtime (ไม่เห็นบันทึกของ implementer) ใช้ tool แค่ Read/Glob/Grep; ถ้า reviewer แก้ไฟล์ verdict เป็นโมฆะ; verdict (approve / changes requested) แสดงในส่วน Reviews ของงานที่ถูกรีวิว; เปิดเมื่อ claude login |
| Continue with Codex | สร้างงานใหม่ต่อจาก commit ผลของงานต้นทาง; เปิดเมื่อ codex login ใน agent home ของ Axon |
| REVIEW | ไม่มีคำถามแยก UI เปิด diff ให้ตรวจแล้ว Approve/Reject (ผูกกับ attempt ที่เห็น) |
| Stop/Kill | `capabilities.controls.graceful_stop = false`: ฆ่า process tree ทันที UI จึงแสดง "Terminate attempt" |
| Apply to my folder | `git apply` ผลของงาน (`base..head`) ลง working tree ของ project แบบ uncommitted; all-or-nothing: ถ้างานของคุณแก้บรรทัดเดียวกันจะไม่เขียนอะไร; บันทึก event `applied` (`auto_apply = true` ในไฟล์ project = ทำเองหลังผ่าน checks) |
| Brainstorm | (เฉพาะโหมด real) ฟอร์มเริ่ม: โปรเจกต์ เป้าหมาย lead/other และ model/effort ของแต่ละฝั่ง (ปุ่มเติมค่าแนะนำ); การ์ดต่อ brainstorm แสดงขั้นปัจจุบัน คำถามจาก agent พร้อมช่องตอบ/ตัวเลือก (ตอบด้วย action `answer` ของ task นั้น) คำตอบที่ผ่านมา และปุ่ม **Stop** / **Review the plan** (action `brainstorm_start`, `brainstorm_stop`; snapshot มี `brainstorms`) |
| Plans | (เฉพาะโหมด real) เมื่อ brainstorm ถึง READY Axon เขียน `PLAN.md` (ให้คนอ่าน) กับ `plan.json` (ให้ agent อ่าน) ที่ `~/.local/share/axon/plans/<id>/` จาก JSON ของแผนตัวเดียวกัน หน้านี้แสดงเส้นทางไฟล์ ข้อที่เห็นไม่ตรงกัน ความเสี่ยง ข้อค้านของผู้ตรวจ แต่ละ phase มีปุ่ม **Break phase into tasks** (`brainstorm_expand`; ให้ lead เขียน task ของ phase นั้นหลัง phase ก่อนหน้าเสร็จ) และ **Start phase: create these N tasks** (`brainstorm_create_tasks` + `phase`) แล้วเป็นกระดาน 4 ช่องตาม state ของ task จริง (CLI: `axon brainstorm ID --expand [PHASE]`, `--approve [--phase PHASE]`) แต่ละการ์ดกาง "Done when" และ brief ที่ agent ได้รับได้ ก่อนสร้าง task Axon รัน checks บน HEAD ของโปรเจกต์ ถ้าแดงอยู่แล้วจะถามก่อนว่าจะเริ่มต่อไหม (`force`; CLI `--force`) task ที่ระบุ `after` หลายงานเริ่มจากผลของทุกงานที่รวมกัน และงานที่ไม่มี `after` ใน phase จะต่อจากผลของทั้ง phase ก่อนหน้า phase ที่เริ่มแล้วแต่มีงานล้ม/ถูกหยุดจะมีปุ่ม **Retry phase** ที่สร้างใหม่เฉพาะงานเหล่านั้น (พร้อมงานที่ยังรองานนั้นอยู่) และ phase ที่เสร็จครบมีปุ่ม **Integrate phase** (`brainstorm_integrate`) ที่ใส่ผลลง integration branch ตามลำดับ (ยัง promote เอง) |
| คำถามที่รวมจากสองฝั่ง | ในขั้นถามของ Brainstorm ถ้า Claude และ Codex ถามพร้อมกัน หน้าจอแสดง "Collecting questions …" ระหว่างรวม (ไม่เกิน 120 วินาทีที่รอฝั่งที่ช้า) แล้วเป็นฟอร์มเดียว แต่ละข้อกางดูถ้อยคำเดิมของแต่ละฝั่งได้ ตอบครั้งเดียว (`brainstorm_answer`) หรือ `axon brainstorm ID --answer` |
| คำถามหลายข้อจาก agent | `ask_user` ส่ง `questions` ได้ครั้งละหลายข้อ (สูงสุด 8) ฟอร์มแสดงทีละข้อพร้อมปุ่มตัวเลือกของข้อนั้นและช่องพิมพ์เอง ต้องตอบทุกข้อแล้วกด Send all answers ครั้งเดียว ใช้ทั้งในหน้า Brainstorm และกล่อง Your input is needed ของ task |
| Agent chat | terminal จริง (xterm.js ที่โหลดเมื่อเปิดหน้า chat) ต่อ WebSocket กับ `tmux attach` บน pty; เลือก Claude Code, Codex หรือ Shell (bash ในโฟลเดอร์โปรเจกต์); ขนาดตามหน้าจอ, wheel/ปัดนิ้ว/ปุ่ม Scroll ▲▼ เลื่อนย้อน, ลากเลือก = copy ลง clipboard (OSC 52 จาก tmux), Ctrl+Shift+V = paste, ปุ่ม Esc/Tab/↑↓/Ctrl-C สำหรับมือถือ; วาง/ลากรูปเพื่อแนบ |

ข้อจำกัด: adapter ของ Codex/Claude ยังไม่ผ่าน probe จริง; `gui-smoke.cjs` แก้ selector/ข้อความที่ UI เปลี่ยนไปแล้วและผ่านบน Chromium headless (2026-10-06, โหมด simulation เท่านั้น; ยังไม่ครอบคลุมโหมด real)

## ทดสอบ

Core/transport/startup tests ใช้ standard library:

```bash
python3 -m unittest discover -s tests -v
node --check axon/web/app.js
node tests/test-ui.cjs
```

ตรวจ packaging:

```bash
python3 -m pip install .
axon --help
```

Browser integration test เป็น optional dev dependency ต้องใช้ Node 18+ และ Playwright พร้อม Chromium; ติดตั้งไว้นอก repo ได้:

```bash
npm install --prefix /tmp/axon-browser-check playwright
/tmp/axon-browser-check/node_modules/.bin/playwright install chromium
NODE_PATH=/tmp/axon-browser-check/node_modules node tests/gui-smoke.cjs
```

Test นี้เปิด instance ด้วย temp state ของตัวเองแล้วทดสอบ reload/session, approval/input/stop/retry/kill และ confirmation cancellation, artifacts, search, projects, escaping, mobile form และ disconnect; ไม่แตะ state ปกติหรือ CLI account จริง `AXON_SCREENSHOT=/absolute/path/control-room.png` เป็น optional screenshot output

GitHub Actions รัน unittest, JS syntax, pure UI rendering/control checks และ package installation บน Python 3.11/3.12/3.13; ไม่ได้รัน browser test หรือ provider probes

ผลตรวจใน workspace วันที่ 2026-10-06: unittest 21 กรณีผ่าน, JS syntax และ pure UI rendering/control checks ผ่าน (full patch/result escaping, classification labels, captured confirmation/source attempt, Cancel ไม่ส่ง command) รุ่นก่อนตรวจ package installation ผ่านแล้ว; รุ่นนี้เปลี่ยน web assets และ stdlib code โดยไม่มี dependency ใหม่ Browser test **ยังไม่ยืนยัน** ตามที่ผู้ใช้เลือกข้าม localhost/browser check ไม่มีการอ้างว่า UI rendering/mobile interaction, accessibility หรือ performance ผ่านแล้ว

## ขั้นต่อไปที่ต้องทำก่อนใช้ AI จริง

1. ทำ fake-agent CLI + adapter interface, lease/action reconciliation และ full acceptance scenarios
2. เชื่อม project TOML config, isolated attempt clone, sandbox, cgroup และ checks
3. พิสูจน์ Stop/Kill กับ process tree รวม orphan; scope enforcement และ secret redaction
4. เปลี่ยน simulation model เป็น Runtime commands/snapshots ที่ authenticated ตามสัญญาเดิม
5. ทำ Codex/Claude/local backend probes ตาม Execution Design §10 หลัง fake runner ผ่าน
6. เพิ่ม immutable Git diff, exact-commit verifier evidence และ UI controls ที่ runner รองรับ

ไม่มีการใช้ provider quota หรือแก้ไฟล์ของ project จริง เพื่อสร้าง GUI รุ่นนี้
