# src/latexzettel/util/io.py
"""
Utilidades de I/O interactivo para consola.

Objetivo:
- Centralizar prompts y confirmaciones (y/n), selección de opciones y lectura segura.
- Evitar `input()` disperso en API/infra.
- Este módulo NO debe ser importado por `latexzettel.api.*` (para mantener el API
  no-interactivo). Úsalo desde `latexzettel.cli.*` o desde scripts interactivos.

Diseño:
- Funciones pequeñas, determinísticas y con validación.
- Parametrizables (input_fn/print_fn) para facilitar tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Sequence, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class IO:
    """
    Abstracción simple para inyectar dependencias en tests.
    Por defecto usa input/print nativos.
    """

    input_fn: Callable[[str], str] = input
    print_fn: Callable[..., None] = print

    def ask(self, prompt: str) -> str:
        return self.input_fn(prompt)

    def say(self, *args, **kwargs) -> None:
        self.print_fn(*args, **kwargs)


def confirm(
    prompt: str,
    *,
    default: Optional[bool] = None,
    io: IO = IO(),
) -> bool:
    """
    Pregunta una confirmación y/n.

    - default=True  -> Enter => sí
    - default=False -> Enter => no
    - default=None  -> Enter => repregunta

    Ejemplos:
      confirm("¿Continuar?", default=False)
      confirm("Delete file?", default=None)
    """
    if default is True:
        suffix = " [Y/n]: "
    elif default is False:
        suffix = " [y/N]: "
    else:
        suffix = " [y/n]: "

    while True:
        ans = io.ask(prompt + suffix).strip().lower()
        if ans == "" and default is not None:
            return default
        if ans in {"y", "yes", "s", "si", "sí"}:
            return True
        if ans in {"n", "no"}:
            return False
        io.say("Por favor responda 'y' o 'n'.")


def ask_text(
    prompt: str,
    *,
    default: Optional[str] = None,
    allow_empty: bool = False,
    strip: bool = True,
    io: IO = IO(),
) -> str:
    """
    Lee texto del usuario.

    - Si default está definido, Enter devuelve default.
    - Si allow_empty=False, repregunta si queda vacío.
    """
    if default is not None:
        full_prompt = f"{prompt} [{default}]: "
    else:
        full_prompt = f"{prompt}: "

    while True:
        s = io.ask(full_prompt)
        if strip:
            s = s.strip()

        if s == "" and default is not None:
            return default

        if s == "" and not allow_empty:
            io.say("Entrada vacía. Intente de nuevo.")
            continue

        return s


def choose_one(
    prompt: str,
    options: Sequence[str],
    *,
    default_index: Optional[int] = None,
    io: IO = IO(),
) -> int:
    """
    Permite escoger una opción de una lista (retorna el índice 0-based).

    - Muestra la lista enumerada 1..N
    - Permite ingresar número
    - default_index: si se presiona Enter, se usa el default
    """
    if not options:
        raise ValueError("options no puede ser vacío")

    io.say(prompt)
    for i, opt in enumerate(options, start=1):
        io.say(f"  {i}) {opt}")

    if default_index is not None:
        if not (0 <= default_index < len(options)):
            raise ValueError("default_index fuera de rango")

    while True:
        if default_index is None:
            ans = io.ask("Seleccione un número: ").strip()
        else:
            ans = io.ask(f"Seleccione un número [{default_index + 1}]: ").strip()

        if ans == "" and default_index is not None:
            return default_index

        try:
            n = int(ans)
        except ValueError:
            io.say("Entrada inválida. Ingrese un número.")
            continue

        if 1 <= n <= len(options):
            return n - 1

        io.say(f"Fuera de rango. Ingrese un número entre 1 y {len(options)}.")


def choose_many(
    prompt: str,
    options: Sequence[str],
    *,
    default: Optional[Sequence[int]] = None,
    io: IO = IO(),
) -> list[int]:
    """
    Permite escoger múltiples opciones ingresando números separados por coma.

    - Retorna lista de índices 0-based, ordenados, sin duplicados.
    - default: lista de índices por defecto si Enter.
    """
    if not options:
        raise ValueError("options no puede ser vacío")

    if default is not None:
        for i in default:
            if i < 0 or i >= len(options):
                raise ValueError("default contiene índices fuera de rango")

    io.say(prompt)
    for i, opt in enumerate(options, start=1):
        io.say(f"  {i}) {opt}")

    if default is None:
        default_hint = ""
    else:
        default_hint = " [" + ",".join(str(i + 1) for i in default) + "]"

    while True:
        ans = io.ask(f"Seleccione números separados por coma{default_hint}: ").strip()
        if ans == "" and default is not None:
            return sorted(set(default))

        parts = [p.strip() for p in ans.split(",") if p.strip() != ""]
        if not parts:
            io.say("Entrada vacía. Intente de nuevo.")
            continue

        try:
            nums = [int(p) for p in parts]
        except ValueError:
            io.say("Entrada inválida. Use números separados por coma.")
            continue

        if any(n < 1 or n > len(options) for n in nums):
            io.say(f"Fuera de rango. Use números entre 1 y {len(options)}.")
            continue

        return sorted(set(n - 1 for n in nums))


def warn_and_confirm(
    warning: str,
    prompt: str = "¿Desea continuar?",
    *,
    default: Optional[bool] = False,
    io: IO = IO(),
) -> bool:
    """
    Muestra una advertencia y solicita confirmación.
    Útil para operaciones destructivas.
    """
    io.say(warning)
    return confirm(prompt, default=default, io=io)
