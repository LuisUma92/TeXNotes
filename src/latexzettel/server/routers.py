# src/latexzettel/server/router.py
"""
Router y registro de handlers para LatexZettel Server (JSONL RPC).

Objetivo:
- Separar "tabla de rutas" + handlers del main loop/transport.
- Mantener handlers transport-agnostic: stdio hoy, unix socket mañana.

Este módulo no escribe stdout; no imprime; no hace logs. Las excepciones se elevan
al main loop, que las convierte a error responses.

Nota:
- Los handlers devuelven dicts JSON-serializables (JsonObject).
- Los handlers reciben:
    - ctx: ServerContext (settings + db module)
    - params: JsonObject
    - token: CancelToken (best-effort cancel)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

from latexzettel.config.settings import DEFAULT_SETTINGS, Settings
from latexzettel.domain.types import RenderFormat

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

# =============================================================================
# Tipos del protocolo (mínimos, para evitar imports circulares)
# =============================================================================


class CancelledError(Exception):
    pass


@dataclass
class CancelToken:
    cancelled: bool = False


def require_not_cancelled(token: CancelToken) -> None:
    if token.cancelled:
        raise CancelledError("Cancelled")


@dataclass
class ServerContext:
    """
    Contexto de sesión del server.
    En stdio hay una sola sesión; en unix socket normalmente será por conexión.
    """

    settings: Settings
    db_module_path: str
    db: Any
    initialized: bool = False


Handler = Callable[[ServerContext, JsonObject, CancelToken], JsonObject]


# =============================================================================
# Helpers de validación
# =============================================================================


def _req_str(params: JsonObject, key: str) -> str:
    v = params.get(key)
    if not isinstance(v, str) or not v:
        raise ProtocolError(f"params.{key} must be non-empty string")
    return v


def _opt_str(params: JsonObject, key: str) -> Optional[str]:
    v = params.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ProtocolError(f"params.{key} must be string or null")
    return v


def _opt_bool(params: JsonObject, key: str, default: bool = False) -> bool:
    v = params.get(key, default)
    return bool(v)


def _opt_int(params: JsonObject, key: str, default: int) -> int:
    v = params.get(key, default)
    if not isinstance(v, int):
        raise ProtocolError(f"params.{key} must be int")
    return v


def _opt_format(params: JsonObject, key: str = "format", default: str = "pdf") -> str:
    v = params.get(key, default)
    if not isinstance(v, str):
        raise ProtocolError(f"params.{key} must be string")
    v = v.lower().strip()
    if v not in ("pdf", "html"):
        raise ProtocolError("params.format must be 'pdf' or 'html'")
    return v


# =============================================================================
# Handlers: initialize/cancel (transport loop aplica cancel tokens)
# =============================================================================


def handle_initialize(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    require_not_cancelled(token)

    # Estos campos son metadata; el transport layer puede usar db_module/root para reconfigurar.
    # En MVP, ctx.settings se mantiene; ctx.db se reemplaza desde main.py para evitar imports circulares.
    ctx.initialized = True

    client = params.get("client", {})
    if client is None:
        client = {}
    if not isinstance(client, dict):
        raise ProtocolError("params.client must be object or null")

    return {
        "accepted": True,
        "client": client,
    }


def handle_cancel(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    require_not_cancelled(token)
    id_to_cancel = params.get("id_to_cancel")
    if not isinstance(id_to_cancel, (str, int)):
        raise ProtocolError("cancel.params.id_to_cancel must be string|int")
    return {"cancel_requested": True, "id_to_cancel": id_to_cancel}


# =============================================================================
# Handlers: notes
# =============================================================================


def handle_notes_new(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    require_not_cancelled(token)
    note_name = _req_str(params, "note_name")
    reference_name = _opt_str(params, "reference_name")
    extension = params.get("extension", "tex")
    if not isinstance(extension, str):
        raise ProtocolError("params.extension must be string")

    create_note(
        db=ctx.db,
        note_name=note_name,
        reference_name=reference_name,
        extension=extension,
        paths=ctx.settings.paths,
        add_to_documents=_opt_bool(params, "add_to_documents", True),
        create_file=_opt_bool(params, "create_file", True),
    )
    return {"created": True, "note_name": note_name, "extension": extension}


def handle_notes_new_md(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    require_not_cancelled(token)
    note_name = _req_str(params, "note_name")
    reference_name = _opt_str(params, "reference_name")

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
    require_not_cancelled(token)
    n = _opt_int(params, "n", 10)
    if n < 0:
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
    require_not_cancelled(token)
    n = _opt_int(params, "n", 1)
    if n <= 0:
        raise ProtocolError("params.n must be int >= 1")
    it = get_recent_note(paths=ctx.settings.paths, n=n)
    return {"item": {"filename": it.filename, "path": str(it.path), "mtime": it.mtime}}


def handle_notes_rename_file(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    require_not_cancelled(token)
    old_filename = _req_str(params, "old_filename")
    new_filename = _req_str(params, "new_filename")
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
    require_not_cancelled(token)
    old_reference = _req_str(params, "old_reference")
    new_reference = _req_str(params, "new_reference")
    rename_reference(
        db=ctx.db,
        old_reference=old_reference,
        new_reference=new_reference,
        paths=ctx.settings.paths,
        update_backrefs=_opt_bool(params, "update_backrefs", True),
    )
    return {
        "renamed": True,
        "old_reference": old_reference,
        "new_reference": new_reference,
    }


def handle_notes_remove(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    require_not_cancelled(token)
    filename = _req_str(params, "filename")
    remove_note(
        db=ctx.db,
        filename=filename,
        paths=ctx.settings.paths,
        delete_db_entry=_opt_bool(params, "delete_db_entry", True),
        delete_documents_entry=_opt_bool(params, "delete_documents_entry", True),
        delete_file=_opt_bool(params, "delete_file", False),
    )
    return {"removed": True, "filename": filename}


# =============================================================================
# Handlers: render
# =============================================================================


def handle_render_note(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    require_not_cancelled(token)
    filename = _req_str(params, "filename")
    fmt = _opt_format(params)
    run_biber_flag = _opt_bool(params, "run_biber", False)

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
    require_not_cancelled(token)
    fmt = _opt_format(params)
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


# =============================================================================
# Handlers: sync
# =============================================================================


def handle_sync_synchronize(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    require_not_cancelled(token)
    res = synchronize(db=ctx.db, paths=ctx.settings.paths)
    return {
        "updated_notes": [n.filename for n in res.updated_notes],
        "modified_links": len(res.new_or_modified_links),
        "needs_biber": [n.filename for n, rb in res.run_biber.items() if rb],
    }


def handle_sync_force(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    require_not_cancelled(token)
    res = force_synchronize(
        db=ctx.db,
        paths=ctx.settings.paths,
        create_missing_note_files=_opt_bool(params, "create_missing_note_files", False),
        create_documents_tex_if_missing=_opt_bool(
            params, "create_documents_tex_if_missing", True
        ),
    )
    return {
        "tracked": len(res.tracked_notes),
        "added_notes": [n.filename for n in res.added_notes],
        "updated_notes": [n.filename for n in res.updated_notes],
    }


# =============================================================================
# Handlers: markdown
# =============================================================================


def handle_markdown_sync_md(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    require_not_cancelled(token)
    res = sync_md(
        db=ctx.db,
        paths=ctx.settings.paths,
        pandoc=ctx.settings.pandoc,
        overwrite_tex=_opt_bool(params, "overwrite_tex", True),
        auto_register_new_notes=_opt_bool(params, "auto_register_new_notes", True),
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
    require_not_cancelled(token)
    note_name = _req_str(params, "note_name")
    out_dir = _opt_str(params, "output_dir")
    output_dir = Path(out_dir) if out_dir else None

    res = tex_to_md(
        db=ctx.db,
        note_name=note_name,
        paths=ctx.settings.paths,
        pandoc=ctx.settings.pandoc,
        output_dir=output_dir,
        overwrite=_opt_bool(params, "overwrite", True),
    )
    return {"output_file": str(res.output_file), "pandoc_stderr": res.pandoc_stderr}


# =============================================================================
# Handlers: export
# =============================================================================


def handle_export_new_project(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    require_not_cancelled(token)
    dir_name = _req_str(params, "dir_name")
    filename = _opt_str(params, "filename")

    res = new_project(dir_name=dir_name, filename=filename, paths=ctx.settings.paths)
    return {"dirpath": str(res.dirpath), "tex_file": str(res.tex_file)}


def handle_export_project(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    require_not_cancelled(token)
    project_folder = _req_str(params, "project_folder")
    texfile = _opt_str(params, "texfile")

    res = export_project(
        project_folder=project_folder,
        texfile=texfile,
        paths=ctx.settings.paths,
        overwrite=_opt_bool(params, "overwrite", False),
    )
    return {"output_file": str(res.output_file), "overwritten": res.overwritten}


def handle_export_draft(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    require_not_cancelled(token)
    input_file = _req_str(params, "input_file")
    output_file = _opt_str(params, "output_file")

    res = export_draft(
        input_file=Path(input_file),
        output_file=None if output_file is None else Path(output_file),
        paths=ctx.settings.paths,
        overwrite=_opt_bool(params, "overwrite", False),
    )
    return {
        "output_file": str(res.output_file),
        "created_draft_dir": res.created_draft_dir,
    }


# =============================================================================
# Handlers: analysis
# =============================================================================


def handle_analysis_unreferenced(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    require_not_cancelled(token)
    index_by = params.get("index_by", "filename")
    if not isinstance(index_by, str):
        raise ProtocolError("params.index_by must be string")
    notes = list_unreferenced_notes(db=ctx.db, index_by=index_by)
    return {"unreferenced": [n.filename for n in notes]}


def handle_analysis_dedup_citations(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    require_not_cancelled(token)
    deleted = remove_duplicate_citations(db=ctx.db)
    return {"deleted": deleted}


def handle_analysis_adjacency(
    ctx: ServerContext, params: JsonObject, token: CancelToken
) -> JsonObject:
    require_not_cancelled(token)
    index_by = params.get("index_by", "filename")
    show = _opt_bool(params, "show", False)
    if not isinstance(index_by, str):
        raise ProtocolError("params.index_by must be string")

    res = calculate_adjacency_matrix(db=ctx.db, index_by=index_by)
    payload: JsonObject = {"count": len(res.notes), "index_by": res.index_by}
    if show:
        payload["adjacency"] = res.adjacency.tolist()
        payload["notes"] = [getattr(n, "filename", "") for n in res.notes]
    return payload


# =============================================================================
# Routes registry
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


def list_methods() -> list[str]:
    return sorted(ROUTES.keys())
