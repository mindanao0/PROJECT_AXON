# Mobile app (D-033)

> **พักไว้ (2026-10-08):** รอ Tether (`~/code/Tether`) จบก่อน แล้วค่อยกลับมาทำต่อ เหตุผล: terminal/pairing/revoke/reconnect บนมือถือซ้ำกับ Tether T0-05 และ T2-01..T2-05 และ Tether เป็นทางเข้า terminal ที่รัน sudo ได้ซึ่ง Tailscale+Axon ทำแทนไม่ได้ ยังไม่สร้าง `mobile/` และยังไม่ลงชุดเครื่องมือ Flutter/Android ตอนกลับมา ให้ตัดสินใหม่ว่าหน้า board/approve ของ Axon จะเป็นหน้าเพิ่มในแอป Tether หรือแอปแยก และจะส่ง HTTP ผ่าน tunnel ของ Tether หรือเรียก `axon` CLI ผ่าน SSH เนื้อหาด้านล่างเป็นแผนเดิมก่อนพัก

> **เงื่อนไขกลับมาทำ (ผู้ใช้ตัดสิน 2026-10-08):** Tether Phase 2 ผ่านบน **Android จริง** ([PLAN.md](../../Tether/Tether/docs/PLAN.md) §7) คือ
> - ผ่าน Phase 0 (T0-04, T0-05, T0-07) และ Phase 1 (T1-01..T1-07 รวม relay ที่ deploy แล้ว)
> - T2-01..T2-06: pairing UI, เก็บ/ลบ key และหน้า host key ไม่ตรง, terminal + แถบปุ่ม + resize, new/resume/close tmux, เปลี่ยนเน็ต/background/reconnect, ใช้ Claude Code/Codex จริง
> - gate: ใช้ผ่านเน็ตมือถือ, ปิดแอปแล้วกลับ session เดิมได้, ไม่ส่งคำสั่งซ้ำ
>
> ไม่รอ iPhone/T0-06, Phase 3 (file browser) หรือ Phase 4; แต่ถ้าจะใช้ sudo จากมือถือประจำ ควรผ่าน T4-01/T4-02 (replay, key tampering, revoke ระหว่าง session) ก่อน

แอปมือถือ **native จริง** ไม่ใช่เว็บ, PWA หรือ WebView/Capacitor: Flutter, Android ก่อน, โค้ดอยู่ใน `mobile/` (ยังไม่สร้าง) ไม่แก้ browser UI เดิม

## ขอบเขต

แอปเป็น client ของ Axon บนเครื่องพัฒนา ไม่รัน agent เอง และใช้ API เดิมของ `axon/server.py` ทั้งหมด:

| ใช้ทำอะไร | Endpoint |
|---|---|
| ล็อกอิน (รหัสผ่านจาก `axon passwd`) | `POST /api/login` → cookie `axon_session_<port>` |
| Overview, board, activity (poll 1.5 วิ) | `GET /api/snapshot?cursor=N` |
| หน้า task | `GET /api/tasks/<id>` |
| add / approve / reject / input / stop / retry | `POST /api/command` (JSON) |
| Chat terminal | WebSocket `/api/chat/ws?session=…` (ส่ง `{"data":…}` / `{"resize":[cols,rows]}`) |
| แนบรูปใน Chat | `POST /api/chat/upload?session=…` |

เข้าผ่าน `https://<เครื่อง>.<tailnet>.ts.net` (`axon remote`, D-030) ต้องเปิด Tailscale บนมือถือ ไม่เปิด internet สาธารณะ

## สิ่งที่ native client ต้องจัดการเอง (server ไม่ต้องแก้ใน v0)

1. **Origin**: `boundary()` ปฏิเสธ POST/WebSocket ที่ไม่มี `Origin` ตรงกับ Host; client native ไม่ส่งให้เอง → ตั้ง header `Origin: https://<host>` เองทุก request และตอนต่อ WebSocket (dart:io ทำได้)
2. **Cookie**: เก็บ `Set-Cookie` จาก login แล้วส่งกลับเอง (cookie jar ไม่มีในตัว); session token เปลี่ยนทุกครั้งที่ server รีสตาร์ท → ได้ 401 ให้ล็อกอินใหม่
3. **Terminal**: ใช้ widget terminal ของ Flutter (เช่น `xterm` บน pub.dev — ตรวจ maintenance/เวอร์ชันก่อนล็อก) ต่อ WebSocket; แถบปุ่ม Esc/Tab/↑↓/Ctrl-C ทำเป็น widget เอง เหมือน `axon/web/app.js`

## งาน server ที่ต้องทำก่อนใช้ประจำ

- **token ต่อเครื่องที่เพิกถอนได้** (OD-015 ช่องว่างข้อ 1): แอปไม่ควรเก็บรหัสผ่านไว้ล็อกอินซ้ำ → `POST /api/devices` (ต้องล็อกอินก่อน) คืน token ต่อเครื่อง เก็บแบบ hash ใน `~/.config/axon/`, `axon devices rm` เพิกถอน, `boundary()` ยอม `Authorization: Bearer <device token>` โดยไม่ต้องมี Origin (ไม่ใช่ browser → ไม่มี CSRF) แอปเก็บ token ใน Android Keystore (`flutter_secure_storage`)
- **แจ้งเตือน** (เหตุผลหลักที่ D-015 เคยเว้นไว้): ต้องรู้เมื่อ agent รออนุมัติ/รอ input ตอนปิดแอปอยู่ ตัวเลือก: (ก) foreground service poll `/api/snapshot` ผ่าน Tailscale — ไม่พึ่ง Google, กินแบต; (ข) FCM — ต้องให้ server ส่งออกไป Google ซึ่งขัดกับหลัก "ไม่ออกนอก tailnet" **ยังไม่ตัดสิน** v1 เริ่มจาก (ก)

## ลำดับงาน

| M | ผลที่เห็น | หมายเหตุ |
|---|---|---|
| M0 | `flutter doctor` ผ่าน, รัน hello app บน emulator/เครื่องจริง | ตอนนี้เครื่องนี้ยังไม่มี flutter, Android SDK, adb (มีแค่ java) |
| M1 | ล็อกอิน + Overview/board แบบอ่านอย่างเดียว | ใช้รหัสผ่านไปก่อน |
| M2 | หน้า task + approve/reject/input/stop/retry + add task | `POST /api/command` |
| M3 | Chat terminal พร้อมแถบปุ่ม + แนบรูป | ส่วนเสี่ยงสุด ทำ spike ก่อน |
| M4 | device token (server + แอป) | แทนรหัสผ่านที่ M1 |
| M5 | แจ้งเตือน | ตัดสินตัวเลือกข้างบนก่อน |

iOS: โค้ด Dart ใช้ร่วมได้ แต่ build ต้องมี Mac หรือ cloud build และ Apple Developer account ($99/ปี; แบบฟรีแอปหมดอายุทุก 7 วัน) ยังไม่ทำ

## ทดสอบ

server ใช้ `tests/` เดิม; Flutter ใช้ `flutter test` กับ server ที่รัน runtime จำลอง (`ControlServer(Runtime())` แบบ `tests/test_server.py`) ไม่ใช้ quota ของ agent จริง
