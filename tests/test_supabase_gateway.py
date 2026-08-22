from __future__ import annotations

import base64

import pytest

from webapp.supabase_gateway import (
    AuthIdentity,
    AuthenticationRejected,
    AuthorizedUser,
    SupabaseGateway,
    SupabaseUnavailable,
    UserAccessDisabled,
    UserNotAuthorized,
)


def configured_gateway(monkeypatch) -> SupabaseGateway:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test")
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


def test_login_uses_complete_normalized_email_without_restricting_domain(monkeypatch):
    gateway = configured_gateway(monkeypatch)
    captured = {}

    def request(method, endpoint, *, api_key, payload=None, extra_headers=None):
        captured.update(payload)
        return {"user": {"id": "user-1", "email": "usuario@empresa.com.br"}}

    monkeypatch.setattr(gateway, "_request_json", request)
    identity = gateway.sign_in(" Usuario@Empresa.Com.Br ", "senha-de-teste")
    assert identity == AuthIdentity("user-1", "usuario@empresa.com.br")
    assert captured == {"email": "usuario@empresa.com.br", "password": "senha-de-teste"}


def test_active_administrator_is_authorized_by_auth_user_id(monkeypatch):
    gateway = configured_gateway(monkeypatch)
    captured = {}

    def request(method, endpoint, *, api_key, payload=None, extra_headers=None):
        captured.update(method=method, endpoint=endpoint, api_key=api_key)
        return [{
            "user_id": "user-1",
            "email": "cadastro@empresa.com.br",
            "nome": "Pessoa Autorizada",
            "perfil": "administrador",
            "ativo": True,
        }]

    monkeypatch.setattr(gateway, "_request_json", request)
    authorized = gateway.authorize_user(AuthIdentity("user-1", "login@empresa.com.br"))
    assert authorized == AuthorizedUser("user-1", "login@empresa.com.br", "Pessoa Autorizada", "administrador")
    assert captured["method"] == "GET"
    assert captured["endpoint"].startswith("/rest/v1/usuarios_autorizados?")
    assert "user_id=eq.user-1" in captured["endpoint"]
    assert captured["api_key"] == "sb_secret_test"


def test_active_basic_profile_is_authorized(monkeypatch):
    gateway = configured_gateway(monkeypatch)
    monkeypatch.setattr(gateway, "_request_json", lambda *args, **kwargs: [{
        "user_id": "user-2", "email": "basico@outlook.com", "nome": "Básico",
        "perfil": "basico", "ativo": True,
    }])
    authorized = gateway.authorize_user(AuthIdentity("user-2", "basico@outlook.com"))
    assert authorized.profile == "basico"


def test_authenticated_user_without_authorization_row_is_rejected(monkeypatch):
    gateway = configured_gateway(monkeypatch)
    monkeypatch.setattr(gateway, "_request_json", lambda *args, **kwargs: [])
    with pytest.raises(UserNotAuthorized):
        gateway.authorize_user(AuthIdentity("user-3", "sem-registro@example.com"))


def test_inactive_authorized_user_is_rejected(monkeypatch):
    gateway = configured_gateway(monkeypatch)
    monkeypatch.setattr(gateway, "_request_json", lambda *args, **kwargs: [{
        "user_id": "user-4", "email": "inativo@example.com", "nome": "Inativo",
        "perfil": "administrador", "ativo": False,
    }])
    with pytest.raises(UserAccessDisabled):
        gateway.authorize_user(AuthIdentity("user-4", "inativo@example.com"))


def test_unknown_profile_is_not_authorized(monkeypatch):
    gateway = configured_gateway(monkeypatch)
    monkeypatch.setattr(gateway, "_request_json", lambda *args, **kwargs: [{
        "user_id": "user-5", "email": "outro@example.com", "nome": "Outro",
        "perfil": "superusuario", "ativo": True,
    }])
    with pytest.raises(UserNotAuthorized):
        gateway.authorize_user(AuthIdentity("user-5", "outro@example.com"))


def test_malformed_email_is_rejected_before_network_request(monkeypatch):
    gateway = configured_gateway(monkeypatch)
    monkeypatch.setattr(
        gateway,
        "_request_json",
        lambda *args, **kwargs: pytest.fail("Não deveria chamar o Supabase com e-mail inválido."),
    )
    with pytest.raises(AuthenticationRejected, match="E-mail ou senha inválidos"):
        gateway.sign_in("usuario-sem-dominio", "senha-de-teste")


def test_gateway_fails_closed_without_external_configuration(monkeypatch):
    for name in (
        "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SECRET_KEY",
        "PERSISTENT_BASE_KEY_B64",
    ):
        monkeypatch.delenv(name, raising=False)
    gateway = SupabaseGateway()
    with pytest.raises(SupabaseUnavailable):
        gateway.sign_in("alan@example.com", "qualquer")
