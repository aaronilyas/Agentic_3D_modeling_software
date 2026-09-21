# GUI foundation validation

Baseline commit: `26214102f8b681b5e408baa460aa033afb302cf1`.
Working tree was clean before changes. No backend implementation files changed.

With `JEWELRY_TEST_ADAPTER=jewelry.adapter:create_application`, both before and
after implementation:

| Command (`.venv/bin/python -m`) | Result |
| --- | --- |
| `tests.run harness` | 15 passed |
| `tests.run fast` | 19 passed |
| `tests.run integration` | 8 passed |
| `tests.run e2e` | 3 passed |

Desktop validation: `.venv/bin/python -m unittest tests.test_gui -v`: 6 passed.
Real displayed windows, exact backend-to-VTK vertex/triangle comparisons, actual
VTK picking, synthesized orbit/pan/wheel interaction, camera fit, selection,
inspection, history, reset, failure envelopes and resource shutdown were checked.
A rendered screenshot was visually inspected: a shaded annulus with an open
bore and correct proportions. Canonical create + refresh + render took about
50 ms on this machine; no worker is needed for this limited workflow.

Environment tested: Python 3.14, PySide6 6.11.2, PyVista 0.49.0,
PyVistaQt 0.13.1, VTK 9.7.0, Linux graphical desktop. VTK emits OpenGL
color-buffer query warnings (1282) here during initialization. Rendering and
interaction tests still pass; other platforms/drivers have not been tested.

Technology references: [PyVistaQt QtInteractor](https://qt.pyvista.org/api_reference.html)
and [PyVista mesh picking](https://docs.pyvista.org/examples/02-plot/mesh_picking.html).
