from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))
import user_file_organizer as ufo  # noqa: E402


def base_cfg(tmp_path: Path) -> dict:
    home = tmp_path / "home"
    desktop = home / "Desktop"
    downloads = home / "Downloads"
    for path in [
        desktop,
        downloads,
        home / "01-Projects" / "mission-control",
        home / "02-Areas" / "Work",
        home / "03-Resources",
    ]:
        path.mkdir(parents=True, exist_ok=True)
    return {
        "user_home": str(home),
        "min_age_minutes": 0,
        "max_auto_actions": 10,
        "manifest_dir": str(home / "runtime" / "manifests"),
        "report_dir": str(home / "runtime" / "reports"),
        "proposal_dir": str(home / "runtime" / "proposals"),
        "proposal_max_age_hours": 24,
        "proposal_confidence_threshold": 0.92,
        "local_naming": {
            "review_name_confidence_threshold": 0.9,
            "review_destination_confidence_threshold": 0.75,
        },
        "never_touch_names": ["01-Projects", "02-Areas", "03-Resources"],
        "never_touch_paths": [
            str(home / "01-Projects"),
            str(home / "02-Areas"),
            str(home / "03-Resources"),
        ],
        "para": {
            "resource_destinations": {
                "screenshots": str(home / "03-Resources" / "File Intake" / "Screenshots"),
                "downloads": str(home / "03-Resources" / "File Intake" / "Downloads"),
                "review": str(home / "03-Resources" / "File Intake" / "Needs Review"),
            },
            "allowed_projects": {
                "mission-control": {
                    "path": str(home / "01-Projects" / "mission-control"),
                    "incoming_subdir": "Incoming",
                }
            },
            "allowed_areas": {
                "work-meetings": {
                    "path": str(home / "02-Areas" / "Work"),
                    "incoming_subdir": "File Intake/Meetings",
                }
            },
        },
        "allow_roots": [
            {
                "path": str(desktop),
                "clean_root": True,
                "move_directories": False,
                "fallback_key": "screenshots",
            },
            {
                "path": str(downloads),
                "clean_root": True,
                "move_directories": False,
                "fallback_key": "downloads",
            },
        ],
        "rules": [
            {
                "name": "installers",
                "roots": [str(downloads)],
                "extensions": ["dmg"],
                "action": "trash",
            },
            {
                "name": "screenshots",
                "extensions": ["png"],
                "action": "move",
                "destination_key": "screenshots",
            },
        ],
    }


def write_old(path: Path, content: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    old = time.time() - 7200
    os.utime(path, (old, old))


def test_installer_rule_is_root_scoped(tmp_path: Path):
    cfg = base_cfg(tmp_path)
    home = Path(cfg["user_home"])
    desktop_dmg = home / "Desktop" / "keep.dmg"
    download_dmg = home / "Downloads" / "trash.dmg"
    write_old(desktop_dmg)
    write_old(download_dmg)
    assert ufo.match_rule(desktop_dmg, cfg) is None
    assert ufo.match_rule(download_dmg, cfg)["name"] == "installers"


def test_high_confidence_resource_proposal_is_accepted(tmp_path: Path):
    cfg = base_cfg(tmp_path)
    src = Path(cfg["user_home"]) / "Desktop" / "Screenshot 1.png"
    write_old(src, b"image")
    proposal = {
        "source": str(src),
        "sha256": ufo.sha256(src),
        "size": src.stat().st_size,
        "mtime": src.stat().st_mtime,
        "confidence": 0.97,
        "destination_key": "resource:screenshots",
        "suggested_name": "2026-07-26-hermes-profile-sync.png",
    }
    result = ufo.validate_proposal(src, proposal, cfg)
    assert result is not None
    assert result.name == "2026-07-26-hermes-profile-sync.png"
    assert "File Intake/Screenshots" in str(result)


def test_low_confidence_proposal_is_rejected(tmp_path: Path):
    cfg = base_cfg(tmp_path)
    src = Path(cfg["user_home"]) / "Desktop" / "Screenshot 1.png"
    write_old(src, b"image")
    proposal = {
        "source": str(src),
        "sha256": ufo.sha256(src),
        "size": src.stat().st_size,
        "mtime": src.stat().st_mtime,
        "confidence": 0.7,
        "destination_key": "resource:screenshots",
        "suggested_name": "useful.png",
    }
    assert ufo.validate_proposal(src, proposal, cfg) is None


def test_review_proposal_can_use_separate_name_and_destination_confidence(tmp_path: Path):
    cfg = base_cfg(tmp_path)
    cfg["local_naming"]["auto_apply_review"] = True
    src = Path(cfg["user_home"]) / "Desktop" / "IMG_1234.jpg"
    write_old(src, b"image")
    proposal = {
        "source": str(src),
        "sha256": ufo.sha256(src),
        "size": src.stat().st_size,
        "mtime": src.stat().st_mtime,
        "name_confidence": 0.97,
        "destination_confidence": 0.8,
        "destination_key": "resource:review",
        "suggested_name": "ruckus-r770-access-point-label.jpg",
    }
    result = ufo.validate_proposal(src, proposal, cfg)
    assert result is not None
    assert result.parent.name == "Needs Review"


def test_review_proposal_is_not_auto_applied_by_default(tmp_path: Path):
    cfg = base_cfg(tmp_path)
    src = Path(cfg["user_home"]) / "Desktop" / "IMG_1234.jpg"
    write_old(src, b"image")
    proposal = {
        "source": str(src),
        "sha256": ufo.sha256(src),
        "size": src.stat().st_size,
        "mtime": src.stat().st_mtime,
        "name_confidence": 0.99,
        "destination_confidence": 0.99,
        "destination_key": "resource:review",
        "suggested_name": "possibly-hallucinated-proper-name.jpg",
    }
    assert ufo.validate_proposal(src, proposal, cfg) is None


def test_changed_file_proposal_is_rejected(tmp_path: Path):
    cfg = base_cfg(tmp_path)
    src = Path(cfg["user_home"]) / "Desktop" / "Screenshot 1.png"
    write_old(src, b"original")
    proposal = {
        "source": str(src),
        "sha256": ufo.sha256(src),
        "size": src.stat().st_size,
        "mtime": src.stat().st_mtime,
        "confidence": 0.99,
        "destination_key": "resource:screenshots",
        "suggested_name": "useful.png",
    }
    src.write_bytes(b"changed")
    assert ufo.validate_proposal(src, proposal, cfg) is None


def test_allowlisted_project_proposal_routes_to_incoming(tmp_path: Path):
    cfg = base_cfg(tmp_path)
    src = Path(cfg["user_home"]) / "Desktop" / "Screenshot 1.png"
    write_old(src, b"image")
    proposal = {
        "source": str(src),
        "sha256": ufo.sha256(src),
        "size": src.stat().st_size,
        "mtime": src.stat().st_mtime,
        "confidence": 0.98,
        "destination_key": "project:mission-control",
        "suggested_name": "analytics-panel.png",
    }
    result = ufo.validate_proposal(src, proposal, cfg)
    assert result == (
        Path(cfg["user_home"])
        / "01-Projects"
        / "mission-control"
        / "Incoming"
        / "analytics-panel.png"
    )


def test_unallowlisted_area_proposal_is_rejected(tmp_path: Path):
    cfg = base_cfg(tmp_path)
    src = Path(cfg["user_home"]) / "Desktop" / "Screenshot 1.png"
    write_old(src, b"image")
    proposal = {
        "source": str(src),
        "sha256": ufo.sha256(src),
        "size": src.stat().st_size,
        "mtime": src.stat().st_mtime,
        "confidence": 0.99,
        "destination_key": "area:personal",
        "suggested_name": "private.png",
    }
    assert ufo.validate_proposal(src, proposal, cfg) is None


def test_collision_safe_preserves_existing(tmp_path: Path):
    dest = tmp_path / "name.png"
    dest.write_bytes(b"one")
    assert ufo.collision_safe(dest) == tmp_path / "name (1).png"


def test_exact_directory_rule_routes_but_unmatched_directory_is_reported(tmp_path: Path):
    cfg = base_cfg(tmp_path)
    downloads = Path(cfg["user_home"]) / "Downloads"
    cfg["allow_roots"][1]["move_directories"] = True
    cfg["rules"].insert(
        0,
        {
            "name": "work-transcripts",
            "roots": [str(downloads)],
            "kinds": ["directory"],
            "filename_patterns": ["dot foods.*transcript"],
            "action": "move",
            "destination_key": "area:work-meetings",
        },
    )
    matched = downloads / "Dot Foods transcript"
    unmatched = downloads / "Omi Exports"
    matched.mkdir()
    unmatched.mkdir()
    assert ufo.deterministic_classify(matched, cfg["allow_roots"][1], cfg)[0] == "move"
    assert ufo.deterministic_classify(unmatched, cfg["allow_roots"][1], cfg) == (
        "report",
        None,
        "unmatched-directory",
    )


def test_repo_config_hard_protects_dotfiles():
    cfg = ufo.load_config(
        Path("/Users/sva/01-Projects/home-ops/hermes/file-organizer/file-organization.json")
    )
    assert "dotfiles" in cfg["never_touch_names"]
    assert "/Users/sva/dotfiles" in cfg["never_touch_paths"]


def test_main_dry_run_writes_manifest_without_moving(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    cfg = base_cfg(tmp_path)
    src = Path(cfg["user_home"]) / "Desktop" / "Screenshot 1.png"
    write_old(src, b"image")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(cfg))
    rc = ufo.run(config_path=config_path, mode="dry-run")
    assert rc == 0
    assert src.exists()
    summary = json.loads(capsys.readouterr().out)
    assert summary["counts"]["planned"] == 1
    assert Path(summary["manifest"]).exists()
