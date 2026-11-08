#!/usr/bin/env python3
"""Motion Bot — Bot HQ bridge (remake, 2026-11-03).

Direct interface between D'Vaughn and Motion Bot on Bot HQ
(https://bots.dvaughnhouse.com), so he does not have to filter through
Janine. Design rule: VERBATIM PASSTHROUGH. His messages land in the
bot's intake and memory exactly as written — this module never
paraphrases, reframes, gates, or "improves" them. Janine's job here is
keeping the pipe working, nothing else.

Bot HQ contract (from bot-hq/src/api.ts, read 2026-11-03):
  Bot-facing auth: X-Bot-Key header. No other auth on these routes.
  GET  /api/messages/inbox?bot_id=   undelivered user->bot chat;
                                     fetching MARKS them delivered,
                                     so each message is handed over
                                     exactly once — which is why this
                                     module writes every fetched
                                     message to hq_pending.json BEFORE
                                     tasking it. A crash between fetch
                                     and task leaves the message in
                                     pending, retried next run.
  POST /api/messages                 {bot_id, body, in_reply_to?}
  POST /api/heartbeat                {bot_id, name, status, detail,
                                      capabilities?}
  POST /api/events                   {bot_id, kind, title, detail}

Inbox rows: {id, bot_id, direction, body, in_reply_to, created_at,
delivered_at}. Outbound replies set in_reply_to to the inbound id so
the dashboard threads them.

Message handling (done by the watcher, using this module's helpers):
  - body naming task-NNN  -> correction: recorded verbatim in memory,
    appended verbatim to that task's details, task reopened.
  - body "status"         -> queue-status reply, no task created.
  - body "help"            -> usage reply, no task created.
  - anything else         -> new Mission Control task (project 56):
    title = first line, details = full body verbatim,
    completionSteps = full body verbatim (so the story-first pipeline
    reads beat sheets sent from HQ exactly as it reads MC tasks).

No secrets are ever logged. A missing key file means "HQ not wired":
every function degrades to skip, never to a crash. All HQ calls are
fail-silent from the caller's side — an HQ outage must never break a
render run.
"""

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

HQ_URL = "https://bots.dvaughnhouse.com"
BOT_ID = "motion-bot"
BOT_NAME = "Motion Bot"
UA = "GlenrideBotHQ/1.0 (+https://bots.dvaughnhouse.com)"
WATCHER_DIR = Path(__file__).resolve().parent
KEY_FILE = (Path.home() / "workspace/goals/motion-bot/hidden_files"
            / "bot-hq-key")
SEEN_PATH = WATCHER_DIR / "hq_seen.json"
PENDING_PATH = WATCHER_DIR / "hq_pending.json"

TASK_ID_RE = re.compile(r"task-(\d+)")


def load_key():
    """Shared bot key, or None when HQ is not wired. Never logged."""
    try:
        key = KEY_FILE.read_text().strip()
        return key or None
    except OSError:
        return None


def _req(method, path, key, body=None, timeout=15):
    req = urllib.request.Request(
        HQ_URL + path, method=method,
        headers={"X-Bot-Key": key, "User-Agent": UA,
                 "Content-Type": "application/json"},
        data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HQ {method} {path} -> HTTP {e.code}")
    except (urllib.error.URLError, ValueError, OSError) as e:
        raise RuntimeError(f"HQ {method} {path} failed: {e}")


def poll_inbox(key):
    """Undelivered HQ messages, oldest first. Fetching marks them
    delivered server-side — callers must persist them to pending
    BEFORE doing anything fallible with them."""
    resp = _req("GET", f"/api/messages/inbox?bot_id={BOT_ID}", key)
    return resp.get("messages") or []


def send_message(key, body, in_reply_to=None):
    payload = {"bot_id": BOT_ID, "body": body}
    if in_reply_to is not None:
        payload["in_reply_to"] = in_reply_to
    return _req("POST", "/api/messages", key, payload)


def heartbeat(key, status="online", detail=""):
    return _req("POST", "/api/heartbeat", key, {
        "bot_id": BOT_ID, "name": BOT_NAME, "status": status,
        "detail": detail, "capabilities": ["chat"],
    })


def post_event(key, kind, title, detail=""):
    return _req("POST", "/api/events", key, {
        "bot_id": BOT_ID, "kind": kind, "title": title, "detail": detail,
    })


def _load_json(path, default):
    try:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def _save_json(path, data):
    tmp = Path(str(path) + ".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(path)
    except OSError:
        pass


def load_seen():
    """{hq_id: {"task_id": int, "ts": str}} — tolerates the old flat
    {hq_id: task_id} shape."""
    raw = _load_json(SEEN_PATH, {})
    seen = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            seen[k] = v
        else:
            seen[k] = {"task_id": v, "ts": None}
    return seen


def save_seen(seen):
    _save_json(SEEN_PATH, seen)


def load_pending():
    """[{id, body, in_reply_to}] — messages fetched but not yet tasked."""
    items = _load_json(PENDING_PATH, [])
    return [m for m in items if isinstance(m, dict) and "id" in m]


def save_pending(items):
    _save_json(PENDING_PATH, items)


def add_pending(msg):
    items = load_pending()
    if not any(m["id"] == msg["id"] for m in items):
        items.append({"id": msg["id"], "body": msg.get("body") or "",
                      "in_reply_to": msg.get("in_reply_to")})
        save_pending(items)


def drop_pending(hq_id):
    items = [m for m in load_pending() if m["id"] != hq_id]
    save_pending(items)


def mark_seen(hq_id, task_id):
    seen = load_seen()
    from datetime import datetime, timezone
    seen[str(hq_id)] = {"task_id": task_id,
                        "ts": datetime.now(timezone.utc).isoformat()}
    save_seen(seen)


def split_title(body):
    """First non-empty line, capped at 200 chars. Verbatim content,
    only truncated for the title field — the full body always lands
    in details + completionSteps."""
    for line in (body or "").splitlines():
        line = line.strip()
        if line:
            return line[:200]
    return ""


def correction_task_id(body):
    """Task id named by a correction (task-NNN), or None. The ONLY
    parsing this bridge does — everything else passes through whole."""
    m = TASK_ID_RE.search(body or "")
    return int(m.group(1)) if m else None


def is_command(body, word):
    return (body or "").strip().lower().rstrip("?") == word


__all__ = [
    "HQ_URL", "BOT_ID", "load_key", "poll_inbox", "send_message",
    "heartbeat", "post_event", "load_seen", "save_seen", "load_pending",
    "save_pending", "add_pending", "drop_pending", "mark_seen",
    "split_title", "correction_task_id", "is_command",
]
