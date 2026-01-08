# src/latexzettel/api/notes.py
"""
Creation, renaming and deletion of notes
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import shutil
from typing import Optional

import peewee as pw

from latexzettel.config.settings import NotesPaths
from latexzettel.domain.errors import (
    NoteAlreadyExists,
    ReferenceAlreadyExists,
    DocumentsTexNotFound,
    NoteNotFound,
)
from latexzettel.util.text import (
    default_reference_name,
    default_filename,
)
from latexzettel.util.fs import (
    create_note_file,
    append_documents_entry,
)


def create_note(
    *,
    db,
    note_name: str,
    reference_name: Optional[str] = None,
    extension: str = "tex",
    paths: NotesPaths = NotesPaths(),
    now: Optional[datetime] = None,
) -> None:
    """
    Makes a new note with name note_name [Optional ReferenceName]
    - Unique file name and reference on DB
    - If don't exist, create a template copy
    - Appends entry to notes/documents.tex
    - Creates new DB entry
    """
    if not note_name:
        raise ValueError("Empty note_name")

    # Formatting
    note_name = default_filename(note_name)
    if not reference_name:
        reference_name = default_reference_name(note_name)

    if now is None:
        now = datetime.now()

    try:
        db.Note.get(db.Note.filename == note_name)
        msn = f"A note with file name {note_name} already exists in the database.\n"
        msn += "If this is not the case then run\n"
        msn += "\tmanage.py synchronize\n"
        msn += "to update the database, and then try again"
        raise NoteAlreadyExists(msn)
    except pw.OperationalError:
        db.create_all_tables()
    except db.Note.DoesNotExist:
        pass

    # Unicidad por reference
    try:
        db.Note.get(db.Note.reference == reference_name)
        msn = f"A note with reference {reference} already exists in the database.\n"
        msn += "If this is not the case then run\n"
        msn += "\tmanage.py synchronize\n"
        msn += "to update the database, and then try again.\n"
        msn += "If the problem persists check the documents.tex file is correctly setup"
        raise ReferenceAlreadyExists(msn)
    except db.Note.DoesNotExist:
        pass

    create_note_file(paths, filename=note_name, extension=extension)
    append_documents_entry(paths, filename=note_name, reference=reference_name)

    db.Note.create(
        filename=note_name,
        reference=reference_name,
        created=now,
        last_edit_date=now,
    )


def create_note_md(
    *,
    db,
    note_name: str,
    reference_name: Optional[str] = None,
    paths: NotesPaths = NotesPaths(),
) -> None:
    """
    Creates a new markdown note with the given title.
    Otherwise, same functionality as create_note()
    """
    create_note(
        db=db,
        note_name=note_name,
        reference_name=reference_name,
        extension="md",
        paths=paths,
    )


def rename_note_file(
    *,
    db,
    old_filename: str,
    new_filename: str,
    paths: NotesPaths = NotesPaths(),
) -> None:
    """
    Rename the .tex file
    - notes/slipbox/(<old>.tex -> <new>.tex)
    - updates documents.tex and DB.
    """
    try:
        note = db.Note.get(db.Note.filename == old_filename)
    except db.Note.DoesNotExist:
        raise NoteNotFound(f"No filename='{old_filename}' register found.")

    slipbox = paths.abs(paths.slipbox_dir)
    src = slipbox / f"{old_filename}.tex"
    dst = slipbox / f"{new_filename}.tex"

    if dst.exists():
        raise NoteAlreadyExists(f"File, {dst} already exists")

    if not src.exists():
        raise NoteNotFound(f"Source file not found: {src}")

    shutil.copyfile(src, dst)
    src.unlink()

    note.filename = new_filename
    note.save()

    doc = paths.abs(paths.documents_tex)
    if not doc.exists():
        raise DocumentsTexNotFound(f"Document not found: {doc}")

    pattern = rf"\\externaldocument\[{re.escape(note.reference)}-\]\{{{re.escape(old_filename)}\}}"
    repl = rf"\\externaldocument[{note.reference}-]{{{new_filename}}}"

    doc.write_text(
        re.sub(pattern, repl, doc.read_text(encoding="utf-8")), encoding="utf-8"
    )


def rename_reference(
    *,
    db,
    old_reference: str,
    new_reference: str,
    paths: NotesPaths = NotesPaths(),
) -> None:
    """
    Rename the reference:
    - throughout the whole Zettelkasten.
    - changes documents.tex
    - any documents that reference this note.
    - updates DB
    """
    try:
        note = db.Note.get(db.Note.reference == old_reference)
    except db.Note.DoesNotExist:
        raise NoteNotFound(f"No reference='{old_reference}' register found.")

    try:
        db.Note.get(db.Note.reference == new_reference)
        raise ReferenceAlreadyExists(f"Note reference='{new_reference}' already exists")
    except db.Note.DoesNotExist:
        pass

    doc = paths.abs(paths.documents_tex)
    if not doc.exists():
        raise DocumentsTexNotFound(f"Document not found: {doc}")

    pattern = rf"\\externaldocument\[{re.escape(old_reference)}-\]\{{{re.escape(note.filename)}\}}"
    repl = rf"\\externaldocument[{new_reference}-]{{{note.filename}}}"
    doc.write_text(
        re.sub(pattern, repl, doc.read_text(encoding="utf-8")), encoding="utf-8"
    )

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
        # Por compatibilidad con tu base actual, todo lo no-hyper lo dejamos como \excref
        return (
            rf"\excref[{opt}]{{{new_reference}}}"
            if opt
            else rf"\excref{{{new_reference}}}"
        )

    # Actualiza archivos que referencian la nota (según tu esquema: Label.referenced_by -> Link.source)
    for label in note.labels:
        for backref in label.referenced_by:
            f = slipbox / f"{backref.source.filename}.tex"
            if not f.exists():
                continue
            f.write_text(rx.sub(_repl, f.read_text(encoding="utf-8")), encoding="utf-8")

    note.reference = new_reference
    note.save()


def remove_note(
    *,
    db,
    filename: str,
    paths: NotesPaths = NotesPaths(),
):
    """
    Delete a note with given filename
    """
    try:
        note = db.Note.get(filename=filename)
        note.delete_instance()
    except db.Note.DoesNotExist:
        note = None

    with open("notes/documents.tex", "r") as f:
        lines = f.readlines()

    to_delete = []
    for i, line in enumerate(lines):
        m = re.search(rf"(\\externaldocument\[)(.+?)(\-\]\{{){filename}(\}})", line)
        if m:
            to_delete.append(i)

    for i in reversed(to_delete):
        print(f"delete line {lines[i].strip()} from notes/documents.tex? (y/n)")
        if Helper.__getyesno():
            lines.pop(i)

    with open("notes/documents.tex", "w") as f:
        for line in lines:
            f.write(line)

    doc = paths.abs(paths.documents_tex)

    slipbox = paths.abs(paths.slipbox_dir)
    src = slipbox / f"{filename}.tex"

    if src.exists():
        src.unlink()
