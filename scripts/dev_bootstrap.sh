#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
cp -n .env.example .env 2>/dev/null || true
echo "SAGE dev environment ready. Run: source .venv/bin/activate && sage status"
