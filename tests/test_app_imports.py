from __future__ import annotations

import unittest
from importlib.util import find_spec


class DesktopImportTests(unittest.TestCase):
    @unittest.skipUnless(find_spec("PyQt6") and find_spec("pyqtgraph"),
                         "desktop requirements are not installed in this local runtime")
    def test_desktop_entrypoint_imports_without_starting_the_event_loop(self) -> None:
        import app
        from omnistore import ui

        self.assertTrue(callable(app.install_premium_ui))
        self.assertTrue(callable(ui.run))
        self.assertTrue(hasattr(ui, "SupabaseSyncThread"))


if __name__ == "__main__":
    unittest.main()
