# AI Grant Apply Agent — Handover Document

**Created:** 2026-03-13
**Purpose:** Context and instructions for an autonomous agent tasked with preparing and submitting grant applications on behalf of this team.

---

## 1. WHO WE ARE

### Organization
**Liminal Commons** — a small, technically deep team (2–10 people) building an ecosystem of AI-integrated collaboration platforms. Operating under the domain umbrella `castalia.one` / `liminalcommons.com`.

We are product builders, not researchers. We ship. We run our own AI inference stack on-premise (AMD Ryzen AI NPU, NVIDIA GPU) and integrate state-of-the-art open-source models into real production systems used by real people.

### Mission
Build the infrastructure for human collective intelligence — spatial, voice-first, AI-assisted environments where groups think, meet, and create together.

### What Makes Us Different
- **Full local AI stack**: We run Parakeet STT (NVIDIA model, NPU-accelerated), Kokoro TTS, and MiniMax M2.5 LLM locally — zero per-call API cost for audio. Most teams pay OpenAI for this; we own it.
- **Spatial AI**: We embed AI into a real-time multiplayer spatial world, not just a chat interface. Users navigate zones, interact with AI agents as named participants, and see transcripts of their presence in space.
- **MCP-first**: Every new capability is designed for MCP (Model Context Protocol) exposure. Our systems are designed to be AI-orchestratable from day one.
- **Self-hosted everything**: We operate a full Docker-managed production stack on our own hardware. We understand the full stack from silicon to UX.

---

## 2. THE PRODUCT ECOSYSTEM

### Core Platforms

| Product | Domain | What it is |
|---------|--------|------------|
| **Castalia** | `castalia.one` | Real-time multiplayer spatial platform. Users move through zones, talk, build. LiveKit video/audio orbs, talk zones with BGM, world map, AI scripting sandbox. Built with React + Phaser + Colyseus + MongoDB. |
| **Vox** | `vox.castalia.one` | Voice meeting platform. LiveKit-based real-time audio, AI transcription, presence, spatial lobby. |
| **Scribe Agent** | (Docker service) | AI transcription agent using Parakeet STT with VAD (Silero), rolling summaries via LiteLLM. Runs alongside LiveKit rooms. |
| **Session Viewer** | (packages/session-viewer) | Next.js app for post-meeting review — synchronized video + transcript, artifact generation (summaries, action items, SRT), dual-brain storage (personal + group). |
| **Tessera** | (AFFiNE-based) | Collaborative canvas and knowledge tool. OIDC-integrated with Castalia auth. |
| **Liminalia** | (Docker stack) | Self-hosted AI serving layer: LiteLLM proxy, Open WebUI, SearXNG, STT proxy, Nginx. The "brain" of the local AI stack. |
| **Memoria** | (packages/memoria) | Transcript knowledge hub. Cognitive synthesis from meeting artifacts. |
| **Voice Agent / Oracle** | (packages/voice-agent) | Conversational voice agent pinned to the "workshop" zone. Zero-latency STT + LLM + TTS pipeline, local. Creates Tessera mind maps from conversation. |
| **Castalia MCP** | (packages/castalia-mcp) | MCP server exposing Castalia's full API to AI agents. |
| **Meeting Views** | (packages/meeting-views) | Shared React component library for in-meeting UI. |

### Technology Stack

**Frontend**: React, Next.js, Phaser 3, TypeScript, MobX, Redux, Tailwind
**Backend**: Node.js, Express, Colyseus (WebSocket rooms), MongoDB, Redis
**AI/ML**: LiveKit Agents SDK, Parakeet TDT v3 (STT), Kokoro-onnx (TTS), MiniMax M2.5 (LLM), LiteLLM proxy, Silero VAD
**Infrastructure**: Docker Compose (20 services), self-hosted on Windows (AMD Strix Point / XDNA NPU + Radeon 890M), Cloudflare tunnels
**Auth**: NextAuth v5, Hylo OAuth, shared JWE cookie bridge across all `*.castalia.one` apps
**Protocols**: LiveKit (WebRTC), Colyseus (WebSockets), MCP (Model Context Protocol), Hocuspocus (Y.js CRDT collab)

---

## 3. KEY FRAMING ANGLES

When writing grant applications, use these narratives depending on the funder's focus:

### Angle A — "Open Infrastructure for Human Collective Intelligence"
*Use for: AI4Good, foundation grants, social impact programs*

> We are building open infrastructure that allows groups of people to think, decide, and create together using AI as a collaborative participant — not a tool. Castalia and Vox lower the barrier for any community, organization, or research group to run AI-facilitated meetings, preserve collective knowledge, and surface insights that would otherwise be lost.

### Angle B — "Local-First, Privacy-Respecting AI Deployment"
*Use for: AI safety grants, EU/UK government programs, trustworthy AI programs*

> Our entire AI stack runs on-premise. No user audio or transcript leaves the host organization's infrastructure. We believe responsible AI deployment means the organization, not a cloud provider, controls sensitive meeting data. We are demonstrating that production-quality AI (real-time STT, LLM, TTS) can be fully self-hosted by small teams.

### Angle C — "AI-Native Platform for Distributed Teams and Communities"
*Use for: corporate accelerators, startup programs, cloud credit grants*

> We have built and deployed a production AI platform serving real users across voice, spatial computing, and knowledge synthesis — on a small team budget. Our architecture integrates 6+ AI models (STT, TTS, LLM, VAD, embeddings, vision) into a coherent user experience. We need compute credits to scale inference and expand to new user communities.

### Angle D — "AI Safety Through Transparency and Human Oversight"
*Use for: OpenAI, Anthropic, Open Philanthropy, Schmidt Sciences safety grants*

> Castalia's AI scripting sandbox (QuickJS, sandboxed, CPU-limited) and MCP server are designed with the premise that AI agents in collaborative environments must be observable, interruptible, and auditable by the humans in the room. Our architecture enforces human oversight at every layer — AI is a participant, not the operator.

### Angle E — "Democratizing AI-Facilitated Collaboration for Underserved Communities"
*Use for: Mozilla, Google.org, GitLab Foundation, Humanity AI — requires nonprofit framing*

> Voice-first, spatially-grounded AI collaboration tools are currently only available to well-resourced organizations using expensive SaaS. We are building and open-sourcing the stack that allows community organizations, indigenous groups, educational institutions, and civil society groups to run their own AI-facilitated collaborative spaces.

---

## 4. THE GRANT DATABASE

**Location**: `C:/flur_workspace/ai-grants/index.html`
**Run locally**: `cd C:/flur_workspace/ai-grants && python -m http.server 3000` → http://localhost:3000
**Total grants**: 40 (as of 2026-03-13)
**Data format**: JavaScript array `GRANTS` embedded in the HTML file

### Viability Tiers

**TIER 1 — Apply Immediately (no equity, rolling, easy entry)**
- Google Cloud AI Startup Program → `cloud.google.com/startup/ai`
- Microsoft for Startups AI Tier → `startups.microsoft.com`
- NVIDIA Inception Program → `nvidia.com/en-us/startups`
- Hugging Face ZeroGPU → `huggingface.co/docs/hub/en/spaces-zerogpu`
- Anthropic Claude Partner Network → `anthropic.com`
- a16z Open Source AI Grants → `a16z.com` (submit work directly)

**TIER 2 — Apply Soon (open deadlines, strong fit)**
- Schmidt Sciences Trustworthy AI RFP — **May 17, 2026**
- SFF S-Process 2026 — **April 22, 2026** (need Speculation Grant first)
- Google.org AI for Government — April 3, 2026 (requires nonprofit partner)
- Foresight Institute — April 1, 2026 (AI safety angle needed)
- AI Grant Accelerator (aigrant.org) — check current cohort
- AWS Activate AI Tier → rolling
- AWS GenAI Accelerator — mid-2026
- Vercel AI Accelerator — next cohort mid-2026

**TIER 3 — Conditional (viable with right structure)**
- NSF SBIR/STTR — if US-incorporated, needs R&D framing
- EIC Accelerator — if EU entity exists or can be created
- NRC IRAP AI Assist — if Canadian entity
- Singapore IMDA / Startup SG Tech — if SG-registered
- YC 2026 — dilutive but worth applying

**DO NOT APPLY**
- Programs requiring academic institution affiliation
- DARPA / defense contracts
- Age/gender-restricted programs (Technovation)
- Health/LMIC-only programs (EVAH, NSF SCH) unless platform pivots
- Programs requiring large established nonprofit (Humanity AI pooled fund)

---

## 5. GRANT APPLICATION GUIDANCE

### What to Always Include

1. **Team size**: "A 2–10 person team with a working production system"
2. **What's live**: "Castalia (`castalia.one`) is in production. Vox is live. Scribe processes real meeting transcripts."
3. **Technical depth**: Mention the local AI stack (Parakeet, Kokoro, MiniMax, LiteLLM, LiveKit)
4. **The gap we fill**: No affordable, privacy-respecting, self-hosted alternative for AI-facilitated spatial collaboration exists
5. **What the grant unlocks**: Be specific — compute credits reduce inference cost, enabling us to onboard underserved communities; cash enables hiring a dedicated AI researcher

### Questions You'll Be Asked

**"What problem do you solve?"**
Groups lose their collective intelligence after every meeting. Castalia and Vox capture, synthesize, and resurface that knowledge — making AI a participant in the room, not an afterthought.

**"What's your traction?"**
Production deployment at `castalia.one` and `vox.castalia.one`. Real users. Full AI stack running on-premise (STT, TTS, LLM, VAD). Multiple interconnected packages in active development.

**"What will you do with the funding?"**
Depends on grant type — compute credits go to scaling inference; cash goes to research time, open-sourcing components, and expanding to underserved community use cases.

**"Are you open source?"**
Core infrastructure components (Scribe Agent, Castalia MCP, meeting-views) are or will be open-sourced. We believe in open infrastructure for collective intelligence.

**"What's your business model?"**
Platform-as-a-service for organizations that want AI-facilitated collaboration in a private, self-hosted environment. We can also operate as a hosted service.

### Tone and Style

- **Confident, specific, technical** — never vague ("AI-powered platform")
- **Grounded in what's real** — cite live systems, real stack, real users
- **Mission-forward** — we believe in collective intelligence, not just productivity software
- **Honest about stage** — we are early, but we are building something that doesn't exist elsewhere

---

## 6. WHAT THE AGENT SHOULD DO

### For Each Grant in TIER 1 or TIER 2 with `viability: "yes"`:

1. **Read the grant page** (fetch the URL in the grant record)
2. **Identify the application form or portal**
3. **Draft responses** to all questions using the framing angles above
4. **Flag for human review** before submitting — do not auto-submit
5. **Log the application** in `C:/flur_workspace/ai-grants/applications/` (one file per grant)

### Application Log Format

```markdown
# Application: [Grant Name]
**Date drafted:** YYYY-MM-DD
**Deadline:** YYYY-MM-DD
**Status:** drafted | reviewed | submitted | rejected | awarded
**Grant URL:** ...
**Application URL / Portal:** ...
**Framing angle used:** A / B / C / D / E

## Draft Responses
[question-by-question draft]

## Notes for Human Review
[anything uncertain, questions needing team input]
```

---

## 7. CONTACTS AND ASSETS

| Asset | Location |
|-------|----------|
| Grant database (live app) | `C:/flur_workspace/ai-grants/index.html` |
| Grant app server | `http://localhost:3000` (python -m http.server 3000) |
| Application drafts | `C:/flur_workspace/ai-grants/applications/` (create if needed) |
| Castalia production | `https://castalia.one` |
| Vox production | `https://vox.castalia.one` |
| Team workspace | `C:/flur_workspace/` |
| Memory / context | `C:/Users/choranode/.claude/projects/C--flur-workspace/memory/` |

---

## 8. RESEARCH LOOP STATUS

A cron job (ID: `9ae580f8`) runs every 10 minutes searching for new AI grant opportunities and appending them to the grant database. As of 2026-03-13, **40 grants** are catalogued.

When new grants are found by the research loop, the apply agent should:
1. Check if `viability === "yes"` and `relevant2026 === true`
2. If yes — draft application immediately
3. If `viability === "partial"` — flag for human decision with a one-paragraph assessment

---

## 9. CRITICAL CONSTRAINTS

- **Never auto-submit an application** — always flag for human review first
- **Never misrepresent the team** — do not claim academic affiliations, nonprofit status, or funding that doesn't exist
- **Do not apply to programs we clearly don't qualify for** — wasted applications damage reputation
- **When in doubt about eligibility** — email the program officer first with a 3-sentence pre-application inquiry
- **Track all applications** — duplicate submissions are embarrassing and sometimes disqualifying

---

*This document is maintained at `C:/flur_workspace/ai-grants/APPLY-AGENT-HANDOVER.md`*
*Update the "traction" and "what's live" sections as new products ship.*
