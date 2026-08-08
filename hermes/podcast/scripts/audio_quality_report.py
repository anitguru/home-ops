#!/usr/bin/env python3
"""Emit objective audio QA metrics as JSON for one or more files."""

from __future__ import annotations

import array
import hashlib
import json
import pathlib
import re
import subprocess
import sys


def run(*args: str, binary: bool = False):
    result = subprocess.run(args, capture_output=True, check=True)
    return result.stdout if binary else result.stdout.decode(errors="replace")


def probe(path: pathlib.Path) -> dict:
    raw = run(
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration,size,bit_rate:stream=codec_name,sample_rate,channels",
        "-of", "json", str(path),
    )
    return json.loads(raw)


def filter_stderr(path: pathlib.Path, audio_filter: str) -> str:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-af", audio_filter, "-f", "null", "-"],
        capture_output=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))
    return result.stderr.decode(errors="replace")


def loudness(path: pathlib.Path) -> dict:
    text = filter_stderr(
        path, "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json"
    )
    blocks = re.findall(r"\{\s*\"input_i\".*?\}", text, flags=re.S)
    if not blocks:
        raise RuntimeError("ffmpeg loudnorm emitted no JSON metrics")
    data = json.loads(blocks[-1])
    return {
        "integrated_lufs": float(data["input_i"]),
        "true_peak_dbtp": float(data["input_tp"]),
        "lra_lu": float(data["input_lra"]),
        "threshold_lufs": float(data["input_thresh"]),
    }


def silence(path: pathlib.Path, duration: float) -> dict:
    text = filter_stderr(path, "silencedetect=noise=-40dB:d=0.5")
    durations = [float(value) for value in re.findall(r"silence_duration: ([0-9.]+)", text)]
    total = sum(durations)
    return {
        "regions": len(durations),
        "seconds": round(total, 4),
        "ratio": round(total / duration, 6) if duration else None,
    }


def sample_metrics(path: pathlib.Path) -> dict:
    raw = run(
        "ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "24000",
        "-f", "f32le", "-acodec", "pcm_f32le", "-", binary=True,
    )
    samples = array.array("f")
    samples.frombytes(raw)
    peak = max((abs(value) for value in samples), default=0.0)
    clipped = sum(1 for value in samples if abs(value) >= 0.999)
    return {
        "decoded_pcm_sha256": hashlib.sha256(raw).hexdigest(),
        "decoded_samples": len(samples),
        "sample_peak": round(peak, 8),
        "clipped_samples": clipped,
        "clipped_ratio": round(clipped / len(samples), 9) if samples else None,
    }


def report(path: pathlib.Path) -> dict:
    info = probe(path)
    fmt = info["format"]
    stream = next(s for s in info["streams"] if s.get("codec_name"))
    duration = float(fmt["duration"])
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "duration_seconds": round(duration, 6),
        "bytes": int(fmt["size"]),
        "bit_rate": int(fmt.get("bit_rate", 0)),
        "codec": stream.get("codec_name"),
        "sample_rate": int(stream.get("sample_rate", 0)),
        "channels": int(stream.get("channels", 0)),
        **loudness(path),
        "silence": silence(path, duration),
        **sample_metrics(path),
    }


def main() -> int:
    if len(sys.argv) < 2:
        print(f"usage: {sys.argv[0]} AUDIO...", file=sys.stderr)
        return 2
    results = [report(pathlib.Path(arg).resolve()) for arg in sys.argv[1:]]
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
