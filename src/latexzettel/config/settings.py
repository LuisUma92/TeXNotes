# src/latexzettel/config/settings.py
"""
Configuration for LatexZettel
Configuración ensamblada del proyecto LatexZettel.

Rol del módulo:
- Construir objetos de configuración a partir de defaults.
- Resolver rutas absolutas.
- Centralizar parámetros que dependen del entorno o del layout del proyecto.
- NO contiene lógica de negocio.
- NO hace I/O destructivo.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import platform

from latexzettel.config import defaults


# =============================================================================
# Rutas principales
# =============================================================================


@dataclass(frozen=True)
class NotesPaths:
    """
    Contenedor de rutas usadas por el sistema de notas.

    Todas las rutas son relativas a `root` y se resuelven con `.abs()`.
    """

    root: Path = defaults.DEFAULT_ROOT

    notes_dir: Path = defaults.NOTES_DIR
    slipbox_dir: Path = defaults.SLIPBOX_DIR
    md_dir: Path = defaults.MD_DIR

    documents_tex: Path = defaults.DOCUMENTS_TEX

    template_dir: Path = defaults.TEMPLATE_DIR
    projects_dir: Path = defaults.PROJECTS_DIR
    draft_dir: Path = defaults.DRAFT_DIR

    pdf_dir: Path = defaults.PDF_DIR
    html_dir: Path = defaults.HTML_DIR

    def abs(self, path: Path) -> Path:
        """
        Resuelve una ruta relativa al root del proyecto.
        """
        return (self.root / path).resolve()


# =============================================================================
# Renderizado
# =============================================================================


@dataclass(frozen=True)
class RenderCommand:
    """
    Define un comando externo de renderizado y sus opciones.
    """

    command: str
    options: list[str]


@dataclass(frozen=True)
class RenderSettings:
    """
    Configuración completa de renderizado.
    """

    default_format: str
    supported_formats: tuple[str, ...]
    renderers: dict[str, RenderCommand]


def build_render_settings() -> RenderSettings:
    """
    Construye la configuración de renderizado a partir de defaults.
    """
    renderers = {
        "pdf": RenderCommand(
            command=defaults.DEFAULT_LATEX_ENGINE,
            options=list(defaults.PDFLATEX_OPTIONS),
        ),
        "html": RenderCommand(
            command=defaults.DEFAULT_HTML_ENGINE,
            options=list(defaults.MAKE4HT_OPTIONS),
        ),
    }

    return RenderSettings(
        default_format=defaults.DEFAULT_RENDER_FORMAT,
        supported_formats=defaults.SUPPORTED_RENDER_FORMATS,
        renderers=renderers,
    )


# =============================================================================
# Pandoc
# =============================================================================


@dataclass(frozen=True)
class PandocSettings:
    command: str
    latex_options: list[str]
    markdown_format: str


def build_pandoc_settings() -> PandocSettings:
    return PandocSettings(
        command=defaults.PANDOC_COMMAND,
        latex_options=list(defaults.PANDOC_LATEX_OPTIONS),
        markdown_format=defaults.PANDOC_MARKDOWN_FORMAT,
    )


# =============================================================================
# Base de datos
# =============================================================================


@dataclass(frozen=True)
class DatabaseSettings:
    """
    Configuración de base de datos.
    """

    filename: str


def build_database_settings() -> DatabaseSettings:
    return DatabaseSettings(filename=defaults.DEFAULT_DB_FILENAME)


# =============================================================================
# Comportamiento / UX
# =============================================================================


@dataclass(frozen=True)
class BehaviorSettings:
    """
    Flags de comportamiento por defecto.
    """

    auto_create_documents_tex: bool
    auto_create_directories: bool
    confirm_destructive_actions: bool


def build_behavior_settings() -> BehaviorSettings:
    return BehaviorSettings(
        auto_create_documents_tex=defaults.AUTO_CREATE_DOCUMENTS_TEX,
        auto_create_directories=defaults.AUTO_CREATE_DIRECTORIES,
        confirm_destructive_actions=defaults.CONFIRM_DESTRUCTIVE_ACTIONS,
    )


# =============================================================================
# Plataforma
# =============================================================================


@dataclass(frozen=True)
class PlatformSettings:
    """
    Configuración dependiente del sistema operativo.
    """

    system: str
    open_command: str


def build_platform_settings() -> PlatformSettings:
    system = platform.system()

    if system == "Darwin":
        open_cmd = "open"
    elif system == "Windows":
        open_cmd = "start"
    else:
        open_cmd = "xdg-open"

    return PlatformSettings(
        system=system,
        open_command=open_cmd,
    )


# =============================================================================
# Ensamblado global
# =============================================================================


@dataclass(frozen=True)
class Settings:
    """
    Configuración global del proyecto.
    """

    paths: NotesPaths
    render: RenderSettings
    pandoc: PandocSettings
    database: DatabaseSettings
    behavior: BehaviorSettings
    platform: PlatformSettings


def build_settings(root: Path | None = None) -> Settings:
    """
    Punto único de construcción de configuración.

    - Permite inyectar un root distinto (tests, sandbox, etc.).
    - El resto se deriva de defaults.
    """
    paths = NotesPaths(root=root if root is not None else defaults.DEFAULT_ROOT)

    return Settings(
        paths=paths,
        render=build_render_settings(),
        pandoc=build_pandoc_settings(),
        database=build_database_settings(),
        behavior=build_behavior_settings(),
        platform=build_platform_settings(),
    )


# =============================================================================
# Configuración por defecto (uso directo)
# =============================================================================

DEFAULT_SETTINGS: Settings = build_settings()
