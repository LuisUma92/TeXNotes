# src/latexzettel/cli/commands/export.py
from __future__ import annotations

from pathlib import Path
from typing import Optional

import click

from latexzettel.cli.context import CLIContext
from latexzettel.domain.errors import DomainError
from latexzettel.api.export import new_project, export_project, export_draft


def register(root: click.Group) -> None:
    root.add_command(export)


@click.group()
@click.pass_context
def export(ctx: click.Context) -> None:
    """Exportación (proyectos y drafts)."""
    _ = ctx


# -----------------------------------------------------------------------------
# newproject
# -----------------------------------------------------------------------------


@export.command("newproject")
@click.argument("dir_name", type=str)
@click.option(
    "--filename",
    type=str,
    default=None,
    help="Nombre del archivo .tex dentro del proyecto (por defecto: <dir_name>.tex).",
)
@click.pass_context
def cmd_newproject(ctx: click.Context, dir_name: str, filename: Optional[str]) -> None:
    """Crea un proyecto en projects/<dir_name> copiando template/project.tex."""
    c: CLIContext = ctx.obj
    try:
        res = new_project(dir_name=dir_name, filename=filename, paths=c.settings.paths)
        click.echo(f"OK: creado proyecto {res.dirpath}")
        click.echo(str(res.tex_file))
    except DomainError as e:
        raise click.ClickException(str(e)) from e


# -----------------------------------------------------------------------------
# export_project
# -----------------------------------------------------------------------------


@export.command("project")
@click.argument("project_folder", type=str)
@click.option(
    "--texfile",
    default=None,
    help="Nombre del .tex del proyecto (default: <project_folder>.tex).",
)
@click.option(
    "--overwrite",
    is_flag=True,
    help="Sobrescribir export si ya existe (legacy preguntaba; aquí es flag).",
)
@click.pass_context
def cmd_export_project(
    ctx: click.Context, project_folder: str, texfile: Optional[str], overwrite: bool
) -> None:
    """
    Exporta un proyecto reemplazando \\transclude[...]{} con el contenido de notas,
    guardando en projects/<project_folder>/standalone/<texfile>.
    """
    c: CLIContext = ctx.obj
    try:
        res = export_project(
            project_folder=project_folder,
            texfile=texfile,
            paths=c.settings.paths,
            overwrite=overwrite,
        )
        click.echo(f"OK: exportado {res.output_file}")
    except DomainError as e:
        raise click.ClickException(str(e)) from e


# -----------------------------------------------------------------------------
# export_draft
# -----------------------------------------------------------------------------


@export.command("draft")
@click.argument(
    "input_file",
    type=click.Path(exists=True, dir_okay=False, file_okay=True, path_type=str),
)
@click.option(
    "--output-file",
    default=None,
    type=click.Path(dir_okay=False, file_okay=True, path_type=str),
    help="Ruta de salida. Por defecto: draft/<basename(input_file)>.",
)
@click.option(
    "--overwrite",
    is_flag=True,
    help="Sobrescribir output si ya existe.",
)
@click.pass_context
def cmd_export_draft(
    ctx: click.Context, input_file: str, output_file: Optional[str], overwrite: bool
) -> None:
    """
    Exporta un draft reemplazando \\ExecuteMetaData[../<import_file>]{tag} por el bloque %<*tag>...%</tag>.
    """
    c: CLIContext = ctx.obj
    try:
        res = export_draft(
            input_file=Path(input_file),
            output_file=None if output_file is None else Path(output_file),
            paths=c.settings.paths,
            overwrite=overwrite,
        )
        click.echo(f"OK: exportado {res.output_file}")
    except DomainError as e:
        raise click.ClickException(str(e)) from e
