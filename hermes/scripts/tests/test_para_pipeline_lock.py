from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest


HELPER = Path(__file__).resolve().parents[1] / "para_pipeline_lock.sh"


def test_stale_lock_without_owner_is_reclaimed(tmp_path: Path):
    lockdir = tmp_path / "pipeline.lock"
    lockdir.mkdir()
    old = time.time() - 7200
    os.utime(lockdir, (old, old))

    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; acquire_para_pipeline_lock; printf acquired; cleanup_para_pipeline_lock',
            "test",
            str(HELPER),
        ],
        env={**os.environ, "HERMES_PARA_LOCKDIR": str(lockdir)},
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "acquired"
    assert not lockdir.exists()


def test_live_owner_lock_is_not_stolen(tmp_path: Path):
    lockdir = tmp_path / "pipeline.lock"
    lockdir.mkdir()
    (lockdir / "pid").write_text(str(os.getpid()))

    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; if acquire_para_pipeline_lock; then printf stolen; else printf busy; fi',
            "test",
            str(HELPER),
        ],
        env={**os.environ, "HERMES_PARA_LOCKDIR": str(lockdir)},
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "busy"
    assert lockdir.exists()


def test_captured_child_failure_status_and_output_are_preserved(tmp_path: Path):
    lockdir = tmp_path / "pipeline.lock"
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; acquire_para_pipeline_lock; '
            'run_para_pipeline_command bash -c "printf child-failed; exit 7"; '
            'status=$?; printf "%s:%s" "$status" "$HERMES_PARA_OUTPUT"; exit 0',
            "test",
            str(HELPER),
        ],
        env={**os.environ, "HERMES_PARA_LOCKDIR": str(lockdir)},
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "7:child-failed"
    assert not lockdir.exists()


def test_terminating_wrapper_kills_child_and_cleans_lock(tmp_path: Path):
    lockdir = tmp_path / "pipeline.lock"
    child_pid_file = tmp_path / "child.pid"
    command = (
        'source "$1"; acquire_para_pipeline_lock; '
        'run_para_pipeline_command python3 -c '
        "'import os,time,pathlib; pathlib.Path(os.environ[\"CHILD_PID_FILE\"]).write_text(str(os.getpid())); time.sleep(60)'"
    )
    process = subprocess.Popen(
        ["bash", "-c", command, "test", str(HELPER)],
        env={
            **os.environ,
            "HERMES_PARA_LOCKDIR": str(lockdir),
            "CHILD_PID_FILE": str(child_pid_file),
        },
    )
    deadline = time.time() + 5
    while not child_pid_file.exists() and time.time() < deadline:
        time.sleep(0.02)
    assert child_pid_file.exists()
    child_pid = int(child_pid_file.read_text())

    process.send_signal(signal.SIGTERM)
    process.wait(timeout=5)

    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
    assert not lockdir.exists()
