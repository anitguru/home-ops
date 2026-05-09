"""Runtime state paths for the @anitdotguru X/social automation.

State changes on every scheduled post/engagement run. Keep it outside the
version-controlled checkout by default so successful Hermes cron runs do not
leave home-ops dirty. Set X_SOCIAL_STATE_DIR to override the location.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEGACY_STATE_DIR = ROOT / "state"


def state_dir() -> Path:
    """Return the directory that holds mutable X/social runtime state."""
    explicit = os.environ.get("X_SOCIAL_STATE_DIR")
    if explicit:
        return Path(explicit).expanduser()

    hermes_state = os.environ.get("HERMES_STATE_DIR")
    if hermes_state:
        return Path(hermes_state).expanduser() / "x-social"

    return Path.home() / ".local" / "state" / "home-ops" / "x-social"


def state_file(name: str, *, seed_from_legacy: bool = True) -> Path:
    """Return a mutable state file path, seeding it from the old repo path.

    The legacy repo-local state path is intentionally no longer tracked by git,
    but seeding from it keeps existing checkouts from losing their current ledger
    or cursor when this migration first lands.
    """
    path = state_dir() / name
    if seed_from_legacy and not path.exists():
        legacy = LEGACY_STATE_DIR / name
        if legacy.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy, path)
    return path


POSTS_HISTORY = state_file("posts.jsonl")
ENGAGE_CURSOR = state_file("engage_cursor.json")
