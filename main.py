from __future__ import annotations

import asyncio
import base64
import os
import re
import secrets
import shutil
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from app.services.excel_reader import SUPPORTED_EXTENSIONS
from webapp.crypto_storage import decrypt_uploaded_chunks, iter_unseal_file, validate_office_container
from webapp.engine import WebEngine
from webapp.security import RuntimeSecurity, SlidingWindowLimiter, request_origin_is_allowed
from webapp.session_store import SessionStore

PROJECT_ROOT = Path(__file__).resolve().parent
INDEX_HTML = PROJECT_ROOT / "webapp" / "templates" / "index.html"
STATIC_DIR = PROJECT_ROOT / "webapp" / "static"
RESOURCES_DIR = PROJECT_ROOT / "resources"
COOKIE_NAME = "cap_session"
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9À-ÿ._()\- ]+")
SESSION_CLEANUP_INTERVAL = 10 * 60

store = SessionStore(PROJECT_ROOT)
engine = WebEngine(PROJECT_ROOT, store)
security = RuntimeSecurity()
limiter = SlidingWindowLimiter()
heavy_jobs = asyncio.Semaphore(max(1, min(8, int(os.getenv("MAX_HEAVY_JOBS", "1") or "1"))))


def _safe_filename(name: str) -> str:
    raw = Path(name or "arquivo.xlsx").name.strip() or "arquivo.xlsx"
    cleaned = SAFE_NAME_RE.sub("_", raw).strip(" .")
    return (cleaned or "arquivo.xlsx")[:180]


def _sid(request: Request) -> str:
    return request.state.session_key


def _session_token(request: Request) -> str:
    return request.state.session_token


def _safe_error(exc: Exception, *, fallback: str = "Não foi possível concluir a operação.") -> str:
    text = str(exc).strip() or fallback
    roots = {str(PROJECT_ROOT), str(store.root), str(Path.home())}
    for root in roots:
        if root:
            text = text.replace(root, "[caminho protegido]")
            text = text.replace(root.replace("/", "\\"), "[caminho protegido]")
    text = re.sub(r"[A-Za-z]:\\(?:[^\s\r\n'\"]+\\)+", lambda _m: "[caminho protegido]\\", text)
    return text[:1800]


def _content_disposition(kind: str, filename: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", filename).strip() or "arquivo"
    return f'{kind}; filename="{safe}"'


def _report_csp(sid: str) -> str:
    hashes = " ".join(f"'{value}'" for value in store.state(sid).report_script_hashes)
    script_src = hashes or "'none'"
    return (
        "default-src 'none'; "
        f"script-src {script_src}; "
        "style-src 'unsafe-inline'; "
        "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )


def _apply_security_headers(request: Request, response: Response) -> None:
    path = request.url.path
    static_public = path.startswith("/static/") or path in {
        "/resources/contas_a_pagar_logo.png",
        "/resources/contas_a_pagar.ico",
    }
    if static_public:
        response.headers.setdefault("Cache-Control", "public, max-age=300, must-revalidate")
    else:
        response.headers.setdefault("Cache-Control", "no-store, max-age=0")
        response.headers.setdefault("Pragma", "no-cache")

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=(), serial=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; "
        "frame-ancestors 'none'; form-action 'self'",
    )
    forwarded = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip().lower()
    if forwarded == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")


async def _cleanup_loop() -> None:
    while True:
        await asyncio.sleep(SESSION_CLEANUP_INTERVAL)
        await asyncio.to_thread(store.cleanup_expired)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(_cleanup_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="Contas a Pagar Web",
    version="2.0.2.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=2048, compresslevel=5)


@app.middleware("http")
async def session_security_middleware(request: Request, call_next):
    path = request.url.path
    sessionless = path == "/healthz" or path.startswith("/static/") or path in {
        "/resources/contas_a_pagar_logo.png",
        "/resources/contas_a_pagar.ico",
    }
    if sessionless:
        response = await call_next(request)
        _apply_security_headers(request, response)
        return response

    token, sid, is_new = store.resolve_session(request.cookies.get(COOKIE_NAME))
    request.state.session_token = token
    request.state.session_key = sid
    store.begin_request(sid)
    try:
        if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            if not request_origin_is_allowed(request):
                response = JSONResponse(status_code=403, content={"detail": "Origem da requisição não autorizada."})
            elif not security.valid_csrf(token, request.headers.get("x-csrf-token")):
                response = JSONResponse(status_code=403, content={"detail": "A sessão de segurança expirou. Atualize a página e tente novamente."})
            else:
                session_ok = limiter.allow(f"session:{sid}", limit=1200, window_seconds=300)
                peer = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "unknown")).split(",")[0].strip()
                peer_ok = limiter.allow(f"peer:{peer}", limit=5000, window_seconds=300)
                if not session_ok or not peer_ok:
                    response = JSONResponse(status_code=429, content={"detail": "Muitas requisições em sequência. Aguarde alguns segundos e tente novamente."})
                else:
                    response = await call_next(request)
        else:
            response = await call_next(request)
    finally:
        store.end_request(sid)

    forwarded = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip().lower()
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="strict",
        secure=forwarded == "https",
        max_age=store.session_ttl_seconds,
        path="/",
    )
    _apply_security_headers(request, response)
    return response


class UploadInitRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    purpose: Literal["financial", "base"] = "financial"
    encrypted_key: str = Field(min_length=16, max_length=2048)


class UploadIdsRequest(BaseModel):
    upload_ids: list[str] = Field(min_length=1, max_length=200)


class UploadIdRequest(BaseModel):
    upload_id: str = Field(min_length=32, max_length=32)


@app.get("/")
def home():
    return FileResponse(INDEX_HTML, media_type="text/html; charset=utf-8")


@app.get("/static/{asset:path}")
def static_asset(asset: str):
    rel = Path(asset)
    if rel.is_absolute() or ".." in rel.parts:
        raise HTTPException(status_code=404, detail="Recurso não encontrado.")
    path = (STATIC_DIR / rel).resolve()
    if STATIC_DIR.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Recurso não encontrado.")
    return FileResponse(path)


@app.get("/resources/contas_a_pagar_logo.png")
def public_logo():
    return FileResponse(RESOURCES_DIR / "contas_a_pagar_logo.png", media_type="image/png")


@app.get("/resources/contas_a_pagar.ico")
def public_icon():
    return FileResponse(RESOURCES_DIR / "contas_a_pagar.ico", media_type="image/x-icon")


@app.get("/healthz")
def healthz():
    return {"status": "ok", "app": "Contas a Pagar Web", "version": "2.0.2.0"}


@app.get("/api/security/bootstrap")
def security_bootstrap(request: Request):
    return {
        "csrf_token": security.csrf_token(_session_token(request)),
        "public_key_jwk": security.public_jwk,
        "max_upload_bytes": store.max_upload_bytes,
        "upload_chunk_bytes": store.upload_chunk_bytes,
        "session_idle_seconds": store.session_ttl_seconds,
    }


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
        raise HTTPException(status_code=500, detail="Não foi possível carregar o estado da sessão.") from exc


@app.post("/api/uploads/init")
def upload_init(request: Request, payload: UploadInitRequest):
    sid = _sid(request)
    name = _safe_filename(payload.filename)
    extension = Path(name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Formato não suportado: {extension or 'sem extensão'}")
    if payload.size > store.max_upload_bytes:
        raise HTTPException(status_code=413, detail=f"Cada planilha pode ter no máximo {store.max_upload_bytes // (1024 * 1024)} MB.")

    aes_key = None
    try:
        aes_key = security.unwrap_upload_key(payload.encrypted_key)
        record = store.register_upload(
            sid,
            purpose=payload.purpose,
            filename=name,
            extension=extension,
            expected_size=payload.size,
            aes_key=aes_key,
        )
        return {
            "ok": True,
            "upload_id": record.upload_id,
            "chunk_bytes": record.chunk_size,
            "total_chunks": record.total_chunks,
        }
    except Exception as exc:
        if aes_key is not None:
            for index in range(len(aes_key)):
                aes_key[index] = 0
        raise HTTPException(status_code=400, detail=_safe_error(exc)) from exc


@app.post("/api/uploads/{upload_id}/chunk/{index}")
async def upload_chunk(request: Request, upload_id: str, index: int):
    sid = _sid(request)
    try:
        record = store.upload_record(sid, upload_id)
        expected_plain = record.expected_plain_size(index)
        try:
            claimed_plain = int(request.headers.get("x-plain-size", "-1"))
        except ValueError:
            claimed_plain = -1
        if claimed_plain != expected_plain:
            raise RuntimeError("Tamanho do bloco de upload não confere.")

        try:
            iv = base64.b64decode(request.headers.get("x-chunk-iv", ""), validate=True)
        except Exception as exc:
            raise RuntimeError("IV criptográfico inválido.") from exc
        if len(iv) != 12:
            raise RuntimeError("IV criptográfico com tamanho inválido.")

        expected_cipher = expected_plain + 16
        temp = record.encrypted_dir / f"{index:06d}.part"
        final = record.encrypted_dir / f"{index:06d}.chunk"
        total = 0
        try:
            with temp.open("wb") as fh:
                fh.write(iv)
                async for block in request.stream():
                    if not block:
                        continue
                    total += len(block)
                    if total > expected_cipher:
                        raise RuntimeError("Bloco criptografado maior que o esperado.")
                    fh.write(block)
            if total != expected_cipher:
                raise RuntimeError("Bloco criptografado incompleto.")
            temp.replace(final)
        finally:
            temp.unlink(missing_ok=True)

        store.mark_chunk(sid, upload_id, index)
        return {"ok": True, "index": index}
    except (KeyError, IndexError) as exc:
        raise HTTPException(status_code=404, detail="Upload não encontrado nesta sessão.") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=_safe_error(exc)) from exc


@app.post("/api/uploads/{upload_id}/complete")
def upload_complete(request: Request, upload_id: str):
    sid = _sid(request)
    try:
        record = store.upload_record(sid, upload_id)
        if not record.complete:
            raise RuntimeError("O upload ainda não recebeu todos os blocos do arquivo.")
        return {"ok": True, "upload_id": upload_id}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Upload não encontrado nesta sessão.") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=_safe_error(exc)) from exc


@app.post("/api/uploads/discard")
def upload_discard(request: Request, payload: UploadIdsRequest):
    store.discard_uploads(_sid(request), payload.upload_ids)
    return {"ok": True}


@app.post("/api/validate")
async def api_validate(request: Request, payload: UploadIdsRequest):
    sid = _sid(request)
    upload_ids = list(dict.fromkeys(payload.upload_ids))
    work = store.new_work_dir(sid, "validation")
    materialized: list[Path] = []
    try:
        for position, upload_id in enumerate(upload_ids):
            record = store.upload_record(sid, upload_id, purpose="financial")
            if not record.complete:
                raise RuntimeError(f"O arquivo '{record.filename}' ainda não terminou de ser enviado.")
            dest = work / f"{position:03d}" / record.filename
            await asyncio.to_thread(decrypt_uploaded_chunks, record, dest)
            await asyncio.to_thread(
                validate_office_container,
                dest,
                record.extension,
                max_file_bytes=store.max_upload_bytes,
                max_expanded_bytes=store.max_office_expanded_bytes,
            )
            materialized.append(dest)

        with store.lock(sid):
            store.invalidate_validation(sid, preserve_last_outputs=True)
        async with heavy_jobs:
            with store.lock(sid):
                validated = await asyncio.to_thread(engine.validate, sid, materialized)
        summary = engine.validation_summary(validated)
        return {"ok": True, "summary": summary}
    except Exception as exc:
        with suppress(Exception):
            store.invalidate_validation(sid, preserve_last_outputs=True)
        raise HTTPException(status_code=400, detail=_safe_error(exc)) from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)
        store.discard_uploads(sid, upload_ids)


@app.post("/api/generate")
async def api_generate(request: Request):
    sid = _sid(request)
    try:
        async with heavy_jobs:
            with store.lock(sid):
                result = await asyncio.to_thread(engine.generate, sid)
        stamp = int(time.time())
        return {
            "ok": True,
            "report_url": f"{result['report_url']}?v={stamp}",
            "pdf_url": f"{result['pdf_url']}?v={stamp}",
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=_safe_error(exc)) from exc


@app.get("/report/current")
def report_current(request: Request):
    return _serve_report_artifact(request, "index.html", force_inline=True)


@app.get("/report/{artifact_path:path}")
def report_artifact(request: Request, artifact_path: str):
    return _serve_report_artifact(request, artifact_path, force_inline=artifact_path.lower().endswith(".pdf"))


def _serve_report_artifact(request: Request, logical_name: str, *, force_inline: bool):
    sid = _sid(request)
    try:
        artifact = store.report_artifact(sid, logical_name)
        state = store.state(sid)
        headers = {
            "Cache-Control": "no-store, max-age=0",
            "Content-Disposition": _content_disposition("inline" if force_inline or artifact.logical_name == "index.html" else "attachment", artifact.download_name),
        }
        if artifact.logical_name == "index.html":
            headers["Content-Security-Policy"] = _report_csp(sid)
        return StreamingResponse(
            iter_unseal_file(artifact.sealed_path, bytes(state.artifact_key), artifact.logical_name),
            media_type=artifact.content_type,
            headers=headers,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Relatório não encontrado nesta sessão ou sessão expirada.") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Não foi possível abrir o artefato protegido do relatório.") from exc


@app.get("/api/base")
def api_base(request: Request):
    sid = _sid(request)
    try:
        return engine.base_rows(sid)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=_safe_error(exc)) from exc


@app.post("/api/base/import")
async def api_base_import(request: Request, payload: UploadIdRequest):
    sid = _sid(request)
    work = store.new_work_dir(sid, "base_import")
    try:
        record = store.upload_record(sid, payload.upload_id, purpose="base")
        if not record.complete:
            raise RuntimeError("O upload da BASE DADOS ainda não terminou.")
        dest = work / record.filename
        await asyncio.to_thread(decrypt_uploaded_chunks, record, dest)
        await asyncio.to_thread(
            validate_office_container,
            dest,
            record.extension,
            max_file_bytes=store.max_upload_bytes,
            max_expanded_bytes=store.max_office_expanded_bytes,
        )
        async with heavy_jobs:
            with store.lock(sid):
                info = await asyncio.to_thread(engine.import_base, sid, dest)
        return {"ok": True, "base": info}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"A base anterior foi preservada. {_safe_error(exc)}") from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)
        store.discard_upload(sid, payload.upload_id)


@app.get("/api/base/export")
async def api_base_export(request: Request):
    sid = _sid(request)
    path: Path | None = None
    try:
        async with heavy_jobs:
            with store.lock(sid):
                path = await asyncio.to_thread(engine.export_base, sid)
        data = await asyncio.to_thread(path.read_bytes)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": _content_disposition("attachment", "BASE_DADOS.xlsx")},
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=_safe_error(exc)) from exc
    finally:
        if path is not None:
            shutil.rmtree(path.parent, ignore_errors=True)


@app.exception_handler(404)
async def not_found(_: Request, __):
    return JSONResponse(status_code=404, content={"detail": "Recurso não encontrado."})
