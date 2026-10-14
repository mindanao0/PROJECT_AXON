# Axon

ระบบกลางสำหรับให้ AI หลายตัวทำงานเป็นทีมในหลายโปรเจกต์ โดยมีเป้าหมายหลักคือให้ ChatGPT/Codex, Claude Code และ Local LLM สามารถคุย วิเคราะห์ แบ่งงาน ตรวจงาน และส่งผลลัพธ์หากันได้โดยไม่ต้องใช้ไฟล์ handoff เป็นช่องทางหลัก

> สถานะ: runtime จริงใช้งานได้ (sandbox bwrap + cgroup, fake/claude/codex/local agent, integration branch) ผ่าน `axon` ทั้ง CLI และ GUI; adapter ของ claude/codex ยังไม่ผ่าน probe เต็มชุด

## เริ่มใช้งาน

ต้องใช้ Linux + Python 3.11 ขึ้นไป ไม่มี dependency เพิ่ม ติดตั้งครั้งเดียวแล้วพิมพ์ `axon` ได้จากทุก folder:

```bash
python3 -m pip install --user -e ~/code/PROJECT_AXON
```

ใช้งานประจำ (อยู่ใน folder ของ repo ไม่ต้องใส่ `-p`):

```bash
cd ~/code/<project ของคุณ>
axon init                          # ทำ repo นี้เป็น project (ใส่คำสั่ง test ใต้ [checks] ในไฟล์ที่มันบอก)
axon doctor                        # เช็ค sandbox, login ของ agent และ checks ก่อนใช้จริง
axon add "แก้ error ตอน password ว่าง" -f   # สั่งสั้นๆ ได้; -f = ดู agent ทำงานสด (default agent: claude)
axon ls                            # งานที่วิ่งอยู่บอกว่าวิ่งมานานเท่าไร และ output ล่าสุดกี่วินาทีก่อน
axon apply 12                      # เอาผลงานลง folder จริงของ project (uncommitted, ทับงานคุณไม่ได้)
axon chat                          # คุยกับ claude ในโฟลเดอร์โปรเจกต์ (tmux, ไม่มี sandbox)
axon brainstorm "เป้าหมาย"         # claude กับ codex วางแผนด้วยกัน (ถามคุณก่อน) แล้ว axon brainstorm ID --approve เพื่อสร้างงาน
axon                               # เปิด GUI (ถ้ารันอยู่แล้วจะเปิดตัวเดิม)
```

- ผลงานยังเข้า `refs/axon/attempts/*` เหมือนเดิม และเลือกลง folder จริงได้: ปุ่ม **Apply to my folder** ใน GUI, `axon apply ID` หรือใส่ `auto_apply = true` ในไฟล์ project ให้ลงเองทุกงานที่ผ่าน checks; ถ้าคุณแก้บรรทัดเดียวกันอยู่ มันจะไม่เขียนอะไรเลย
- **Brainstorm** (หน้า Brainstorm หรือ `axon brainstorm`): Claude กับ Codex ถามคุณให้ครบ (ห้ามเดา) ร่างแผนแยกกัน เทียบกัน รวมเป็นแผนเดียว และให้อีกฝั่งตรวจ เมื่อแผนพร้อม Axon เขียน `PLAN.md` (ให้คนอ่าน) กับ `plan.json` (ให้ agent อ่าน) จากแผนเดียวกัน แผนใหญ่แบ่งเป็น phase (เกิน 25 งานจะยังไม่เขียน task: กด Break into tasks ทีละ phase เมื่อ phase ก่อนเสร็จ ให้ lead เขียนจากโค้ดและผลจริง) แล้วหน้า **Plans** เป็นกระดานตามงานตามแผนว่าอะไรรอ/กำลังทำ/เสร็จแล้ว งานจริงเกิดเมื่อคุณกดสร้างเท่านั้น (ถ้า checks ของโปรเจกต์แดงอยู่แล้ว Axon จะถามก่อน; phase ที่มีงานล้มกด Retry ทำเฉพาะงานนั้นซ้ำได้ พร้อมงานที่รองานนั้นอยู่) ตั้ง model/effort แยกขั้นเบา/หนักได้ในส่วน `[brainstorm]` ของ config
- Agent chat ใน GUI เป็น terminal จริง (xterm.js ต่อ WebSocket เข้า tmux) พิมพ์แล้วเห็นทันที สีและเมนูเหมือน terminal ปุ่ม Esc/Tab/↑↓/Ctrl-C มีให้กดบนมือถือ
- Chat ของ claude/codex ใช้ `~/.claude`, `~/.claude.json`, `~/.codex` ของคุณเอง (login, settings และประวัติชุดเดียวกับที่ใช้นอก Axon; **chat ไม่มี sandbox**: agent รันเป็นคุณในโฟลเดอร์โปรเจกต์จริง เห็นและแก้ไฟล์เดียวกับ terminal ปกติ รวมถึง home, credential และ git push; จำกัดแค่หน่วยความจำ `chat_memory` ผ่าน systemd scope) `/resume` จึงเห็น session เดิมของโปรเจกต์ ส่วนงาน (task) ยังใช้ home แยกของ Axon
- Agent chat มีตัวเลือก **Shell**: bash ธรรมดาในโฟลเดอร์โปรเจกต์ (home จริงของคุณ, มีเน็ต) ใช้ได้เหมือน terminal ปกติ: ปุ่มทุกปุ่ม สี resize, ลากเลือกข้อความ = copy ลง clipboard, **Ctrl+Shift+V** = paste (Ctrl+V ส่งให้โปรแกรมเหมือน terminal บน Linux), wheel หรือปัดนิ้วบนจอ/ปุ่ม Scroll ▲▼ เลื่อนย้อน
- Agent ค้นเว็บและอ่านหน้าเว็บได้ (Claude: WebSearch/WebFetch, Codex: `--search`) แต่คำสั่งที่มันรันและ checks ยังไม่มีเน็ต ปิดได้ด้วย `[agents] web = false` ใน `~/.config/axon/config.toml`
- แก้ไฟล์นอก project: ใส่ใน `~/.config/axon/projects/<ชื่อ>.toml`

  ```toml
  [sandbox]
  rw = ["~/notes", "/data/shared"]   # agent แก้ได้ตรงๆ (ไม่ผ่าน diff/review และ Axon ย้อนไม่ได้)
  ```

  ใช้ได้ทั้งงานและ chat; ห้าม home ทั้งก้อน, state ของ Axon, ตัว repo เอง และ folder credential เช่น `~/.ssh`
- Agent fleet (หน้า Agents) แสดง limit ที่เหลือของ subscription ช่วง 5 ชม. และรายสัปดาห์ของ Claude/Codex เป็น % (provider ไม่บอกเป็นจำนวน token): Claude อ่านสดทุกนาทีขณะ login ของมันยังไม่หมดอายุ (อายุ 8 ชม. หลัง Claude รันครั้งล่าสุด) นอกนั้นแสดงค่าล่าสุด; Codex เป็นค่าหลัง turn ล่าสุดที่รันผ่าน Axon
- งานที่กำลังวิ่ง: การ์ดและหน้า task บอก “running 3m · last output 5s ago” และเปิดแท็บ Agent output ให้เองซึ่งอัปเดตสด; เงียบเกิน 5 นาทีจะเตือนให้เข้าไปดู

### ให้รันตลอด (ทำเครื่องนี้เป็น server)

```bash
axon service install       # systemd user service: GUI + runner อยู่ที่ http://127.0.0.1:8765 ไม่ต้องเปิด terminal ค้าง
loginctl enable-linger      # ครั้งเดียว: รันต่อหลัง logout และเริ่มเองตอนเปิดเครื่อง
journalctl --user -u axon -f   # ดู log;  axon service remove = เอาออก
```

### เข้าจากเครื่องอื่น / มือถือ ต่าง network ได้

ใช้ Tailscale (เครื่องนี้กับ iPhone อยู่ใน tailnet เดียวกันแล้ว) ไม่เปิดสู่ internet สาธารณะ:

```bash
axon passwd    # ตั้งรหัสผ่านหน้า login (ต้องมีก่อนเปิด remote)
axon remote    # tailscale serve → https://<ชื่อเครื่อง>.<tailnet>.ts.net ; axon remote --off = ปิด
```

ครั้งแรก `tailscale serve` อาจขอให้เปิด HTTPS ของ tailnet (มันพิมพ์ลิงก์ให้) หรือบอก access denied ให้รัน `sudo tailscale set --operator=$USER` ครั้งเดียว Axon ยัง bind แค่ `127.0.0.1` เสมอ; ชื่อ remote ใช้ได้เฉพาะเมื่อมีรหัสผ่าน

### Agent ที่ใช้ได้

`fake` ใช้ทดสอบได้ทันทีโดยไม่ใช้ quota ส่วน `codex` / `claude` ต้อง login agent home ของ Axon ก่อน (แยกจาก login ปกติ; `axon doctor` บอกว่ายังขาดอะไร):

```bash
CLAUDE_CONFIG_DIR=~/.local/share/axon/agents/claude claude auth login
CODEX_HOME=~/.local/share/axon/agents/codex codex login --device-auth
```

`axon --sim` เปิด GUI แบบ simulation (fake agent ในหน่วยความจำ ไม่แตะ repo) สำหรับลอง controls; `axon -h` ดูคำสั่งทั้งหมด (`axon-cli` ยังใช้ได้เหมือน `axon`)

วิธีใช้ controls ใน GUI, authentication, persistence และข้อจำกัด: [Local GUI Guide](docs/GUI.md)

## ขอบเขต MVP ที่ยืนยันแล้ว

- เริ่มจาก CLI/session ที่ Runtime จัดการ ไม่เชื่อมแชทเดิมบนเว็บใน MVP
- Linux first
- Coding agent อ่าน–แก้โค้ด–รันทดสอบได้ภายใน assigned workspace ตามสิทธิ์ที่บังคับใช้จริง
- Local LLM เริ่มจากสรุป context และวิเคราะห์ log; เพิ่ม coding หลัง Agent Runner ผ่านการทดสอบและอนุญาตบทบาทนั้น
- UI bind แค่ `127.0.0.1`; เข้าจากเครื่องอื่นผ่าน `tailscale serve` + รหัสผ่าน (`axon remote`)
- ผู้ใช้คนเดียว, หลาย project, ใช้ subscription ของ Claude/Codex ที่ผู้ใช้มี
- เป้าหมายหลัก: แบ่งงานชัด ไม่ทับกัน ไม่ทำซ้ำ และแบ่งทรัพยากรเครื่อง

ดู [Confirmed Decisions](docs/DECISIONS.md), [MVP Contract](docs/MVP_CONTRACT.md) และ [Execution Design](docs/EXECUTION_DESIGN.md) สำหรับขอบเขต เกณฑ์ผ่าน และการออกแบบที่ implement ได้

## เป้าหมาย

- ใช้งานได้กับหลาย project ไม่ผูกกับ project ใด project หนึ่ง
- เชื่อม Cloud coding agents ผ่าน account/CLI ที่รองรับ โดยไม่บังคับให้ผู้ใช้จัดการ API key เอง
- รองรับ Local LLM เช่น Ollama / llama.cpp / LM Studio หรือ adapter อื่น
- ให้ agent คุยกันแบบมีโครงสร้าง ไม่ใช่แชร์ transcript ทั้งหมด
- ให้ agent delegate, critique, review และแบ่งงานกันได้ (Claude กับ Codex ถามกันระหว่างรันได้ด้วย `ask_peer`)
- มี UI สำหรับดูสถานะ ควบคุม หยุด อนุมัติ ปฏิเสธ และเข้าแทรกแซง
- ลด token/context ที่ส่งซ้ำโดยมี Context Broker และ Artifact references
- แยก workspace ของ agent เพื่อลดการแก้ไฟล์ชนกัน
- มี verifier, policy และ audit trail เพื่อไม่ให้ “AI เห็นตรงกัน” เท่ากับ “ถูกต้อง”

## แนวคิดหลัก

```text
                         Control UI
                            |
                    +-------v-------+
                    |  Team Runtime |
                    |---------------|
                    | Supervisor    |
                    | Scheduler     |
                    | Task Engine   |
                    | Context Broker|
                    | Policy Engine |
                    | Event Store   |
                    | Merge Manager |
                    +-------+-------+
                            |
                  Internal Agent Bus
              +-------------+-------------+
              |             |             |
              v             v             v
          Codex Adapter  Claude Adapter  Local Adapter
              |             |             |
          Codex CLI     Claude Code   Ollama/llama.cpp
              |             |             |
           Worktree A    Worktree B    Worktree C
              +-------------+-------------+
                            |
                         Git Repo
```

## Protocol boundary

- **Agent ↔ Agent:** ใช้ protocol/message model ของ Runtime เอง โดยสามารถออกแบบให้สอดคล้องกับแนวคิด A2A เช่น task, message, artifact, capability และ streaming
- **Agent ↔ Tool/Data:** ใช้ MCP ได้เมื่อเหมาะสม
- **Runtime ↔ Agent implementation:** ใช้ Adapter เพื่อครอบ CLI, local endpoint หรือ backend อื่น

ไม่ควรบังคับให้ Codex/Claude “พูด A2A โดยตรง” เพราะ CLI แต่ละตัวมี lifecycle และ interface ต่างกัน Runtime ควรเป็นตัว normalize ความต่างเหล่านั้น

## เอกสาร

- [Confirmed Decisions](docs/DECISIONS.md)
- [MVP Contract / Acceptance Criteria](docs/MVP_CONTRACT.md)
- [Execution Design](docs/EXECUTION_DESIGN.md)
- [Architecture Draft](docs/ARCHITECTURE_DRAFT.md)
- [Open Decisions](docs/OPEN_DECISIONS.md)
- [Initial Roadmap](docs/ROADMAP.md)

## หลักการที่ยังยึดไว้

1. Core แยกจาก UI
2. Agent เปลี่ยน/เพิ่มได้ผ่าน Adapter
3. Chat ไม่ใช่ source of truth ของ task
4. Code ใช้ Git เป็น source of truth
5. Event log ใช้สำหรับ audit/recovery แต่ไม่ส่งกลับเข้า model ทั้งหมด
6. งานสำคัญต้องผ่าน verifier/test ไม่ใช่ใช้เสียงข้างมากของ AI
7. ผู้ใช้สามารถ interrupt/override ระบบได้เสมอ
8. Default ควรประหยัด context และ token
