from __future__ import annotations

import base64

import pytest

from webapp.supabase_gateway import AuthIdentity, SupabaseGateway, SupabaseUnavailable


def configured_gateway(monkeypatch) -> SupabaseGateway:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test")
    monkeypatch.setenv("SUPABASE_USERNAME_DOMAIN", "contasapagar.local")
    monkeypatch.setenv("PERSISTENT_BASE_KEY_B64", base64.urlsafe_b64encode(bytes(range(32))).decode())
    return SupabaseGateway()


def test_base_is_encrypted_before_persistence_and_authenticated_on_load(monkeypatch):
    gateway = configured_gateway(monkeypatch)
    stored = {}

    def request(method, endpoint, *, api_key, payload=None, extra_headers=None):
        if method == "POST":
            stored.update(payload)
            return None
        return [{key: stored[key] for key in ("ciphertext", "nonce", "revision", "row_count")}]

    monkeypatch.setattr(gateway, "_request_json", request)
    items = [{"supplier_code": "42", "supplier": "FORNECEDOR SECRETO", "flow": "FLUXO A", "category": "CAT A"}]
    revision = gateway.save_base("00000000-0000-0000-0000-000000000001", items)
    assert revision == stored["revision"]
    assert "FORNECEDOR SECRETO" not in stored["ciphertext"]
    assert gateway.load_base("00000000-0000-0000-0000-000000000001") == (items, revision)


def test_login_uses_technical_email_but_returns_plain_username(monkeypatch):
    gateway = configured_gateway(monkeypatch)
    captured = {}

    def request(method, endpoint, *, api_key, payload=None, extra_headers=None):
        captured.update(payload)
        return {"user": {"id": "user-1", "email": "alan@contasapagar.local"}}

    monkeypatch.setattr(gateway, "_request_json", request)
    identity = gateway.sign_in("Alan", "senha-de-teste")
    assert identity == AuthIdentity("user-1", "alan", "alan@contasapagar.local")
    assert captured == {"email": "alan@contasapagar.local", "password": "senha-de-teste"}


def test_gateway_fails_closed_without_external_configuration(monkeypatch):
    for name in (
        "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SECRET_KEY",
        "PERSISTENT_BASE_KEY_B64",
    ):
        monkeypatch.delenv(name, raising=False)
    gateway = SupabaseGateway()
    with pytest.raises(SupabaseUnavailable):
        gateway.sign_in("alan", "qualquer")
