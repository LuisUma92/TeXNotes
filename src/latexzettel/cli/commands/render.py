# src/latexzettel/cli/commands/render.py
from __future__ import annotations

from dataclasses import asdict
from typing import Optional

import click

from latexzettel.cli.context import CLIContext
from latexzettel.domain.errors import DomainError
from latexzettel.domain.types import RenderFormat
from latexzettel.api.render import (
    render_note,
    render_updates,
    render_all,
    biber as api_biber,
)


def register(root: click.Group) -> None:
    root.add_command(render)


@click.group()
@click.pass_context
def render(ctx: click.Context) -> None:
    """Renderizado (pdf/html), biber y render incremental."""
    _ = ctx


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _parse_format(fmt: str) -> RenderFormat:
    fmt = fmt.lower().strip()
    if fmt == "pdf":
        return RenderFormat.PDF
    if fmt == "html":
        return RenderFormat.HTML
    raise click.BadParameter("format debe ser 'pdf' o 'html'")


# -----------------------------------------------------------------------------
# render note
# -----------------------------------------------------------------------------


@render.command("note")
@click.argument("filename", type=str)
@click.option(
    "--format",
    "fmt",
    default="pdf",
    show_default=True,
    type=click.Choice(["pdf", "html"], case_sensitive=False),
    help="Formato de salida.",
)
@click.option(
    "--biber",
    "run_biber",
    is_flag=True,
    help="Ejecutar biber (render -> biber -> render).",
)
@click.option(
    "--check/--no-check",
    default=False,
    show_default=True,
    help="Fallar (raise) si el renderer falla.",
)
@click.pass_context
def cmd_render_note(
    ctx: click.Context,
    filename: str,
    fmt: str,
    run_biber: bool,
    check: bool,
) -> None:
    """Renderiza una nota específica."""
    c: CLIContext = ctx.obj
    try:
        res = render_note(
            db=c.db,
            filename=filename,
            format=_parse_format(fmt),
            run_biber=run_biber,
            settings=c.settings.render,
            paths=c.settings.paths,
            check=check,
        )
        if res.ok:
            click.echo(f"OK: render {filename} ({fmt})")
        else:
            # rc != 0 y check=False
            raise click.ClickException(res.stderr_text())
    except DomainError as e:
        raise click.ClickException(str(e)) from e


# -----------------------------------------------------------------------------
# biber
# -----------------------------------------------------------------------------


@render.command("biber")
@click.argument("filename", type=str)
@click.option(
    "--folder",
    type=click.Path(file_okay=False, dir_okay=True, path_type=str),
    default=None,
    help="Carpeta donde está el artefacto (por defecto pdf/ o html/ según --format).",
)
@click.option(
    "--format",
    "fmt",
    default="pdf",
    show_default=True,
    type=click.Choice(["pdf", "html"], case_sensitive=False),
    help="Formato para seleccionar carpeta por defecto.",
)
@click.option(
    "--check/--no-check",
    default=False,
    show_default=True,
    help="Fallar si biber falla.",
)
@click.pass_context
def cmd_biber(
    ctx: click.Context, filename: str, folder: Optional[str], fmt: str, check: bool
) -> None:
    """Ejecuta biber para una nota."""
    from pathlib import Path

    c: CLIContext = ctx.obj
    try:
        if folder is None:
            out_dir = c.settings.paths.abs(
                c.settings.paths.pdf_dir
                if _parse_format(fmt) == RenderFormat.PDF
                else c.settings.paths.html_dir
            )
        else:
            out_dir = Path(folder).resolve()

        proc = api_biber(filename=filename, folder=out_dir, check=check)
        if proc.returncode == 0:
            click.echo(f"OK: biber {filename} ({out_dir})")
        else:
            raise click.ClickException(proc.stderr_text())
    except DomainError as e:
        raise click.ClickException(str(e)) from e


# -----------------------------------------------------------------------------
# render all
# -----------------------------------------------------------------------------


@render.command("all")
@click.option(
    "--format",
    "fmt",
    default="pdf",
    show_default=True,
    type=click.Choice(["pdf", "html"], case_sensitive=False),
    help="Formato de salida.",
)
@click.option(
    "--biber/--no-biber",
    "run_biber_each",
    default=True,
    show_default=True,
    help="Ejecutar biber por nota durante la primera pasada (como legacy).",
)
@click.option(
    "--check/--no-check",
    default=False,
    show_default=True,
    help="Fallar si una nota falla.",
)
@click.pass_context
def cmd_render_all(
    ctx: click.Context, fmt: str, run_biber_each: bool, check: bool
) -> None:
    """Renderiza todas las notas (dos pasadas)."""
    c: CLIContext = ctx.obj
    try:
        results = render_all(
            db=c.db,
            format=_parse_format(fmt),
            settings=c.settings.render,
            paths=c.settings.paths,
            run_biber_each=run_biber_each,
            check=check,
        )

        ok = sum(1 for r in results if r.ok)
        fail = len(results) - ok

        click.echo(f"Render all ({fmt}): ok={ok}, fail={fail}")

        if fail > 0:
            # Mostrar fallos resumidos
            for r in results:
                if not r.ok:
                    click.echo(f"FAIL: {r.filename} rc={r.returncode}", err=True)
    except DomainError as e:
        raise click.ClickException(str(e)) from e


# -----------------------------------------------------------------------------
# render updates (incremental)
# -----------------------------------------------------------------------------


@render.command("updates")
@click.option(
    "--format",
    "fmt",
    default="pdf",
    show_default=True,
    type=click.Choice(["pdf", "html"], case_sensitive=False),
    help="Formato de salida.",
)
@click.option(
    "--check/--no-check",
    default=False,
    show_default=True,
    help="Fallar si el renderer falla.",
)
@click.pass_context
def cmd_render_updates(ctx: click.Context, fmt: str, check: bool) -> None:
    """
    Render incremental:
    - sincroniza DB (labels/citations/links)
    - renderiza lo modificado o desactualizado
    - re-renderiza targets y sources afectados por nuevos links
    """
    c: CLIContext = ctx.obj
    try:
        res = render_updates(
            db=c.db,
            format=_parse_format(fmt),
            settings=c.settings.render,
            paths=c.settings.paths,
            check=check,
        )

        click.echo(f"Rendered: {len(res.rendered)}")
        for fn in res.rendered:
            click.echo(f"  {fn}")

        click.echo(f"Re-render targets: {len(res.rerendered_targets)}")
        for fn in res.rerendered_targets:
            click.echo(f"  {fn}")

        click.echo(f"Re-render sources: {len(res.rerendered_sources)}")
        for fn in res.rerendered_sources:
            click.echo(f"  {fn}")

    except DomainError as e:
        raise click.ClickException(str(e)) from e
