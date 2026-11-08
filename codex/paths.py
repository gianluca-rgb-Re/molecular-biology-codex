"""Caminhos do aplicativo (conteúdo empacotado vs. dados do usuário)."""
from __future__ import annotations
import os
import sys
from pathlib import Path

APP_NAME = "MolecularBiologyCodex"


def resource_root() -> Path:
    """Raiz dos recursos somente-leitura (código-fonte ou pasta do PyInstaller)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Pasta de dados do usuário (banco, logs, conteúdo adicional).

    Windows: %LOCALAPPDATA%\\MolecularBiologyCodex (sobrevive a atualizações do .exe).
    Para testes ou instalação portátil: variável de ambiente CODEX_DATA_DIR.
    """
    override = os.environ.get("CODEX_DATA_DIR")
    if override:
        p = Path(override)
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        p = Path(base) / APP_NAME
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        p = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def bundled_content_dir() -> Path:
    return resource_root() / "content"


def user_content_dir() -> Path:
    d = data_dir() / "content"
    for sub in ("articles", "references", "figures"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d
