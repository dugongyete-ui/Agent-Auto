#!/bin/bash
set -e

# ─── Post-merge setup — Dzeck AI ──────────────────────────────────────────────
# Dijalankan otomatis setelah task agent merge ke main.
# Memastikan semua dependencies (Node.js + Python) terinstall setelah merge.

# Node.js packages
npm install --legacy-peer-deps

# Deteksi Python
PYTHON=""
for cmd in python3.11 python3.10 python3 python; do
  if command -v "$cmd" &>/dev/null; then PYTHON="$cmd"; break; fi
done

# Python packages — semua sekaligus
if [ -n "$PYTHON" ]; then
  PIP_FLAGS="-q"
  if $PYTHON -m pip install --help 2>&1 | grep -q 'break-system'; then
    PIP_FLAGS="$PIP_FLAGS --break-system-packages"
  fi
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
    "anthropic>=0.40.0" \
    "websockify>=0.10.0" \
    2>&1 | tail -3 || true
fi
