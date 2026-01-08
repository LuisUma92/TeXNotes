# src/latexzettel/infra/orm.py
"""
Definición del ORM (Peewee) y modelos persistentes.

Este archivo reemplaza al legacy LatexZettel/database.py, preservando:
- SQLite slipbox.db
- modelos: Note, Citation, Label, Link, Tag, NoteTag
- helpers: create_tables(), create_all_tables()

Basado en el esquema existente. :contentReference[oaicite:2]{index=2}
"""

from __future__ import annotations

from pathlib import Path
import peewee as pw

from latexzettel.config.settings import DEFAULT_SETTINGS


def _default_db_path() -> Path:
    # Mantiene compatibilidad con slipbox.db en root (como antes). :contentReference[oaicite:3]{index=3}
    return Path(DEFAULT_SETTINGS.database.filename)


# Base de datos (SQLite)
database = pw.SqliteDatabase(str(_default_db_path()), pragmas={"foreign_keys": 1})


class BaseModel(pw.Model):
    class Meta:
        database = database


class Note(BaseModel):
    # mismo esquema que legacy :contentReference[oaicite:4]{index=4}
    filename = pw.CharField(unique=True)
    reference = pw.CharField(unique=True)
    last_build_date_html = pw.DateTimeField(null=True)
    last_build_date_pdf = pw.DateTimeField(null=True)
    last_edit_date = pw.DateTimeField(null=True)
    created = pw.DateTimeField(null=True)


class Citation(BaseModel):
    """Model to keep track of which notes reference papers."""

    note = pw.ForeignKeyField(Note, on_delete="CASCADE", backref="citations")
    citationkey = pw.CharField()


class Label(BaseModel):
    note = pw.ForeignKeyField(Note, on_delete="CASCADE", backref="labels")
    label = pw.CharField()


class Link(BaseModel):
    """
    Model to keep track of links between files.
    source = note containing the reference
    target = label pointed to (note+label)
    """

    source = pw.ForeignKeyField(Note, on_delete="CASCADE", backref="references")
    target = pw.ForeignKeyField(Label, on_delete="CASCADE", backref="referenced_by")


class Tag(BaseModel):
    name = pw.CharField(unique=True)
    notes = pw.ManyToManyField(Note)


NoteTag = Tag.notes.get_through_model()


def create_tables(*models: type[pw.Model]) -> None:
    """
    Crea tablas; idempotente en práctica si se invoca vía infra/db.ensure_tables()
    (que solo llama si detecta que faltan tablas).
    """
    with database:
        database.create_tables(models)


def create_all_tables() -> None:
    create_tables(Note, Citation, Link, Label, Tag, NoteTag)
