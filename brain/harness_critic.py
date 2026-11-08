#!/usr/bin/env python3
"""Motion Bot Harness — Critic.

Verifies a rendered Harness clip with real numbers, after every
Harness render:

  1. Probe: duration / resolution / fps match the storyboard.
  2. Frames differ: mean absolute pixel difference between frames
     sampled at each scene's midpoint plus the last frame — a clip
     whose frames are identical is a broken render, not a video.
  3. Palette present: pixel counts (within RGB tolerance 30) for each
     storyboard palette color in the sampled frames; background and
     surface are checked as one light field (they are often ~40 apart,
     and the gradient between them counts for both).
  4. No blank frames: per-frame pixel stddev.
  5. Text readable: WCAG contrast ratio of text vs background.
  6. No self-mention: "Motion Bot" / "Untitled Project" must appear
     nowhere — checked in the storyboard text AND by OCR (tesseract)
     on the sampled frames.

OCR runs locally when tesseract exists; otherwise it runs on the iMac
render host against the iMac copy of the MP4 (tesseract is installed
there). If neither is available the OCR check reports "skipped", never
a false PASS.

Usage:
  python3 watcher/harness_critic.py <mp4> <storyboard.json>
      [--imac-mp4 ~/projects/motion-bot/out/<name>.mp4]
      [--srt <subtitles.srt>]   # narrated clips: global caption sidecar
      [--out <critic.json>]
Prints a JSON report to stdout and writes it to --out (default:
out/<mp4-stem>.critic.json next to the mp4). Exit 0 on PASS, 1 on FAIL.

Narrated storyboards (narrated:true) skip palette_present and
text_contrast (stock footage has no palette) and gain audio_present
(real voiceover, mean volume > -60 dB) and captions_present (SRT
sidecar has > 0 cues).
"""

import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_director import contrast_ratio  # noqa: E402

REPO = Path(os.path.expanduser("~/workspace/repos/motion-bot"))
IMAC_SSH = os.path.expanduser("~/workspace/.imac-ssh.sh")
BANNED_STRINGS = ("motion bot", "untitled project")
DIFF_PASS = 2.0               # mean abs diff /255 between sampled frames
PALETTE_TOLERANCE = 30        # max RGB Euclidean distance to count a pixel
# accentDeep only ever appears blended (reflection at 0.75 opacity,
# teardrop gradients), so it gets a wider tolerance. Background and
# surface are one "light field" when they are close (white #FFFFFF vs
# parchment #F4EEDC are only ~40 apart, and the gradient between them
# counts for both) — the check uses their union, not each alone.
ROLE_TOLERANCE = {"accentDeep": 60}
CONTRAST_PASS = 3.0           # WCAG contrast text vs background


def run(cmd, timeout=120):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def probe(mp4):
    r = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate",
             "-show_entries", "format=duration",
             "-of", "json", str(mp4)])
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {(r.stderr or '').strip()[-300:]}")
    data = json.loads(r.stdout)
    stream = data["streams"][0]
    num, den = (int(x) for x in stream["r_frame_rate"].split("/"))
    return {
        "width": stream["width"],
        "height": stream["height"],
        "fps": num / den if den else num,
        "duration": float(data["format"]["duration"]),
    }


def probe_audio(mp4):
    """Audio stream present + real mean volume (narrated only).

    Returns (has_audio, mean_volume_db or None). Uses ffmpeg
    volumedetect; a silent track reads -inf / ~-91 dB.
    """
    r = run(["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_name",
             "-of", "csv=p=0", str(mp4)])
    if r.returncode != 0 or not (r.stdout or "").strip():
        return False, None
    r = run(["ffmpeg", "-i", str(mp4), "-vn", "-af", "volumedetect",
             "-f", "null", "-"], timeout=180)
    m = re.search(r"mean_volume:\s*(-?[\d.]+|-\s*inf)\s*dB",
                  (r.stderr or "") + (r.stdout or ""))
    if not m:
        return True, None
    raw = m.group(1).replace(" ", "")
    if raw == "-inf":
        return True, -91.0
    return True, float(raw)


def count_srt_cues(srt_path):
    """Number of cues in an SRT file (0 when missing/unparseable)."""
    try:
        text = Path(srt_path).read_text(errors="ignore")
    except OSError:
        return 0
    cues = re.findall(
        r"^\d+\s*\n\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*"
        r"\d{2}:\d{2}:\d{2}[,.]\d{3}",
        text, re.M)
    return len(cues)


def extract_frame(mp4, seconds, out_path):
    r = run(["ffmpeg", "-v", "error", "-ss", str(seconds), "-i", str(mp4),
             "-frames:v", "1", "-y", str(out_path)])
    if r.returncode != 0 or not Path(out_path).exists():
        raise RuntimeError(f"frame extract at {seconds}s failed")
    return out_path


def load_pixels(path, size=(320, 180)):
    from PIL import Image
    import numpy as np
    img = Image.open(path).convert("RGB").resize(size)
    return np.asarray(img, dtype=float)


def mean_abs_diff(a, b):
    import numpy as np
    return float(np.mean(np.abs(a - b)))


def palette_counts(pixels, palette):
    import numpy as np
    flat = pixels.reshape(-1, 3)
    counts = {}
    for role, hexcode in palette.items():
        h = hexcode.lstrip("#")
        target = np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=float)
        dist = np.sqrt(((flat - target) ** 2).sum(axis=1))
        tol = ROLE_TOLERANCE.get(role, PALETTE_TOLERANCE)
        counts[role] = int((dist <= tol).sum())
    # Light field: pixels matching background OR surface (union) — the
    # two are often near-identical and the gradient counts for both.
    if "background" in palette and "surface" in palette:
        import numpy as np

        def _dist(hexcode):
            h = hexcode.lstrip("#")
            t = np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=float)
            return np.sqrt(((flat - t) ** 2).sum(axis=1))

        counts["light_field"] = int(
            ((_dist(palette["background"]) <= PALETTE_TOLERANCE)
             | (_dist(palette["surface"]) <= PALETTE_TOLERANCE)).sum()
        )
    # Accent family: pixels matching accent OR accentDeep (union) —
    # on light backgrounds the particles render in the deeper gold.
    if "accent" in palette and "accentDeep" in palette:
        import numpy as np

        def _dist2(hexcode, tol):
            h = hexcode.lstrip("#")
            t = np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=float)
            return np.sqrt(((flat - t) ** 2).sum(axis=1)) <= tol

        counts["accent_family"] = int(
            (_dist2(palette["accent"], PALETTE_TOLERANCE)
             | _dist2(palette["accentDeep"], ROLE_TOLERANCE["accentDeep"])).sum()
        )
    return counts


def sample_times(storyboard, duration):
    """Mid-scene samples (each scene at its fullest, words landed) plus
    a last-frame sample. Fixed clock times lie: a sample 0.3s into a
    scene catches words still fading in and reads 0% text.

    Narrated storyboards carry per-scene durationSeconds, so midpoints
    come from the real cumulative durations; Harness storyboards
    split the duration evenly."""
    scenes = storyboard.get("scenes") or []
    n = len(scenes)
    if n == 0:
        return [1.0, 4.0, 7.0, max(0.5, duration - 0.5)]
    if all(isinstance(s.get("durationSeconds"), (int, float)) for s in scenes):
        times = []
        at = 0.0
        for s in scenes:
            d = s["durationSeconds"] or 0
            times.append(round(at + d / 2, 2))
            at += d
    else:
        per = duration / n
        times = [round((i + 0.5) * per, 2) for i in range(n)]
    times.append(round(max(0.5, duration - 0.5), 2))
    return sorted(set(t for t in times if t < duration))


def ocr_local(frame_paths):
    r = run(["which", "tesseract"])
    if r.returncode != 0:
        return None
    texts = []
    for path in frame_paths:
        r = run(["tesseract", str(path), "stdout", "--psm", "6"], timeout=120)
        texts.append(r.stdout if r.returncode == 0 else "")
    return texts


def ocr_imac(imac_mp4, times):
    """OCR on the iMac: extract frames there, tesseract them, print text."""
    if not Path(IMAC_SSH).exists():
        return None
    script = (
        "cd ~/projects/motion-bot && "
        + " && ".join(
            f"ffmpeg -v error -ss {t} -i {imac_mp4} -frames:v 1 -y "
            f"/tmp/critic-{t}.png && tesseract /tmp/critic-{t}.png stdout --psm 6"
            for t in times
        )
    )
    r = run([IMAC_SSH, script], timeout=180)
    if r.returncode != 0:
        return None
    return [r.stdout or ""]


_COVERAGE_STOPWORDS = {
    "about", "after", "again", "against", "along", "among", "around",
    "because", "before", "behind", "below", "between", "beyond",
    "during", "every", "first", "from", "into", "over", "through",
    "under", "until", "upon", "where", "which", "while", "with",
    "without", "within", "would", "could", "should", "there", "their",
    "these", "those", "this", "that", "what", "when", "your", "yours",
}


def _distinctive_words(text):
    """Words that identify a beat on screen: 5+ letters, lowercased,
    not a stopword. OCR is noisy, so coverage matches on any one of
    them rather than demanding the full sentence."""
    words = re.findall(r"[a-z]+", (text or "").lower())
    seen = []
    for w in words:
        if len(w) >= 5 and w not in _COVERAGE_STOPWORDS and w not in seen:
            seen.append(w)
    return seen


def critic(mp4_path, storyboard, imac_mp4=None, srt_path=None):
    """Verify a clip. Narrated storyboards (narrated:true) skip the
    palette/contrast checks (stock footage has no palette) and gain
    two checks of their own: audio_present (real voiceover, not a
    silent track) and captions_present (the SRT sidecar has cues).
    srt_path is the global subtitles.srt pulled back with the MP4."""
    mp4_path = Path(mp4_path)
    narrated = bool(storyboard.get("narrated"))
    report = {"mp4": str(mp4_path), "checks": {}, "overall": "FAIL"}
    if not mp4_path.exists():
        report["checks"]["file"] = {"status": "FAIL", "detail": "mp4 missing"}
        return report
    info = probe(mp4_path)
    report["probe"] = info

    length = storyboard.get("lengthSeconds", 12)
    checks = report["checks"]
    # Orientation-aware (Nov 3 fix): the old check demanded 1280x720
    # landscape, so every 9:16 vertical clip failed probe structurally
    # even when it matched its storyboard exactly (Nov 3: tasks
    # 236-238, 720x1280 @ 30fps, duration on-storyboard). A valid 720p
    # clip in either orientation passes; duration and fps rules hold.
    checks["probe"] = {
        "status": "PASS" if (abs(info["duration"] - length) <= 0.6
                             and (info["width"], info["height"])
                             in ((1280, 720), (720, 1280))
                             and abs(info["fps"] - 30) < 1) else "FAIL",
        "detail": (f"duration {info['duration']:.2f}s (storyboard {length}s), "
                   f"{info['width']}x{info['height']} @ {info['fps']:.1f}fps"),
    }

    times = sample_times(storyboard, info["duration"])
    palette = storyboard.get("palette", {})
    with tempfile.TemporaryDirectory() as tmp:
        frames = []
        for t in times:
            path = Path(tmp) / f"frame-{t}.png"
            extract_frame(mp4_path, t, path)
            frames.append((t, load_pixels(path)))
        # 2. Frames differ.
        diffs = {}
        for (t1, p1), (t2, p2) in zip(frames, frames[1:]):
            diffs[f"{t1}s-vs-{t2}s"] = round(mean_abs_diff(p1, p2), 2)
        checks["frames_differ"] = {
            "status": "PASS" if all(d > DIFF_PASS for d in diffs.values()) else "FAIL",
            "detail": f"mean abs diff /255 per pair: {diffs} (pass > {DIFF_PASS})",
            "numbers": diffs,
        }
        # 3 + 4. Palette presence + blank frames, per sampled frame.
        # Narrated clips have no palette (stock footage) — only the
        # blank-frame stddev applies; palette is SKIPped below.
        total_px = 320 * 180
        per_frame = {}
        blank = []
        for t, px in frames:
            import numpy as np
            if palette:
                counts = palette_counts(px, palette)
                per_frame[f"{t}s"] = {
                    role: {"pixels": c, "pct": round(100 * c / total_px, 2)}
                    for role, c in counts.items()
                }
            blank.append((t, round(float(np.std(px)), 2)))
        # Palette: the light field (background/surface union) must fill
        # every frame; text must be visible in every frame; the accent
        # family (accent + accentDeep union — on light backgrounds the
        # particles render in the deeper gold) must show in at least
        # half the frames (a motif-less middle scene legitimately
        # carries less accent than the mirror scene).
        if palette:
            n_frames = len(frames)
            light_ok = all(
                per_frame[f"{t}s"].get("light_field", {"pct": 0})["pct"] > 50
                for t, _ in frames
            )
            text_ok = all(
                per_frame[f"{t}s"]["text"]["pct"] > 0.02 for t, _ in frames
            )
            accent_frames = sum(
                1 for t, _ in frames
                if per_frame[f"{t}s"].get("accent_family", {"pct": 0})["pct"] > 0.02
            )
            palette_ok = light_ok and text_ok and accent_frames >= (n_frames + 1) // 2
            checks["palette_present"] = {
                "status": "PASS" if palette_ok else "FAIL",
                "detail": ("light field (bg/surface union) >50% every frame; "
                           f"text >0.02% every frame ({text_ok}); accent family "
                           f">0.02% in {accent_frames}/{n_frames} frames"),
                "numbers": per_frame,
            }
        else:
            checks["palette_present"] = {
                "status": "SKIP",
                "detail": "narrated clip: stock footage, no palette",
            }
        checks["not_blank"] = {
            "status": "PASS" if all(s > 5 for _, s in blank) else "FAIL",
            "detail": f"pixel stddev per frame: {dict(blank)} (pass > 5)",
        }
        # 6. OCR (local tesseract, else iMac).
        frame_files = []
        for t in times:
            path = Path(tmp) / f"ocr-{t}.png"
            extract_frame(mp4_path, t, path)
            frame_files.append(path)
        texts = ocr_local(frame_files)
        ocr_source = "local"
        if texts is None and imac_mp4:
            joined = ocr_imac(imac_mp4, times)
            if joined is not None:
                texts = joined
                ocr_source = "imac"
        if texts is None:
            checks["ocr_no_self_mention"] = {
                "status": "SKIP",
                "detail": "tesseract unavailable locally and on iMac",
            }
        else:
            joined_text = "\n".join(texts).lower()
            hits = [b for b in BANNED_STRINGS if b in joined_text]
            checks["ocr_no_self_mention"] = {
                "status": "PASS" if not hits else "FAIL",
                "detail": (f"OCR via {ocr_source} on {len(times)} frames; "
                           f"banned strings found: {hits or 'none'}"),
                "ocr_text_sample": joined_text[:400],
            }
        # 8. Story coverage (remake): every beat in the storyboard's
        # story must show up on screen. OCR is noisy on stylized
        # text, so a beat passes when any distinctive word from its
        # text appears in its scene's sampled frame or anywhere in
        # the OCR text; missed beats are reported in the detail.
        # Blocking rule: FAIL only when NO beat matches at all — a
        # clip that tells nothing of its story. OCR unavailable
        # means SKIP, never a false FAIL.
        story_beats = (storyboard.get("story") or {}).get("beats") or []
        if not story_beats:
            checks["story_coverage"] = {
                "status": "SKIP",
                "detail": "no story beats in storyboard",
            }
        elif texts is None:
            checks["story_coverage"] = {
                "status": "SKIP",
                "detail": "OCR unavailable; coverage unverifiable",
            }
        else:
            joined = "\n".join(texts).lower()
            per_beat = {}
            for i, beat in enumerate(story_beats):
                words = _distinctive_words(beat.get("text", ""))
                frame_text = texts[i].lower() if i < len(texts) else ""
                hit = [w for w in words
                       if w in frame_text or w in joined]
                per_beat[beat.get("title") or f"beat {i + 1}"] = (
                    hit[0] if hit else None)
            matched = sum(1 for v in per_beat.values() if v)
            checks["story_coverage"] = {
                "status": "PASS" if matched > 0 else "FAIL",
                "detail": (f"{matched}/{len(story_beats)} beats matched "
                           f"on screen via OCR; missed: "
                           f"{[k for k, v in per_beat.items() if not v] or 'none'}"),
                "numbers": per_beat,
            }

    # 5. Text readability (deterministic, from the palette).
    # Narrated clips have no palette — SKIP.
    if palette:
        ratio = contrast_ratio(palette.get("text", "#FFFFFF"),
                               palette.get("background", "#000000"))
        checks["text_contrast"] = {
            "status": "PASS" if ratio >= CONTRAST_PASS else "FAIL",
            "detail": f"WCAG contrast text {palette.get('text')} vs background "
                      f"{palette.get('background')}: {ratio:.1f} (pass >= {CONTRAST_PASS})",
            "number": round(ratio, 2),
        }
    else:
        checks["text_contrast"] = {
            "status": "SKIP",
            "detail": "narrated clip: stock footage, no palette",
        }

    # 7. Narrated-only: real voiceover + caption cues.
    if narrated:
        has_audio, mean_db = probe_audio(mp4_path)
        checks["audio_present"] = {
            "status": "PASS" if (has_audio and mean_db is not None and mean_db > -60) else "FAIL",
            "detail": (f"audio stream: {has_audio}, mean volume "
                       f"{mean_db if mean_db is not None else '?'} dB (pass > -60 dB)"),
            "number": mean_db,
        }
        # SRT: explicit --srt path first, else <mp4-stem>.subtitles.srt
        # next to the MP4.
        srt = Path(srt_path) if srt_path else mp4_path.with_name(
            mp4_path.stem + ".subtitles.srt")
        cues = count_srt_cues(srt)
        checks["captions_present"] = {
            "status": "PASS" if cues > 0 else "FAIL",
            "detail": f"{cues} caption cues in {srt.name} (pass > 0)",
            "number": cues,
        }
    # 6b. Storyboard text itself must not name the bot.
    story_text = " ".join([
        storyboard.get("hook", ""),
        storyboard.get("project", ""),
        storyboard.get("subtitle", ""),
    ]).lower()
    hits = [b for b in BANNED_STRINGS if b in story_text]
    checks["storyboard_no_self_mention"] = {
        "status": "PASS" if not hits else "FAIL",
        "detail": f"banned strings in storyboard text: {hits or 'none'}",
    }

    report["overall"] = (
        "PASS" if all(c["status"] in ("PASS", "SKIP")
                      for c in checks.values()) else "FAIL"
    )
    return report


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    mp4, storyboard_path = argv[1], argv[2]
    imac_mp4 = None
    srt_path = None
    out_path = None
    i = 3
    while i < len(argv):
        if argv[i] == "--imac-mp4" and i + 1 < len(argv):
            imac_mp4 = argv[i + 1]
            i += 2
        elif argv[i] == "--srt" and i + 1 < len(argv):
            srt_path = argv[i + 1]
            i += 2
        elif argv[i] == "--out" and i + 1 < len(argv):
            out_path = Path(argv[i + 1])
            i += 2
        else:
            i += 1
    storyboard = json.loads(Path(storyboard_path).read_text())
    report = critic(mp4, storyboard, imac_mp4, srt_path)
    if out_path is None:
        # task-161-harness.mp4 -> task-161-harness.critic.json
        out_path = Path(str(mp4).replace(".mp4", ".critic.json"))
    out_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
