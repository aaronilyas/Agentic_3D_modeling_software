"""K01–K08 geometry contracts, with analytic expectations in mm and mm³."""
import math

from tests.fixtures import (CANONICAL_RING, CANONICAL_VOLUME, CANONICAL_BOUNDS,
    KERNEL_NUMERIC_TOL, GEOMETRY_ABS_TOL, translation, rotation_z, uniform_scale)
from tests.jewelry_fixtures import SETTING, PRONGS, PRONG_CENTERS
from tests.support import ContractTestCase


class KernelTests(ContractTestCase):
    def box(self, size=(2,2,2), origin=(0,0,0)):
        return self.ok('create_box', size=list(size), origin=list(origin))['ref']

    def cylinder(self, radius, height, z):
        return self.ok('create_cylinder', radius=radius, height=height, origin=[0,0,z])['ref']

    def bore_open(self, ref):
        for point in ([0,0,-3], [0,0,0], [0,0,3], [7.5,0,0], [-7.5,0,0],
                      [7.9,0,1.99], [7.9,0,-1.99]):
            self.assertFalse(self.contains(ref, point), point)

    def test_K01_primitives_and_invalid_dimensions(self):
        cases = [
            ('create_box', {'size':[2,3,4], 'origin':[-1,-1.5,-2]}, 24,
             [[-1,-1.5,-2],[1,1.5,2]], [0,0,0], [2,0,0]),
            ('create_cylinder', {'radius':2., 'height':5., 'origin':[0,0,-2.5]}, 20*math.pi,
             [[-2,-2,-2.5],[2,2,2.5]], [1,0,0], [2.1,0,0]),
            ('create_sphere', {'radius':3., 'center':[0,0,0]}, 36*math.pi,
             [[-3,-3,-3],[3,3,3]], [2,0,0], [3.1,0,0]),
        ]
        for operation, arguments, volume, bounds, inside, outside in cases:
            with self.subTest(primitive=operation):
                ref = self.ok(operation, **arguments)['ref']
                self.assert_solid(ref, volume)
                self.assert_bounds(ref, bounds)
                self.assertTrue(self.contains(ref, inside))
                self.assertFalse(self.contains(ref, outside))
            dimensions = range(3) if operation == 'create_box' else (
                ['radius','height'] if operation == 'create_cylinder' else ['radius'])
            for dimension in dimensions:
                for bad in (0., -1., math.nan, math.inf, -math.inf):
                    with self.subTest(primitive=operation, dimension=dimension, invalid=bad):
                        invalid = dict(arguments)
                        if operation == 'create_box':
                            invalid['size'] = list(arguments['size'])
                            invalid['size'][dimension] = bad
                        else:
                            invalid[dimension] = bad
                        before = self.snapshot()
                        self.error(operation, **invalid)
                        self.assertEqual(self.snapshot(), before)

    def test_K02_rigid_inverse_scale_and_invalid_transforms(self):
        ref = self.box((2,3,4), (-1,-1.5,-2))
        for matrix in (rotation_z(90), translation(3,4,5)):
            ref = self.ok('transform', ref=ref, matrix=matrix)['ref']
            self.assert_solid(ref, 24)
        self.assert_bounds(ref, [[1.5,3,3],[4.5,5,7]])
        self.assertTrue(self.contains(ref, [3,4,5]))
        for matrix in (translation(-3,-4,-5), rotation_z(-90)):
            ref = self.ok('transform', ref=ref, matrix=matrix)['ref']
        self.assert_bounds(ref, [[-1,-1.5,-2],[1,1.5,2]])
        self.assert_solid(ref, 24)
        self.assertTrue(self.contains(ref, [0.5,1,1.5]))
        self.assertFalse(self.contains(ref, [1.2,0,0]))
        for scale in (0.5,2.0):
            body = self.box((2,3,4), (-1,-1.5,-2))
            body = self.ok('transform', ref=body, matrix=uniform_scale(scale))['ref']
            self.assert_solid(body, 24*scale**3)
            self.assert_bounds(body, [[-scale,-1.5*scale,-2*scale],[scale,1.5*scale,2*scale]])
        projective = translation(0,0,0)
        projective[12] = 1
        for matrix in ([1]*15, uniform_scale(0), uniform_scale(-1),
                       translation(math.nan,0,0), translation(0,math.inf,0), projective):
            with self.subTest(matrix=matrix):
                before = self.snapshot()
                self.error('transform', ref=ref, matrix=matrix)
                self.assertEqual(self.snapshot(), before)

    def test_K03_extrusion_revolution_and_malformed_profiles(self):
        rectangle = [[0,0],[2,0],[2,3],[0,3]]
        extruded = self.ok('extrude', profile=rectangle, height=4)['ref']
        self.assert_solid(extruded, 24)
        self.assert_bounds(extruded, [[0,0,0],[2,3,4]])
        ring_profile = [[8,-2],[9.5,-2],[9.5,2],[8,2]]
        revolved = self.ok('revolve', profile=ring_profile, angle_degrees=360)['ref']
        self.assert_solid(revolved, CANONICAL_VOLUME)
        self.assert_bounds(revolved, CANONICAL_BOUNDS)
        invalid = [[], [[0,0],[1,1]], [[0,0],[1,0],[2,0]],
                   [[1,0],[3,2],[1,2],[3,0]], [[1,0],[math.nan,1],[2,0]],
                   {'type':'unsupported_spline','control_points':[[0,0],[1,1]]}]
        for operation, extra in (('extrude',{'height':4}), ('revolve',{'angle_degrees':360})):
            for profile in invalid:
                with self.subTest(operation=operation, profile=profile):
                    self.error(operation, profile=profile, **extra)
        for height in (0,-1,math.inf):
            self.error('extrude', profile=rectangle, height=height)

    def test_K04_analytic_booleans_disjoint_and_deterministic_self_subtraction(self):
        for kind, expected in (('union',12), ('subtract',4)):
            a, b = self.box(), self.box(origin=(1,0,0))
            ref = self.ok('boolean', kind=kind, left=a, right=b)['ref']
            self.assert_solid(ref, expected)
            self.assertTrue(self.contains(ref, [.5,1,1]))
            self.assertEqual(self.contains(ref, [1.5,1,1]), kind == 'union')
            self.assertEqual(self.contains(ref, [2.5,1,1]), kind == 'union')
        a, b = self.box(), self.box(origin=(5,0,0))
        ref = self.ok('boolean', kind='union', left=a, right=b)['ref']
        self.assert_solid(ref, 16, components=2)
        self.assertFalse(self.contains(ref, [3,1,1]))
        a, b = self.box(), self.box(origin=(5,0,0))
        ref = self.ok('boolean', kind='subtract', left=a, right=b)['ref']
        self.assert_solid(ref, 8)
        outcomes = []
        for _ in range(2):
            a = self.box()
            result = self.app.execute('boolean', {'kind':'subtract','left':a,'right':a})
            self.assertIsInstance(result.get('ok'), bool)
            if result['ok']:
                self.assertIs(result['value']['empty'], True)
                self.assertNotIn('ref', result['value'])
                outcomes.append('empty')
            else:
                self.assertEqual(result['error']['code'], 'EMPTY_RESULT')
                self.assertTrue(result['error']['message'])
                self.assertNotIn('value', result)
                outcomes.append(result['error']['code'])
        self.assertEqual(outcomes[0], outcomes[1])

    def test_K05_gap_overlap_contact_and_tolerance_policy(self):
        for offset in (-1e-3,0,1e-3,-2*KERNEL_NUMERIC_TOL,
                       -0.5*KERNEL_NUMERIC_TOL,0.5*KERNEL_NUMERIC_TOL,2*KERNEL_NUMERIC_TOL):
            with self.subTest(offset=offset):
                a = self.box((1,1,1))
                b = self.box((1,1,1), (1+offset,0,0))
                result = self.app.execute('boolean', {'kind':'union','left':a,'right':b})
                self.assertIsInstance(result.get('ok'), bool)
                if not result['ok']:
                    self.assertNotEqual(offset, 0, 'Exact face contact must merge')
                    self.assertLessEqual(abs(offset), 2*KERNEL_NUMERIC_TOL)
                    self.assertEqual(result['error']['code'], 'TOLERANCE_AMBIGUITY')
                    self.assertTrue(result['error']['message'])
                    self.assertNotIn('value', result)
                    continue
                ref = result['value']['ref']
                components = self.ok('inspect', ref=ref)['topology']['components']
                if abs(offset) > 2*KERNEL_NUMERIC_TOL or offset == 0:
                    self.assertEqual(components, 2 if offset > 0 else 1)
                else:
                    self.assertIn(components, (1,2))
                self.assert_solid(ref, 2+min(offset,0), components)
                self.assertTrue(self.contains(ref, [.5,.5,.5]))
                self.assertTrue(self.contains(ref, [1.5+offset,.5,.5]))

    def test_K06_canonical_ring_three_equivalent_construction_paths(self):
        outer, inner = self.cylinder(9.5,4,-2), self.cylinder(8,6,-3)
        refs = [self.ring(), self.ok('boolean',kind='subtract',left=outer,right=inner)['ref'],
                self.ok('revolve',profile=[[8,-2],[9.5,-2],[9.5,2],[8,2]],angle_degrees=360)['ref']]
        for ref in refs:
            self.assert_solid(ref, CANONICAL_VOLUME)
            self.assert_bounds(ref, CANONICAL_BOUNDS)
            self.bore_open(ref)
            for point in ([8.75,0,0],[-8.75,0,0],[0,8.75,1],[0,-8.75,-1]):
                self.assertTrue(self.contains(ref, point))
            self.assertFalse(self.contains(ref, [9.6,0,0]))
            self.assertFalse(self.contains(ref, [8.75,0,2.1]))
        for overrides in ({'inner_radius':9.5},{'outer_radius':7.9},{'width':0},
                          {'inner_radius':-1},{'outer_radius':math.nan}):
            self.error('create_ring', **(CANONICAL_RING | overrides))

    def test_K07_through_hole_and_blind_recess_remove_intended_material(self):
        for through in (True,False):
            ref = self.ring()
            radius, depth = 0.2, 0.6
            if through:
                ref = self.ok('cut_through_hole', ref=ref, center=[8.75,0], radius=radius)['ref']
                removed = math.pi*radius**2*4
                for z in (-1.9,0,1.9):
                    self.assertFalse(self.contains(ref, [8.75,0,z]))
            else:
                ref = self.ok('cut_recess', ref=ref, center=[8.75,0], radius=radius,
                              depth=depth, top_z=2.)['ref']
                removed = math.pi*radius**2*depth
                self.assertFalse(self.contains(ref, [8.75,0,1.7]))
                self.assertTrue(self.contains(ref, [8.75,0,1.4-0.01]))
                self.assertFalse(self.contains(ref, [8.75,0,1.4+0.01]))
                self.assertTrue(self.contains(ref, [8.75,0,0]))
            self.assert_solid(ref, CANONICAL_VOLUME-removed)
            self.assertTrue(self.contains(ref, [8.75,.3,0]))
            self.bore_open(ref)

    def test_K08_setting_and_four_repeated_connected_prongs(self):
        ref = self.ring()
        ref = self.ok('add_setting', ref=ref, **SETTING)['ref']
        self.assert_solid(ref)
        before = self.ok('inspect', ref=ref)['volume']
        ref = self.ok('repeat_prongs', ref=ref, diameter=.8, **PRONGS)['ref']
        self.assert_solid(ref, before+4*math.pi*.4**2*1.8)
        # At z=4 only the four prongs are present. Probe both their axes and
        # the gaps; the one-component solid assertion rejects floating prongs.
        for x,y in PRONG_CENTERS:
            for z in (2.9,4,4.7):
                self.assertTrue(self.contains(ref, [x,y,z]))
        for angle in range(0,360,5):
            theta = math.radians(angle)
            point = [10.0+math.cos(theta),math.sin(theta),4]
            expected = any(math.hypot(point[0]-x,point[1]-y) < .4 for x,y in PRONG_CENTERS)
            self.assertEqual(self.contains(ref, point), expected, point)
        self.bore_open(ref)
        for overrides in ({'count':0},{'count':-1},{'count':2.5},{'diameter':0},
                          {'orbit_radius':math.inf},{'start_angle_degrees':math.nan}):
            before = self.snapshot()
            self.error('repeat_prongs', ref=ref, **(PRONGS | {'diameter':.8} | overrides))
            self.assertEqual(self.snapshot(), before)
