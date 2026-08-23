from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import secrets
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .crypto_storage import seal_file

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{40,64}$")
UPLOAD_ID_RE = re.compile(r"^[a-f0-9]{32}$")
SESSION_PROFILES = frozenset({"administrador", "basico"})


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def data_root(project_root: Path) -> Path:
    raw = os.getenv("WEB_DATA_DIR", "").strip()
    root = Path(raw).expanduser() if raw else project_root / "runtime_data"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


@dataclass
class UploadRecord:
    upload_id: str
    purpose: str
    filename: str
    extension: str
    expected_size: int
    chunk_size: int
    total_chunks: int
    aes_key: bytearray
    encrypted_dir: Path
    received: set[int] = field(default_factory=set)
    created_at: float = field(default_factory=time.time)

    def expected_plain_size(self, index: int) -> int:
        if index < 0 or index >= self.total_chunks:
            raise IndexError(index)
        start = index * self.chunk_size
        return min(self.chunk_size, self.expected_size - start)

    @property
    def complete(self) -> bool:
        return len(self.received) == self.total_chunks and all(i in self.received for i in range(self.total_chunks))

    def wipe_key(self) -> None:
        for i in range(len(self.aes_key)):
            self.aes_key[i] = 0


@dataclass(frozen=True)
class SealedArtifact:
    logical_name: str
    sealed_path: Path
    content_type: str
    download_name: str
    plain_size: int


@dataclass
class SessionState:
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    active_requests: int = 0
    validated: Any | None = None
    last_report_url: str = ""
    last_pdf_url: str = ""
    last_source_names: list[str] = field(default_factory=list)
    authenticated_user_id: str = ""
    authenticated_email: str = ""
    authenticated_name: str = ""
    authenticated_profile: str = ""
    recovery_email: str = ""
    recovery_access_token: bytearray = field(default_factory=bytearray)
    recovery_verified_at: float = 0.0
    custom_base_table: Any | None = None
    custom_base_revision: str = ""
    artifact_key: bytearray = field(default_factory=lambda: bytearray(os.urandom(32)))
    report_artifacts: dict[str, SealedArtifact] = field(default_factory=dict)
    report_artifact_root: Path | None = None
    report_script_hashes: list[str] = field(default_factory=list)
    uploads: dict[str, UploadRecord] = field(default_factory=dict)
    financial_upload_ids: list[str] = field(default_factory=list)

    def wipe_artifact_key(self) -> None:
        for i in range(len(self.artifact_key)):
            self.artifact_key[i] = 0

    def wipe_recovery(self) -> None:
        for i in range(len(self.recovery_access_token)):
            self.recovery_access_token[i] = 0
        self.recovery_access_token = bytearray()
        self.recovery_email = ""
        self.recovery_verified_at = 0.0


class SessionStore:
    """Sessões autenticadas isoladas, efêmeras e não identificáveis por URL."""

    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self.root = data_root(self.project_root)
        self.sessions_root = self.root / "sessions"
        # Chaves são exclusivamente em memória. Após restart, qualquer conteúdo
        # residual seria indecriptável; portanto ele é eliminado no startup.
        shutil.rmtree(self.sessions_root, ignore_errors=True)
        self.sessions_root.mkdir(parents=True, exist_ok=True)

        self.session_ttl_seconds = _env_int("WEB_SESSION_TTL_SECONDS", 2 * 60 * 60, 15 * 60, 24 * 60 * 60)
        self.max_upload_bytes = _env_int("MAX_UPLOAD_BYTES", 200 * 1024 * 1024, 1 * 1024 * 1024, 1024 * 1024 * 1024)
        self.upload_chunk_bytes = _env_int("UPLOAD_CHUNK_BYTES", 16 * 1024 * 1024, 1 * 1024 * 1024, 32 * 1024 * 1024)
        self.max_session_staged_bytes = _env_int("MAX_SESSION_STAGED_BYTES", 2 * 1024 * 1024 * 1024, self.max_upload_bytes, 8 * 1024 * 1024 * 1024)
        self.max_office_expanded_bytes = _env_int("MAX_OFFICE_EXPANDED_BYTES", 2 * 1024 * 1024 * 1024, 128 * 1024 * 1024, 8 * 1024 * 1024 * 1024)

        self._states: dict[str, SessionState] = {}
        self._locks: dict[str, threading.RLock] = {}
        self._guard = threading.RLock()

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def valid_token(value: str | None) -> bool:
        return bool(value and TOKEN_RE.fullmatch(value))

    def resolve_session(self, current_token: str | None) -> tuple[str, str, bool]:
        now = time.time()
        if self.valid_token(current_token):
            key = self.token_hash(current_token or "")
            with self._guard:
                state = self._states.get(key)
                if state and now - state.last_activity < self.session_ttl_seconds:
                    state.last_activity = now
                    return current_token or "", key, False
        return self.create_session()

    def create_session(self) -> tuple[str, str, bool]:
        with self._guard:
            while True:
                token = secrets.token_urlsafe(32)
                key = self.token_hash(token)
                if key not in self._states:
                    break
            self._states[key] = SessionState()
            self._locks[key] = threading.RLock()
            self.session_dir(key)
            return token, key, True

    def has_session(self, key: str) -> bool:
        with self._guard:
            return key in self._states

    def state(self, key: str) -> SessionState:
        with self._guard:
            state = self._states.get(key)
            if state is None:
                raise KeyError("Sessão expirada.")
            state.last_activity = time.time()
            return state

    def is_authenticated(self, key: str) -> bool:
        try:
            state = self.state(key)
            return bool(
                state.authenticated_user_id
                and state.authenticated_email
                and state.authenticated_profile in SESSION_PROFILES
            )
        except KeyError:
            return False

    def authenticate(
        self,
        key: str,
        *,
        user_id: str,
        email: str,
        name: str,
        profile: str,
    ) -> SessionState:
        normalized_profile = str(profile or "").strip().lower()
        if normalized_profile not in SESSION_PROFILES:
            raise ValueError("Perfil de sessão inválido.")
        state = self.state(key)
        state.authenticated_user_id = str(user_id)
        state.authenticated_email = str(email).strip().lower()
        state.authenticated_name = str(name).strip()
        state.authenticated_profile = normalized_profile
        state.wipe_recovery()
        state.last_activity = time.time()
        return state

    def clear_authentication(self, key: str) -> None:
        state = self.state(key)
        state.authenticated_user_id = ""
        state.authenticated_email = ""
        state.authenticated_name = ""
        state.authenticated_profile = ""
        state.custom_base_table = None
        state.custom_base_revision = ""
        state.wipe_recovery()

    def set_recovery(self, key: str, *, email: str, access_token: str) -> None:
        encoded = str(access_token or "").encode("utf-8")
        if not encoded or len(encoded) > 8192:
            raise ValueError("Sessão de recuperação inválida.")
        state = self.state(key)
        state.wipe_recovery()
        state.recovery_email = str(email or "").strip().lower()
        state.recovery_access_token = bytearray(encoded)
        state.recovery_verified_at = time.time()

    def recovery_context(self, key: str, *, max_age_seconds: int) -> tuple[str, str]:
        state = self.state(key)
        if (
            not state.recovery_email
            or not state.recovery_access_token
            or time.time() - state.recovery_verified_at > max_age_seconds
        ):
            state.wipe_recovery()
            raise KeyError("Sessão de recuperação ausente ou expirada.")
        try:
            token = bytes(state.recovery_access_token).decode("utf-8")
        except UnicodeDecodeError as exc:
            state.wipe_recovery()
            raise KeyError("Sessão de recuperação inválida.") from exc
        return state.recovery_email, token

    def clear_recovery(self, key: str) -> None:
        self.state(key).wipe_recovery()

    def touch(self, key: str) -> None:
        with self._guard:
            state = self._states.get(key)
            if state:
                state.last_activity = time.time()

    def begin_request(self, key: str) -> None:
        with self._guard:
            state = self._states.get(key)
            if state:
                state.active_requests += 1
                state.last_activity = time.time()

    def end_request(self, key: str) -> None:
        with self._guard:
            state = self._states.get(key)
            if state:
                state.active_requests = max(0, state.active_requests - 1)
                state.last_activity = time.time()

    def lock(self, key: str) -> threading.RLock:
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                raise KeyError("Sessão expirada.")
            return lock

    def session_dir(self, key: str) -> Path:
        path = self.sessions_root / key
        path.mkdir(parents=True, exist_ok=True)
        return path

    def upload_dir(self, key: str) -> Path:
        path = self.session_dir(key) / "uploads_encrypted"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def temp_dir(self, key: str) -> Path:
        path = self.session_dir(key) / "plaintext_work"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def new_work_dir(self, key: str, kind: str) -> Path:
        safe_kind = re.sub(r"[^A-Za-z0-9_-]", "_", kind)[:40] or "work"
        path = self.temp_dir(key) / f"{safe_kind}_{secrets.token_hex(8)}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def new_report_staging(self, key: str) -> Path:
        return self.new_work_dir(key, "report")

    def register_upload(self, key: str, *, purpose: str, filename: str, extension: str, expected_size: int, aes_key: bytearray) -> UploadRecord:
        if expected_size <= 0 or expected_size > self.max_upload_bytes:
            raise RuntimeError(f"Cada arquivo pode ter no máximo {self.max_upload_bytes // (1024 * 1024)} MB.")
        state = self.state(key)
        staged = sum(rec.expected_size for rec in state.uploads.values())
        if staged + expected_size > self.max_session_staged_bytes:
            raise RuntimeError("O volume total de arquivos preparados nesta sessão ultrapassou o limite de segurança. Valide os arquivos atuais antes de adicionar um novo lote.")
        upload_id = secrets.token_hex(16)
        total_chunks = (expected_size + self.upload_chunk_bytes - 1) // self.upload_chunk_bytes
        encrypted_dir = self.upload_dir(key) / upload_id
        encrypted_dir.mkdir(parents=True, exist_ok=False)
        record = UploadRecord(
            upload_id=upload_id,
            purpose=purpose,
            filename=filename,
            extension=extension,
            expected_size=expected_size,
            chunk_size=self.upload_chunk_bytes,
            total_chunks=total_chunks,
            aes_key=aes_key,
            encrypted_dir=encrypted_dir,
        )
        state.uploads[upload_id] = record
        return record

    def upload_record(self, key: str, upload_id: str, *, purpose: str | None = None) -> UploadRecord:
        if not UPLOAD_ID_RE.fullmatch(upload_id or ""):
            raise KeyError("Upload inválido.")
        record = self.state(key).uploads.get(upload_id)
        if record is None or (purpose and record.purpose != purpose):
            raise KeyError("Upload não encontrado nesta sessão.")
        return record

    def mark_chunk(self, key: str, upload_id: str, index: int) -> None:
        record = self.upload_record(key, upload_id)
        if index < 0 or index >= record.total_chunks:
            raise IndexError("Bloco fora do intervalo esperado.")
        record.received.add(index)
        self.touch(key)

    def discard_upload(self, key: str, upload_id: str) -> None:
        try:
            state = self.state(key)
        except KeyError:
            return
        record = state.uploads.pop(upload_id, None)
        state.financial_upload_ids = [item for item in state.financial_upload_ids if item != upload_id]
        if record:
            record.wipe_key()
            shutil.rmtree(record.encrypted_dir, ignore_errors=True)

    def discard_uploads(self, key: str, upload_ids: list[str]) -> None:
        for upload_id in dict.fromkeys(upload_ids):
            self.discard_upload(key, upload_id)

    def clear_uploads(self, key: str) -> None:
        try:
            ids = list(self.state(key).uploads)
        except KeyError:
            return
        self.discard_uploads(key, ids)
        shutil.rmtree(self.upload_dir(key), ignore_errors=True)
        self.upload_dir(key)

    def replace_financial_uploads(self, key: str, upload_ids: list[str]) -> None:
        state = self.state(key)
        unique = list(dict.fromkeys(upload_ids))
        for upload_id in unique:
            record = self.upload_record(key, upload_id, purpose="financial")
            if not record.complete:
                raise RuntimeError("Um dos arquivos financeiros protegidos está incompleto.")
        previous = list(state.financial_upload_ids)
        state.financial_upload_ids = unique
        for old_id in previous:
            if old_id not in unique:
                self.discard_upload(key, old_id)

    def financial_uploads(self, key: str) -> list[UploadRecord]:
        state = self.state(key)
        return [self.upload_record(key, upload_id, purpose="financial") for upload_id in state.financial_upload_ids]

    def replace_report_artifacts(self, key: str, source_dir: Path, script_hashes: list[str]) -> None:
        state = self.state(key)
        artifact_root = self.session_dir(key) / "artifacts" / secrets.token_hex(8)
        artifact_root.mkdir(parents=True, exist_ok=False)
        new_map: dict[str, SealedArtifact] = {}
        try:
            for source in sorted(Path(source_dir).rglob("*")):
                if not source.is_file():
                    continue
                logical = source.relative_to(source_dir).as_posix()
                target = artifact_root / f"{logical}.capenc"
                size = seal_file(source, target, bytes(state.artifact_key), logical)
                content_type = mimetypes.guess_type(logical)[0] or "application/octet-stream"
                new_map[logical] = SealedArtifact(
                    logical_name=logical,
                    sealed_path=target,
                    content_type=content_type,
                    download_name=PurePosixPath(logical).name,
                    plain_size=size,
                )
            if "index.html" not in new_map or "Relatorio_Contas_a_Pagar.pdf" not in new_map:
                raise RuntimeError("A geração não produziu todos os artefatos obrigatórios.")
            old_root = state.report_artifact_root
            state.report_artifacts = new_map
            state.report_artifact_root = artifact_root
            state.report_script_hashes = list(script_hashes)
            state.last_report_url = "/report/current"
            state.last_pdf_url = "/report/Relatorio_Contas_a_Pagar.pdf"
            if old_root and old_root != artifact_root:
                shutil.rmtree(old_root, ignore_errors=True)
        except Exception:
            shutil.rmtree(artifact_root, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(source_dir, ignore_errors=True)

    def report_artifact(self, key: str, logical_name: str) -> SealedArtifact:
        logical = PurePosixPath(logical_name)
        if logical.is_absolute() or ".." in logical.parts:
            raise KeyError("Artefato inválido.")
        artifact = self.state(key).report_artifacts.get(logical.as_posix())
        if artifact is None:
            raise KeyError("Artefato não encontrado.")
        return artifact

    def clear_report(self, key: str) -> None:
        state = self.state(key)
        if state.report_artifact_root:
            shutil.rmtree(state.report_artifact_root, ignore_errors=True)
        state.report_artifacts = {}
        state.report_artifact_root = None
        state.report_script_hashes = []
        state.last_report_url = ""
        state.last_pdf_url = ""

    def invalidate_validation(self, key: str, *, preserve_last_outputs: bool = True) -> None:
        state = self.state(key)
        state.validated = None
        state.last_source_names = []
        if not preserve_last_outputs:
            self.clear_report(key)

    def destroy_session(self, key: str) -> None:
        with self._guard:
            state = self._states.pop(key, None)
            self._locks.pop(key, None)
        if state:
            for record in state.uploads.values():
                record.wipe_key()
            state.wipe_artifact_key()
            state.validated = None
            state.authenticated_user_id = ""
            state.authenticated_email = ""
            state.authenticated_name = ""
            state.authenticated_profile = ""
            state.wipe_recovery()
            state.custom_base_table = None
            state.custom_base_revision = ""
            state.financial_upload_ids = []
        shutil.rmtree(self.sessions_root / key, ignore_errors=True)

    def cleanup_expired(self) -> int:
        now = time.time()
        with self._guard:
            expired = [
                key for key, state in self._states.items()
                if state.active_requests == 0 and now - state.last_activity >= self.session_ttl_seconds
            ]
        for key in expired:
            self.destroy_session(key)
        return len(expired)
