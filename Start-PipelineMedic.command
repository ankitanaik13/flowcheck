#!/bin/zsh
set -eu
cd "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  echo "Run make setup and make data in this directory first."
  read '?Press Enter to close.'
  exit 1
fi
echo "Open http://127.0.0.1:8765 in your browser. Keep this terminal open."
exec .venv/bin/python -m uvicorn pipelinemedic.api:app --app-dir src --host 127.0.0.1 --port 8765
