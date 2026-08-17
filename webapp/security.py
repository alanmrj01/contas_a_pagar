from __future__ import annotations

import base64
import hashlib
import hmac
import os
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except Exception as exc:  # pragma: no cover - mensagem padronizada no chamador
        raise ValueError("Payload criptográfico inválido.") from exc


def _int_b64url(value: int) -> str:
    length = max(1, (value.bit_length() + 7) // 8)
    return _b64url(value.to_bytes(length, "big"))


class RuntimeSecurity:
    """Segredos efêmeros do processo web.

    A chave RSA não é persistida e não vai para GitHub/Render Environment.
    Cada restart invalida uploads/sessões que ainda estivessem em andamento.
    """

    def __init__(self) -> None:
        self._private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        self._csrf_secret = os.urandom(32)
        public = self._private_key.public_key().public_numbers()
        self.public_jwk = {
            "kty": "RSA",
            "n": _int_b64url(public.n),
            "e": _int_b64url(public.e),
            "alg": "RSA-OAEP-256",
            "ext": True,
            "key_ops": ["encrypt"],
        }

    def unwrap_upload_key(self, wrapped_b64: str) -> bytearray:
        if not wrapped_b64 or len(wrapped_b64) > 2048:
            raise ValueError("Chave de upload inválida.")
        wrapped = _b64decode(wrapped_b64)
        try:
            raw = self._private_key.decrypt(
                wrapped,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None,
                ),
            )
        except Exception as exc:
            raise ValueError("Não foi possível validar a chave criptográfica do upload.") from exc
        if len(raw) != 32:
            raise ValueError("Chave de upload com tamanho inválido.")
        return bytearray(raw)

    def csrf_token(self, session_token: str) -> str:
        digest = hmac.new(self._csrf_secret, session_token.encode("utf-8"), hashlib.sha256).digest()
        return _b64url(digest)

    def valid_csrf(self, session_token: str, candidate: str | None) -> bool:
        if not candidate:
            return False
        return hmac.compare_digest(self.csrf_token(session_token), candidate)


class SlidingWindowLimiter:
    """Limitador antiabuso deliberadamente generoso.

    Não limita relatórios por hora. Apenas impede rajadas claramente automatizadas.
    """

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.RLock()

    def allow(self, key: str, *, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            queue = self._events[key]
            while queue and queue[0] < cutoff:
                queue.popleft()
            if len(queue) >= limit:
                return False
            queue.append(now)
            return True

    def forget_prefix(self, prefix: str) -> None:
        with self._lock:
            for key in [k for k in self._events if k.startswith(prefix)]:
                self._events.pop(key, None)


def request_origin_is_allowed(request) -> bool:
    """Valida Origin quando o navegador o fornece, sem quebrar clientes HTTP de teste.

    SameSite=Strict + CSRF continuam sendo exigidos independentemente desta camada.
    """

    origin = (request.headers.get("origin") or "").strip()
    if origin:
        parsed = urlsplit(origin)
        forwarded_proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
        forwarded_host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
        expected = f"{forwarded_proto}://{forwarded_host}".rstrip("/")
        actual = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        return hmac.compare_digest(actual.lower(), expected.lower())

    fetch_site = (request.headers.get("sec-fetch-site") or "").lower()
    return fetch_site in {"", "same-origin", "none"}
