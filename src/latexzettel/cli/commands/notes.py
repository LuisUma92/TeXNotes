# src/latexzettel/cli/commands/notes.py
from __future__ import annotations

from typing import Optional

import click

from latexzettel.cli.context import CLIContext
from latexzettel.domain.errors import (
    DomainError,
    NoteAlreadyExists,
    ReferenceAlreadyExists,
)
from latexzettel.api import notes as api_notes
from latexzettel.api.workflows import (
    list_recent_notes,
    get_recent_note,
    open_note_in_editor,
)
from latexzettel.api.markdown import tex_to_md
from latexzettel.util.io import confirm


@click.group()
@click.pass_context
def notes(ctx: click.Context) -> None:
    """Operaciones sobre notas (crear, renombrar, borrar, listar, abrir, exportar a md)."""
    _ = ctx  # contexto provisto por Click


# -----------------------------------------------------------------------------
# newnote
# -----------------------------------------------------------------------------


@notes.command("newnote")
@click.argument("note_name", type=str)
@click.argument("reference_name", required=False, type=str)
@click.option(
    "--ext",
    "extension",
    default="tex",
    show_default=True,
    help="Extensión de nota (tex o md).",
)
@click.option(
    "--no-documents",
    is_flag=True,
    help="No agregar \\externaldocument[...]{} en notes/documents.tex.",
)
@click.option(
    "--no-file",
    is_flag=True,
    help="No crear archivo en notes/slipbox (o notes/<ext>). Solo registra en DB.",
)
@click.pass_context
def cmd_newnote(
    ctx: click.Context,
    note_name: str,
    reference_name: Optional[str],
    extension: str,
    no_documents: bool,
    no_file: bool,
) -> None:
    """Crea una nueva nota."""
    c: CLIContext = ctx.obj
    try:
        api_notes.create_note(
            db=c.db,
            note_name=note_name,
            reference_name=reference_name,
            extension=extension,
            paths=c.settings.paths,
            add_to_documents=not no_documents,
            create_file=not no_file,
        )
        click.echo(f"OK: '{note_name}' (ext={extension})")
    except (NoteAlreadyExists, ReferenceAlreadyExists) as e:
        raise click.ClickException(str(e)) from e
    except DomainError as e:
        raise click.ClickException(str(e)) from e


@notes.command("newnote-md")
@click.argument("note_name", type=str)
@click.argument("reference_name", required=False, type=str)
@click.pass_context
def cmd_newnote_md(
    ctx: click.Context, note_name: str, reference_name: Optional[str]
) -> None:
    """Crea una nueva nota markdown (notes/md)."""
    c: CLIContext = ctx.obj
    try:
        api_notes.create_note_md(
            db=c.db,
            note_name=note_name,
            reference_name=reference_name,
            paths=c.settings.paths,
        )
        click.echo(f"OK: creada '{note_name}' (md)")
    except (NoteAlreadyExists, ReferenceAlreadyExists) as e:
        raise click.ClickException(str(e)) from e
    except DomainError as e:
        raise click.ClickException(str(e)) from e


# -----------------------------------------------------------------------------
# rename
# -----------------------------------------------------------------------------


@notes.command("rename-file")
@click.argument("old_filename", type=str)
@click.argument("new_filename", type=str)
@click.pass_context
def cmd_rename_file(ctx: click.Context, old_filename: str, new_filename: str) -> None:
    """Renombra el archivo de una nota (notes/slipbox/<old>.tex -> <new>.tex) y actualiza DB + documents.tex."""
    c: CLIContext = ctx.obj
    try:
        api_notes.rename_note_file(
            db=c.db,
            old_filename=old_filename,
            new_filename=new_filename,
            paths=c.settings.paths,
        )
        click.echo(f"OK: renombrado archivo '{old_filename}' -> '{new_filename}'")
    except DomainError as e:
        raise click.ClickException(str(e)) from e


@notes.command("rename-ref")
@click.argument("old_reference", type=str)
@click.argument("new_reference", type=str)
@click.option(
    "--no-backrefs",
    is_flag=True,
    help="No actualizar archivos que referencian esta nota (solo documents.tex y DB).",
)
@click.pass_context
def cmd_rename_ref(
    ctx: click.Context, old_reference: str, new_reference: str, no_backrefs: bool
) -> None:
    """Renombra la reference de una nota en todo el sistema."""
    c: CLIContext = ctx.obj
    try:
        api_notes.rename_reference(
            db=c.db,
            old_reference=old_reference,
            new_reference=new_reference,
            paths=c.settings.paths,
            update_backrefs=not no_backrefs,
        )
        click.echo(f"OK: renombrada reference '{old_reference}' -> '{new_reference}'")
    except DomainError as e:
        raise click.ClickException(str(e)) from e


# -----------------------------------------------------------------------------
# remove
# -----------------------------------------------------------------------------


@notes.command("remove")
@click.argument("filename", type=str)
@click.option(
    "--db/--no-db", default=True, show_default=True, help="Borrar entrada en DB."
)
@click.option(
    "--documents/--no-documents",
    default=True,
    show_default=True,
    help="Borrar la línea correspondiente en notes/documents.tex.",
)
@click.option(
    "--file", "delete_file", is_flag=True, help="Borrar notes/slipbox/<filename>.tex."
)
@click.option("--yes", is_flag=True, help="No pedir confirmación.")
@click.pass_context
def cmd_remove(
    ctx: click.Context,
    filename: str,
    db: bool,
    documents: bool,
    delete_file: bool,
    yes: bool,
) -> None:
    """Elimina una nota (controlado por flags)."""
    c: CLIContext = ctx.obj

    if not yes:
        warning = (
            f"Se eliminará '{filename}' con opciones: "
            f"db={db}, documents={documents}, file={delete_file}."
        )
        if not confirm(warning, default=False):
            click.echo("Abortado.")
            return

    try:
        api_notes.remove_note(
            db=c.db,
            filename=filename,
            paths=c.settings.paths,
            delete_db_entry=db,
            delete_documents_entry=documents,
            delete_file=delete_file,
        )
        click.echo(f"OK: eliminado '{filename}'")
    except DomainError as e:
        raise click.ClickException(str(e)) from e


# -----------------------------------------------------------------------------
# recent
# -----------------------------------------------------------------------------


@notes.command("list-recent")
@click.option(
    "-n", default=10, show_default=True, type=int, help="Cantidad de notas recientes."
)
@click.pass_context
def cmd_list_recent(ctx: click.Context, n: int) -> None:
    """Lista las notas más recientemente editadas (por mtime del .tex)."""
    c: CLIContext = ctx.obj
    recent = list_recent_notes(paths=c.settings.paths, n=n)
    if not recent:
        click.echo("No hay notas en slipbox.")
        return

    # salida humana y estable
    for i, item in enumerate(recent, start=1):
        click.echo(f"{i:>2}: {item.filename}")


@notes.command("show-recent")
@click.option(
    "-n",
    "idx",
    default=1,
    show_default=True,
    type=int,
    help="Índice 1..N (1 = más reciente).",
)
@click.pass_context
def cmd_show_recent(ctx: click.Context, idx: int) -> None:
    """Muestra cuál es la n-ésima nota reciente (1-indexado)."""
    c: CLIContext = ctx.obj
    try:
        r = get_recent_note(paths=c.settings.paths, n=idx)
        click.echo(r.filename)
    except DomainError as e:
        raise click.ClickException(str(e)) from e


# -----------------------------------------------------------------------------
# edit / open
# -----------------------------------------------------------------------------


@notes.command("edit")
@click.argument("filename", required=False, type=str)
@click.pass_context
def cmd_edit(ctx: click.Context, filename: Optional[str]) -> None:
    """
    Abre una nota con el comando del sistema.
    Si no se indica filename, abre la nota más reciente.
    """
    c: CLIContext = ctx.obj
    try:
        res = open_note_in_editor(
            filename=filename,
            paths=c.settings.paths,
            open_command=c.settings.platform.open_command,
        )
        if res.returncode != 0:
            raise click.ClickException(res.stderr_text())
    except DomainError as e:
        raise click.ClickException(str(e)) from e


# -----------------------------------------------------------------------------
# to-md (export)
# -----------------------------------------------------------------------------


@notes.command("to-md")
@click.argument("note_name", type=str)
@click.option(
    "--out-dir",
    type=click.Path(file_okay=False, dir_okay=True, path_type=str),
    default=None,
    help="Directorio de salida. Por defecto: <root>/markdown/",
)
@click.option(
    "--no-overwrite", is_flag=True, help="No sobrescribir si el .md ya existe."
)
@click.pass_context
def cmd_to_md(
    ctx: click.Context, note_name: str, out_dir: Optional[str], no_overwrite: bool
) -> None:
    """Exporta una nota LaTeX a Markdown (conversión de exrefs a wikilinks + pandoc)."""
    c: CLIContext = ctx.obj
    try:
        out_path = (
            None
            if out_dir is None
            else click.Path(path_type=str).convert(out_dir, None, ctx)
        )  # type: ignore[arg-type]
        # Nota: tex_to_md acepta Path|None; convertimos a Path si aplica
        from pathlib import Path as _Path

        res = tex_to_md(
            db=c.db,
            note_name=note_name,
            paths=c.settings.paths,
            pandoc=c.settings.pandoc,
            output_dir=None if out_dir is None else _Path(out_dir),
            overwrite=not no_overwrite,
        )
        click.echo(str(res.output_file))
        if res.pandoc_stderr:
            # warnings de pandoc, no necesariamente error
            click.echo(res.pandoc_stderr, err=True)
    except DomainError as e:
        raise click.ClickException(str(e)) from e
