# src/latexzettel/api/workflows.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from latexzettel.config.settings import NotesPaths, DEFAULT_SETTINGS
from latexzettel.domain.errors import NoteNotFound
from latexzettel.infra.fs import rglob_files
from latexzettel.infra.processes import ProcessResult, open_with_system


@dataclass(frozen=True)
class RecentNote:
    """
    Representa una nota reciente basada en mtime del archivo .tex en slipbox.
    """

    filename: str  # sin extensión
    path: Path  # path absoluto al .tex
    mtime: float  # epoch seconds (stat().st_mtime)


def list_recent_notes(
    *,
    paths: NotesPaths = DEFAULT_SETTINGS.paths,
    n: int = 10,
) -> list[RecentNote]:
    """
    Lista las N notas más recientemente modificadas en notes/slipbox.

    Equivalente funcional a Helper.list_recent_files(n) + Helper.__get_recent_files(n),
    pero sin prints y retornando estructura rica.

    - Ordena por mtime descendente.
    - Si hay empates de mtime, ordena por filename ascendente para estabilidad.
    - Incluye solo archivos .tex.
    """
    if n <= 0:
        return []

    slipbox_dir = paths.abs(paths.slipbox_dir)
    tex_files = rglob_files(slipbox_dir, suffix=".tex", exclude_dotfiles=True)

    recent: list[RecentNote] = []
    for p in tex_files:
        try:
            st = p.stat()
        except FileNotFoundError:
            # carrera: archivo desapareció entre rglob y stat
            continue
        recent.append(
            RecentNote(
                filename=p.stem,
                path=p.resolve(),
                mtime=float(st.st_mtime),
            )
        )

    # mtime desc, filename asc (estable)
    recent.sort(key=lambda x: (-x.mtime, x.filename))

    return recent[:n]


def get_recent_note(
    *,
    paths: NotesPaths,
    n: int = 1,
) -> RecentNote:
    """
    Retorna la n-ésima nota más reciente (1-indexado).

    Equivalente funcional al uso interno de Helper.rename_recent(n) en manage.py,
    pero sin interacción ni efectos secundarios.

    Parámetros:
    - n: 1 = más reciente, 2 = segunda más reciente, etc.

    Lanza:
    - NoteNotFound si no existen suficientes notas .tex en slipbox.
    """
    if n <= 0:
        raise ValueError("n debe ser >= 1")

    recent = list_recent_notes(paths=paths, n=n)

    if len(recent) < n:
        raise NoteNotFound(f"No existen {n} notas recientes en {paths.slipbox_dir}")

    return recent[n - 1]


def open_note_in_editor(
    *,
    filename: Optional[str] = None,
    paths: NotesPaths = DEFAULT_SETTINGS.paths,
    open_command: str = DEFAULT_SETTINGS.platform.open_command,
) -> ProcessResult:
    """
    Abre una nota usando el comando del sistema (xdg-open/open/start).

    Replica la semántica de Helper.edit() en manage.py:
    - Si filename es None, abre la nota más reciente.
    - Si filename se proporciona, abre notes/slipbox/<filename>.tex.

    Nota de arquitectura:
    - Aunque esto es "workflow/UX", es útil como primitiva reutilizable desde CLI.
      Si prefieres mantenerlo fuera de api/*, muévelo a cli/* directamente.

    Retorna:
    - ProcessResult (stdout/stderr/returncode) del comando de apertura.
    """
    if filename is None:
        # import local para evitar ciclos

        recent = get_recent_note(paths=paths, n=1)
        target = recent.path
    else:
        target = paths.abs(paths.slipbox_dir / f"{filename}.tex")

    if not target.exists():
        raise NoteNotFound(f"No existe la nota: {target}")

    # En Windows, `start` suele requerir shell=True, pero manage.py lo invoca como subprocess.call.
    # Aquí mantenemos el mismo enfoque (args directos). Si necesitas soporte Windows robusto,
    # conviene implementar un wrapper específico en infra/processes.py.
    return open_with_system(open_command=open_command, target=target)
