# src/latexzettel/infra/processes.py
"""
Capa de infraestructura para ejecución de procesos externos (subprocess).

Este módulo encapsula los patrones usados en manage.py:
- pandoc (sync_md, to_md) :contentReference[oaicite:0]{index=0}
- pdflatex / make4ht (render) :contentReference[oaicite:1]{index=1}
- biber :contentReference[oaicite:2]{index=2}
- OPEN_COMMAND / abrir editor/visor :contentReference[oaicite:3]{index=3}

Reglas:
- No depende de Click.
- No imprime.
- No modifica DB.
- Devuelve resultados estructurados y, cuando corresponde, lanza excepciones de dominio.

Nota: Puedes mapear estas excepciones a click.ClickException en la capa cli/*.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

import subprocess


# =============================================================================
# Errores
# =============================================================================


class ProcessError(RuntimeError):
    """Error genérico de ejecución de proceso externo."""


class ProcessNotFound(ProcessError):
    """El ejecutable no existe o no está en PATH."""


class ProcessFailed(ProcessError):
    """El proceso terminó con returncode != 0."""


# =============================================================================
# Resultados
# =============================================================================


@dataclass(frozen=True)
class ProcessResult:
    args: list[str]
    returncode: int
    stdout: bytes
    stderr: bytes

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def stdout_text(self, encoding: str = "utf-8", errors: str = "replace") -> str:
        return self.stdout.decode(encoding, errors=errors)

    def stderr_text(self, encoding: str = "utf-8", errors: str = "replace") -> str:
        return self.stderr.decode(encoding, errors=errors)


# =============================================================================
# Runner genérico
# =============================================================================


def run(
    args: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    input_bytes: Optional[bytes] = None,
    check: bool = False,
    env: Optional[dict[str, str]] = None,
) -> ProcessResult:
    """
    Ejecuta un proceso y retorna stdout/stderr.

    - check=True: lanza ProcessFailed si returncode != 0
    - cwd: directorio de trabajo (Path)
    - input_bytes: stdin (bytes)
    """
    try:
        p = subprocess.run(
            list(args),
            cwd=str(cwd) if cwd is not None else None,
            input=input_bytes,
            capture_output=True,
            env=env,
        )
    except FileNotFoundError as e:
        raise ProcessNotFound(f"No se encontró el ejecutable: {args[0]}") from e

    result = ProcessResult(
        args=list(args),
        returncode=p.returncode,
        stdout=p.stdout,
        stderr=p.stderr,
    )

    if check and not result.ok:
        raise ProcessFailed(
            f"Proceso falló (rc={result.returncode}): {' '.join(result.args)}\n"
            f"stderr:\n{result.stderr_text()}"
        )

    return result


# =============================================================================
# Biber
# =============================================================================


def run_biber(
    filename: str,
    *,
    folder: Path = Path("pdf"),
    check: bool = False,
) -> ProcessResult:
    """
    Ejecuta `biber <filename>` en el folder indicado.

    Equivalente a Helper.biber() en manage.py :contentReference[oaicite:4]{index=4}
    """
    return run(["biber", filename], cwd=folder, check=check)


# =============================================================================
# LaTeX render (pdflatex / make4ht)
# =============================================================================


def run_latex_renderer(
    *,
    command: str,
    options: Sequence[str],
    input_tex: bytes,
    cwd: Path,
    check: bool = False,
) -> ProcessResult:
    """
    Ejecuta un motor LaTeX recibiendo el documento por stdin.

    Equivalente al patrón en Helper.render():
      subprocess.run([command, *options], input=document.encode(), capture_output=True) :contentReference[oaicite:5]{index=5}
    """
    return run([command, *options], cwd=cwd, input_bytes=input_tex, check=check)


# =============================================================================
# Pandoc
# =============================================================================


def run_pandoc(
    *,
    options: Sequence[str],
    input_text: str,
    cwd: Optional[Path] = None,
    check: bool = False,
    encoding: str = "utf-8",
) -> ProcessResult:
    """
    Ejecuta pandoc pasando el texto por stdin.

    Equivalente al patrón en sync_md() / to_md(): :contentReference[oaicite:6]{index=6}
      subprocess.run([command, *options], input=text.encode(), capture_output=True)
    """
    return run(
        ["pandoc", *options],
        cwd=cwd,
        input_bytes=input_text.encode(encoding),
        check=check,
    )


# =============================================================================
# Abrir archivos (xdg-open / open / start)
# =============================================================================


def open_with_system(
    open_command: str,
    target: Path,
    *,
    cwd: Optional[Path] = None,
    check: bool = False,
) -> ProcessResult:
    """
    Abre un archivo con el comando del sistema.

    En manage.py OPEN_COMMAND se decide por platform.system(): :contentReference[oaicite:7]{index=7}
    """
    return run([open_command, str(target)], cwd=cwd, check=check)


# =============================================================================
# Utilidades específicas del flujo (helpers de composición)
# =============================================================================


def ensure_dir(path: Path) -> None:
    """
    Helper local para procesos que requieren cwd existente.
    (Si ya usas infra/fs.ensure_dir, puedes eliminar esto y reutilizarlo.)
    """
    path.mkdir(parents=True, exist_ok=True)
