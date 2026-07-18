#!/usr/bin/env python3
"""Build an SRT from authored script.txt text, timed against Whisper output.

Uses the audio's total duration (from whisper verbose_json segments) and
distributes the authored text proportionally by character length. Text comes
from script.txt (canonical), NOT Whisper's transcription. Lines <= 47 chars.
"""
import json, pathlib, sys, re

D = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/podcast-2026-07-17")
TODAY = sys.argv[2] if len(sys.argv) > 2 else "2026-07-17"

whisper = json.loads((D / "whisper-raw.json").read_text())
segs = whisper.get("segments", [])
total = whisper.get("duration") or (segs[-1]["end"] if segs else 0.0)
if not total:
    raise SystemExit("no duration from whisper output")

script = (D / "script.txt").read_text().strip()
paras = [p.strip() for p in script.split("\n\n") if p.strip()]

def wrap(text, width=47):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len((cur + " " + w).strip()) <= width:
            cur = (cur + " " + w).strip()
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

# Build cues: each cue is up to 2 lines (<=47 chars each), grouped from paragraphs.
cues = []
for p in paras:
    lines = wrap(p)
    for i in range(0, len(lines), 2):
        cues.append("\n".join(lines[i:i + 2]))

# Distribute time proportional to cue character length across total duration.
weights = [max(len(c.replace("\n", " ")), 1) for c in cues]
wsum = sum(weights)
def fmt(t):
    h = int(t // 3600); m = int((t % 3600) // 60); s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms == 1000:
        s += 1; ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

out, t = [], 0.0
for idx, (cue, w) in enumerate(zip(cues, weights), 1):
    dur = total * (w / wsum)
    start, end = t, min(t + dur, total)
    t = end
    out.append(f"{idx}\n{fmt(start)} --> {fmt(end)}\n{cue}\n")

srt_path = D / f"gurus-tech-bytes-{TODAY}.srt"
srt_path.write_text("\n".join(out).strip() + "\n")
print(f"wrote {srt_path} with {len(cues)} cues over {total:.1f}s")
