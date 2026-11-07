"""No image builds or native kernel execution: startup changes use isolated fixtures."""

import io
import os
import ssl
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "httpboot"))
from boot_splash import install, boot_commandline
from boot_ui import Progress
from kernel_stage import launch
from image_delivery import download


class StartupPresentationTests(unittest.TestCase):
    def test_actual_gauge_redraw_keeps_identity_in_the_dialog(self):
        with patch("sys.stdout", io.StringIO()):
            progress = Progress()
        progress.interactive = True
        process = MagicMock()
        with (
            patch("builtins.open", mock_open()),
            patch("boot_ui.subprocess.Popen", return_value=process) as spawn,
        ):
            progress.progress(bytes_done=1, bytes_total=10)
            progress.last = 0
            progress.progress(bytes_done=5, bytes_total=10)
            self.assertIn("KagNode.", spawn.call_args[0][0][4])
            self.assertIn("KagNode.", process.stdin.write.call_args[0][0])
            self.assertIn("MiB", process.stdin.write.call_args[0][0])
            progress.close()

    def test_download_dialog_keeps_logo_during_every_update(self):
        with patch("sys.stdout", io.StringIO()):
            progress = Progress()
        with patch("os.get_terminal_size", return_value=os.terminal_size((80, 24))):
            content, height, width = progress.display(
                "Downloading image", "1 / 4 MiB\nConnection interrupted; resuming"
            )
        self.assertIn("KagNode.", content)
        self.assertIn("#", content)
        self.assertIn("Downloading image", content)
        self.assertIn("resuming", content)
        self.assertLessEqual(len(content.splitlines()), int(height) - 4)
        self.assertLessEqual(int(width), 78)

    def test_splash_uses_distribution_art_and_preserves_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "usr/share/plymouth/ubuntu-logo.png"
            original.parent.mkdir(parents=True)
            original.write_bytes(b"original-ubuntu-logo-fixture")
            target = install(root)
            self.assertEqual(
                (target / "ubuntu.png").read_bytes(), original.read_bytes()
            )
            self.assertTrue(
                (target / "kagnode.png").read_bytes().startswith(b"\x89PNG")
            )
            self.assertIn("KagNode × Ubuntu", (target / "kagnode.plymouth").read_text())
            self.assertIn(
                "Theme=kagnode", (root / "etc/plymouth/plymouthd.conf").read_text()
            )
        self.assertIn("quiet", boot_commandline().split())
        self.assertIn("splash", boot_commandline().split())
        self.assertIn("httpboot.recovery=1", boot_commandline(recovery=True).split())
        self.assertNotIn("quiet", boot_commandline(debug=True).split())
        self.assertIn("plymouth.enable=0", boot_commandline(debug=True).split())

    def test_kernel_identity_mismatch_never_calls_kexec(self):
        with patch("kernel_stage.subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "does not match"):
                launch(
                    {".uname": b"wrong-kernel\0"},
                    "release",
                    Path("/fixture"),
                    expected_kernel="approved-kernel",
                )
            run.assert_not_called()


class RetryTests(unittest.TestCase):
    def test_transient_failure_preserves_partial_and_reports_bounded_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "image"
            partial = target.with_name("image.partial")
            calls = []

            def attempt(*args):
                calls.append(1)
                if len(calls) == 1:
                    partial.write_bytes(b"retained")
                    raise ConnectionResetError("interrupted")
                self.assertEqual(partial.read_bytes(), b"retained")
                return target

            updates = []
            with (
                patch("image_delivery._download_once", side_effect=attempt),
                patch("image_delivery.time.sleep"),
            ):
                self.assertEqual(
                    download(
                        "https://server",
                        "release",
                        "filesystem.squashfs",
                        {"size": 50},
                        Path(temp),
                        target,
                        lambda **v: updates.append(v),
                    ),
                    target,
                )
            self.assertEqual(len(calls), 2)
            self.assertEqual(updates[0]["retry_attempt"], 2)
            self.assertEqual(updates[0]["bytes_done"], len(b"retained"))

    def test_trust_and_storage_errors_are_not_retried(self):
        for error in (
            ssl.SSLCertVerificationError("untrusted"),
            OSError(28, "No space"),
            ValueError("checksum mismatch"),
        ):
            with (
                patch("image_delivery._download_once", side_effect=error) as run,
                patch("image_delivery.time.sleep") as sleep,
            ):
                with self.assertRaises(type(error)):
                    download(
                        "https://server",
                        "release",
                        "filesystem.squashfs",
                        {"size": 50},
                        Path("/fixture"),
                        Path("/fixture/image"),
                    )
                self.assertEqual(run.call_count, 1)
                sleep.assert_not_called()
        with (
            patch(
                "image_delivery._download_once", side_effect=TimeoutError("offline")
            ) as run,
            patch("image_delivery.time.sleep"),
        ):
            with self.assertRaises(TimeoutError):
                download(
                    "https://server",
                    "release",
                    "filesystem.squashfs",
                    {"size": 50},
                    Path("/fixture"),
                    Path("/fixture/image"),
                )
            self.assertEqual(run.call_count, 3)


if __name__ == "__main__":
    unittest.main()
