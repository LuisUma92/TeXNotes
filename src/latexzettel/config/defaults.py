# src/latexzettel/config/defaults.py
"""
Valores por defecto del proyecto LatexZettel.

Este módulo define **constantes y valores canónicos** que:
- No dependen del entorno (FS, DB, CLI).
- No contienen lógica.
- Son importados por `config/settings.py`, `api/*`, `cli/*`.

Principio:
    defaults.py  -> QUÉ valores se usan por defecto
    settings.py  -> CÓMO se ensamblan/configuran esos valores
"""

from __future__ import annotations

from pathlib import Path
from typing import Final


# ---------------------------------------------------------------------------
# Rutas por defecto (relativas al root del proyecto)
# ---------------------------------------------------------------------------

DEFAULT_ROOT: Final[Path] = Path(".")

NOTES_DIR: Final[Path] = Path("notes")
SLIPBOX_DIR: Final[Path] = Path("notes/slipbox")
MD_DIR: Final[Path] = Path("notes/md")
DOCUMENTS_TEX: Final[Path] = Path("notes/documents.tex")

TEMPLATE_DIR: Final[Path] = Path("template")
PROJECTS_DIR: Final[Path] = Path("projects")
DRAFT_DIR: Final[Path] = Path("draft")

PDF_DIR: Final[Path] = Path("pdf")
HTML_DIR: Final[Path] = Path("html")


# ---------------------------------------------------------------------------
# Plantillas
# ---------------------------------------------------------------------------

NOTE_TEMPLATE_TEX: Final[str] = "note.tex"
NOTE_TEMPLATE_MD: Final[str] = "note.md"
PROJECT_TEMPLATE_TEX: Final[str] = "project.tex"


# ---------------------------------------------------------------------------
# Renderizado
# ---------------------------------------------------------------------------

DEFAULT_RENDER_FORMAT: Final[str] = "pdf"
SUPPORTED_RENDER_FORMATS: Final[tuple[str, ...]] = ("pdf", "html")

DEFAULT_LATEX_ENGINE: Final[str] = "pdflatex"
DEFAULT_HTML_ENGINE: Final[str] = "make4ht"

PDFLATEX_OPTIONS: Final[list[str]] = [
    "--interaction=scrollmode",
]

MAKE4HT_OPTIONS: Final[list[str]] = [
    "-um",
    "draft",
    "-c",
    "../config/make4ht.cfg",
    "-",
]


# ---------------------------------------------------------------------------
# Pandoc
# ---------------------------------------------------------------------------

PANDOC_COMMAND: Final[str] = "pandoc"

PANDOC_LATEX_OPTIONS: Final[list[str]] = [
    "-s",
    "-t",
    "latex",
    "--lua-filter=pandoc/filter.lua",
    "--template=pandoc/template.tex",
    "--metadata-file=pandoc/defaults.yaml",
    "--biblatex",
]

PANDOC_MARKDOWN_FORMAT: Final[str] = "markdown"


# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------

DEFAULT_DB_FILENAME: Final[str] = "slipbox.db"


# ---------------------------------------------------------------------------
# Convenciones de nombres
# ---------------------------------------------------------------------------

DEFAULT_NOTE_EXTENSION: Final[str] = "tex"
ALLOWED_NOTE_EXTENSIONS: Final[tuple[str, ...]] = ("tex", "md")

FILENAME_SEPARATOR: Final[str] = "_"


# ---------------------------------------------------------------------------
# Comportamiento por defecto (flags lógicos)
# ---------------------------------------------------------------------------

AUTO_CREATE_DOCUMENTS_TEX: Final[bool] = True
AUTO_CREATE_DIRECTORIES: Final[bool] = True

CONFIRM_DESTRUCTIVE_ACTIONS: Final[bool] = True


# ---------------------------------------------------------------------------
# Internacionalización / UX
# ---------------------------------------------------------------------------

DEFAULT_ENCODING: Final[str] = "utf-8"

YES_VALUES: Final[set[str]] = {"y", "yes"}
NO_VALUES: Final[set[str]] = {"n", "no"}


# ---------------------------------------------------------------------------
# Seguridad y límites
# ---------------------------------------------------------------------------

MAX_FILENAME_LENGTH: Final[int] = 255
MAX_REFERENCE_LENGTH: Final[int] = 128
