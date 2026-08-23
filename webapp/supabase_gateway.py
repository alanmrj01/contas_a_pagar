from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


BASE_AAD_PREFIX = "cap-persistent-base-v1"
BASE_TABLE = "contas_a_pagar_bases"
AUTHORIZED_USERS_TABLE = "usuarios_autorizados"
VALID_PROFILES = frozenset({"administrador", "basico"})


class SupabaseUnavailable(RuntimeError):
    pass


class AuthenticationRejected(RuntimeError):
    pass


class RecoveryCodeRejected(RuntimeError):
    pass


class UserNotAuthorized(RuntimeError):
    pass


class UserAccessDisabled(RuntimeError):
    pass


@dataclass(frozen=True)
class AuthIdentity:
    user_id: str
    email: str


@dataclass(frozen=True)
class RecoverySession:
    email: str
    access_token: str


@dataclass(frozen=True)
class AuthorizedUser:
    user_id: str
    email: str
    name: str
    profile: str


def _clean_url(value: str) -> str:
    return value.strip().rstrip("/")


def _decode_storage_key(value: str) -> bytes:
    raw = value.strip()
    if not raw:
        raise SupabaseUnavailable("A chave de proteção da BASE DADOS não foi configurada.")
    try:
        if re.fullmatch(r"[A-Fa-f0-9]{64}", raw):
            key = bytes.fromhex(raw)
        else:
            key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except Exception as exc:
        raise SupabaseUnavailable("A chave de proteção da BASE DADOS possui formato inválido.") from exc
    if len(key) != 32:
        raise SupabaseUnavailable("A chave de proteção da BASE DADOS precisa ter exatamente 32 bytes.")
    return key


class SupabaseGateway:
    """Autenticação e persistência cifrada via APIs oficiais do Supabase.

    A senha é enviada ao Supabase Auth somente durante o login e nunca é
    armazenada pela aplicação. A BASE DADOS é cifrada localmente com AES-256-GCM
    antes de ser enviada ao PostgREST.
    """

    def __init__(self) -> None:
        self.url = _clean_url(os.getenv("SUPABASE_URL", ""))
        self.publishable_key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
        self.secret_key = os.getenv("SUPABASE_SECRET_KEY", "").strip()
        self._storage_key_value = os.getenv("PERSISTENT_BASE_KEY_B64", "").strip()
        self.timeout_seconds = 15

    @property
    def configured(self) -> bool:
        return bool(
            self.url
            and self.publishable_key
            and self.secret_key
            and self._storage_key_value
        )

    def _require_configuration(self) -> None:
        if not self.configured:
            raise SupabaseUnavailable(
                "A autenticação segura ainda não foi configurada no ambiente de hospedagem."
            )
        parsed = urllib.parse.urlparse(self.url)
        local_hosts = {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and parsed.hostname not in local_hosts:
            raise SupabaseUnavailable("A URL do serviço de autenticação precisa usar HTTPS.")

    @staticmethod
    def _headers(api_key: str, *, json_body: bool = True) -> dict[str, str]:
        headers = {
            "apikey": api_key,
            "Accept": "application/json",
            "User-Agent": "ContasAPagarWeb/2.1",
        }
        if json_body:
            headers["Content-Type"] = "application/json"
        # As chaves legadas são JWTs e precisam do Bearer. As novas chaves
        # sb_publishable_/sb_secret_ são enviadas somente no header apikey.
        if api_key.count(".") == 2:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _request_json(
        self,
        method: str,
        endpoint: str,
        *,
        api_key: str,
        payload: Any | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = self._headers(api_key, json_body=payload is not None)
        if extra_headers:
            headers.update(extra_headers)
        request = urllib.request.Request(
            f"{self.url}{endpoint}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read(50 * 1024 * 1024 + 1)
                if len(body) > 50 * 1024 * 1024:
                    raise SupabaseUnavailable("A resposta do armazenamento externo excedeu o limite seguro.")
                return json.loads(body.decode("utf-8")) if body else None
        except urllib.error.HTTPError as exc:
            safe_status = int(getattr(exc, "code", 0) or 0)
            if endpoint.startswith("/auth/v1/") and safe_status in {400, 401, 403, 422}:
                raise AuthenticationRejected("E-mail ou senha inválidos.") from exc
            raise SupabaseUnavailable("O serviço externo recusou a operação segura solicitada.") from exc
        except AuthenticationRejected:
            raise
        except Exception as exc:
            raise SupabaseUnavailable("Não foi possível acessar o serviço seguro de autenticação e dados.") from exc

    @staticmethod
    def normalize_email(value: str) -> str:
        email = str(value or "").strip().lower()
        local, separator, domain = email.partition("@")
        valid = (
            separator == "@"
            and local
            and domain
            and "@" not in domain
            and not any(character.isspace() for character in email)
            and len(local) <= 64
            and len(email) <= 320
        )
        if not valid:
            raise AuthenticationRejected("E-mail ou senha inválidos.")
        return email

    def sign_in(self, email: str, password: str) -> AuthIdentity:
        self._require_configuration()
        normalized_email = self.normalize_email(email)
        if not password:
            raise AuthenticationRejected("E-mail ou senha inválidos.")
        payload = self._request_json(
            "POST",
            "/auth/v1/token?grant_type=password",
            api_key=self.publishable_key,
            payload={"email": normalized_email, "password": password},
        )
        user = payload.get("user") if isinstance(payload, dict) else None
        user_id = str((user or {}).get("id") or "").strip()
        returned_email = str((user or {}).get("email") or "").strip().lower()
        if not user_id or returned_email != normalized_email:
            raise AuthenticationRejected("E-mail ou senha inválidos.")
        return AuthIdentity(user_id=user_id, email=returned_email)

    def request_password_recovery(self, email: str) -> None:
        """Solicita ao Supabase o e-mail oficial de recuperação, sem enumerar usuários."""

        self._require_configuration()
        normalized_email = self.normalize_email(email)
        self._request_json(
            "POST",
            "/auth/v1/recover",
            api_key=self.publishable_key,
            payload={"email": normalized_email},
        )

    def verify_recovery_otp(self, email: str, token: str) -> RecoverySession:
        """Troca o OTP de recovery por uma sessão temporária mantida somente no servidor."""

        self._require_configuration()
        normalized_email = self.normalize_email(email)
        normalized_token = str(token or "").strip()
        if not re.fullmatch(r"[0-9]{6}", normalized_token):
            raise RecoveryCodeRejected("Código de recuperação inválido ou expirado.")
        try:
            payload = self._request_json(
                "POST",
                "/auth/v1/verify",
                api_key=self.publishable_key,
                payload={"email": normalized_email, "token": normalized_token, "type": "recovery"},
            )
        except AuthenticationRejected as exc:
            raise RecoveryCodeRejected("Código de recuperação inválido ou expirado.") from exc
        user = payload.get("user") if isinstance(payload, dict) else None
        returned_email = str((user or {}).get("email") or "").strip().lower()
        access_token = str((payload or {}).get("access_token") or "").strip() if isinstance(payload, dict) else ""
        if returned_email != normalized_email or not access_token or len(access_token) > 8192:
            raise RecoveryCodeRejected("Código de recuperação inválido ou expirado.")
        return RecoverySession(email=returned_email, access_token=access_token)

    def update_recovery_password(self, access_token: str, password: str) -> None:
        """Atualiza a senha com o JWT temporário emitido pelo verifyOtp de recovery."""

        self._require_configuration()
        token = str(access_token or "").strip()
        if not token or len(token) > 8192:
            raise RecoveryCodeRejected("A confirmação de recuperação expirou.")
        try:
            result = self._request_json(
                "PUT",
                "/auth/v1/user",
                api_key=self.publishable_key,
                payload={"password": password},
                extra_headers={"Authorization": f"Bearer {token}"},
            )
        except AuthenticationRejected as exc:
            raise RecoveryCodeRejected("A confirmação de recuperação expirou.") from exc
        if not isinstance(result, dict) or not str(result.get("id") or "").strip():
            raise SupabaseUnavailable("O serviço de autenticação não confirmou a atualização da senha.")

    def end_recovery_session(self, access_token: str) -> None:
        """Revoga a sessão Supabase criada exclusivamente para a recuperação."""

        self._require_configuration()
        token = str(access_token or "").strip()
        if not token:
            return
        try:
            self._request_json(
                "POST",
                "/auth/v1/logout?scope=local",
                api_key=self.publishable_key,
                extra_headers={"Authorization": f"Bearer {token}"},
            )
        except AuthenticationRejected:
            # Sessão já expirada/revogada equivale ao resultado pretendido.
            return

    def authorize_user(self, identity: AuthIdentity) -> AuthorizedUser:
        """Valida a autorização no servidor depois do sucesso no Supabase Auth."""

        self._require_configuration()
        query = urllib.parse.urlencode({
            "select": "user_id,email,nome,perfil,ativo",
            "user_id": f"eq.{identity.user_id}",
            "limit": "2",
        })
        rows = self._request_json(
            "GET",
            f"/rest/v1/{AUTHORIZED_USERS_TABLE}?{query}",
            api_key=self.secret_key,
        )
        if not isinstance(rows, list) or len(rows) != 1:
            raise UserNotAuthorized("Usuário autenticado sem autorização ativa.")

        record = rows[0] if isinstance(rows[0], dict) else {}
        if str(record.get("user_id") or "").strip() != identity.user_id:
            raise UserNotAuthorized("Usuário autenticado sem autorização ativa.")
        if record.get("ativo") is not True:
            raise UserAccessDisabled("O acesso deste usuário está desativado.")

        profile = str(record.get("perfil") or "").strip().lower()
        if profile not in VALID_PROFILES:
            raise UserNotAuthorized("Perfil de acesso não reconhecido.")
        name = str(record.get("nome") or "").strip()
        return AuthorizedUser(
            user_id=identity.user_id,
            email=identity.email,
            name=name,
            profile=profile,
        )

    def _base_key(self) -> bytes:
        self._require_configuration()
        return _decode_storage_key(self._storage_key_value)

    @staticmethod
    def _aad(user_id: str) -> bytes:
        return f"{BASE_AAD_PREFIX}|{user_id}".encode("utf-8")

    def load_base(self, user_id: str) -> tuple[list[dict[str, str]], str] | None:
        self._require_configuration()
        query = urllib.parse.urlencode({
            "select": "ciphertext,nonce,revision,row_count",
            "user_id": f"eq.{user_id}",
            "limit": "1",
        })
        rows = self._request_json(
            "GET",
            f"/rest/v1/{BASE_TABLE}?{query}",
            api_key=self.secret_key,
        )
        if not rows:
            return None
        record = rows[0]
        try:
            nonce = base64.b64decode(str(record["nonce"]), validate=True)
            cipher = base64.b64decode(str(record["ciphertext"]), validate=True)
            plain = AESGCM(self._base_key()).decrypt(nonce, cipher, self._aad(user_id))
            document = json.loads(plain.decode("utf-8"))
            if document.get("schema") != 1 or not isinstance(document.get("items"), list):
                raise ValueError("schema")
            items = [
                {
                    "supplier_code": str(item.get("supplier_code") or "").strip(),
                    "supplier": str(item.get("supplier") or "").strip(),
                    "flow": str(item.get("flow") or "").strip(),
                    "category": str(item.get("category") or "").strip(),
                }
                for item in document["items"]
                if isinstance(item, dict)
            ]
            if int(record.get("row_count") or -1) != len(items):
                raise ValueError("row_count")
            return items, str(record.get("revision") or "")
        except Exception as exc:
            raise SupabaseUnavailable(
                "A BASE DADOS persistida não passou na verificação criptográfica. A operação foi interrompida."
            ) from exc

    def save_base(self, user_id: str, items: list[dict[str, str]]) -> str:
        self._require_configuration()
        canonical = [
            {
                "supplier_code": str(item.get("supplier_code") or "").strip(),
                "supplier": str(item.get("supplier") or "").strip(),
                "flow": str(item.get("flow") or "").strip(),
                "category": str(item.get("category") or "").strip(),
            }
            for item in items
        ]
        plain = json.dumps(
            {"schema": 1, "items": canonical},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        nonce = os.urandom(12)
        cipher = AESGCM(self._base_key()).encrypt(nonce, plain, self._aad(user_id))
        revision = hashlib.sha256(nonce + cipher).hexdigest()[:12]
        payload = {
            "user_id": user_id,
            "ciphertext": base64.b64encode(cipher).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "revision": revision,
            "row_count": len(canonical),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._request_json(
            "POST",
            f"/rest/v1/{BASE_TABLE}?on_conflict=user_id",
            api_key=self.secret_key,
            payload=payload,
            extra_headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )
        return revision
