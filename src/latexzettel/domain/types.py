# src/latexzettel/domain/types.py
"""
Tipos y contratos del dominio (independientes del ORM y del CLI).

Propósito:
- Estandarizar nombres, formatos y estructuras que aparecen en múltiples capas:
  api/*, infra/*, util/*, cli/*.
- Mantener el "lenguaje ubicuo" del proyecto: formatos de render, extensiones,
  rutas relativas, etc.
- Evitar dependencias hacia Peewee/Click.

Contexto:
- manage.py opera con formatos 'pdf'/'html', extensiones 'tex'/'md', y convenciones
  de rutas (notes/, slipbox/, pdf/, html/). :contentReference[oaicite:0]{index=0}
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import (
    NewType,
    Optional,
    Protocol,
    Sequence,
    TypedDict,
    runtime_checkable,
)

from latexzettel.infra.orm import Note


# =============================================================================
# Tipos nominales (NewType) para claridad semántica
# =============================================================================

NoteName = NewType("NoteName", str)  # nombre lógico (sin extensión) e.g. "mi_nota"
ReferenceName = NewType("ReferenceName", str)  # e.g. "MiNota"
LabelName = NewType("LabelName", str)  # e.g. "sec:intro"
CitationKey = NewType("CitationKey", str)  # e.g. "Doe2023"

RenderFormatStr = NewType("RenderFormatStr", str)  # "pdf" | "html"
NoteExtension = NewType("NoteExtension", str)  # "tex" | "md"


# =============================================================================
# Enums
# =============================================================================


class RenderFormat(str, Enum):
    PDF = "pdf"
    HTML = "html"


class Extension(str, Enum):
    TEX = "tex"
    MD = "md"


# =============================================================================
# Estructuras de configuración mínimas (agnósticas a settings.py)
# =============================================================================


@dataclass(frozen=True)
class RendererSpec:
    """
    Especificación de un renderer externo:
    - command: ejecutable
    - options: flags/args
    """

    command: str
    options: tuple[str, ...]


class Renderers(TypedDict):
    """
    Mapa de formato -> RendererSpec.
    """

    pdf: RendererSpec
    html: RendererSpec


# =============================================================================
# Resultados/DTOs genéricos para operaciones comunes
# =============================================================================


@dataclass(frozen=True)
class FileChange:
    """
    Representa el estado de actualización de un archivo frente a un timestamp guardado.
    """

    path: Path
    changed: bool
    mtime: Optional[float] = None


@dataclass(frozen=True)
class RenderPlan:
    """
    Plan mínimo de renderizado usado por api/render.py (cuando lo implementes):
    - filename: nota (sin extensión)
    - format: pdf/html
    - run_biber: si se requiere biber
    """

    filename: str
    format: RenderFormat
    run_biber: bool = False


# =============================================================================
# Protocolos (interfaces) para modularidad
# =============================================================================


@runtime_checkable
class DbModule(Protocol):
    """
    Contrato mínimo esperado por infra/db.py (modularidad).
    Coincide con tu diseño: infra/db.py espera un módulo externo 'database'
    con modelos y create_all_tables(). :contentReference[oaicite:1]{index=1}
    """

    database: object

    class Note(Note):  # ORM model
        pass

    def create_all_tables(self) -> None: ...


@runtime_checkable
class FileFinder(Protocol):
    """
    Contrato para módulos estilo LatexZettel/files.py:
    - get_files(dir_name, extension="") -> list[Path]
    """

    def get_files(
        self, dir_name: str | Path, extension: str = ""
    ) -> Sequence[Path]: ...


# =============================================================================
# Utilidades de validación (opcionales, sin I/O)
# =============================================================================


def is_valid_render_format(value: str) -> bool:
    return value in {RenderFormat.PDF.value, RenderFormat.HTML.value}


def is_valid_extension(value: str) -> bool:
    return value in {Extension.TEX.value, Extension.MD.value}
