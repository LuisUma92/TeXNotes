# src/latexzettel/cli/commands/sync.py
from __future__ import annotations

from dataclasses import asdict
from typing import Optional

import click

from latexzettel.cli.context import CLIContext
from latexzettel.domain.errors import DomainError
from latexzettel.api.sync import synchronize, force_synchronize
from latexzettel.api.markdown import sync_md


def register(root: click.Group) -> None:
    root.add_command(sync)


@click.group()
@click.pass_context
def sync(ctx: click.Context) -> None:
    """Sincronización DB <-> filesystem y pipeline Markdown."""
    _ = ctx


# -----------------------------------------------------------------------------
# synchronize (incremental)
# -----------------------------------------------------------------------------


@sync.command("synchronize")
@click.pass_context
def cmd_synchronize(ctx: click.Context) -> None:
    """
    Sincronización incremental:
    - detecta notas .tex modificadas
    - actualiza labels/citations/links en DB
    """
    c: CLIContext = ctx.obj
    try:
        res = synchronize(db=c.db, paths=c.settings.paths)

        click.echo(f"Updated notes: {len(res.updated_notes)}")
        for n in res.updated_notes:
            click.echo(f"  {n.filename}")

        click.echo(f"Modified links: {len(res.new_or_modified_links)}")

        # Reporte de biber
        needs_biber = [note.filename for note, rb in res.run_biber.items() if rb]
        click.echo(f"Needs biber: {len(needs_biber)}")
        for fn in needs_biber:
            click.echo(f"  {fn}")

    except DomainError as e:
        raise click.ClickException(str(e)) from e


# -----------------------------------------------------------------------------
# force_synchronize (full rebuild)
# -----------------------------------------------------------------------------


@sync.command("force")
@click.option(
    "--create-missing-files",
    is_flag=True,
    help="Crear archivos .tex faltantes que estén en documents.tex (no interactivo).",
)
@click.option(
    "--no-create-documents-tex",
    is_flag=True,
    help="No crear notes/documents.tex si no existe (fallar).",
)
@click.pass_context
def cmd_force(
    ctx: click.Context,
    create_missing_files: bool,
    no_create_documents_tex: bool,
) -> None:
    """
    Sincronización completa:
    - lee documents.tex
    - alinea DB con filesystem
    - reparsea labels/citations/links para todas las notas
    """
    c: CLIContext = ctx.obj
    try:
        res = force_synchronize(
            db=c.db,
            paths=c.settings.paths,
            create_missing_note_files=create_missing_files,
            create_documents_tex_if_missing=not no_create_documents_tex,
        )

        click.echo(f"Tracked in documents.tex: {len(res.tracked_notes)}")
        click.echo(f"Added notes: {len(res.added_notes)}")
        for n in res.added_notes:
            click.echo(f"  {n.filename}")

        click.echo(f"Updated notes: {len(res.updated_notes)}")
        for n in res.updated_notes:
            click.echo(f"  {n.filename}")

    except DomainError as e:
        raise click.ClickException(str(e)) from e


# -----------------------------------------------------------------------------
# sync-md (Markdown -> LaTeX slipbox)
# -----------------------------------------------------------------------------


@sync.command("sync-md")
@click.option(
    "--no-overwrite",
    is_flag=True,
    help="No sobrescribir .tex existente en slipbox.",
)
@click.option(
    "--no-auto-register",
    is_flag=True,
    help="No crear notas nuevas en DB/documents.tex aunque existan .md nuevos.",
)
@click.pass_context
def cmd_sync_md(ctx: click.Context, no_overwrite: bool, no_auto_register: bool) -> None:
    """
    Sincroniza notes/md/*.md -> notes/slipbox/*.tex usando pandoc,
    convirtiendo wikilinks a \\excref/\\exhyperref.
    """
    c: CLIContext = ctx.obj
    try:
        res = sync_md(
            db=c.db,
            paths=c.settings.paths,
            pandoc=c.settings.pandoc,
            overwrite_tex=not no_overwrite,
            auto_register_new_notes=not no_auto_register,
        )

        click.echo(f"Created notes: {len(res.created_notes)}")
        for fn in res.created_notes:
            click.echo(f"  {fn}")

        click.echo(f"Updated notes: {len(res.updated_notes)}")
        for fn in res.updated_notes:
            click.echo(f"  {fn}")

        click.echo(f"Skipped notes: {len(res.skipped_notes)}")
        for fn in res.skipped_notes:
            click.echo(f"  {fn}")

        if res.pandoc_failures:
            click.echo(f"Pandoc failures: {len(res.pandoc_failures)}", err=True)
            for fn, err in res.pandoc_failures.items():
                click.echo(f"FAIL: {fn}", err=True)
                click.echo(err, err=True)

    except DomainError as e:
        raise click.ClickException(str(e)) from e
