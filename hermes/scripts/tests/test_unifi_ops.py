import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unifi_ops


TEST_SOURCE_CONTEXT_KEY = "unit-test-source-context-key"


def source_context(
    *,
    source="local-sva",
    action="block",
    confirmation="confirm block Everett computer",
    expires_at=4_102_444_800,
):
    return unifi_ops.make_source_context(
        source=source,
        action=action,
        target=unifi_ops.resolve_target(["everett", "computer"]),
        confirmation=confirmation,
        key=TEST_SOURCE_CONTEXT_KEY,
        issued_at=1_700_000_000,
        expires_at=expires_at,
    )


class FakeUniFiApi:
    def __init__(self, client):
        self.client = dict(client)
        self.posts = []
        self.gets = []

    def pick_site_id(self, preferred=None):
        return preferred or "site-1"

    def find_clients(self, site_id, target):
        self.gets.append((site_id, target.mac_address))
        if self.client.get("macAddress") == target.mac_address:
            return [dict(self.client)]
        return []

    def get_client(self, site_id, client_id):
        return dict(self.client)

    def execute_client_action(self, site_id, client_id, payload):
        self.posts.append((site_id, client_id, payload))
        if payload["action"] == "BLOCK":
            self.client["access"] = {"type": "BLOCKED"}
        elif payload["action"] == "UNBLOCK":
            self.client["access"] = {"type": "DEFAULT"}
        return {"status": 200, "data": {"accepted": True}}


def everett_client(access_type="DEFAULT"):
    return {
        "id": "client-1",
        "name": "Everetts-Mac-Mini",
        "macAddress": "1c:f6:4c:3a:e8:13",
        "ipAddress": "10.0.0.182",
        "type": "WIRELESS",
        "uplinkDeviceId": "ap-1",
        "access": {"type": access_type},
    }


def test_resolves_pinned_everett_computer_alias_deterministically():
    target = unifi_ops.resolve_target(["Everett's", "computer"])

    assert target.canonical_alias == "Everett computer"
    assert target.mac_address == "1c:f6:4c:3a:e8:13"
    assert target.fixed_ip == "10.0.0.182"
    assert target.local_dns == "everettmacmini.transformers.lan"
    assert target.confirmation_phrase("block") == "confirm block Everett computer"


def test_preflight_is_read_only_and_returns_confirmation_phrase():
    api = FakeUniFiApi(everett_client("DEFAULT"))

    result = unifi_ops.run_operation("block", ["everett", "computer"], api=api, confirm=False)

    assert result["mutated"] is False
    assert result["requires_confirmation"] is True
    assert result["confirmation_phrase"] == "confirm block Everett computer"
    assert result["current_blocked"] is False
    assert result["target"]["mac_address"] == "1c:f6:4c:3a:e8:13"
    assert api.posts == []


def test_confirmed_block_posts_deterministic_action_and_verifies_afterward():
    api = FakeUniFiApi(everett_client("DEFAULT"))

    result = unifi_ops.run_operation(
        "block",
        ["everett", "computer"],
        api=api,
        confirm=True,
        request_source="local-sva",
        source_context=source_context(action="block"),
        source_context_key=TEST_SOURCE_CONTEXT_KEY,
        confirmation="confirm block Everett computer",
    )

    assert result["mutated"] is True
    assert result["verified"] is True
    assert result["current_blocked"] is False
    assert result["verified_blocked"] is True
    assert api.posts == [(unifi_ops.DEFAULT_SITE_ID, "client-1", {"action": "BLOCK"})]


def test_action_payloads_ignore_environment_overrides(monkeypatch):
    monkeypatch.setenv("UNIFI_OPS_BLOCK_ACTION", "DELETE")
    try:
        importlib.reload(unifi_ops)
        api = FakeUniFiApi(everett_client("DEFAULT"))

        unifi_ops.run_operation(
            "block",
            ["everett", "computer"],
            api=api,
            confirm=True,
            request_source="local-sva",
            source_context=source_context(action="block"),
            source_context_key=TEST_SOURCE_CONTEXT_KEY,
            confirmation="confirm block Everett computer",
        )

        assert api.posts == [(unifi_ops.DEFAULT_SITE_ID, "client-1", {"action": "BLOCK"})]
    finally:
        monkeypatch.delenv("UNIFI_OPS_BLOCK_ACTION", raising=False)
        importlib.reload(unifi_ops)


def test_confirmed_unblock_is_idempotent_when_already_unblocked():
    api = FakeUniFiApi(everett_client("DEFAULT"))

    result = unifi_ops.run_operation(
        "unblock",
        ["Everett", "computer"],
        api=api,
        confirm=True,
        request_source="local-sva",
        source_context=source_context(action="unblock", confirmation="confirm unblock Everett computer"),
        source_context_key=TEST_SOURCE_CONTEXT_KEY,
        confirmation="confirm unblock Everett computer",
    )

    assert result["mutated"] is False
    assert result["idempotent"] is True
    assert result["verified"] is True
    assert result["verified_blocked"] is False
    assert api.posts == []


def test_mutation_fails_safe_when_alias_is_ambiguous():
    api = FakeUniFiApi(everett_client("DEFAULT"))

    with pytest.raises(unifi_ops.AliasError):
        unifi_ops.run_operation("block", ["everett"], api=api, confirm=True)

    assert api.posts == []


def test_live_api_client_lookup_uses_only_filterable_mac_and_ip_fields():
    class RecordingApi(unifi_ops.UniFiApi):
        def __init__(self):
            self.filters = []

        def request(self, method, path, body=None, query=None):
            assert query is not None
            self.filters.append(query["filter"])
            return {"data": []}

    api = RecordingApi()
    target = unifi_ops.resolve_target(["everett", "computer"])

    api.find_clients("site-1", target)

    assert api.filters == ["macAddress.eq('1c:f6:4c:3a:e8:13')", "ipAddress.eq('10.0.0.182')"]


def test_mutation_denies_missing_request_source_before_posting():
    api = FakeUniFiApi(everett_client("DEFAULT"))

    with pytest.raises(unifi_ops.PermissionDeniedError):
        unifi_ops.run_operation(
            "block",
            ["everett", "computer"],
            api=api,
            confirm=True,
            confirmation="confirm block Everett computer",
        )

    assert api.posts == []


def test_mutation_denies_wrong_confirmation_before_posting():
    api = FakeUniFiApi(everett_client("DEFAULT"))

    with pytest.raises(unifi_ops.ConfirmationError):
        unifi_ops.run_operation(
            "block",
            ["everett", "computer"],
            api=api,
            confirm=True,
            request_source="local-sva",
            source_context=source_context(action="block"),
            source_context_key=TEST_SOURCE_CONTEXT_KEY,
            confirmation="confirm block Everett",
        )

    assert api.posts == []


def test_mutation_denies_spoofed_request_source_without_trusted_context():
    api = FakeUniFiApi(everett_client("DEFAULT"))

    with pytest.raises(unifi_ops.PermissionDeniedError):
        unifi_ops.run_operation(
            "block",
            ["everett", "computer"],
            api=api,
            confirm=True,
            request_source="local-sva",
            confirmation="confirm block Everett computer",
        )

    assert api.posts == []


def test_mutation_denies_tampered_source_context_before_posting():
    api = FakeUniFiApi(everett_client("DEFAULT"))
    tampered_context = source_context(action="block")[:-1] + "0"

    with pytest.raises(unifi_ops.PermissionDeniedError):
        unifi_ops.run_operation(
            "block",
            ["everett", "computer"],
            api=api,
            confirm=True,
            request_source="local-sva",
            source_context=tampered_context,
            source_context_key=TEST_SOURCE_CONTEXT_KEY,
            confirmation="confirm block Everett computer",
        )

    assert api.posts == []


def test_mutation_denies_expired_source_context_before_posting():
    api = FakeUniFiApi(everett_client("DEFAULT"))

    with pytest.raises(unifi_ops.PermissionDeniedError):
        unifi_ops.run_operation(
            "block",
            ["everett", "computer"],
            api=api,
            confirm=True,
            request_source="local-sva",
            source_context=source_context(action="block", expires_at=1),
            source_context_key=TEST_SOURCE_CONTEXT_KEY,
            confirmation="confirm block Everett computer",
        )

    assert api.posts == []


def test_mutation_denies_mismatched_signed_source_context_before_posting():
    api = FakeUniFiApi(everett_client("DEFAULT"))

    with pytest.raises(unifi_ops.PermissionDeniedError):
        unifi_ops.run_operation(
            "block",
            ["everett", "computer"],
            api=api,
            confirm=True,
            request_source="vanfam-telegram",
            source_context=source_context(source="sva-dm", action="block"),
            source_context_key=TEST_SOURCE_CONTEXT_KEY,
            confirmation="confirm block Everett computer",
        )

    assert api.posts == []


def test_cli_confirm_requires_explicit_request_source_even_if_env_set(monkeypatch, capsys):
    monkeypatch.setenv("UNIFI_OPS_REQUEST_SOURCE", "local-sva")
    monkeypatch.setenv("UNIFI_OPS_ACTUAL_REQUEST_SOURCE", "local-sva")
    monkeypatch.setenv("UNIFI_OPS_SOURCE_CONTEXT_KEY", TEST_SOURCE_CONTEXT_KEY)
    api = FakeUniFiApi(everett_client("DEFAULT"))
    monkeypatch.setattr(unifi_ops, "UniFiApi", lambda: api)

    exit_code = unifi_ops.main(
        ["block", "everett", "computer", "--confirm", "--confirmation", "confirm block Everett computer"]
    )

    assert exit_code == 1
    assert api.posts == []
    assert "require --request-source" in capsys.readouterr().err


def test_cli_ignores_caller_controlled_env_source_context_key(monkeypatch, capsys):
    monkeypatch.setenv("UNIFI_OPS_SOURCE_CONTEXT_KEY", TEST_SOURCE_CONTEXT_KEY)
    monkeypatch.setattr(unifi_ops, "load_source_context_key", lambda: "vault-backed-key")
    api = FakeUniFiApi(everett_client("DEFAULT"))
    monkeypatch.setattr(unifi_ops, "UniFiApi", lambda: api)

    exit_code = unifi_ops.main(
        [
            "block",
            "everett",
            "computer",
            "--confirm",
            "--request-source",
            "local-sva",
            "--source-context",
            source_context(action="block"),
            "--confirmation",
            "confirm block Everett computer",
        ]
    )

    assert exit_code == 1
    assert api.posts == []
    assert "source context signature is invalid" in capsys.readouterr().err


def test_mutation_denies_untrusted_request_source_before_posting():
    api = FakeUniFiApi(everett_client("DEFAULT"))

    with pytest.raises(unifi_ops.PermissionDeniedError):
        unifi_ops.run_operation(
            "block",
            ["everett", "computer"],
            api=api,
            confirm=True,
            request_source="random-public-chat",
            confirmation="confirm block Everett computer",
        )

    assert api.posts == []


def test_mutation_fails_safe_when_device_is_missing():
    api = FakeUniFiApi({"id": "other", "macAddress": "aa:bb:cc:dd:ee:ff"})

    with pytest.raises(unifi_ops.DeviceLookupError):
        unifi_ops.run_operation(
            "block",
            ["everett", "computer"],
            api=api,
            confirm=True,
            request_source="local-sva",
            source_context=source_context(action="block"),
            source_context_key=TEST_SOURCE_CONTEXT_KEY,
            confirmation="confirm block Everett computer",
        )

    assert api.posts == []


def test_mutation_denies_site_override_before_posting():
    api = FakeUniFiApi(everett_client("DEFAULT"))

    with pytest.raises(unifi_ops.PermissionDeniedError):
        unifi_ops.run_operation(
            "block",
            ["everett", "computer"],
            api=api,
            confirm=True,
            site_id="other-site",
            request_source="local-sva",
            source_context=source_context(action="block"),
            source_context_key=TEST_SOURCE_CONTEXT_KEY,
            confirmation="confirm block Everett computer",
        )

    assert api.posts == []


def test_live_api_uses_pinned_default_site_without_listing_sites():
    class RecordingApi(unifi_ops.UniFiApi):
        def __init__(self):
            self.requests = []

        def request(self, method, path, body=None, query=None):
            self.requests.append((method, path, query))
            return {"data": []}

    api = RecordingApi()

    assert api.pick_site_id() == unifi_ops.DEFAULT_SITE_ID
    assert api.requests == []
    assert api.pick_site_id("override-site") == "override-site"


def test_top_level_common_args_are_preserved_for_subcommands(monkeypatch, capsys):
    api = FakeUniFiApi(everett_client("DEFAULT"))
    monkeypatch.setattr(unifi_ops, "UniFiApi", lambda: api)

    exit_code = unifi_ops.main(["--site-id", "site-2", "--json", "blocked", "everett", "computer"])

    assert exit_code == 0
    assert api.gets == [("site-2", "1c:f6:4c:3a:e8:13")]
    assert '"site_id": "site-2"' in capsys.readouterr().out
