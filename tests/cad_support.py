"""Helpers for generic CAD tests. They talk to the real application."""

import unittest

from cad.adapter import create_application


class CadTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_application()
        self.addCleanup(self.app.close)

    def ok(self, operation, **arguments):
        result = self.app.execute(operation, arguments)
        self.assertIs(result.get("ok"), True, result)
        self.assertIn("value", result)
        self.assertNotIn("error", result)
        return result["value"]

    def err(self, operation, **arguments):
        result = self.app.execute(operation, arguments)
        self.assertIs(result.get("ok"), False, result)
        self.assertNotIn("value", result)
        self.assertTrue(result["error"]["code"])
        self.assertTrue(result["error"]["message"])
        return result["error"]

    def revision(self):
        return self.ok("snapshot")["revision"]
