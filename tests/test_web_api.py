from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def test_http_flow_upload_validate_generate_and_downloads(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_DATA_DIR", str(tmp_path / "webdata"))
    sys.modules.pop("main", None)
    main = importlib.import_module("main")
    client = TestClient(main.app)

    home = client.get("/")
    assert home.status_code == 200
    assert "Arraste seu arquivo financeiro aqui" in home.text

    state = client.get("/api/state")
    assert state.status_code == 200
    assert state.json()["base"]["rows"] > 0

    sample = ROOT / "samples" / "PLANILHAS PAGAR E PREVISTO.xlsx"
    with sample.open("rb") as fh:
        response = client.post(
            "/api/validate",
            files={"files": (sample.name, fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert response.status_code == 200, response.text
    summary = response.json()["summary"]
    assert summary["previsto"] > 0
    assert summary["realizado"] > 0

    generated = client.post("/api/generate")
    assert generated.status_code == 200, generated.text
    payload = generated.json()
    report = client.get(payload["report_url"])
    pdf = client.get(payload["pdf_url"])
    assert report.status_code == 200
    assert "Contas a Pagar — Previsto x Realizado" in report.text
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
