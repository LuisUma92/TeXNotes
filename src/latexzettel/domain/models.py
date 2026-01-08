# src/latexzettel/domain/models.py
"""
Modelos del dominio (independientes del ORM).

Estos tipos son los que debería exponer el API hacia arriba (CLI, tests, etc.)
sin filtrar Peewee.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class RenderFormat(str, Enum):
    PDF = "pdf"
    HTML = "html"


@dataclass(frozen=True)
class NoteId:
    filename: str
    reference: str


@dataclass(frozen=True)
class NoteInfo:
    filename: str
    reference: str
    created: Optional[datetime] = None
    last_edit_date: Optional[datetime] = None
    last_build_date_pdf: Optional[datetime] = None
    last_build_date_html: Optional[datetime] = None


@dataclass(frozen=True)
class LabelInfo:
    note_reference: str
    label: str


@dataclass(frozen=True)
class LinkInfo:
    source_filename: str
    target_reference: str
    target_label: str


@dataclass(frozen=True)
class CitationInfo:
    note_filename: str
    citationkey: str
