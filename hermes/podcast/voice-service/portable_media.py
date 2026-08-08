"""Stateless media assembly and objective-QA routes for Chatterbox.

These routes intentionally do only the OS-heavy operations that n8n cannot do
with a native node. Segmentation, six TTS calls, gating, Whisper, publishing,
and notifications remain separate visible nodes in n8n.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response


router = APIRouter(prefix="/v1/audio", tags=["Portable Podcast Media"])
MAX_SEGMENT_BYTES = 20 * 1024 * 1024
MAX_ASSEMBLED_BYTES = 40 * 1024 * 1024
SAMPLE_RATE = 24_000


def _run(command: list[str], timeout: int = 180) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(command, check=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise HTTPException(status_code=504, detail="media operation timed out") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", "replace")[-1200:]
        raise HTTPException(status_code=422, detail=f"ffmpeg rejected media: {detail}") from error


async def _save_upload(upload: UploadFile, target: Path) -> None:
    payload = await upload.read(MAX_SEGMENT_BYTES + 1)
    if not payload or len(payload) > MAX_SEGMENT_BYTES:
        raise HTTPException(status_code=413, detail=f"invalid segment size: {upload.filename}")
    target.write_bytes(payload)


def _duration(path: Path) -> float:
    result = _run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ])
    return float(result.stdout.strip())


def _loudness(path: Path) -> tuple[float, float]:
    result = _run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
        "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-",
    ])
    text = result.stderr.decode("utf-8", "replace")
    matches = re.findall(r"\{\s*\"input_i\".*?\}", text, re.DOTALL)
    if not matches:
        raise HTTPException(status_code=422, detail="loudness analysis returned no metrics")
    metrics = json.loads(matches[-1])
    return float(metrics["input_i"]), float(metrics["input_tp"])


def _pcm_metrics(path: Path) -> tuple[int, float]:
    result = _run([
        "ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar",
        str(SAMPLE_RATE), "-f", "s16le", "-acodec", "pcm_s16le", "-",
    ])
    pcm = np.frombuffer(result.stdout, dtype="<i2")
    if not pcm.size:
        raise HTTPException(status_code=422, detail="decoded audio is empty")
    clipped = int(np.count_nonzero(np.abs(pcm.astype(np.int32)) >= 32767))
    threshold = int(round(32767 * math.pow(10, -50 / 20)))
    quiet = np.abs(pcm.astype(np.int32)) <= threshold
    changes = np.flatnonzero(np.diff(np.concatenate(([False], quiet, [False]))))
    runs = changes.reshape(-1, 2)
    minimum = int(0.8 * SAMPLE_RATE)
    long_silent_samples = int(sum(end - start for start, end in runs if end - start >= minimum))
    return clipped, long_silent_samples / int(pcm.size)


@router.get("/portable-health")
def portable_health() -> dict[str, object]:
    return {"ok": True, "assembly": "ffmpeg-visible-v1", "qa": "objective-visible-v1"}


@router.post("/assemble-six")
async def assemble_six(
    segment01: UploadFile = File(...),
    segment02: UploadFile = File(...),
    segment03: UploadFile = File(...),
    segment04: UploadFile = File(...),
    segment05: UploadFile = File(...),
    segment06: UploadFile = File(...),
) -> Response:
    uploads = [segment01, segment02, segment03, segment04, segment05, segment06]
    with tempfile.TemporaryDirectory(prefix="podcast-assemble-") as directory:
        root = Path(directory)
        inputs: list[Path] = []
        for index, upload in enumerate(uploads, start=1):
            target = root / f"segment-{index:02d}.mp3"
            await _save_upload(upload, target)
            inputs.append(target)
        output = root / "assembled.mp3"
        command = ["ffmpeg", "-hide_banner", "-y"]
        for path in inputs:
            command.extend(["-i", str(path)])
        labels = "".join(f"[{index}:a]aresample={SAMPLE_RATE}[a{index}];" for index in range(6))
        concat = "".join(f"[a{index}]" for index in range(6))
        command.extend([
            "-filter_complex", f"{labels}{concat}concat=n=6:v=0:a=1,loudnorm=I=-16:TP=-1.5:LRA=11[out]",
            "-map", "[out]", "-ar", str(SAMPLE_RATE), "-ac", "1", "-codec:a", "libmp3lame",
            "-b:a", "64k", str(output),
        ])
        _run(command, timeout=300)
        payload = output.read_bytes()
        if not payload or len(payload) > MAX_ASSEMBLED_BYTES:
            raise HTTPException(status_code=422, detail="assembled audio size is invalid")
    return Response(content=payload, media_type="audio/mpeg", headers={"X-Podcast-Segment-Count": "6"})


@router.post("/objective-qa")
async def objective_qa(audio: UploadFile = File(...)) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="podcast-qa-") as directory:
        path = Path(directory) / "audio.mp3"
        await _save_upload(audio, path)
        duration = _duration(path)
        integrated_lufs, true_peak_dbtp = _loudness(path)
        clipped_samples, silence_ratio = _pcm_metrics(path)
    return {
        "duration_seconds": round(duration, 3),
        "integrated_lufs": round(integrated_lufs, 2),
        "true_peak_dbtp": round(true_peak_dbtp, 2),
        "clipped_samples": clipped_samples,
        "long_silence_ratio": round(silence_ratio, 6),
        "sample_rate_hz": SAMPLE_RATE,
        "channels": 1,
    }
