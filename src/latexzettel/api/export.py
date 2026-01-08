# src/latexzettel/api/export.py
"""
API de exportación.

Refactoriza las funciones legacy:
- Helper.newproject()
- Helper.export_project()
- Helper.export_draft()

del manage.py original. :contentReference[oaicite:0]{index=0}

Diseño:
- Sin Click (sin print/input).
- La interacción (confirmaciones) se hace desde cli/* usando util/io.py si se requiere.
- Opera sobre filesystem; no requiere DB para exportar (igual que legacy).
- Usa infra/regexes.py para consistencia de patrones.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from latexzettel.config.settings import DEFAULT_SETTINGS, NotesPaths
from latexzettel.domain.errors import DomainError
from latexzettel.infra.regexes import (
    TRANSCLUDE_RE,
    EXECUTE_METADATA_RE,
    metadata_block_re,
)
from latexzettel.infra.fs import ensure_dir


# =============================================================================
# Resultados
# =============================================================================


@dataclass(frozen=True)
class NewProjectResult:
    dirpath: Path
    tex_file: Path
    created_dir: bool
    copied_template: bool


@dataclass(frozen=True)
class ExportProjectResult:
    input_file: Path
    output_dir: Path
    output_file: Path
    overwritten: bool


@dataclass(frozen=True)
class ExportDraftResult:
    input_file: Path
    output_file: Path
    created_draft_dir: bool


# =============================================================================
# API pública
# =============================================================================


def new_project(
    *,
    dir_name: str,
    filename: Optional[str] = None,
    paths: NotesPaths = DEFAULT_SETTINGS.paths,
) -> NewProjectResult:
    """
    Crea un folder projects/<dir_name> y copia template/project.tex dentro.

    Equivalente a Helper.newproject(). :contentReference[oaicite:1]{index=1}
    """
    if not dir_name:
        raise ValueError("dir_name vacío")

    projects_dir = paths.abs(paths.projects_dir)
    ensure_dir(projects_dir)

    dirpath = projects_dir / dir_name
    if dirpath.exists():
        raise DomainError(f"El directorio de proyecto ya existe: {dirpath}")

    dirpath.mkdir(parents=True, exist_ok=False)

    if filename is None:
        filename = f"{dir_name}.tex"

    template = paths.abs(paths.template_dir / "project.tex")
    if not template.exists():
        raise DomainError(f"No existe la plantilla de proyecto: {template}")

    tex_file = dirpath / filename
    tex_file.write_bytes(template.read_bytes())

    return NewProjectResult(
        dirpath=dirpath,
        tex_file=tex_file,
        created_dir=True,
        copied_template=True,
    )


def export_project(
    *,
    project_folder: str,
    texfile: Optional[str] = None,
    paths: NotesPaths = DEFAULT_SETTINGS.paths,
    overwrite: bool = False,
) -> ExportProjectResult:
    """
    Reemplaza \\transclude[...]{} en projects/<project_folder>/<texfile>
    con el contenido de la nota, extrayendo el bloque %<*tag>...%</tag>.

    Equivalente a Helper.export_project(). :contentReference[oaicite:2]{index=2}

    - output se guarda en: projects/<project_folder>/standalone/<texfile>
    - si overwrite=False y ya existe output_dir, lanza error (en legacy preguntaba)

    Parámetros:
    - texfile: por defecto "<project_folder>.tex"
    - overwrite: si True, permite sobrescribir output
    """
    if not project_folder:
        raise ValueError("project_folder vacío")

    if texfile is None:
        texfile = f"{project_folder}.tex"

    project_dir = paths.abs(paths.projects_dir / project_folder)
    input_file = project_dir / texfile
    if not input_file.exists():
        raise DomainError(f"No existe el archivo de proyecto: {input_file}")

    output_dir = project_dir / "standalone"
    if output_dir.exists() and not overwrite:
        raise DomainError(
            f"Export ya existe: {output_dir}. Use overwrite=True para sobrescribir."
        )
    ensure_dir(output_dir)

    output_file = output_dir / texfile
    overwritten = output_file.exists()

    out = bytearray()

    # Recorre el archivo línea por línea como legacy
    for line in input_file.read_text(encoding="utf-8").splitlines(True):
        # 1) Emitir la línea con \transclude removido (igual que legacy)
        stripped = TRANSCLUDE_RE.sub("", line).strip()
        out.extend((stripped + "\n").encode("utf-8"))

        # 2) Por cada \transclude, incluir contenido
        for m in TRANSCLUDE_RE.finditer(line):
            tag = m.group(2) or "note"
            document = m.group(3)

            note_file = paths.abs(paths.slipbox_dir / f"{document}.tex")
            if not note_file.exists():
                raise DomainError(f"No existe la nota referenciada: {note_file}")

            full_document = note_file.read_text(encoding="utf-8")
            block = metadata_block_re(tag).search(full_document)
            if not block:
                raise DomainError(
                    f"No se encontró bloque metadata %<*{tag}>...</{tag}> en {note_file}"
                )

            out.extend(block.group(1).strip().encode("utf-8"))

    output_file.write_bytes(out)

    return ExportProjectResult(
        input_file=input_file,
        output_dir=output_dir,
        output_file=output_file,
        overwritten=overwritten,
    )


def export_draft(
    *,
    input_file: str | Path,
    output_file: Optional[str | Path] = None,
    paths: NotesPaths = DEFAULT_SETTINGS.paths,
    overwrite: bool = False,
) -> ExportDraftResult:
    """
    Reemplaza \\ExecuteMetaData[../<import_file>]{tag} con el contenido del bloque
    %<*tag>...%</tag> dentro del archivo importado.

    Equivalente a Helper.export_draft(). :contentReference[oaicite:3]{index=3}

    - Por defecto, crea carpeta draft/ y escribe draft/<basename(input_file)>
    - overwrite controla si se permite sobrescribir output
    """
    in_path = Path(input_file)
    if not in_path.exists():
        raise DomainError(f"No existe input_file: {in_path}")

    created_draft_dir = False

    if output_file is None:
        draft_dir = paths.abs(paths.draft_dir)
        if not draft_dir.exists():
            draft_dir.mkdir(parents=True, exist_ok=True)
            created_draft_dir = True
        out_path = draft_dir / in_path.name
    else:
        out_path = Path(output_file)

    if out_path.exists() and not overwrite:
        raise DomainError(f"output_file ya existe: {out_path}. Use overwrite=True.")

    out = bytearray()

    for line in in_path.read_text(encoding="utf-8").splitlines(True):
        # 1) Emitir línea sin ExecuteMetaData (igual que legacy)
        stripped = EXECUTE_METADATA_RE.sub("", line).strip()
        out.extend((stripped + "\n").encode("utf-8"))

        # 2) Expandir cada ExecuteMetaData
        for m in EXECUTE_METADATA_RE.finditer(line):
            import_file = m.group(1)
            tag = m.group(2)

            import_path = Path(import_file)
            if not import_path.exists():
                raise DomainError(f"No existe import_file: {import_path}")

            import_text = import_path.read_text(encoding="utf-8")
            block = metadata_block_re(tag).search(import_text)
            if not block:
                raise DomainError(
                    f"No se encontró bloque metadata %<*{tag}>...</{tag}> en {import_path}"
                )

            out.extend(block.group(1).strip().encode("utf-8"))

    out_path.write_bytes(out)

    return ExportDraftResult(
        input_file=in_path,
        output_file=out_path,
        created_draft_dir=created_draft_dir,
    )
