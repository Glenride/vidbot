#!/usr/bin/env python3
"""vidbot job runner (scaffold, 2026-11-03).

Takes a vidbot job JSON and renders it with the Automated-Video-Generator
engine. A job is {"id": ..., "title": ..., "script": ...}; the script may
carry [Visual: ...] hints, the engine's input format.

Mechanism, stated plainly: the engine's CLI reads one fixed input file,
so the runner backs that file up, writes the vidbot job in its place,
runs the engine, copies the newest MP4 into vidbot/out/, and restores
the backup. Do NOT run this while another engine generation is in
progress — both runs would fight over the same input file.
"""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

VIDBOT = Path(__file__).resolve().parent
# The engine lives next to vidbot on every host (VM: ~/workspace/repos,
# iMac: ~/projects), so derive it from vidbot's own location.
AVG = VIDBOT.parent / "automated-video-generator"
AVG_INPUT = AVG / "input/scripts/input-scripts.json"
AVG_OUT = AVG / "output"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: run_job.py job.json", file=sys.stderr)
        return 2
    job = json.loads(Path(sys.argv[1]).read_text())
    job_id = job["id"]
    backup = AVG_INPUT.read_bytes()
    started = time.time()
    try:
        AVG_INPUT.write_text(json.dumps([job], indent=2))
        r = subprocess.run(["npm", "run", "generate"], cwd=AVG,
                           text=True, capture_output=True)
        print(r.stdout[-2000:])
        if r.returncode != 0:
            print(r.stderr[-2000:], file=sys.stderr)
            return r.returncode
    finally:
        AVG_INPUT.write_bytes(backup)
    fresh = [p for p in AVG_OUT.rglob("*.mp4")
             if p.stat().st_mtime >= started]
    if not fresh:
        print("no fresh MP4 found in engine output", file=sys.stderr)
        return 1
    newest = max(fresh, key=lambda p: p.stat().st_mtime)
    dest = VIDBOT / "out" / f"{job_id}.mp4"
    shutil.copy2(newest, dest)
    print(f"vidbot: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
