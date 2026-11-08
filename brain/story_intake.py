#!/usr/bin/env python3
"""Motion Bot — story intake (remake slice 1, 2026-11-03).

Reads the WHOLE task, not just title + details. The old Director read
title + details only, so the actual process in a task — the beat sheet
in completionSteps — was invisible to it, and clips rendered as
title-only slideshows. This module is the fix for that read gap.

Intake priority, in order:
  (a) completionSteps beat sheet: [BEAT n: TITLE | start - end] blocks
      with a Narrative Text line, plus the header's Total Duration /
      fps / Viewport when present. This is the task's own process.
  (b) a Story: block in the details (beats split on |, ->, =>).
  (c) nothing: the caller falls back to the old title-scene behavior.

Epistemic rule (his standing rule 2026-11-03): the hard anchor is
premises, not expression. Beats here are his words (or, for (b),
his Story block) — never invented, never paraphrased. Shaping beats
into scenes, pacing, and transitions happens downstream and is
expression, not fabrication. A beat without narrative text is not a
beat: a title like "THE BAIT" is a label, not story text, so
header-only beat sheets fall through to (b).

Standalone: imports nothing from harness_director (which imports this
module) — no circular import. Pure functions, no I/O, no network.
"""

import re

BEAT_HEADER_RE = re.compile(
    r"(?im)^\[BEAT\s*\d+\s*:\s*(?P<title>[^|\]]+?)\|"
    r"\s*(?P<start>[\d.]+)s\s*-\s*(?P<end>[\d.]+)s\s*\]"
)
NARRATIVE_RE = re.compile(
    r"(?im)^\s*(?:-\s*)?Narrative Text\s*:\s*(?P<text>.+?)\s*$"
)
DURATION_RE = re.compile(
    r"(?i)Total Duration\s*:\s*(?P<seconds>[\d.]+)\s*(?:seconds|secs|sec|s)\b"
)
FPS_RE = re.compile(r"(?i)(?P<fps>\d+)\s*fps\b")
VIEWPORT_RE = re.compile(
    r"(?i)Viewport\s*:\s*(?P<w>\d+)\s*x\s*(?P<h>\d+)"
)
STORY_LINE_RE = re.compile(r"(?im)^\s*story\s*[:\-=]\s*(?P<raw>.+?)\s*$")


def _words(text):
    return [w for w in re.split(r"\s+", (text or "").strip()) if w]


def parse_beat_sheet(completion_steps):
    """completionSteps text -> beat-sheet dict or None.

    Returns {"beats": [{title, start, end, text}], "duration",
    "fps", "viewport"} when at least one beat carries narrative text
    of 3+ words; otherwise None (header-only sheets are labels, not
    story, and fall through to the Story: block).
    """
    text = completion_steps or ""
    headers = list(BEAT_HEADER_RE.finditer(text))
    if not headers:
        return None
    beats = []
    for i, m in enumerate(headers):
        block = text[m.end():headers[i + 1].start() if i + 1 < len(headers)
                     else len(text)]
        nm = NARRATIVE_RE.search(block)
        beat_text = (nm.group("text").strip() if nm else "")
        # Narrative texts are often quoted in the task ("..."); the
        # quotes are punctuation, not content — strip one matching
        # surrounding pair so scenes render the words, not the quotes.
        if (len(beat_text) >= 2 and beat_text[0] == beat_text[-1]
                and beat_text[0] in "\"'"):
            beat_text = beat_text[1:-1].strip()
        if len(_words(beat_text)) < 3:
            continue
        beats.append({
            "title": m.group("title").strip(),
            "start": float(m.group("start")),
            "end": float(m.group("end")),
            "text": beat_text,
        })
    if not beats:
        return None
    dm = DURATION_RE.search(text)
    fm = FPS_RE.search(text)
    vm = VIEWPORT_RE.search(text)
    return {
        "beats": beats,
        "duration": float(dm.group("seconds")) if dm else None,
        "fps": int(fm.group("fps")) if fm else None,
        "viewport": (int(vm.group("w")), int(vm.group("h"))) if vm else None,
    }


def parse_story_block(details):
    """Details text -> list of Story:-block beat texts (or []).

    Same beat rule as the gate: a beat counts at 3+ words. A Story:
    line is his words, kept verbatim.
    """
    m = STORY_LINE_RE.search(details or "")
    if not m:
        return []
    parts = re.split(r"\s*(?:\||->|=>)\s*", m.group("raw"))
    return [p.strip() for p in parts if len(_words(p)) >= 3]


def extract_story(task):
    """Task dict -> story dict for the Director.

    {"source": "beat_sheet" | "story_block" | "none",
     "beats": [{title, start, end, text}],
     "duration": float | None, "fps": int | None,
     "viewport": (w, h) | None}
    Duration/fps/viewport come from the beat-sheet header only when
    the beat sheet is the source; otherwise the caller's label logic
    applies.
    """
    sheet = parse_beat_sheet(task.get("completionSteps") or "")
    if sheet:
        return {"source": "beat_sheet", **sheet}
    block = parse_story_block(task.get("details") or "")
    if block:
        return {
            "source": "story_block",
            "beats": [{"title": "", "start": None, "end": None, "text": b}
                      for b in block],
            "duration": None,
            "fps": None,
            "viewport": None,
        }
    return {"source": "none", "beats": [], "duration": None,
            "fps": None, "viewport": None}


__all__ = ["parse_beat_sheet", "parse_story_block", "extract_story"]
