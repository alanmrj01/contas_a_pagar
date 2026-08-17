from __future__ import annotations

import base64

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _b64u_int(value: str) -> int:
    padded = value + "=" * (-len(value) % 4)
    return int.from_bytes(base64.urlsafe_b64decode(padded), "big")


def wrap_key_from_jwk(jwk: dict, key: bytes) -> str:
    public = rsa.RSAPublicNumbers(_b64u_int(jwk["e"]), _b64u_int(jwk["n"])).public_key()
    wrapped = public.encrypt(
        key,
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    return base64.b64encode(wrapped).decode("ascii")


def stage_file(client, path, *, purpose="financial", tamper_chunk: int | None = None) -> str:
    boot = client.get("/api/security/bootstrap")
    assert boot.status_code == 200, boot.text
    security = boot.json()
    csrf = security["csrf_token"]
    key = bytes(range(32))
    wrapped = wrap_key_from_jwk(security["public_key_jwk"], key)
    data = path.read_bytes()
    init = client.post(
        "/api/uploads/init",
        headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
        json={"filename": path.name, "size": len(data), "purpose": purpose, "encrypted_key": wrapped},
    )
    assert init.status_code == 200, init.text
    info = init.json()
    upload_id = info["upload_id"]
    chunk_bytes = info["chunk_bytes"]
    aes = AESGCM(key)
    total = info["total_chunks"]
    for index in range(total):
        plain = data[index * chunk_bytes : (index + 1) * chunk_bytes]
        iv = bytes([index % 251 + 1]) * 12
        aad = f"cap-upload-v1|{upload_id}|{index}|{len(plain)}".encode()
        cipher = bytearray(aes.encrypt(iv, plain, aad))
        if tamper_chunk == index:
            cipher[len(cipher) // 2] ^= 0x01
        response = client.post(
            f"/api/uploads/{upload_id}/chunk/{index}",
            headers={
                "X-CSRF-Token": csrf,
                "X-Chunk-IV": base64.b64encode(iv).decode("ascii"),
                "X-Plain-Size": str(len(plain)),
                "Content-Type": "application/octet-stream",
            },
            content=bytes(cipher),
        )
        assert response.status_code == 200, response.text
    complete = client.post(f"/api/uploads/{upload_id}/complete", headers={"X-CSRF-Token": csrf})
    assert complete.status_code == 200, complete.text
    return upload_id
