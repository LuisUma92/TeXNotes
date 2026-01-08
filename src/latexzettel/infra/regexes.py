# src/latexzettel/infra/regexes.py
"""
Regexes centralizados para LatexZettel.

Este módulo extrae y formaliza los patrones regex que aparecen repetidamente en
manage.py, particularmente para:

- documents.tex: \\externaldocument[REF-]{filename} :contentReference[oaicite:0]{index=0}
- labels: \\label{...} y \\currentdoc{...} :contentReference[oaicite:1]{index=1}
- links: \\excref / \\exhyperref con label opcional :contentReference[oaicite:2]{index=2}
- wiki links en markdown para sync_md ([[...]], [[...#label]], [[...|text]], ...) :contentReference[oaicite:3]{index=3}
- citations (lista extensa de comandos biblatex) :contentReference[oaicite:4]{index=4}
- transclude/ExecuteMetaData para exportación :contentReference[oaicite:5]{index=5}

Reglas:
- Este módulo NO hace I/O.
- Solo define patrones y helpers de compilación.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Pattern


# =============================================================================
# documents.tex
# =============================================================================

# Coincide con: \externaldocument[Ref-]{filename}
# Grupos:
#  1: "\externaldocument["
#  2: reference (sin el "-")
#  3: "-]{"
#  4: filename
#  5: "}"
EXTERNALDOCUMENT_RE: Pattern[str] = re.compile(
    r"(\\externaldocument\[)(.+?)(\-\]\{)(.+?)(\})"
)


# Variante usada en remove_note: captura filename exacto en la línea.
# Se recomienda construir dinámicamente con re.escape(filename).
def externaldocument_line_re(filename: str) -> Pattern[str]:
    return re.compile(
        rf"(\\externaldocument\[)(.+?)(\-\]\{{){re.escape(filename)}(\}})"
    )


def externaldocument_exact_re(reference: str, filename: str) -> Pattern[str]:
    """
    Regex exacta para encontrar la línea de documents.tex que referencia a (reference, filename).
    Útil para renombrar filename o reference sin falsos positivos.
    """
    return re.compile(
        rf"\\externaldocument\[{re.escape(reference)}\-\]\{{{re.escape(filename)}\}}"
    )


# =============================================================================
# Labels en LaTeX
# =============================================================================

# Coincide con \label{...} o \currentdoc{...}
# Grupo 3: contenido del label
LABEL_OR_CURRENTDOC_RE: Pattern[str] = re.compile(r"(\\(label|currentdoc)\{)(.*?)(\})")

# =============================================================================
# Enlaces LaTeX (excref/exhyperref)
# =============================================================================

# Coincide con:
#   \excref{Ref}
#   \excref[label]{Ref}
#   \exhyperref{Ref}{Texto}  (nota: el texto se maneja aparte en algunos flujos)
# En manage.py se usan variantes con (hyper)? (c)? y label opcional.
EX_REF_RE: Pattern[str] = re.compile(r"\\ex(hyper)?(c)?ref(\[([^]]+)\])?\{(.*?)\}")

# Variante usada en to_md() donde también puede existir un segundo {...} (texto ancla).
EX_REF_WITH_TEXT_RE: Pattern[str] = re.compile(
    r"\\ex(hyper)?(c)?ref(\[([^]]+)\])?\{(.*?)\}(\{(.*?)\})?"
)

# =============================================================================
# Citations (biblatex)
# =============================================================================

BIBLATEX_CITATION_COMMANDS: tuple[str, ...] = (
    "cite",
    "parencite",
    "footcite",
    "footcitetext",
    "textcite",
    "smartcite",
    "cite*",
    "parencite*",
    "supercite",
    "autocite",
    "autocite*",
    "citeauthor",
    "citeauthor*",
    "citetitle",
    "citeyear",
    "citedate",
    "citeurl",
    "volcite",
    "pvolcite",
    "fvolcite",
    "ftvolcite",
    "svolcite",
    "tvolcite",
    "avolcite",
    "fillcite",
    "footfullcite",
    "nocite",
    "notecite",
    "pnotecite",
    "fnotecite",
)

# Coincide con comandos biblatex (según tu lista en manage.py) y extrae la clave final.
# Grupos relevantes:
#  7: citation key
CITATION_RE: Pattern[str] = re.compile(
    r"\\("
    + "|".join(re.escape(c) for c in BIBLATEX_CITATION_COMMANDS)
    + r")(\[([^]]+)\])?(\{[^\}]+\})?(\[([^]]+)\])?\{([^\}]+)\}"
)


# =============================================================================
# Wiki links (markdown) para sync_md
# =============================================================================

# [[Note Name]]
WIKILINK_NOTE_RE: Pattern[str] = re.compile(r"\[\[([^{\#\]\|}]+)\]\]")

# [[Note Name#label]] o [[Note Name#^block]]
WIKILINK_NOTE_LABEL_RE: Pattern[str] = re.compile(r"\[\[([^{\#\]\|}]+)\#\^?([^]]+)\]\]")

# [[Note Name|Texto]]
WIKILINK_NOTE_TEXT_RE: Pattern[str] = re.compile(r"\[\[([^{\#\]\|}]+)\|([^]]+)\]\]")

# [[Note Name#label|Texto]] o [[Note Name#^block|Texto]]
WIKILINK_NOTE_LABEL_TEXT_RE: Pattern[str] = re.compile(
    r"\[\[([^{\#\]\|}]+)\#\^?([^]]+)\|([^]]+)\]\]"
)


# =============================================================================
# Exportación (transclude / ExecuteMetaData)
# =============================================================================

# \transclude{note} o \transclude[tag]{note}
TRANSCLUDE_RE: Pattern[str] = re.compile(r"\\transclude(\[([^]]+)\])?\{([^}]+)\}")

# \ExecuteMetaData[../path]{tag}
EXECUTE_METADATA_RE: Pattern[str] = re.compile(
    r"\\ExecuteMetaData\[\.\./([^]]+)\]\{([^}]+)\}"
)


# Bloques de metadata:
# %<*tag> ... %</tag>
def metadata_block_re(tag: str) -> Pattern[str]:
    return re.compile(rf"%<\\*{re.escape(tag)}>((.|\n)*?)%</{re.escape(tag)}>")


# =============================================================================
# Helpers: compilación/constructor
# =============================================================================


def exref_for_reference(old_reference: str) -> Pattern[str]:
    """
    Regex para reemplazar solo referencias a una referencia específica:
      \\ex(hyper)?(c)?ref([label])?{old_reference}
    Usada para rename_reference.
    """
    return re.compile(
        rf"\\ex(hyper)?(c)?ref(\[([^]]+)\])?\{{{re.escape(old_reference)}\}}"
    )
