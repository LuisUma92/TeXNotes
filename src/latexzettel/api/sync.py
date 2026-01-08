# src/latexzettel/api/sync.py
"""
API de sincronización de la base de datos con el filesystem.

Este módulo refactoriza principalmente:
- Helper.synchronize()
- Helper.force_synchronize()
- (parcialmente) Helper.sync_md() en lo que respecta a asegurar notas/DB y
  coordinar actualizaciones

del manage.py legacy. :contentReference[oaicite:0]{index=0}

Diseño:
- NO usa Click (sin prints/input), salvo que tú decidas inyectar confirmaciones
  desde cli/* usando util/io.py.
- Opera sobre un módulo DB externo (modularidad) compatible con infra/db.py.
- Usa infra/regexes.py para patrones consistentes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from latexzettel.config.settings import NotesPaths, DEFAULT_SETTINGS
from latexzettel.domain.errors import (
    DomainError,
    NoteNotFound,
    DocumentsTexNotFound,
)
from latexzettel.domain.templates import min_tex_file
from latexzettel.domain.types import DbModule
from latexzettel.infra.db import ensure_tables
from latexzettel.infra.regexes import (
    EXTERNALDOCUMENT_RE,
    LABEL_OR_CURRENTDOC_RE,
    CITATION_RE,
    EX_REF_RE,
)
from latexzettel.infra import fs as ifs
from latexzettel.util.time import (
    file_mtime,
    needs_update,
    now,
)


# =============================================================================
# Resultados
# =============================================================================


@dataclass(frozen=True)
class SyncResult:
    """
    Resultado de una sincronización incremental.

    updated_notes:
      lista de instancias Note (peewee) cuyo contenido fue releído y procesado
      (labels/citations/links).
    new_or_modified_links:
      lista de instancias Link (peewee) creadas o eliminadas durante la sync.
    run_biber:
      dict {note_instance: bool} para indicar si la nota requiere biber
      (por cambios en citas), replicando manage.py. :contentReference[oaicite:1]{index=1}
    """

    updated_notes: list
    new_or_modified_links: list
    run_biber: dict


@dataclass(frozen=True)
class ForceSyncResult:
    """
    Resultado de una sincronización completa (force).
    """

    tracked_notes: dict[str, str]  # filename -> reference
    added_notes: list
    updated_notes: list


# =============================================================================
# Helpers internos
# =============================================================================


def _note_tex_path(paths: NotesPaths, filename: str) -> Path:
    return paths.abs(paths.slipbox_dir / f"{filename}.tex")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _get_labels_from_file(note_file: Path) -> list[str]:
    labels: list[str] = []
    with note_file.open("r", encoding="utf-8") as f:
        for line in f:
            m = LABEL_OR_CURRENTDOC_RE.search(line)
            if m:
                labels.append(m.group(3))
    return labels


def _get_citation_keys_from_file(note_file: Path) -> set[str]:
    keys: set[str] = set()
    with note_file.open("r", encoding="utf-8") as f:
        for line in f:
            for m in CITATION_RE.finditer(line):
                keys.add(m.group(7))
    return keys


def _get_links_from_file(note_file: Path) -> list[tuple[str, str]]:
    """
    Retorna lista de (reference, label) apuntados por la nota.

    En manage.py, si no hay [label] se usa 'note'. :contentReference[oaicite:2]{index=2}
    """
    out: list[tuple[str, str]] = []
    with note_file.open("r", encoding="utf-8") as f:
        for line in f:
            for m in EX_REF_RE.finditer(line):
                ref = m.group(5)  # {Ref}
                label = m.group(4) if m.group(4) is not None else "note"
                out.append((ref, label))
    return out


def _sync_note_labels(db: DbModule, note, note_file: Path) -> None:
    file_labels = _get_labels_from_file(note_file)
    tracked_labels = [lbl.label for lbl in note.labels]

    for lbl in file_labels:
        if lbl not in tracked_labels:
            db.Label.create(label=lbl, note=note)

    # remover labels que ya no existen
    for lbl in list(note.labels):
        if lbl.label not in file_labels:
            lbl.delete_instance()


def _sync_note_citations(db: DbModule, note, note_file: Path) -> bool:
    """
    Sincroniza tabla Citation para la nota.
    Retorna True si hubo cambios (para decidir biber), como manage.py. :contentReference[oaicite:3]{index=3}
    """
    keys = _get_citation_keys_from_file(note_file)
    tracked = [c for c in note.citations]
    tracked_keys = [c.citationkey for c in tracked]

    changed = False

    for key in keys:
        if key not in tracked_keys:
            db.Citation.create(note=note, citationkey=key)
            changed = True

    for c in tracked:
        if c.citationkey not in keys:
            c.delete_instance()
            changed = True

    return changed


def _sync_note_links(db: DbModule, note, note_file: Path) -> list:
    """
    Sincroniza tabla Link para la nota.
    Retorna lista de instancias Link modificadas (creadas/eliminadas),
    como manage.py. :contentReference[oaicite:4]{index=4}
    """
    links = _get_links_from_file(note_file)
    modified: list = []

    tracked = [(lnk.target.note.reference, lnk.target.label) for lnk in note.references]

    # Crear links nuevos
    for link in links:
        if link in tracked:
            continue
        try:
            label = db.Label.get(
                db.Label.note.reference == link[0], db.Label.label == link[1]
            )
            lnk = db.Link.create(target=label, source=note)
            modified.append(lnk)
        except db.Label.DoesNotExist:
            # No existe el label target; en legacy se imprimía un warning.
            # Aquí lo omitimos silenciosamente. El CLI puede reportarlo si deseas.
            continue

    # Eliminar links que ya no existen en el archivo
    for lnk in list(note.references):
        if (lnk.target.note.reference, lnk.target.label) not in links:
            lnk.delete_instance()
            modified.append(lnk)

    return modified


def _update_note_from_file(db: DbModule, note, paths: NotesPaths) -> tuple[bool, list]:
    """
    Relee el archivo de la nota y actualiza labels/citations/links.

    Retorna:
      - run_biber: bool (si cambiaron citas)
      - modified_links: list[Link]
    """
    note_file = _note_tex_path(paths, note.filename)
    if not note_file.exists():
        # en legacy se imprimía; aquí lo elevamos como error leve
        raise NoteNotFound(
            f"Archivo no encontrado para note '{note.filename}': {note_file}"
        )

    _sync_note_labels(db, note, note_file)
    run_biber = _sync_note_citations(db, note, note_file)
    modified_links = _sync_note_links(db, note, note_file)
    return run_biber, modified_links


# =============================================================================
# API pública: synchronize()
# =============================================================================


def synchronize(
    *,
    db: DbModule,
    paths: NotesPaths = DEFAULT_SETTINGS.paths,
) -> SyncResult:
    """
    Sincronización incremental:
    - detecta notas editadas desde el último sync (mtime > note.last_edit_date)
    - last_edit_date
    - reparsea labels/citations/links solo para las notas modificadas

    Retorna estructuras equivalentes a manage.py:
      (to_read, new_links, run_biber) :contentReference[oaicite:5]{index=5}
    """
    health = ensure_tables(db)
    if not health.ok:
        raise DomainError(f"DB no disponible: {health.error}")

    to_read: list = []

    # detectar notas modificadas
    for note in db.Note:
        try:
            fpath = _note_tex_path(paths, note.filename)

            if needs_update(
                file_path=fpath,
                last_edit_date=note.last_edit_date,
            ):
                to_read.append(note)
                note.last_edit_date = file_mtime(fpath)
                note.save()
        except FileNotFoundError:
            # legacy imprimía un warning; aquí omitimos (force_synchronize lo arregla)
            continue

    run_biber: dict = {}
    new_links: list = []

    for note in to_read:
        rb, modified_links = _update_note_from_file(db, note, paths)
        run_biber[note] = rb
        new_links.extend(modified_links)

    return SyncResult(
        updated_notes=to_read, new_or_modified_links=new_links, run_biber=run_biber
    )


# =============================================================================
# API pública: force_synchronize()
# =============================================================================


def force_synchronize(
    *,
    db: DbModule,
    paths: NotesPaths = DEFAULT_SETTINGS.paths,
    create_missing_note_files: bool = False,
    create_documents_tex_if_missing: bool = True,
    timestamp: Optional[datetime] = None,
) -> ForceSyncResult:
    """
    Sincronización completa (force), inspirada en Helper.force_synchronize(). :contentReference[oaicite:6]{index=6}

    Diferencias vs legacy:
    - No hace prompts interactivos.
    - Los comportamientos interactivos (crear archivos faltantes, agregar a documents.tex)
      se controlan con flags.
    - No imprime.

    Flujo:
    1) Lee notes/documents.tex y determina tracked_notes (filename->reference)
    2) Valida que cada filename exista en slipbox; opcionalmente crea archivos faltantes
    3) Sincroniza/crea entradas Note en DB (filename/reference/timestamps build si existen)
    4) Busca notas .tex en slipbox no listadas en documents.tex:
       - (opcional) agrega a documents.tex (aquí NO lo hacemos automáticamente; esa política
         queda para el CLI y/o api/notes.py)
    5) Reparsea labels/citations/links para todas las notas

    Retorna un resumen de cambios.
    """
    ts = timestamp or now()

    health = ensure_tables(db)
    if not health.ok:
        raise DomainError(f"DB no disponible: {health.error}")

    # documents.tex
    doc_path = paths.abs(paths.documents_tex)
    if not doc_path.exists():
        if create_documents_tex_if_missing:
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            doc_path.write_text("", encoding="utf-8")
        else:
            raise DocumentsTexNotFound(f"No existe: {doc_path}")

    # 1) Parse tracked_notes desde documents.tex
    tracked_notes: dict[str, str] = {}
    for line in doc_path.read_text(encoding="utf-8").splitlines():
        m = EXTERNALDOCUMENT_RE.search(line)
        if m:
            reference_name = m.group(2)
            filename = m.group(4)
            tracked_notes[filename] = reference_name

    # 2) Lista de notas físicas en slipbox
    slipbox_files = ifs.rglob_files(paths.abs(paths.slipbox_dir), suffix=".tex")
    slipbox_names = {p.stem for p in slipbox_files}

    # 3) Asegurar que tracked_notes existan como archivos
    for filename in list(tracked_notes.keys()):
        if filename not in slipbox_names:
            if create_missing_note_files:
                # crea un archivo mínimo: delega a util/fs o api/notes; aquí hacemos mínimo
                f = _note_tex_path(paths, filename)
                f.parent.mkdir(parents=True, exist_ok=True)
                min_tex_file(f)
                slipbox_names.add(filename)
            else:
                # si no creamos, simplemente seguimos; DB puede seguir reflejando docs
                continue

    added_notes: list = []
    updated_notes: list = []

    # 4) Sync DB para tracked_notes
    for filename, reference_name in tracked_notes.items():
        fpath = _note_tex_path(paths, filename)
        if not fpath.exists():
            continue

        modified_dt = file_mtime(fpath)

        try:
            note = db.Note.get(db.Note.filename == filename)
            # update timestamps
            note.last_edit_date = modified_dt
            if note.created is None:
                note.created = note.last_edit_date

            # best-effort build dates
            html_path = paths.abs(paths.html_dir / f"{filename}.html")
            pdf_path = paths.abs(paths.pdf_dir / f"{filename}.pdf")

            if html_path.exists():
                note.last_build_date_html = file_mtime(html_path)
            if pdf_path.exists():
                note.last_build_date_pdf = file_mtime(pdf_path)

            # update reference si difiere
            if note.reference != reference_name:
                note.reference = reference_name

            note.save()
            updated_notes.append(note)

        except db.Note.DoesNotExist:
            # Si existe una nota con el mismo reference, reasignar filename (comportamiento legacy) :contentReference[oaicite:7]{index=7}
            try:
                note = db.Note.get(db.Note.reference == reference_name)
                note.filename = filename
                note.last_edit_date = modified_dt
                if note.created is None:
                    note.created = modified_dt
                note.save()
                updated_notes.append(note)
            except db.Note.DoesNotExist:
                note = db.Note.create(
                    filename=filename,
                    reference=reference_name,
                    created=modified_dt,
                    last_edit_date=modified_dt,
                )
                added_notes.append(note)

    # 5) Reparsear labels/citations/links para todas las notas presentes en DB
    for note in db.Note:
        try:
            _update_note_from_file(db, note, paths)
        except NoteNotFound:
            continue

    return ForceSyncResult(
        tracked_notes=tracked_notes,
        added_notes=added_notes,
        updated_notes=updated_notes,
    )
