from __future__ import annotations

import os
from pathlib import Path

from webapp.crypto_storage import iter_unseal_file, seal_file
from webapp.session_store import SessionStore

ROOT = Path(__file__).resolve().parents[1]


def test_artifact_encryption_roundtrip_and_integrity(tmp_path):
    plain = tmp_path / "plain.bin"
    sealed = tmp_path / "sealed.capenc"
    data = os.urandom(2_500_000)
    plain.write_bytes(data)
    key = os.urandom(32)
    seal_file(plain, sealed, key, "report/test.bin")
    assert sealed.read_bytes().startswith(b"CAPART01")
    assert b"plain" not in sealed.read_bytes()[:200]
    restored = b"".join(iter_unseal_file(sealed, key, "report/test.bin"))
    assert restored == data


def test_expired_session_is_destroyed_with_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_DATA_DIR", str(tmp_path / "data"))
    store = SessionStore(ROOT)
    _, sid, _ = store.create_session()
    state = store.state(sid)
    session_dir = store.session_dir(sid)
    (session_dir / "marker").write_text("sensitive")
    state.last_activity -= store.session_ttl_seconds + 1
    assert store.cleanup_expired() == 1
    assert not session_dir.exists()
    assert not store.has_session(sid)
