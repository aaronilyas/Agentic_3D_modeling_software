"""A01–A04: observable document behavior, no assumptions about topology IDs."""
from tests.fixtures import CANONICAL_BOUNDS, CANONICAL_VOLUME, VOLUME_REL_TOL
from tests.support import ContractTestCase, MissingCapability


class ApplicationTests(ContractTestCase):
    def geometry(self, ref):
        info = self.ok('inspect', ref=ref)
        return {key: info[key] for key in ('bounds', 'volume', 'topology')}

    def assert_geometry(self, ref, expected):
        actual = self.geometry(ref)
        self.assertEqual(actual['topology'], expected['topology'])
        self.assertAlmostEqual(actual['volume'], expected['volume'],
                               delta=expected['volume']*VOLUME_REL_TOL)
        self.assert_bounds(ref, expected['bounds'])

    def test_A01_authoritative_state_and_ambiguous_targeting(self):
        a = self.ring()
        b = self.ring(outer_radius=10.0)
        self.assertNotEqual(a, b)
        b_before = self.geometry(b)
        before = self.snapshot()
        self.ok('modify_ring', ref=a, outer_radius=10.5)
        self.assert_geometry(b, b_before)
        self.assert_bounds(a, [[-10.5,-10.5,-2], [10.5,10.5,2]])
        committed = self.snapshot()
        self.assertNotEqual(committed['revision'], before['revision'])
        self.assertEqual(set(committed['references']), {a,b})
        self.assertEqual(self.snapshot(), committed)
        self.error('modify_ring', outer_radius=11.0)
        self.assertEqual(self.snapshot(), committed)

    def test_A02_failure_after_intermediate_geometry_rolls_back_everything(self):
        ref = self.ring()
        before = self.snapshot()
        geometry = self.ok('inspect', ref=ref)
        fail_at = getattr(self.app, 'fail_at', None)
        if not callable(fail_at):
            raise MissingCapability('MISSING_CAPABILITY: fail_at(after_geometry) test hook')
        # The hook raises inside production's transaction after a temporary
        # candidate has been constructed, before any commit. triggered is an
        # observation from that hook, not a pre-validation rejection.
        with fail_at('modify_ring', 'after_geometry') as fault:
            self.error('modify_ring', ref=ref, outer_radius=10.0)
        self.assertIs(fault.triggered, True, 'The operation never reached intermediate work')
        self.assertEqual(self.snapshot(), before, 'geometry/refs/revision/history leaked')
        self.assertEqual(self.ok('inspect', ref=ref), geometry)
        self.assertEqual(self.snapshot()['references'], [ref])
        self.ok('modify_ring', ref=ref, outer_radius=10.0)
        self.assert_bounds(ref, [[-10,-10,-2], [10,10,2]])

    def empty_history(self, operation):
        before = self.snapshot()
        results = [self.app.execute(operation, {}) for _ in range(2)]
        for result in results:
            self.assertIsInstance(result.get('ok'), bool)
            if result['ok']:
                self.assertIn('value', result)
            else:
                self.assertNotIn('value', result)
                self.assertTrue(result['error']['code'])
                self.assertTrue(result['error']['message'])
        self.assertEqual(results[0], results[1], 'Empty-history policy is nondeterministic')
        self.assertEqual(self.snapshot(), before)

    def test_A03_create_modify_delete_undo_redo_and_branch(self):
        self.empty_history('undo')
        self.empty_history('redo')
        ref = self.ring()
        original = self.geometry(ref)
        self.ok('modify_ring', ref=ref, outer_radius=10.0)
        modified = self.geometry(ref)
        self.assertNotEqual(modified['volume'], original['volume'])
        self.ok('delete', ref=ref)
        self.assertEqual(self.snapshot()['references'], [])
        self.ok('undo')
        self.assert_geometry(ref, modified)
        self.ok('undo')
        self.assert_geometry(ref, original)
        self.ok('undo')
        self.assertEqual(self.snapshot()['references'], [])
        for expected in (original, modified):
            self.ok('redo')
            self.assert_geometry(ref, expected)
        self.ok('redo')
        self.assertEqual(self.snapshot()['references'], [])
        self.ok('undo')
        self.ok('modify_ring', ref=ref, outer_radius=11.0)
        self.assertEqual(self.snapshot()['redo'], [])
        self.empty_history('redo')
        self.assert_bounds(ref, [[-11,-11,-2], [11,11,2]])

    def test_A04_reference_lifecycle_and_branch_never_aliases_old_reference(self):
        ref = self.ring()
        self.assert_solid(ref, CANONICAL_VOLUME)
        self.assert_bounds(ref, CANONICAL_BOUNDS)
        before = self.snapshot()
        self.error('inspect', ref='never-issued:contract-test')
        self.assertEqual(self.snapshot(), before)
        self.ok('delete', ref=ref)
        deleted = self.snapshot()
        self.error('inspect', ref=ref)
        self.error('modify_ring', ref=ref, outer_radius=10.0)
        self.assertEqual(self.snapshot(), deleted)
        self.ok('undo')
        self.assert_solid(ref, CANONICAL_VOLUME)
        self.ok('redo')
        self.error('inspect', ref=ref)
        newer = self.ring()
        self.assertNotEqual(newer, ref)
        self.error('inspect', ref=ref)
        self.ok('undo')
        branched = self.ring(outer_radius=10.0)
        self.assertNotEqual(branched, newer)
        self.error('inspect', ref=newer)
        self.assert_solid(branched)
