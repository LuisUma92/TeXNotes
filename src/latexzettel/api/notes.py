# src/latexzettel/api/notes.py
"""
Creation, renaming and deletion of notes
API de alto nivel para operaciones sobre notas (crear/renombrar/eliminar).

Estado actual (arquitectura):
- La DB se inyecta como "módulo externo" (modularidad), compatible con infra/db.py.
- Este módulo NO depende de Click y NO hace I/O interactivo (sin input/print).
- La inicialización del esquema NO se ejecuta “siempre”; se hace únicamente si
  detectamos que faltan tablas (OperationalError), replicando el patrón legacy.
"""

from __future__ import annotations

from datetime import datetime
import re
import shutil
from typing import Optional


from latexzettel.config.settings import NotesPaths, DEFAULT_SETTINGS
from latexzettel.domain.errors import (
    NoteAlreadyExists,
    ReferenceAlreadyExists,
    NoteNotFound,
)
from latexzettel.domain.types import DbModule
from latexzettel.infra.db import ensure_schema_if_needed
from latexzettel.util.text import (
    default_reference_name,
    default_filename,
)
from latexzettel.util.fs import (
    create_note_file,
    append_documents_entry,
    ensure_documents_tex,
)


def create_note(
    *,
    db: DbModule,
    note_name: str,
    reference_name: Optional[str] = None,
    extension: str = "tex",
    paths: NotesPaths = DEFAULT_SETTINGS.paths,
    now: Optional[datetime] = None,
    add_to_documents: bool = True,
    create_file: bool = True,
) -> None:
    """
    Crea una nota:
    - valida unicidad de filename y reference en DB
    - crea archivo desde plantilla (opcional)
    - agrega entrada a notes/documents.tex (opcional)
    - crea registro Note en DB

    db: módulo externo Peewee con:
      - database
      - modelos (Note, ...)
      - create_all_tables() (usado indirectamente por infra/db.ensure_tables)
    """
    if not note_name:
        raise ValueError("note_name vacío")
    note_name = default_filename(note_name)

    if not reference_name:
        reference_name = default_reference_name(note_name)

    ts = now or datetime.now()

    ensure_schema_if_needed(db)

    # Unicidad por filename
    try:
        db.Note.get(db.Note.filename == note_name)
        raise NoteAlreadyExists(f"Ya existe note filename='{note_name}'")
    except db.Note.DoesNotExist:
        pass

    # Unicidad por reference
    try:
        db.Note.get(db.Note.reference == reference_name)
        raise ReferenceAlreadyExists(f"Ya existe note reference='{reference_name}'")
    except db.Note.DoesNotExist:
        pass

    if create_file:
        create_note_file(paths, filename=note_name, extension=extension)

    if add_to_documents:
        append_documents_entry(paths, filename=note_name, reference=reference_name)

    db.Note.create(
        filename=note_name,
        reference=reference_name,
        created=ts,
        last_edit_date=ts,
    )


def create_note_md(
    *,
    db: DbModule,
    note_name: str,
    reference_name: Optional[str] = None,
    paths: NotesPaths = DEFAULT_SETTINGS.paths,
    now: Optional[datetime] = None,
) -> None:
    """
    Crea una nota markdown, equivalente a Helper.newnote_md().
    """
    create_note(
        db=db,
        note_name=note_name,
        reference_name=reference_name,
        extension="md",
        paths=paths,
        now=now,
    )


def rename_note_file(
    *,
    db: DbModule,
    old_filename: str,
    new_filename: str,
    paths: NotesPaths = DEFAULT_SETTINGS.paths,
) -> None:
    """
    Renombra notes/slipbox/<old>.tex -> <new>.tex y actualiza:
    - DB Note.filename
    - notes/documents.tex

    Replica la semántica esencial de Helper.rename_file().
    """
    if not old_filename or not new_filename:
        raise ValueError("old_filename y new_filename son obligatorios")

    ensure_schema_if_needed(db)

    try:
        note = db.Note.get(db.Note.filename == old_filename)
    except db.Note.DoesNotExist as e:
        raise NoteNotFound(f"No existe nota filename='{old_filename}'") from e

    slipbox = paths.abs(paths.slipbox_dir)
    src = slipbox / f"{old_filename}.tex"
    dst = slipbox / f"{new_filename}.tex"

    if dst.exists():
        raise NoteAlreadyExists(f"El archivo ya existe: {dst}")

    if not src.exists():
        raise NoteNotFound(f"No existe el archivo fuente: {src}")

    shutil.copyfile(src, dst)
    src.unlink()

    note.filename = new_filename
    note.save()

    doc = ensure_documents_tex(paths, create=False)
    text = doc.read_text(encoding="utf-8")

    pattern = rf"\\externaldocument\[{re.escape(note.reference)}\-\]\{{{re.escape(old_filename)}\}}"
    repl = rf"\\externaldocument[{note.reference}-]{{{new_filename}}}"

    doc.write_text(re.sub(pattern, repl, text), encoding="utf-8")


def rename_reference(
    *,
    db: DbModule,
    old_reference: str,
    new_reference: str,
    paths: NotesPaths = DEFAULT_SETTINGS.paths,
    update_backrefs: bool = True,
) -> None:
    """
    Renombra la reference:
    - actualiza notes/documents.tex
    - actualiza referencias en notas que apuntan a esa reference (opcional)
    - actualiza DB Note.reference

    Replica la intención de Helper.rename_reference().
    """
    if not old_reference or not new_reference:
        raise ValueError("old_reference y new_reference son obligatorios")

    ensure_schema_if_needed(db)

    try:
        note = db.Note.get(db.Note.reference == old_reference)
    except db.Note.DoesNotExist as e:
        raise NoteNotFound(f"No existe nota reference='{old_reference}'") from e

    # colisión
    try:
        db.Note.get(db.Note.reference == new_reference)
        raise ReferenceAlreadyExists(f"Ya existe note reference='{new_reference}'")
    except db.Note.DoesNotExist:
        pass

    # documents.tex
    doc = ensure_documents_tex(paths, create=False)
    text = doc.read_text(encoding="utf-8")

    pattern = rf"\\externaldocument\[{re.escape(old_reference)}\-\]\{{{re.escape(note.filename)}\}}"
    repl = rf"\\externaldocument[{new_reference}-]{{{note.filename}}}"
    doc.write_text(re.sub(pattern, repl, text), encoding="utf-8")

    if update_backrefs:
        slipbox = paths.abs(paths.slipbox_dir)

        # \ex(hyper)?(c)?ref([label])?{OldReference}
        rx = re.compile(
            rf"\\ex(hyper)?(c)?ref(\[([^]]+)\])?\{{{re.escape(old_reference)}\}}"
        )

        def _repl(m: re.Match) -> str:
            opt = m.group(4)
            is_hyper = m.group(1) is not None
            if is_hyper:
                return (
                    rf"\exhyperref[{opt}]{{{new_reference}}}"
                    if opt
                    else rf"\exhyperref{{{new_reference}}}"
                )
            return (
                rf"\excref[{opt}]{{{new_reference}}}"
                if opt
                else rf"\excref{{{new_reference}}}"
            )

        # El legacy obtiene backrefs vía labels->referenced_by->source.filename
        backref_files: set[str] = set()
        for lbl in note.labels:
            for backref in lbl.referenced_by:
                backref_files.add(backref.source.filename)

        for fname in backref_files:
            fpath = slipbox / f"{fname}.tex"
            if not fpath.exists():
                continue
            content = fpath.read_text(encoding="utf-8")
            updated = rx.sub(_repl, content)
            if updated != content:
                fpath.write_text(updated, encoding="utf-8")

    note.reference = new_reference
    note.save()


def remove_note(
    *,
    db: DbModule,
    filename: str,
    paths: NotesPaths = DEFAULT_SETTINGS.paths,
    delete_db_entry: bool = True,
    delete_documents_entry: bool = True,
    delete_file: bool = False,
) -> None:
    """
    Elimina una nota (determinístico, sin prompts):
    - delete_db_entry: borra Note y cascadas
    - delete_documents_entry: elimina la línea en documents.tex
    - delete_file: elimina notes/slipbox/<filename>.tex

    El legacy era interactivo; aquí se controla por flags.
    """
    if not filename:
        raise ValueError("filename vacío")

    ensure_schema_if_needed(db)

    note = None
    try:
        note = db.Note.get(db.Note.filename == filename)
    except db.Note.DoesNotExist:
        note = None

    if delete_db_entry and note is not None:
        note.delete_instance()

    if delete_documents_entry:
        doc = ensure_documents_tex(paths, create=False)
        lines = doc.read_text(encoding="utf-8").splitlines(True)
        rx = re.compile(rf"\\externaldocument\[(.+?)\-\]\{{{re.escape(filename)}\}}")
        doc.write_text(
            "".join(ln for ln in lines if not rx.search(ln)), encoding="utf-8"
        )

    if delete_file:
        fpath = paths.abs(paths.slipbox_dir / f"{filename}.tex")
        if fpath.exists():
            fpath.unlink()
        else:
            raise NoteNotFound(f"No existe el archivo: {fpath}")
