"""M01–M04 use a real MCP JSON-RPC connection to the shared application."""
import json

from tests.fixtures import CANONICAL_RING, CANONICAL_VOLUME
from tests.mcp_client import McpClient
from tests.support import ContractTestCase


class McpTests(ContractTestCase):
    def setUp(self):
        super().setUp()
        self.mcp = McpClient(self, self.app)
        self.mcp.initialize()

    def test_M01_discover_schema_and_create_live_ring(self):
        reply = self.mcp.request('tools/list', {})
        self.assertIn('result', reply, reply)
        tools = reply['result']['tools']
        names = [tool['name'] for tool in tools]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn('create_ring', names)
        schema = next(t['inputSchema'] for t in tools if t['name'] == 'create_ring')
        self.assertEqual(schema['type'], 'object')
        self.assertTrue(set(CANONICAL_RING) <= set(schema['properties']))
        self.assertTrue(set(CANONICAL_RING) <= set(schema['required']))
        for field in CANONICAL_RING:
            self.assertEqual(schema['properties'][field]['type'], 'number')
        ref = self.mcp.ok('create_ring', **CANONICAL_RING)['ref']
        self.assertEqual(self.snapshot()['references'], [ref])
        self.assert_solid(ref, CANONICAL_VOLUME)
        self.assertFalse(self.contains(ref, [0,0,0]))

    def test_M02_both_interfaces_share_commits_and_references(self):
        ref = self.mcp.ok('create_ring', **CANONICAL_RING)['ref']
        self.mcp.ok('modify_ring', ref=ref, outer_radius=10.0)
        self.assert_bounds(ref, [[-10,-10,-2], [10,10,2]])
        self.assertEqual(self.mcp.ok('snapshot'), self.snapshot())
        self.ok('modify_ring', ref=ref, width=5.0)
        remote = self.mcp.ok('inspect', ref=ref)
        local = self.ok('inspect', ref=ref)
        self.assertEqual(remote, local)
        self.assert_bounds(ref, [[-10,-10,-2.5], [10,10,2.5]])
        self.assertEqual(self.mcp.ok('snapshot'), self.snapshot())
        self.assertEqual(self.snapshot()['references'], [ref])

    def test_M03_malformed_requests_are_atomic_and_session_recovers(self):
        cases = [
            ('invalid JSON', '{', -32700),
            ('invalid envelope', json.dumps({'jsonrpc':'1.0', 'id':101, 'method':'tools/list'}), -32600),
            ('unknown operation', json.dumps({'jsonrpc':'2.0','id':102,'method':'missing/method'}), -32601),
            ('unknown tool', json.dumps({'jsonrpc':'2.0','id':103,'method':'tools/call',
                                       'params':{'name':'missing_tool','arguments':{}}}), None),
            ('wrong type', json.dumps({'jsonrpc':'2.0','id':104,'method':'tools/call',
                                     'params':{'name':'create_ring','arguments':CANONICAL_RING | {'width':'wide'}}}), None),
            ('missing required', json.dumps({'jsonrpc':'2.0','id':105,'method':'tools/call',
                                           'params':{'name':'create_ring','arguments':{'width':4}}}), None),
        ]
        for label, raw, code in cases:
            with self.subTest(case=label):
                before = self.snapshot()
                self.mcp.transport.send_line(raw)
                reply = self.mcp.receive()
                if 'error' in reply:
                    self.assertNotIn('result', reply)
                    error = reply['error']
                    self.assertIsInstance(error['code'], int)
                    self.assertTrue(error['message'])
                    if code is not None:
                        self.assertEqual(error['code'], code)
                    else:
                        self.assertIn(error['code'], (-32601, -32602))
                else:
                    self.assertIsNone(code, 'Malformed protocol must produce a protocol error')
                    self.assertIs(self.mcp.envelope(reply)['ok'], False)
                self.assertEqual(self.snapshot(), before)
                ref = self.mcp.ok('create_ring', **CANONICAL_RING)['ref']
                self.assertIn(ref, self.snapshot()['references'])
                self.assert_solid(ref, CANONICAL_VOLUME)

    def test_M04_deleted_references_and_geometry_errors_survive_boundary(self):
        ref = self.ring()
        self.ok('delete', ref=ref)
        before = self.snapshot()
        local = self.error('inspect', ref=ref)
        remote = self.mcp.error('inspect', ref=ref)
        self.assertEqual(remote['code'], local['code'])
        self.assertEqual(self.snapshot(), before)
        # Union at one isolated point cannot be a manifold solid.
        a = self.ok('create_sphere', radius=1., center=[0,0,0])['ref']
        b = self.ok('create_sphere', radius=1., center=[2,0,0])['ref']
        before = self.snapshot()
        local = self.error('boolean', kind='union', left=a, right=b)
        remote = self.mcp.error('boolean', kind='union', left=a, right=b)
        self.assertEqual(remote['code'], local['code'])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(set(before['references']), {a,b})
        self.assert_solid(a)
        self.assert_solid(b)
