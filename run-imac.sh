#!/usr/bin/env bash
# vidbot runner wrapper for the iMac: edge-tts venv + Node 24 via mise,
# then the runner. Usage: ./run-imac.sh job.json
export PATH="$HOME/.venvs/edge-tts/bin:$PATH"
exec mise x node@24 -- python3 "$(dirname "$0")/run_job.py" "$@"
