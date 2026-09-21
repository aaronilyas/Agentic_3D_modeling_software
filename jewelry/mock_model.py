"""Local OpenAI-compatible mock. Never calls execute() or paid inference."""

from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, allow_nan=False).encode("utf-8")


def _normalize_tools(payload: dict) -> list[dict]:
    tools = []
    raw = payload.get("tools") or payload.get("functions") or []
    if not isinstance(raw, list):
        return tools

    def add(name: object, parameters: object) -> None:
        if isinstance(name, str) and name:
            tools.append({"name": name, "parameters": parameters or {}})

    def walk(item: dict, prefix: str | None = None) -> None:
        if item.get("type") == "function" and isinstance(item.get("function"), dict):
            function = item["function"]
            name = function.get("name")
            params = function.get("parameters") or function.get("input_schema") or {}
            add(name, params)
            if prefix and name:
                add(f"{prefix}__{name}", params)
            return
        if item.get("type") == "namespace" and isinstance(item.get("tools"), list):
            namespace = item.get("name")
            for nested in item["tools"]:
                if isinstance(nested, dict):
                    walk(nested, namespace if isinstance(namespace, str) else prefix)
            return
        name = item.get("name")
        params = item.get("parameters") or item.get("inputSchema") or item.get("input_schema") or {}
        add(name, params)
        if prefix and name:
            add(f"{prefix}__{name}", params)

    for item in raw:
        if isinstance(item, dict):
            walk(item)
    return tools


def _messages(payload: dict) -> list[dict]:
    if isinstance(payload.get("messages"), list):
        return [item for item in payload["messages"] if isinstance(item, dict)]
    incoming = payload.get("input")
    if isinstance(incoming, list):
        return [item for item in incoming if isinstance(item, dict)]
    if isinstance(incoming, str):
        return [{"role": "user", "content": incoming}]
    return []


def _has_tool_result(messages: list[dict]) -> bool:
    for item in messages:
        role = item.get("role")
        kind = item.get("type")
        if role == "tool" or kind in {
            "function_call_output",
            "custom_tool_call_output",
            "tool_result",
            "tool",
            "mcp_call",
        }:
            return True
        if item.get("tool_call_id") or item.get("call_id") and kind == "function_call_output":
            return True
        content = item.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") in {
                    "tool_result",
                    "function_call_output",
                    "tool_use",
                }:
                    if block.get("type") == "function_call_output":
                        return True
                    if block.get("type") == "tool_result":
                        return True
    return False


def _message_text(item: dict) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return ""


def lift_envelope(raw: object) -> dict | None:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return None
    if not isinstance(raw, dict):
        return None
    if type(raw.get("ok")) is bool and ("value" in raw or "error" in raw):
        return raw
    if "structuredContent" in raw:
        lifted = lift_envelope(raw.get("structuredContent"))
        if lifted is not None:
            return lifted
    if "result" in raw:
        lifted = lift_envelope(raw.get("result"))
        if lifted is not None:
            return lifted
    output = raw.get("output")
    if isinstance(output, dict):
        for key in (
            "OkayOutput",
            "ErrorOutput",
            "okay_output",
            "error_output",
            "Okay",
            "Error",
            "okay",
            "error",
            "Ok",
            "ok_output",
        ):
            if key in output:
                lifted = lift_envelope(output[key])
                if lifted is not None:
                    return lifted
        lifted = lift_envelope(output)
        if lifted is not None:
            return lifted
    elif isinstance(output, str):
        lifted = lift_envelope(output)
        if lifted is not None:
            return lifted
    for block in raw.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            lifted = lift_envelope(block.get("text"))
            if lifted is not None:
                return lifted
        elif isinstance(block, str):
            lifted = lift_envelope(block)
            if lifted is not None:
                return lifted
    return None


def _envelope_in_messages(messages: list[dict]) -> bool:
    for item in messages:
        if lift_envelope(item) is not None:
            return True
        content = item.get("content")
        if lift_envelope(content) is not None:
            return True
        if lift_envelope(_message_text(item)) is not None:
            return True
    return False


def _current_turn(messages: list[dict]) -> list[dict]:
    last_user = -1
    for index, item in enumerate(messages):
        role = item.get("role")
        if role == "user" or (item.get("type") == "message" and role == "user"):
            last_user = index
    if last_user < 0:
        return messages
    return messages[last_user + 1 :]


def _is_prefetch(payload: dict, tools: list[dict], messages: list[dict]) -> bool:
    names = {tool["name"] for tool in tools}
    if names and names <= {"session_title", "set_session_title"}:
        return True
    if not tools:
        return True
    if not messages:
        return True
    has_user = any(item.get("role") == "user" or item.get("type") == "message" for item in messages)
    return not has_user


def _property_names(parameters: object) -> set[str]:
    if not isinstance(parameters, dict):
        return set()
    props = parameters.get("properties")
    if isinstance(props, dict):
        return set(props)
    return set()


def _enum_values(parameters: object, field: str) -> list[str]:
    if not isinstance(parameters, dict):
        return []
    props = parameters.get("properties")
    if not isinstance(props, dict):
        return []
    spec = props.get(field)
    if not isinstance(spec, dict):
        return []
    values = spec.get("enum") or []
    return [value for value in values if isinstance(value, str)]


class MockModel:
    def __init__(self) -> None:
        self.host = "127.0.0.1"
        self.port: int | None = None
        self.requests: list[dict] = []
        self.decisions: list[dict] = []
        self._queue: list[dict] = []
        self._awaiting = False
        self._inflight = False
        self._baseline = 0
        self.observed_len = lambda: 0
        self.mcp_ready: threading.Event | None = None
        self._lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        if self.port is None:
            raise RuntimeError("mock model is not running")
        return f"http://{self.host}:{self.port}/v1"

    def start(self) -> None:
        mock = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args) -> None:
                return

            def _read_json(self) -> dict:
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length <= 0:
                    return {}
                raw = self.rfile.read(length)
                if not raw:
                    return {}
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    return {}
                return payload if isinstance(payload, dict) else {}

            def _send(self, status: int, payload: object, content_type: str = "application/json") -> None:
                body = payload if isinstance(payload, bytes) else _json_bytes(payload)
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _send_sse(self, events: list[str]) -> None:
                if len(events) == 1 and "\n" in events[0]:
                    body = (events[0] + "\n\n").encode("utf-8")
                else:
                    body = ("\n\n".join(events) + "\n\n").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self) -> None:
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.end_headers()

            def do_GET(self) -> None:
                path = urlparse(self.path).path.rstrip("/")
                if path in {"/v1/models", "/models"}:
                    self._send(200, mock.models_payload())
                    return
                self._send(404, {"error": {"message": "not found"}})

            def do_POST(self) -> None:
                path = urlparse(self.path).path.rstrip("/")
                payload = self._read_json()
                mock.requests.append({"path": path, "body": payload})
                if path in {"/v1/models", "/models"}:
                    self._send(200, mock.models_payload())
                    return
                if path in {"/v1/chat/completions", "/chat/completions"}:
                    completion, streamed = mock.chat_completion(payload)
                    if payload.get("stream"):
                        self._send_sse(_chat_sse(completion, streamed))
                    else:
                        self._send(200, completion)
                    return
                if path in {"/v1/responses", "/responses"}:
                    response, streamed = mock.responses_api(payload)
                    if payload.get("stream"):
                        self._send_sse(_responses_sse(response))
                    else:
                        self._send(200, response)
                    return
                if path in {"/v1/messages", "/messages"}:
                    completion, streamed = mock.chat_completion(payload)
                    self._send(200, _to_messages(completion, streamed))
                    return
                self._send(404, {"error": {"message": "not found"}})

        class Server(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address) -> None:
                return

        httpd = Server((self.host, 0), Handler)
        self._httpd = httpd
        self.port = int(httpd.server_address[1])
        self._thread = threading.Thread(target=httpd.serve_forever, name="jewelry-mock-model", daemon=True)
        self._thread.start()

    def close(self) -> None:
        httpd = self._httpd
        self._httpd = None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)
        self._thread = None

    def queue_tool_calls(self, calls: list[dict]) -> None:
        with self._lock:
            self._queue = [dict(call) for call in calls]
            self._awaiting = False
            self._inflight = False
            self._baseline = int(self.observed_len())

    def models_payload(self) -> dict:
        return {
            "object": "list",
            "data": [
                {
                    "id": "jewelry-mock",
                    "object": "model",
                    "created": 0,
                    "owned_by": "jewelry",
                }
            ],
        }

    def chat_completion(self, payload: dict) -> tuple[dict, dict | None]:
        decision = self._decide(payload)
        model = payload.get("model") or "jewelry-mock"
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        if decision["kind"] == "tool":
            call_id = f"call_{uuid.uuid4().hex[:12]}"
            tool_call = {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": decision["name"],
                    "arguments": json.dumps(decision["arguments"], allow_nan=False),
                },
            }
            message = {"role": "assistant", "content": None, "tool_calls": [tool_call]}
            completion = {
                "id": completion_id,
                "object": "chat.completion",
                "created": 0,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
            return completion, tool_call
        message = {"role": "assistant", "content": decision["text"]}
        completion = {
            "id": completion_id,
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        return completion, None

    def responses_api(self, payload: dict) -> tuple[dict, dict | None]:
        decision = self._decide(payload)
        model = payload.get("model") or "jewelry-mock"
        response_id = f"resp_{uuid.uuid4().hex[:12]}"
        created_at = int(time.time())
        output: list[dict] = []
        include = payload.get("include") or []
        if isinstance(include, list) and "reasoning.encrypted_content" in include:
            output.append(
                {
                    "type": "reasoning",
                    "id": f"rs_{uuid.uuid4().hex[:12]}",
                    "summary": [],
                    "encrypted_content": "gAAAAA==",
                }
            )
        tool_item = None
        if decision["kind"] == "tool":
            call_id = f"call_{uuid.uuid4().hex[:12]}"
            payload_args = json.dumps(decision["arguments"], allow_nan=False)
            if decision.get("style") == "custom" or decision["name"].startswith("mcp__"):
                short = decision["name"].split("__")[-1]
                tool_item = {
                    "type": "function_call",
                    "id": f"fc_{uuid.uuid4().hex[:12]}",
                    "call_id": call_id,
                    "name": short,
                    "namespace": "mcp__jewelry",
                    "arguments": payload_args,
                    "status": "completed",
                }
            else:
                tool_item = {
                    "type": "function_call",
                    "id": f"fc_{uuid.uuid4().hex[:12]}",
                    "call_id": call_id,
                    "name": decision["name"],
                    "arguments": payload_args,
                    "status": "completed",
                }
            output.append(tool_item)
        else:
            output.append(
                {
                    "type": "message",
                    "id": f"msg_{uuid.uuid4().hex[:12]}",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": decision["text"],
                            "annotations": [],
                        }
                    ],
                    "status": "completed",
                }
            )
        response = {
            "id": response_id,
            "object": "response",
            "created_at": created_at,
            "status": "completed",
            "model": model,
            "output": output,
            "error": None,
            "incomplete_details": None,
            "parallel_tool_calls": True,
            "store": False,
            "usage": {
                "input_tokens": 1,
                "output_tokens": 1,
                "total_tokens": 2,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 0},
            },
        }
        return response, tool_item

    def _wait_for_mcp(self) -> None:
        ready = self.mcp_ready
        if ready is None or ready.is_set():
            return
        ready.wait(timeout=8.0)

    def _decide(self, payload: dict) -> dict:
        tools = _normalize_tools(payload)
        messages = _messages(payload)
        current = _current_turn(messages)
        if self._queue:
            self._wait_for_mcp()
        with self._lock:
            observed = int(self.observed_len())
            executed = observed > self._baseline
            envelope = _envelope_in_messages(current)
            if executed or envelope:
                if self._queue:
                    self._queue.pop(0)
                self._awaiting = False
                self._inflight = False
                self._baseline = observed
                return {"kind": "text", "text": "done"}
            if self._queue:
                queued = self._queue[0]
                mapped = map_tool_call(tools, queued["name"], queued.get("arguments") or {})
                if mapped is not None:
                    failed = _has_tool_result(current) and not envelope
                    if self._inflight and not failed:
                        self.decisions.append({"why": "inflight"})
                        return {"kind": "text", "text": ""}
                    self._awaiting = True
                    self._inflight = True
                    self.decisions.append({"why": "tool", "name": mapped["name"]})
                    return mapped
            if _is_prefetch(payload, tools, messages):
                decision = {"kind": "text", "text": "Create ring"}
                self.decisions.append({"why": "prefetch", "tools": [tool["name"] for tool in tools[:8]]})
                return decision
            decision = {"kind": "text", "text": "done" if _has_tool_result(current) else "Create ring"}
            self.decisions.append({"why": "fallback", "mapped": None})
            return decision


def map_tool_call(tools: list[dict], name: str, arguments: dict) -> dict | None:
    by_name = {tool["name"]: tool for tool in tools}
    catalog = f"jewelry__{name}"
    blocked = {
        "search_tool",
        "use_tool",
        "run_terminal_command",
        "read_file",
        "write",
        "search_replace",
        "list_dir",
        "grep",
        "shell",
        "bash",
        "session_title",
    }
    namespaced = f"mcp__jewelry__{name}"
    if namespaced in by_name and name in by_name:
        return {"kind": "tool", "name": name, "arguments": arguments, "style": "custom"}
    for candidate in (namespaced, catalog, name):
        if candidate in by_name and candidate not in blocked:
            style = "custom" if candidate.startswith("mcp__") else "function"
            return {"kind": "tool", "name": candidate, "arguments": arguments, "style": style}
    if "use_tool" in by_name:
        return {
            "kind": "tool",
            "name": "use_tool",
            "arguments": _use_tool_arguments(by_name["use_tool"], catalog, arguments),
        }
    return None


def _use_tool_arguments(tool: dict, catalog: str, arguments: dict) -> dict:
    fields = _property_names(tool.get("parameters"))
    name_field = next(
        (field for field in ("tool_name", "name", "tool") if field in fields),
        "tool_name",
    )
    args_field = next(
        (field for field in ("tool_input", "arguments", "args", "input") if field in fields),
        "tool_input",
    )
    enums = _enum_values(tool.get("parameters"), name_field)
    chosen = catalog
    if enums:
        if catalog in enums:
            chosen = catalog
        else:
            suffix = catalog.split("__")[-1]
            matches = [value for value in enums if value.endswith(f"__{suffix}")]
            if matches:
                chosen = matches[0]
    return {name_field: chosen, args_field: arguments}


def _chat_sse(completion: dict, tool_call: dict | None) -> list[str]:
    model = completion.get("model")
    completion_id = completion.get("id")
    if tool_call is None:
        text = completion["choices"][0]["message"].get("content") or ""
        first = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": 0,
            "model": model,
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}],
        }
        last = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": 0,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        return [f"data: {json.dumps(first, allow_nan=False)}", f"data: {json.dumps(last, allow_nan=False)}", "data: [DONE]"]
    first = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": tool_call["id"],
                            "type": "function",
                            "function": {"name": tool_call["function"]["name"], "arguments": ""},
                        }
                    ],
                },
                "finish_reason": None,
            }
        ],
    }
    second = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {"index": 0, "function": {"arguments": tool_call["function"]["arguments"]}}
                    ]
                },
                "finish_reason": None,
            }
        ],
    }
    last = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
    }
    return [
        f"data: {json.dumps(first, allow_nan=False)}",
        f"data: {json.dumps(second, allow_nan=False)}",
        f"data: {json.dumps(last, allow_nan=False)}",
        "data: [DONE]",
    ]


def _responses_sse(response: dict) -> list[str]:
    created = int(time.time())
    response.setdefault("created_at", created)
    skeleton = {
        "id": response.get("id"),
        "object": response.get("object", "response"),
        "created_at": response.get("created_at", created),
        "status": "in_progress",
        "model": response.get("model"),
        "output": [],
    }
    seq = 0

    def numbered(event: dict) -> dict:
        nonlocal seq
        event["sequence_number"] = seq
        seq += 1
        return event

    events = [
        numbered({"type": "response.created", "response": dict(skeleton)}),
        numbered({"type": "response.in_progress", "response": dict(skeleton)}),
    ]
    for index, item in enumerate(response.get("output", [])):
        events.append(
            numbered(
                {
                    "type": "response.output_item.added",
                    "output_index": index,
                    "item": item,
                }
            )
        )
        if item.get("type") == "message":
            for block in item.get("content") or []:
                if block.get("type") == "output_text":
                    events.append(
                        numbered(
                            {
                                "type": "response.output_text.delta",
                                "output_index": index,
                                "content_index": 0,
                                "item_id": item.get("id"),
                                "delta": block.get("text") or "",
                            }
                        )
                    )
                    events.append(
                        numbered(
                            {
                                "type": "response.output_text.done",
                                "output_index": index,
                                "content_index": 0,
                                "item_id": item.get("id"),
                                "text": block.get("text") or "",
                            }
                        )
                    )
        if item.get("type") in {"function_call", "custom_tool_call"}:
            added = dict(item)
            added["status"] = "in_progress"
            if item.get("type") == "function_call":
                added["arguments"] = ""
                delta_type = "response.function_call_arguments.delta"
                done_type = "response.function_call_arguments.done"
                body = item.get("arguments") or ""
            else:
                added["input"] = ""
                delta_type = "response.custom_tool_call_input.delta"
                done_type = "response.custom_tool_call_input.done"
                body = item.get("input") or ""
            events[-1]["item"] = added
            events.append(
                numbered(
                    {
                        "type": delta_type,
                        "output_index": index,
                        "delta": body,
                    }
                )
            )
            events.append(
                numbered(
                    {
                        "type": done_type,
                        "output_index": index,
                        "item_id": item.get("id"),
                        "input" if item.get("type") == "custom_tool_call" else "arguments": body,
                    }
                )
            )
        events.append(
            numbered(
                {
                    "type": "response.output_item.done",
                    "output_index": index,
                    "item": item,
                }
            )
        )
    events.append(numbered({"type": "response.completed", "response": response}))
    lines = []
    for event in events:
        payload = json.dumps(event, allow_nan=False)
        lines.append(f"event: {event['type']}")
        lines.append(f"data: {payload}")
        lines.append("")
    lines.append("data: [DONE]")
    lines.append("")
    return ["\n".join(lines).rstrip("\n")]


def _to_messages(completion: dict, tool_call: dict | None) -> dict:
    if tool_call is None:
        return {
            "id": completion.get("id"),
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": completion["choices"][0]["message"].get("content") or ""}],
            "stop_reason": "end_turn",
            "model": completion.get("model"),
        }
    return {
        "id": completion.get("id"),
        "type": "message",
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": tool_call["id"],
                "name": tool_call["function"]["name"],
                "input": json.loads(tool_call["function"]["arguments"]),
            }
        ],
        "stop_reason": "tool_use",
        "model": completion.get("model"),
    }
