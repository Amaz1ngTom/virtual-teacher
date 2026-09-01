from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from app.config import Settings, resolve_project_path
from app.launch import worker_command
from scripts.maintenance.export_github_source import check_source, export_source, selected_files


class PortableConfigTests(unittest.TestCase):
    def test_relative_paths_are_project_root_based(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(resolve_project_path(root, "assets/a.png"), root / "assets" / "a.png")
            self.assertEqual(resolve_project_path(root, root / "absolute.png"), root / "absolute.png")

    def test_clean_settings_do_not_read_developer_dotenv(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"VT_DATA_DIR": directory}, clear=True), patch("app.config.load_dotenv"):
                settings = Settings.from_env()
            self.assertEqual(settings.llm_mode, "rule")
            self.assertEqual(settings.qwen_api_key, "")
            self.assertTrue(settings.avatar_reference_image.is_file())
            self.assertTrue(settings.float_reference_image.is_file())

    def test_worker_uses_explicit_interpreter_and_gpu(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = SimpleNamespace(project_root=root, float_reference_image=root / "teacher.png", tts_output_dir=root / "audio")
            with patch.dict(os.environ, {"VT_FLOAT_PYTHON": "float-python", "VT_FLOAT_ROOT": "models/float", "VT_FLOAT_CUDA_VISIBLE_DEVICES": "4"}, clear=True):
                command = worker_command(settings, 8012)
            self.assertEqual(command[0], "float-python")
            self.assertEqual(command[command.index("--float-root") + 1], str(root / "models" / "float"))
            self.assertEqual(command[command.index("--cuda-visible-devices") + 1], "4")
            self.assertEqual(command[command.index("--port") + 1], "8012")

    def test_worker_can_use_separate_conda_environment(self):
        root = Path.cwd()
        settings = SimpleNamespace(project_root=root, float_reference_image=root / "teacher.png", tts_output_dir=root / "audio")
        with patch.dict(os.environ, {}, clear=True), patch("app.launch.shutil.which", return_value="conda"):
            command = worker_command(settings, 8011)
        self.assertEqual(command[:6], ["conda", "run", "--no-capture-output", "-n", "FLOAT", "python"])
        self.assertNotIn("--cuda-visible-devices", command)


class SourceExportTests(unittest.TestCase):
    def test_export_excludes_private_files_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixtures = {
                "README.md": "public", ".env.example": "VT_QWEN_API_KEY=\n",
                ".env": "private", ".git/config": "private", "data/history.json": "private",
                "scripts/local.settings.bat": "private", "scripts/my_startfloatsession.bat": "private",
                "docs/current-project-status.md": "private", "assets/teacher/idle.mp4": "private",
                "models/weights.bin": "private", "frontend/node_modules/local.js": "private",
                "scripts/maintenance/export_float_aligned_reference.py": "excluded helper",
            }
            for name, value in fixtures.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value, encoding="utf-8")
            target, archive = export_source(root, require_complete=False)
            actual = {p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()}
            self.assertEqual(actual, {"README.md", ".env.example", "SOURCE_MANIFEST.sha256"})
            manifest = (target / "SOURCE_MANIFEST.sha256").read_text()
            self.assertIn(hashlib.sha256(b"public").hexdigest(), manifest)
            self.assertEqual((root / ".env").read_text(), "private")
            with zipfile.ZipFile(archive) as zipped:
                self.assertEqual(len(zipped.namelist()), 3)
            second, _ = export_source(root, require_complete=False)
            self.assertNotEqual(target, second)

    def test_scan_rejects_secret_without_echoing_value(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = "sk-" + "a" * 32
            (root / "README.md").write_text(secret)
            with self.assertRaises(ValueError) as captured:
                check_source(root, require_complete=False)
            self.assertIn("README.md", str(captured.exception))
            self.assertNotIn(secret, str(captured.exception))
            self.assertFalse((root / "dist").exists())

    def test_missing_required_release_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "Required release files missing"):
                check_source(Path(directory))

    def test_external_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            other = Path(outside) / "secret.txt"
            other.write_text("private")
            try:
                (root / "README.md").symlink_to(other)
            except OSError:
                self.skipTest("OS does not permit symlink creation")
            with self.assertRaises(ValueError):
                selected_files(root)


if __name__ == "__main__":
    unittest.main()
