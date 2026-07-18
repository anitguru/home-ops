#!/usr/bin/env python3
"""pi4 Approach-B script generator for Guru's Tech Bytes.

Selects the top 4 non-duplicate ranked stories, writes selected-stories.json,
then calls `claude -p` (Opus by default) to author script.txt in the Peter
Griffin voice per the podcast-prompt.md STEP 2 spec. Validates structure and
retries a few times before failing loudly.

Usage: pi4_generate_script.py <PODCAST_DIR> <EPISODE_NUM> <DAY_NAME>
Env:   SCRIPT_MODEL (default claude-opus-4-8), SCRIPT_MAX_TRIES (default 3)
"""
from __future__ import annotations
import json, os, pathlib, subprocess, sys

VOICE_SPEC = """Write a 60-90 second spoken script (~330-400 words) in Peter Griffin's voice:
- Rambling, self-interrupting, blue-collar everyman who somehow has opinions on AI
- Goes off on tangents ("You know what this reminds me of...") then snaps back to the point
- Slightly confused by tech but enthusiastic
- Dry digs at Microsoft feel like a guy who just had a bad Windows update experience
- Natural, conversational -- not trying to be funny, just is
- Include at MOST one short nervous chuckle, written phonetically EXACTLY as: Heh. Hhh, okay, that's something.
  placed right after one joke lands. Do NOT use bracketed stage directions.

Structure -- EXACTLY 6 paragraphs, each separated by a blank line:
1. Greeting, verbatim shape: "Good morning, it's {DAY}. This is Guru's Tech Bytes, episode {EP}." (plain number, no zero-pad, no "Ep." prefix)
2. Story 1 (highest upvotes): 2-3 sentences, Peter voice, lead with "First up..."
3. Story 2: lead with "Second..."
4. Story 3: lead with "Third..."
5. Story 4 (lowest upvotes): lead with "And finally..."
6. Closing, verbatim: "That's your daily byte. Have a great day. Until next time."

Output ONLY the script text. No preamble, no markdown, no bullet points, no headers, no quotes around it."""


def load_selection(pdir: pathlib.Path):
    ranked = json.loads((pdir / "ranked-stories.json").read_text())
    stories = {s["id"]: s for s in json.loads((pdir / "stories.json").read_text())}
    def cs(s): return s.get("combined_score", s.get("score", 0))
    ordered = sorted(ranked, key=cs, reverse=True)
    non_dup = [s for s in ordered if not s.get("is_recent_duplicate")]
    pick = non_dup[:4] if len(non_dup) >= 4 else ordered[:4]
    sel = []
    for s in pick:
        b = stories.get(s["id"], {})
        sel.append({
            "title": s.get("title"),
            "url": b.get("url"),
            "hnUrl": b.get("hn_url"),
            "score": s.get("score"),
            "matchedTopics": s.get("matched_topics", []),
            "cocoindexReason": [
                f"matched trending topics: {', '.join(s.get('matched_topics', [])) or 'none'}",
                f"HN score: {s.get('score')}",
                "not recently covered" if not s.get("is_recent_duplicate") else "recent duplicate (backfill)",
            ],
        })
    return sel


def build_prompt(sel, episode, day):
    lines = [VOICE_SPEC.replace("{DAY}", day).replace("{EP}", str(episode)), "", "The four stories, in order (Story 1 = highest upvotes):"]
    for i, s in enumerate(sel, 1):
        lines.append(f"{i}. {s['title']}  ({s['score']} upvotes)")
    return "\n".join(lines)


def validate(text: str) -> list[str]:
    errs = []
    paras = [p.strip() for p in text.strip().split("\n\n") if p.strip()]
    if len(paras) != 6:
        errs.append(f"expected 6 paragraphs, got {len(paras)}")
    words = len(text.split())
    if not (330 <= words <= 400):
        errs.append(f"word count {words} outside 330-400")
    ch = text.count("Heh. Hhh, okay, that's something.")
    if ch > 1:
        errs.append(f"chuckle used {ch} times (max 1)")
    if paras and not paras[0].lower().startswith("good morning"):
        errs.append("paragraph 1 is not the greeting")
    if paras and "daily byte" not in paras[-1].lower():
        errs.append("paragraph 6 is not the closing")
    return errs


def gen(prompt: str, model: str) -> str:
    r = subprocess.run(["claude", "-p", prompt, "--model", model],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"claude -p exited {r.returncode}: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def main() -> int:
    pdir = pathlib.Path(sys.argv[1])
    episode = sys.argv[2]
    day = sys.argv[3]
    model = os.environ.get("SCRIPT_MODEL", "claude-opus-4-8")
    tries = int(os.environ.get("SCRIPT_MAX_TRIES", "3"))

    sel = load_selection(pdir)
    (pdir / "selected-stories.json").write_text(json.dumps(sel, indent=2))
    prompt = build_prompt(sel, episode, day)

    last = ""
    for attempt in range(1, tries + 1):
        text = gen(prompt, model)
        errs = validate(text)
        if not errs:
            (pdir / "script.txt").write_text(text.strip() + "\n")
            print(f"[script] OK on attempt {attempt} ({len(text.split())} words, model={model})")
            return 0
        last = "; ".join(errs)
        print(f"[script] attempt {attempt} rejected: {last}", file=sys.stderr)
        prompt_retry = prompt + f"\n\nYour previous attempt failed these checks: {last}. Fix them exactly."
        prompt = prompt_retry
    print(f"[script] FAILED after {tries} attempts: {last}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
