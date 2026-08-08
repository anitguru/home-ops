#!/usr/bin/env python3
"""Compare Whisper JSON transcripts with an authored reference using WER."""

from __future__ import annotations

import json
import pathlib
import re
import sys


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", text.lower())


def edit_counts(reference: list[str], hypothesis: list[str]) -> tuple[int, int, int]:
    # Each cell is (cost, substitutions, deletions, insertions).
    row = [(i, 0, 0, i) for i in range(len(hypothesis) + 1)]
    for r_index, r_word in enumerate(reference, 1):
        new = [(r_index, 0, r_index, 0)]
        for h_index, h_word in enumerate(hypothesis, 1):
            if r_word == h_word:
                new.append(row[h_index - 1])
                continue
            sub = row[h_index - 1]
            delete = row[h_index]
            insert = new[h_index - 1]
            choices = [
                (sub[0] + 1, sub[1] + 1, sub[2], sub[3]),
                (delete[0] + 1, delete[1], delete[2] + 1, delete[3]),
                (insert[0] + 1, insert[1], insert[2], insert[3] + 1),
            ]
            new.append(min(choices))
        row = new
    _, substitutions, deletions, insertions = row[-1]
    return substitutions, deletions, insertions


def main() -> int:
    if len(sys.argv) < 3:
        print(f"usage: {sys.argv[0]} REFERENCE.txt WHISPER.json...", file=sys.stderr)
        return 2
    reference_text = pathlib.Path(sys.argv[1]).read_text().strip()
    reference_words = words(reference_text)
    results = []
    for arg in sys.argv[2:]:
        path = pathlib.Path(arg).resolve()
        data = json.loads(path.read_text())
        transcript = data.get("text", "").strip()
        hypothesis_words = words(transcript)
        substitutions, deletions, insertions = edit_counts(
            reference_words, hypothesis_words
        )
        errors = substitutions + deletions + insertions
        results.append({
            "path": str(path),
            "reference_words": len(reference_words),
            "transcript_words": len(hypothesis_words),
            "substitutions": substitutions,
            "deletions": deletions,
            "insertions": insertions,
            "word_error_rate": round(errors / len(reference_words), 6),
            "transcript": transcript,
        })
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
