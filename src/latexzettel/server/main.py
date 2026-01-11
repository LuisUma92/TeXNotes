# src/latexzettel/server/main.py
"""
LatexZettel Server (MVP) - JSONL/NDJSON over stdin/stdout

Objetivo:
- Proceso persistente para ser usado por Neovim (modelo 3).
- Protocolo RPC estable y transport-agnostic (stdio hoy, unix domain socket mañana)
  manteniendo exactamente el mismo framing: 1 JSON por línea + '\n' (JSONL).

Requisitos de protocolo (cumplidos):
- NDJSON estricto: 1 JSON completo por línea; stdout solo datos; stderr solo logs.
- Correlación obligatoria: request incluye id; response devuelve el mismo id.
- Envelope RPC estable:
    Request: { "v": ..., "id": ..., "method": "...", "params": { ... } }
    Response OK: { "v": ..., "id": ..., "ok": true, "result": { ... } }
    Response error: { "v": ..., "id": ..., "ok": false, "error": { "code": "...", "message": "...", "data": { ... } } }
- Versionado desde día 1:
    - v en cada mensaje.
    - Si no coincide -> responder error VERSION_MISMATCH y cerrar.
- Handshake initialize:
    - Primer mensaje recomendado method="initialize".
    - Respuesta incluye capabilities y server_version.
- Cancelación:
    - method="cancel" con params { "id_to_cancel": ... }.
    - Best-effort en MVP: marcamos cancelado; handlers deben consultar el token.
- No asumir cliente único:
    - Cada request debe ser autosuficiente.
    - initialize permite fijar config default de sesión (root/db_module), pero cada request
      puede override con params si se desea.
- Compatible con unix socket:
    - El framing es JSONL; para UDS solo cambia el transporte, no el protocolo ni handlers.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

# API imports (negocio)
from latexzettel.config.settings import DEFAULT_SETTINGS, Settings
from latexzettel.infra.db import ensure_tables

from latexzettel.api.notes import (
    create_note,
    create_note_md,
    rename_note_file,
    rename_reference,
    remove_note,
)
from latexzettel.api.workflows import list_recent_notes, get_recent_note
from latexzettel.api.render import render_note, render_updates
from latexzettel.api.sync import synchronize, force_synchronize
from latexzettel.api.markdown import sync_md, tex_to_md
from latexzettel.api.export import new_project, export_project, export_draft
from latexzettel.api.analysis import (
    list_unreferenced_notes,
    remove_duplicate_citations,
    calculate_adjacency_matrix,
)

from latexzettel.server.protocols import JsonObject, ProtocolError
from latexzettel.server.routers import (
    CancelledError,
    CancelToken,
    require_not_cancelled,
)

# =============================================================================
# Protocolo
# =============================================================================

PROTOCOL_VERSION = 1
SERVER_NAME = "latexzettel-server"
SERVER_VERSION = (
    "0.1.0"  # puedes sustituir por importlib.metadata.version("texnotes") si deseas
)


def _eprint(*args: Any) -> None:
    """
    Logs/diagnóstico SIEMPRE a stderr.
    """
    print(*args, file=sys.stderr, flush=True)


def _write_jsonl(obj: JsonObject) -> None:
    """
    stdout solo datos JSONL. Nunca logs aquí.
    """
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _error_obj(
    *,
    v: int,
    req_id: JsonScalar,
    code: str,
    message: str,
    data: Optional[JsonObject] = None,
) -> JsonObject:
    err: JsonObject = {"code": code, "message": message, "data": data or {}}
    return {"v": v, "id": req_id, "ok": False, "error": err}


def _ok_obj(*, v: int, req_id: JsonScalar, result: JsonObject) -> JsonObject:
    return {"v": v, "id": req_id, "ok": True, "result": result}


# =============================================================================
# Contexto de servidor (sesión explícita)
# =============================================================================


@dataclass
class ServerContext:
    """
    Contexto mantenido por el server. Importante:
    - No asumimos un único cliente “implícito” en el protocolo.
    - initialize permite cargar defaults para el “session context” del transporte.
    - Para soportar multi-cliente real (socket), estos defaults deberían moverse
      a un scope por conexión; por stdio hay una sola conexión.
    """

    settings: Settings
    db_module_path: str
    db: Any  # módulo peewee importado dinámicamente
    initialized: bool = False


def _import_db_module(db_module: str):
    import importlib

    return importlib.import_module(db_module)


def _init_db(db: Any) -> None:
    health = ensure_tables(db)
    if not health.ok:
        raise RuntimeError(f"DB init failed: {health.error}")


# =============================================================================
# Parsing/validación de requests
# =============================================================================


def _parse_request_line(line: str) -> JsonObject:
    """
    Parse NDJSON line -> dict. Lanza ProtocolError si inválido.
    """
    line = line.strip("\n")
    if not line:
        raise ProtocolError("Empty line")
    try:
        msg = json.loads(line)
    except json.JSONDecodeError as e:
        raise ProtocolError(f"Invalid JSON: {e}") from e

    if not isinstance(msg, dict):
        raise ProtocolError("Request must be a JSON object")

    return msg  # type: ignore[return-value]


def _require_fields(msg: JsonObject, fields: list[str]) -> None:
    for f in fields:
        if f not in msg:
            raise ProtocolError(f"Missing field '{f}'")


def _get_v(msg: JsonObject) -> int:
    v = msg.get("v", None)
    if not isinstance(v, int):
        raise ProtocolError("Field 'v' must be int")
    return v


def _get_id(msg: JsonObject) -> JsonScalar:
    req_id = msg.get("id", None)
    if isinstance(req_id, (str, int)):
        return req_id
    raise ProtocolError("Field 'id' must be string or int")


def _get_method(msg: JsonObject) -> str:
    method = msg.get("method", None)
    if not isinstance(method, str):
        raise ProtocolError("Field 'method' must be string")
    return method


def _get_params(msg: JsonObject) -> JsonObject:
    params = msg.get("params", {})
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise ProtocolError("Field 'params' must be an object")
    return params  # type: ignore[return-value]


# =============================================================================
# Handlers (negocio)
# =============================================================================

Handler = Callable[[ServerContext, JsonObject, CancelToken], JsonObject]


def handle_initialize(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    """
    method="initialize"
    params:
      {
        "client": { "name": "...", "version": "...", "capabilities": {...} },
        "root": "...",                  # opcional
        "db_module": "LatexZettel.database"  # opcional
      }

    Política de versión:
    - v debe ser PROTOCOL_VERSION (validado antes de llamar)
    """
    require_not_cancelled(token)

    root = params.get("root")
    db_module = params.get("db_module")

    # Para MVP: Settings root no está reconfigurable aquí, a menos que ya tengas build_settings(root=...).
    # Si lo tienes, reemplaza DEFAULT_SETTINGS.
    # Se conserva ctx.settings; root sirve como metadata hoy.
    if isinstance(db_module, str) and db_module:
        ctx.db_module_path = db_module
        ctx.db = _import_db_module(db_module)
        _init_db(ctx.db)

    ctx.initialized = True

    return {
        "server": {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
            "protocol_version": PROTOCOL_VERSION,
        },
        "capabilities": {
            "transport": ["stdio-jsonl", "unix-socket-jsonl"],  # futuro
            "cancel": True,
            "methods": sorted(list(ROUTES.keys())),
        },
        "session": {
            "db_module": ctx.db_module_path,
            "root": str(root) if isinstance(root, str) else None,
        },
    }


def handle_cancel(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    """
    method="cancel"
    params: { "id_to_cancel": ... }
    Best-effort MVP: marca cancelación. El request cancelado solo se abortará si su handler consulta token.
    """
    _require_not_cancelled(token)

    id_to_cancel = params.get("id_to_cancel")
    if not isinstance(id_to_cancel, (str, int)):
        raise ProtocolError("cancel.params.id_to_cancel must be string|int")

    # La cancelación real se resuelve a nivel loop (tokens_by_id)
    # Aquí solo devolvemos ACK; la acción la hace el loop principal.
    return {"cancel_requested": True, "id_to_cancel": id_to_cancel}


# ---- Notes


def handle_notes_new(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    _require_not_cancelled(token)
    note_name = params.get("note_name")
    reference_name = params.get("reference_name")
    extension = params.get("extension", "tex")

    if not isinstance(note_name, str) or not note_name:
        raise ProtocolError("params.note_name must be non-empty string")
    if reference_name is not None and not isinstance(reference_name, str):
        raise ProtocolError("params.reference_name must be string or null")
    if not isinstance(extension, str):
        raise ProtocolError("params.extension must be string")

    create_note(
        db=ctx.db,
        note_name=note_name,
        reference_name=reference_name,
        extension=extension,
        paths=ctx.settings.paths,
        add_to_documents=bool(params.get("add_to_documents", True)),
        create_file=bool(params.get("create_file", True)),
    )
    return {"created": True, "note_name": note_name, "extension": extension}


def handle_notes_new_md(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    _require_not_cancelled(token)
    note_name = params.get("note_name")
    reference_name = params.get("reference_name")

    if not isinstance(note_name, str) or not note_name:
        raise ProtocolError("params.note_name must be non-empty string")
    if reference_name is not None and not isinstance(reference_name, str):
        raise ProtocolError("params.reference_name must be string or null")

    create_note_md(
        db=ctx.db,
        note_name=note_name,
        reference_name=reference_name,
        paths=ctx.settings.paths,
    )
    return {"created": True, "note_name": note_name, "extension": "md"}


def handle_notes_list_recent(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    _require_not_cancelled(token)
    n = params.get("n", 10)
    if not isinstance(n, int) or n < 0:
        raise ProtocolError("params.n must be int >= 0")

    items = list_recent_notes(paths=ctx.settings.paths, n=n)
    return {
        "items": [
            {"filename": it.filename, "path": str(it.path), "mtime": it.mtime}
            for it in items
        ]
    }


def handle_notes_get_recent(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    _require_not_cancelled(token)
    n = params.get("n", 1)
    if not isinstance(n, int) or n <= 0:
        raise ProtocolError("params.n must be int >= 1")
    it = get_recent_note(paths=ctx.settings.paths, n=n)
    return {"item": {"filename": it.filename, "path": str(it.path), "mtime": it.mtime}}


def handle_notes_rename_file(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    _require_not_cancelled(token)
    old_filename = params.get("old_filename")
    new_filename = params.get("new_filename")
    if not isinstance(old_filename, str) or not old_filename:
        raise ProtocolError("params.old_filename must be non-empty string")
    if not isinstance(new_filename, str) or not new_filename:
        raise ProtocolError("params.new_filename must be non-empty string")

    rename_note_file(
        db=ctx.db,
        old_filename=old_filename,
        new_filename=new_filename,
        paths=ctx.settings.paths,
    )
    return {"renamed": True, "old_filename": old_filename, "new_filename": new_filename}


def handle_notes_rename_ref(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    _require_not_cancelled(token)
    old_reference = params.get("old_reference")
    new_reference = params.get("new_reference")
    update_backrefs = bool(params.get("update_backrefs", True))

    if not isinstance(old_reference, str) or not old_reference:
        raise ProtocolError("params.old_reference must be non-empty string")
    if not isinstance(new_reference, str) or not new_reference:
        raise ProtocolError("params.new_reference must be non-empty string")

    rename_reference(
        db=ctx.db,
        old_reference=old_reference,
        new_reference=new_reference,
        paths=ctx.settings.paths,
        update_backrefs=update_backrefs,
    )
    return {
        "renamed": True,
        "old_reference": old_reference,
        "new_reference": new_reference,
    }


def handle_notes_remove(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    _require_not_cancelled(token)
    filename = params.get("filename")
    if not isinstance(filename, str) or not filename:
        raise ProtocolError("params.filename must be non-empty string")

    remove_note(
        db=ctx.db,
        filename=filename,
        paths=ctx.settings.paths,
        delete_db_entry=bool(params.get("delete_db_entry", True)),
        delete_documents_entry=bool(params.get("delete_documents_entry", True)),
        delete_file=bool(params.get("delete_file", False)),
    )
    return {"removed": True, "filename": filename}


# ---- Render / Sync / Markdown / Export / Analysis (subset MVP + extensible)


def handle_render_note(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    _require_not_cancelled(token)
    filename = params.get("filename")
    fmt = params.get("format", "pdf")
    run_biber_flag = bool(params.get("run_biber", False))

    if not isinstance(filename, str) or not filename:
        raise ProtocolError("params.filename must be non-empty string")
    if fmt not in ("pdf", "html"):
        raise ProtocolError("params.format must be 'pdf' or 'html'")

    res = render_note(
        db=ctx.db,
        filename=filename,
        format=(RenderFormat.PDF if fmt == "pdf" else RenderFormat.HTML),
        run_biber=run_biber_flag,
        settings=ctx.settings.render,
        paths=ctx.settings.paths,
        check=False,
    )
    if not res.ok:
        raise RuntimeError(res.stderr_text())
    return {"rendered": True, "filename": filename, "format": fmt}


def handle_render_updates(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    _require_not_cancelled(token)
    fmt = params.get("format", "pdf")
    if fmt not in ("pdf", "html"):
        raise ProtocolError("params.format must be 'pdf' or 'html'")

    res = render_updates(
        db=ctx.db,
        format=(RenderFormat.PDF if fmt == "pdf" else RenderFormat.HTML),
        settings=ctx.settings.render,
        paths=ctx.settings.paths,
        check=False,
    )
    return {
        "rendered": res.rendered,
        "rerendered_targets": res.rerendered_targets,
        "rerendered_sources": res.rerendered_sources,
    }


def handle_sync_synchronize(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    _require_not_cancelled(token)
    res = synchronize(db=ctx.db, paths=ctx.settings.paths)
    return {
        "updated_notes": [n.filename for n in res.updated_notes],
        "modified_links": len(res.new_or_modified_links),
        "needs_biber": [n.filename for n, rb in res.run_biber.items() if rb],
    }


def handle_sync_force(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    _require_not_cancelled(token)
    res = force_synchronize(
        db=ctx.db,
        paths=ctx.settings.paths,
        create_missing_note_files=bool(params.get("create_missing_note_files", False)),
        create_documents_tex_if_missing=bool(
            params.get("create_documents_tex_if_missing", True)
        ),
    )
    return {
        "tracked": len(res.tracked_notes),
        "added_notes": [n.filename for n in res.added_notes],
        "updated_notes": [n.filename for n in res.updated_notes],
    }


def handle_markdown_sync_md(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    _require_not_cancelled(token)
    res = sync_md(
        db=ctx.db,
        paths=ctx.settings.paths,
        pandoc=ctx.settings.pandoc,
        overwrite_tex=bool(params.get("overwrite_tex", True)),
        auto_register_new_notes=bool(params.get("auto_register_new_notes", True)),
    )
    return {
        "created_notes": res.created_notes,
        "updated_notes": res.updated_notes,
        "skipped_notes": res.skipped_notes,
        "pandoc_failures": res.pandoc_failures,
    }


def handle_markdown_tex_to_md(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    _require_not_cancelled(token)
    note_name = params.get("note_name")
    if not isinstance(note_name, str) or not note_name:
        raise ProtocolError("params.note_name must be non-empty string")

    out_dir = params.get("output_dir")
    output_dir = Path(out_dir) if isinstance(out_dir, str) and out_dir else None

    res = tex_to_md(
        db=ctx.db,
        note_name=note_name,
        paths=ctx.settings.paths,
        pandoc=ctx.settings.pandoc,
        output_dir=output_dir,
        overwrite=bool(params.get("overwrite", True)),
    )
    return {"output_file": str(res.output_file), "pandoc_stderr": res.pandoc_stderr}


def handle_export_new_project(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    _require_not_cancelled(token)
    dir_name = params.get("dir_name")
    filename = params.get("filename")
    if not isinstance(dir_name, str) or not dir_name:
        raise ProtocolError("params.dir_name must be non-empty string")
    if filename is not None and not isinstance(filename, str):
        raise ProtocolError("params.filename must be string or null")

    res = new_project(dir_name=dir_name, filename=filename, paths=ctx.settings.paths)
    return {"dirpath": str(res.dirpath), "tex_file": str(res.tex_file)}


def handle_export_project(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    _require_not_cancelled(token)
    project_folder = params.get("project_folder")
    texfile = params.get("texfile")
    overwrite = bool(params.get("overwrite", False))
    if not isinstance(project_folder, str) or not project_folder:
        raise ProtocolError("params.project_folder must be non-empty string")
    if texfile is not None and not isinstance(texfile, str):
        raise ProtocolError("params.texfile must be string or null")

    res = export_project(
        project_folder=project_folder,
        texfile=texfile,
        paths=ctx.settings.paths,
        overwrite=overwrite,
    )
    return {"output_file": str(res.output_file), "overwritten": res.overwritten}


def handle_export_draft(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    _require_not_cancelled(token)
    input_file = params.get("input_file")
    output_file = params.get("output_file")
    overwrite = bool(params.get("overwrite", False))
    if not isinstance(input_file, str) or not input_file:
        raise ProtocolError("params.input_file must be non-empty string")
    if output_file is not None and not isinstance(output_file, str):
        raise ProtocolError("params.output_file must be string or null")

    res = export_draft(
        input_file=Path(input_file),
        output_file=None if output_file is None else Path(output_file),
        paths=ctx.settings.paths,
        overwrite=overwrite,
    )
    return {
        "output_file": str(res.output_file),
        "created_draft_dir": res.created_draft_dir,
    }


def handle_analysis_unreferenced(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    _require_not_cancelled(token)
    index_by = params.get("index_by", "filename")
    if not isinstance(index_by, str):
        raise ProtocolError("params.index_by must be string")
    notes = list_unreferenced_notes(db=ctx.db, index_by=index_by)
    return {"unreferenced": [n.filename for n in notes]}


def handle_analysis_dedup_citations(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    _require_not_cancelled(token)
    deleted = remove_duplicate_citations(db=ctx.db)
    return {"deleted": deleted}


def handle_analysis_adjacency(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    _require_not_cancelled(token)
    index_by = params.get("index_by", "filename")
    show = bool(params.get("show", False))
    if not isinstance(index_by, str):
        raise ProtocolError("params.index_by must be string")

    res = calculate_adjacency_matrix(db=ctx.db, index_by=index_by)
    payload: JsonObject = {
        "count": len(res.notes),
        "index_by": res.index_by,
    }
    if show:
        # cuidado: puede ser grande. Se serializa como lista de listas.
        payload["adjacency"] = res.adjacency.tolist()
        payload["notes"] = [getattr(n, "filename", "") for n in res.notes]
    return payload


# =============================================================================
# Routing table
# =============================================================================

ROUTES: dict[str, Handler] = {
    # handshake
    "initialize": handle_initialize,
    "cancel": handle_cancel,
    # notes
    "notes.new": handle_notes_new,
    "notes.new_md": handle_notes_new_md,
    "notes.list_recent": handle_notes_list_recent,
    "notes.get_recent": handle_notes_get_recent,
    "notes.rename_file": handle_notes_rename_file,
    "notes.rename_ref": handle_notes_rename_ref,
    "notes.remove": handle_notes_remove,
    # render
    "render.note": handle_render_note,
    "render.updates": handle_render_updates,
    # sync
    "sync.synchronize": handle_sync_synchronize,
    "sync.force": handle_sync_force,
    # markdown
    "markdown.sync_md": handle_markdown_sync_md,
    "markdown.tex_to_md": handle_markdown_tex_to_md,
    # export
    "export.new_project": handle_export_new_project,
    "export.project": handle_export_project,
    "export.draft": handle_export_draft,
    # analysis
    "analysis.unreferenced": handle_analysis_unreferenced,
    "analysis.dedup_citations": handle_analysis_dedup_citations,
    "analysis.adjacency": handle_analysis_adjacency,
}


# =============================================================================
# Main loop
# =============================================================================


def _handle_request(
    ctx: ServerContext,
    msg: JsonObject,
    tokens_by_id: dict[Union[str, int], CancelToken],
) -> Optional[JsonObject]:
    """
    Procesa un request (ya parseado). Devuelve una response JSONObject o None.
    Errores se convierten a response error.
    """
    _require_fields(msg, ["v", "id", "method"])
    v = _get_v(msg)
    req_id = _get_id(msg)
    method = _get_method(msg)
    params = _get_params(msg)

    # Enforce version
    if v != PROTOCOL_VERSION:
        # responder error y señalizar cierre por versión
        return _error_obj(
            v=v,
            req_id=req_id,
            code="VERSION_MISMATCH",
            message=f"Protocol version mismatch: client={v}, server={PROTOCOL_VERSION}",
            data={"server_protocol_version": PROTOCOL_VERSION},
        )

    # Cancel request handling: we allow cancel even before initialize
    if method == "cancel":
        # cancel itself should not be cancellable
        token = CancelToken(cancelled=False)
        resp = ROUTES["cancel"](ctx, params, token)
        return _ok_obj(v=v, req_id=req_id, result=resp)

    # Enforce initialize first (recommended); allow a small set before init if desired.
    if not ctx.initialized and method != "initialize":
        return _error_obj(
            v=v,
            req_id=req_id,
            code="NOT_INITIALIZED",
            message="Server not initialized. Call method 'initialize' first.",
            data={"required_method": "initialize"},
        )

    handler = ROUTES.get(method)
    if handler is None:
        return _error_obj(
            v=v,
            req_id=req_id,
            code="METHOD_NOT_FOUND",
            message=f"Unknown method '{method}'",
        )

    # Token per request id
    token = tokens_by_id.setdefault(req_id, CancelToken(cancelled=False))

    try:
        result = handler(ctx, params, token)
        return _ok_obj(v=v, req_id=req_id, result=result)
    except CancelledError:
        return _error_obj(
            v=v, req_id=req_id, code="CANCELLED", message="Request cancelled", data={}
        )
    except ProtocolError as e:
        return _error_obj(
            v=v, req_id=req_id, code="INVALID_REQUEST", message=str(e), data={}
        )
    except Exception as e:
        # Internal error
        data: JsonObject = {"exception": e.__class__.__name__}
        # Para debug, podemos incluir stacktrace si LATEXZETTEL_SERVER_DEBUG=1
        if os.environ.get("LATEXZETTEL_SERVER_DEBUG", "") in ("1", "true", "yes"):
            data["trace"] = traceback.format_exc()
        return _error_obj(
            v=v, req_id=req_id, code="INTERNAL_ERROR", message=str(e), data=data
        )


def main() -> None:
    """
    Inicia el server en modo stdio JSONL.

    El cliente debe:
    1) enviar initialize
    2) enviar requests NDJSON
    3) leer responses NDJSON

    stdout: SOLO responses JSONL
    stderr: logs/diagnóstico
    """
    # Defaults de sesión (pueden ser override por initialize)
    ctx = ServerContext(
        settings=DEFAULT_SETTINGS,
        # db_module_path="LatexZettel.database",
        # db=_import_db_module("LatexZettel.database"),
        db_module_path="latexzettel.infra.orm",
        db=_import_db_module("latexzettel.infra.orm"),
        initialized=False,
    )

    try:
        _init_db(ctx.db)
    except Exception as e:
        # No romper el protocolo en stdout; log a stderr y salir.
        _eprint(f"[{SERVER_NAME}] DB init failed on startup: {e}")
        sys.exit(2)

    tokens_by_id: dict[Union[str, int], CancelToken] = {}

    # Lectura NDJSON
    for line in sys.stdin:
        try:
            msg = _parse_request_line(line)
        except ProtocolError as e:
            # No hay id para correlación; log y continuar.
            _eprint(f"[{SERVER_NAME}] Protocol error (no id): {e}")
            continue

        # Pre-parse id/v if possible to handle version mismatch and id errors
        # If id/v missing, respond with best-effort error if id extractable.
        try:
            # Attempt full handling
            resp = _handle_request(ctx, msg, tokens_by_id)
        except ProtocolError as e:
            # If id exists, respond; else log.
            try:
                v = msg.get("v", PROTOCOL_VERSION)
                if not isinstance(v, int):
                    v = PROTOCOL_VERSION
                req_id = msg.get("id", None)
                if isinstance(req_id, (str, int)):
                    resp = _error_obj(
                        v=v,
                        req_id=req_id,
                        code="INVALID_REQUEST",
                        message=str(e),
                        data={},
                    )
                else:
                    _eprint(f"[{SERVER_NAME}] Protocol error (no id): {e}")
                    resp = None
            except Exception:
                resp = None

        if resp is None:
            continue

        # Version mismatch policy: respond + close
        if resp.get("ok") is False:
            err = resp.get("error", {})
            if isinstance(err, dict) and err.get("code") == "VERSION_MISMATCH":
                _write_jsonl(resp)
                # Cerrar inmediatamente según política
                break

        # Special case: cancel method should mark tokens
        # If request is cancel, apply it here
        try:
            if msg.get("method") == "cancel":
                params = msg.get("params", {})
                if isinstance(params, dict):
                    id_to_cancel = params.get("id_to_cancel")
                    if isinstance(id_to_cancel, (str, int)):
                        tok = tokens_by_id.get(id_to_cancel)
                        if tok is not None:
                            tok.cancelled = True
        except Exception:
            # best-effort; ignore
            pass

        _write_jsonl(resp)

    # Cleanup (no stdout)
    try:
        # cerrar DB si el módulo lo permite; respetamos modularidad
        if hasattr(ctx.db, "database") and hasattr(ctx.db.database, "close"):
            ctx.db.database.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
