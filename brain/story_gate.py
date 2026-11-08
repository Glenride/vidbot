"""Story gate (v2.5, his call 2026-11-03): the bot builds its own story.

The watcher calls check_story() BEFORE claiming, for every Motion Bot
task. A task without a story NO LONGER waits on him: auto_story()
builds a 3-beat arc from the task's own words, the watcher writes it
visibly into the task details as a Story: block (labeled as bot-built,
so he can see and correct it), and the task renders. No question is
posted, no decision is left "needed".

What counts as a story: a beat sheet in completionSteps (2+ beats
with narrative text), a Story: block with 2+ beats, or 2+ narrative
sentences in the details. A hook plus labels (Background / Project /
Subtitle / length) is NOT a story: that is the failure mode the gate
used to catch by asking. The gate checks details + completionSteps,
never the title alone — a three-sentence hook is a slogan list, not
a story.

An empty title returns None here: the watcher's empty-title block
handles that case separately.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness_director import parse_story, split_scenes  # noqa: E402
from story_intake import extract_story  # noqa: E402
from question_gate import (  # noqa: E402
    clear_asked,
    is_asked,
    load_asked,
    post_question_to_mc,
    record_asked,
)

STORY_ASKED_PATH = Path(__file__).resolve().parent / "story_asked.json"


def check_story(task):
    """Task dict -> question dict or None.

    Pure function: no API calls, no file writes.
    """
    title = (task.get("title") or "").strip()
    if not title:
        return None  # empty title blocks separately, asking for the hook
    if len(extract_story(task)["beats"]) >= 2:
        return None
    if len(parse_story(task.get("details") or "")) >= 2:
        return None
    return {
        "trigger": "missing_story",
        "question": (
            "What story should this clip tell? Give it in 2-3 beats: "
            "what happened, what turned, what it means. Add a Story: "
            "block to the task details (beats separated by |) and "
            "reopen the task."
        ),
        "options": [],
    }


def auto_story(task):
    """Task dict -> list of 3+ story beats, built from the task's own words.

    Used when check_story() fires (fewer than 2 beats found): the bot
    builds the story instead of asking him. Beat sources, in order:
    any beats already in the details, then hook-derived scenes (words
    never invented — split_scenes rejoins to the hook), then
    method-language arc lines about how the clip itself is built
    (never topic facts, never stats, never claims about the world).
    The result is written back into the task details as a Story:
    block, labeled bot-built, so it stays visible and correctable.
    """
    title = (task.get("title") or "").strip()
    details = task.get("details") or ""
    beats = [b for b in parse_story(details)]
    for scene in split_scenes(title):
        if len(scene.split()) >= 3 and scene not in beats:
            beats.append(scene)
    if len(beats) < 3:
        beats.append("Slow it down and take it apart, piece by piece.")
    if len(beats) < 3:
        beats.append("What holds up once the noise is stripped away.")
    return beats


__all__ = [
    "STORY_ASKED_PATH",
    "check_story",
    "clear_asked",
    "is_asked",
    "load_asked",
    "post_question_to_mc",
    "record_asked",
]
