# src/latexzettel/infra/platform.py
"""
Capa de infraestructura para decisiones dependientes de plataforma.

Este módulo encapsula la lógica que en manage.py se resolvía con:

    OPEN_COMMAND = "xdg-open"
    if platform.system() == "Darwin": OPEN_COMMAND = "open"
    elif platform.system() == "Windows": OPEN_COMMAND = "start"

:contentReference[oaicite:0]{index=0}

Reglas:
- No depende de Click.
- No hace I/O por sí mismo.
- Se usa desde config/settings.py (build_platform_settings) o desde cli/*.
"""

from __future__ import annotations

from dataclasses import dataclass
import platform as _platform


@dataclass(frozen=True)
class PlatformInfo:
    """
    Información relevante de plataforma para el proyecto.
    """

    system: str
    open_command: str


def detect_system() -> str:
    """
    Retorna el identificador de sistema usado por Python (platform.system()).
    """
    return _platform.system()


def default_open_command(system: str | None = None) -> str:
    """
    Devuelve el comando por defecto para abrir archivos según el sistema.

    - Linux/otros: xdg-open
    - macOS (Darwin): open
    - Windows: start

    Replica la semántica de manage.py. :contentReference[oaicite:1]{index=1}
    """
    if system is None:
        system = detect_system()

    if system == "Darwin":
        return "open"
    if system == "Windows":
        return "start"
    return "xdg-open"


def get_platform_info() -> PlatformInfo:
    """
    Construye PlatformInfo con el comando de apertura adecuado.
    """
    sysname = detect_system()
    return PlatformInfo(system=sysname, open_command=default_open_command(sysname))
