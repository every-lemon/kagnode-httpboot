"""Exercise real administration dispatch outside the long-running serve branch."""

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "httpboot"))
from server_v2 import Authority


@unittest.skipUnless(os.geteuid() == 0, "Server CLI requires root")
class ServerCliTests(unittest.TestCase):
    def test_pin_image_retains_existing_image_and_reports_unknown_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            authority = Authority(state / "authority.sqlite3")
            try:
                with authority.db() as db:
                    db.execute(
                        "INSERT INTO images VALUES (?,?,?,1)",
                        ("test-3.1.16", json.dumps({"release": "test-3.1.16"}), 0),
                    )

                def run(image):
                    return subprocess.run(
                        [
                            sys.executable,
                            str(ROOT / "httpboot/server_v2.py"),
                            "--state",
                            str(state),
                            "pin-image",
                            image,
                            "qualification-retain",
                        ],
                        capture_output=True,
                        text=True,
                    )

                result = run("test-3.1.16")
                self.assertEqual(result.returncode, 0, result.stderr)
                with authority.db(write=False) as db:
                    self.assertEqual(
                        [
                            tuple(r)
                            for r in db.execute("SELECT image,reason FROM image_pins")
                        ],
                        [("test-3.1.16", "qualification-retain")],
                    )
                    self.assertEqual(
                        db.execute("SELECT active FROM images").fetchone()[0], 1
                    )
                result = run("missing-image")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Unknown image", result.stderr)
                self.assertNotIn("UnboundLocalError", result.stderr)
            finally:
                authority.close()
