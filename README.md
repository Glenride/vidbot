# vidbot

A new video bot, created 2026-11-03. Its job: generate a video you can
actually use, first shot.

## What it is

- **Engine:** Automated-Video-Generator (MIT, TypeScript + Remotion) at
  `~/workspace/repos/automated-video-generator` — script in, narrated
  stock-footage video with captions out.
- **Brain:** Motion Bot's modules, copied into `brain/` as starting
  points to adapt — beat-sheet intake, story gate, critic, memory,
  Bot HQ bridge. Reuse and modification are assumed; this is a
  creative bot, and adapting these parts is part of building it.
- **Runner:** `run_job.py` — takes a job JSON and renders it with the
  engine, then copies the MP4 into `out/`.

## Status: live on the iMac (2026-11-03)

Identity and soul are written (bot-soul-pack) as drafts for D'Vaughn's
correction. The engine smoke test PASSED on the VM (local-pool sample:
8s, 1080x1350, 4.27MB, copy in out/local-pool-smoke.mp4) AND on the
iMac (same sample: 8s, 1080x1350, 0.88MB, copy in out/local-pool-smoke-imac.mp4).

## Layout (VM / iMac / Studio split)

- **iMac (vidbot's home):** ~/projects/vidbot/ (this repo) + engine
  ~/projects/automated-video-generator/ (git clone, pinned to upstream
  68db464 + the vidbot patch below). Node 24 via mise (`mise x
  node@24`), edge-tts 7.3.1 in ~/.venvs/edge-tts, engine config with
  NO Pexels and NO stored Pixabay key. Run jobs with
  `./run-imac.sh job.json` (sets the voice venv + Node 24, then the
  runner). Render host + voice live here.
- **VM:** Pixabay stock via the custom.pixabay connector (the key
  lives in authd on this VM only and cannot be copied — fetch here,
  ship media files to the iMac). This repo is the dev copy; render.ts
  patches sync to the iMac by rsync.
- **Studio:** Ollama over LAN at http://192.168.1.187:11434 (reachable
  from the iMac; NOT reachable from this VM over the tailnet, which
  returns an empty reply). No moondream installed yet, so the engine's
  metadata step still skips — the render does not need it.

## Vidbot patch to the engine (src/render.ts)

Upstream bug, fixed locally: free-source IMAGE visuals keep absolute
cache paths, which Remotion staticFile() rejects (it only accepts
public-relative paths). Staged videos already resolve relatively;
images did not — any job landing on an image crashed at the thumbnail
step. The patch copies absolute-path image/audio assets into the job
public dir and rewrites them to staged relative paths. Drop the patch
if upstream fixes this properly.

## Known gap

sharp is still missing on the iMac (its build fails without
node-addon-api in a form that survives npm's pruning). It is only
required by the agentic-image features — the plain render path does
not import it, and the smoke proof passed without it.

Still to build (next steps, not blockers on creation): HQ/MC intake
wiring, render-host placement, and vidbot's own memory store.

## Run a job

```bash
python3 run_job.py job.json
```

`job.json` shape: `{"id": "...", "title": "...", "script": "..."}`.
The script may carry `[Visual: ...]` hints, the engine's input format.
Output lands in `out/<id>.mp4`.
