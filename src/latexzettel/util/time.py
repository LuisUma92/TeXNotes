# src/latexzettel/util/time.py
"""
Utilidades de tiempo y fechas.

Este módulo encapsula toda la lógica temporal que aparece dispersa en
manage.py, con los siguientes objetivos:

- Centralizar el manejo de datetime/mtime.
- Evitar llamadas directas repetidas a datetime.datetime.now().
- Facilitar tests (inyectando "now").
- Mantener semántica idéntica a la usada en manage.py original.

NO hace I/O.
NO depende de peewee.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Tiempo actual
# ---------------------------------------------------------------------------


def now() -> datetime:
    """
    Retorna el tiempo actual (datetime naive, local),
    consistente con el uso en manage.py.
    """
    return datetime.now()


# ---------------------------------------------------------------------------
# Conversión desde filesystem
# ---------------------------------------------------------------------------


def mtime_to_datetime(mtime: float) -> datetime:
    """
    Convierte un mtime (segundos desde epoch) a datetime.
    """
    return datetime.fromtimestamp(mtime)


def file_mtime(path: Path) -> datetime:
    """
    Obtiene la fecha de última modificación de un archivo como datetime.

    Lanza FileNotFoundError si el archivo no existe.
    """
    return mtime_to_datetime(os.path.getmtime(path))


# ---------------------------------------------------------------------------
# Comparaciones temporales
# ---------------------------------------------------------------------------


def is_newer(
    *,
    file_time: datetime,
    reference_time: Optional[datetime],
) -> bool:
    """
    Determina si file_time es más reciente que reference_time.

    - Si reference_time es None, retorna True.
    - Replica exactamente la lógica usada en manage.py para decidir
      si una nota debe ser re-procesada o re-renderizada.
    """
    if reference_time is None:
        return True
    return file_time > reference_time


# ---------------------------------------------------------------------------
# Helpers de alto nivel (usados en sync/render)
# ---------------------------------------------------------------------------


def needs_update(
    *,
    file_path: Path,
    last_edit_date: Optional[datetime],
) -> bool:
    """
    Determina si un archivo necesita ser leído/procesado nuevamente
    comparando su mtime con la fecha almacenada en DB.

    Equivalente al patrón repetido en manage.py:

        modified = os.path.getmtime(file)
        if datetime.fromtimestamp(modified) > note.last_edit_date:
            ...
    """
    file_time = file_mtime(file_path)
    return is_newer(file_time=file_time, reference_time=last_edit_date)


def needs_render(
    *,
    last_edit_date: Optional[datetime],
    last_build_date: Optional[datetime],
) -> bool:
    """
    Determina si un artefacto (PDF/HTML) debe regenerarse.

    Lógica equivalente a la usada en:
      - render_updates()
      - render_all_pdf/html()

    Retorna True si:
    - nunca se ha renderizado, o
    - el archivo fue editado después del último render.
    """
    if last_build_date is None:
        return True
    if last_edit_date is None:
        return True
    return last_edit_date > last_build_date


# ---------------------------------------------------------------------------
# Utilidad defensiva
# ---------------------------------------------------------------------------


def safe_now(fallback: Optional[datetime] = None) -> datetime:
    """
    Retorna datetime.now(), o un fallback si ocurre algún error inesperado.
    Útil en contextos muy defensivos (migraciones, recovery).
    """
    try:
        return now()
    except Exception:
        return fallback if fallback is not None else datetime.now()
