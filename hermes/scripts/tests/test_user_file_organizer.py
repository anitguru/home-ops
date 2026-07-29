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


def test_review_proposal_name_can_improve_deterministic_destination(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    cfg = base_cfg(tmp_path)
    cfg["local_naming"]["proposal_name_confidence_threshold"] = 0.90
    src = Path(cfg["user_home"]) / "Desktop" / "Screenshot 1.png"
    write_old(src, b"image")
    proposal_dir = Path(cfg["proposal_dir"])
    proposal_dir.mkdir(parents=True)
    proposal = {
        "source": str(src),
        "sha256": ufo.sha256(src),
        "size": src.stat().st_size,
        "mtime": src.stat().st_mtime,
        "name_confidence": 0.95,
        "destination_confidence": 0.2,
        "destination_key": "resource:review",
        "suggested_name": "2026-07-27-useful-dashboard.png",
    }
    (proposal_dir / "proposal.jsonl").write_text(json.dumps(proposal) + "\n")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(cfg))

    rc = ufo.run(config_path=config_path, mode="dry-run")
    summary = json.loads(capsys.readouterr().out)
    manifest = [json.loads(line) for line in Path(summary["manifest"]).read_text().splitlines()]
    action = next(row for row in manifest if row["source"] == str(src))

    assert rc == 0
    assert action["destination"].endswith(
        "File Intake/Screenshots/2026-07-27-useful-dashboard.png"
    )
    assert action["reason"] == "screenshots+validated-local-name"
    assert summary["counts"]["proposal_used"] == 1


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


def test_validated_name_can_be_used_for_in_place_review_rename(tmp_path: Path):
    cfg = base_cfg(tmp_path)
    src = Path(cfg["user_home"]) / "Desktop" / "HMeT1hYWIAAGtHA.jpg"
    write_old(src, b"image")
    proposal = {
        "source": str(src),
        "sha256": ufo.sha256(src),
        "size": src.stat().st_size,
        "mtime": src.stat().st_mtime,
        "name_confidence": 0.95,
        "destination_confidence": 0.2,
        "destination_key": "resource:review",
        "suggested_name": "woman-braiding-hair-with-book.jpg",
    }
    assert ufo.validated_proposal_name(src, proposal, 0.5) == (
        "woman-braiding-hair-with-book.jpg"
    )


def test_suggested_jpeg_alias_preserves_original_extension():
    source = Path("opaque.jpeg")

    assert ufo.sanitize_suggested_name("descriptive-photo.jpg", source) == (
        "descriptive-photo.jpeg"
    )
    assert ufo.sanitize_suggested_name("descriptive-photo.png", source) is None


def test_in_place_action_cannot_escape_source_directory(tmp_path: Path):
    cfg = base_cfg(tmp_path)
    src = Path(cfg["user_home"]) / "Desktop" / "opaque.jpg"
    write_old(src, b"image")
    safe = src.with_name("descriptive.jpg")
    assert ufo.apply_action(src, safe, True, cfg, allow_in_place=True) == safe
    escaped = Path(cfg["user_home"]) / "Downloads" / "escaped.jpg"
    with pytest.raises(ValueError, match="escaped source root"):
        ufo.apply_action(src, escaped, True, cfg, allow_in_place=True)


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


def test_allowlisted_area_uses_calibrated_confidence_threshold(tmp_path: Path):
    cfg = base_cfg(tmp_path)
    cfg["proposal_confidence_thresholds"] = {
        "area": 0.85,
        "project": 0.92,
        "resource": 0.92,
    }
    src = Path(cfg["user_home"]) / "Desktop" / "Screenshot 1.png"
    write_old(src, b"image")
    proposal = {
        "source": str(src),
        "sha256": ufo.sha256(src),
        "size": src.stat().st_size,
        "mtime": src.stat().st_mtime,
        "name_confidence": 0.90,
        "destination_confidence": 0.85,
        "destination_key": "area:work-meetings",
        "suggested_name": "2026-07-27-sentinelone-meeting-participants.png",
    }

    result = ufo.validate_proposal(src, proposal, cfg)

    assert result == (
        Path(cfg["user_home"])
        / "02-Areas"
        / "Work"
        / "File Intake"
        / "Meetings"
        / "2026-07-27-sentinelone-meeting-participants.png"
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


def test_recent_proposal_batches_are_merged_newest_first(tmp_path: Path):
    cfg = base_cfg(tmp_path)
    proposal_dir = Path(cfg["proposal_dir"])
    proposal_dir.mkdir(parents=True)
    first = {"source": "/tmp/first.png", "suggested_name": "first.png"}
    second_old = {"source": "/tmp/second.png", "suggested_name": "old.png"}
    second_new = {"source": "/tmp/second.png", "suggested_name": "new.png"}
    older = proposal_dir / "2026-07-27_010000.jsonl"
    newer = proposal_dir / "2026-07-27_020000.jsonl"
    older.write_text(json.dumps(first) + "\n" + json.dumps(second_old) + "\n")
    newer.write_text(json.dumps(second_new) + "\n")
    os.utime(older, (time.time() - 60, time.time() - 60))

    proposals = ufo.load_latest_proposals(cfg)

    assert proposals["/tmp/first.png"]["suggested_name"] == "first.png"
    assert proposals["/tmp/second.png"]["suggested_name"] == "new.png"


def test_generic_image_without_proposal_waits_for_local_naming(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    cfg = base_cfg(tmp_path)
    cfg["local_naming"].update(
        {
            "extensions": ["png", "jpg"],
            "generic_name_patterns": ["^Screenshot ", "^[A-Za-z0-9_-]{8,24}$"],
        }
    )
    src = Path(cfg["user_home"]) / "Desktop" / "HOOhnL2aYAAZpNS.jpg"
    write_old(src, b"image")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(cfg))

    rc = ufo.run(config_path=config_path, mode="dry-run")
    summary = json.loads(capsys.readouterr().out)
    manifest = [json.loads(line) for line in Path(summary["manifest"]).read_text().splitlines()]
    action = next(row for row in manifest if row["source"] == str(src))

    assert rc == 0
    assert action["action"] == "report"
    assert action["reason"] == "awaiting-local-name-proposal"
    assert "destination" not in action


def test_exact_duplicate_is_trashed_while_canonical_file_is_preserved(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    cfg = base_cfg(tmp_path)
    cfg["deduplication"] = {"enabled": True, "algorithm": "sha256", "action": "trash"}
    cfg["local_naming"].update(
        {
            "extensions": ["jpg"],
            "generic_name_patterns": [r"^[A-Za-z0-9_-]{8,24}(?: \([0-9]+\))?$"],
        }
    )
    desktop = Path(cfg["user_home"]) / "Desktop"
    canonical = desktop / "HOSKQ1dakAAJGLh.jpg"
    duplicate = desktop / "HOSKQ1dakAAJGLh (1).jpg"
    write_old(canonical, b"same-image")
    write_old(duplicate, b"same-image")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(cfg))

    rc = ufo.run(config_path=config_path, mode="apply")
    summary = json.loads(capsys.readouterr().out)
    manifest = [json.loads(line) for line in Path(summary["manifest"]).read_text().splitlines()]
    duplicate_action = next(row for row in manifest if row["source"] == str(duplicate))

    assert rc == 0
    assert canonical.exists()
    assert not duplicate.exists()
    assert (Path(cfg["user_home"]) / ".Trash" / duplicate.name).exists()
    assert duplicate_action["action"] == "trash"
    assert duplicate_action["reason"] == "exact-content-duplicate"
    assert duplicate_action["duplicate_of"] == str(canonical)
    assert summary["counts"]["deduplicated"] == 1


def test_same_size_different_content_is_not_deduplicated(tmp_path: Path):
    cfg = base_cfg(tmp_path)
    cfg["deduplication"] = {"enabled": True, "algorithm": "sha256", "action": "trash"}
    desktop = Path(cfg["user_home"]) / "Desktop"
    first = desktop / "first.bin"
    second = desktop / "second.bin"
    write_old(first, b"one")
    write_old(second, b"two")

    assert ufo.exact_duplicate_plan(cfg, min_age_minutes=0) == {}
    assert first.exists()
    assert second.exists()


def test_existing_intake_file_is_preserved_as_duplicate_keeper(tmp_path: Path):
    cfg = base_cfg(tmp_path)
    cfg["deduplication"] = {"enabled": True, "algorithm": "sha256", "action": "trash"}
    desktop = Path(cfg["user_home"]) / "Desktop"
    source = desktop / "descriptive-dashboard.png"
    intake = Path(cfg["para"]["resource_destinations"]["screenshots"])
    keeper = intake / "Screenshot 42.png"
    write_old(source, b"same-image")
    write_old(keeper, b"same-image")

    plan = ufo.exact_duplicate_plan(cfg, min_age_minutes=0)

    assert plan[str(source)]["keeper"] == str(keeper)
    assert str(keeper) not in plan


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


def test_rename_root_applies_fingerprinted_name_in_place(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    cfg = base_cfg(tmp_path)
    cfg["local_naming"]["rename_name_confidence_threshold"] = 0.5
    stash = Path(cfg["user_home"]) / "Pictures" / "stash"
    src = stash / "HMeT1hYWIAAGtHA.jpg"
    write_old(src, b"image")
    proposal_dir = Path(cfg["proposal_dir"])
    proposal_dir.mkdir(parents=True)
    proposal = {
        "source": str(src),
        "sha256": ufo.sha256(src),
        "size": src.stat().st_size,
        "mtime": src.stat().st_mtime,
        "name_confidence": 0.6,
        "destination_confidence": 0.0,
        "destination_key": "resource:review",
        "suggested_name": "woman-braiding-hair-with-book.jpg",
    }
    (proposal_dir / "proposal.jsonl").write_text(json.dumps(proposal) + "\n")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(cfg))

    rc = ufo.run(config_path=config_path, mode="apply", rename_root=stash)

    assert rc == 0
    assert not src.exists()
    assert (stash / "woman-braiding-hair-with-book.jpg").exists()
    summary = json.loads(capsys.readouterr().out)
    assert summary["counts"]["renamed"] == 1
    assert summary["counts"]["moved"] == 0
