#!/usr/bin/env python3
"""Resolve automation credentials from the local SOPS+age secret store.

The canonical store is read through the headless ``secret <vendor> <KEY>``
helper. Normal mode emits shell-quoted exports for deterministic cron wrappers;
``--check`` reports only key presence and never prints secret values.
"""
from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path


class SecretError(RuntimeError):
    """Safe secret lookup failure that never includes a secret value."""


SecretReader = Callable[[str, str], str]

PURPOSES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "post": (
        ("X_CONSUMER_KEY", "x", "CONSUMER_KEY"),
        ("X_CONSUMER_SECRET", "x", "CONSUMER_SECRET"),
        ("X_ACCESS_TOKEN", "x", "ACCESS_TOKEN"),
        ("X_ACCESS_TOKEN_SECRET", "x", "ACCESS_TOKEN_SECRET"),
        ("TAVILY_API_TOKEN", "tavily", "API_TOKEN"),
        ("PG_DSN", "postgres", "DSN"),
    ),
    "engage": (
        ("X_CONSUMER_KEY", "x", "CONSUMER_KEY"),
        ("X_CONSUMER_SECRET", "x", "CONSUMER_SECRET"),
        ("X_ACCESS_TOKEN", "x", "ACCESS_TOKEN"),
        ("X_ACCESS_TOKEN_SECRET", "x", "ACCESS_TOKEN_SECRET"),
        ("PG_DSN", "postgres", "DSN"),
    ),
    "radar": (
        ("X_CONSUMER_KEY", "x", "CONSUMER_KEY"),
        ("X_CONSUMER_SECRET", "x", "CONSUMER_SECRET"),
        ("X_ACCESS_TOKEN", "x", "ACCESS_TOKEN"),
        ("X_ACCESS_TOKEN_SECRET", "x", "ACCESS_TOKEN_SECRET"),
        ("PG_DSN", "postgres", "DSN"),
    ),
    "podcast": (
        ("CLOUDINARY_CLOUD_NAME", "cloudinary", "CLOUD_NAME"),
        ("CLOUDINARY_API_KEY", "cloudinary", "API_KEY"),
        ("CLOUDINARY_API_SECRET", "cloudinary", "API_SECRET"),
        ("COCOINDEX_DATABASE_URL", "supabase", "PG_DSN"),
        # TTS_URL intentionally NOT injected here: it is endpoint *config*, not a
        # secret, and a legacy value here clobbered the rgb-primary failover set
        # in run-podcast-pi4.sh. The run script is the single source of truth now.
        ("TTS_VOICE", "podcast", "TTS_VOICE"),
        ("TTS_LOUDNORM", "podcast", "TTS_LOUDNORM"),
        ("WHISPER_URL", "podcast", "WHISPER_URL"),
    ),
}


def secret_binary() -> str:
    configured = os.environ.get("SECRET_BIN")
    if configured:
        return str(Path(configured).expanduser())
    found = shutil.which("secret")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "secret"
    if fallback.exists():
        return str(fallback)
    raise SecretError("secret helper is not installed or not on PATH")


def get_secret(vendor: str, key: str, *, secret_bin: str | None = None) -> str:
    binary = secret_bin or secret_binary()
    try:
        result = subprocess.run(
            [binary, vendor, key],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SecretError(f"secret lookup failed for {vendor}/{key}: {type(exc).__name__}") from exc
    if result.returncode != 0:
        detail = (result.stderr or "secret helper exited non-zero").strip().splitlines()[0][:240]
        raise SecretError(f"secret lookup failed for {vendor}/{key}: {detail}")
    if not result.stdout:
        raise SecretError(f"secret lookup returned an empty value for {vendor}/{key}")
    return result.stdout


def collect_env(purpose: str, *, reader: SecretReader = get_secret) -> dict[str, str]:
    try:
        specs = PURPOSES[purpose]
    except KeyError as exc:
        raise SecretError(f"unknown SOPS secret purpose: {purpose}") from exc
    values: dict[str, str] = {}
    for env_name, vendor, key in specs:
        values[env_name] = reader(vendor, key)
    return values


def render_exports(values: dict[str, str]) -> str:
    return "\n".join(f"export {name}={shlex.quote(value)}" for name, value in values.items())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load automation secrets from the local SOPS+age store")
    parser.add_argument("--purpose", choices=sorted(PURPOSES), required=True)
    parser.add_argument("--check", action="store_true", help="report key presence only; never print values")
    args = parser.parse_args(argv)

    try:
        values = collect_env(args.purpose)
    except SecretError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.check:
        for name in values:
            print(f"{name}: set")
        return 0

    print(render_exports(values))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
