# src/latexzettel/cli/main.py
from __future__ import annotations

import importlib

import click

from latexzettel.config.settings import DEFAULT_SETTINGS
from latexzettel.infra.db import ensure_tables

from latexzettel.cli.commands.notes import notes
from latexzettel.cli.commands.render import render
from latexzettel.cli.commands.sync import sync
from latexzettel.cli.commands.export import export
from latexzettel.cli.commands.analysis import analysis
from latexzettel.cli.context import CLIContext


def _load_db_module(db_module: str):
    """
    Importa un módulo DB por string, p.ej.:
      - "LatexZettel.database"
      - "texnotes.database"
      - "latexzettel.infra.orm"  (si luego migras)

    Esto mantiene el CLI desacoplado del origen.
    """
    return importlib.import_module(db_module)


def _init_db(db) -> None:
    """
    Inicializa tablas SOLO si falta el esquema.
    """
    health = ensure_tables(db)
    if not health.ok:
        raise click.ClickException(f"No se pudo inicializar la DB: {health.error}")


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--db-module",
    default="latexzettel.infra.orm",
    show_default=True,
    help="Ruta del módulo peewee que define la DB y modelos (Note, Label, Link, etc.).",
)
@click.option(
    "--root",
    type=click.Path(file_okay=False, dir_okay=True, path_type=str),
    default=".",
    show_default=True,
    help="Root del proyecto (donde viven notes/, template/, projects/, etc.).",
)
@click.pass_context
def cli(ctx: click.Context, db_module: str, root: str) -> None:
    """
    CLI para gestionar el Zettelkasten LaTeX.
    """
    settings = DEFAULT_SETTINGS

    db = _load_db_module(db_module)
    _init_db(db)

    ctx.obj = CLIContext(db=db, settings=settings)


cli.add_command(notes)
cli.add_command(render)
cli.add_command(sync)
cli.add_command(export)
cli.add_command(analysis)
# cli.add_command(misc)


def main() -> None:
    """
    Entry point para console_scripts.
    """
    print("hola")
    cli()


if __name__ == "__main__":
    main()
