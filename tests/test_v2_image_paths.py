import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "httpboot"))
from image_paths import CLIENT_LIBRARY, LEGACY_CLIENT_LIBRARY, client_library


class ClientImagePathTests(unittest.TestCase):
    def test_installed_code_and_fonts_are_readable_under_private_umask(self):
        from build_public import install_client

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "etc/pam.d").mkdir(parents=True)
            (root / "etc/pam.d/common-session").write_text(
                "session optional pam_systemd.so\n"
            )
            (root / "etc/cups").mkdir(parents=True)
            (root / "etc/cups/cupsd.conf").write_text("Listen localhost:631\n")
            previous = os.umask(0o077)
            try:
                with patch("build_public.run"):
                    install_client(root)
            finally:
                os.umask(previous)
            for name in ("client_ui.py", "client_worker.py", "client_agent.py"):
                self.assertEqual(
                    (root / CLIENT_LIBRARY / name).stat().st_mode & 0o777, 0o644
                )
            for font in (root / "usr/local/share/fonts/kagnode/httpboot").iterdir():
                self.assertEqual(font.stat().st_mode & 0o777, 0o644)
            unit = root / "etc/systemd/user/httpboot-saver-v2.service"
            self.assertEqual(unit.stat().st_mode & 0o777, 0o644)
            self.assertEqual(unit.parent.stat().st_mode & 0o777, 0o755)
            self.assertEqual(
                (unit.parent / "default.target.wants").stat().st_mode & 0o777, 0o755
            )
            self.assertTrue((root / LEGACY_CLIENT_LIBRARY / "client_ui.py").is_file())

    def test_public_image_audit_refuses_retained_legacy_server_configuration(self):
        from build_public import audit_root

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "etc/httpboot").mkdir(parents=True)
            secret = root / "etc/httpboot/fixture-config"
            secret.write_text("deployment-specific fixture")
            (root / "etc/passwd").write_text("root:x:0:0:root:/root:/bin/bash\n")
            (root / "etc/shadow").write_text("root:!:1::::::\n")
            (root / "etc/resolv.conf").symlink_to(
                "/run/systemd/resolve/stub-resolv.conf"
            )
            (root / "home").mkdir()
            with self.assertRaisesRegex(ValueError, "deployment-specific"):
                audit_root(root)
            self.assertEqual(secret.read_text(), "deployment-specific fixture")

    def test_private_umask_does_not_hide_code_from_client_users(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = os.umask(0o077)
            try:
                current = client_library(root)
            finally:
                os.umask(previous)
            for path in (
                current,
                current.parent,
                current.parent.parent,
                root / "opt",
                root / "usr/local/lib",
            ):
                self.assertEqual(path.stat().st_mode & 0o777, 0o755)

    def test_fresh_image_uses_canonical_path_and_compatible_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = client_library(root)
            self.assertEqual(current, root / CLIENT_LIBRARY)
            (current / "client.py").write_text("fixture code")
            old = root / LEGACY_CLIENT_LIBRARY
            self.assertTrue(old.is_symlink())
            self.assertEqual((old / "client.py").read_text(), "fixture code")
            self.assertEqual(client_library(root), current)

    def test_retained_private_launcher_bytes_and_modes_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / LEGACY_CLIENT_LIBRARY
            old.mkdir(parents=True)
            launcher = old / "chrome-launch"
            launcher.write_bytes(b"original private launcher")
            launcher.chmod(0o750)
            inode = launcher.stat().st_ino
            current = client_library(root)
            self.assertEqual(
                (current / launcher.name).read_bytes(), b"original private launcher"
            )
            self.assertEqual((current / launcher.name).stat().st_mode & 0o777, 0o750)
            self.assertEqual((old / launcher.name).stat().st_ino, inode)

    def test_conflicting_trees_are_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in (CLIENT_LIBRARY, LEGACY_CLIENT_LIBRARY):
                (root / path).mkdir(parents=True)
                (root / path / "preserve").write_text(str(path))
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                client_library(root)
            for path in (CLIENT_LIBRARY, LEGACY_CLIENT_LIBRARY):
                self.assertEqual((root / path / "preserve").read_text(), str(path))

    def test_external_symlinks_are_not_followed(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            tempfile.TemporaryDirectory() as outside,
        ):
            root = Path(directory)
            old = root / LEGACY_CLIENT_LIBRARY
            old.parent.mkdir(parents=True)
            old.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "Unexpected"):
                client_library(root)
            self.assertEqual(os.readlink(old), outside)
            self.assertEqual(list(Path(outside).iterdir()), [])
            old.unlink()
            (root / "opt").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "parent"):
                client_library(root)
            self.assertEqual(list(Path(outside).iterdir()), [])
