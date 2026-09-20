"""Small synchronous MCP client; the adapter supplies a real stdio transport."""
import json
import time

from tests.support import MissingCapability


class McpClient:
    def __init__(self, case, app):
        self.case = case
        opener = getattr(app, 'open_mcp', None)
        if not callable(opener):
            raise MissingCapability('MISSING_CAPABILITY: app.open_mcp() real transport')
        self.transport = opener()
        case.addCleanup(self.transport.close)
        self.next_id = 0

    def send(self, message):
        self.transport.send_line(json.dumps(message, allow_nan=False))

    def receive(self, timeout=5.0):
        raw = self.transport.recv_line(timeout=timeout)
        self.case.assertIsInstance(raw, (str, bytes))
        message = json.loads(raw)
        self.case.assertIsInstance(message, dict)
        self.case.assertEqual(message.get('jsonrpc'), '2.0')
        return message

    def request(self, method, params):
        self.next_id += 1
        request_id = self.next_id
        self.send({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            message = self.receive(max(0.001, deadline-time.monotonic()))
            if message.get('id') == request_id and 'method' not in message:
                self.case.assertTrue(('result' in message) ^ ('error' in message), message)
                return message
        self.case.fail(f'MCP timed out: {method}, id={request_id}')

    def initialize(self):
        reply = self.request('initialize', {
            'protocolVersion': '2025-06-18', 'capabilities': {},
            'clientInfo': {'name': 'jewelry-mvp-tests', 'version': '1'},
        })
        self.case.assertIn('result', reply, reply)
        result = reply['result']
        self.case.assertEqual(result['protocolVersion'], '2025-06-18')
        self.case.assertIsInstance(result['capabilities']['tools'], dict)
        self.case.assertTrue(result['serverInfo']['name'])
        self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        return result

    def call(self, name, **arguments):
        return self.request('tools/call', {'name': name, 'arguments': arguments})

    def envelope(self, reply):
        self.case.assertIn('result', reply, reply)
        result = reply['result']
        envelope = result.get('structuredContent')
        if envelope is None:
            for item in result.get('content', []):
                if item.get('type') == 'text':
                    try:
                        candidate = json.loads(item['text'])
                    except (ValueError, TypeError):
                        continue
                    if isinstance(candidate, dict) and 'ok' in candidate:
                        envelope = candidate
                        break
        self.case.assertIsInstance(envelope, dict, reply)
        self.case.assertIsInstance(envelope.get('ok'), bool)
        self.case.assertEqual(result.get('isError', False), not envelope['ok'])
        if envelope['ok']:
            self.case.assertIn('value', envelope)
            self.case.assertNotIn('error', envelope)
        else:
            self.case.assertNotIn('value', envelope)
            self.case.assertNotIn('ref', envelope)
            for field in ('code', 'message'):
                self.case.assertIsInstance(envelope['error'][field], str)
                self.case.assertTrue(envelope['error'][field].strip())
        return envelope

    def ok(self, name, **arguments):
        envelope = self.envelope(self.call(name, **arguments))
        self.case.assertIs(envelope['ok'], True, envelope)
        return envelope['value']

    def error(self, name, **arguments):
        envelope = self.envelope(self.call(name, **arguments))
        self.case.assertIs(envelope['ok'], False, envelope)
        return envelope['error']
