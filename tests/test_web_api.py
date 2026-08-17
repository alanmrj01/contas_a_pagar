from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from tests.security_helpers import stage_file, wrap_key_from_jwk

ROOT = Path(__file__).resolve().parents[1]


def load_main(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_DATA_DIR", str(tmp_path / "webdata"))
    sys.modules.pop("main", None)
    return importlib.import_module("main")


def csrf(client):
    boot = client.get("/api/security/bootstrap")
    assert boot.status_code == 200
    return boot.json()["csrf_token"]


def test_http_flow_encrypted_upload_validate_generate_and_private_downloads(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    client = TestClient(main.app)

    home = client.get("/")
    assert home.status_code == 200
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

    report = client.get(payload["report_url"])
    pdf = client.get(payload["pdf_url"])
    assert report.status_code == 200
    assert "Contas a Pagar — Previsto x Realizado" in report.text
    assert "WEB-PERFORMANCE-PATCH-2.0.2" in report.text
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
    client.get("/")
    response = client.post("/api/generate")
    assert response.status_code == 403


def test_tampered_encrypted_chunk_is_rejected_before_engine_use(tmp_path, monkeypatch):
    main = load_main(tmp_path, monkeypatch)
    client = TestClient(main.app)
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
