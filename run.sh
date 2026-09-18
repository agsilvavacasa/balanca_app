#!/usr/bin/env bash
# Desenvolvimento em macOS/Linux (a plataforma-alvo é Windows: veja run_windows.bat).
# Ex.: ./run.sh --modo caixa --janela
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements-dev.txt
fi
exec .venv/bin/python main.py "$@"
