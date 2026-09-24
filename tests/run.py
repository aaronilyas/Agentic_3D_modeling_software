"""Explicit test layers; default invocation never starts an external agent CLI."""
import argparse
import unittest

from tests.support import MissingCapability


class ContractResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.missing_capabilities = 0

    def addFailure(self, test, err):
        if issubclass(err[0], MissingCapability):
            self.missing_capabilities += 1
        super().addFailure(test, err)

LAYERS = {
    'harness': ['tests.test_harness'],
    'fast': ['tests.test_kernel', 'tests.test_validator', 'tests.test_application'],
    'integration': ['tests.test_export', 'tests.test_mcp'],
    'generic': [
        'tests.test_cad_model', 'tests.test_cad_export', 'tests.test_cad_assets', 'tests.test_cad_agent',
    ],
    'mcp': ['tests.test_mcp'],
    'acp': ['tests.test_acp'],
    'e2e': ['tests.test_e2e'],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('layer', choices=[*LAYERS, 'local', 'all'], nargs='?', default='fast')
    options = parser.parse_args()
    layers = {'local': ['harness', 'fast', 'integration'],
              'all': ['harness', 'fast', 'integration', 'generic', 'acp', 'e2e']}.get(options.layer, [options.layer])
    suite = unittest.defaultTestLoader.loadTestsFromNames(
        [module for layer in layers for module in LAYERS[layer]])
    result = unittest.TextTestRunner(verbosity=2, resultclass=ContractResult).run(suite)
    print(f'Classification: {result.missing_capabilities} missing-production failures; '
          f'{len(result.failures)-result.missing_capabilities} other assertion failures; '
          f'{len(result.errors)} test/adapter errors; {len(result.skipped)} skips.')
    raise SystemExit(not result.wasSuccessful())


if __name__ == '__main__':
    main()
