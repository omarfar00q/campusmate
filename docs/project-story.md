# CampusMate: The Alexa+ AI College Assistant Powered by Model Context Protocol

## 💡 Inspiration

Every college student knows the daily cognitive overload of campus life:
- Checking three separate portals just to find out where your 9:00 AM lab is.
- Constantly calculating whether you can afford to skip tomorrow's 8:00 AM lecture without dropping below the mandatory 75% attendance threshold.
- Scrambling between lectures to complete homework assignments with unrealistic deadlines.
- Wandering around massive academic buildings trying to find a classroom like `CS-302` or `Turing Hall Basement Lab`.

When Amazon announced the **Alexa+ Hackathon** focusing on the **Model Context Protocol (MCP)**, we saw an opportunity to rethink the student experience from the ground up. Instead of forcing students to dig through disjointed dashboards and mobile apps, what if an ambient voice assistant like Alexa+ could act as a proactive, context-aware chief of staff? What if Alexa+ could pull real-time timetable data, calculate attendance risk mathematically, schedule study blocks into genuine free time, and provide step-by-step walking directions—all through open standards?

That vision inspired **CampusMate**.

---

## 🎯 What CampusMate Does

CampusMate bridges the gap between university enterprise systems and ambient AI assistants. Built strictly on the **MCP Spec (version 2025-11-25+)** over **Streamable HTTP**, CampusMate provides:

1. **A Standalone, Self-Hosted MCP Server**: Exposes 9 standardized tools (8 read tools + 1 confirmed write tool) with strict session isolation and Bearer token authentication.
2. **Deterministic Daily Planning**: Rather than asking an LLM to hallucinate time slots, CampusMate features a deterministic, pure-function scheduling engine that packs assignments and exam review into verified free slots between classes.
3. **Mathematical Attendance Guardrails**: Accurately computes safe skips and recovery classes based on institution thresholds ($75\%$).
4. **Interactive Alexa+ Web Simulator**: A companion dashboard featuring multimodal voice/screen toggles, speech synthesis, student switcher (Alice, Bob, Charlie), a dynamic timetable view, and a real-time **MCP Protocol Trace Drawer** visualizing every JSON-RPC exchange and sub-second latency.

---

## 📐 The Mathematics Behind CampusMate

### 1. Attendance & Skip Safety Model

For any course with attended classes $N_{\text{att}}$ and total conducted classes $N_{\text{tot}}$, current attendance percentage $A$ is given by:

$$A = \left( \frac{N_{\text{att}}}{N_{\text{tot}}} \right) \times 100$$

Given an institutional threshold $\tau = 75\%$, CampusMate evaluates whether a student can safely miss $k$ upcoming classes without falling into disciplinary probation:

$$\frac{N_{\text{att}}}{N_{\text{tot}} + k} \ge \frac{\tau}{100}$$

Solving for the maximum safe skips $S$:

$$S = \max\left(0, \left\lfloor \frac{100 \cdot N_{\text{att}} - \tau \cdot N_{\text{tot}}}{\tau} \right\rfloor\right)$$

Conversely, if a student is in attendance deficit ($A < \tau$), CampusMate computes the exact number of consecutive classes $R$ the student must attend to recover:

$$\frac{N_{\text{att}} + R}{N_{\text{tot}} + R} \ge \frac{\tau}{100} \implies R = \left\lceil \frac{\tau \cdot N_{\text{tot}} - 100 \cdot N_{\text{att}}}{100 - \tau} \right\rceil$$

### 2. Deterministic Free Slot & Study Packing Algorithm

Let a student's day contain $M$ scheduled classes with intervals $[s_i, e_i]$ for $i \in \{1, \dots, M\}$ between campus waking bounds $[T_{\text{start}}, T_{\text{end}}]$ (e.g., 08:00 to 22:00).

The set of contiguous free slots $\mathcal{F}$ is computed by complementary interval subtraction:

$$\mathcal{F} = [T_{\text{start}}, T_{\text{end}}] \setminus \bigcup_{i=1}^{M} [s_i - \delta, e_i + \delta]$$

where $\delta = 10\text{ min}$ represents walking and classroom transition buffers.

Given $K$ pending tasks with required durations $D_j$ and priority weights $W_j$ based on hours until deadline:

$$W_j = \frac{1}{\max(1, \Delta t_{\text{due}, j})}$$

The planner executes a greedy interval packing to maximize scheduled study time:

$$\max \sum_{j \in \mathcal{S}} W_j D_j \quad \text{subject to} \quad \sum_{j \in \mathcal{S}} D_j \le \sum_{f \in \mathcal{F}} |f|$$

If the total available free time $T_{\text{avail}} < \sum D_j$, the system computes the exact time deficit:

$$\text{Deficit} = \sum_{j=1}^{K} D_j - \sum_{f \in \mathcal{F}} |f|$$

and emits an actionable warning to Alexa+, guiding the student on which lower-priority tasks should be deferred.

---

## 🛠️ How We Built It

We engineered CampusMate across four integrated tiers:

```
┌─────────────────────────────────────────────────────────────┐
│                 Vite + React Frontend (Alexa+ UI)           │
│     - Voice / Screen Mode     - Real-Time MCP Protocol Trace│
│     - Personas (Alice, Bob)   - Interactive Daily Schedule  │
└──────────────────────────────┬──────────────────────────────┘
                               │ SSE Stream (fetch)
┌──────────────────────────────▼──────────────────────────────┐
│                    FastAPI Agent Service                    │
│     - Multi-Turn Agent Loop   - Prompt Injection Defense    │
│     - Speech Summarizer       - Resilient Intent Matcher    │
└──────────────────────────────┬──────────────────────────────┘
                               │ Streamable HTTP (JSON-RPC)
┌──────────────────────────────▼──────────────────────────────┐
│          Standalone MCP Server (Spec 2025-11-25)            │
│  - get_timetable     - find_classroom    - prepare_my_day   │
│  - get_assignments   - get_free_slots    - get_attendance   │
│  - get_exams         - get_facility_info - add_study_block  │
└──────────────────────────────┬──────────────────────────────┘
                               │ SQLAlchemy
┌──────────────────────────────▼──────────────────────────────┐
│                  Relational SQLite Database                 │
│         Students • Timetable • Assignments • Attendance     │
└─────────────────────────────────────────────────────────────┘
```

### 1. Standalone MCP Server (`server/`)
- Built using the official Python SDK (`mcp==2.3.0`) following the **MCP Spec 2025-11-25**.
- Served over **Streamable HTTP** (`/mcp`) using Starlette and Uvicorn.
- **Strict Session Isolation**: Custom ASGI `BearerAuthMiddleware` extracts bearer tokens, resolves student identity (`student_alice`, `student_bob`, `student_charlie`), and binds context variables via Python's `contextvars`. Individual tool arguments never take `student_id`, completely preventing authorization bypass.
- **Safety Protocol**: Added confirmation guards to write tools (`add_study_block` requires `confirmed=True`), ensuring ambient agents never make state mutations without explicit student consent.

### 2. Multi-Turn Agent Client (`agent/`)
- Connects directly to the MCP server as an MCP client over Streamable HTTP using `ClientSession` and `streamable_http_client`.
- Implements two response pathways:
  1. **Live LLM Reasoning**: Seamless support for OpenAI GPT-4o, Groq, or OpenRouter.
  2. **Zero-Key Offline Engine**: A deterministic fallback matcher ensuring hackathon evaluators can test and demo every feature locally without needing paid API keys or credit cards.
- **Prompt Injection Defense**: Evaluates incoming tool results inside protected boundary delimiters, ensuring student-entered task descriptions cannot hijack the agent system prompt.
- **SSE Streaming API**: Uses `sse-starlette` to stream real-time events (`tool_started`, `tool_result`, `final_answer`) directly to frontends.

### 3. Alexa+ Frontend Simulator (`frontend/`)
- Built with React and Vite using custom CSS tokens and glassmorphism.
- **Voice Mode with Web Speech API**: Leverages browser speech recognition and speech synthesis to recreate the hands-free Alexa+ ambient experience.
- **Live MCP Protocol Trace Drawer**: Visualizes the exact JSON-RPC payloads, parameters, results, and network latencies ($15\text{ms} - 45\text{ms}$) as tools execute.
- **One-Command Local Runner**: PowerShell (`run.ps1`) and Bash (`run.sh`) scripts that start all services with automated port conflict resolution and database seeding.

---

## 🧗 Challenges We Faced

1. **Streamable HTTP Session Lifecycle**:
   The `2025-11-25` MCP specification introduced Streamable HTTP sessions. Passing session authentication without relying on legacy stdio pipes required building custom ASGI middleware that handles initial handshakes, persists session ID headers, and guarantees per-request context cleanup.

2. **Cross-Platform CRLF Stream Buffering**:
   During frontend development on Windows, we encountered a subtle bug where the Server-Sent Events stream from FastAPI sent `\r\n\r\n` delimiters. The JavaScript reader split chunks using `\n\n` (LF only), resulting in unsplit buffers that delayed assistant responses. Normalizing CRLF to LF on the fly resolved the issue and restored instant streaming.

3. **Preventing LLM Math Hallucination**:
   Language models frequently make basic arithmetic errors when calculating time intervals or attendance percentages. We solved this by strictly delegating all mathematical logic to deterministic Python functions inside tools (`get_attendance`, `prepare_my_day`), using the model strictly for intent extraction and natural speech synthesis.

4. **Zero-Friction Hackathon Onboarding**:
   We wanted evaluators to run the project without having to install Docker extensions, configure cloud databases, or purchase OpenAI credits. Implementing `.pth` virtualenv auto-discovery and an offline intent matcher enabled true one-command execution via `.\run.ps1`.

---

## 📚 What We Learned

- **The Power of the Model Context Protocol**: Standardizing tool calling through MCP decouples the AI model from backend integrations. You can swap the client LLM (GPT-4o, Claude 3.5, local Llama) without modifying a single line of your database or timetable tools.
- **Defense in Depth for Ambient Agents**: Ambient smart home agents like Alexa+ operate in trusted environments. Implementing confirmation steps for write operations and verifying tokens via headers prevents unintended actions.
- **Deterministic Tools vs. Generative Speech**: The best agent architecture combines deterministic code for math, data retrieval, and constraints, with generative models for conversational fluidity and voice output.

---

## 🚀 What's Next for CampusMate

- **Canvas & Blackboard LMS Integration**: Automated webhooks to pull assignments and grade announcements directly into the student's MCP data lake.
- **Indoor Campus Beacon Navigation**: Integrating BLE beacon telemetry to deliver real-time turn-by-turn guidance inside complex academic complexes.
- **Multi-Agent Study Groups**: Enabling peer agents to discover common free slots via MCP and coordinate collaborative study sessions automatically.
