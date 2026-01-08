"""
File system interactions
"""

from pathlib import Path
from latexzettel.util.templates import render_note_template
from latexzettel.config.settings import NotesPaths
from latexzettel.domain.errors import DocumentsTexNotFound


def ensure_note_dirs(paths: NotesPaths, extension: str) -> Path:
    paths.abs(paths.notes_dir).mkdir(parents=True, exist_ok=True)

    folder = (
        paths.abs(paths.slipbox_dir)
        if extension == "tex"
        else paths.abs(paths.notes_dir / extension)
    )

    folder.mkdir(parents=True, exist_ok=True)
    return folder


def create_note_file(
    paths: NotesPaths,
    *,
    filename: str,
    extension: str,
) -> None:
    folder = ensure_note_dirs(paths, extension)
    out = folder / f"{filename}.{extension}"

    if out.exists():
        return

    title = " ".join(w.capitalize() for w in filename.split("_"))
    template = paths.abs(paths.template_dir / f"note.{extension}")
    out.write_bytes(render_note_template(template, title=title, extension=extension))


def append_documents_entry(
    paths: NotesPaths,
    *,
    filename: str,
    reference: str,
) -> None:
    doc = paths.abs(paths.documents_tex)
    doc.parent.mkdir(parents=True, exist_ok=True)

    if not doc.exists():
        doc.write_text("", encoding="utf-8")

    with doc.open("a", encoding="utf-8") as f:
        f.write(f"\\externaldocument[{reference}-]{{{filename}}}\n")


def ensure_documents_tex(paths: NotesPaths, *, create: bool = True) -> Path:
    doc = paths.abs(paths.documents_tex)
    doc.parent.mkdir(parents=True, exist_ok=True)

    if not doc.exists():
        if create:
            doc.write_text("", encoding="utf-8")
        else:
            raise DocumentsTexNotFound(f"No existe: {doc}")

    return doc
