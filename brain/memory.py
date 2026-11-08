#!/usr/bin/env python3
"""Motion Bot — memory (remake slice 1, 2026-11-03).

The bot's memory store: every render, every correction in D'Vaughn's
own words verbatim, and style learnings stated as observed outcomes.
The Director reads this before rendering; ponder notes summarize it
for him. Nothing here is paraphrased into Janine's framing — a
correction is stored exactly as he wrote it, and a learning is only
recorded when an outcome was observed (a render passed, a correction
landed, a clip failed), never as a guessed preference.

Store: memory.json beside this file (mirrored VM + iMac with the rest
of the watcher). Writes are atomic (tmp + rename). Every function is
failure-silent: memory must never break a render — a missing or
corrupt store reads as empty.

No secrets live here: task ids, titles, story sources, and outcomes
only. Never a key, token, or credential.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

MEMORY_PATH = Path(__file__).resolve().parent / "memory.json"
MAX_ENTRIES = 200


def _now():
    return datetime.now(timezone.utc).isoformat()


def load(path=None):
    """Read the store; missing/corrupt reads as empty, never raises."""
    try:
        data = json.loads(Path(path or MEMORY_PATH).read_text())
        if not isinstance(data, dict):
            return {"renders": [], "corrections": [], "learnings": []}
        return {
            "renders": data.get("renders") or [],
            "corrections": data.get("corrections") or [],
            "learnings": data.get("learnings") or [],
        }
    except (OSError, ValueError):
        return {"renders": [], "corrections": [], "learnings": []}


def _save(data, path=None):
    target = Path(path or MEMORY_PATH)
    tmp = target.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=1))
        os.replace(tmp, target)
    except OSError:
        pass


def _append(kind, entry, path=None):
    try:
        data = load(path)
        data[kind].append(entry)
        data[kind] = data[kind][-MAX_ENTRIES:]
        _save(data, path)
    except Exception:
        pass


def record_render(task_id, title, story_source, beats, critic_overall,
                  out_file, path=None):
    """One finished render: what story it used, what the critic said."""
    _append("renders", {
        "ts": _now(),
        "task_id": task_id,
        "title": title,
        "story_source": story_source,
        "beats": beats,
        "critic": critic_overall,
        "file": out_file,
    }, path)


def record_correction(task_id, text, applies_to="", path=None):
    """His correction, verbatim. Never paraphrased, never summarized."""
    _append("corrections", {
        "ts": _now(),
        "task_id": task_id,
        "text": text,
        "applies_to": applies_to,
    }, path)


def record_learning(text, source, path=None):
    """An observed outcome (render result, correction, ponder note).
    `source` names where it was observed, e.g. "critic", "correction",
    "ponder-2026-11-07". Never a guessed preference."""
    _append("learnings", {
        "ts": _now(),
        "text": text,
        "source": source,
    }, path)


def learnings_summary(limit=5, path=None):
    """Short notes for the Director and for ponder notes: the latest
    corrections (verbatim), the latest learnings, and render counts.
    Returns a list of strings; empty when the store is empty."""
    data = load(path)
    notes = []
    for c in data["corrections"][-limit:]:
        notes.append(f"correction (his words): {c['text']}")
    for le in data["learnings"][-limit:]:
        notes.append(f"learned ({le['source']}): {le['text']}")
    if data["renders"]:
        notes.append(
            f"memory: {len(data['renders'])} past renders on record; "
            f"latest: {data['renders'][-1]['title']}")
    return notes


__all__ = [
    "MEMORY_PATH",
    "load",
    "record_render",
    "record_correction",
    "record_learning",
    "learnings_summary",
]
