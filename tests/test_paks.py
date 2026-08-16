from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ui.services.paks import PakModService
from ui.services.zen_builder import (
    EFOOTBALL_AES_KEY,
    ZenBuilderService,
    ZenBuildResult,
    get_container_base_name,
    is_cooked_mod_dir,
)


class TestPakModService(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.mods_dir = Path(self._tmp.name)
        self.service = PakModService(self.mods_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def _make_triplet(
        self,
        base: str,
        disabled: bool = False,
        parts=("pak", "utoc", "ucas"),
        mtime: float | None = None,
    ):
        for part in parts:
            suffix = ".disabled" if disabled else ""
            file_path = self.mods_dir / f"{base}.{part}{suffix}"
            file_path.write_bytes(b"x" * 10)
            if mtime is not None:
                os.utime(file_path, (mtime, mtime))

    def _make_content_package(
        self,
        content_dir: Path,
        folder_name: str,
        is_cooked: bool = True,
        mtime: float | None = None,
    ) -> Path:
        pkg_dir = content_dir / folder_name
        if is_cooked:
            asset_dir = pkg_dir / "PesConsole" / "Content" / "Characters"
            asset_dir.mkdir(parents=True, exist_ok=True)
            asset_file = asset_dir / "player.uasset"
            asset_file.write_bytes(b"cooked_data")
            if mtime is not None:
                os.utime(asset_file, (mtime, mtime))
                os.utime(asset_dir, (mtime, mtime))
                os.utime(pkg_dir / "PesConsole" / "Content", (mtime, mtime))
                os.utime(pkg_dir / "PesConsole", (mtime, mtime))
                os.utime(pkg_dir, (mtime, mtime))
        else:
            asset_dir = pkg_dir / "common" / "etc"
            asset_dir.mkdir(parents=True, exist_ok=True)
            bin_file = asset_dir / "info.bin"
            bin_file.write_bytes(b"raw_bin")
            if mtime is not None:
                os.utime(bin_file, (mtime, mtime))
                os.utime(asset_dir, (mtime, mtime))
                os.utime(pkg_dir, (mtime, mtime))
        return pkg_dir

    def test_list_groups_triplets_and_ignores_other_files(self):
        self._make_triplet("MyMod_P")
        (self.mods_dir / "readme.txt").write_text("ignore me")
        paks = self.service.list_pak_mods()
        self.assertEqual(len(paks), 1)
        self.assertEqual(paks[0].base, "MyMod_P")
        self.assertTrue(paks[0].enabled)
        self.assertEqual(len(paks[0].files), 3)
        self.assertEqual(paks[0].size_bytes, 30)

    def test_disabled_containers_are_detected(self):
        self._make_triplet("Old_P", disabled=True)
        self._make_triplet("New_P", parts=("pak",))
        paks = {info.base: info for info in self.service.list_pak_mods()}
        self.assertFalse(paks["Old_P"].enabled)
        self.assertTrue(paks["New_P"].enabled)

    def test_disable_and_enable_roundtrip(self):
        self._make_triplet("Round_P", parts=("pak", "utoc"))
        self.service.set_enabled("Round_P", False)
        names = sorted(p.name for p in self.mods_dir.iterdir())
        self.assertEqual(names, ["Round_P.pak.disabled", "Round_P.utoc.disabled"])

        self.service.set_enabled("Round_P", True)
        names = sorted(p.name for p in self.mods_dir.iterdir())
        self.assertEqual(names, ["Round_P.pak", "Round_P.utoc"])

    def test_delete_removes_all_files(self):
        self._make_triplet("Gone_P", parts=("pak", "ucas"))
        self.service.delete("Gone_P")
        self.assertEqual(list(self.mods_dir.iterdir()), [])

    def test_unknown_base_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.service.set_enabled("Nope_P", False)
        with self.assertRaises(FileNotFoundError):
            self.service.delete("Nope_P")

    def test_missing_dir_returns_empty(self):
        service = PakModService(self.mods_dir / "does_not_exist")
        self.assertEqual(service.list_pak_mods(), [])

    def test_accepts_str_path(self):
        service = PakModService(str(self.mods_dir))
        self.assertEqual(service.list_pak_mods(), [])

    def test_container_files_and_mtime_calculation(self):
        t0 = time.time() - 500
        self._make_triplet("MyMod_P", mtime=t0)
        files = self.service.get_container_files("MyMod_P")
        self.assertEqual(len(files), 3)
        mtime = self.service.get_container_mtime("MyMod_P")
        self.assertIsNotNone(mtime)
        self.assertAlmostEqual(mtime, t0, delta=2.0)

        # Incomplete container should return None for mtime
        self._make_triplet("Incomplete_P", parts=("pak", "utoc"))
        self.assertIsNone(self.service.get_container_mtime("Incomplete_P"))
        self.assertIsNone(self.service.get_container_mtime("NonExistent_P"))

    def test_is_container_outdated_when_content_newer(self):
        with tempfile.TemporaryDirectory() as c_tmp:
            content_dir = Path(c_tmp)
            t_old = time.time() - 300
            t_new = time.time() - 50

            self._make_triplet("FaceMod_P", mtime=t_old)
            mod_path = self._make_content_package(content_dir, "FaceMod", is_cooked=True, mtime=t_new)

            self.assertTrue(self.service.is_container_outdated("FaceMod_P", mod_path))
            status_map = self.service.check_sync_status(content_dir)
            self.assertEqual(status_map.get("FaceMod"), "Needs Rebuild")

    def test_is_container_outdated_when_container_newer(self):
        with tempfile.TemporaryDirectory() as c_tmp:
            content_dir = Path(c_tmp)
            t_old = time.time() - 500
            t_new = time.time() - 50

            mod_path = self._make_content_package(content_dir, "KitMod", is_cooked=True, mtime=t_old)
            self._make_triplet("KitMod_P", mtime=t_new)

            self.assertFalse(self.service.is_container_outdated("KitMod_P", mod_path))
            status_map = self.service.check_sync_status(content_dir)
            self.assertEqual(status_map.get("KitMod"), "Up to date")

    def test_is_container_outdated_when_container_missing(self):
        with tempfile.TemporaryDirectory() as c_tmp:
            content_dir = Path(c_tmp)
            mod_path = self._make_content_package(content_dir, "BrandNewMod", is_cooked=True)

            self.assertTrue(self.service.is_container_outdated("BrandNewMod_P", mod_path))
            status_map = self.service.check_sync_status(content_dir)
            self.assertEqual(status_map.get("BrandNewMod"), "Not Built")

    def test_incompatible_loose_folder_not_flagged_for_build(self):
        with tempfile.TemporaryDirectory() as c_tmp:
            content_dir = Path(c_tmp)
            mod_path = self._make_content_package(content_dir, "LegacyLoose", is_cooked=False)

            self.assertFalse(self.service.is_compatible_package(mod_path))
            status_map = self.service.check_sync_status(content_dir)
            self.assertEqual(status_map.get("LegacyLoose"), "Incompatible")

    def test_incomplete_container_needs_rebuild(self):
        with tempfile.TemporaryDirectory() as c_tmp:
            content_dir = Path(c_tmp)
            self._make_triplet("Partial_P", parts=("pak", "utoc"))
            mod_path = self._make_content_package(content_dir, "Partial", is_cooked=True)

            self.assertTrue(self.service.is_container_outdated("Partial_P", mod_path))
            status_map = self.service.check_sync_status(content_dir)
            self.assertEqual(status_map.get("Partial"), "Needs Rebuild")

    def test_disabled_container_outdated_detection(self):
        with tempfile.TemporaryDirectory() as c_tmp:
            content_dir = Path(c_tmp)
            t_old = time.time() - 400
            t_new = time.time() - 20
            self._make_triplet("DisabledMod_P", disabled=True, mtime=t_old)
            mod_path = self._make_content_package(content_dir, "DisabledMod", is_cooked=True, mtime=t_new)

            self.assertTrue(self.service.is_container_outdated("DisabledMod_P", mod_path))
            status_map = self.service.check_sync_status(content_dir)
            self.assertEqual(status_map.get("DisabledMod"), "Needs Rebuild")

    def test_sync_loose_mods_to_paks_compiles_only_compatible(self):
        with tempfile.TemporaryDirectory() as c_tmp:
            content_dir = Path(c_tmp)
            self._make_content_package(content_dir, "ModAlpha", is_cooked=True)
            self._make_content_package(content_dir, "ModBeta", is_cooked=True)
            self._make_content_package(content_dir, "ModGamma_Raw", is_cooked=False)

            mock_builder = MagicMock(spec=ZenBuilderService)
            mock_builder.build_triplet.side_effect = lambda source, name, out: ZenBuildResult(
                success=True,
                mod_name=name,
                pak_path=out / f"{name}_P.pak",
                utoc_path=out / f"{name}_P.utoc",
                ucas_path=out / f"{name}_P.ucas",
                log_output="OK",
            )
            # Use real scanning logic from ZenBuilderService
            real_builder = ZenBuilderService()
            mock_builder.get_content_packages.side_effect = real_builder.get_content_packages
            mock_builder.build_all_content_packages.side_effect = (
                lambda content_dir, output_mods_dir, only_outdated=False, progress_callback=None: [
                    mock_builder.build_triplet(pkg.source_dir, pkg.folder_name, output_mods_dir)
                    for pkg in real_builder.get_content_packages(content_dir, output_mods_dir)
                    if pkg.is_compatible and (not only_outdated or pkg.needs_rebuild)
                ]
            )

            results = self.service.sync_loose_mods_to_paks(content_dir, zen_builder=mock_builder)
            self.assertEqual(len(results), 2)
            built_names = {r.mod_name for r in results}
            self.assertEqual(built_names, {"ModAlpha", "ModBeta"})

    def test_sync_loose_mods_only_outdated(self):
        with tempfile.TemporaryDirectory() as c_tmp:
            content_dir = Path(c_tmp)
            t_old = time.time() - 600
            t_new = time.time() - 30

            # Up to date mod
            self._make_content_package(content_dir, "ModUpToDate", is_cooked=True, mtime=t_old)
            self._make_triplet("ModUpToDate_P", mtime=t_new)

            # Outdated mod
            self._make_content_package(content_dir, "ModOutdated", is_cooked=True, mtime=t_new)
            self._make_triplet("ModOutdated_P", mtime=t_old)

            mock_builder = MagicMock(spec=ZenBuilderService)
            mock_builder.build_triplet.side_effect = lambda source, name, out: ZenBuildResult(
                success=True,
                mod_name=name,
                pak_path=out / f"{name}_P.pak",
                utoc_path=out / f"{name}_P.utoc",
                ucas_path=out / f"{name}_P.ucas",
                log_output="OK",
            )
            real_builder = ZenBuilderService()
            mock_builder.get_content_packages.side_effect = real_builder.get_content_packages
            mock_builder.build_all_content_packages.side_effect = (
                lambda content_dir, output_mods_dir, only_outdated=False, progress_callback=None: [
                    mock_builder.build_triplet(pkg.source_dir, pkg.folder_name, output_mods_dir)
                    for pkg in real_builder.get_content_packages(content_dir, output_mods_dir)
                    if pkg.is_compatible and (not only_outdated or pkg.needs_rebuild)
                ]
            )

            results = self.service.sync_loose_mods_to_paks(
                content_dir, zen_builder=mock_builder, only_outdated=True
            )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].mod_name, "ModOutdated")


class TestZenBuilderService(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base_dir = Path(self._tmp.name)
        self.retoc = self.base_dir / "retoc.exe"
        self.retoc.write_bytes(b"dummy_retoc")
        self.stub_pak = self.base_dir / "stub.pak"
        self.stub_pak.write_bytes(b"STUB_PAK_DATA")
        self.builder = ZenBuilderService(retoc_exe=self.retoc, stub_pak=self.stub_pak)
        self.mods_dir = self.base_dir / "~mods"
        self.content_dir = self.base_dir / "content"
        self.mods_dir.mkdir()
        self.content_dir.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_helpers(self):
        self.assertEqual(get_container_base_name("TestMod"), "TestMod_P")
        self.assertEqual(get_container_base_name("TestMod_P"), "TestMod_P")

        loose_dir = self.content_dir / "Loose"
        loose_dir.mkdir()
        self.assertFalse(is_cooked_mod_dir(loose_dir))

        cooked_dir = self.content_dir / "Cooked" / "PesConsole" / "Content"
        cooked_dir.mkdir(parents=True)
        self.assertTrue(is_cooked_mod_dir(self.content_dir / "Cooked"))

    def test_build_triplet_invokes_retoc(self):
        source = self.content_dir / "MyFace"
        (source / "PesConsole" / "Content").mkdir(parents=True)
        (source / "PesConsole" / "Content" / "face.uasset").write_bytes(b"data")

        # Create disabled file to test cleanup
        (self.mods_dir / "MyFace_P.pak.disabled").write_bytes(b"old")

        def fake_subprocess_run(cmd, **kwargs):
            self.assertIn(str(self.retoc), cmd)
            self.assertIn(EFOOTBALL_AES_KEY, cmd)
            self.assertIn("to-zen", cmd)
            self.assertIn("UE4_26", cmd)
            # Simulate retoc producing .utoc and .ucas
            out_utoc = Path(cmd[-1])
            out_utoc.write_bytes(b"UTOC_MAGIC")
            out_ucas = out_utoc.with_suffix(".ucas")
            out_ucas.write_bytes(b"UCAS_DATA")
            mock_res = MagicMock()
            mock_res.returncode = 0
            mock_res.stdout = "Zen container created"
            mock_res.stderr = ""
            return mock_res

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            res = self.builder.build_triplet(source, "MyFace", self.mods_dir)

        self.assertTrue(res.success)
        self.assertEqual(res.mod_name, "MyFace")
        self.assertTrue((self.mods_dir / "MyFace_P.utoc").is_file())
        self.assertTrue((self.mods_dir / "MyFace_P.ucas").is_file())
        self.assertTrue((self.mods_dir / "MyFace_P.pak").is_file())
        # Companion pak copied from stub_pak
        self.assertEqual((self.mods_dir / "MyFace_P.pak").read_bytes(), b"STUB_PAK_DATA")
        # Old .disabled should have been cleaned up
        self.assertFalse((self.mods_dir / "MyFace_P.pak.disabled").exists())

    def test_build_all_content_packages_with_progress(self):
        pkg1 = self.content_dir / "Pkg1"
        (pkg1 / "PesConsole" / "Content").mkdir(parents=True)
        (pkg1 / "PesConsole" / "Content" / "a.uasset").write_bytes(b"1")

        pkg2 = self.content_dir / "Pkg2"
        (pkg2 / "PesConsole" / "Content").mkdir(parents=True)
        (pkg2 / "PesConsole" / "Content" / "b.uasset").write_bytes(b"2")

        progress_calls = []

        def on_progress(name, current, total):
            progress_calls.append((name, current, total))

        def fake_subprocess_run(cmd, **kwargs):
            out_utoc = Path(cmd[-1])
            out_utoc.write_bytes(b"UTOC")
            mock_res = MagicMock()
            mock_res.returncode = 0
            mock_res.stdout = "OK"
            mock_res.stderr = ""
            return mock_res

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            results = self.builder.build_all_content_packages(
                self.content_dir, self.mods_dir, progress_callback=on_progress
            )

        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.success for r in results))
        self.assertEqual(progress_calls, [("Pkg1", 1, 2), ("Pkg2", 2, 2)])


if __name__ == "__main__":
    unittest.main()
