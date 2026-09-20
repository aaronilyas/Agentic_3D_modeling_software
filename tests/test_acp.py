"""C01–C04: one deterministic ACP contract, parameterized over both real CLIs."""
import tempfile
from pathlib import Path

from tests.acp_client import AcpClient
from tests.export_assertions import assert_stl
from tests.fixtures import (CANONICAL_RING, CANONICAL_VOLUME, MANUFACTURING_PROFILE,
                           TESSELLATION_ERROR)
from tests.support import ContractTestCase


class AcpCases:
    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory(prefix='jewelry-acp-')
        self.addCleanup(directory.cleanup)
        self.cwd = Path(directory.name)
        self.acp = AcpClient(self,self.app,self.agent,self.cwd)

    def command(self, session, name, **arguments):
        envelope = self.acp.command(session,name,arguments)
        self.assertIs(envelope['ok'],True,envelope)
        return envelope['value']

    def rpc_error(self, reply):
        self.assertIn('error',reply,reply)
        self.assertNotIn('result',reply)
        self.assertIsInstance(reply['error']['code'],int)
        self.assertTrue(reply['error']['message'])

    def test_C01_connection_and_invalid_setup(self):
        self.acp.initialize()
        invalid = self.acp.request('session/new',{'cwd':'relative/not/absolute','mcpServers':[]})
        self.rpc_error(invalid)
        valid = self.acp.request('session/new',{'cwd':str(self.cwd),
                                               'mcpServers':self.acp.transport.mcp_servers})
        self.assertIn('result',valid,valid)
        self.assertIsInstance(valid['result']['sessionId'],str)
        self.assertTrue(valid['result']['sessionId'])
        self.assertEqual(self.snapshot()['references'],[])

    def test_C02_intended_dimensions_exactly_once_and_live_result(self):
        session = self.acp.new_session(self.cwd)
        envelope = self.acp.command(session,'create_ring',dict(CANONICAL_RING),
            text='Create one ring with inner radius 8 mm, outer radius 9.5 mm, and width 4 mm.')
        self.assertIs(envelope['ok'],True,envelope)
        ref = envelope['value']['ref']
        self.assertEqual(self.snapshot()['references'],[ref])
        self.assert_solid(ref,CANONICAL_VOLUME)
        self.assert_bounds(ref,[[-9.5,-9.5,-2],[9.5,9.5,2]])
        self.assertEqual(len(self.acp.transport.observed_calls),1)

    def test_C03_protocol_domain_and_manufacturing_results_remain_distinct(self):
        session = self.acp.new_session(self.cwd)
        before = self.snapshot()
        self.rpc_error(self.acp.request('session/prompt',{'sessionId':'never-issued',
                       'prompt':[{'type':'text','text':'Create a ring.'}]}))
        self.rpc_error(self.acp.request('unknown/protocol/method',{}))
        self.assertEqual(self.snapshot(),before)
        failed = self.acp.command(session,'modify_ring',{'ref':'never-issued','width':4.})
        self.assertIs(failed['ok'],False)
        self.assertEqual(self.snapshot(),before)
        ref = self.command(session,'create_ring',**(CANONICAL_RING | {'outer_radius':8.5}))['ref']
        report = self.command(session,'validate',profile=MANUFACTURING_PROFILE)
        self.assertIs(report['ready'],False)
        self.assertTrue(any(f['code']=='THIN_FEATURE' and f['severity']=='error'
                            for f in report['findings']))
        self.assertEqual(report['revision'],self.snapshot()['revision'])
        self.assertEqual(self.snapshot()['references'],[ref])

    def test_C04_sequential_create_modify_failed_modify_query_validate_export(self):
        session = self.acp.new_session(self.cwd)
        ref = self.command(session,'create_ring',**CANONICAL_RING)['ref']
        self.command(session,'modify_ring',ref=ref,outer_radius=10.)
        before = self.snapshot()
        failed = self.acp.command(session,'modify_ring',{'ref':ref,'outer_radius':7.})
        self.assertIs(failed['ok'],False)
        self.assertEqual(self.snapshot(),before)
        queried = self.command(session,'inspect',ref=ref)
        self.assertEqual(queried,self.ok('inspect',ref=ref))
        self.assert_bounds(ref,[[-10,-10,-2],[10,10,2]])
        report = self.command(session,'validate',profile=MANUFACTURING_PROFILE)
        self.assertIs(report['ready'],True)
        self.assertEqual(report['revision'],before['revision'])
        path = self.cwd/'ring.stl'
        exported = self.command(session,'export',ref=ref,path=str(path),format='stl',
                                validation=report,chord_tolerance=TESSELLATION_ERROR)
        self.assertEqual(exported['revision'],report['revision'])
        assert_stl(self,path,queried)
        self.assertEqual(self.snapshot(),before)
        creates = [call for call in self.acp.transport.observed_calls if call['name']=='create_ring']
        self.assertEqual(len(creates),1)


class CodexAcpTests(AcpCases,ContractTestCase):
    agent = 'codex'


class GrokAcpTests(AcpCases,ContractTestCase):
    agent = 'grok'
