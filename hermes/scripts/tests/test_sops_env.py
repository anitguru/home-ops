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


def test_render_exports_shell_quotes_values_without_printing_labels_as_values():
    rendered = sops_env.render_exports({"TOKEN": "has spaces and 'quotes'"})

    expected_value = shlex.quote("has spaces and 'quotes'")
    assert rendered == f"export TOKEN={expected_value}"


def test_collect_env_reports_key_name_without_secret_value_on_failure():
    def broken_reader(vendor: str, key: str) -> str:
        raise sops_env.SecretError(f"lookup failed for {vendor}/{key}")

    with pytest.raises(sops_env.SecretError, match="x/CONSUMER_KEY"):
        sops_env.collect_env("post", reader=broken_reader)
