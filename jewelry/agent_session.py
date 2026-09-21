"""GUI-independent ACP client. CAD results come from the shared MCP endpoint."""
import json
import threading
import time
from pathlib import Path


class AgentError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class AgentSession:
    def __init__(self, application, agent, cwd, *, deterministic=False):
        self.application = application
        self.agent = agent
        self.cwd = str(Path(cwd).absolute())
        self.deterministic = deterministic
        self.transport = None
        self.session_id = None
        self.cancelled = threading.Event()
        self._next_id = 0
        self.tool_failures = []
        self._tool_calls = {}

    def start(self, activity):
        if self.cancelled.is_set():
            raise AgentError('CANCELLED', 'Agent startup cancelled')
        activity('Starting agent')
        self.application.endpoint().tools_ready.clear()
        try:
            self.transport = self.application.open_acp(
                self.agent, cwd=self.cwd, deterministic=self.deterministic, cancel_event=self.cancelled)
            reply = self.request('initialize', {
                'protocolVersion': 1, 'clientCapabilities': {},
                'clientInfo': {'name': 'jewelry-cad', 'version': '0.1.0'}}, activity)
            if reply.get('protocolVersion') != 1:
                raise AgentError('ACP_PROTOCOL', 'Unsupported ACP protocol version')
            reply = self.request('session/new', {
                'cwd': self.cwd, 'mcpServers': self.transport.mcp_servers}, activity)
            self.session_id = reply.get('sessionId')
            if not isinstance(self.session_id, str) or not self.session_id:
                raise AgentError('ACP_PROTOCOL', 'Agent did not return a session ID')
            deadline = time.monotonic() + 10
            ready = self.application.endpoint().tools_ready
            while not ready.wait(timeout=.1):
                if self.cancelled.is_set():
                    raise AgentError('CANCELLED', 'Agent startup cancelled')
                if time.monotonic() >= deadline:
                    raise AgentError('MCP_CONNECTION', 'Agent did not discover the Jewelry MCP tools')
        except Exception:
            self.close()
            raise

    def request(self, method, params, activity, chunks=None):
        self._next_id += 1
        request_id = self._next_id
        self.transport.send_line(json.dumps({'jsonrpc': '2.0', 'id': request_id,
                                             'method': method, 'params': params}))
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if self.cancelled.is_set():
                raise AgentError('CANCELLED', 'Agent turn cancelled; completed CAD operations remain undoable')
            try:
                raw = self.transport.recv_line(timeout=.2)
            except TimeoutError:
                continue
            try:
                message = json.loads(raw)
                if not isinstance(message, dict) or message.get('jsonrpc') != '2.0':
                    raise ValueError('invalid JSON-RPC envelope')
            except ValueError as exc:
                raise AgentError('ACP_PROTOCOL', str(exc)) from exc
            if message.get('method') == 'session/update':
                update = message.get('params', {}).get('update', {})
                kind = update.get('sessionUpdate')
                if kind == 'agent_message_chunk' and chunks is not None:
                    content = update.get('content', {})
                    if content.get('type') == 'text':
                        chunks.append(content.get('text', ''))
                elif kind in ('tool_call', 'tool_call_update'):
                    call_id = update.get('toolCallId')
                    self._tool_calls.setdefault(call_id, {}).update(update)
                    if update.get('status') == 'failed':
                        self.tool_failures.append(self._tool_calls[call_id].get('title', 'Agent tool call'))
                    activity('Applying CAD operation')
            elif 'method' in message and 'id' in message:
                # The desktop advertises no filesystem/terminal capabilities. Only
                # Jewelry MCP permissions are approved, never arbitrary CLI tools.
                response = {'jsonrpc': '2.0', 'id': message['id']}
                if message['method'] == 'session/request_permission':
                    params = message.get('params', {})
                    requested = params.get('toolCall', {})
                    tool = self._tool_calls.get(requested.get('toolCallId'), {}) | requested
                    raw_input = tool.get('rawInput') or {}
                    server = raw_input.get('server', raw_input.get('serverName')) if isinstance(raw_input, dict) else None
                    title = tool.get('title', '')
                    cad = server == 'jewelry' or title.startswith(('mcp__jewelry__', 'jewelry__', 'jewelry/'))
                    option = next((o for o in params.get('options', [])
                                   if o.get('kind') == 'allow_once'), None) if cad else None
                    outcome = {'outcome': 'selected', 'optionId': option['optionId']} if option else {'outcome': 'cancelled'}
                    response['result'] = {'outcome': outcome}
                else:
                    response['error'] = {'code': -32601, 'message': 'Desktop client capability unavailable'}
                self.transport.send_line(json.dumps(response))
            elif message.get('id') == request_id:
                if 'error' in message:
                    detail = str(message['error'].get('message', message['error']))
                    code = 'ACP_STARTUP' if method in ('initialize', 'session/new') else 'ACP_PROTOCOL'
                    raise AgentError(code, detail)
                if not isinstance(message.get('result'), dict):
                    raise AgentError('ACP_PROTOCOL', 'Missing ACP result')
                return message['result']
        raise AgentError('ACP_TIMEOUT', f'{method} timed out; check CLI authentication and model configuration')

    def turn(self, prompt, activity, *, context='', calls=None):
        if self.transport is None:
            self.start(activity)
        self.tool_failures.clear()
        self._tool_calls.clear()
        before = len(self.transport.observed_calls)
        if calls is not None:
            self.transport.queue_tool_calls(calls)
        chunks = []
        activity('Thinking')
        reply = self.request('session/prompt', {
            'sessionId': self.session_id, 'prompt': [{'type': 'text', 'text':
                'You are the Jewelry CAD design assistant. Use the jewelry MCP tools for all CAD '
                'operations on the live document. Never use files or shell commands to modify CAD. '
                'Inspect snapshot and inspect tools for current references; dimensions are mm. '
                'Do not claim a CAD operation succeeded unless its structured result has ok=true. '
                'Report manufacturing findings separately from tool failures. '
                + context + '\nUser request: ' + prompt}]}, activity, chunks)
        if reply.get('stopReason') != 'end_turn':
            raise AgentError('ACP_STOPPED', f"Agent stopped: {reply.get('stopReason', 'unknown reason')}")
        return ''.join(chunks), list(self.transport.observed_calls[before:])

    def close(self):
        if self.transport is not None:
            self.transport.close()
            self.transport = None
        self.session_id = None
