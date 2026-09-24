"""JSON-RPC 2.0 envelopes for the generic CAD MCP stream."""

from __future__ import annotations

import json

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def dumps(payload: object) -> str:
    return json.dumps(payload, allow_nan=False, separators=(",", ":"))


def success(request_id: object, result: object) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error(request_id: object, code: int, message: str, data: object | None = None) -> dict:
    payload = {"code": int(code), "message": str(message)}
    if data is not None:
        payload["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": payload}


def parse_line(raw: str) -> tuple[dict | None, dict | None]:
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return None, error(None, PARSE_ERROR, "Parse error")
    if not isinstance(payload, dict):
        return None, error(None, INVALID_REQUEST, "Invalid Request")
    if payload.get("jsonrpc") != "2.0":
        return None, error(payload.get("id"), INVALID_REQUEST, "Invalid Request")
    return payload, None
