"""Green tests for independent oracles, never counted as product coverage."""
import copy
import re
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tests.mesh_oracle import (assert_printable_mesh, measure_mesh, read_stl,
                               contains_point, point_mesh_distance, point_triangle_distance)
from tests.support import load_application


from tests.mesh_fixtures import TETRAHEDRON


class HarnessTests(unittest.TestCase):
    def test_independent_surface_distance_and_containment_controls(self):
        self.assertTrue(contains_point(TETRAHEDRON, [.1,.1,.1]))
        self.assertFalse(contains_point(TETRAHEDRON, [2,2,2]))
        a,b,c = [0,0,0], [1,0,0], [0,1,0]
        for point, distance in (([.2,.2,1],1), ([1,1,0],2**-.5),
                                ([-1,-1,0],2**.5), ([2,0,0],1), ([0,2,0],1)):
            self.assertAlmostEqual(point_triangle_distance(point,a,b,c), distance)
        self.assertAlmostEqual(point_mesh_distance(TETRAHEDRON, [.1,.1,0]),0)

    def test_all_34_specification_groups_are_discoverable_without_skips(self):
        from tests.run import LAYERS
        modules = [name for layer in ('fast', 'integration', 'acp', 'e2e')
                   for name in LAYERS[layer]]
        suite = unittest.defaultTestLoader.loadTestsFromNames(modules)

        def leaves(node):
            for item in node:
                if isinstance(item, unittest.TestSuite):
                    yield from leaves(item)
                else:
                    yield item

        found = set()
        for test in leaves(suite):
            self.assertNotIsInstance(test, unittest.loader._FailedTest,
                                     f'Test module failed to import: {test.id()}')
            method = getattr(test, test._testMethodName)
            self.assertFalse(getattr(method, '__unittest_skip__', False), test.id())
            self.assertFalse(getattr(type(test), '__unittest_skip__', False), test.id())
            self.assertFalse(getattr(method, '__unittest_expecting_failure__', False), test.id())
            match = re.search(r'([KVXAMCE]\d{2})', test.id(), re.I)
            if match:
                found.add(match[1].upper())
        required = {f'{prefix}{number:02d}' for prefix, count in
                    [('K',8), ('V',7), ('X',4), ('A',4), ('M',4), ('C',4), ('E',3)]
                    for number in range(1, count+1)}
        self.assertEqual(found, required)

    def test_closed_mesh_analytic_volume_and_bounds(self):
        result = assert_printable_mesh(self, TETRAHEDRON)
        self.assertAlmostEqual(result['signed_volume'], 1/6)
        self.assertEqual(result['bounds'], [[0,0,0], [1,1,1]])

    def test_exact_seams_are_welded_but_geometric_gaps_are_not_repaired(self):
        vertices = [list(TETRAHEDRON['vertices'][i])
                    for face in TETRAHEDRON['triangles'] for i in face]
        mesh = {'vertices':vertices,'triangles':[[i,i+1,i+2] for i in range(0,12,3)]}
        assert_printable_mesh(self,mesh)
        vertices[0][0] += 1e-5
        self.assertGreater(measure_mesh(mesh)['boundary_edges'],0)

    def test_missing_face_is_detected(self):
        mesh = copy.deepcopy(TETRAHEDRON)
        mesh['triangles'].pop()
        self.assertEqual(measure_mesh(mesh)['boundary_edges'], 3)

    def test_reversed_face_is_detected(self):
        mesh = copy.deepcopy(TETRAHEDRON)
        mesh['triangles'][0].reverse()
        self.assertFalse(measure_mesh(mesh)['consistent_orientation'])

    def test_degenerate_triangle_and_nonmanifold_edges_are_detected(self):
        mesh = copy.deepcopy(TETRAHEDRON)
        mesh['triangles'].extend([[0,0,1], [0,2,1]])
        result = measure_mesh(mesh)
        self.assertGreater(result['nonmanifold_edges'], 0)
        self.assertGreater(result['degenerate_triangles'], 0)

    def test_vertex_only_contact_is_nonmanifold(self):
        mesh = copy.deepcopy(TETRAHEDRON)
        mesh['vertices'].extend([[-1,0,0], [0,-1,0], [0,0,-1]])
        mapping = [0,4,5,6]
        mesh['triangles'].extend([[mapping[i] for i in reversed(f)] for f in TETRAHEDRON['triangles']])
        self.assertEqual(measure_mesh(mesh)['nonmanifold_edges'], 0)
        self.assertFalse(measure_mesh(mesh)['manifold_vertices'])

    def test_disconnected_component_is_detected(self):
        mesh = copy.deepcopy(TETRAHEDRON)
        mesh['vertices'].extend([[x+3,y,z] for x,y,z in TETRAHEDRON['vertices']])
        mesh['triangles'].extend([[i+4 for i in f] for f in TETRAHEDRON['triangles']])
        self.assertEqual(measure_mesh(mesh)['components'], 2)

    def test_binary_and_ascii_stl_parsing(self):
        binary = bytearray(b'solid binary header'.ljust(80, b'\0'))
        binary.extend(struct.pack('<I', 4))
        lines = ['solid tetra']
        for face in TETRAHEDRON['triangles']:
            vertices = [TETRAHEDRON['vertices'][i] for i in face]
            binary.extend(struct.pack('<12fH', 0,0,0, *(x for v in vertices for x in v), 0))
            lines.extend(['facet normal 0 0 0', 'outer loop'])
            lines.extend('vertex '+' '.join(map(str, v)) for v in vertices)
            lines.extend(['endloop', 'endfacet'])
        lines.append('endsolid tetra')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'tetra.stl'
            for data in (bytes(binary), '\n'.join(lines).encode()):
                with self.subTest(encoding='binary' if data == binary else 'ascii'):
                    path.write_bytes(data)
                    result = assert_printable_mesh(self, read_stl(path))
                    self.assertAlmostEqual(result['signed_volume'], 1/6)
            path.write_bytes(bytes(binary[:-1]))
            with self.assertRaises((ValueError, UnicodeError)):
                read_stl(path)
            path.write_text('solid truncated\nfacet normal 0 0 0\nendsolid truncated')
            with self.assertRaises(ValueError):
                read_stl(path)

    def test_missing_adapter_is_explicit_and_misconfiguration_is_not_hidden(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaisesRegex(AssertionError, 'MISSING_CAPABILITY'):
                load_application()
        with patch.dict('os.environ', {'JEWELRY_TEST_ADAPTER': 'broken'}):
            with self.assertRaises(ValueError):
                load_application()
        with patch.dict('os.environ', {'JEWELRY_TEST_ADAPTER': '_nonexistent_jewelry_adapter_:create'}):
            with self.assertRaises(ModuleNotFoundError):
                load_application()
