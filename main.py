from __future__ import annotations

import asyncio
import os
import re
import secrets
import shutil
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.services.excel_reader import SUPPORTED_EXTENSIONS
from webapp.engine import WebEngine
from webapp.session_store import SessionStore

PROJECT_ROOT = Path(__file__).resolve().parent
INDEX_HTML = PROJECT_ROOT / "webapp" / "templates" / "index.html"
STATIC_DIR = PROJECT_ROOT / "webapp" / "static"
RESOURCES_DIR = PROJECT_ROOT / "resources"

store = SessionStore(PROJECT_ROOT)
engine = WebEngine(PROJECT_ROOT, store)

app = FastAPI(
    title="Contas a Pagar Web",
    version="2.0.2.0",
    docs_url=None,
    redoc_url=None,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/resources", StaticFiles(directory=str(RESOURCES_DIR)), name="resources")
# Apenas saídas geradas são públicas. Uploads e BASE DADOS ficam fora deste mount.
app.mount("/generated", StaticFiles(directory=str(store.reports_root), html=True), name="generated")

COOKIE_NAME = "cap_session"
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9À-ÿ._()\- ]+")


def _sid(request: Request) -> str:
    return request.state.sid


def _safe_filename(name: str) -> str:
    raw = Path(name or "arquivo.xlsx").name.strip() or "arquivo.xlsx"
    cleaned = SAFE_NAME_RE.sub("_", raw).strip(" .")
    return cleaned or "arquivo.xlsx"


async def _save_upload(upload: UploadFile, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as fh:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)
    await upload.close()


@app.middleware("http")
async def ensure_session(request: Request, call_next):
    current = request.cookies.get(COOKIE_NAME)
    is_new = not store.valid_sid(current)
    sid = current if not is_new else secrets.token_hex(16)
    request.state.sid = sid
    response = await call_next(request)
    if is_new:
        forwarded = request.headers.get("x-forwarded-proto", "").lower()
        secure = request.url.scheme == "https" or forwarded == "https"
        response.set_cookie(
            COOKIE_NAME,
            sid,
            httponly=True,
            samesite="lax",
            secure=secure,
            max_age=60 * 60 * 24 * 365,
        )
    return response


@app.get("/")
def home():
    return FileResponse(INDEX_HTML)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "app": "Contas a Pagar Web", "version": "2.0.2.0"}


@app.get("/api/state")
def api_state(request: Request):
    sid = _sid(request)
    try:
        base = engine.base_info(sid)
        state = store.state(sid)
        return {
            "base": base,
            "validated": state.validated is not None,
            "report_url": state.last_report_url,
            "pdf_url": state.last_pdf_url,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/validate")
async def api_validate(request: Request, files: list[UploadFile] = File(...)):
    sid = _sid(request)
    if not files:
        raise HTTPException(status_code=400, detail="Adicione ao menos um arquivo com PREVISTO e/ou REALIZADO.")

    invalid = [f.filename or "" for f in files if Path(f.filename or "").suffix.lower() not in SUPPORTED_EXTENSIONS]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Formato não suportado: {', '.join(invalid)}")

    with store.lock(sid):
        store.invalidate_validation(sid, preserve_last_outputs=True)
        store.clear_uploads(sid)
        batch = store.upload_dir(sid) / secrets.token_hex(8)
        saved: list[Path] = []
        try:
            for index, upload in enumerate(files):
                # Diretório por posição evita sobrescrever arquivos com o mesmo nome,
                # preservando o nome original usado na rastreabilidade do motor.
                name = _safe_filename(upload.filename or f"arquivo_{index + 1}.xlsx")
                dest = batch / f"{index:03d}" / name
                await _save_upload(upload, dest)
                saved.append(dest)
            validated = await asyncio.to_thread(engine.validate, sid, saved)
            summary = engine.validation_summary(validated)
            # Os arquivos brutos já foram lidos integralmente; removê-los reduz a
            # retenção no servidor sem alterar o resultado validado em memória.
            shutil.rmtree(batch, ignore_errors=True)
            return {"ok": True, "summary": summary}
        except Exception as exc:
            shutil.rmtree(batch, ignore_errors=True)
            store.invalidate_validation(sid, preserve_last_outputs=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/generate")
async def api_generate(request: Request):
    sid = _sid(request)
    try:
        with store.lock(sid):
            result = await asyncio.to_thread(engine.generate, sid)
        # Query string impede cache antigo quando o usuário gera novamente.
        stamp = int(time.time())
        return {
            "ok": True,
            "report_url": f"{result['report_url']}?v={stamp}",
            "pdf_url": f"{result['pdf_url']}?v={stamp}",
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/base")
def api_base(request: Request):
    sid = _sid(request)
    try:
        return engine.base_rows(sid)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/base/import")
async def api_base_import(request: Request, file: UploadFile = File(...)):
    sid = _sid(request)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Formato não suportado: {suffix or 'sem extensão'}")

    temp_dir = store.session_dir(sid) / "base_import"
    temp_dir.mkdir(parents=True, exist_ok=True)
    dest = temp_dir / _safe_filename(file.filename or "BASE_DADOS.xlsx")
    try:
        await _save_upload(file, dest)
        with store.lock(sid):
            info = await asyncio.to_thread(engine.import_base, sid, dest)
        return {"ok": True, "base": info}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"A base anterior foi preservada. {exc}") from exc
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.get("/api/base/export")
def api_base_export(request: Request):
    sid = _sid(request)
    try:
        with store.lock(sid):
            path = engine.export_base(sid)
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename="BASE_DADOS.xlsx",
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.exception_handler(404)
async def not_found(_: Request, __):
    return JSONResponse(status_code=404, content={"detail": "Recurso não encontrado."})
