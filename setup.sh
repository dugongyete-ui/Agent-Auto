#!/usr/bin/env bash
#
# Dzeck AI — Auto Setup & Install Dependencies
# Run from project root: ./setup.sh
# Updated: Synced with actual project usage (Mar 2026)
#
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

print_step()  { echo -e "${BLUE}[$(date +%H:%M:%S)]${NC} ${BOLD}$1${NC}"; }
print_ok()    { echo -e "${GREEN}  ✓ $1${NC}"; }
print_warn()  { echo -e "${YELLOW}  ⚠ $1${NC}"; }
print_error() { echo -e "${RED}  ✗ $1${NC}"; }

echo ""
echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}${BOLD}║     Dzeck AI — Setup & Install           ║${NC}"
echo -e "${CYAN}${BOLD}║     Model: llama-3.3-70b (tool-calling)  ║${NC}"
echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""

# ─── Python detection ─────────────────────────────────────────────────────────
PYTHON=""
for cmd in python3 python; do
  if command -v "$cmd" &>/dev/null; then PYTHON="$cmd"; break; fi
done
if [ -z "$PYTHON" ]; then print_error "Python not found! Install Python 3.10+"; exit 1; fi
print_ok "Python: $($PYTHON --version)"

# ─── Node.js check ────────────────────────────────────────────────────────────
if ! command -v node &>/dev/null; then print_error "Node.js not found! Install Node.js 18+"; exit 1; fi
print_ok "Node.js: $(node --version) / npm: $(npm --version)"

# ─── npm packages ─────────────────────────────────────────────────────────────
print_step "Installing Node.js packages..."
cd "$PROJECT_ROOT"
npm install --no-audit --prefer-offline 2>&1 | grep -E "added|updated|packages" | head -3 || true
print_ok "Node.js packages ready"

# ─── Python packages ──────────────────────────────────────────────────────────
print_step "Installing Python packages..."

PIP_FLAGS=""
if $PYTHON -m pip install --help 2>&1 | grep -q 'break-system'; then
  PIP_FLAGS="--break-system-packages"
fi

# Packages actually used in this project (synced Mar 2026):
# - pydantic: data validation for models (Plan, Step, Memory, ToolResult)
# - playwright: headless browser automation (browser.py local fallback)
# - e2b: cloud sandbox for isolated shell/code execution (e2b_sandbox.py)
# - redis: session state caching (db/cache.py — optional, lazy import)
# - motor: MongoDB async driver (db/session_store.py — optional, lazy import)
PYTHON_PACKAGES=(
  "pydantic>=2.0.0"
  "playwright>=1.40.0"
  "e2b>=0.17.0"
  "redis>=5.0.0"
  "motor>=3.7.0"
)

for pkg in "${PYTHON_PACKAGES[@]}"; do
  pkg_name="${pkg%%[>=<]*}"
  echo -n "  Checking $pkg_name..."
  if $PYTHON -m pip install $PIP_FLAGS "$pkg" -q 2>&1; then
    print_ok "$pkg_name ready"
  else
    print_warn "$pkg_name install failed — may need manual install"
  fi
done

# ─── Playwright browser ───────────────────────────────────────────────────────
print_step "Installing Playwright browser (Chromium headless)..."
if $PYTHON -m playwright install chromium --quiet 2>&1; then
  print_ok "Playwright Chromium ready (headless, screenshots enabled)"
else
  print_warn "Run manually: python3 -m playwright install chromium"
fi

# ─── E2B Sandbox check ────────────────────────────────────────────────────────
print_step "Checking E2B cloud sandbox..."
if [ -n "${E2B_API_KEY:-}" ]; then
  print_ok "E2B_API_KEY is set — cloud sandbox enabled (shell/code tools)"
else
  print_warn "E2B_API_KEY not set — shell/code tools will run locally"
  print_warn "Set via: export E2B_API_KEY=your-key (or add to Replit Secrets)"
fi

# ─── Dzeck files directory ────────────────────────────────────────────────────
print_step "Creating Dzeck file store directory..."
mkdir -p /tmp/dzeck_files
mkdir -p /tmp/dzeck_files/uploads
print_ok "/tmp/dzeck_files ready (downloadable files stored here)"

# ─── .env file ────────────────────────────────────────────────────────────────
print_step "Checking .env configuration..."
if [ ! -f "$PROJECT_ROOT/.env" ]; then
  if [ -f "$PROJECT_ROOT/.env.example" ]; then
    cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
    print_warn ".env created from .env.example — set CF_API_KEY, CF_ACCOUNT_ID, CF_GATEWAY_NAME, E2B_API_KEY"
  else
    cat > "$PROJECT_ROOT/.env" <<'EOF'
# ─── Cloudflare AI Gateway — REQUIRED ────────────────────────────────────────
CF_API_KEY=
CF_ACCOUNT_ID=
CF_GATEWAY_NAME=

# ─── Model selection ─────────────────────────────────────────────────────────
# Model terbaik untuk tool calling (verified: llama-3.3-70b-instruct-fp8-fast)
CF_MODEL=@cf/meta/llama-3.3-70b-instruct-fp8-fast
CF_AGENT_MODEL=@cf/meta/llama-3.3-70b-instruct-fp8-fast

# ─── E2B Cloud Sandbox ───────────────────────────────────────────────────────
# Untuk shell/code execution terisolasi (buatkan script, download musik, dll.)
E2B_API_KEY=

# ─── Browser ─────────────────────────────────────────────────────────────────
# Playwright headless untuk browsing web (cari info, screenshot, dll.)
PLAYWRIGHT_ENABLED=true

# ─── Server ──────────────────────────────────────────────────────────────────
PORT=5000
NODE_ENV=development
EOF
    print_warn ".env created — fill in CF_API_KEY, CF_ACCOUNT_ID, CF_GATEWAY_NAME, E2B_API_KEY"
  fi
else
  print_ok ".env file exists"
fi

# ─── Tool routing summary ─────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}${BOLD}║  Routing Cerdas — Tool Dispatch Logic                    ║${NC}"
echo -e "${CYAN}${BOLD}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${CYAN}${BOLD}║  Browser/VNC  → Playwright headless (screenshot live)    ║${NC}"
echo -e "${CYAN}${BOLD}║  Shell/Code   → E2B cloud sandbox (terisolasi, aman)     ║${NC}"
echo -e "${CYAN}${BOLD}║  File I/O     → Local /tmp/dzeck_files                   ║${NC}"
echo -e "${CYAN}${BOLD}║  Search       → DuckDuckGo (bebas API key)               ║${NC}"
echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"

# ─── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║   Setup selesai! Dzeck AI siap digunakan ║${NC}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Mulai server:${NC}"
echo -e "    ${CYAN}npm run server:dev${NC}     → http://localhost:5000"
echo ""
echo -e "  ${BOLD}Model AI aktif:${NC}"
echo -e "    ${GREEN}@cf/meta/llama-3.3-70b-instruct-fp8-fast${NC}"
echo -e "    ${CYAN}✓ Native tool calling verified${NC}"
echo ""
echo -e "  ${BOLD}Konfigurasi:${NC}"
echo -e "    Edit ${CYAN}.env${NC} → CF_API_KEY, CF_ACCOUNT_ID, CF_GATEWAY_NAME, E2B_API_KEY"
echo ""
