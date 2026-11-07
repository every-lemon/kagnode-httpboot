from pathlib import Path
import importlib.util, json, socket, subprocess, sys, tempfile, unittest
from types import SimpleNamespace
from unittest.mock import patch

repo = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "repair", repo / "scripts/repair_update_progress.py"
)
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)
old = (repo / "httpboot/client_updates.py").read_text()
old = (
    old[: old.index("    def progress(")]
    + __import__("textwrap").indent(repair.OLD, "    ")
    + "\n"
    + old[old.index("    def snapshot(") :]
)
old = old.encode()
new = (repo / "httpboot/client_updates.py").read_bytes()


class RepairTests(unittest.TestCase):
    def test_canonical_and_legacy_layouts_are_detected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            canonical = root / "opt/kagnode/httpboot/client"
            legacy = root / "usr/local/lib/httpboot"
            self.assertIsNone(repair.select_root((canonical, legacy)))
            legacy.mkdir(parents=True)
            for name in ("client_updates.py", "client_power.py"):
                (legacy / name).write_text("# fixture")
            self.assertEqual(repair.select_root((canonical, legacy)), legacy)
            canonical.mkdir(parents=True)
            for name in ("client_updates.py", "client_power.py"):
                (canonical / name).write_text("# fixture")
            self.assertEqual(repair.select_root((canonical, legacy)), canonical)

    def test_known_module_fixed_idempotently(self):
        self.assertEqual(repair.replacement(old), new)
        self.assertEqual(repair.replacement(new), new)

    def test_intermediate_progress_fix_can_be_upgraded(self):
        text = new.decode()
        a = text.index("    def progress(")
        b = text.index("    def snapshot(", a)
        intermediate = (
            text[:a]
            + __import__("textwrap").indent(repair.INTERMEDIATE, "    ")
            + "\n"
            + text[b:]
        )
        self.assertEqual(repair.replacement(intermediate.encode()), new)

    def test_known_display_dependency_is_backed_up_and_relaxed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dropin = root / "httpboot.conf"
            original = (
                "[Unit]\nRequires=" + repair.UNIT + "\nAfter=" + repair.UNIT + "\n"
            ).encode()
            dropin.write_bytes(original)
            before = {
                "ActiveState": "active",
                "MainPID": "123",
                "Requires": repair.UNIT,
                "BindsTo": "",
            }
            after = {**before, "Requires": ""}
            with (
                patch.object(repair, "DISPLAY_DROPIN", dropin),
                patch.object(repair, "display_state", side_effect=[before, after]),
                patch.object(repair, "command") as command,
            ):
                self.assertEqual(repair.prepare_display(root), before)
            self.assertEqual(
                dropin.read_bytes(), original.replace(b"Requires=", b"Wants=")
            )
            self.assertEqual(
                (root / "display-manager-httpboot.conf.before").read_bytes(), original
            )
            command.assert_called_once_with("systemctl", "daemon-reload")

    def test_custom_display_dependencies_refuse_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dropin = root / "httpboot.conf"
            original = b"[Unit]\nRequires=custom-service.service\n"
            dropin.write_bytes(original)
            with (
                patch.object(repair, "DISPLAY_DROPIN", dropin),
                patch.object(
                    repair, "display_state", return_value={"Requires": repair.UNIT}
                ),
                patch.object(repair, "command") as command,
            ):
                with self.assertRaisesRegex(ValueError, "custom display dependency"):
                    repair.prepare_display(root)
                command.assert_not_called()
            self.assertEqual(dropin.read_bytes(), original)

    def test_unknown_function_refused(self):
        with self.assertRaisesRegex(ValueError, "Unrecognized"):
            repair.replacement(
                old.replace(
                    b'previous = self.state.get("message")', b'previous = "custom"'
                )
            )

    def test_other_local_edits_preserved(self):
        self.assertEqual(
            repair.replacement(old + b"\n# retained local comment\n"),
            new + b"\n# retained local comment\n",
        )

    def test_safe_runtime_service_restart_and_sessions_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            t = Path(temporary)
            root = t / "client"
            root.mkdir()
            run = t / "run"
            run.mkdir()
            (root / "client_updates.py").write_bytes(old)
            (root / "client_power.py").write_bytes(
                (repo / "httpboot/client_power.py").read_bytes()
            )
            caller = repair.pwd.getpwuid(0)
            sessions = {
                "0": {
                    "name": caller.pw_name,
                    "token": "isolated-fixture",
                    "ready": True,
                }
            }
            (run / "sessions.json").write_text(json.dumps(sessions))
            canary = t / "unsaved-work"
            canary.write_bytes(b"keep this work")
            actions = []

            def command(*args, **kw):
                actions.append(args)
                if args[0] == "findmnt":
                    return SimpleNamespace(stdout="overlay\n")
                if args[:2] == ("systemctl", "is-system-running"):
                    return SimpleNamespace(stdout="running\n")
                if args[:3] == ("systemctl", "show", "display-manager.service"):
                    return SimpleNamespace(
                        stdout="ActiveState=inactive\nMainPID=0\nRequires=\nBindsTo=\n"
                    )
                if args == ("systemctl", "restart", repair.UNIT):
                    return SimpleNamespace(stdout="")
                raise AssertionError(args)

            original_stat = Path.stat

            def fixture_stat(path, *args, **kwargs):
                result = original_stat(path, *args, **kwargs)
                if path == run / "update-progress-repair":
                    return SimpleNamespace(st_uid=0, st_mode=result.st_mode)
                return result

            with socket.socket(socket.AF_UNIX) as control:
                control.bind(str(run / "control.sock"))
                with (
                    patch.object(repair.os, "geteuid", return_value=0),
                    patch.object(Path, "stat", fixture_stat),
                    patch.object(repair, "ROOT", root),
                    patch.object(repair, "RUN", run),
                    patch.object(repair, "command", command),
                    patch.object(repair, "workers", return_value=False),
                    patch.object(
                        repair,
                        "state",
                        return_value={
                            "power": {"state": "idle"},
                            "operation": {"state": "failed"},
                            "session_ready": True,
                        },
                    ),
                    patch.object(sys, "argv", ["repair"]),
                ):
                    repair.main()
            self.assertEqual((root / "client_updates.py").read_bytes(), new)
            self.assertEqual(json.loads((run / "sessions.json").read_text()), sessions)
            self.assertEqual(canary.read_bytes(), b"keep this work")
            self.assertIn(("systemctl", "restart", repair.UNIT), actions)
            self.assertFalse(any("reboot" in x or "poweroff" in x for x in actions))
            self.assertTrue((run / "update-progress-repair/result.json").is_file())


if __name__ == "__main__":
    unittest.main()
