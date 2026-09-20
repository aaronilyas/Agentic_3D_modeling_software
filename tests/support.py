"""Thin production boundary and reusable assertions; no geometry implementation."""
import importlib
import os
import unittest

from tests.fixtures import CANONICAL_RING, GEOMETRY_ABS_TOL, VOLUME_REL_TOL


class MissingCapability(AssertionError):
    """The production boundary is absent, rather than a broken test import."""


def load_application():
    target = os.environ.get('JEWELRY_TEST_ADAPTER')
    if not target:
        raise MissingCapability(
            'MISSING_CAPABILITY: no production application exists in this repository; '
            'provide JEWELRY_TEST_ADAPTER=module:create_application (tests/CONTRACT.md)'
        )
    module, separator, factory = target.partition(':')
    if not separator or not module or not factory:
        raise ValueError('JEWELRY_TEST_ADAPTER must be module:factory')
    return getattr(importlib.import_module(module), factory)()


class ContractTestCase(unittest.TestCase):
    def setUp(self):
        self.app = load_application()
        self.addCleanup(self.app.close)

    def ok(self, operation, **arguments):
        result = self.app.execute(operation, arguments)
        self.assertIsInstance(result, dict)
        self.assertIs(result.get('ok'), True, f'{operation}: {result!r}')
        self.assertIn('value', result)
        self.assertNotIn('error', result)
        return result['value']

    def error(self, operation, **arguments):
        result = self.app.execute(operation, arguments)
        self.assertIsInstance(result, dict)
        self.assertIs(result.get('ok'), False, f'{operation}: {result!r}')
        self.assertNotIn('value', result)
        self.assertNotIn('ref', result)
        error = result['error']
        for field in ('code', 'message'):
            self.assertIsInstance(error[field], str)
            self.assertTrue(error[field].strip())
        return error

    def ring(self, **overrides):
        return self.ok('create_ring', **(CANONICAL_RING | overrides))['ref']

    def snapshot(self):
        import copy
        return copy.deepcopy(self.ok('snapshot'))

    def contains(self, ref, point):
        value = self.ok('contains', ref=ref, point=point)
        self.assertIsInstance(value, bool)
        return value

    def assert_solid(self, ref, volume=None, components=1):
        info = self.ok('inspect', ref=ref)
        self.assertIs(info['topology']['closed'], True)
        self.assertIs(info['topology']['manifold'], True)
        self.assertEqual(info['topology']['components'], components)
        self.assertGreater(info['volume'], 0)
        if volume is not None:
            self.assertAlmostEqual(info['volume'], volume,
                                   delta=max(GEOMETRY_ABS_TOL**3, abs(volume)*VOLUME_REL_TOL))
        return info

    def assert_bounds(self, ref, expected):
        actual = self.ok('inspect', ref=ref)['bounds']
        self.assertEqual(len(actual), 2)
        for corner, target in zip(actual, expected):
            self.assertEqual(len(corner), 3)
            for value, wanted in zip(corner, target):
                self.assertAlmostEqual(value, wanted, delta=GEOMETRY_ABS_TOL)
