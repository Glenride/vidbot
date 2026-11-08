#!/usr/bin/env bash
# vidbot runner wrapper: puts the edge-tts venv on PATH, then runs a job.
# Usage: ./run.sh job.json
export PATH="$HOME/.venvs/edge-tts/bin:$PATH"
exec python3 "$(dirname "$0")/run_job.py" "$@"
