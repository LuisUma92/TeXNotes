# src/latexzettel/infra/db.py
"""
Capa de infraestructura para base de datos (Peewee).

Este módulo está diseñado para encapsular el patrón que tenías en manage.py:
- “asumir DB existente”, pero si falta (tablas no creadas) inicializarla
  atrapando pw.OperationalError. :contentReference[oaicite:0]{index=0}

Notas:
- No depende de Click.
- Puede ser importado por API y/o CLI.
- La idea recomendada es: el CLI inicializa una vez; el API usa ensure_tables()
  solo cuando quieras robustez ante instalaciones nuevas.

Compatibilidad:
- Espera un módulo `database` tipo el que compartiste antes (LatexZettel/database.py),
  que expone:
    - database (pw.Database)
    - modelos: Note, Label, Link, Citation, Tag
    - create_all_tables() :contentReference[oaicite:1]{index=1}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import peewee as pw

from latexzettel.domain.types import DbModule
from latexzettel.domain.errors import DomainError

# =============================================================================
# Configuración
# =============================================================================


@dataclass(frozen=True)
class DbHealth:
    """
    Estado de salud/inicialización del esquema.

    ok:
      True si el esquema está disponible para operar.
    initialized:
      True si se ejecutó create_all_tables() durante ensure_tables().
    error:
      mensaje de error si ok=False.
    """

    ok: bool
    initialized: bool
    error: Optional[str] = None


# =============================================================================
# API de infraestructura
# =============================================================================


def connect(db: DbModule) -> None:
    """
    Abre conexión si no está abierta.
    Con SQLite y Peewee, es seguro llamar esto repetidamente.
    """
    if db.database.is_closed():
        db.database.connect(reuse_if_open=True)


def close(db: DbModule) -> None:
    """
    Cierra conexión si está abierta.
    """
    if not db.database.is_closed():
        db.database.close()


def schema_exists(db: DbModule) -> bool:
    """
    Verifica si el esquema existe intentando una consulta mínima sobre Note.

    Si la tabla Note no existe, Peewee típicamente lanza OperationalError.
    """
    try:
        # Ejecuta SELECT 1 FROM note LIMIT 1 (aprox)
        _ = db.Note.select().limit(1).execute()
        return True
    except pw.OperationalError:
        return False


def ensure_tables(db: DbModule) -> DbHealth:
    """
    Garantiza que las tablas existan:
    - Si ya existen: no hace nada y retorna initialized=False.
    - Si no existen: crea tablas y retorna initialized=True.

    Este patrón replica el enfoque de manage.py: solo crear si falla. :contentReference[oaicite:2]{index=2}
    """
    try:
        connect(db)

        if schema_exists(db):
            return DbHealth(ok=True, initialized=False)

        # Si falta el esquema (tablas), inicializar
        db.create_all_tables()

        # Re-check
        if schema_exists(db):
            return DbHealth(ok=True, initialized=True)

        return DbHealth(
            ok=False,
            initialized=True,
            error="No se pudo verificar el esquema tras crear tablas.",
        )
    except Exception as e:
        return DbHealth(ok=False, initialized=False, error=str(e))


def ensure_schema_if_needed(db: DbModule) -> None:
    """
    No inicializa “siempre”.
    Solo crea tablas si el primer acceso básico falla por OperationalError
    (típicamente 'no such table').
    """
    try:
        # consulta mínima para disparar ausencia de tabla
        db.Note.select().limit(1).execute()
    except pw.OperationalError:
        health = ensure_tables(db)
        if not health.ok:
            raise DomainError(f"DB no disponible: {health.error}")


# =============================================================================
# Context manager
# =============================================================================


class db_session:
    """
    Context manager para abrir/cerrar conexión de forma explícita.

    Uso:
        from LatexZettel import database as legacy_db
        from latexzettel.infra.db import db_session, ensure_tables

        ensure_tables(legacy_db)
        with db_session(legacy_db) as db:
            ... db.Note.select() ...

    Nota:
    - Cierra la conexión al salir. Si prefieres mantenerla abierta en CLI, no uses este context.
    """

    def __init__(self, db: DbModule):
        self._db = db

    def __enter__(self) -> DbModule:
        connect(self._db)
        return self._db

    def __exit__(self, exc_type, exc, tb) -> bool:
        close(self._db)
        return False
