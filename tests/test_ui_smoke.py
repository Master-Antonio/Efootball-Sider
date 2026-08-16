import os
import tempfile
import unittest
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from ui.app import create_application
from ui.main_window import NAVIGATION, MainWindow
from ui.models import Column, DictTableModel, TypedSortFilterProxyModel
from ui.pages.assets import AssetsPage
from ui.pages.camera import CameraPage
from ui.pages.database import DatabasePage
from ui.pages.diagnostics import DiagnosticsPage
from ui.pages.mods import ModsPage
from ui.pages.overview import OverviewPage
from ui.services.config import CameraSettings, ConfigurationService
from ui.services.paths import WorkspacePaths
from ui.workers import TaskWorker


class TestQtApplication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or create_application(["ui-tests"])

    def test_main_window_contains_six_operational_pages(self):
        window = MainWindow()
        expected_types = (
            OverviewPage,
            AssetsPage,
            DatabasePage,
            ModsPage,
            CameraPage,
            DiagnosticsPage,
        )
        self.assertEqual(window._stack.count(), len(NAVIGATION))
        for index, expected_type in enumerate(expected_types):
            window._select_page(index)
            self.app.processEvents()
            self.assertIsInstance(window._stack.currentWidget(), expected_type)
            self.assertEqual(window._stack.currentIndex(), index)
        window.close()

    def test_context_retains_worker_until_finished(self):
        window = MainWindow()
        worker = TaskWorker(lambda: 42)
        results = []
        loop = QEventLoop()
        worker.signals.result.connect(results.append)
        worker.signals.finished.connect(loop.quit)
        window.context.start_worker(worker)
        self.assertIn(worker, window.context.workers)
        QTimer.singleShot(5_000, loop.quit)
        loop.exec()
        self.app.processEvents()
        self.assertEqual(results, [42])
        self.assertNotIn(worker, window.context.workers)
        window.close()

    def test_typed_proxy_sorts_numeric_ids_numerically(self):
        model = DictTableModel((Column("id", "ID"),), [{"id": 2489}, {"id": 84}, {"id": 10_000}])
        proxy = TypedSortFilterProxyModel()
        proxy.setSourceModel(model)
        proxy.sort(0)
        self.assertEqual([proxy.index(row, 0).data() for row in range(3)], ["84", "2489", "10000"])


class TestConfigurationService(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.paths = WorkspacePaths(repository=root, game_root=root / "game")
        self.paths.content.mkdir(parents=True)
        self.paths.sider_ini.write_text(
            "\n".join(
                (
                    "[camera]",
                    "enabled = 1",
                    "zoom = 1.0",
                    "",
                    "[LIVE_CPK]",
                    'cpk.root = "content\\A"',
                    'cpk.root = "content\\B"',
                    "",
                )
            ),
            encoding="utf-8",
        )
        self.service = ConfigurationService(self.paths)

    def tearDown(self):
        self.temp.cleanup()

    def test_camera_save_preserves_duplicate_mod_roots(self):
        self.service.save_camera(CameraSettings(True, 0.82, 1.32, -0.12, 50.0, 2.5))
        text = self.paths.sider_ini.read_text(encoding="utf-8")
        self.assertIn('cpk.root = "content\\A"', text)
        self.assertIn('cpk.root = "content\\B"', text)
        self.assertEqual(len(self.service.active_roots()), 2)
        self.assertAlmostEqual(self.service.read_camera().height, 1.32)

    def test_mod_zip_rejects_path_traversal(self):
        archive_path = Path(self.temp.name) / "unsafe.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("../outside.txt", "unsafe")
        with self.assertRaisesRegex(ValueError, "Unsafe ZIP path"):
            self.service.install_zip(archive_path)

    def test_legacy_catch_all_blocks_false_individual_disable(self):
        (self.paths.content / "A").mkdir()
        self.paths.sider_ini.write_text('[LIVE_CPK]\ncpk.root = "content"\n', encoding="utf-8")
        mods = self.service.list_mods()
        self.assertTrue(mods[0].enabled)
        with self.assertRaisesRegex(ValueError, "catch-all"):
            self.service.set_mod_enabled("A", False)


if __name__ == "__main__":
    unittest.main()
