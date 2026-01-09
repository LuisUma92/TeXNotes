# src/latexzettel/server/protocols.py
"""
Definiciones del protocolo RPC JSONL/NDJSON para latexzettel-server.

Objetivo:
- Centralizar tipos, constantes y helpers de envelope para que el server sea
  transport-agnostic (stdio hoy, unix socket mañana) sin reescribir handlers.

Contratos:
Request:
  { "v": <int>, "id": <str|int>, "method": <str>, "params": <object> }

Response OK:
  { "v": <int>, "id": <str|int>, "ok": true, "result": <object> }

Response error:
  { "v": <int>, "id": <str|int>, "ok": false,
    "error": { "code": <str>, "message": <str>, "data": <object> } }

Política de versión:
- Cada mensaje incluye "v".
- Si v != PROTOCOL_VERSION: responder VERSION_MISMATCH y cerrar conexión.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, Union, Optional, Any, List

# =============================================================================
# Versionado
# =============================================================================

PROTOCOL_VERSION: int = 1


# =============================================================================
# Tipos JSON
# =============================================================================

JsonScalar = Union[str, int, float, bool, None]
JsonValue = Union[JsonScalar, Dict[str, "JsonValue"], List["JsonValue"]]
JsonObject = Dict[str, JsonValue]


# =============================================================================
# Errores del protocolo
# =============================================================================


class ProtocolError(Exception):
    """Request inválido (JSON mal formado, fields faltantes o tipos incorrectos)."""


# =============================================================================
# Envelope helpers
# =============================================================================


def ok_response(*, v: int, req_id: JsonScalar, result: JsonObject) -> JsonObject:
    return {"v": v, "id": req_id, "ok": True, "result": result}


def error_response(
    *,
    v: int,
    req_id: JsonScalar,
    code: str,
    message: str,
    data: Optional[JsonObject] = None,
) -> JsonObject:
    return {
        "v": v,
        "id": req_id,
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "data": data or {},
        },
    }


# =============================================================================
# Parsing / Validación (transport layer)
# =============================================================================


def parse_jsonl_line(line: str) -> JsonObject:
    """
    Parse estricto de una línea JSONL (sin '\n') -> JsonObject.
    """
    line = line.strip("\n")
    if not line:
        raise ProtocolError("Empty line")

    try:
        msg = json.loads(line)
    except json.JSONDecodeError as e:
        raise ProtocolError(f"Invalid JSON: {e}") from e

    if not isinstance(msg, dict):
        raise ProtocolError("Message must be a JSON object")

    return msg  # type: ignore[return-value]


def require_fields(msg: JsonObject, fields: list[str]) -> None:
    for f in fields:
        if f not in msg:
            raise ProtocolError(f"Missing field '{f}'")


def get_v(msg: JsonObject) -> int:
    v = msg.get("v", None)
    if not isinstance(v, int):
        raise ProtocolError("Field 'v' must be int")
    return v


def get_id(msg: JsonObject) -> JsonScalar:
    req_id = msg.get("id", None)
    if isinstance(req_id, (str, int)):
        return req_id
    raise ProtocolError("Field 'id' must be string or int")


def get_method(msg: JsonObject) -> str:
    method = msg.get("method", None)
    if not isinstance(method, str):
        raise ProtocolError("Field 'method' must be string")
    return method


def get_params(msg: JsonObject) -> JsonObject:
    params = msg.get("params", {})
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise ProtocolError("Field 'params' must be an object")
    return params  # type: ignore[return-value]


def enforce_version(v: int) -> None:
    """
    Verifica compatibilidad de versión.
    El transport layer debe usar esto para decidir cerrar la conexión.
    """
    if v != PROTOCOL_VERSION:
        raise ProtocolError(
            f"Protocol version mismatch: client={v}, server={PROTOCOL_VERSION}"
        )


# =============================================================================
# Capabilities helper (handshake)
# =============================================================================


def server_capabilities(methods: list[str]) -> JsonObject:
    """
    Capabilities del server para initialize().
    """
    return {
        "transport": ["stdio-jsonl", "unix-socket-jsonl"],
        "cancel": True,
        "methods": methods,
        "protocol_version": PROTOCOL_VERSION,
    }
