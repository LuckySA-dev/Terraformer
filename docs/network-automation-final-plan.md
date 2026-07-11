# Network Automation Playground — Final Product & Implementation Plan

> Version: 3.0 Final  
> Updated: 2026-07-11  
> Deployment: Local self-hosted  
> Initial scale: 1–50 devices  
> Initial vendors: Cisco IOS/IOS-XE, followed by Juniper Junos  
> User model: Single-user

---

## 1. Product Definition

Network Automation Playground คือเครื่องมือ Local สำหรับค้นหา มองเห็น ตรวจสอบ และตั้งค่าอุปกรณ์ Network จริงผ่าน Playground แบบ Visual โดยไม่ได้จำลองอุปกรณ์ขึ้นมาแทนอุปกรณ์จริง

ระบบเป็น Control Workbench ระหว่างผู้ใช้กับ Router, Switch และอุปกรณ์ใน Management Network เดียวกัน มี 3 วิธีทำงานหลัก:

1. **Manual Terminal** — เข้า CLI ของอุปกรณ์จริงผ่าน Web Terminal
2. **Guided Configuration** — ตั้งค่าผ่าน Wizard ที่สร้าง Change Plan ให้ตรวจสอบ
3. **AI Assistant** — ใช้โมเดลที่ผู้ใช้เลือกเพื่ออธิบาย วิเคราะห์ หรือสร้าง Change Plan

ทุกการเปลี่ยนแปลงจาก Wizard หรือ AI ต้องผ่าน Preview, Diff, Backup และการยืนยันก่อน Apply เสมอ

### Product positioning

- Local-first Network Automation Workbench
- ใช้กับ Lab, Small Office, Training Environment และ Management Network ขนาดเล็ก
- ควบคุมอุปกรณ์จริง ไม่ใช่ Packet Tracer replacement
- AI เป็น Model Gateway และผู้ช่วย ไม่ใช่ผู้ควบคุมระบบอัตโนมัติ
- Core network features ต้องทำงานได้แม้ไม่มี AI Provider

### Non-goals

- Public SaaS, Live Service หรือ Multi-tenant
- Multi-user collaboration, RBAC, OAuth, LDAP หรือ SSO
- AWS/GCP deployment และ High Availability
- ISP scale หรือการรับประกัน 500+ devices
- รองรับทุก Vendor ตั้งแต่รุ่นแรก
- Autonomous AI ที่ Apply Config เอง
- Universal Auto-Rollback บนอุปกรณ์ทุกชนิด
- Offline packet emulation ระดับ GNS3/EVE-NG ใน MVP

---

## 2. Decisions Locked for Implementation

| Area | Final decision |
|---|---|
| Deployment | Docker Compose บนเครื่อง Local |
| Exposure | Bind `127.0.0.1` เป็นค่าเริ่มต้น; ผู้ใช้เปิดให้ Management LAN เอง |
| Cloud | ใช้เฉพาะ Outbound request ไป AI Provider ที่ผู้ใช้ตั้งค่า |
| User | Single local admin |
| Authentication | Master password/local session |
| Initial scale | 1–50 registered devices |
| Device concurrency | สูงสุด 10 connections เป็นค่าเริ่มต้นและปรับได้ |
| Bulk config | ไม่อยู่ใน MVP; หนึ่งอุปกรณ์ต่อหนึ่ง Change Job |
| Vendor 1 | Cisco IOS/IOS-XE |
| Vendor 2 | Juniper Junos |
| AI | Embedded multi-model gateway พร้อม Provider Adapter |
| Local AI | Ollama เป็น Optional profile |
| Current state | Running Config บนอุปกรณ์ |
| App state | Snapshots, topology metadata และ Intended Changes |
| Node creation | Discovery หรือ Manual Add ที่ตรวจ Connection ได้ |
| Canvas | ลากเพื่อจัดตำแหน่งได้ แต่ไม่สร้างอุปกรณ์ปลอมใน Operational Mode |

### Scale stages

- Stage A: 1–50 devices
- Stage B: 50–200 devices หลังทำ load test และเพิ่ม concurrency control
- Stage C: มากกว่า 200 devices ต้องประเมินสถาปัตยกรรมใหม่

---

## 3. Core Draft vs Current PRD vs Final Decision

| Core draft เดิม | PRD ปัจจุบัน | Final decision |
|---|---|---|
| ค้นหาและ Map เป็น Node | Discovery, ZTP, IPAM และ auto-map | เก็บ Manual Add, SSH scan และ CDP/LLDP; เลื่อน ZTP/IPAM |
| AI, Wizard และ Manual config | Deep Config ทุก Domain | คง 3 Mode แต่ MVP จำกัด Interface, VLAN, IP และ Static Route |
| Terminal จริง | Advanced multi-tab terminal | ทำ Terminal ที่จำเป็น; เลื่อน split view, autocomplete, recording |
| ICMP/ARP แสดง Path | Simulation และ Digital Twin | เปลี่ยนเป็น Live Diagnostics; ARP แสดง Inferred L2 evidence |
| Multi-vendor | 10+ vendors | Cisco ก่อน, Juniper ถัดไป |
| ใช้ Library ที่มี | โหลด subsystem จำนวนมากพร้อมกัน | ใช้ Library ตามหน้าที่และเพิ่มเมื่อจำเป็น |
| Refactor ภายหลัง | Refactor อยู่ Phase 8 | Test/security ทุก Phase; refactor หลังแต่ละ vertical slice |
| Predictive monitoring | อยู่บน critical path | Future หลัง Monitoring พื้นฐาน |
| Auto-rollback | รับประกันผ่าน Software กลาง | Capability-based safety; ไม่รับประกันเมื่อ connection ขาด |
| Export IaC | Ansible/Terraform/YAML | เริ่ม YAML/Ansible หลัง MVP; Terraform เฉพาะ Vendor ที่เหมาะสม |
| Firmware/Power | Advanced Care | Future high-risk module แยกต่างหาก |

---

## 4. Core User Flows

### First run

1. รัน Docker Compose และเปิด Local Web UI
2. ตั้ง Master Password
3. สร้าง Credential Profile แบบเข้ารหัส
4. เพิ่มอุปกรณ์ด้วย IP หรือเริ่ม Discovery
5. ทดสอบ Connection และ Approve
6. ดึง Facts, Interfaces และ Neighbors
7. แสดง Node และ Link บน Canvas

### Read and diagnose

1. เลือก Node
2. ดู Facts, Interfaces, Neighbors และ Config Snapshot
3. เปิด Terminal หรือ Diagnostic Action
4. รัน Ping, Traceroute หรือ Read-only Show Command
5. แสดงผลและบันทึก Event แบบ Sanitized

### Guided or AI configuration

1. เลือกอุปกรณ์และระบุความต้องการ
2. อ่าน Current State ที่จำเป็น
3. Wizard หรือ AI สร้าง Structured Change Plan
4. Vendor Driver render คำสั่ง
5. Validate และสร้าง Pre-change Snapshot
6. แสดง Diff, Risk และ Rollback Capability
7. ผู้ใช้กด Apply
8. Worker ส่ง Config และรัน Post-check
9. Confirm, Rollback หรือ Assisted Recovery ตาม Capability

---

## 5. Functional Scope

### MVP — Must Have

#### Local platform

- Docker Compose install/start/stop
- First-run setup และ Single local admin
- Backup/restore ของฐานข้อมูลและ Config snapshots
- Health check สำหรับ Database, Worker และ optional Ollama

#### Inventory and discovery

- Manual Add ด้วย IP, port, vendor และ Credential Profile
- Connection Test ก่อนบันทึก
- SSH discovery จาก CIDR ที่ผู้ใช้ระบุ
- Safe scan profile และ concurrency limit
- Cisco CDP และ LLDP discovery
- Facts: hostname, vendor, model, serial, OS version และ uptime เมื่อดึงได้
- Interface inventory และ operational state
- Approve ก่อนเพิ่มอุปกรณ์จากผล Scan

#### Topology playground

- Pan, zoom, select และ auto-layout
- บันทึกตำแหน่ง Node
- Node/link status และ interface-pair labels
- Drag เพื่อจัดตำแหน่งเท่านั้น
- Manual link ต้องติดป้าย `Unverified`
- Manual refresh และ configurable refresh interval

#### Terminal and diagnostics

- Web SSH Terminal ผ่าน PTY
- Multiple tabs แบบจำกัดจำนวน
- Idle timeout และ output buffer limit
- Ping/Traceroute จาก App host หรือ Device เมื่อ Driver รองรับ
- Show interfaces, routing, ARP, MAC และ neighbors
- Download sanitized output
- Read-only command allowlist สำหรับ AI tools

#### Safe configuration

- Immutable Running Config snapshots
- Config history และ text diff
- Structured Change Plan
- Explicit Apply
- Per-device operation lock
- Pre-check, Post-check และ timeout
- Event/Audit timeline
- Assisted rollback
- Vendor-specific rollback capability display

#### Guided configuration

- Interface description และ admin state
- Access VLAN และ Trunk allowed VLAN
- SVI/IP address เมื่อ Platform รองรับ
- Static route
- DNS/NTP/SNMP basic settings หลัง Core flow เสถียร

#### AI model gateway

- Profiles: OpenAI, Anthropic, Gemini, Ollama และ OpenAI-compatible endpoint
- Model ID เป็น Runtime setting ไม่ hard-code
- Test connection และ capability probe
- Streaming response
- Config explanation และ troubleshooting recommendation
- Structured Change Plan generation
- Provider/model selection ต่อ Session
- Optional fallback chain
- Context preview ก่อนส่ง Cloud
- Secret stripping และ sensitive-field masking
- AI ไม่มีสิทธิ์ Apply โดยตรง

### Post-MVP — Should Have

- Juniper Junos ผ่าน NETCONF
- Candidate config, compare และ commit confirmed
- Config drift detection
- SNMPv3 polling
- Local dashboard: availability, CPU, memory และ interface utilization
- Syslog receiver แบบ opt-in และ UI alerts
- YAML topology export/import
- Ansible inventory/playbook export
- 50–200 device load testing
- Controlled bulk read; bulk write หลังมี DAG และ failure policy

### Future/Optional

- Digital Twin ผ่าน Containerlab/Batfish
- MTU, loop และ protocol scenario simulation
- Predictive monitoring และ anomaly detection
- Full IPAM, ZTP, firmware, PDU/power และ compliance
- Additional vendors, Multi-user/RBAC, HA และ Cloud deployment

---

## 6. Live Diagnostics vs Simulation

### Live Diagnostics

- ICMP Ping และ Traceroute
- Routing table lookup และ Interface status
- CDP/LLDP relationships
- ARP/MAC table inspection
- Path inference จาก Topology และ Routing State

ผลต้องติดป้าย `Observed` หรือ `Inferred` เสมอ ARP เป็น L2 local/broadcast-domain mechanism จึงไม่ควรแสดงเป็น routed end-to-end path แบบ ICMP ระบบควรแสดง VLAN, switch interfaces, CAM/ARP evidence และส่วนที่ข้อมูลไม่ครบ

### Offline Simulation

Digital Twin สำหรับ MTU mismatch, TTL/routing loop, STP convergence, ACL impact และ failure scenario ไม่อยู่ใน MVP

---

## 7. Configuration Safety Model

### Safety levels

| Level | Meaning | Example |
|---|---|---|
| A — Native transactional | Candidate, compare, commit confirmed และ native rollback | Juniper Junos |
| B — Device-assisted | Pre-stage rollback/reload หรือ replace ตาม Platform | Cisco บาง Platform/Feature |
| C — Best effort | Snapshot, diff และ post-check; rollback ต้องเชื่อมต่อกลับได้ | Cisco IOS/IOS-XE ทั่วไป |
| D — Read-only | Driver ยังไม่ผ่าน write test | Unknown platform |

UI ต้องแสดง Safety Level ก่อน Apply และห้ามใช้คำว่า Auto-Rollback กับ Level C

### Mandatory apply pipeline

```text
Intent -> Change Plan -> Vendor Render -> Validation -> Snapshot
       -> Diff/Risk -> User Confirmation -> Device Lock -> Apply
       -> Post-check -> Confirm/Rollback/Assisted Recovery -> Audit
```

### Rules

- Manual Terminal เป็น Direct Mode และไม่รับประกัน rollback
- Wizard/AI block คำสั่ง erase, reload, format และ factory reset
- Terminal แสดง Warning แต่ไม่ถือ Command parser เป็น security boundary
- Credential/secret ห้ามอยู่ใน Diff, AI context หรือ logs
- Apply ต้อง idempotent เท่าที่ Change Type รองรับ

---

## 8. Vendor Architecture

ใช้ Capability-based Driver แทนการสมมติว่าทุก Vendor ทำงานเหมือนกัน

```text
Application Service
  -> DeviceDriver Interface
      -> CiscoIOSXEDriver
      -> JuniperJunosDriver
      -> GenericReadOnlyDriver
```

Driver ต้องประกาศ capability สำหรับ Connect, Facts, Interfaces, Neighbors, Config, Routing/ARP/MAC, Render, Validate, Compare, Apply, Post-check และ Rollback

| Capability | Cisco IOS/IOS-XE | Juniper Junos |
|---|---:|---:|
| SSH/show commands | MVP | Post-MVP |
| Facts/interfaces | MVP | Post-MVP |
| CDP/LLDP | MVP | Post-MVP |
| Running config | MVP | Post-MVP |
| VLAN/interface/static route | MVP | Post-MVP |
| NETCONF | Optional by model | Primary path |
| Candidate compare | Capability-dependent | Yes |
| Commit confirmed | Capability-dependent | Yes |

ทุก capability ต้องมี Fixture และ Real-lab test ต่อ OS family/version ก่อนเปลี่ยนสถานะเป็น Supported

---

## 9. AI Gateway Design

AI layer เป็น Model Middleware รับ Request รูปแบบกลาง เลือก Provider/Model และคืนผลลัพธ์ตาม Schema ของระบบ

### Components

- Provider และ Model profile registry
- Capability detection
- Request/response normalization และ streaming adapter
- Retry/fallback policy
- Tool schema registry
- Context builder และ Sanitizer
- Structured output validator
- Local usage log

### Provider profile fields

- Provider type, display name, base URL
- Encrypted API key หรือ no-key local mode
- Model ID และ context limit override
- Streaming/tool-calling/structured-output capabilities
- Local/Cloud flag, timeout และ retry

### Tool policy

- Read-only tools เปิดใช้เมื่อผู้ใช้อนุญาตใน Session
- Write tools ไม่ถูกส่งให้โมเดลใน MVP
- AI สร้าง `ChangePlan` เท่านั้น
- Backend เป็นผู้ Validate, Render และ Execute
- Output ที่ไม่ผ่าน Schema ห้ามเข้าสู่ Apply Pipeline
- ผู้ใช้เห็น Context Summary ก่อนส่ง Cloud

MCP เป็น Optional integration สำหรับ read-only tools/context ไม่ใช่ AI Provider และไม่อยู่บน Critical Path

---

## 10. Recommended Technology Stack

### Frontend

| Component | Choice | Reason |
|---|---|---|
| Framework | React + TypeScript + Vite | Local SPA ไม่ต้องใช้ SSR/SEO; deploy ง่ายกว่า Next.js |
| Topology | Cytoscape.js | Interactive graph, layouts และ pan/zoom |
| Terminal | xterm.js + WebSocket | Browser PTY terminal |
| Server state | TanStack Query | Cache/retry/request state |
| UI state | Zustand | Canvas/session state ที่เบา |
| Forms/schema | React Hook Form + Zod | Typed validation |
| Components | Radix UI + Tailwind CSS | Accessible และปรับ theme ได้ |
| Testing | Vitest + RTL + Playwright | Unit/component/E2E |

ไม่ใช้ Next.js เพราะไม่มี Public pages, SEO, SSR หรือ Server Actions ที่จำเป็น

### Backend

| Component | Choice | Reason |
|---|---|---|
| Language | Python 3.12 | Compatibility ที่ดีใน Network ecosystem |
| API | FastAPI + Pydantic v2 | Typed REST/OpenAPI/WebSocket |
| ORM | SQLAlchemy 2.0 | Pin stable line |
| Migration | Alembic | Schema migration |
| DB driver | psycopg 3 | PostgreSQL sync/async support |
| Job queue | RQ + Redis | เบากว่า Celery และเหมาะกับ Blocking network jobs |
| Package manager | uv | Lockfile และ environment |
| Logging | structlog | Structured logs และ secret filtering |
| Tests | pytest + pytest-asyncio + httpx | Backend testing |

Worker แยก Process จาก API เพื่อไม่ให้ Discovery หรือ Config Job block API/Terminal

### Database and storage

| Component | Choice | Scope |
|---|---|---|
| Primary DB | PostgreSQL 17 | Inventory, topology, jobs, events, metadata |
| Queue/cache | Redis 7 | RQ jobs, status และ pub/sub |
| Snapshots | Encrypted/compressed local volume | Config artifacts |
| Time-series | PostgreSQL ก่อน | แยก DB เมื่อ Monitoring โตจริง |

ไม่ใช้ SQLite เพราะ API, Worker และ WebSocket Process เขียนพร้อมกัน และมีแผนขยายถึง 50–200 devices

### Network automation

| Purpose | Primary | Fallback/notes |
|---|---|---|
| Getters/config abstraction | NAPALM | ใช้เฉพาะ method ที่ผ่าน capability test |
| CLI execution | Scrapli | Netmiko fallback |
| Web terminal PTY | AsyncSSH | แยกจาก structured commands |
| Juniper NETCONF | ncclient | Native transaction flow |
| CLI parsing | TextFSM + NTC Templates | Custom parser เฉพาะที่ขาด |
| SNMP | PySNMP | แนะนำ SNMPv3 |
| Orchestration | Nornir หลัง MVP | เพิ่มเมื่อทำ bulk operations |
| Templates | Jinja2 | Vendor-specific rendering |

NAPALM ไม่แทน Vendor Driver ทั้งหมด เพราะ Feature และ Rollback semantics ต่างกัน

### AI

| Component | Choice | Reason |
|---|---|---|
| Multi-provider | LiteLLM Python SDK แบบ Embedded | Unified provider interface ไม่เพิ่ม Proxy container |
| Local runtime | Ollama optional | Local/offline models |
| Structured output | Pydantic schemas | Validate ChangePlan |
| Agent loop | Small deterministic tool loop | คุมสิทธิ์และตรวจสอบง่าย |
| MCP | Optional หลัง MVP | ไม่อยู่ใน Apply path |

ไม่เพิ่ม LangChain หรือ Autonomous-agent framework ใน MVP

### Security

| Area | Choice |
|---|---|
| Password hashing | Argon2id |
| Secret encryption | AES-GCM ผ่าน `cryptography` |
| Master key | แยกจาก DB; local secret file/OS-protected storage |
| Session | Secure, HttpOnly, SameSite cookie |
| Binding | `127.0.0.1` default |
| API | CSRF, validation และ request size limits |
| AI privacy | Context preview, redaction และ Cloud opt-in |
| Audit | Append-oriented records พร้อม artifact hashes |

คำว่า AES-256 อย่างเดียวไม่พอ ต้องกำหนด authenticated mode และ key management

### Deployment/tooling

- Docker Compose และ Multi-stage builds
- Backend image เดียวสำหรับ API/Worker โดยเปลี่ยน command
- Nginx สำหรับ Static UI/WebSocket routing
- `.env` สำหรับ non-secret settings
- Docker secret/local mounted secret file สำหรับ Keys
- Ruff + Pyright; ESLint + TypeScript strict; pre-commit
- Pin exact versions ใน lockfile และทดสอบก่อน Upgrade
- Model ID เป็น Runtime configuration ไม่ผูกกับ PRD

---

## 11. Local Architecture

```text
Browser
  -> Local Reverse Proxy
      -> React Static UI
      -> FastAPI REST/WebSocket
          -> PostgreSQL
          -> Redis
          -> RQ Worker
              -> Device Drivers -> Management Network Devices
              -> AI Gateway -> Ollama or Cloud AI APIs
          -> Encrypted Snapshot Volume
```

### Docker Compose services

1. `web` — Static UI และ Reverse Proxy
2. `api` — FastAPI
3. `worker` — RQ Worker จาก Backend image เดียวกัน
4. `postgres`
5. `redis`
6. `ollama` — Optional profile

ไม่มี Load Balancer, Redis Sentinel, PostgreSQL replica หรือ InfluxDB ใน MVP

| Mode | CPU | RAM | Disk |
|---|---:|---:|---:|
| Core app without local LLM | 4 cores | 8 GB | 20 GB+ |
| With Ollama | ตามโมเดล | 16 GB+ โดยทั่วไป | เพิ่มตาม Model weights |

---

## 12. Core Data Model and State Rules

Entities หลัก:

- `app_settings`, `credential_profiles`
- `devices`, `device_capabilities`, `interfaces`
- `topologies`, `topology_nodes`, `links`
- `config_snapshots`, `change_plans`, `change_executions`
- `jobs`, `events`
- `provider_profiles`, `ai_sessions`

Rules:

- Running Config คือ Observed Current State
- Snapshot เป็น Immutable record
- Change Plan เป็น Intended Change จน Apply สำเร็จ
- Link มี Source: `observed`, `inferred` หรือ `manual-unverified`
- Credential secret แยกจาก Device record
- AI context เก็บเฉพาะ Sanitized summary โดย Default

---

## 13. API Surface

REST groups:

- `/api/health`, `/api/setup`, `/api/session`
- `/api/credential-profiles`, `/api/devices`, `/api/discovery-jobs`
- `/api/topologies`, `/api/diagnostics`
- `/api/config-snapshots`, `/api/change-plans`, `/api/change-executions`
- `/api/events`, `/api/ai/providers`, `/api/ai/sessions`

WebSocket channels:

- `/ws/jobs/{job_id}`
- `/ws/terminal/{device_id}`
- `/ws/topology/{topology_id}`
- `/ws/ai/{session_id}`

WebSocket URL เดิมที่มี slash 3 ตัวหลัง scheme ต้องเปลี่ยนเป็น Relative path หรือ URL ที่มี Host ถูกต้อง

---

## 14. Suggested Project Structure

```text
network-automation-playground/
├── backend/
│   ├── app/
│   │   ├── api/ core/ models/ schemas/ repositories/
│   │   ├── services/ jobs/
│   │   ├── drivers/
│   │   │   ├── base.py
│   │   │   ├── cisco_iosxe.py
│   │   │   ├── juniper_junos.py
│   │   │   └── generic_readonly.py
│   │   ├── ai/
│   │   │   ├── gateway.py providers.py context.py
│   │   │   └── sanitizer.py tools.py
│   │   └── main.py
│   ├── migrations/
│   ├── tests/{unit,integration,fixtures,lab}/
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/{pages,features,components,stores,api,types}/
│   ├── tests/
│   ├── package.json
│   └── Dockerfile
├── deploy/{compose.yml,compose.ollama.yml,proxy/}
├── docs/{architecture.md,safety-model.md,capability-matrix.md,lab-test-guide.md,user-guide.md}
├── .env.example
└── README.md
```

---

## 15. Implementation Roadmap

Roadmap ใช้ Vertical Slices เพื่อให้มีของใช้งานได้เร็ว

### Phase 0 — Repository and Safety Foundation

- Repository, lint, type check และ tests
- Docker Compose, Database migration และ Worker
- First-run master password และ Credential encryption
- Driver interface, capability model และ sanitized logging

**Exit:** Start ได้คำสั่งเดียว, Migration/Test ผ่าน และไม่มี Plaintext secrets

### Phase 1 — First Real Device

- Cisco IOS/IOS-XE connection และ Manual Add
- Facts/interfaces, Running Config snapshot
- Read-only Node panel และ Event timeline

**Exit:** เพิ่ม Cisco จริงหนึ่งตัวและอ่านข้อมูลได้โดยไม่ใช้ AI

### Phase 2 — Topology and Terminal

- Safe discovery และ CDP/LLDP
- Approve flow และ Cytoscape canvas
- Web Terminal, Ping/Traceroute และ Show commands

**Exit:** แสดง Lab topology พร้อม Terminal/Diagnostics จาก Node

### Phase 3 — Safe Configuration MVP

- Change Plan และ Cisco renderer สำหรับ Interface/VLAN/Static Route
- Diff, validation, risk, lock และ explicit Apply
- Post-check, Assisted rollback และ Failure UI

**Exit:** เปลี่ยน VLAN/Interface ผ่าน Preview/Apply และ Recovery flow ได้

### Phase 4 — Multi-model AI

- LiteLLM gateway และ Provider profiles
- OpenAI-compatible, OpenAI, Anthropic, Gemini และ Ollama
- Streaming, Context/Sanitizer และ Read-only tools
- Structured Change Plan generation

**Exit:** สลับโมเดลได้โดยไม่เปลี่ยน Business Logic และ AI ข้าม Confirmation ไม่ได้

### Phase 5 — Guided Configuration and UX

- Wizard สำหรับ VLAN, trunk/access, IP และ Static Route
- Config history, Search/filter, Backup/restore และ Error guidance
- User documentation

**Exit:** Core workflow ใช้ได้โดยไม่ต้องใช้ Terminal หรือ AI

### Phase 6 — Juniper Junos

- Junos driver, NETCONF, Candidate compare และ Commit confirmed
- Fixtures, Real-lab test และ Capability matrix

**Exit:** Read/config/rollback ผ่าน Juniper Lab ตาม Matrix

### Phase 7 — Monitoring and Scale-up

- SNMP polling, Basic dashboard, Config drift และ Retention
- 50-device load test และ Queue/concurrency tuning
- ประเมิน 50–200 device target

**Exit:** ทำงานต่อเนื่องกับ 50 devices โดยไม่ Overload App หรือ Device

### Phase 8 — Optional Advanced Modules

- YAML/Ansible export
- Digital Twin/Batfish
- Advanced Monitoring, Bulk, IPAM/ZTP
- Additional vendors, Firmware/Power

แต่ละ Module ต้องมี PRD และ Risk Review แยก

---

## 16. Testing Strategy

### Every change

- Unit, API contract และ Frontend component tests
- Type check, lint และ format

### Network drivers

- Sanitized CLI fixtures แยก Vendor/OS version
- Golden parser และ Config renderer tests
- Timeout, auth failure และ malformed output
- Capability tests ป้องกัน unsupported method

### Real lab

- Read-only tests รันได้ปกติ
- Write tests ต้อง Opt-in และระบุ Target
- Backup ก่อน Write ทุกครั้ง
- มี Console/OOB หรือ Recovery plan ก่อน High-risk tests
- บันทึก Model/OS/ผลทดสอบใน Capability matrix

### AI

- Provider contract และ structured-output tests
- Prompt injection จาก Banner/Config/Hostname
- Secret leakage และ Tool allowlist tests
- Change Plan ต้องผ่าน Deterministic backend validation

---

## 17. MVP Acceptance Criteria

### Functional

- ติดตั้งและเปิด Local app ด้วย Docker Compose
- เชื่อม Cisco IOS/IOS-XE Lab device
- Discover, Approve และแสดง 50 Nodes/Links บน Canvas
- Terminal มี reconnect, timeout และ buffer limit
- ทุก Apply มี Immutable pre-change snapshot
- Wizard/AI Apply ไม่ได้หากผู้ใช้ไม่ยืนยัน
- Failure มีสถานะและ Recovery guidance
- AI Provider เปลี่ยนผ่าน Profile ได้โดย Core ไม่ผูก Model

### Safety

- ไม่มี Device/API credentials ใน Response, logs หรือ Cloud context
- Write operation มี Device lock
- Unsupported driver เป็น Read-only
- UI แสดง Safety Level ก่อน Apply
- Manual Terminal ระบุว่าเป็น Direct Mode
- App backup/restore ผ่านการทดสอบ

### Scale

- 50 registered devices
- Default 10 concurrent connections
- Discovery/polling เคารพ Rate limit
- Queue ไม่ทำให้ API/Terminal ค้าง
- Retention ป้องกัน Disk growth ไม่จำกัด

---

## 18. Main Risks and Mitigations

| Risk | Mitigation |
|---|---|
| AI สร้าง Config ผิด | AI สร้าง Plan; Backend validate/render; Explicit confirmation |
| Management หลุด | Safety Level, native commit confirmed, post-check, recovery plan |
| Parser ผิด | Versioned fixtures, unknown handling และ Raw evidence |
| Abstraction ซ่อน Vendor differences | Capability matrix และ Vendor driver |
| Discovery โหลดอุปกรณ์เก่า | CIDR opt-in, rate/concurrency limit |
| Secret หลุด | Central sanitizer, log filter, context preview และ tests |
| Local disk เต็ม | Retention, compression และ storage warning |
| Library incompatibility | Lockfile และ Integration tests ก่อน upgrade |
| Scope โตเกิน MVP | ยึด Non-goals และ Separate PRD สำหรับ Optional module |

---

## 19. Removed from Critical Path

- Predictive monitoring และ InfluxDB
- HA, AWS/GCP, Multi-user/RBAC และ Collaboration
- 10+ Vendors และ Universal auto-remediation
- Terraform export, Firmware และ Power control
- Full Digital Twin และ Advanced compliance
- Video tutorials และ UI animation polish

---

## 20. Definition of Done per Phase

1. User flow ทำงาน End-to-end กับ Device/Fixture ที่กำหนด
2. Error, timeout และ disconnected state ถูกทดสอบ
3. ไม่มี Secret ใน Log/Test artifact
4. Database migration ถูกทดสอบ
5. Capability matrix และ Documentation อัปเดต
6. ผ่าน Lint, Type check และ Automated tests
7. ไม่มี Critical TODO ซ่อนใน Implementation
8. Demo/Acceptance scenario ทำซ้ำได้

Refactor หลังแต่ละ Vertical Slice เฉพาะจุดที่กระทบการพัฒนาต่อ ส่วน UI polish และ Optimization ที่ไม่มี Measurement ให้เลื่อนหลัง MVP

---

## 21. Reference Documentation

- FastAPI: https://fastapi.tiangolo.com/
- React: https://react.dev/
- Vite: https://vite.dev/
- Cytoscape.js: https://js.cytoscape.org/
- xterm.js: https://xtermjs.org/
- PostgreSQL: https://www.postgresql.org/docs/
- SQLAlchemy: https://docs.sqlalchemy.org/
- NAPALM: https://napalm.readthedocs.io/
- Scrapli: https://carlmontanari.github.io/scrapli/
- Netmiko: https://ktbyers.github.io/netmiko/
- Nornir: https://nornir.readthedocs.io/
- LiteLLM: https://docs.litellm.ai/
- Ollama: https://docs.ollama.com/

---

## Final Scope Statement

เวอร์ชันแรกต้องทำให้ผู้ใช้คนเดียวบนเครื่อง Local สามารถค้นหาและมองเห็น Cisco Lab, เปิด Terminal, ตรวจสอบสถานะ, สร้างและ Apply การเปลี่ยนแปลงอย่างมี Backup/Diff/Confirmation และเลือกใช้ AI Model หลาย Provider ผ่าน Gateway กลางได้อย่างปลอดภัย

Juniper เป็น Vendor ถัดไปหลัง Cisco workflow ผ่าน Real-lab acceptance แล้ว ส่วน Monitoring ขั้นสูง, Digital Twin, Bulk operations และ Enterprise features เป็นงานขยาย ไม่ใช่เงื่อนไขของ MVP
