from __future__ import annotations

import os
import struct
import zipfile
from pathlib import Path
from typing import Iterator

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ARTIFACT_MAGIC = b"CAPART01"
ARTIFACT_CHUNK = 1024 * 1024
_HEADER = struct.Struct("!8sIQ")
_LEN = struct.Struct("!I")
ZIP_OFFICE_EXTENSIONS = {".xlsx", ".xlsm", ".xlsb"}
OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
ZIP_MAGIC = b"PK\x03\x04"


def upload_aad(upload_id: str, index: int, plain_size: int) -> bytes:
    return f"cap-upload-v1|{upload_id}|{index}|{plain_size}".encode("utf-8")


def artifact_aad(logical_name: str, index: int, plain_size: int) -> bytes:
    return f"cap-artifact-v1|{logical_name}|{index}|{plain_size}".encode("utf-8")


def seal_file(source: Path, destination: Path, key: bytes, logical_name: str) -> int:
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = source.stat().st_size
    aes = AESGCM(key)
    temp = destination.with_suffix(destination.suffix + ".tmp")
    try:
        with source.open("rb") as src, temp.open("wb") as dst:
            dst.write(_HEADER.pack(ARTIFACT_MAGIC, ARTIFACT_CHUNK, total))
            index = 0
            while True:
                plain = src.read(ARTIFACT_CHUNK)
                if not plain:
                    break
                iv = os.urandom(12)
                cipher = aes.encrypt(iv, plain, artifact_aad(logical_name, index, len(plain)))
                dst.write(iv)
                dst.write(_LEN.pack(len(plain)))
                dst.write(cipher)
                index += 1
        temp.replace(destination)
    finally:
        temp.unlink(missing_ok=True)
    return total


def iter_unseal_file(source: Path, key: bytes, logical_name: str) -> Iterator[bytes]:
    source = Path(source)
    aes = AESGCM(key)
    with source.open("rb") as fh:
        raw = fh.read(_HEADER.size)
        if len(raw) != _HEADER.size:
            raise RuntimeError("Artefato protegido incompleto.")
        magic, chunk_size, total_expected = _HEADER.unpack(raw)
        if magic != ARTIFACT_MAGIC or chunk_size <= 0 or chunk_size > 8 * 1024 * 1024:
            raise RuntimeError("Artefato protegido inválido.")
        total = 0
        index = 0
        while total < total_expected:
            iv = fh.read(12)
            raw_len = fh.read(_LEN.size)
            if len(iv) != 12 or len(raw_len) != _LEN.size:
                raise RuntimeError("Artefato protegido truncado.")
            plain_size = _LEN.unpack(raw_len)[0]
            if plain_size <= 0 or plain_size > chunk_size:
                raise RuntimeError("Bloco protegido inválido.")
            cipher = fh.read(plain_size + 16)
            if len(cipher) != plain_size + 16:
                raise RuntimeError("Bloco protegido truncado.")
            try:
                plain = aes.decrypt(iv, cipher, artifact_aad(logical_name, index, plain_size))
            except Exception as exc:
                raise RuntimeError("Falha de integridade no artefato protegido.") from exc
            total += len(plain)
            index += 1
            yield plain
        if total != total_expected or fh.read(1):
            raise RuntimeError("Tamanho do artefato protegido não confere.")


def decrypt_uploaded_chunks(record, destination: Path) -> Path:
    """Materializa plaintext somente para o período mínimo necessário ao motor Python."""

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    aes = AESGCM(bytes(record.aes_key))
    temp = destination.with_suffix(destination.suffix + ".decrypting")
    total = 0
    try:
        with temp.open("wb") as out:
            for index in range(record.total_chunks):
                chunk_path = record.encrypted_dir / f"{index:06d}.chunk"
                if not chunk_path.is_file():
                    raise RuntimeError("Upload incompleto. Selecione o arquivo novamente e repita a validação.")
                data = chunk_path.read_bytes()
                if len(data) < 12 + 16:
                    raise RuntimeError("Bloco criptografado incompleto.")
                iv, cipher = data[:12], data[12:]
                plain_size = record.expected_plain_size(index)
                if len(cipher) != plain_size + 16:
                    raise RuntimeError("Tamanho do bloco criptografado não confere.")
                try:
                    plain = aes.decrypt(iv, cipher, upload_aad(record.upload_id, index, plain_size))
                except Exception as exc:
                    raise RuntimeError("Falha de integridade ao descriptografar o arquivo enviado. Tente selecionar o arquivo novamente.") from exc
                out.write(plain)
                total += len(plain)
        if total != record.expected_size:
            raise RuntimeError("O tamanho do arquivo descriptografado não confere com o arquivo selecionado.")
        temp.replace(destination)
        return destination
    finally:
        temp.unlink(missing_ok=True)


def validate_office_container(
    path: Path,
    extension: str,
    *,
    max_file_bytes: int,
    max_expanded_bytes: int,
    max_zip_entries: int = 100_000,
) -> None:
    path = Path(path)
    size = path.stat().st_size
    if size <= 0:
        raise RuntimeError("O arquivo enviado está vazio.")
    if size > max_file_bytes:
        raise RuntimeError("O arquivo excede o limite de tamanho permitido.")

    with path.open("rb") as fh:
        magic = fh.read(8)

    ext = extension.lower()
    if ext == ".xls":
        if magic != OLE_MAGIC:
            raise RuntimeError("O conteúdo do arquivo .xls não corresponde a uma planilha Excel válida.")
        return

    if ext not in ZIP_OFFICE_EXTENSIONS:
        raise RuntimeError("Formato de planilha não suportado.")
    if not magic.startswith(ZIP_MAGIC) or not zipfile.is_zipfile(path):
        raise RuntimeError(f"O conteúdo do arquivo {ext} não corresponde a uma planilha Office válida.")

    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            if len(infos) > max_zip_entries:
                raise RuntimeError("A planilha possui uma quantidade anormal de componentes internos.")
            names = {item.filename for item in infos}
            if "[Content_Types].xml" not in names or not any(name.startswith("xl/") for name in names):
                raise RuntimeError("A estrutura interna do arquivo não corresponde a uma planilha Excel válida.")
            total_expanded = 0
            for item in infos:
                if item.flag_bits & 0x1:
                    raise RuntimeError("Planilhas Office protegidas por senha não são suportadas para análise automática.")
                name = item.filename.replace("\\", "/")
                if name.startswith("/") or "../" in f"/{name}":
                    raise RuntimeError("A planilha possui caminhos internos inválidos.")
                total_expanded += int(item.file_size or 0)
                if total_expanded > max_expanded_bytes:
                    raise RuntimeError("A planilha expande para um volume de dados acima do limite seguro de processamento.")
                compressed = int(item.compress_size or 0)
                if item.file_size > 256 * 1024 * 1024 and compressed > 0 and item.file_size / compressed > 1500:
                    raise RuntimeError("A planilha possui um componente com taxa de compactação anormal.")
    except zipfile.BadZipFile as exc:
        raise RuntimeError("A planilha Office está corrompida ou possui estrutura ZIP inválida.") from exc
