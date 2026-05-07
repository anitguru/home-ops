#!/usr/bin/env python3
"""Subscription-backed LLM bridge for automation scripts.

This module intentionally routes generative work through Hermes profiles instead
of direct vendor SDKs or provider-specific CLIs. It also strips Anthropic env vars
from the child process so legacy CI secrets cannot accidentally re-enable direct
Claude API usage.
"""
from __future__ import annotations

import os
import re
import subprocess
from shutil import which


def hermes_available() -> bool:
    return bool(which(os.getenv("HERMES_BIN", "hermes")))


def strip_code_fences(text: str) -> str:
    raw = text.strip()
    raw = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return raw.strip()


def run_hermes_prompt(
    prompt: str,
    *,
    profile: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    timeout: int = 300,
    source: str = "automation-script",
) -> str:
    """Run a non-interactive Hermes one-shot and return stdout text.

    Default profile is selected by HERMES_AUTOMATION_PROFILE. The caller should
    set that to a specialty one-shot profile such as ``xposting`` or
    ``xengaging`` while the default profile remains the persistent cron owner.
    If unset, Hermes' default profile is used; never fall back to the retired
    Gitea/automations profile.
    """
    hermes_bin = os.getenv("HERMES_BIN", "hermes")
    profile = profile if profile is not None else os.getenv("HERMES_AUTOMATION_PROFILE", "")

    cmd = [hermes_bin]
    if profile:
        cmd.extend(["-p", profile])
    cmd.extend(["chat", "-q", prompt, "--quiet", "--source", source])
    if provider:
        cmd.extend(["--provider", provider])
    if model:
        cmd.extend(["-m", model])

    env = os.environ.copy()
    for key in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_TOKEN",
        "CLAUDE_API_KEY",
        "HERMES_TUI",
        "HERMES_TUI_ACTIVE_SESSION_FILE",
        "HERMES_GATEWAY_SESSION",
        "HERMES_INTERACTIVE",
        "HERMES_SESSION_KEY",
    ):
        env.pop(key, None)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Hermes one-shot failed: {result.stderr.strip()[:500]}")
    return strip_code_fences(result.stdout)
