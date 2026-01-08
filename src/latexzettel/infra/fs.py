# src/latexzettel/infra/fs.py
"""
Capa de infraestructura para operaciones de filesystem.

Este módulo encapsula patrones presentes en:
- LatexZettel/files.py (rglob filtrando dotfiles) :contentReference[oaicite:0]{index=0}
- manage.py (creación de carpetas, paths, mtime, etc.) :contentReference[oaicite:1]{index=1}

Reglas:
- Puede hacer I/O (leer/escribir archivos, mkdir, etc.).
- No debe depender de Click.
- Idealmente no depende de Peewee (solo opera sobre paths/strings).
- Mantiene funciones pequeñas y testeables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence


# =============================================================================
# Rutas / entorno
# =============================================================================


@dataclass(frozen=True)
class ProjectLayout:
    """
    Estructura de carpetas del repositorio, equivalente a la asumida en manage.py.
    """

    root: Path = Path(".")

    notes_dir: Path = Path("notes")
    slipbox_dir: Path = Path("notes/slipbox")
    md_dir: Path = Path("notes/md")
    documents_tex: Path = Path("notes/documents.tex")

    template_dir: Path = Path("template")
    projects_dir: Path = Path("projects")
    draft_dir: Path = Path("draft")

    pdf_dir: Path = Path("pdf")
    html_dir: Path = Path("html")

    def abs(self, path: Path) -> Path:
        return (self.root / path).resolve()


# =============================================================================
# Enumeración / descubrimiento de archivos (equivalente a LatexZettel/files.py)
# =============================================================================


def rglob_files(
    dir_path: Path | str,
    *,
    suffix: str = "",
    exclude_dotfiles: bool = True,
) -> list[Path]:
    """
    Recorre recursivamente dir_path y retorna una lista de Paths.

    - suffix: "" o ".tex" o "md" (se acepta ambos estilos).
      Mantiene compatibilidad con `files.get_files(dir_name, extension)` :contentReference[oaicite:2]{index=2}
    - exclude_dotfiles: filtra cualquier path que contenga "/." (dotfiles y carpetas ocultas).

    Nota: en files.py se usa rglob(f"*{extension}") y luego se filtra '/.' :contentReference[oaicite:3]{index=3}
    """
    base = Path(dir_path)
    if not base.exists():
        return []

    # Normaliza suffix
    if suffix and not suffix.startswith(".") and "/" not in suffix:
        # Si el usuario pasa "tex" o "md", interpretarlo como ".tex" o ".md"
        # En tu files.py se pasa ".tex" o "md" indistintamente en manage.py.
        suffix = f".{suffix}"

    files = list(base.rglob(f"*{suffix}")) if suffix else list(base.rglob("*"))
    if exclude_dotfiles:
        files = [p for p in files if "/." not in str(p)]
    return files


def list_note_tex_files(layout: ProjectLayout = ProjectLayout()) -> list[Path]:
    """
    Equivalente a Helper.__getnotefiles() en manage.py:
      notes/slipbox/*.tex (recursivo) :contentReference[oaicite:5]{index=5}
    """
    return rglob_files(layout.abs(layout.slipbox_dir), suffix=".tex")


def list_note_md_files(layout: ProjectLayout = ProjectLayout()) -> list[Path]:
    """
    Lista notas markdown en notes/md (recursivo).
    """
    return rglob_files(layout.abs(layout.md_dir), suffix=".md")


# =============================================================================
# Directorios / creación segura
# =============================================================================


def ensure_dir(path: Path) -> Path:
    """
    Crea el directorio si no existe (equivalente repetido de os.mkdir con try/except).
    Retorna el Path.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_layout(layout: ProjectLayout, *, ensure_render_dirs: bool = False) -> None:
    """
    Garantiza la existencia de directorios base usados por el proyecto.
    NO crea archivos (solo carpetas).
    """
    ensure_dir(layout.abs(layout.notes_dir))
    ensure_dir(layout.abs(layout.slipbox_dir))
    ensure_dir(layout.abs(layout.template_dir))
    ensure_dir(layout.abs(layout.projects_dir))

    if ensure_render_dirs:
        ensure_dir(layout.abs(layout.pdf_dir))
        ensure_dir(layout.abs(layout.html_dir))


# =============================================================================
# Tiempo de modificación / metadatos
# =============================================================================


def mtime(path: Path) -> float:
    """
    Retorna mtime (float epoch seconds). Lanza FileNotFoundError si no existe.
    """
    return os.path.getmtime(path)


def exists(path: Path) -> bool:
    return path.exists()


# =============================================================================
# Helpers específicos del flujo actual
# =============================================================================


def slipbox_tex_path(filename: str, layout: ProjectLayout = ProjectLayout()) -> Path:
    """
    notes/slipbox/<filename>.tex
    """
    return layout.abs(layout.slipbox_dir / f"{filename}.tex")


def documents_tex_path(layout: ProjectLayout = ProjectLayout()) -> Path:
    """
    notes/documents.tex
    """
    return layout.abs(layout.documents_tex)


def ensure_documents_tex(
    layout: ProjectLayout = ProjectLayout(), *, create: bool = True
) -> Path:
    """
    Garantiza que notes/documents.tex exista.

    - Si create=True y no existe, lo crea vacío.
    - Si create=False y no existe, lanza FileNotFoundError.
    """
    doc = documents_tex_path(layout)
    ensure_dir(doc.parent)
    if not doc.exists():
        if create:
            doc.write_text("", encoding="utf-8")
        else:
            raise FileNotFoundError(str(doc))
    return doc


def append_line(path: Path, line: str, *, encoding: str = "utf-8") -> None:
    """
    Appendea una línea asegurando que termine con '\n'.
    """
    if not line.endswith("\n"):
        line = line + "\n"
    with path.open("a", encoding=encoding) as f:
        f.write(line)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """
    Escritura atómica: escribe a un archivo temporal y luego hace replace.
    Útil para actualizar documents.tex o notas sin riesgo de truncado a medias.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding))


# =============================================================================
# Funcionalidades heredadas de files.get_rendered_dates (opcional)
# =============================================================================


def rendered_artifact_path(
    note_tex_path: Path,
    *,
    artifact_ext: str = "pdf",
    artifact_root: Path | str = "pdf",
) -> Path:
    """
    Replica el mapeo de LatexZettel/files.py.get_rendered_dates(): :contentReference[oaicite:6]{index=6}
      notes/<subpath>.tex  ->  <artifact_root>/<subpath>.<artifact_ext>

    Nota:
    - En files.py se arma como:
        files = get_files('notes', '.tex')
        files = [f'{str(f)[:-4]}.{extension}' for f in files]
        pdfs = [extension + '/' + 'notes/'.join(str(f).split('notes/')[1:]) for f in files]
    """
    note_tex_path = Path(note_tex_path)
    artifact_root = Path(artifact_root)

    s = str(note_tex_path)
    if "notes/" not in s:
        # Si no es un path dentro de notes/, degradamos: mismo nombre en artifact_root
        return artifact_root / f"{note_tex_path.stem}.{artifact_ext}"

    rel_after_notes = s.split("notes/")[1]
    base_no_ext = (
        rel_after_notes[:-4]
        if rel_after_notes.endswith(".tex")
        else str(Path(rel_after_notes).with_suffix(""))
    )
    return artifact_root / f"{base_no_ext}.{artifact_ext}"


def get_rendered_mtimes(
    *,
    note_tex_files: Optional[Sequence[Path]] = None,
    artifact_ext: str = "pdf",
    artifact_root: Path | str = "pdf",
    exclude_missing: bool = True,
) -> dict[str, float]:
    """
    Devuelve un dict {artifact_path_str: mtime} similar al print(dates) en files.py.get_rendered_dates(). :contentReference[oaicite:7]{index=7}

    - note_tex_files: si None, lista notes/**/*.tex (recursivo) tal como files.py.
    - exclude_missing: si True, ignora artefactos que no existen en disco.
    """
    if note_tex_files is None:
        note_tex_files = rglob_files("notes", suffix=".tex")

    out: dict[str, float] = {}
    for f in note_tex_files:
        art = rendered_artifact_path(
            f, artifact_ext=artifact_ext, artifact_root=artifact_root
        )
        if exclude_missing and not art.exists():
            continue
        out[str(art)] = os.path.getmtime(art)
    return out
