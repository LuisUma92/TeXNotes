# src/latexzettel/api/render.py
"""
API de renderizado (PDF/HTML) para una nota.

Este módulo refactoriza la lógica de Helper.render(), Helper.biber(),
render_all_pdf/html() y partes de render_updates() de tu manage.py :contentReference[oaicite:0]{index=0}
a una API sin CLI (sin print/input/sys.exit).

Diseño:
- El ORM/DB se inyecta como "módulo externo" (para modularidad), igual que en infra/db.py.
- La ejecución de procesos externos se delega a infra/processes.py.
- Las rutas y configuración se toman de config/settings.py (NotesPaths, RenderSettings).
- La actualización de timestamps se hace en DB (Note.last_build_date_*).

Nota:
- La construcción del documento (inyección de external documents y sección "Referenced In")
  replica el comportamiento del manage.py original. :contentReference[oaicite:1]{index=1}
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from latexzettel.config.settings import (
    NotesPaths,
    RenderSettings,
    DEFAULT_SETTINGS,
)
from latexzettel.domain.errors import (
    DomainError,
    NoteNotFound,
)
from latexzettel.domain.types import DbModule, RenderFormat
from latexzettel.infra import processes
from latexzettel.infra.db import ensure_tables
from latexzettel.util.time import now

from latexzettel.api.sync import synchronize

# =============================================================================
# Resultados
# =============================================================================


@dataclass(frozen=True)
class RenderResult:
    filename: str
    format: RenderFormat
    ok: bool
    returncode: int
    stdout: bytes
    stderr: bytes
    ran_biber: bool = False

    def stdout_text(self, encoding: str = "utf-8") -> str:
        return self.stdout.decode(encoding, errors="replace")

    def stderr_text(self, encoding: str = "utf-8") -> str:
        return self.stderr.decode(encoding, errors="replace")


# =============================================================================
# Helpers internos
# =============================================================================


def _load_note_tex(paths: NotesPaths, filename: str) -> str:
    tex_path = paths.abs(paths.slipbox_dir / f"{filename}.tex")
    if not tex_path.exists():
        raise NoteNotFound(f"No existe el archivo de la nota: {tex_path}")
    return tex_path.read_text(encoding="utf-8")


def _build_referenced_by_section(linked_refs: set[str]) -> str:
    """
    Replica:
      \\section*{Referenced In}
      \\begin{itemize}
        \\item \\excref{Ref}
      \\end{itemize}
    :contentReference[oaicite:2]{index=2}
    """
    if not linked_refs:
        return ""

    section = "\\section*{Referenced In}\n\\begin{itemize}\n"
    for ref in linked_refs:
        section += f"\\item \\excref{{{ref}}}"
    section += "\\end{itemize}"
    return section


def _inject_external_documents_for_html(
    references: set,
) -> str:
    """
    Construye las líneas \\externaldocument[Ref-]{filename} para HTML, solo para notas
    que tengan last_build_date_html != None.

    Esto replica el bloque:
      if format == 'html':
        for reference in references:
          if reference.last_build_date_html is not None:
             external_documents += ...
    :contentReference[oaicite:3]{index=3}
    """
    external_documents = ""
    for reference in references:
        if getattr(reference, "last_build_date_html", None) is not None:
            external_documents += (
                f"\\externaldocument[{reference.reference}-]{{{reference.filename}}}\n"
            )
    return external_documents


def _prepare_document_for_render(
    *,
    raw_tex: str,
    format: RenderFormat,
    referenced_by_section: str,
    external_documents: str,
) -> str:
    """
    Construye el documento final:
    - recorta antes de \\end{document}
    - añade sección "Referenced In" si procede
    - para HTML: reemplaza preamble.tex por preamble_html.tex y/o inyecta external docs
    - re-anexa \\end{document}

    Replica Helper.render() :contentReference[oaicite:4]{index=4}
    """
    document = raw_tex.split("\\end{document}")[0]

    if referenced_by_section:
        document += referenced_by_section

    if format == RenderFormat.HTML:
        # Inyecta external docs y cambia preámbulo
        document = document.replace(
            "\\subimport{../template}{preamble.tex}",
            "\\subimport{../template}{preamble_html.tex}\n" + external_documents,
        )
        document = document.replace(
            "\\documentclass{../template/texnote}",
            "\\documentclass{../template/texnote}\n" + external_documents,
        )

    document += "\\end{document}"
    return document


# =============================================================================
# API pública
# =============================================================================


def biber(
    *,
    filename: str,
    folder: Path,
    check: bool = False,
) -> processes.ProcessResult:
    """
    Ejecuta biber en el folder indicado (pdf o html).
    Equivalente a Helper.biber() :contentReference[oaicite:5]{index=5}
    """
    return processes.run_biber(filename, folder=folder, check=check)


def render_note(
    *,
    db: DbModule,
    filename: str,
    format: RenderFormat = RenderFormat.PDF,
    run_biber: bool = False,
    settings: RenderSettings = DEFAULT_SETTINGS.render,
    paths: NotesPaths = DEFAULT_SETTINGS.paths,
    timestamp: Optional[datetime] = None,
    check: bool = False,
) -> RenderResult:
    """
    Renderiza una nota a PDF o HTML.

    Parámetros:
    - db: módulo externo de Peewee (legacy o nuevo), con Note + create_all_tables + database
    - filename: nombre de nota (sin extensión)
    - format: RenderFormat.PDF | RenderFormat.HTML
    - run_biber: si True, ejecuta un ciclo: render -> biber -> render (igual que manage.py) :contentReference[oaicite:6]{index=6}
    - settings: RenderSettings (comandos y opciones)
    - paths: NotesPaths (rutas del proyecto)
    - timestamp: si None, usa util.time.now()
    - check: si True, lanza excepción si el render falla

    Devuelve:
    - RenderResult con stdout/stderr y estado.
    """
    # Timestamp
    ts = timestamp or now()

    # Asegurar esquema si estás usando el patrón modular defensivo
    health = ensure_tables(db)
    if not health.ok:
        raise DomainError(f"DB no disponible: {health.error}")

    # Obtener Note desde DB
    try:
        note = db.Note.get(db.Note.filename == filename)
    except db.Note.DoesNotExist as e:
        raise NoteNotFound(f"No existe nota en DB: filename='{filename}'") from e

    # Render->biber->render (semántica original)
    if run_biber:
        # Primera pasada sin biber=True para evitar recursión
        _ = render_note(
            db=db,
            filename=filename,
            format=format,
            run_biber=False,
            settings=settings,
            paths=paths,
            timestamp=ts,
            check=check,
        )
        # biber se ejecuta sobre el artefacto en la carpeta correspondiente
        folder = paths.abs(
            paths.pdf_dir if format == RenderFormat.PDF else paths.html_dir
        )
        _ = biber(filename=filename, folder=folder, check=check)
        # Segunda pasada
        return render_note(
            db=db,
            filename=filename,
            format=format,
            run_biber=False,
            settings=settings,
            paths=paths,
            timestamp=ts,
            check=check,
        )

    # Selección renderer
    if format.value not in settings.renderers:
        raise ValueError(f"Formato no soportado: {format}")

    renderer = settings.renderers[format.value]
    options = list(renderer.options)

    # Crear carpeta de salida (pdf/ o html/) como manage.py :contentReference[oaicite:7]{index=7}
    out_dir = paths.abs(paths.pdf_dir if format == RenderFormat.PDF else paths.html_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Cargar contenido tex
    raw_tex = _load_note_tex(paths, filename)

    # Calcular referenced_by + referencias (igual que manage.py)
    linked_refs: set[str] = set()
    references: set = set()

    # referencias entrantes: note.labels -> label.referenced_by -> link.source
    for label in note.labels:
        for link in label.referenced_by:
            references.add(link.source)
            linked_refs.add(link.source.reference)

    # referencias salientes: note.references -> link.target.note
    for link in note.references:
        target_note = link.target.note
        if getattr(target_note, "last_build_date_html", None) is not None:
            references.add(target_note)

    referenced_by_section = _build_referenced_by_section(linked_refs)

    external_documents = ""
    if format == RenderFormat.HTML:
        external_documents = _inject_external_documents_for_html(references)

    # Preparar documento final
    final_document = _prepare_document_for_render(
        raw_tex=raw_tex,
        format=format,
        referenced_by_section=referenced_by_section,
        external_documents=external_documents,
    )

    # Ajuste de opciones según formato (semántica original)
    if format == RenderFormat.PDF:
        # pdflatex --jobname=<filename> ...
        options.insert(0, f"--jobname={filename}")
    else:
        # make4ht -j <filename> ... "svg-"
        options = ["-j", filename] + options + ['"svg-"']

    # Ejecutar proceso en out_dir, con stdin el documento
    proc = processes.run_latex_renderer(
        command=renderer.command,
        options=options,
        input_tex=final_document.encode("utf-8"),
        cwd=out_dir,
        check=check,
    )

    # Si falló y check=False, devolver resultado con ok=False
    if not proc.ok:
        return RenderResult(
            filename=filename,
            format=format,
            ok=False,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            ran_biber=False,
        )

    # Actualizar timestamps en DB
    if format == RenderFormat.HTML:
        note.last_build_date_html = ts
    else:
        note.last_build_date_pdf = ts
    note.save()

    return RenderResult(
        filename=filename,
        format=format,
        ok=True,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        ran_biber=False,
    )


def render_all(
    *,
    db: DbModule,
    format: RenderFormat = RenderFormat.PDF,
    settings: RenderSettings = DEFAULT_SETTINGS.render,
    paths: NotesPaths = DEFAULT_SETTINGS.paths,
    run_biber_each: bool = True,
    check: bool = False,
) -> list[RenderResult]:
    """
    Renderiza todas las notas en notes/slipbox/*.tex.

    Equivale a render_all_pdf() / render_all_html() pero sin prints y
    con retorno de resultados. :contentReference[oaicite:8]{index=8}

    Nota:
    - La implementación original hacía "pass 1" y "pass 2".
    - Aquí mantenemos dos pasadas para reproducir la semántica.
    """
    from latexzettel.infra.fs import rglob_files  # import local para evitar ciclos

    health = ensure_tables(db)
    if not health.ok:
        raise DomainError(f"DB no disponible: {health.error}")

    note_files = rglob_files(paths.abs(paths.slipbox_dir), suffix=".tex")
    filenames = [p.stem for p in note_files]

    results: list[RenderResult] = []

    # pass 1
    for fn in filenames:
        res = render_note(
            db=db,
            filename=fn,
            format=format,
            run_biber=run_biber_each,
            settings=settings,
            paths=paths,
            check=check,
        )
        results.append(res)

    # pass 2
    for fn in filenames:
        res = render_note(
            db=db,
            filename=fn,
            format=format,
            run_biber=False,
            settings=settings,
            paths=paths,
            check=check,
        )
        results.append(res)

    return results


@dataclass(frozen=True)
class RenderUpdatesResult:
    """
    rendered:
      notas renderizadas porque estaban modificadas (sync) o requerían build por timestamps.
    rerendered_targets:
      notas target re-renderizadas por aparición/cambio de links.
    rerendered_sources:
      notas source re-renderizadas por aparición/cambio de links.
    """

    rendered: list[str]
    rerendered_targets: list[str]
    rerendered_sources: list[str]


def render_updates(
    *,
    db: DbModule,
    format: RenderFormat = RenderFormat.PDF,
    settings: RenderSettings = DEFAULT_SETTINGS.render,
    paths: NotesPaths = DEFAULT_SETTINGS.paths,
    timestamp: Optional[datetime] = None,
    check: bool = False,
) -> RenderUpdatesResult:
    """
    Render incremental con semántica legacy.

    Parámetros:
    - db: módulo externo peewee (modularidad)
    - format: RenderFormat.PDF | RenderFormat.HTML
    - timestamp: timestamp único para esta corrida (si None, now()).
    - check: si True, propaga fallos de proceso como excepción (ver api/render.py).
    """
    ts = timestamp or now()

    health = ensure_tables(db)
    if not health.ok:
        raise DomainError(f"DB no disponible: {health.error}")

    # 1) Sync incremental (equivalente a Helper.synchronize())
    sync_res = synchronize(db=db, paths=paths)

    # "updated" del legacy = to_read (notas cuyo archivo cambió desde last_edit_date)
    updated = list(sync_res.updated_notes)  # list[Note]
    new_links = list(sync_res.new_or_modified_links)  # list[Link]
    run_biber = dict(sync_res.run_biber)  # dict[Note, bool]

    # 2) Extender updated con notas que requieren render por timestamps (igual que legacy)
    #    y, al agregarlas, marcar run_biber=True y extender new_links con note.references
    for note in db.Note:
        if note in updated:
            continue

        if format == RenderFormat.PDF:
            needs = (note.last_build_date_pdf is None) or (
                note.last_edit_date is not None
                and note.last_edit_date > note.last_build_date_pdf
            )
        else:
            needs = (note.last_build_date_html is None) or (
                note.last_edit_date is not None
                and note.last_edit_date > note.last_build_date_html
            )

        if needs:
            updated.append(note)
            run_biber[note] = True
            # en legacy: new_links.extend([r for r in note.references])
            new_links.extend(list(note.references))

    # 3) Renderizar las notas "updated"
    rendered_names: list[str] = []
    for note in updated:
        rb = bool(run_biber.get(note, False))
        res = render_note(
            db=db,
            filename=note.filename,
            format=format,
            run_biber=rb,
            settings=settings,
            paths=paths,
            timestamp=ts,
            check=check,
        )
        if res.ok:
            rendered_names.append(note.filename)

    # 4) Re-render targets afectados por new_links (una vez cada uno)
    rerendered_targets: list[str] = []
    seen_targets: set[str] = set()
    for link in new_links:
        target_note = link.target.note
        if target_note.filename in seen_targets:
            continue
        seen_targets.add(target_note.filename)

        res = render_note(
            db=db,
            filename=target_note.filename,
            format=format,
            run_biber=False,
            settings=settings,
            paths=paths,
            timestamp=ts,
            check=check,
        )
        if res.ok:
            rerendered_targets.append(target_note.filename)

    # 5) Re-render sources afectados por new_links (una vez cada uno)
    rerendered_sources: list[str] = []
    seen_sources: set[str] = set()
    for link in new_links:
        source_note = link.source
        if source_note.filename in seen_sources:
            continue
        seen_sources.add(source_note.filename)

        res = render_note(
            db=db,
            filename=source_note.filename,
            format=format,
            run_biber=False,
            settings=settings,
            paths=paths,
            timestamp=ts,
            check=check,
        )
        if res.ok:
            rerendered_sources.append(source_note.filename)

    return RenderUpdatesResult(
        rendered=rendered_names,
        rerendered_targets=rerendered_targets,
        rerendered_sources=rerendered_sources,
    )
