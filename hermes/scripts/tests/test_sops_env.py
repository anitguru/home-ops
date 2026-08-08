from __future__ import annotations

import shlex
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sops_env


def test_social_post_mapping_uses_expected_sops_vendor_keys():
    calls: list[tuple[str, str]] = []

    def fake_reader(vendor: str, key: str) -> str:
        calls.append((vendor, key))
        return f"value-for-{vendor}-{key}"

    env = sops_env.collect_env("post", reader=fake_reader)

    assert env == {
        "X_CONSUMER_KEY": "value-for-x-CONSUMER_KEY",
        "X_CONSUMER_SECRET": "value-for-x-CONSUMER_SECRET",
        "X_ACCESS_TOKEN": "value-for-x-ACCESS_TOKEN",
        "X_ACCESS_TOKEN_SECRET": "value-for-x-ACCESS_TOKEN_SECRET",
        "TAVILY_API_TOKEN": "value-for-tavily-API_TOKEN",
        "PG_DSN": "value-for-postgres-DSN",
    }
    assert calls == [
        ("x", "CONSUMER_KEY"),
        ("x", "CONSUMER_SECRET"),
        ("x", "ACCESS_TOKEN"),
        ("x", "ACCESS_TOKEN_SECRET"),
        ("tavily", "API_TOKEN"),
        ("postgres", "DSN"),
    ]


def test_social_engage_mapping_omits_tavily():
    env = sops_env.collect_env("engage", reader=lambda vendor, key: f"{vendor}/{key}")

    assert "TAVILY_API_TOKEN" not in env
    assert env["PG_DSN"] == "postgres/DSN"


def test_podcast_mapping_uses_expected_sops_vendor_keys():
    calls: list[tuple[str, str]] = []

    def fake_reader(vendor: str, key: str) -> str:
        calls.append((vendor, key))
        return f"value-for-{vendor}-{key}"

    env = sops_env.collect_env("podcast", reader=fake_reader)

    assert env == {
        "CLOUDINARY_CLOUD_NAME": "value-for-cloudinary-CLOUD_NAME",
        "CLOUDINARY_API_KEY": "value-for-cloudinary-API_KEY",
        "CLOUDINARY_API_SECRET": "value-for-cloudinary-API_SECRET",
        "COCOINDEX_DATABASE_URL": "value-for-supabase-PG_DSN",
        "TTS_VOICE": "value-for-podcast-TTS_VOICE",
        "TTS_LOUDNORM": "value-for-podcast-TTS_LOUDNORM",
        "WHISPER_URL": "value-for-podcast-WHISPER_URL",
    }
    assert calls == [
        ("cloudinary", "CLOUD_NAME"),
        ("cloudinary", "API_KEY"),
        ("cloudinary", "API_SECRET"),
        ("supabase", "PG_DSN"),
        ("podcast", "TTS_VOICE"),
        ("podcast", "TTS_LOUDNORM"),
        ("podcast", "WHISPER_URL"),
    ]
    assert "TELEGRAM_BOT_TOKEN" not in env


def test_n8n_mcp_mapping_uses_expected_sops_vendor_keys():
    calls: list[tuple[str, str]] = []

    def fake_reader(vendor: str, key: str) -> str:
        calls.append((vendor, key))
        return f"value-for-{vendor}-{key}"

    env = sops_env.collect_env("n8n_mcp", reader=fake_reader)

    assert env == {
        "N8N_MCP_URL": "value-for-n8n-MCP_URL",
        "N8N_MCP_ACCESS_TOKEN": "value-for-n8n-MCP_ACCESS_TOKEN",
        "N8N_MCP_CONFIG_JSON": "value-for-n8n-MCP_CONFIG_JSON",
    }
    assert calls == [
        ("n8n", "MCP_URL"),
        ("n8n", "MCP_ACCESS_TOKEN"),
        ("n8n", "MCP_CONFIG_JSON"),
    ]


def test_n8n_runner_mapping_uses_expected_sops_vendor_key():
    calls: list[tuple[str, str]] = []

    def fake_reader(vendor: str, key: str) -> str:
        calls.append((vendor, key))
        return f"value-for-{vendor}-{key}"

    env = sops_env.collect_env("n8n_runner", reader=fake_reader)

    assert env == {
        "N8N_RUNNERS_AUTH_TOKEN": "value-for-n8n-RUNNER_AUTH_TOKEN",
    }
    assert calls == [("n8n", "RUNNER_AUTH_TOKEN")]


def test_n8n_podcast_mapping_uses_only_cloudinary_signing_keys():
    calls: list[tuple[str, str]] = []

    def fake_reader(vendor: str, key: str) -> str:
        calls.append((vendor, key))
        return f"value-for-{vendor}-{key}"

    env = sops_env.collect_env("n8n_podcast", reader=fake_reader)

    assert env == {
        "CLOUDINARY_CLOUD_NAME": "value-for-cloudinary-CLOUD_NAME",
        "CLOUDINARY_API_KEY": "value-for-cloudinary-API_KEY",
        "CLOUDINARY_API_SECRET": "value-for-cloudinary-API_SECRET",
    }
    assert calls == [
        ("cloudinary", "CLOUD_NAME"),
        ("cloudinary", "API_KEY"),
        ("cloudinary", "API_SECRET"),
    ]


def test_render_exports_shell_quotes_values_without_printing_labels_as_values():
    rendered = sops_env.render_exports({"TOKEN": "has spaces and 'quotes'"})

    expected_value = shlex.quote("has spaces and 'quotes'")
    assert rendered == f"export TOKEN={expected_value}"


def test_collect_env_reports_key_name_without_secret_value_on_failure():
    def broken_reader(vendor: str, key: str) -> str:
        raise sops_env.SecretError(f"lookup failed for {vendor}/{key}")

    with pytest.raises(sops_env.SecretError, match="x/CONSUMER_KEY"):
        sops_env.collect_env("post", reader=broken_reader)
