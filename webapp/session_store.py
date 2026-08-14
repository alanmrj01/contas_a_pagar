from __future__ import annotations

import os
import re
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SESSION_RE = re.compile(r"^[a-f0-9]{32}$")


def data_root(project_root: Path) -> Path:
    raw = os.getenv("WEB_DATA_DIR", "").strip()
    root = Path(raw).expanduser() if raw else project_root / "runtime_data"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


@dataclass
class SessionState:
    validated: Any | None = None
    last_report_url: str = ""
    last_pdf_url: str = ""
    last_source_names: list[str] = field(default_factory=list)


class SessionStore:
    """Estado de sessão apenas para a orquestração web.

    A lógica financeira permanece nos módulos originais em app/services.
    Cada navegador recebe um id aleatório, impedindo mistura acidental de dados
    entre sessões na mesma instância do servidor.
    """

    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self.root = data_root(self.project_root)
        self.sessions_root = self.root / "sessions"
        self.reports_root = self.root / "reports"
        self.sessions_root.mkdir(parents=True, exist_ok=True)
        self.reports_root.mkdir(parents=True, exist_ok=True)
        self._states: dict[str, SessionState] = {}
        self._locks: dict[str, threading.RLock] = {}
        self._guard = threading.RLock()

    @staticmethod
    def valid_sid(value: str | None) -> bool:
        return bool(value and SESSION_RE.fullmatch(value))

    def state(self, sid: str) -> SessionState:
        with self._guard:
            return self._states.setdefault(sid, SessionState())

    def lock(self, sid: str) -> threading.RLock:
        with self._guard:
            return self._locks.setdefault(sid, threading.RLock())

    def session_dir(self, sid: str) -> Path:
        path = self.sessions_root / sid
        path.mkdir(parents=True, exist_ok=True)
        return path

    def upload_dir(self, sid: str) -> Path:
        path = self.session_dir(sid) / "uploads"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def custom_base_path(self, sid: str) -> Path:
        path = self.session_dir(sid) / "base"
        path.mkdir(parents=True, exist_ok=True)
        return path / "base_dados_ativa.xlsx"

    def export_base_path(self, sid: str) -> Path:
        path = self.session_dir(sid) / "exports"
        path.mkdir(parents=True, exist_ok=True)
        return path / "BASE_DADOS.xlsx"

    def report_dir(self, sid: str) -> Path:
        path = self.reports_root / sid / "current"
        return path

    def clear_uploads(self, sid: str) -> None:
        path = self.upload_dir(sid)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True, exist_ok=True)

    def clear_report(self, sid: str) -> None:
        path = self.report_dir(sid)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    def invalidate_validation(self, sid: str, *, preserve_last_outputs: bool = True) -> None:
        state = self.state(sid)
        state.validated = None
        state.last_source_names = []
        if not preserve_last_outputs:
            state.last_report_url = ""
            state.last_pdf_url = ""
