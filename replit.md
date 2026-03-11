# Dzeck AI

Cross-platform AI chat + autonomous agent app built with Expo (React Native) and Node.js backend.
Implements Manus-like autonomous agent architecture with class-based tools, PlannerAgent + ExecutionAgent pattern.

## Architecture (Manus-like Autonomous Agent)

| Aspek | Implementation |
|---|---|
| Language | Python async (AsyncGenerator) |
| LLM | Cloudflare Workers AI (llama-3.3-70b-instruct-fp8-fast via AI Gateway) |
| Framework | Pydantic BaseModel + async generator streaming |
| Database | MongoDB Atlas (motor async driver) for session/agent persistence |
| Cache | Redis (aioredis) for session state caching |
| Browser | Playwright headless local (screenshot) + HTTP fallback |
| Shell Sandbox | E2B Cloud Sandbox (isolated, secure execution) |
| Architecture | DDD: Domain / Application / Infrastructure layers |
| Session mgmt | Full session resume + rollback support |
| Default Language | Bahasa Indonesia (semua prompt) |
| Tools | Class-based dengan @tool decorator (BaseTool pattern) |

## Key Features

- **Manus-like Web UI**: Full redesign di `server/templates/web-chat.html` dengan Manus-style interface
  - **Welcome → Chat Transition**: switchToConv() uses dynamic DOM query to always remove current #empty-state; works correctly after startNewChat() recreates welcome screen
  - **Komputer Button**: Header button untuk toggle computer panel secara manual (bukan hanya saat tool dipanggil)
  - **E2B Sandbox**: Shell/code tools run in isolated E2B cloud sandbox (no VNC needed); Browser tools use local headless Playwright with screenshot streaming
  - **Plan Cards**: Plan agent tampil sebagai expandable card dalam chat, real-time update
  - **Tool Items**: Setiap tool call tampil dengan spinner (calling) → checkmark (called) → X (error)
  - **Komputer Dzeck Panel**: Side panel yang bisa dibuka manual atau otomatis saat tool dipanggil, menampilkan browser screenshot real-time dari Playwright headless
  - **Perencana Tab**: Overview semua plan steps dengan status (completed/running/pending)
  - **Clean Chat**: Hanya respons AI final yang tampil di chat, tool activity tersembunyi rapi di bawah steps
  - **Browser Screenshot**: Screenshot langsung dari Playwright browser muncul di tool card dan panel bawah
- **Chat Mode**: Real-time streaming via Cloudflare Workers AI SSE
- **Agent Mode**: Async autonomous Plan-Act agent dengan real tool execution
- **Class-Based Tools**: BaseTool + @tool decorator pattern (Manus architecture)
- **Tool Registry**: Centralized registry dengan dynamic schema generation
- **Session Persistence**: Full MongoDB session history with Redis cache
- **Browser Automation**: Playwright-powered real browser dengan live screenshot (base64) streamed ke frontend
- **Expandable Tool Cards**: AgentToolCard shows colored left accent bar, icon, label, expandable inline content (shell/search/browser/file) — no modals
- **message_notify_user streaming**: Intercepted as streaming message_start/chunk/end events → chat bubbles
- **Session Resume/Rollback**: Resume interrupted sessions, rollback to any step
- **MCP Protocol**: Support for Model Context Protocol (HTTP/SSE transport, extensible to stdio/WebSocket)
- **DDD Architecture**: Clean separation of domain, application, and infrastructure

## Setup

### Running the Project

1. **Backend** (Start Backend workflow): `npm run server:dev` — serves on port 5000 + 8081 (web chat UI)
2. **Frontend** (Start Frontend workflow): Expo Metro bundler on port 8082 (mobile only)

### Web Access
- **Web Chat UI**: Accessible at port 80 (default domain) → Express serves `server/templates/web-chat.html`
- **Mobile Landing**: Accessible at `/mobile` path
- **API**: All `/api/*` routes on port 5000

### Components Added
- `components/ChatBox.tsx` — Input box component for Expo mobile app (was missing)
- `server/templates/web-chat.html` — Full-featured browser chat UI with SSE streaming

### Environment Variables (set in Replit Secrets)

```
CF_API_KEY=<cloudflare-api-key>
CF_ACCOUNT_ID=6c807fe58ad83714e772403cd528dbeb
CF_GATEWAY_NAME=dzeck
CF_MODEL=@cf/meta/llama-3.3-70b-instruct-fp8-fast
CF_AGENT_MODEL=@cf/meta/llama-3.3-70b-instruct-fp8-fast
MONGODB_URI=<mongodb-atlas-uri>
REDIS_HOST=<redis-host>
REDIS_PORT=16364
REDIS_PASSWORD=<redis-password>
SESSION_TTL_HOURS=24
PLAYWRIGHT_ENABLED=true
MCP_SERVER_URL=<optional-mcp-server-url>
```

## File Structure

```
server/
  index.ts              - Express server entry point
  routes.ts             - API routes + session management endpoints
  agent/
    agent_flow.py       - Core async Plan-Act agent (DzeckAgent AsyncGenerator)
    db/
      session_store.py  - MongoDB session persistence (motor async)
      cache.py          - Redis session cache (aioredis)
    services/
      session_service.py - Session lifecycle orchestration (DDD Application layer)
    tools/
      __init__.py       - Tools package - exports all tool classes + registry
      base.py           - BaseTool class + @tool decorator (Manus pattern)
      browser.py        - BrowserTool class + Playwright/HTTP browser functions
      shell.py          - ShellTool class + persistent shell session management
      file.py           - FileTool class + line-based file read/write/str_replace
      search.py         - SearchTool class + DuckDuckGo search (no API key needed)
      message.py        - MessageTool class + user notification/ask functions
      mcp.py            - MCPTool class + MCPClientManager (HTTP/SSE transport)
      registry.py       - Centralized tool registry + dynamic schema generation
    prompts/
      system.py         - System prompt (Bahasa Indonesia default, Manus-style rules)
      planner.py        - Planner prompts (PLANNER_SYSTEM_PROMPT, CREATE_PLAN, UPDATE_PLAN)
      execution.py      - Execution step prompts (EXECUTION_SYSTEM_PROMPT, EXECUTION_PROMPT)
    models/             - Pydantic data models (Plan, Step, Memory, ToolResult, etc.)
    utils/              - Robust JSON parser
app/                    - Expo React Native frontend
components/             - UI components (AgentPlanView, AgentToolCard, ComputerView, etc.)
```

## API Endpoints

- `GET /api/status` — Health check
- `POST /api/chat` — Streaming chat (SSE)
- `POST /api/agent` — Async autonomous agent (SSE) with session_id
- `GET /api/sessions` — List all sessions from MongoDB
- `GET /api/sessions/:id` — Get session details
- `POST /api/sessions/:id/resume` — Resume an interrupted session (SSE)
- `POST /api/sessions/:id/rollback` — Rollback session to previous step
- `GET /api/sessions/:id/events` — Get full event log for a session

## Tool Architecture (Manus Pattern)

### BaseTool + @tool Decorator
```python
class MyTool(BaseTool):
    name: str = "my_tool"
    
    @tool(name="my_function", description="...", parameters={...}, required=[...])
    def _my_function(self, arg: str) -> ToolResult:
        return ToolResult(success=True, message="done")
```

### Tool Registry (registry.py)
- Instantiates all tool classes as singletons
- Provides `get_all_tool_schemas()` for dynamic LLM schema generation
- Provides `execute_tool(name, args)` for centralized dispatch
- Provides `resolve_tool_name(name)` for alias resolution

### TOOL_SCHEMAS (agent_flow.py)
- Built dynamically from `_build_tool_schemas()` using class-based schemas
- Includes special `idle` tool
- Converts OpenAI format → CF-native format automatically

## Python Dependencies

- `pydantic>=2.0.0` - Pydantic BaseModel data models (Plan, Step, Memory, ToolResult)
- `playwright>=1.40.0` - Real browser automation (Chromium headless, screenshots)
- `e2b>=0.17.0` - E2B cloud sandbox for isolated shell/code execution
- `motor>=3.7.0` - Async MongoDB driver (optional, lazy import)
- `redis>=5.0.0` - Redis async client (optional, lazy import)

Note: `requests`, `aiohttp`, `beautifulsoup4` are NOT used — the codebase uses Python stdlib `urllib` + regex for HTTP/HTML parsing.

## Nix System Dependencies (for Playwright Chromium)

Required for Playwright to work on Replit/NixOS:
- `nspr`, `nss`, `mesa`, `expat`, `libxkbcommon`, `glib`, `dbus`
- `atk`, `at-spi2-atk`
- `xorg.libXdamage`, `xorg.libXrandr`, `xorg.libXfixes`, `xorg.libX11`
- `xorg.libXcomposite`, `xorg.libXext`, `xorg.libXcursor`, `xorg.libXtst`
- `xorg.libXinerama`, `xorg.libXi`, `xorg.libxcb`, `xorg.libXScrnSaver`
- `cups`, `alsa-lib`, `pango`, `cairo`

## Key Technical Notes

### Async Agent Flow (AsyncGenerator)
The agent uses Python's `AsyncGenerator` pattern - events are yielded as they happen, enabling true real-time streaming without blocking.

### True Real-Time Streaming (asyncio.Queue bridge)
`call_cf_streaming_realtime()` uses an `asyncio.Queue` to bridge the sync urllib thread with the async generator. Cloudflare chunks are pushed to the queue from a thread via `loop.call_soon_threadsafe()` and yielded immediately - no buffering, no fake streaming.

### Session Persistence
- **MongoDB Atlas**: Stores full session documents (plan, steps, events, metadata)
- **Redis**: Fast cache for hot session state (TTL: 1 hour per session)
- **Session ID**: Auto-generated UUID, returned in first SSE event

### Cloudflare Workers AI Response Format
- Non-streaming: `{"response": "...", "usage": {...}}`
- Streaming SSE: `data: {"response": "chunk"}` then `data: [DONE]`
- Tool calls: `{"tool_calls": [{"name": "func", "arguments": {...}}]}`

### Agent Event Types
- `type: "session"` — session_id assigned
- `type: "plan"` — plan creating/created/running/updated/completed
- `type: "step"` — step running/completed/failed
- `type: "tool"` — tool calling/called/error
- `type: "message_start/chunk/end"` — streaming text
- `type: "done"` — agent finished
