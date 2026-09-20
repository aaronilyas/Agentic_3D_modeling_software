"""ACP wire client. Deterministic model responses are injected by the adapter.

The real CLI and its ACP/MCP transport remain under test; there is no fallback
that invokes app.execute() or trusts agent prose when wire results are absent.
"""
import json
import time

from tests.support import MissingCapability


def result_envelope(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, dict):
        return None
    if type(raw.get('ok')) is bool and ('value' in raw or 'error' in raw):
        return raw
    if 'structuredContent' in raw:
        return result_envelope(raw['structuredContent'])
    for block in raw.get('content', []):
        if block.get('type') == 'text':
            result = result_envelope(block.get('text'))
            if result is not None:
                return result
    return None


class AcpClient:
    def __init__(self, case, app, agent, cwd):
        self.case = case
        opener = getattr(app, 'open_acp', None)
        if not callable(opener):
            raise MissingCapability(f'MISSING_CAPABILITY: {agent} real ACP CLI adapter')
        self.transport = opener(agent, cwd=str(cwd), deterministic=True)
        case.addCleanup(self.transport.close)
        if not callable(getattr(self.transport, 'queue_tool_calls', None)):
            raise MissingCapability('MISSING_CAPABILITY: deterministic CLI model-backend injection')
        self.next_id = 0
        self.updates = []

    def request(self, method, params):
        self.next_id += 1
        request_id = self.next_id
        self.transport.send_line(json.dumps({'jsonrpc':'2.0','id':request_id,
                                            'method':method,'params':params},allow_nan=False))
        deadline = time.monotonic()+30
        while time.monotonic() < deadline:
            raw = self.transport.recv_line(timeout=max(.001,deadline-time.monotonic()))
            self.case.assertIsInstance(raw,(str,bytes))
            message = json.loads(raw)
            self.case.assertEqual(message['jsonrpc'],'2.0')
            if message.get('method') == 'session/update':
                self.updates.append(message['params'])
            elif 'method' in message and 'id' in message:
                self.case.fail(f'Unexpected ACP client request: {message["method"]}; '
                               'adapter must preauthorize only the isolated CAD tools')
            elif message.get('id') == request_id:
                self.case.assertTrue(('result' in message) ^ ('error' in message),message)
                return message
        self.case.fail(f'ACP timed out: {method}')

    def initialize(self):
        reply = self.request('initialize', {'protocolVersion':1,'clientCapabilities':{},
                             'clientInfo':{'name':'jewelry-tests','version':'1'}})
        self.case.assertIn('result',reply,reply)
        self.case.assertEqual(reply['result']['protocolVersion'],1)
        self.case.assertIsInstance(reply['result']['agentCapabilities'],dict)

    def new_session(self, cwd):
        self.initialize()
        reply = self.request('session/new',{'cwd':str(cwd),
                                           'mcpServers':self.transport.mcp_servers})
        self.case.assertIn('result',reply,reply)
        session = reply['result']['sessionId']
        self.case.assertIsInstance(session,str)
        self.case.assertTrue(session)
        return session

    def command(self, session, name, arguments, text=None):
        call = {'name':name,'arguments':arguments}
        self.transport.queue_tool_calls([call])
        before_trace = len(self.transport.observed_calls)
        before_updates = len(self.updates)
        reply = self.request('session/prompt',{'sessionId':session,'prompt':[
            {'type':'text','text':text or f'Perform {name} with these arguments: {json.dumps(arguments)}'}]})
        self.case.assertIn('result',reply,reply)
        self.case.assertEqual(reply['result']['stopReason'],'end_turn')
        observed = self.transport.observed_calls[before_trace:]
        self.case.assertEqual(len(observed),1,'Expected exactly one modeling call')
        self.case.assertEqual(observed[0]['name'],name)
        self.case.assertEqual(observed[0]['arguments'],arguments)
        outputs = []
        for event in self.updates[before_updates:]:
            self.case.assertEqual(event['sessionId'],session)
            update = event['update']
            if update['sessionUpdate'] in ('tool_call','tool_call_update'):
                envelope = result_envelope(update.get('rawOutput'))
                if envelope is not None:
                    outputs.append(envelope)
        self.case.assertTrue(outputs,'No structured tool result crossed ACP')
        envelope = outputs[-1]
        self.case.assertEqual(envelope,observed[0]['result'])
        self.case.assertIsInstance(envelope.get('ok'),bool)
        if envelope['ok']:
            self.case.assertIn('value',envelope)
            self.case.assertNotIn('error',envelope)
        else:
            self.case.assertNotIn('value',envelope)
            self.case.assertNotIn('ref',envelope)
            for field in ('code','message'):
                self.case.assertIsInstance(envelope['error'][field],str)
                self.case.assertTrue(envelope['error'][field])
        return envelope
