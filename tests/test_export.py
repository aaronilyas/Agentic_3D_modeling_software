"""X01–X04 tessellation accuracy and atomic manufacturing export (MVP STL)."""
import math
from pathlib import Path
import tempfile

from tests.fixtures import (CANONICAL_VOLUME, KERNEL_NUMERIC_TOL, GEOMETRY_ABS_TOL,
                           MANUFACTURING_PROFILE, TESSELLATION_ERROR)
from tests.jewelry_fixtures import ring_with_setting, PRONG_CENTERS
from tests.mesh_fixtures import _open_tetrahedron, TETRAHEDRON
from tests.mesh_oracle import (assert_printable_mesh, contains_point, point_mesh_distance)
from tests.export_assertions import assert_stl
from tests.support import ContractTestCase


def surface_samples():
    # Analytic locations on retained ring, hole and prong surfaces; no call to
    # the product's own deviation estimator.
    for n in range(24):
        theta = 2*math.pi*(n+.37)/24
        for radius in (8.,9.5):
            yield [radius*math.cos(theta), radius*math.sin(theta),0.]
        yield [-8.75+.2*math.cos(theta),.2*math.sin(theta),0.]
        for x,y in PRONG_CENTERS:
            yield [x+.4*math.cos(theta), y+.4*math.sin(theta),4.]
    for degrees in (45,135,225,315):
        angle = math.radians(degrees)
        yield [10.0+.65*math.cos(angle),.65*math.sin(angle),2.75]
    yield [10.0,0,2.5]  # blind recess floor


def cylinder_field(point, center, radius, z0, z1):
    x,y,z = point
    radial = math.hypot(x-center[0],y-center[1])-radius
    axial = abs(z-(z0+z1)/2)-(z1-z0)/2
    return min(max(radial,axial),0)+math.hypot(max(radial,0),max(axial,0))


def jewelry_field(point):
    # Signed constructive field, used as an additional mesh-to-analytic check.
    # Reverse distance is independently measured to actual triangles above.
    ring = max(cylinder_field(point,[0,0],9.5,-2,2),
               -cylinder_field(point,[0,0],8,-3,3))
    setting = cylinder_field(point,[10.0,0],1.5,1.8,3)
    body = max(min(ring,setting), -cylinder_field(point,[10.0,0],.65,2.5,4))
    body = min(body, *(cylinder_field(point,c,.4,2.8,4.8) for c in PRONG_CENTERS))
    return max(body,-cylinder_field(point,[-8.75,0],.2,-3,3))


class ExportTests(ContractTestCase):
    def test_X01_watertight_oriented_nondegenerate_jewelry_mesh(self):
        for decorated in (False,True):
            with self.subTest(decorated=decorated):
                ref = ring_with_setting(self, seat=True) if decorated else self.ring()
                mesh = self.ok('tessellate',ref=ref,chord_tolerance=TESSELLATION_ERROR)
                assert_printable_mesh(self,mesh)
                self.assertFalse(contains_point(mesh,[0,0,0]))

    def test_X02_two_tolerances_preserve_hole_recess_prongs_and_accuracy(self):
        ref = ring_with_setting(self, seat=True, hole=True)
        for tolerance in (.04,.01):
            with self.subTest(tolerance=tolerance):
                mesh = self.ok('tessellate',ref=ref,chord_tolerance=tolerance)
                assert_printable_mesh(self,mesh)
                for point in surface_samples():
                    self.assertLessEqual(point_mesh_distance(mesh,point),tolerance+GEOMETRY_ABS_TOL,point)
                for face in mesh['triangles']:
                    vertices = [mesh['vertices'][i] for i in face]
                    centroid = [sum(p[i] for p in vertices)/3 for i in range(3)]
                    midpoints = [[(vertices[j][i]+vertices[(j+1)%3][i])/2
                                  for i in range(3)] for j in range(3)]
                    for point in (*vertices,*midpoints,centroid):
                        self.assertLessEqual(abs(jewelry_field(point)),tolerance+GEOMETRY_ABS_TOL,point)
                for z in (-1.9,0,1.9):
                    self.assertFalse(contains_point(mesh,[-8.75,0,z]), 'small through-hole filled')
                    self.assertFalse(contains_point(mesh,[0,0,z]), 'finger bore filled')
                self.assertFalse(contains_point(mesh,[10.0,0,2.75]), 'recess filled')
                self.assertTrue(contains_point(mesh,[10.0,0,2.4]), 'recess floor lost')
                for x,y in PRONG_CENTERS:
                    self.assertTrue(contains_point(mesh,[x,y,4.]), 'prong erased')
                    self.assertTrue(contains_point(mesh,[x,y,2.9]), 'prong joint lost')
        for tolerance in (0,-.01,math.nan,math.inf,KERNEL_NUMERIC_TOL/1000):
            before = self.snapshot()
            self.error('tessellate',ref=ref,chord_tolerance=tolerance)
            self.assertEqual(self.snapshot(),before)
        self.error('tessellate',ref=ref,chord_tolerance=.01,max_triangles=4)

    def test_X03_stl_roundtrip_preserves_millimetres_bounds_volume_and_topology(self):
        ref = self.ring()
        validation = self.ok('validate',profile=MANUFACTURING_PROFILE)
        self.assertIs(validation['ready'],True)
        before = self.snapshot()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'canonical.stl'
            result = self.ok('export',ref=ref,path=str(path),format='stl',
                             validation=validation,chord_tolerance=TESSELLATION_ERROR)
            self.assertEqual(result['revision'],validation['revision'])
            # STL has no unit metadata: the 19 × 19 × 4 coordinate bounds are
            # the independent unit check (an inch/metre conversion fails).
            mesh = assert_stl(self,path,self.ok('inspect',ref=ref))
            self.assertFalse(contains_point(mesh,[0,0,0]))
            self.assert_solid(ref,CANONICAL_VOLUME)
        self.assertEqual(self.snapshot(),before)

    def reject_unchanged(self, directory, operation, **arguments):
        before = self.snapshot()
        files = {str(p.relative_to(directory)):p.read_bytes()
                 for p in directory.rglob('*') if p.is_file()}
        self.error(operation,**arguments)
        self.assertEqual(self.snapshot(),before)
        after = {str(p.relative_to(directory)):p.read_bytes()
                 for p in directory.rglob('*') if p.is_file()}
        self.assertEqual(after,files,'Partial artifact published or previous artifact overwritten')

    def test_X04_reject_invalid_blocked_stale_and_unwritable_exports_atomically(self):
        ref = self.ring()
        validation = self.ok('validate',profile=MANUFACTURING_PROFILE)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root/'ring.stl'
            args = {'ref':ref,'path':str(path),'format':'stl','validation':validation,
                    'chord_tolerance':TESSELLATION_ERROR}
            self.ok('export',**args)
            assert_stl(self,path,self.ok('inspect',ref=ref))
            self.ok('modify_ring',ref=ref,outer_radius=8.5)
            current = self.ok('validate',profile=MANUFACTURING_PROFILE)
            self.assertIs(current['ready'],False)
            self.assertNotEqual(current['revision'],validation['revision'])
            self.reject_unchanged(root,'export',**args)  # stale ready report
            self.reject_unchanged(root,'export',**(args | {'validation':current}))
            self.reject_unchanged(root,'export',**(args | {'path':str(root/'new.stl'),'validation':current}))
            # Open but well-formed geometry and structurally invalid mesh data.
            invalid_mesh = {'vertices':TETRAHEDRON['vertices'],'triangles':[[0,1,99]]}
            for mesh in (_open_tetrahedron(),invalid_mesh):
                self.reject_unchanged(root,'export_mesh',**mesh,path=str(root/'invalid.stl'),format='stl')
            self.ok('modify_ring',ref=ref,outer_radius=9.5)
            current = self.ok('validate',profile=MANUFACTURING_PROFILE)
            # A regular file cannot be a parent directory, even when run as root.
            parent = root/'not-a-directory'
            parent.write_bytes(b'preserve parent')
            self.reject_unchanged(root,'export',**(args | {'validation':current,'path':str(parent/'ring.stl')}))
