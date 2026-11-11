#!/usr/bin/env python3
"""KagNode HTTP Boot progress repair; preserves RAM work and session journals."""

import ast, hashlib, json, os, pathlib, pwd, socket, subprocess, sys, tempfile, textwrap, time

OLD = """def progress(self, message, **values):
    with self.state_lock:
        now = time.time()
        previous = self.state.get("message")
        self.state.update(
            message=message,
            updated=now,
            elapsed_seconds=round(now - self.state.get("started", now)),
            **values,
        )
        if previous != message:
            self.state["logs"] = (
                self.state.get("logs", []) + [{"time": now, "message": message}]
            )[-200:]
        dump(self.path, self.state)
        dump(self.agent.run / "update-current.json", self.state)
"""
INTERMEDIATE = """def progress(self, message, **values):
    with self.state_lock:
        now = time.time()
        previous = self.state.get("message")
        self.state.update(
            {
                "elapsed_seconds": round(now - self.state.get("started", now)),
                **values,
                "message": message,
                "updated": now,
            }
        )
        if previous != message:
            self.state["logs"] = (
                self.state.get("logs", []) + [{"time": now, "message": message}]
            )[-200:]
        dump(self.path, self.state)
        dump(self.agent.run / "update-current.json", self.state)
"""
NEW = """def progress(self, message, **values):
    with self.state_lock:
        now = time.time()
        previous = self.state.get("message")
        old_state = self.state.get("state")
        old_phase = self.state.get("phase")
        reset = {}
        if values.get("phase", old_phase) != old_phase or (
            previous != message and "bytes_total" not in values
        ):
            reset = {
                "bytes_done": 0,
                "bytes_total": 0,
                "bytes_per_second": 0,
                "eta_seconds": None,
                "io_stage": None,
                "percent": 0,
            }
        self.state.update(
            {
                **reset,
                "elapsed_seconds": round(now - self.state.get("started", now)),
                **values,
                "message": message,
                "updated": now,
            }
        )
        if previous != message:
            self.state["logs"] = (
                self.state.get("logs", []) + [{"time": now, "message": message}]
            )[-200:]
        # RAM status stays responsive; durable phase changes are preserved.
        # Repeated transfer samples need not fsync the boot card per MiB.
        dump(self.agent.run / "update-current.json", self.state)
        if (
            previous != message
            or old_state != self.state.get("state")
            or old_phase != self.state.get("phase")
            or now - getattr(self, "_last_progress_persist", 0) >= 10
        ):
            dump(self.path, self.state)
            self._last_progress_persist = now
"""
POWER_GUARD = "FunctionDef(name='main', args=arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]), body=[Assign(targets=[Name(id='state', ctx=Store())], value=Call(func=Attribute(value=Attribute(value=Call(func=Attribute(value=Name(id='subprocess', ctx=Load()), attr='run', ctx=Load()), args=[List(elts=[Constant(value='systemctl'), Constant(value='is-system-running')], ctx=Load())], keywords=[keyword(arg='capture_output', value=Constant(value=True)), keyword(arg='text', value=Constant(value=True))]), attr='stdout', ctx=Load()), attr='strip', ctx=Load()), args=[], keywords=[])), If(test=Compare(left=Name(id='state', ctx=Load()), ops=[NotEq()], comparators=[Constant(value='stopping')]), body=[Return()], orelse=[]), ImportFrom(module='client_agent', names=[alias(name='rpc')], level=0), Expr(value=Call(func=Name(id='rpc', ctx=Load()), args=[Constant(value='shutdown-cleanup')], keywords=[]))], decorator_list=[], type_params=[])"
ROOTS = (
    pathlib.Path("/opt/kagnode/httpboot/client"),
    pathlib.Path("/usr/local/lib/httpboot"),
)


def select_root(roots):
    return next(
        (
            root
            for root in roots
            if (root / "client_updates.py").is_file()
            and (root / "client_power.py").is_file()
        ),
        None,
    )


ROOT = select_root(ROOTS) or ROOTS[0]
RUN = pathlib.Path("/run/httpboot-v2")
UNIT = "httpboot-client-v2.service"
DISPLAY_DROPIN = pathlib.Path(
    "/etc/systemd/system/display-manager.service.d/httpboot.conf"
)


def replacement(raw):
    text = raw.decode()
    tree = ast.parse(text)
    cls = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Updates"
    )
    node = next(
        n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "progress"
    )
    observed = ast.dump(node, include_attributes=False)
    expected = {
        ast.dump(ast.parse(value).body[0], include_attributes=False)
        for value in (OLD, INTERMEDIATE)
    }
    fixed = ast.dump(ast.parse(NEW).body[0], include_attributes=False)
    if observed == fixed:
        return raw
    if observed not in expected:
        raise ValueError("Unrecognized progress function; no changes made")
    lines = text.splitlines(keepends=True)
    lines[node.lineno - 1 : node.end_lineno] = [
        textwrap.indent(NEW, " " * node.col_offset)
    ]
    changed = "".join(lines).encode()
    compile(changed, str(ROOT / "client_updates.py"), "exec")
    return changed


def command(*args, **kw):
    kw.setdefault("check", True)
    return subprocess.run(list(args), capture_output=True, text=True, **kw)


def journal():
    return json.loads((RUN / "sessions.json").read_text())


def state(name):
    code = "import sys,json;sys.path.insert(0,ROOT_PLACEHOLDER);from client_agent import rpc;print(json.dumps(rpc('state',timeout=10)))"
    code = code.replace("ROOT_PLACEHOLDER", repr(str(ROOT)))
    return json.loads(
        command(
            "runuser", "-u", name, "--", "/usr/bin/python3", "-c", code, timeout=15
        ).stdout
    )


def workers():
    for p in pathlib.Path("/proc").glob("[0-9]*/cmdline"):
        try:
            parts = [
                x.decode(errors="replace") for x in p.read_bytes().split(b"\0") if x
            ]
        except OSError:
            continue
        if any(pathlib.Path(x).name == "client_worker.py" for x in parts) and any(
            x in ("save", "restore") for x in parts
        ):
            return True
    return False


def write_atomic(path, data):
    fd, temporary = tempfile.mkstemp(prefix=".httpboot-repair-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def display_state():
    text = command(
        "systemctl",
        "show",
        "display-manager.service",
        "-p",
        "ActiveState",
        "-p",
        "MainPID",
        "-p",
        "Requires",
        "-p",
        "BindsTo",
    ).stdout
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def prepare_display(backup):
    before = display_state()
    strong = lambda data: (
        UNIT in (data.get("Requires", "") + " " + data.get("BindsTo", "")).split()
    )
    if not strong(before):
        return before
    expected = ("[Unit]\nRequires=" + UNIT + "\nAfter=" + UNIT + "\n").encode()
    if (
        not DISPLAY_DROPIN.is_file()
        or DISPLAY_DROPIN.is_symlink()
        or DISPLAY_DROPIN.read_bytes() != expected
    ):
        raise ValueError(
            "A custom display dependency would close the desktop during restart. No Client service restart was performed"
        )
    (backup / "display-manager-httpboot.conf.before").write_bytes(expected)
    (backup / "display-manager-httpboot.conf.before").chmod(0o600)
    write_atomic(DISPLAY_DROPIN, expected.replace(b"Requires=", b"Wants="))
    command("systemctl", "daemon-reload")
    if strong(display_state()):
        write_atomic(DISPLAY_DROPIN, expected)
        command("systemctl", "daemon-reload")
        raise ValueError(
            "Another display dependency still requires the Client authority. No service restart was performed"
        )
    return before


def main():
    if os.geteuid() != 0:
        raise ValueError("Run this repair with sudo on the HTTP Boot Client")
    fs = command("findmnt", "-n", "-o", "FSTYPE", "/").stdout.strip()
    if (
        fs not in ("overlay", "tmpfs", "ramfs")
        or not (RUN / "control.sock").is_socket()
    ):
        raise ValueError(
            "This repair is only for the running diskless HTTP Boot Client"
        )
    if (
        command("systemctl", "is-system-running", check=False).stdout.strip()
        == "stopping"
    ):
        raise ValueError("Wait until shutdown is cancelled; no changes made")
    p = ROOT / "client_updates.py"
    raw = p.read_bytes()
    fixed = replacement(raw)
    power = ast.parse((ROOT / "client_power.py").read_text())
    guard = next(
        n for n in power.body if isinstance(n, ast.FunctionDef) and n.name == "main"
    )
    if ast.dump(guard, include_attributes=False) != POWER_GUARD:
        raise ValueError("Unrecognized service-restart safety guard; no changes made")
    if "--check" in sys.argv:
        print(
            "Recognized progress code and safe service-restart guard; no files changed"
        )
        return
    before = journal()
    if not before:
        raise ValueError("Sign into the HTTP Boot desktop before applying this repair")
    names = [pwd.getpwuid(int(uid)).pw_name for uid in before]
    deadline = time.monotonic() + 180
    while True:
        states = [state(name) for name in names]
        busy = workers() or any(
            s["power"].get("state") == "running"
            or s["operation"].get("state") == "running"
            or s.get("saving_paused")
            or not s.get("session_ready")
            for s in states
        )
        if not busy:
            break
        if time.monotonic() > deadline:
            raise ValueError(
                "A save or update is still running. No files changed; retry after it finishes"
            )
        time.sleep(2)
    backup = RUN / "update-progress-repair"
    backup.mkdir(mode=0o700, exist_ok=True)
    if (
        backup.is_symlink()
        or backup.stat().st_uid != 0
        or backup.stat().st_mode & 0o077
    ):
        raise ValueError("Unsafe backup directory; no changes made")
    if fixed == raw and all(
        "elapsed_seconds" not in item["operation"].get("message", "") for item in states
    ):
        print("The progress fix is already installed; no services restarted")
        return
    display_before = prepare_display(backup)
    digest = hashlib.sha256(raw).hexdigest()
    saved = backup / (digest + ".py")
    if not saved.exists():
        saved.write_bytes(raw)
        saved.chmod(0o600)
    if fixed != raw:
        fd, tmp = tempfile.mkstemp(prefix=".update-progress-", dir=ROOT)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(fixed)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o644)
            os.replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    command("systemctl", "restart", UNIT, timeout=180)
    deadline = time.monotonic() + 60
    while True:
        try:
            after = journal()
            if {(k, v.get("name"), v.get("token")) for k, v in before.items()} != {
                (k, v.get("name"), v.get("token")) for k, v in after.items()
            }:
                raise RuntimeError(
                    "Session identities changed during repair. Do not reboot; inspect the Client service log"
                )
            [state(name) for name in names]
            break
        except (OSError, ValueError, subprocess.SubprocessError):
            if time.monotonic() > deadline:
                raise ValueError(
                    "Repair installed, but Client service has not become ready. Do not reboot; inspect its service log"
                )
            time.sleep(2)
    display_after = display_state()
    if display_before.get("ActiveState") == "active" and (
        display_after.get("ActiveState") != "active"
        or display_before.get("MainPID") != display_after.get("MainPID")
    ):
        raise RuntimeError(
            "The display manager changed unexpectedly. Inspect its service log before further maintenance"
        )
    (backup / "result.json").write_text(
        json.dumps(
            {
                "repaired": True,
                "module_sha256": hashlib.sha256(fixed).hexdigest(),
                "session_identities_preserved": True,
                "client_rebooted": False,
            }
        )
        + "\n"
    )
    print(
        "Update progress repaired. Apps and RAM work were retained. Open HTTP Boot > Updates and choose Retry if needed."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        raise SystemExit(str(e))
