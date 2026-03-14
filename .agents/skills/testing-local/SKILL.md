# Testing Agent-Autonomous Locally

## Prerequisites

### System Dependencies
- `x11vnc` must be installed (`sudo apt-get install -y x11vnc`). The server spawns VNC for browser automation and will crash on startup if x11vnc is missing.
- `Xvfb` is usually pre-installed on Linux VMs.
- Python 3.11+ with pip for the agent backend.
- Node.js 22+ with npm for the server.

### Environment Setup
1. Copy `.env.example` to `.env` and fill in:
   - `CF_API_KEY`, `CF_ACCOUNT_ID`, `CF_GATEWAY_NAME` - Cloudflare Workers AI credentials
   - `CF_MODEL` - Chat model (e.g., `@cf/meta/llama-3-8b-instruct`)
   - `CF_AGENT_MODEL` - Agent model (e.g., `@cf/meta/llama-3.3-70b-instruct-fp8-fast`)
   - `E2B_API_KEY` - For cloud sandbox (optional, falls back to local)
   - `MONGODB_URI` - For session persistence (optional)
   - `REDIS_HOST`, `REDIS_PASSWORD` - For caching (optional)
2. Run `npm install` for Node.js dependencies
3. Run `pip3 install -r requirements.txt` for Python dependencies

### Devin Secrets Needed
- `CF_API_KEY` - Cloudflare Workers AI API key
- `E2B_API_KEY` - E2B sandbox API key
- `MONGODB_URI` - MongoDB connection string
- `REDIS_PASSWORD` - Redis password

## Starting the Server
```bash
npx tsx server/index.ts
```
The server runs on port 5000 by default. It also serves on ports 8081 and 8082.

### Common Startup Issues
- **VNC crash (x11vnc ENOENT)**: Install x11vnc: `sudo apt-get install -y x11vnc`
- **E2B_API_KEY not set warning**: The server falls back to local tools. Set E2B_API_KEY in .env for cloud sandbox.
- **Redis not connected**: Optional - the server works without Redis but won't cache sessions.
- **Chromium conflicts**: The VNC stack launches its own Chromium instance on display :10. This may conflict with your testing browser by opening new tabs. Monitor carefully.

## Web UI Testing
- Open `http://localhost:5000` in a browser
- The web UI uses `web-chat.html` (server-rendered), NOT the React Native `ChatPage.tsx`
- All requests go to `/api/agent` which spawns a Python agent process
- The agent creates execution plans with steps and uses tools (shell, file, browser, search)

## Agent Behavior Notes
- The agent uses `message_ask_user` tool for clarification on vague requests, which triggers `waiting_for_user` state
- Whether the agent asks for clarification depends on the LLM model's decision-making - it's non-deterministic
- Specific/actionable requests (e.g., "buatkan script download musik YouTube") typically proceed without asking
- Very vague requests may or may not trigger clarification depending on the model
- The web UI shows a "Dzeck sedang menunggu balasan Anda" badge when waiting_for_user is active

## Testing Plan Step Status
- Plan steps have statuses: pending (gray dot), running (orange dot), completed (green checkmark), failed (red X)
- The plan bar at the bottom shows progress (e.g., "3/7")
- Step status transitions can be observed visually in the web UI

## React Native vs Web UI
- `ChatPage.tsx` is the React Native mobile frontend - requires Expo to test
- `web-chat.html` is the web frontend served at localhost:5000 - simpler to test locally
- Both consume the same SSE event stream from `/api/agent`
- Code changes to `ChatPage.tsx` can only be fully tested via the Expo mobile app

## Backend Integration Testing
You can test backend model/event changes directly with Python:
```python
import sys
sys.path.insert(0, '.')
from server.agent.models.event import PlanStatus
from server.agent.models.plan import Plan, Step, ExecutionStatus
# ... create plan, simulate state changes, verify events
```
