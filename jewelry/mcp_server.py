"""In-process MCP 2025-06-18 server bound to one Application document."""

from __future__ import annotations

import json
import secrets
import socket
import threading
import time
from pathlib import Path

from jewelry.jsonrpc import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    dumps,
    error,
    parse_line,
    success,
)

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "jewelry"
SERVER_VERSION = "1"
MAX_LINE = 16 * 1024 * 1024
AUTH_TIMEOUT = 5.0
REPO_ROOT = str(Path(__file__).resolve().parent.parent)

_GENERIC_SCHEMA = {"type": "object", "additionalProperties": True}
_CREATE_RING_SCHEMA = {
    "type": "object",
    "properties": {
        "inner_radius": {"type": "number"},
        "outer_radius": {"type": "number"},
        "width": {"type": "number"},
    },
    "required": ["inner_radius", "outer_radius", "width"],
}


class NdjsonSocket:
    """Line-delimited JSON-RPC over a connected stream socket."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buffer = bytearray()
        self._send_lock = threading.Lock()
        self._closed = False

    def send_line(self, line: str) -> None:
        if self._closed:
            raise ConnectionError("MCP transport is closed")
        data = line.encode("utf-8") if isinstance(line, str) else line
        if not data.endswith(b"\n"):
            data += b"\n"
        if len(data) > MAX_LINE:
            raise ValueError("MCP line exceeds maximum length")
        with self._send_lock:
            self._sock.sendall(data)

    def recv_line(self, timeout: float = 5.0) -> str:
        if self._closed:
            raise ConnectionError("MCP transport is closed")
        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                raw = bytes(self._buffer[:newline])
                del self._buffer[: newline + 1]
                if raw.endswith(b"\r"):
                    raw = raw[:-1]
                return raw.decode("utf-8")
            if len(self._buffer) > MAX_LINE:
                raise ValueError("MCP line exceeds maximum length")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("MCP recv_line timed out")
            self._sock.settimeout(remaining)
            try:
                chunk = self._sock.recv(65536)
            except TimeoutError as exc:
                raise TimeoutError("MCP recv_line timed out") from exc
            except socket.timeout as exc:
                raise TimeoutError("MCP recv_line timed out") from exc
            except OSError as exc:
                raise ConnectionError("MCP connection closed") from exc
            if not chunk:
                raise ConnectionError("MCP connection closed")
            self._buffer.extend(chunk)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass


class McpClientTransport(NdjsonSocket):
    """Client view returned by Application.open_mcp()."""


class McpEndpoint:
    """TCP listener. Every accepted session talks to the same Application."""

    def __init__(self, application) -> None:
        self.application = application
        self.observed_calls: list[dict] = []
        self.token = secrets.token_urlsafe(32)
        self.host = "127.0.0.1"
        self.port: int | None = None
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._clients: list[NdjsonSocket] = []
        self._clients_lock = threading.Lock()
        self._closed = False
        self.tools_ready = threading.Event()

    def start(self) -> None:
        if self._sock is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, 0))
        sock.listen(32)
        sock.settimeout(0.5)
        self._sock = sock
        self.port = int(sock.getsockname()[1])
        self._thread = threading.Thread(
            target=self._accept_loop,
            name="jewelry-mcp-accept",
            daemon=True,
        )
        self._thread.start()

    def mcp_servers(self) -> list[dict]:
        if self.port is None:
            self.start()
        return [
            {
                "name": SERVER_NAME,
                "command": _absolute_python(),
                "args": [
                    "-m",
                    "jewelry.mcp_proxy",
                    "--host",
                    self.host,
                    "--port",
                    str(self.port),
                ],
                "env": [
                    {"name": "PYTHONPATH", "value": REPO_ROOT},
                    {"name": "JEWELRY_MCP_TOKEN", "value": self.token},
                    {"name": "PYTHONUNBUFFERED", "value": "1"},
                ],
            }
        ]

    def open_client(self) -> McpClientTransport:
        self.start()
        raw = socket.create_connection((self.host, self.port), timeout=5)
        transport = McpClientTransport(raw)
        with self._clients_lock:
            self._clients.append(transport)
        transport.send_line(self.token)
        return transport

    def close(self) -> None:
        self._closed = True
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        with self._clients_lock:
            clients = list(self._clients)
            self._clients.clear()
        for client in clients:
            client.close()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._thread = None

    def _accept_loop(self) -> None:
        while not self._closed and self._sock is not None:
            try:
                conn, _addr = self._sock.accept()
            except TimeoutError:
                continue
            except socket.timeout:
                continue
            except OSError:
                if self._closed:
                    return
                continue
            transport = NdjsonSocket(conn)
            with self._clients_lock:
                if self._closed:
                    transport.close()
                    return
                self._clients.append(transport)
            thread = threading.Thread(
                target=self._serve_connection,
                args=(transport,),
                name="jewelry-mcp-session",
                daemon=True,
            )
            thread.start()

    def _serve_connection(self, transport: NdjsonSocket) -> None:
        try:
            try:
                token = transport.recv_line(timeout=AUTH_TIMEOUT)
            except (TimeoutError, ConnectionError, UnicodeDecodeError, ValueError):
                return
            if token != self.token:
                return
            session = McpSession(self)
            while not self._closed:
                try:
                    raw = transport.recv_line(timeout=3600)
                except (TimeoutError, ConnectionError, UnicodeDecodeError, ValueError):
                    return
                if not raw.strip():
                    continue
                reply = session.dispatch(raw)
                if reply is None:
                    continue
                try:
                    transport.send_line(dumps(reply))
                except (ConnectionError, OSError):
                    return
        finally:
            transport.close()
            with self._clients_lock:
                try:
                    self._clients.remove(transport)
                except ValueError:
                    pass


class McpSession:
    def __init__(self, endpoint: McpEndpoint) -> None:
        self.endpoint = endpoint
        self._initialized = False

    def dispatch(self, raw: str) -> dict | None:
        message, parse_error = parse_line(raw)
        if parse_error is not None:
            return parse_error
        assert message is not None
        method = message.get("method")
        if "id" not in message:
            if isinstance(method, str) and method == "notifications/initialized":
                self._initialized = True
            return None
        request_id = message["id"]
        if not isinstance(method, str) or not method:
            return error(request_id, INVALID_REQUEST, "Invalid Request")
        params = message.get("params", {})
        if params is None:
            params = {}
        try:
            result = self._handle(method, params)
        except _RpcError as exc:
            return error(request_id, exc.code, exc.message)
        except Exception as exc:
            return error(request_id, INTERNAL_ERROR, str(exc) or "internal error")
        return success(request_id, result)

    def _handle(self, method: str, params: object) -> object:
        if method == "initialize":
            return self._initialize(params)
        if method == "ping":
            return {}
        if method == "logging/setLevel":
            return {}
        if method == "tools/list":
            return {"tools": self._tools()}
        if method == "tools/call":
            return self._call(params)
        if method == "resources/list":
            return {"resources": []}
        if method == "resources/templates/list":
            return {"resourceTemplates": []}
        if method == "prompts/list":
            return {"prompts": []}
        if method == "completion/complete":
            return {"completion": {"values": [], "total": 0, "hasMore": False}}
        raise _RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")

    def _initialize(self, params: object) -> dict:
        if params in (None, {}):
            params = {}
        elif not isinstance(params, dict):
            raise _RpcError(INVALID_PARAMS, "initialize params must be an object")
        self._initialized = True
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }

    def _tools(self) -> list[dict]:
        self.endpoint.tools_ready.set()
        tools = []
        for name in self.endpoint.application.operation_names():
            schema = _CREATE_RING_SCHEMA if name == "create_ring" else _GENERIC_SCHEMA
            tools.append(
                {
                    "name": name,
                    "description": f"Jewelry CAD operation {name}",
                    "inputSchema": schema,
                }
            )
        return tools

    def _call(self, params: object) -> dict:
        if not isinstance(params, dict):
            raise _RpcError(INVALID_PARAMS, "tools/call params must be an object")
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise _RpcError(INVALID_PARAMS, "tools/call requires a tool name")
        arguments = params.get("arguments", {})
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise _RpcError(INVALID_PARAMS, "tool arguments must be an object")
        if not self.endpoint.application.has_operation(name):
            raise _RpcError(INVALID_PARAMS, f"Unknown tool: {name}")
        envelope = self.endpoint.application.execute(name, arguments)
        self.endpoint.observed_calls.append(
            {"name": name, "arguments": arguments, "result": envelope}
        )
        return {
            "content": [{"type": "text", "text": json.dumps(envelope, allow_nan=False)}],
            "structuredContent": envelope,
            "isError": not bool(envelope.get("ok")),
        }


class _RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _absolute_python() -> str:
    import sys

    executable = Path(sys.executable)
    if not executable.is_absolute():
        executable = Path.cwd() / executable
    # A venv interpreter is often a symlink to the system Python. Resolving it
    # drops the virtualenv prefix, so the MCP child cannot import dependencies.
    return str(executable)
