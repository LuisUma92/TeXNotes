"""
Templates definitions
"""

from pathlib import Path
import re
from latexzettel.domain.errors import TemplateNotFound


def render_note_template(template: Path, *, title: str, extension: str) -> bytes:
    if not template.exists():
        raise TemplateNotFound(f"Plantilla no encontrada: {template}")

    raw = template.read_text(encoding="utf-8")

    if extension == "tex":
        return re.sub(r"\\title\{.*?\}", rf"\\title{{{title}}}", raw).encode("utf-8")

    return raw.replace("Note Title", title).encode("utf-8")
