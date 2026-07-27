from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))
import para_file_namer as pfn  # noqa: E402


def naming_cfg(tmp_path: Path) -> dict:
    home = tmp_path / "home"
    downloads = home / "Downloads"
    downloads.mkdir(parents=True)
    return {
        "user_home": str(home),
        "min_age_minutes": 0,
        "manifest_dir": str(home / "runtime" / "manifests"),
        "report_dir": str(home / "runtime" / "reports"),
        "proposal_dir": str(home / "runtime" / "proposals"),
        "proposal_confidence_threshold": 0.92,
        "never_touch_names": [],
        "never_touch_paths": [],
        "para": {
            "resource_destinations": {
                "review": str(home / "03-Resources" / "Needs Review")
            },
            "allowed_projects": {},
            "allowed_areas": {},
        },
        "allow_roots": [{"path": str(downloads), "clean_root": True}],
        "rules": [],
        "local_naming": {
            "model": "test-model",
            "endpoint": "http://127.0.0.1:11434",
            "max_items": 12,
            "max_run_seconds": 1200,
            "request_timeout_seconds": 120,
            "max_file_bytes": 1024 * 1024,
            "extensions": ["png"],
            "generic_name_patterns": ["^IMG_[0-9]+"],
        },
    }


def old_file(path: Path, content: bytes = b"image") -> None:
    path.write_bytes(content)
    old = time.time() - 7200
    os.utime(path, (old, old))


def test_repo_opaque_pattern_excludes_normal_lowercase_kebab_names():
    cfg = pfn.load_config(
        Path("/Users/sva/01-Projects/home-ops/hermes/file-organizer/file-organization.json")
    )
    patterns = cfg["local_naming"]["generic_name_patterns"]
    assert pfn.is_generic_name(Path("HOOhnL2aYAAZpNS.jpg"), patterns)
    assert not pfn.is_generic_name(Path("bong-wide-angle.jpg"), patterns)


def test_candidates_skip_symlinks_before_resolving_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cfg = naming_cfg(tmp_path)
    downloads = Path(cfg["allow_roots"][0]["path"])
    link = downloads / "IMG_1234.png"
    link.symlink_to(downloads / "missing-target.png")
    original_resolve = Path.resolve

    def guarded_resolve(self: Path, *args, **kwargs):
        if self == link:
            raise AssertionError("candidate discovery followed a symlink")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", guarded_resolve)
    assert pfn.candidates(cfg) == []


def test_successful_proposal_is_persisted_before_a_later_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    cfg = naming_cfg(tmp_path)
    downloads = Path(cfg["allow_roots"][0]["path"])
    first = downloads / "IMG_1001.png"
    second = downloads / "IMG_1002.png"
    old_file(first, b"first")
    old_file(second, b"second")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(cfg))
    calls = 0

    def classify(path: Path, _cfg: dict):
        nonlocal calls
        calls += 1
        if calls == 2:
            manifests = list(Path(cfg["proposal_dir"]).glob("*.jsonl"))
            assert len(manifests) == 1
            persisted = [json.loads(line) for line in manifests[0].read_text().splitlines()]
            assert [row["source"] for row in persisted] == [str(first)]
            raise RuntimeError("synthetic second-item failure")
        return (
            {
                "suggested_name": "first-useful-image.png",
                "destination_key": "resource:review",
                "name_confidence": 0.95,
                "destination_confidence": 0.8,
                "summary": "test",
                "reason": "test",
                "model": "test-model",
            },
            0.1,
        )

    monkeypatch.setattr(pfn, "ollama_classify", classify)
    rc = pfn.run(config_path)
    summary = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert summary["proposals"] == 1
    assert summary["errors"] == 1
    assert Path(summary["proposal_manifest"]).exists()
    assert "synthetic second-item failure" in Path(summary["report"]).read_text()


def test_run_stops_cleanly_at_internal_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    cfg = naming_cfg(tmp_path)
    cfg["local_naming"]["max_run_seconds"] = 10
    downloads = Path(cfg["allow_roots"][0]["path"])
    first = downloads / "IMG_2001.png"
    second = downloads / "IMG_2002.png"
    old_file(first, b"first")
    old_file(second, b"second")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(cfg))

    monkeypatch.setattr(
        pfn,
        "ollama_classify",
        lambda path, cfg: (
            {
                "suggested_name": f"useful-{path.stem.lower()}.png",
                "destination_key": "resource:review",
                "name_confidence": 0.95,
                "destination_confidence": 0.8,
                "summary": "test",
                "reason": "test",
                "model": "test-model",
            },
            0.1,
        ),
    )
    monotonic_values = iter([0.0, 0.0, 11.0])
    monkeypatch.setattr(pfn.time, "monotonic", lambda: next(monotonic_values))

    rc = pfn.run(config_path)
    summary = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert summary["proposals"] == 1
    assert summary["deferred"] == 1
    assert summary["deadline_reached"] is True
