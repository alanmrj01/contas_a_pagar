from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from tests.security_helpers import stage_file, wrap_key_from_jwk
from webapp.supabase_gateway import (
    AuthIdentity,
    AuthenticationRejected,
    AuthorizedUser,
    RecoveryCodeRejected,
    RecoverySession,
    SupabaseUnavailable,
    UserAccessDisabled,
    UserNotAuthorized,
)

ROOT = Path(__file__).resolve().parents[1]


def load_main(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_DATA_DIR", str(tmp_path / "webdata"))
    sys.modules.pop("main", None)
    module = importlib.import_module("main")
    persisted: dict[str, tuple[list[dict[str, str]], str]] = {}
    monkeypatch.setattr(
        module.supabase,
        "sign_in",
        lambda email, password: AuthIdentity(
            user_id="00000000-0000-0000-0000-000000000001",
            email=str(email).strip().lower(),
        ),
    )
    monkeypatch.setattr(
        module.supabase,
        "authorize_user",
        lambda identity: AuthorizedUser(
            user_id=identity.user_id,
            email=identity.email,
            name="Alan",
            profile="administrador",
        ),
    )
    monkeypatch.setattr(module.supabase, "load_base", lambda user_id: persisted.get(user_id))

    def save_base(user_id, items):
        revision = f"teste-{len(items)}"
        persisted[user_id] = ([dict(item) for item in items], revision)
        return revision

    monkeypatch.setattr(module.supabase, "save_base", save_base)
    module._test_persisted_bases = persisted
    return module


def csrf(client):
    boot = client.get("/api/security/bootstrap")
    assert boot.status_code == 200
    return boot.json()["csrf_token"]


def login(client):
    response = client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": csrf(client)},
        json={"email": "alanmr565@gmail.com", "password": "segredo-de-teste"},
    )
    assert response.status_code == 200, response.text


def test_login_authorizes_full_email_and_stores_trusted_identity_in_session(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    client = TestClient(main.app)
    response = client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": csrf(client)},
        json={"email": " Usuario@Empresa.Com.Br ", "password": "segredo-de-teste"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["email"] == "usuario@empresa.com.br"
    assert response.json()["profile"] == "administrador"
    authenticated = [state for state in main.store._states.values() if state.authenticated_user_id]
    assert len(authenticated) == 1
    state = authenticated[0]
    assert state.authenticated_user_id == "00000000-0000-0000-0000-000000000001"
    assert state.authenticated_email == "usuario@empresa.com.br"
    assert state.authenticated_name == "Alan"
    assert state.authenticated_profile == "administrador"


def test_invalid_credentials_return_safe_email_message(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    monkeypatch.setattr(
        main.supabase,
        "sign_in",
        lambda email, password: (_ for _ in ()).throw(AuthenticationRejected("interno")),
    )
    client = TestClient(main.app)
    response = client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": csrf(client)},
        json={"email": "usuario@example.com", "password": "incorreta"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "E-mail ou senha inválidos."


def test_authenticated_but_not_authorized_user_is_denied(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    monkeypatch.setattr(
        main.supabase,
        "authorize_user",
        lambda identity: (_ for _ in ()).throw(UserNotAuthorized("interno")),
    )
    client = TestClient(main.app)
    response = client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": csrf(client)},
        json={"email": "usuario@example.com", "password": "correta"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Seu usuário não possui autorização para acessar este sistema."
    assert client.get("/api/state").status_code == 401


def test_inactive_authorized_user_is_denied_with_specific_message(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    monkeypatch.setattr(
        main.supabase,
        "authorize_user",
        lambda identity: (_ for _ in ()).throw(UserAccessDisabled("interno")),
    )
    client = TestClient(main.app)
    response = client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": csrf(client)},
        json={"email": "inativo@example.com", "password": "correta"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Seu acesso está desativado. Entre em contato com o administrador."


def test_basic_profile_is_permitted_and_kept_in_session(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    monkeypatch.setattr(
        main.supabase,
        "authorize_user",
        lambda identity: AuthorizedUser(identity.user_id, identity.email, "Pessoa Básica", "basico"),
    )
    client = TestClient(main.app)
    response = client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": csrf(client)},
        json={"email": "basico@outlook.com", "password": "correta"},
    )
    assert response.status_code == 200
    assert response.json()["profile"] == "basico"
    state = next(state for state in main.store._states.values() if state.authenticated_user_id)
    assert state.authenticated_profile == "basico"


def test_login_service_failure_does_not_expose_internal_details(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    monkeypatch.setattr(
        main.supabase,
        "sign_in",
        lambda email, password: (_ for _ in ()).throw(SupabaseUnavailable("segredo interno")),
    )
    client = TestClient(main.app)
    response = client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": csrf(client)},
        json={"email": "usuario@example.com", "password": "correta"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Não foi possível realizar o login no momento. Tente novamente."
    assert "segredo interno" not in response.text


def test_password_recovery_request_is_generic_even_when_supabase_rejects_email(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    monkeypatch.setattr(
        main.supabase,
        "request_password_recovery",
        lambda email: (_ for _ in ()).throw(AuthenticationRejected("usuário ausente")),
    )
    client = TestClient(main.app)
    response = client.post(
        "/api/auth/recovery/request",
        headers={"X-CSRF-Token": csrf(client)},
        json={"email": "nao-existe@example.com"},
    )
    assert response.status_code == 200
    assert response.json()["message"].startswith("Se o e-mail estiver cadastrado")
    assert "usuário ausente" not in response.text
    assert response.json()["cooldown_seconds"] == 60


def test_password_recovery_request_does_not_expose_external_service_failure(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    monkeypatch.setattr(
        main.supabase,
        "request_password_recovery",
        lambda email: (_ for _ in ()).throw(SupabaseUnavailable("smtp interno")),
    )
    client = TestClient(main.app)
    response = client.post(
        "/api/auth/recovery/request",
        headers={"X-CSRF-Token": csrf(client)},
        json={"email": "usuario@example.com"},
    )
    assert response.status_code == 200
    assert response.json()["message"].startswith("Se o e-mail estiver cadastrado")
    assert "smtp interno" not in response.text


def test_password_recovery_rejects_incorrect_and_expired_otp_with_safe_message(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    monkeypatch.setattr(
        main.supabase,
        "verify_recovery_otp",
        lambda email, code: (_ for _ in ()).throw(RecoveryCodeRejected("otp_expired interno")),
    )
    client = TestClient(main.app)
    for code in ("111111", "222222"):
        response = client.post(
            "/api/auth/recovery/verify",
            headers={"X-CSRF-Token": csrf(client)},
            json={"email": "usuario@example.com", "code": code},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Código inválido ou expirado. Solicite um novo código e tente novamente."
        assert "interno" not in response.text


def test_password_recovery_rejects_different_passwords_before_supabase_update(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    monkeypatch.setattr(
        main.supabase,
        "verify_recovery_otp",
        lambda email, code: RecoverySession(email, "temporary-recovery-jwt"),
    )
    called = []
    monkeypatch.setattr(main.supabase, "update_recovery_password", lambda *args: called.append(args))
    client = TestClient(main.app)
    verified = client.post(
        "/api/auth/recovery/verify",
        headers={"X-CSRF-Token": csrf(client)},
        json={"email": "usuario@example.com", "code": "123456"},
    )
    assert verified.status_code == 200
    response = client.post(
        "/api/auth/recovery/update",
        headers={"X-CSRF-Token": csrf(client)},
        json={"password": "NovaSenha123", "confirm_password": "OutraSenha123"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "As senhas informadas não coincidem."
    assert called == []


def test_successful_recovery_updates_password_ends_temporary_session_and_allows_new_login(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    updated = []
    ended = []
    logins = []
    monkeypatch.setattr(
        main.supabase,
        "verify_recovery_otp",
        lambda email, code: RecoverySession(str(email).strip().lower(), "temporary-recovery-jwt"),
    )
    monkeypatch.setattr(main.supabase, "update_recovery_password", lambda token, password: updated.append((token, password)))
    monkeypatch.setattr(main.supabase, "end_recovery_session", lambda token: ended.append(token))
    client = TestClient(main.app)
    verified = client.post(
        "/api/auth/recovery/verify",
        headers={"X-CSRF-Token": csrf(client)},
        json={"email": "usuario@example.com", "code": "123456"},
    )
    assert verified.status_code == 200
    assert "access_token" not in verified.text
    response = client.post(
        "/api/auth/recovery/update",
        headers={"X-CSRF-Token": csrf(client)},
        json={"password": "NovaSenha123", "confirm_password": "NovaSenha123"},
    )
    assert response.status_code == 200
    assert updated == [("temporary-recovery-jwt", "NovaSenha123")]
    assert ended == ["temporary-recovery-jwt"]
    assert all(not state.recovery_access_token for state in main.store._states.values())

    monkeypatch.setattr(
        main.supabase,
        "sign_in",
        lambda email, password: (
            logins.append((email, password))
            or AuthIdentity("00000000-0000-0000-0000-000000000001", str(email).strip().lower())
        ),
    )
    login_response = client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": csrf(client)},
        json={"email": "usuario@example.com", "password": "NovaSenha123"},
    )
    assert login_response.status_code == 200
    assert logins == [("usuario@example.com", "NovaSenha123")]


def test_logout_destroys_session_rotates_cookie_and_protects_history(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    client = TestClient(main.app)
    login(client)
    authenticated_cookie = client.cookies.get("cap_session")
    response = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf(client)})
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert client.cookies.get("cap_session") != authenticated_cookie
    assert client.get("/api/state").status_code == 401
    assert client.get("/report/current").status_code == 401
    home = client.get("/")
    assert "Acesso seguro" in home.text


def test_authenticated_session_cannot_be_rebound_without_logout(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    client = TestClient(main.app)
    login(client)
    current_cookie = client.cookies.get("cap_session")
    response = client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": csrf(client)},
        json={"email": "outra-pessoa@example.com", "password": "outra-senha"},
    )
    assert response.status_code == 409
    assert client.cookies.get("cap_session") == current_cookie
    state = client.get("/api/state")
    assert state.status_code == 200
    assert state.json()["user"]["email"] == "alanmr565@gmail.com"


def test_http_flow_encrypted_upload_validate_generate_and_private_downloads(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    client = TestClient(main.app)

    home = client.get("/")
    assert home.status_code == 200
    assert "Acesso seguro" in home.text
    login(client)
    home = client.get("/")
    assert "Arraste seu arquivo financeiro aqui" in home.text
    assert "no-store" in home.headers["cache-control"]
    assert home.headers["x-frame-options"] == "DENY"

    state = client.get("/api/state")
    assert state.status_code == 200
    assert state.json()["base"]["rows"] > 0

    sample = ROOT / "samples" / "PLANILHAS PAGAR E PREVISTO.xlsx"
    upload_id = stage_file(client, sample)
    response = client.post(
        "/api/validate",
        headers={"X-CSRF-Token": csrf(client)},
        json={"upload_ids": [upload_id]},
    )
    assert response.status_code == 200, response.text
    summary = response.json()["summary"]
    assert summary["previsto"] > 0
    assert summary["realizado"] > 0

    generated = client.post("/api/generate", headers={"X-CSRF-Token": csrf(client)})
    assert generated.status_code == 200, generated.text
    payload = generated.json()
    assert payload["report_url"].startswith("/report/current")
    assert "/generated/" not in payload["report_url"]
    assert "cap_session" not in payload["report_url"]

    refreshed = client.post(
        "/api/report/refresh",
        headers={"X-CSRF-Token": csrf(client)},
        json={"upload_ids": []},
    )
    assert refreshed.status_code == 200, refreshed.text
    payload = refreshed.json()

    report = client.get(payload["report_url"])
    pdf = client.get(payload["pdf_url"])
    assert report.status_code == 200
    assert "Contas a Pagar — Previsto x Realizado" in report.text
    assert "WEB-PERFORMANCE-PATCH-2.0.2" in report.text
    assert "FILTER_SET_CACHE" in report.text
    assert "FACET_VALUE_CACHE" in report.text
    assert "filterApplyFrame" in report.text
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert "no-store" in report.headers["cache-control"]
    assert "frame-ancestors 'none'" in report.headers["content-security-policy"]

    # Nada gerado fica disponível como diretório estático público.
    assert client.get("/generated/whatever/index.html").status_code == 404
    assert client.get("/resources/base_dados_padrao.xlsx").status_code == 404

    # Artefatos persistidos na sessão ficam cifrados em repouso.
    session_dirs = list((tmp_path / "webdata" / "sessions").iterdir())
    assert len(session_dirs) == 1
    sealed = list(session_dirs[0].rglob("*.capenc"))
    assert sealed
    assert all(p.read_bytes().startswith(b"CAPART01") for p in sealed)
    assert not list(session_dirs[0].rglob("index.html"))
    assert not list(session_dirs[0].rglob("*.pdf"))


def test_second_browser_cannot_open_first_browser_report(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    owner = TestClient(main.app)
    stranger = TestClient(main.app)
    login(owner)
    login(stranger)
    sample = ROOT / "samples" / "PLANILHAS PAGAR E PREVISTO.xlsx"

    upload_id = stage_file(owner, sample)
    validated = owner.post("/api/validate", headers={"X-CSRF-Token": csrf(owner)}, json={"upload_ids": [upload_id]})
    assert validated.status_code == 200
    generated = owner.post("/api/generate", headers={"X-CSRF-Token": csrf(owner)})
    assert generated.status_code == 200

    assert owner.get("/report/current").status_code == 200
    assert stranger.get("/report/current").status_code == 404
    assert stranger.get("/report/Relatorio_Contas_a_Pagar.pdf").status_code == 404


def test_csrf_is_required_for_mutating_endpoints(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    client = TestClient(main.app)
    login(client)
    response = client.post("/api/generate")
    assert response.status_code == 403


def test_financial_routes_require_login_and_csrf_refresh_has_machine_code(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    client = TestClient(main.app)
    assert client.get("/api/state").status_code == 401
    login(client)
    response = client.post("/api/generate", headers={"X-CSRF-Token": "invalido"})
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_REFRESH_REQUIRED"


def test_tampered_encrypted_chunk_is_rejected_before_engine_use(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    client = TestClient(main.app)
    login(client)
    sample = ROOT / "samples" / "PLANILHAS PAGAR E PREVISTO.xlsx"
    upload_id = stage_file(client, sample, tamper_chunk=0)
    response = client.post(
        "/api/validate",
        headers={"X-CSRF-Token": csrf(client)},
        json={"upload_ids": [upload_id]},
    )
    assert response.status_code == 400
    assert "integridade" in response.json()["detail"].lower() or "descriptograf" in response.json()["detail"].lower()


def test_200mb_is_accepted_at_init_but_larger_file_is_rejected(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    client = TestClient(main.app)
    login(client)
    boot = client.get("/api/security/bootstrap").json()
    csrf_token = boot["csrf_token"]
    wrapped = wrap_key_from_jwk(boot["public_key_jwk"], bytes(range(32)))
    max_bytes = 200 * 1024 * 1024
    ok = client.post(
        "/api/uploads/init",
        headers={"X-CSRF-Token": csrf_token},
        json={"filename": "grande.xlsx", "size": max_bytes, "purpose": "financial", "encrypted_key": wrapped},
    )
    assert ok.status_code == 200, ok.text
    too_big = client.post(
        "/api/uploads/init",
        headers={"X-CSRF-Token": csrf_token},
        json={"filename": "grande.xlsx", "size": max_bytes + 1, "purpose": "financial", "encrypted_key": wrapped},
    )
    assert too_big.status_code == 413


def test_security_cookie_on_https_is_secure_httponly_and_strict(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    client = TestClient(main.app, base_url="https://example.test")
    response = client.get("/")
    cookie = response.headers.get("set-cookie", "")
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=strict" in cookie
    assert "Max-Age=7200" in cookie


def test_validation_summary_reports_base_health(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    client = TestClient(main.app)
    login(client)
    sample = ROOT / "samples" / "PLANILHAS PAGAR E PREVISTO.xlsx"
    upload_id = stage_file(client, sample)
    response = client.post(
        "/api/validate",
        headers={"X-CSRF-Token": csrf(client)},
        json={"upload_ids": [upload_id]},
    )
    assert response.status_code == 200, response.text
    health = response.json()["summary"]["base_health"]
    assert health["status"] in {"ok", "attention"}
    assert "missing_records" in health
    assert "missing_suppliers" in health
    assert "message" in health


def test_imported_base_updates_site_backend_state_and_revalidation(tmp_path, monkeypatch):
    import xlsxwriter

    main = load_main(tmp_path, monkeypatch)
    client = TestClient(main.app)
    login(client)

    base_path = tmp_path / "base_atualizada.xlsx"
    wb = xlsxwriter.Workbook(base_path)
    ws = wb.add_worksheet("BASE DADOS")
    for row_index, row in enumerate([
        ["Cód Fornecedor", "Fornecedor", "Fluxo JMM", "Categoria"],
        [9001, "FORNECEDOR DEMONSTRACAO ALFA", "FLUXO A", "CATEGORIA A"],
        [9002, "FORNECEDOR DEMONSTRACAO BETA", "FLUXO B", "CATEGORIA B"],
        [9003, "FORNECEDOR DEMONSTRACAO GAMA", "FLUXO C", "CATEGORIA C"],
    ]):
        ws.write_row(row_index, 0, row)
    wb.close()

    base_upload = stage_file(client, base_path, purpose="base")
    imported = client.post(
        "/api/base/import",
        headers={"X-CSRF-Token": csrf(client)},
        json={"upload_id": base_upload, "mode": "replace"},
    )
    assert imported.status_code == 200, imported.text
    info = imported.json()["base"]
    assert info["origin"] == "persistida no Supabase"
    assert info["revision"] and info["revision"] != "padrao"

    backend = client.get("/api/base")
    assert backend.status_code == 200
    assert backend.json()["origin"] == "persistida no Supabase"
    assert backend.json()["revision"] == info["revision"]
    assert backend.json()["rows"] == 3

    # Uma nova sessão autenticada do mesmo usuário restaura a base persistida.
    later = TestClient(main.app)
    login(later)
    restored = later.get("/api/base")
    assert restored.status_code == 200
    assert restored.json()["rows"] == 3
    assert restored.json()["revision"] == info["revision"]


def test_manual_base_addition_and_removal_persist_for_later_session(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    client = TestClient(main.app)
    login(client)

    original = client.get("/api/base").json()["items"]
    added = {
        "supplier_code": "CODEX-T2-99001",
        "supplier": "FORNECEDOR MANUAL TAREFA 2",
        "flow": "FLUXO MANUAL",
        "category": "CATEGORIA MANUAL",
    }
    with_added = [*original, added]
    response = client.put(
        "/api/base",
        headers={"X-CSRF-Token": csrf(client)},
        json={"items": with_added},
    )
    assert response.status_code == 200, response.text
    assert response.json()["base"]["rows"] == len(with_added)

    remove_code = original[0]["supplier_code"]
    after_removal = [row for row in with_added if row["supplier_code"] != remove_code]
    response = client.put(
        "/api/base",
        headers={"X-CSRF-Token": csrf(client)},
        json={"items": after_removal},
    )
    assert response.status_code == 200, response.text

    later = TestClient(main.app)
    login(later)
    restored = later.get("/api/base")
    assert restored.status_code == 200
    restored_items = restored.json()["items"]
    assert any(row["supplier_code"] == added["supplier_code"] for row in restored_items)
    assert all(row["supplier_code"] != remove_code for row in restored_items)
    assert restored.json()["rows"] == len(after_removal)


def test_append_base_requires_explicit_resolution_for_similar_rows(tmp_path, monkeypatch):
    import xlsxwriter

    main = load_main(tmp_path, monkeypatch)
    client = TestClient(main.app)
    login(client)
    base_path = tmp_path / "base_com_repetido.xlsx"
    wb = xlsxwriter.Workbook(base_path)
    ws = wb.add_worksheet("BASE DADOS")
    rows = [
        ["Cód Fornecedor", "Fornecedor", "Fluxo JMM", "Categoria"],
        [4, "ANB - AERNNOVA", "FLUXO ENVIADO", "CATEGORIA ENVIADA"],
        [9902, "FORNECEDOR REALMENTE NOVO", "FLUXO NOVO", "CATEGORIA NOVA"],
    ]
    for row_index, row in enumerate(rows):
        ws.write_row(row_index, 0, row)
    wb.close()

    upload_id = stage_file(client, base_path, purpose="base")
    conflict = client.post(
        "/api/base/import",
        headers={"X-CSRF-Token": csrf(client)},
        json={"upload_id": upload_id, "mode": "append"},
    )
    assert conflict.status_code == 200, conflict.text
    payload = conflict.json()
    assert payload["requires_resolution"] is True
    assert payload["new_rows"] == 1
    assert payload["conflicts"][0]["row_index"] == 0

    resolved = client.post(
        "/api/base/import",
        headers={"X-CSRF-Token": csrf(client)},
        json={
            "upload_id": upload_id,
            "mode": "append",
            "duplicate_action": "edit",
            "edited_duplicates": [{
                "row_index": 0,
                "supplier_code": "9901",
                "supplier": "FORNECEDOR EDITADO PARA NOVO",
                "flow": "FLUXO ENVIADO",
                "category": "CATEGORIA ENVIADA",
            }],
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["added"] == 2
    assert resolved.json()["ignored"] == 0
