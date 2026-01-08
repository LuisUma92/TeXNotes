"""
Text formating
"""

import re
import unicodedata


def default_reference_name(note_name: str) -> str:
    return "".join(w.capitalize() for w in note_name.split("_") if w)


def default_filename(note_name: str) -> str:
    """
    Returns a canonic title form an arbitrary one.
    - lower case
    - no accents
    - just '_' as separator
    - just [a-z0-9_] characters
    """
    if not note_name:
        raise ValueError("Empty note_name")

    text = unicodedata.normalize("NFKD", note_name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = text.strip("_")
    return text
