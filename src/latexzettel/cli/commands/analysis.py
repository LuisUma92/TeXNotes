# src/latexzettel/cli/commands/analysis.py
from __future__ import annotations

import click

from latexzettel.cli.context import CLIContext
from latexzettel.domain.errors import DomainError
from latexzettel.api.analysis import (
    calculate_adjacency_matrix,
    list_unreferenced_notes,
    remove_duplicate_citations,
)


def register(root: click.Group) -> None:
    root.add_command(analysis)


@click.group()
@click.pass_context
def analysis(ctx: click.Context) -> None:
    """Análisis del grafo de notas."""
    _ = ctx


# -----------------------------------------------------------------------------
# adjacency matrix
# -----------------------------------------------------------------------------


@analysis.command("adjacency")
@click.option(
    "--index-by",
    default="filename",
    show_default=True,
    type=click.Choice(["filename", "reference", "id"], case_sensitive=False),
    help="Criterio de ordenamiento/indexación de la matriz.",
)
@click.option(
    "--show",
    is_flag=True,
    help="Imprimir la matriz completa (puede ser grande).",
)
@click.pass_context
def cmd_adjacency(ctx: click.Context, index_by: str, show: bool) -> None:
    """Calcula la matriz de adyacencia (N x N) del grafo de referencias."""
    c: CLIContext = ctx.obj
    try:
        res = calculate_adjacency_matrix(db=c.db, index_by=index_by.lower())
        click.echo(f"Notes: {len(res.notes)}")
        click.echo(f"Index by: {res.index_by}")
        if show:
            # Imprime como texto; el usuario puede redirigir a archivo.
            click.echo(str(res.adjacency))
    except DomainError as e:
        raise click.ClickException(str(e)) from e


# -----------------------------------------------------------------------------
# unreferenced
# -----------------------------------------------------------------------------


@analysis.command("unreferenced")
@click.option(
    "--index-by",
    default="filename",
    show_default=True,
    type=click.Choice(["filename", "reference", "id"], case_sensitive=False),
)
@click.pass_context
def cmd_unreferenced(ctx: click.Context, index_by: str) -> None:
    """Lista notas que no son referenciadas por ninguna otra (in-degree = 0)."""
    c: CLIContext = ctx.obj
    try:
        notes = list_unreferenced_notes(db=c.db, index_by=index_by.lower())
        click.echo(f"Unreferenced: {len(notes)}")
        for n in notes:
            click.echo(n.filename)
    except DomainError as e:
        raise click.ClickException(str(e)) from e


# -----------------------------------------------------------------------------
# dedup citations
# -----------------------------------------------------------------------------


@analysis.command("dedup-citations")
@click.pass_context
def cmd_dedup_citations(ctx: click.Context) -> None:
    """Elimina citas duplicadas (misma note + citationkey) en la DB."""
    c: CLIContext = ctx.obj
    try:
        deleted = remove_duplicate_citations(db=c.db)
        click.echo(f"Deleted duplicate citations: {deleted}")
    except DomainError as e:
        raise click.ClickException(str(e)) from e
