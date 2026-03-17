#!/usr/bin/env bash
#
# Dzeck AI — Auto Setup & Install ALL Dependencies (Sekali Jalan)
# Jalankan dari root project: bash setup.sh
# Diperbarui: March 2026 — Multi-Agent Architecture (Web · Data · Code · Files)
#
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

print_step()  { echo -e "\n${BLUE}[$(date +%H:%M:%S)]${NC} ${BOLD}▶ $1${NC}"; }
print_ok()    { echo -e "${GREEN}  ✓ $1${NC}"; }
print_warn()  { echo -e "${YELLOW}  ⚠ $1${NC}"; }
print_error() { echo -e "${RED}  ✗ $1${NC}"; }
print_info()  { echo -e "    ${CYAN}$1${NC}"; }

echo ""
echo -e "${CYAN}${BOLD}╔═══════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}${BOLD}║     Dzeck AI — Setup & Install ALL Dependencies       ║${NC}"
echo -e "${CYAN}${BOLD}║     Multi-Agent: Web · Data · Code · Files            ║${NC}"
echo -e "${CYAN}${BOLD}║     LLM: Cloudflare Workers AI (llama-3.3-70b)        ║${NC}"
echo -e "${CYAN}${BOLD}║     Orchestrator: Cloudflare Workers AI               ║${NC}"
echo -e "${CYAN}${BOLD}╚═══════════════════════════════════════════════════════╝${NC}"
echo ""

# ─── Deteksi Python ───────────────────────────────────────────────────────────
print_step "Mendeteksi runtime Python & Node.js..."
PYTHON=""
for cmd in python3.11 python3.10 python3 python; do
  if command -v "$cmd" &>/dev/null; then PYTHON="$cmd"; break; fi
done
if [ -z "$PYTHON" ]; then
  print_error "Python tidak ditemukan! Install Python 3.10+"
  exit 1
fi
print_ok "Python: $($PYTHON --version 2>&1)"

if ! command -v node &>/dev/null; then
  print_error "Node.js tidak ditemukan! Install Node.js 18+"
  exit 1
fi
print_ok "Node.js: $(node --version)  /  npm: $(npm --version)"

# ─── pip flags (kompatibel Replit / sistem modern) ────────────────────────────
PIP_FLAGS="-q"
if $PYTHON -m pip install --help 2>&1 | grep -q 'break-system'; then
  PIP_FLAGS="$PIP_FLAGS --break-system-packages"
fi

# ─── Node.js packages ─────────────────────────────────────────────────────────
print_step "Menginstall Node.js packages (npm install)..."
cd "$PROJECT_ROOT"
npm install --legacy-peer-deps --no-audit --no-fund 2>&1 \
  | grep -E "added|updated|packages|warn WARN" | head -5 || true
print_ok "Node.js packages siap"

# ─── Python packages — SATU PERINTAH, semua sekaligus ────────────────────────
print_step "Menginstall SEMUA Python packages (satu kali install)..."
print_info "pydantic · requests · aiohttp · httpx · beautifulsoup4"
print_info "flask · flask-cors · playwright · e2b · redis · motor · websockify"

$PYTHON -m pip install $PIP_FLAGS \
  "pydantic>=2.0.0" \
  "requests>=2.28.0" \
  "aiohttp>=3.8.0" \
  "httpx>=0.24.0" \
  "beautifulsoup4>=4.12.0" \
  "flask>=3.0.0" \
  "flask-cors>=4.0.0" \
  "playwright>=1.40.0" \
  "e2b>=0.8.0" \
  "redis>=5.0.0" \
  "motor>=3.0.0" \
  "websockify>=0.10.0" \
  2>&1 | tail -3

print_ok "Semua Python packages berhasil diinstall"

# ─── Verifikasi import setiap package ─────────────────────────────────────────
print_step "Verifikasi import package..."
FAILED=()

check() {
  local mod="$1" name="$2"
  if $PYTHON -c "import $mod" &>/dev/null 2>&1; then
    print_ok "$name"
  else
    print_warn "$name — gagal diimport (opsional atau perlu server)"
    FAILED+=("$name")
  fi
}

check "pydantic"    "pydantic"
check "requests"    "requests"
check "aiohttp"     "aiohttp"
check "httpx"       "httpx"
check "bs4"         "beautifulsoup4"
check "flask"       "flask"
check "flask_cors"  "flask-cors"
check "playwright"  "playwright"
check "e2b"         "e2b"
check "redis"       "redis"
check "motor"       "motor"
check "websockify"  "websockify"

if [ ${#FAILED[@]} -eq 0 ]; then
  print_ok "Semua package terverifikasi berhasil"
else
  print_warn "Package yang gagal diverifikasi: ${FAILED[*]}"
  print_info "Ini normal untuk package yang butuh server (redis, motor) atau X11 (websockify)"
fi

# ─── Playwright Chromium browser ──────────────────────────────────────────────
print_step "Menginstall Playwright Chromium browser..."
if $PYTHON -m playwright install chromium 2>&1 | grep -v "^$"; then
  print_ok "Playwright Chromium siap"
else
  print_warn "Playwright browser gagal. Coba manual:"
  print_info "python3 -m playwright install chromium"
fi

# ─── VNC / Display stack (opsional) ───────────────────────────────────────────
print_step "Cek sistem VNC/display (opsional — butuh replit.nix)..."
VNC_MISSING=()
for bin in Xvfb x11vnc fluxbox; do
  if command -v "$bin" &>/dev/null; then
    print_ok "$bin → $(which "$bin")"
  else
    print_warn "$bin tidak ditemukan (opsional, tambahkan ke replit.nix jika butuh VNC)"
    VNC_MISSING+=("$bin")
  fi
done
if [ ${#VNC_MISSING[@]} -eq 0 ]; then
  print_ok "Stack VNC siap (Xvfb + x11vnc + fluxbox)"

  # Konfigurasi Fluxbox kiosk mode (tanpa toolbar, semua window maximized)
  FBDIR="$HOME/.fluxbox"
  mkdir -p "$FBDIR"
  cat > "$FBDIR/init" <<'FBINIT'
session.screen0.toolbar.visible: false
session.screen0.toolbar.autoHide: true
session.screen0.slit.autoHide: true
session.screen0.defaultDeco: NONE
session.screen0.workspaces: 1
session.screen0.focusModel: MouseFocus
session.screen0.autoRaise: true
session.screen0.clickRaises: true
session.styleFile: /dev/null
FBINIT
  cat > "$FBDIR/apps" <<'FBAPPS'
[app] (name=.*) (class=.*)
  [Maximized] {yes}
  [Deco] {NONE}
  [Dimensions] {1280 720}
  [Position] {0 0}
[end]
FBAPPS
  print_ok "Fluxbox dikonfigurasi: kiosk mode, tanpa dekorasi"
fi

# ─── E2B Sandbox status ────────────────────────────────────────────────────────
print_step "Cek E2B cloud sandbox..."
if [ -n "${E2B_API_KEY:-}" ]; then
  print_ok "E2B_API_KEY terdeteksi — cloud sandbox aktif"
  print_info "Sandbox auto-install: reportlab, python-docx, openpyxl, Pillow"
else
  print_warn "E2B_API_KEY belum diset — shell/code tools jalan lokal"
  print_info "Set via Replit Secrets: E2B_API_KEY"
fi

# ─── Runtime directories ──────────────────────────────────────────────────────
print_step "Membuat runtime directories..."
mkdir -p /tmp/dzeck_files /tmp/dzeck_files/uploads
print_ok "/tmp/dzeck_files/ siap (file hasil agent disimpan di sini)"

# ─── .env file ────────────────────────────────────────────────────────────────
print_step "Cek konfigurasi .env..."
if [ ! -f "$PROJECT_ROOT/.env" ]; then
  cat > "$PROJECT_ROOT/.env" <<'DOTENV'
# ─── Dzeck AI — Environment Variables ────────────────────────────────────────

# Cloudflare Workers AI (WAJIB)
CF_API_KEY=
CF_ACCOUNT_ID=
CF_GATEWAY_NAME=

# Model (opsional, sudah ada default di kode)
CF_MODEL=@cf/qwen/qwen3-30b-a3b-fp8
CF_AGENT_MODEL=@cf/meta/llama-3.3-70b-instruct-fp8-fast

# E2B Cloud Sandbox (untuk shell_exec & browser di sandbox)
E2B_API_KEY=

# MongoDB (opsional — untuk session persistence)
MONGODB_URI=

# Redis (opsional — untuk caching)
REDIS_PASSWORD=

# Session
SESSION_SECRET=

# MCP Server (opsional)
MCP_SERVER_URL=https://mcp.cloudflare.com/mcp
MCP_AUTH_TOKEN=

# Browser
PLAYWRIGHT_ENABLED=true

# Server
PORT=5000
NODE_ENV=development
DOTENV
  print_warn ".env baru dibuat — isi CF_API_KEY, E2B_API_KEY, MONGODB_URI, REDIS_PASSWORD"
else
  print_ok ".env sudah ada"
fi

# ─── Bersihkan Python cache lama ──────────────────────────────────────────────
print_step "Membersihkan __pycache__ lama..."
find "$PROJECT_ROOT/server/agent" -type d -name "__pycache__" \
  -exec rm -rf {} + 2>/dev/null || true
print_ok "Python cache dibersihkan"

# ─── Rangkuman Arsitektur ─────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}${BOLD}║  Arsitektur Multi-Agent Dzeck AI (March 2026)                ║${NC}"
echo -e "${CYAN}${BOLD}╠══════════════════════════════════════════════════════════════╣${NC}"
echo -e "${CYAN}${BOLD}║  Orchestrator → routing tiap step ke agent yang tepat        ║${NC}"
echo -e "${CYAN}${BOLD}║  Web Agent   → browser automation, scraping, search          ║${NC}"
echo -e "${CYAN}${BOLD}║  Data Agent  → analisis data, API datasource, visualisasi    ║${NC}"
echo -e "${CYAN}${BOLD}║  Code Agent  → Python/shell exec, scripting, automasi        ║${NC}"
echo -e "${CYAN}${BOLD}║  Files Agent → manajemen file, dokumen, konversi format      ║${NC}"
echo -e "${CYAN}${BOLD}╠══════════════════════════════════════════════════════════════╣${NC}"
echo -e "${CYAN}${BOLD}║  Browser     → E2B sandbox > Playwright headless > HTTP      ║${NC}"
echo -e "${CYAN}${BOLD}║  Shell/Code  → E2B cloud sandbox (isolated, aman)            ║${NC}"
echo -e "${CYAN}${BOLD}║  LLM Agent   → @cf/meta/llama-3.3-70b-instruct-fp8-fast      ║${NC}"
echo -e "${CYAN}${BOLD}║  LLM Chat    → @cf/qwen/qwen3-30b-a3b-fp8                   ║${NC}"
echo -e "${CYAN}${BOLD}║  Orchestrtr  → Cloudflare Workers AI (llama-3.3-70b)        ║${NC}"
echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"

# ─── Selesai ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔═════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║  ✓  Setup SELESAI! Dzeck AI siap digunakan  ║${NC}"
echo -e "${GREEN}${BOLD}╚═════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Mulai server:${NC}      ${CYAN}npm run dev${NC}   →   http://localhost:5000"
echo ""
echo -e "  ${BOLD}Python packages:${NC}"
echo -e "    ${CYAN}pydantic, requests, aiohttp, httpx, beautifulsoup4${NC}"
echo -e "    ${CYAN}flask, flask-cors, playwright, e2b, redis, motor, websockify${NC}"
echo ""
echo -e "  ${BOLD}Konfigurasi:${NC}"
echo -e "    Edit ${CYAN}.env${NC}  →  CF_API_KEY, E2B_API_KEY, MONGODB_URI, REDIS_PASSWORD, dll."
echo ""
