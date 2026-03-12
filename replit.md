# Dzeck AI

## Overview
Dzeck AI is a cross-platform application built with Expo (React Native) and Node.js, designed to provide an AI chat experience alongside autonomous agent capabilities. It implements a Manus-like autonomous agent architecture featuring class-based tools and a PlannerAgent + ExecutionAgent pattern. The project aims to deliver a robust and interactive AI assistant with real-time streaming, session persistence, and integrated browser automation.

**Key capabilities include:**
- Real-time AI chat with streaming responses.
- Autonomous agent mode with planning and execution.
- Interactive web UI with live VNC display for browser tools.
- Isolated and secure shell/code execution in a cloud sandbox.
- Comprehensive session management with resume and rollback features.
- Support for the Model Context Protocol (MCP).

## User Preferences
- I prefer the AI to communicate using simple language.
- I want iterative development where I can provide feedback at each major step.
- Ask before making any major architectural changes or introducing new dependencies.
- I prefer detailed explanations for complex technical decisions.
- Do not make changes to the `app/` folder without explicit instruction.
- All prompts should be in Bahasa Indonesia by default.

## Recent Updates (March 2026)
- **System Prompt Upgraded:** `server/agent/prompts/system.py` fully rewritten based on official Dzeck system prompt spec. Now includes full agent loop, planner/knowledge/datasource module docs, VNC browser rules, sandbox environment info, and all tool use rules — aligned with Manus-grade agent behavior.
- **Execution Prompt Updated:** `server/agent/prompts/execution.py` — removed "headless sandbox" restrictions. AI is now instructed that the browser runs on real VNC and can click, scroll, type just like a human operating a computer.
- **Web UI — Duplicate Name Removed:** `server/templates/web-chat.html` — removed all HTML text occurrences of "Dzeck AI" name (splash title, sidebar app name, header title default). Only the logo image (which already contains the brand name) remains, avoiding duplication.
- **Browser VNC Control:** Agent browser tools (browser_navigate, browser_click, browser_input, browser_scroll_up/down, browser_press_key, browser_select_option, browser_move_mouse) are fully active and run in the VNC-visible Chromium session via CDP. AI controls browser exactly like a human.
- **Race Condition Bug Fixed:** `message_notify_user` emits `"notify"` event type (inline note inside step card) instead of `message_start/chunk/end`; `message_ask_user` emits `role: "ask"` to distinguish from final AI response bubbles.
- **Step History Navigator ("Loncat ke Live"):** Full scrubber added to Komputer Dzeck panel — `captureStepSnapshot`, `navigateHistory`, `jumpToLive`, `_renderHistoryFrame`, scrubber drag/touch handlers, prev/next buttons, and dot markers. State: `S.stepHistory`, `historyIdx`, `_liveTermHTML/Url`.
- **Real-time Token Streaming:** `summarize_async` now uses `call_cf_streaming_realtime` for true token-by-token streaming. `message_correct` event handles post-stream JSON wrapper cleanup.
- **"Menunggu Balasan" Badge:** `createAiMsg(isAsk)` now renders a pulsing yellow badge "Dzeck sedang menunggu balasan Anda" when agent calls `message_ask_user`. Badge automatically removed when user sends next message via `appendUserMsg`.

## System Architecture

**Core Architecture:**
- **Manus-like Autonomous Agent:** Utilizes a PlannerAgent and ExecutionAgent pattern with class-based tools and a `@tool` decorator.
- **Language:** Python `async` (AsyncGenerator) for the agent, Node.js for the backend.
- **LLM:** Cloudflare Workers AI (specifically `llama-3.3-70b-instruct-fp8-fast` via AI Gateway).
- **Framework:** Pydantic BaseModel for data models, `async` generator for streaming.
- **Database:** MongoDB Atlas for session and agent persistence.
- **Cache:** Redis for session state caching.
- **Browser Automation:** Playwright (non-headless) running on a VNC display for live interaction, with HTTP fallback.
- **Shell Sandbox:** E2B Cloud Sandbox for isolated and secure code execution, with 900s timeout, 3-attempt retry, auto-recovery, and keepalive. The workspace is `/home/user/dzeck-ai/` with output in `/home/user/dzeck-ai/output/`. Pre-installed packages include reportlab, python-docx, openpyxl, Pillow, yt-dlp, pandas, matplotlib.
- **System Design:** Domain-Driven Design (DDD) with clear separation of Domain, Application, and Infrastructure layers.
- **Session Management:** Full session resume and rollback support.
- **Tooling:** Class-based tools implemented with a `BaseTool` pattern and `@tool` decorator.

**Branding:**
- **Logo:** Dzeck AI logo (`assets/images/icon.png`) - new logo applied to all icons (favicon, Android adaptive icon, splash icon).
- **Transparent Logo:** `assets/images/dzeck-logo-transparent.png` - PNG with alpha channel, used for splash screens.
- **Splash Screen (Web):** Full-screen dark splash (#0a0a0c) in `web-chat.html` shows transparent logo (inverted white) with animated dots, auto-hides after 1.2s.
- **Splash Screen (Native):** Custom `SplashLoader` component in `app/_layout.tsx` shows during font loading with animated logo and dots.

**UI/UX and Web Chat Features:**
- **Manus-style Web UI:** Redesigned `server/templates/web-chat.html` for a Manus-like interface.
- **Dynamic UI Elements:** Smooth transitions between welcome screen and chat, dynamic computer panel toggle.
- **VNC Integration:**
    - Xvfb virtual display on `:10` with `1280x720x24` resolution.
    - Fluxbox lightweight window manager for proper window rendering.
    - `x11vnc` server on port `5910` with `-xkb -noxrecord -noxfixes` flags for proper keyboard input passthrough.
    - Native WebSocket to TCP proxy for VNC connection.
    - Playwright agent browser appears on VNC in kiosk mode for live interaction.
    - `noVNC` client loaded via CDN in HTML templates.
    - Mobile-friendly VNC toolbar with essential controls (takeover, keyboard, clipboard, etc.).
    - Mobile touch events handled with `preventDefault()` and `stopPropagation()` in takeover mode; listeners bound once to prevent accumulation on reconnects.
    - VNC auto-shutdown after 10 minutes of idle activity, with auto-restart on agent demand.
- **Sandbox Terminal:** Real-time streaming output from E2B sandbox for shell tools, displayed in a dark terminal panel.
- **Plan Cards:** Agent plans are displayed as expandable cards in the chat with real-time status updates.
- **Tool Items:** Each tool call shows status (calling, called, error) with visual indicators.
- **"Komputer Dzeck" Panel:** Side panel dynamically switches between VNC for browser tools and Sandbox Terminal for other tools.
- **"Perencana" Tab:** Provides an overview of all plan steps and their status.
- **Clean Chat:** Only final AI responses are shown in the main chat; tool activity is neatly organized under steps.
- **Browser Screenshot:** Live screenshots from Playwright are displayed in tool cards and the panel.
- **Expandable Tool Cards:** Show colored accent bars, icons, labels, and expandable inline content without modals.

**Technical Implementations:**
- **Per-Session Isolation:** Each agent request gets a unique `DZECK_SESSION_ID`; files stored in `/tmp/dzeck_files/{session_id}/` with path traversal protection.
- **File Delivery:** System prompt includes rules for the agent to create downloadable files (`.zip`, `.pdf`, etc.), with binary formats generated via Python scripts in `shell_exec`. Files are synced between local and E2B sandbox.
- **Browser Persistence (CDP Architecture):** Node.js server launches persistent Chromium with remote debugging enabled and anti-detection flags. Python agent connects via `playwright.chromium.connect_over_cdp()`.
- **True Real-Time Streaming:** Uses `AsyncGenerator` pattern and `asyncio.Queue` to bridge sync HTTP requests with async generators for unbuffered, real-time SSE streaming.
- **Tool Registry:** Centralized registry manages tool instantiation, dynamic schema generation for LLMs, and tool execution dispatch.

## External Dependencies

- **Cloudflare Workers AI:** For Language Model inference (`llama-3.3-70b-instruct-fp8-fast`).
- **MongoDB Atlas:** Cloud-hosted NoSQL database for session and agent state persistence (using `motor` async driver).
- **Redis:** In-memory data store for session state caching (using `aioredis`).
- **Playwright:** Python library for browser automation, interacting with Chromium.
- **E2B Cloud Sandbox:** External service for isolated and secure shell/code execution.
- **noVNC:** HTML5 VNC client for displaying the virtual desktop in the web UI.
- **DuckDuckGo Search:** Used by the `SearchTool` (no API key required).
- **MCP (Model Context Protocol):** Support for `mcp.cloudflare.com` for tool discovery and execution.
- **Nix Packages:** Essential system libraries required for Playwright Chromium to function in the Replit environment (e.g., `xorg`, `mesa`, `glib`, `cups`, `pango`, `cairo`).
- **Python Libraries:**
    - `pydantic`: For data validation and settings management.
    - `e2b`: Python client for E2B Cloud Sandbox.
    - `motor`: Asynchronous MongoDB driver.
    - `redis`: Asynchronous Redis client.