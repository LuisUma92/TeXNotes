# src/latexzettel/cli/main.py
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Optional

import click

from latexzettel.config.settings import DEFAULT_SETTINGS, Settings
from latexzettel.infra.db import ensure_tables

from latexzettel.cli.commands import notes, render, sync, export, analysis, misc


@dataclass(frozen=True)
class CLIContext:
    """
    Contexto compartido entre comandos Click.

    db:
      módulo externo peewee (por modularidad). Debe exponer Note, create_all_tables(), database, etc.
    settings:
      configuración ensamblada (paths, renderers, platform, etc.)
    """

    db: object
    settings: Settings


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
    default="LatexZettel.database",
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

    Comandos disponibles: notes, render, sync, export, analysis, misc
    """
    # Construir settings con root (si quieres; por ahora usamos DEFAULT_SETTINGS y
    # asumimos que tu Settings permite root configurable. Si no, se ajusta.)
    settings = DEFAULT_SETTINGS
    # Si tu build_settings(root=...) ya existe, se recomienda:
    # from latexzettel.config.settings import build_settings
    # settings = build_settings(Path(root))

    # Importar DB module y asegurar tablas
    db = _load_db_module(db_module)
    _init_db(db)

    ctx.obj = CLIContext(db=db, settings=settings)

    # Registrar comandos

    notes.register(cli)
    render.register(cli)
    sync.register(cli)
    export.register(cli)
    analysis.register(cli)
    misc.register(cli)


def main() -> None:
    """
    Entry point para console_scripts.
    """
    cli()


if __name__ == "__main__":
    main()
