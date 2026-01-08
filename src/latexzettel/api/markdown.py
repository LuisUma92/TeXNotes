# src/latexzettel/api/markdown.py
"""
API para interoperabilidad Markdown <-> LaTeX.

Este módulo implementa, en versión no-interactiva y desacoplada del CLI:

- Helper.sync_md(): sincroniza notes/md/*.md hacia notes/slipbox/*.tex usando pandoc,
  convirtiendo WikiLinks [[...]] a \\excref/\\exhyperref, y asegurando DB + documents.tex.
- Helper.to_md(): exporta una nota LaTeX a Markdown convirtiendo \\excref/\\exhyperref a WikiLinks
  y ejecutando pandoc.

Diseño:
- Sin prints/input.
- DB se inyecta como "módulo externo" (modularidad), compatible con infra/db.py.
- Ejecución de pandoc via infra/processes.py.
- Regex centralizadas en infra/regexes.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from latexzettel.config.settings import DEFAULT_SETTINGS, NotesPaths, PandocSettings
from latexzettel.domain.errors import DomainError, NoteNotFound
from latexzettel.infra.db import ensure_tables
from latexzettel.infra.processes import run_pandoc
from latexzettel.infra.regexes import (
    WIKILINK_NOTE_RE,
    WIKILINK_NOTE_LABEL_RE,
    WIKILINK_NOTE_TEXT_RE,
    WIKILINK_NOTE_LABEL_TEXT_RE,
    EX_REF_WITH_TEXT_RE,
)
from latexzettel.util.fs import append_documents_entry
from latexzettel.util.text import default_filename, default_reference_name


# =============================================================================
# Resultados
# =============================================================================


@dataclass(frozen=True)
class SyncMdResult:
    """
    created_notes:
      filenames (slipbox) creados en DB durante sync_md.
    updated_notes:
      filenames (slipbox) cuyo .tex fue regenerado (pandoc).
    skipped_notes:
      filenames omitidos por políticas (p.ej. overwrite=False).
    pandoc_failures:
      dict filename -> stderr (texto) cuando pandoc retorna error.
    """

    created_notes: list[str]
    updated_notes: list[str]
    skipped_notes: list[str]
    pandoc_failures: dict[str, str]


@dataclass(frozen=True)
class TexToMdResult:
    """
    output_file:
      ruta del markdown generado.
    pandoc_stderr:
      stderr de pandoc (texto) si hubo warning (aunque rc=0).
    """

    output_file: Path
    pandoc_stderr: str


# =============================================================================
# Helpers internos
# =============================================================================


def _slipbox_tex_path(paths: NotesPaths, filename: str) -> Path:
    return paths.abs(paths.slipbox_dir / f"{filename}.tex")


def _md_dir(paths: NotesPaths) -> Path:
    # en settings.py existe md_dir; lo usamos
    return paths.abs(paths.md_dir)


def _wiki_note_to_db_filename(wiki_note: str) -> str:
    """
    En sync_md legacy: se toma el nombre del archivo md (sin .md),
    y se normaliza espacios a underscore. Aquí hacemos algo más canónico.

    Ej:
      "My Note" -> "my_note"
      "mi-nota" -> "mi_nota"
    """
    return default_filename(wiki_note)


def _md_filename_to_slipbox_filename(md_path: Path) -> str:
    """
    Determina el filename destino en slipbox a partir del nombre del archivo .md.
    Legacy:
      filename = basename(file)[:-3]
      sb_name = '_'.join(filename.split(' '))
    """
    stem = md_path.stem
    return _wiki_note_to_db_filename(stem)


def _md_name_to_reference(db, md_note_name: str) -> str:
    """
    Convierte el nombre dentro del wikilink [[...]] hacia la reference LaTeX.
    En legacy se asumía que el texto era el filename (con espacios) y se buscaba Note por filename.
    Aquí lo canonicalizamos a filename y resolvemos reference en DB.
    """
    filename = _wiki_note_to_db_filename(md_note_name)
    try:
        return db.Note.get(db.Note.filename == filename).reference
    except db.Note.DoesNotExist as e:
        raise NoteNotFound(
            f"No existe nota en DB para wikilink '{md_note_name}' (filename='{filename}')"
        ) from e


def _convert_wikilinks_to_latex(db, md_text: str) -> str:
    """
    Reemplaza WikiLinks por \\excref/\\exhyperref.
    Replica la intención de sync_md() legacy con 4 regex.
    """

    # [[Note]]
    def repl_note(m):
        ref = _md_name_to_reference(db, m.group(1))
        return f"\\excref{{{ref}}}"

    text = WIKILINK_NOTE_RE.sub(repl_note, md_text)

    # [[Note#label]]
    def repl_note_label(m):
        ref = _md_name_to_reference(db, m.group(1))
        label = m.group(2)
        return f"\\excref[{label}]{{{ref}}}"

    text = WIKILINK_NOTE_LABEL_RE.sub(repl_note_label, text)

    # [[Note|Text]]
    def repl_note_text(m):
        ref = _md_name_to_reference(db, m.group(1))
        label_text = m.group(2)
        return f"\\exhyperref{{{ref}}}{{{label_text}}}"

    text = WIKILINK_NOTE_TEXT_RE.sub(repl_note_text, text)

    # [[Note#label|Text]]
    def repl_note_label_text(m):
        ref = _md_name_to_reference(db, m.group(1))
        label = m.group(2)
        label_text = m.group(3)
        return f"\\exhyperref[{label}]{{{ref}}}{{{label_text}}}"

    text = WIKILINK_NOTE_LABEL_TEXT_RE.sub(repl_note_label_text, text)
    return text


def _convert_exrefs_to_wikilinks(db, latex_text: str) -> str:
    """
    Convierte \\excref/\\exhyperref a WikiLinks, como to_md() legacy.

    Maneja:
      \\excref{Ref}                      -> [[filename]]
      \\excref[label]{Ref}               -> [[filename#label]]
      \\exhyperref{Ref}{Text}            -> [[filename|Text]]
      \\exhyperref[label]{Ref}{Text}     -> [[filename#label|Text]]
    """

    def replace(m):
        is_hyper = m.group(1) is not None
        label = m.group(4)  # opcional
        ref = m.group(5)
        text = m.group(7)  # opcional (solo si hyperref tenía {Text})

        try:
            note = db.Note.get(db.Note.reference == ref)
        except db.Note.DoesNotExist:
            # si no existe, dejamos la referencia intacta (conservador)
            return m.group(0)

        filename = note.filename

        if not is_hyper:
            if label is None:
                return f"[[{filename}]]"
            return f"[[{filename}#{label}]]"

        # hyperref
        if text is None:
            # caso raro: hyperref sin {Text}; degradamos a link simple
            if label is None:
                return f"[[{filename}]]"
            return f"[[{filename}#{label}]]"

        if label is None:
            return f"[[{filename}|{text}]]"
        return f"[[{filename}#{label}|{text}]]"

    return EX_REF_WITH_TEXT_RE.sub(replace, latex_text)


# =============================================================================
# API pública
# =============================================================================


def sync_md(
    *,
    db,
    paths: NotesPaths = DEFAULT_SETTINGS.paths,
    pandoc: PandocSettings = DEFAULT_SETTINGS.pandoc,
    overwrite_tex: bool = True,
    auto_register_new_notes: bool = True,
) -> SyncMdResult:
    """
    Sincroniza notes/md/*.md hacia notes/slipbox/*.tex con pandoc.

    Semántica base (legacy) :
    - Detecta archivos md.
    - Determina filename destino en slipbox.
    - Asegura que estén en DB y documents.tex (cuando son nuevos).
    - Reescribe wikilinks a comandos LaTeX (\\excref/\\exhyperref).
    - Ejecuta pandoc para producir .tex en slipbox.

    Parámetros:
    - overwrite_tex: si False, no sobrescribe .tex existente.
    - auto_register_new_notes: si True, crea Nota en DB y agrega documents.tex
      cuando detecta md nuevo no registrado.
    """
    health = ensure_tables(db)
    if not health.ok:
        raise DomainError(f"DB no disponible: {health.error}")

    md_dir = _md_dir(paths)
    md_files = sorted(md_dir.rglob("*.md"))

    created_notes: list[str] = []
    updated_notes: list[str] = []
    skipped_notes: list[str] = []
    pandoc_failures: dict[str, str] = {}

    # Conjunto de filenames ya rastreados en DB
    tracked = {n.filename for n in db.Note.select()}

    for md_file in md_files:
        slipbox_filename = _md_filename_to_slipbox_filename(md_file)
        out_tex = _slipbox_tex_path(paths, slipbox_filename)

        # Registrar nota nueva (DB + documents.tex + plantilla .md opcional)
        if slipbox_filename not in tracked:
            if not auto_register_new_notes:
                skipped_notes.append(slipbox_filename)
                continue

            # Crear entrada DB y documents.tex usando el mismo criterio de referencia
            reference = default_reference_name(slipbox_filename)

            db.Note.create(
                filename=slipbox_filename,
                reference=reference,
            )
            append_documents_entry(
                paths, filename=slipbox_filename, reference=reference
            )
            tracked.add(slipbox_filename)
            created_notes.append(slipbox_filename)

        # Política overwrite
        if out_tex.exists() and not overwrite_tex:
            skipped_notes.append(slipbox_filename)
            continue

        # Leer MD y convertir wikilinks a LaTeX
        md_text = md_file.read_text(encoding="utf-8")
        latex_ready_text = _convert_wikilinks_to_latex(db, md_text)

        # Construir opciones pandoc (alineado a legacy)
        # Legacy incluye: -o slipbox.tex + ... + "-M title=<filename>"
        options = [
            "-o",
            str(out_tex),
            *pandoc.latex_options,
            "-M",
            f"title={md_file.stem}",
        ]

        proc = run_pandoc(options=options, input_text=latex_ready_text, check=False)

        if proc.returncode != 0:
            pandoc_failures[slipbox_filename] = proc.stderr_text()
            continue

        updated_notes.append(slipbox_filename)

    return SyncMdResult(
        created_notes=created_notes,
        updated_notes=updated_notes,
        skipped_notes=skipped_notes,
        pandoc_failures=pandoc_failures,
    )


def tex_to_md(
    *,
    db,
    note_name: str,
    paths: NotesPaths = DEFAULT_SETTINGS.paths,
    output_dir: Optional[Path] = None,
    overwrite: bool = True,
) -> TexToMdResult:
    """
    Exporta notes/slipbox/<note_name>.tex a Markdown.

    Semántica base (legacy to_md) :
    - Lee .tex
    - Convierte \\excref/\\exhyperref a wikilinks
    - Ejecuta pandoc latex->markdown para escribir archivo .md

    Parámetros:
    - output_dir: por defecto crea/usa <root>/markdown (como legacy).
    """
    health = ensure_tables(db)
    if not health.ok:
        raise DomainError(f"DB no disponible: {health.error}")

    tex_path = _slipbox_tex_path(paths, note_name)
    if not tex_path.exists():
        raise NoteNotFound(f"No existe el archivo: {tex_path}")

    # Directorio de salida (legacy usaba "markdown/")
    if output_dir is None:
        out_dir = paths.abs(Path("markdown"))
    else:
        out_dir = Path(output_dir).resolve()

    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / f"{note_name}.md"

    if out_md.exists() and not overwrite:
        raise DomainError(f"El archivo ya existe: {out_md} (overwrite=False)")

    latex_text = tex_path.read_text(encoding="utf-8")

    # Convertir exrefs a wikilinks antes de pandoc
    wikified = _convert_exrefs_to_wikilinks(db, latex_text)

    # Ejecutar pandoc: -t markdown -f latex -o out.md
    proc = run_pandoc(
        options=["-t", "markdown", "-f", "latex", "-o", str(out_md)],
        input_text=wikified,
        check=False,
    )

    if proc.returncode != 0:
        raise DomainError(f"pandoc falló al exportar {note_name}: {proc.stderr_text()}")

    return TexToMdResult(output_file=out_md, pandoc_stderr=proc.stderr_text())
