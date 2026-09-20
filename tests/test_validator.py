"""V01–V07 manufacturing rules, direct invalid geometry and revision integrity."""
import copy
import math

from tests.fixtures import CANONICAL_VOLUME, MANUFACTURING_PROFILE, GEOMETRY_ABS_TOL
from tests.jewelry_fixtures import ring_with_setting
from tests.mesh_fixtures import (_open_tetrahedron, _nonmanifold_edge_mesh, _vertex_kiss_mesh,
    _self_intersecting_mesh, _zero_thickness_sandwich, _coplanar_tetrahedron)
from tests.support import ContractTestCase


class ValidatorTests(ContractTestCase):
    def _rules(self, report):
        self.assertIsInstance(report, dict)
        rules = report['profile'] if 'profile' in report else report['rules']
        self.assertIsInstance(rules, dict)
        return rules

    def _assert_report(self, report, profile):
        rules = self._rules(report)
        self.assertIsInstance(report['revision'], int)
        self.assertIsInstance(report['ready'], bool)
        self.assertIsInstance(report['findings'], list)
        self.assertEqual(rules['id'], profile['id'])
        self.assertEqual(rules['version'], profile['version'])
        self.assertEqual(rules['units'], 'mm')
        self.assertEqual(rules['min_wall'], profile['min_wall'])
        self.assertEqual(rules['min_prong'], profile['min_prong'])
        self.assertEqual(rules['max_components'], profile['max_components'])
        for finding in report['findings']:
            self.assertIsInstance(finding['code'], str)
            self.assertTrue(finding['code'].strip())
            self.assertIn(finding['severity'], ('error', 'warning'))
            self.assertIsInstance(finding['message'], str)
            self.assertTrue(finding['message'].strip())
        errors = [item for item in report['findings'] if item['severity'] == 'error']
        self.assertEqual(report['ready'], not errors, report)
        return report

    def _codes(self, report):
        return [item['code'] for item in report['findings']]

    def _assert_ready(self, report, profile):
        self._assert_report(report, profile)
        self.assertIs(report['ready'], True, report)
        self.assertFalse(
            [item for item in report['findings'] if item['severity'] == 'error'],
            report['findings'],
        )

    def _assert_finding(self, report, profile, code):
        self._assert_report(report, profile)
        self.assertIs(report['ready'], False, report)
        self.assertIn(code, self._codes(report), report['findings'])
        match = next(item for item in report['findings'] if item['code'] == code)
        self.assertEqual(match['severity'], 'error')
        return match

    def test_V01_valid_ring_is_repeatable_revision_bound_and_pure(self):
        ref = self.ring()
        self.assert_solid(ref, CANONICAL_VOLUME)
        before = self.snapshot()
        profile = copy.deepcopy(MANUFACTURING_PROFILE)
        results = [self.ok('validate', profile=profile) for _ in range(2)]
        for report in results:
            self._assert_ready(report, profile)
            self.assertEqual(report['revision'], before['revision'])
        for field in ('revision', 'ready', 'findings'):
            self.assertEqual(results[0][field], results[1][field])
        self.assertEqual(self._rules(results[0]), self._rules(results[1]))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(profile, MANUFACTURING_PROFILE)

    def test_V02_open_boundary_nonmanifold_edge_and_vertex(self):
        for name, mesh, code in (
            ('open shell', _open_tetrahedron(), 'OPEN_SHELL'),
            ('three faces per edge', _nonmanifold_edge_mesh(), 'NON_MANIFOLD'),
            ('vertex contact', _vertex_kiss_mesh(), 'NON_MANIFOLD'),
        ):
            with self.subTest(fixture=name):
                before = self.snapshot()
                report = self.ok('validate_mesh', profile=MANUFACTURING_PROFILE, **mesh)
                self._assert_finding(report, MANUFACTURING_PROFILE, code)
                self.assertEqual(self.snapshot(), before)

    def test_V03_self_intersection_and_resolved_boolean_control(self):
        report = self.ok('validate_mesh', profile=MANUFACTURING_PROFILE,
                         **_self_intersecting_mesh())
        self._assert_finding(report, MANUFACTURING_PROFILE, 'SELF_INTERSECTION')
        a = self.ok('create_box', size=[4,4,4], origin=[0,0,0])['ref']
        b = self.ok('create_box', size=[4,4,4], origin=[2,0,0])['ref']
        resolved = self.ok('boolean', kind='union', left=a, right=b)['ref']
        # Adapters can retain source bodies or consume them. Validate only the
        # resolved document, not the two overlapping construction operands.
        for ref in self.snapshot()['references']:
            if ref != resolved:
                self.ok('delete', ref=ref)
        self.assert_solid(resolved, 96.0)
        self._assert_ready(self.ok('validate', profile=MANUFACTURING_PROFILE), MANUFACTURING_PROFILE)

    def test_V04_zero_volume_and_collapsed_geometry_cannot_be_printable(self):
        for mesh in (_zero_thickness_sandwich(), _coplanar_tetrahedron()):
            with self.subTest(mesh=mesh):
                report = self.ok('validate_mesh', profile=MANUFACTURING_PROFILE, **mesh)
                self._assert_finding(report, MANUFACTURING_PROFILE, 'ZERO_THICKNESS')

    def test_V05_wall_and_prong_limits_are_inclusive_and_configurable(self):
        for kind, minimum in (('wall',1.0), ('prong',0.8)):
            for measured in (minimum-0.2, minimum, minimum+0.2):
                with self.subTest(feature=kind, size=measured):
                    profile = MANUFACTURING_PROFILE | {'min_wall': 1.0 if kind == 'wall' else 0.4}
                    ref = (self.ring(outer_radius=8+measured) if kind == 'wall'
                           else ring_with_setting(self, prong_diameter=measured))
                    before = self.snapshot()
                    report = self.ok('validate', profile=profile)
                    if measured < minimum:
                        finding = self._assert_finding(report, profile, 'THIN_FEATURE')
                        self.assertEqual(finding['feature_type'], kind)
                        self.assertAlmostEqual(finding['measured'], measured, delta=GEOMETRY_ABS_TOL)
                        self.assertEqual(finding['required'], minimum)
                    else:
                        self._assert_ready(report, profile)
                    relaxed = profile | {f'min_{kind}': measured-0.1}
                    tightened = profile | {f'min_{kind}': measured+0.1}
                    self._assert_ready(self.ok('validate', profile=relaxed), relaxed)
                    self._assert_finding(self.ok('validate', profile=tightened), tightened, 'THIN_FEATURE')
                    self.assertEqual(self.snapshot(), before, 'Rule changes mutated geometry')
                    for live in self.snapshot()['references']:
                        self.ok('delete', ref=live)

    def test_V06_detached_fragment_rejected_by_single_piece_profile(self):
        self.ring()
        self.ok('create_box', size=[2,2,2], origin=[30,0,0])
        profile = copy.deepcopy(MANUFACTURING_PROFILE)
        self._assert_finding(self.ok('validate', profile=profile), profile, 'UNINTENDED_BODY')
        multiple = profile | {'max_components':2}
        before = self.snapshot()
        result = self.app.execute('validate', {'profile':multiple})
        self.assertIsInstance(result.get('ok'), bool)
        if result['ok']:
            self._assert_ready(result['value'], multiple)
        else:
            # Multi-piece production is optional; single-piece rejection above
            # is mandatory. Unsupported policy must be explicit, never fallback.
            self.assertEqual(result['error']['code'], 'UNSUPPORTED_PROFILE')
            self.assertTrue(result['error']['message'])
            self.assertNotIn('value', result)
        self.assertEqual(self.snapshot(), before)

    def test_V07_missing_negative_nonfinite_and_inconsistent_configuration(self):
        self.ring()
        before = self.snapshot()
        consistent = MANUFACTURING_PROFILE | {'max_wall':2.0}
        self._assert_ready(self.ok('validate', profile=consistent), consistent)
        invalid = [None, {}, MANUFACTURING_PROFILE | {'max_wall':0.5},
                   MANUFACTURING_PROFILE | {'max_components':1.5}]
        for key in ('min_wall','min_prong','max_components'):
            invalid.append({k:v for k,v in MANUFACTURING_PROFILE.items() if k != key})
            for value in (0, -1, math.nan, math.inf, -math.inf):
                invalid.append(MANUFACTURING_PROFILE | {key:value})
        self.error('validate')
        for profile in invalid:
            with self.subTest(profile=profile):
                error = self.error('validate', profile=profile)
                self.assertEqual(error['code'], 'INVALID_PROFILE')
                self.assertEqual(self.snapshot(), before)
