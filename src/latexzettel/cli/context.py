# src/latexzettel/cli/context.py
from __future__ import annotations

from dataclasses import dataclass
from latexzettel.config.settings import Settings


@dataclass(frozen=True)
class CLIContext:
    """
    Contexto compartido entre comandos Click.

    db:
      módulo externo peewee (por modularidad). Debe exponer Note, create_all_tables(), database, etc.
    settings:
      configuración ensamblada (paths, renderers, platform, etc.)
    """

    db: object
    settings: Settings
