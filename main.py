from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import re
import secrets
import shutil
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from app.services.excel_reader import SUPPORTED_EXTENSIONS
from webapp.crypto_storage import decrypt_uploaded_chunks, iter_unseal_file, validate_office_container
from webapp.engine import WebEngine
from webapp.security import RuntimeSecurity, SlidingWindowLimiter, request_origin_is_allowed
from webapp.session_store import SessionStore
from webapp.supabase_gateway import (
    AuthenticationRejected,
    RecoveryCodeRejected,
    SupabaseGateway,
    SupabaseUnavailable,
    UserAccessDisabled,
    UserNotAuthorized,
)

PROJECT_ROOT = Path(__file__).resolve().parent
INDEX_HTML = PROJECT_ROOT / "webapp" / "templates" / "index.html"
LOGIN_HTML = PROJECT_ROOT / "webapp" / "templates" / "login.html"
STATIC_DIR = PROJECT_ROOT / "webapp" / "static"
RESOURCES_DIR = PROJECT_ROOT / "resources"
COOKIE_NAME = "cap_session"
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9À-ÿ._()\- ]+")
SESSION_CLEANUP_INTERVAL = 10 * 60
RECOVERY_CONTEXT_TTL_SECONDS = 10 * 60
RECOVERY_REQUEST_MESSAGE = "Se o e-mail estiver cadastrado, um código de recuperação será enviado. Verifique também a caixa de spam."
LOGGER = logging.getLogger("contas_a_pagar.auth")

store = SessionStore(PROJECT_ROOT)
supabase = SupabaseGateway()
engine = WebEngine(PROJECT_ROOT, store, supabase)
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
        public_session_routes = path in {
            "/",
            "/api/security/bootstrap",
            "/api/auth/login",
            "/api/auth/recovery/request",
            "/api/auth/recovery/verify",
            "/api/auth/recovery/update",
        }
        if not public_session_routes and not store.is_authenticated(sid):
            response = JSONResponse(
                status_code=401,
                content={"detail": "Sua sessão precisa ser autenticada novamente.", "code": "AUTH_REQUIRED"},
            )
        elif request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            if not request_origin_is_allowed(request):
                response = JSONResponse(status_code=403, content={"detail": "Origem da requisição não autorizada."})
            elif not security.valid_csrf(token, request.headers.get("x-csrf-token")):
                response = JSONResponse(
                    status_code=403,
                    content={
                        "detail": "A proteção da sessão foi renovada. Tente novamente.",
                        "code": "CSRF_REFRESH_REQUIRED",
                    },
                )
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

    if getattr(request.state, "session_destroyed", False):
        token, sid, _ = store.create_session()
        request.state.session_token = token
        request.state.session_key = sid

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


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=512)


class PasswordRecoveryRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class PasswordRecoveryVerifyRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    code: str = Field(min_length=1, max_length=32)


class PasswordRecoveryUpdateRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    confirm_password: str = Field(min_length=1, max_length=128)


class BaseRowPayload(BaseModel):
    supplier_code: str = Field(min_length=1, max_length=120)
    supplier: str = Field(min_length=1, max_length=500)
    flow: str = Field(min_length=1, max_length=500)
    category: str = Field(min_length=1, max_length=500)


class EditedDuplicatePayload(BaseRowPayload):
    row_index: int = Field(ge=0, le=1_000_000)


class BaseUpdateRequest(BaseModel):
    items: list[BaseRowPayload] = Field(min_length=1, max_length=500_000)


class BaseImportRequest(BaseModel):
    upload_id: str = Field(min_length=32, max_length=32)
    mode: Literal["replace", "append"]
    duplicate_action: Literal["ask", "ignore", "edit"] = "ask"
    edited_duplicates: list[EditedDuplicatePayload] = Field(default_factory=list, max_length=100_000)


class ReportRefreshRequest(BaseModel):
    upload_ids: list[str] = Field(default_factory=list, max_length=200)


class ClassificationAssignment(BaseRowPayload):
    pass


class ClassificationUpdateRequest(BaseModel):
    assignments: list[ClassificationAssignment] = Field(min_length=1, max_length=100_000)


@app.get("/")
def home(request: Request):
    page = INDEX_HTML if store.is_authenticated(_sid(request)) else LOGIN_HTML
    return FileResponse(page, media_type="text/html; charset=utf-8")


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
        "authenticated": store.is_authenticated(_sid(request)),
    }


def _password_validation_error(password: str) -> str:
    if len(password) < 8 or not any(character.isalpha() for character in password) or not any(character.isdigit() for character in password):
        return "Use pelo menos 8 caracteres, incluindo uma letra e um número."
    return ""


@app.post("/api/auth/recovery/request")
async def api_password_recovery_request(request: Request, payload: PasswordRecoveryRequest):
    sid = _sid(request)
    if store.is_authenticated(sid):
        raise HTTPException(status_code=409, detail="Encerre a sessão atual antes de recuperar outra senha.")
    peer = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "unknown")).split(",")[0].strip()
    email_fingerprint = hashlib.sha256(payload.email.strip().casefold().encode("utf-8")).hexdigest()[:24]
    recovery_rate_key = f"{peer}:{email_fingerprint}"
    cooldown_ok = limiter.allow(f"recovery-cooldown:{recovery_rate_key}", limit=1, window_seconds=60)
    window_ok = cooldown_ok and limiter.allow(f"recovery-send:{recovery_rate_key}", limit=3, window_seconds=15 * 60)
    if not cooldown_ok or not window_ok:
        raise HTTPException(status_code=429, detail="Aguarde alguns minutos antes de solicitar outro código.")
    store.clear_recovery(sid)
    try:
        await asyncio.to_thread(supabase.request_password_recovery, payload.email)
    except AuthenticationRejected:
        # A resposta permanece idêntica para e-mail ausente ou malformado.
        pass
    except SupabaseUnavailable as exc:
        LOGGER.error("Falha externa ao solicitar recuperação: %s", type(exc).__name__)
    except Exception as exc:
        LOGGER.error("Falha inesperada ao solicitar recuperação: %s", type(exc).__name__)
    return {"ok": True, "message": RECOVERY_REQUEST_MESSAGE, "cooldown_seconds": 60}


@app.post("/api/auth/recovery/verify")
async def api_password_recovery_verify(request: Request, payload: PasswordRecoveryVerifyRequest):
    sid = _sid(request)
    if store.is_authenticated(sid):
        raise HTTPException(status_code=409, detail="Encerre a sessão atual antes de recuperar outra senha.")
    if not limiter.allow(f"recovery-verify:{sid}", limit=8, window_seconds=10 * 60):
        raise HTTPException(status_code=429, detail="Muitas tentativas de código. Solicite um novo código e aguarde alguns minutos.")
    try:
        recovery = await asyncio.to_thread(supabase.verify_recovery_otp, payload.email, payload.code)
        with store.lock(sid):
            store.set_recovery(sid, email=recovery.email, access_token=recovery.access_token)
        return {"ok": True}
    except (AuthenticationRejected, RecoveryCodeRejected) as exc:
        raise HTTPException(status_code=400, detail="Código inválido ou expirado. Solicite um novo código e tente novamente.") from exc
    except SupabaseUnavailable as exc:
        LOGGER.error("Falha externa ao validar código de recuperação: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Não foi possível validar o código no momento. Tente novamente.") from exc
    except Exception as exc:
        LOGGER.error("Falha inesperada ao validar código de recuperação: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Não foi possível validar o código no momento. Tente novamente.") from exc


@app.post("/api/auth/recovery/update")
async def api_password_recovery_update(request: Request, payload: PasswordRecoveryUpdateRequest):
    sid = _sid(request)
    if store.is_authenticated(sid):
        raise HTTPException(status_code=409, detail="Encerre a sessão atual antes de recuperar outra senha.")
    try:
        if payload.password != payload.confirm_password:
            raise HTTPException(status_code=400, detail="As senhas informadas não coincidem.")
        password_error = _password_validation_error(payload.password)
        if password_error:
            raise HTTPException(status_code=400, detail=password_error)
        if not limiter.allow(f"recovery-update:{sid}", limit=6, window_seconds=10 * 60):
            raise HTTPException(status_code=429, detail="Muitas tentativas de alteração. Solicite um novo código e aguarde alguns minutos.")
        try:
            _email, access_token = store.recovery_context(sid, max_age_seconds=RECOVERY_CONTEXT_TTL_SECONDS)
        except KeyError as exc:
            raise HTTPException(status_code=401, detail="Sua confirmação de recuperação expirou. Solicite um novo código.") from exc
        try:
            await asyncio.to_thread(supabase.update_recovery_password, access_token, payload.password)
        except RecoveryCodeRejected as exc:
            store.clear_recovery(sid)
            raise HTTPException(status_code=401, detail="Sua confirmação de recuperação expirou. Solicite um novo código.") from exc
        except SupabaseUnavailable as exc:
            LOGGER.error("Falha externa ao atualizar senha recuperada: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="Não foi possível atualizar a senha no momento. Tente novamente.") from exc
        try:
            await asyncio.to_thread(supabase.end_recovery_session, access_token)
        except SupabaseUnavailable as exc:
            LOGGER.warning("Sessão de recuperação já atualizada não pôde ser revogada imediatamente: %s", type(exc).__name__)
        store.destroy_session(sid)
        request.state.session_destroyed = True
        return {"ok": True, "message": "Senha atualizada com sucesso. Entre novamente usando a nova senha."}
    finally:
        payload.password = ""
        payload.confirm_password = ""


@app.post("/api/auth/login")
async def api_login(request: Request, payload: LoginRequest):
    sid = _sid(request)
    if store.is_authenticated(sid):
        raise HTTPException(status_code=409, detail="Encerre a sessão atual antes de entrar com outro usuário.")
    peer = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "unknown")).split(",")[0].strip()
    login_key = f"login:{peer}:{payload.email.strip().casefold()}"
    if not limiter.allow(login_key, limit=12, window_seconds=10 * 60):
        raise HTTPException(status_code=429, detail="Muitas tentativas de login. Aguarde alguns minutos e tente novamente.")
    try:
        identity = await asyncio.to_thread(supabase.sign_in, payload.email, payload.password)
        authorized = await asyncio.to_thread(supabase.authorize_user, identity)
        with store.lock(sid):
            store.authenticate(
                sid,
                user_id=authorized.user_id,
                email=authorized.email,
                name=authorized.name,
                profile=authorized.profile,
            )
            base = await asyncio.to_thread(engine.load_persistent_base, sid)
        return {
            "ok": True,
            "email": authorized.email,
            "name": authorized.name,
            "profile": authorized.profile,
            "base": base,
        }
    except AuthenticationRejected as exc:
        store.clear_authentication(sid)
        raise HTTPException(status_code=401, detail="E-mail ou senha inválidos.") from exc
    except UserAccessDisabled as exc:
        store.clear_authentication(sid)
        raise HTTPException(status_code=403, detail="Seu acesso está desativado. Entre em contato com o administrador.") from exc
    except UserNotAuthorized as exc:
        store.clear_authentication(sid)
        raise HTTPException(status_code=403, detail="Seu usuário não possui autorização para acessar este sistema.") from exc
    except SupabaseUnavailable as exc:
        store.clear_authentication(sid)
        LOGGER.error("Falha de integração externa durante o login: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Não foi possível realizar o login no momento. Tente novamente.") from exc
    except Exception as exc:
        store.clear_authentication(sid)
        LOGGER.error("Falha inesperada durante o login: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Não foi possível realizar o login no momento. Tente novamente.") from exc
    finally:
        payload.password = ""


@app.post("/api/auth/logout")
def api_logout(request: Request):
    sid = _sid(request)
    store.destroy_session(sid)
    request.state.session_destroyed = True
    return {"ok": True}


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
            "user": {
                "email": state.authenticated_email,
                "name": state.authenticated_name,
                "profile": state.authenticated_profile,
            },
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


async def _materialize_financial_uploads(sid: str, upload_ids: list[str], work: Path) -> list[Path]:
    materialized: list[Path] = []
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
    return materialized


async def _rebuild_report(sid: str, new_upload_ids: list[str] | None = None) -> dict[str, Any]:
    additions = list(dict.fromkeys(new_upload_ids or []))
    existing = list(store.state(sid).financial_upload_ids)
    all_ids = list(dict.fromkeys([*existing, *additions]))
    if not all_ids:
        raise RuntimeError("Não há planilhas financeiras protegidas nesta sessão para atualizar o relatório.")
    work = store.new_work_dir(sid, "report_refresh")
    try:
        materialized = await _materialize_financial_uploads(sid, all_ids, work)
        async with heavy_jobs:
            with store.lock(sid):
                validated = await asyncio.to_thread(engine.validate, sid, materialized)
                result = await asyncio.to_thread(engine.generate, sid)
                store.replace_financial_uploads(sid, all_ids)
        stamp = int(time.time())
        return {
            "ok": True,
            "summary": engine.validation_summary(validated),
            "report_url": f"{result['report_url']}?v={stamp}",
            "pdf_url": f"{result['pdf_url']}?v={stamp}",
        }
    except Exception:
        store.discard_uploads(sid, [item for item in additions if item not in existing])
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


@app.post("/api/validate")
async def api_validate(request: Request, payload: UploadIdsRequest):
    sid = _sid(request)
    upload_ids = list(dict.fromkeys(payload.upload_ids))
    work = store.new_work_dir(sid, "validation")
    previous_ids = list(store.state(sid).financial_upload_ids)
    accepted = False
    try:
        materialized = await _materialize_financial_uploads(sid, upload_ids, work)

        with store.lock(sid):
            store.invalidate_validation(sid, preserve_last_outputs=True)
        async with heavy_jobs:
            with store.lock(sid):
                validated = await asyncio.to_thread(engine.validate, sid, materialized)
                store.replace_financial_uploads(sid, upload_ids)
                accepted = True
        summary = engine.validation_summary(validated)
        return {"ok": True, "summary": summary}
    except Exception as exc:
        with suppress(Exception):
            store.invalidate_validation(sid, preserve_last_outputs=True)
        raise HTTPException(status_code=400, detail=_safe_error(exc)) from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if not accepted:
            store.discard_uploads(sid, [item for item in upload_ids if item not in previous_ids])


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


@app.post("/api/report/refresh")
async def api_report_refresh(request: Request, payload: ReportRefreshRequest):
    try:
        return await _rebuild_report(_sid(request), payload.upload_ids)
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


@app.get("/api/base/options")
def api_base_options(request: Request):
    try:
        return engine.base_options(_sid(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=_safe_error(exc)) from exc


@app.put("/api/base")
async def api_base_update(request: Request, payload: BaseUpdateRequest):
    sid = _sid(request)
    try:
        items = [item.model_dump() for item in payload.items]
        async with heavy_jobs:
            with store.lock(sid):
                info = await asyncio.to_thread(engine.update_base, sid, items)
        return {"ok": True, "base": info}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"A base anterior foi preservada. {_safe_error(exc)}") from exc


@app.post("/api/base/import")
async def api_base_import(request: Request, payload: BaseImportRequest):
    sid = _sid(request)
    work = store.new_work_dir(sid, "base_import")
    completed = False
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
                result = await asyncio.to_thread(
                    engine.import_base,
                    sid,
                    dest,
                    mode=payload.mode,
                    duplicate_action=payload.duplicate_action,
                    edited_duplicates=[item.model_dump() for item in payload.edited_duplicates],
                )
        completed = bool(result.get("ok"))
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"A base anterior foi preservada. {_safe_error(exc)}") from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if completed:
            store.discard_upload(sid, payload.upload_id)


@app.post("/api/base/classifications")
async def api_base_classifications(request: Request, payload: ClassificationUpdateRequest):
    sid = _sid(request)
    try:
        assignments = [item.model_dump() for item in payload.assignments]
        async with heavy_jobs:
            with store.lock(sid):
                base = await asyncio.to_thread(engine.apply_classifications, sid, assignments)
        refreshed = await _rebuild_report(sid)
        return {**refreshed, "base": base}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"A base anterior e o relatório anterior foram preservados. {_safe_error(exc)}") from exc


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
