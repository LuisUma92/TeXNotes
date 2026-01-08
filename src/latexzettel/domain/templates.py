# src/latexzettel/domain/templates.py
"""
Collection of basic tex and md files contents to recrate

- To do:
    - Incorporate appdirs
    - Use user/config/latexzettel/templates/ as repo for templates
"""

from pathlib import Path


def min_tex_file(f: Path):
    msn = "\\documentclass{../template/texnote}\n"
    msn += "\\begin{document}\n\\end{document}"
    f.write_text(
        msn,
        encoding="utf-8",
    )
