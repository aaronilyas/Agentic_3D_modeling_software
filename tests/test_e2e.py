"""E01–E03 deterministic workflows across application, real MCP, and STL files.

These use one MCP session per scenario. ACP transport coverage is kept in C01–C04
so the workflow tests do not depend on live model inference.
"""
import copy
from pathlib import Path
import tempfile

from tests.export_assertions import assert_stl
from tests.fixtures import (CANONICAL_RING, CANONICAL_VOLUME, MANUFACTURING_PROFILE,
                           TESSELLATION_ERROR)
from tests.jewelry_fixtures import SETTING, SEAT, PRONGS, PRONG_CENTERS
from tests.mcp_client import McpClient
from tests.mesh_oracle import contains_point
from tests.support import ContractTestCase


class EndToEndTests(ContractTestCase):
    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory(prefix='jewelry-e2e-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.mcp = McpClient(self,self.app)
        self.mcp.initialize()

    def validate_export(self, ref, profile, filename):
        report = self.mcp.ok('validate',profile=profile)
        self.assertIs(report['ready'],True,report)
        self.assertFalse([f for f in report['findings'] if f['severity']=='error'])
        before = self.snapshot()
        self.assertEqual(report['revision'],before['revision'])
        self.assertEqual(self.mcp.ok('snapshot'),before)
        expected = self.ok('inspect',ref=ref)
        self.assertEqual(self.mcp.ok('inspect',ref=ref),expected)
        path = self.root/filename
        result = self.mcp.ok('export',ref=ref,path=str(path),format='stl',
                             validation=report,chord_tolerance=TESSELLATION_ERROR)
        self.assertEqual(result['revision'],report['revision'])
        mesh = assert_stl(self,path,expected)
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.mcp.ok('snapshot'),before)
        self.assertFalse(contains_point(mesh,[0,0,0]))
        return report,mesh

    def test_E01_empty_document_to_printable_canonical_ring(self):
        self.assertEqual(self.snapshot()['references'],[])
        ref = self.mcp.ok('create_ring',**CANONICAL_RING)['ref']
        self.assert_solid(ref,CANONICAL_VOLUME)
        self.assert_bounds(ref,[[-9.5,-9.5,-2],[9.5,9.5,2]])
        self.validate_export(ref,MANUFACTURING_PROFILE,'canonical.stl')
        self.assertEqual(self.snapshot()['references'],[ref])

    def test_E02_modified_ring_setting_seat_prongs_and_export_agree(self):
        ref = self.mcp.ok('create_ring',**CANONICAL_RING)['ref']
        self.mcp.ok('modify_ring',ref=ref,outer_radius=10.)
        self.assert_bounds(ref,[[-10,-10,-2],[10,10,2]])
        # Cross the local/MCP boundary in both directions inside one session.
        ref = self.ok('add_setting',ref=ref,**SETTING)['ref']
        ref = self.mcp.ok('cut_recess',ref=ref,**SEAT)['ref']
        ref = self.mcp.ok('repeat_prongs',ref=ref,diameter=.8,**PRONGS)['ref']
        self.assert_solid(ref)
        self.assertFalse(self.contains(ref,[10.0,0,2.75]))
        self.assertTrue(self.contains(ref,[10.0,0,2.4]))
        profile = MANUFACTURING_PROFILE | {'min_wall':.4,'min_prong':.6}
        _,mesh = self.validate_export(ref,profile,'decorated.stl')
        for x,y in PRONG_CENTERS:
            self.assertTrue(contains_point(mesh,[x,y,4.]))
        self.assertFalse(contains_point(mesh,[10.0,0,2.75]))
        self.assertTrue(contains_point(mesh,[10.0,0,2.4]))
        self.assertEqual(self.snapshot()['references'],[ref])

    def test_E03_invalid_export_blocked_then_corrected_under_unchanged_rules(self):
        profile = copy.deepcopy(MANUFACTURING_PROFILE)
        ref = self.mcp.ok('create_ring',**(CANONICAL_RING | {'outer_radius':8.5}))['ref']
        invalid = self.mcp.ok('validate',profile=profile)
        self.assertIs(invalid['ready'],False)
        self.assertTrue(any(f['code']=='THIN_FEATURE' and f['severity']=='error'
                            for f in invalid['findings']))
        before = self.snapshot()
        self.assertEqual(invalid['revision'],before['revision'])
        path = self.root/'corrected.stl'
        self.mcp.error('export',ref=ref,path=str(path),format='stl',
                       validation=invalid,chord_tolerance=TESSELLATION_ERROR)
        self.assertFalse(path.exists())
        self.assertEqual(list(self.root.iterdir()),[])
        self.assertEqual(self.snapshot(),before)
        self.mcp.ok('modify_ring',ref=ref,outer_radius=9.5)
        corrected,_ = self.validate_export(ref,profile,path.name)
        self.assertNotEqual(invalid['revision'],corrected['revision'])
        self.assertEqual(profile,MANUFACTURING_PROFILE)
        rules = lambda report: report['rules'] if 'rules' in report else report['profile']
        self.assertEqual(rules(invalid),rules(corrected))
        self.assert_solid(ref,CANONICAL_VOLUME)
        self.assertEqual(self.snapshot()['references'],[ref])
