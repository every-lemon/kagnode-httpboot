"""Background Client updates: verify transfer and card readback, then await restart."""

import json
import hashlib
import os
import subprocess
import threading
import time
from pathlib import Path
from common import atomic, dump, load, sha256
import tempfile
import shutil
from image_delivery import download
from boot_client_v2 import verify_manifest


def copy_verified(source, target, checksum, progress=None):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    size = Path(source).stat().st_size
    started = time.monotonic()
    last_report = 0.0

    def report(done, step, force=False):
        nonlocal last_report
        now = time.monotonic()
        if progress is None or (not force and now - last_report < 0.5):
            return
        last_report = now
        elapsed = max(0.001, now - started)
        total = 0 if step == "flushing" else size * 2
        speed = done / elapsed
        progress(
            bytes_done=done if total else 0,
            bytes_total=total,
            bytes_per_second=speed if total else 0,
            elapsed_seconds=elapsed,
            eta_seconds=(total - done) / speed if total and speed else None,
            io_stage=step,
        )

    descriptor, temporary = tempfile.mkstemp(
        prefix=".httpboot-update-", dir=target.parent
    )
    try:
        done = 0
        with os.fdopen(descriptor, "wb") as out, open(source, "rb") as stream:
            while block := stream.read(1024 * 1024):
                out.write(block)
                done += len(block)
                report(done, "copying")
            out.flush()
            report(done, "flushing", True)
            os.fsync(out.fileno())
        digest = hashlib.sha256()
        with open(temporary, "rb") as check:
            while block := check.read(1024 * 1024):
                digest.update(block)
                done += len(block)
                report(done, "verifying")
        if digest.hexdigest() != checksum:
            raise ValueError("Startup-file copy failed verification")
        report(done, "verifying", True)
        os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            report(done, "flushing", True)
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Updates:
    def __init__(self, agent):
        self.agent = agent
        self.lock = threading.Lock()
        self.state_lock = threading.RLock()
        self.path = agent.run / "update-operation.json"
        location = agent.run / "cache-location"
        media = agent.run / "media"
        if location.is_file() and media.is_mount():
            identity = Path(location.read_text().strip())
            if identity == media / "httpboot-v2/identity":
                self.path = identity / "update-operation.json"
        self.state = (
            load(self.path) if self.path.exists() else {"state": "idle", "logs": []}
        )
        current = Path("/run/httpboot/filesystem.metadata.json")
        if current.is_file() and load(current).get("release") == self.state.get(
            "release"
        ):
            self.progress(
                "This verified update is running", state="completed", phase="applied"
            )
        if self.state.get("state") == "running":
            self.progress(
                "Update service restarted; completed downloads are retained. Choose Retry.",
                state="failed",
            )

    def progress(self, message, **values):
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

    def snapshot(self):
        with self.state_lock:
            return json.loads(json.dumps(self.state))

    def start(self, retry=False):
        if not self.lock.acquire(False):
            raise ValueError("An update is already running")

        def execute():
            try:
                items = self.agent.call("/v2/recovery/images")["images"]
                if retry and self.state.get("release"):
                    selected = next(
                        (i for i in items if i["release"] == self.state["release"]),
                        None,
                    )
                else:
                    latest = self.agent.call("/v2/images")["images"]
                    selected = latest[0] if latest else None
                if not selected:
                    raise ValueError("No validated image is available")
                if (
                    self.state.get("release") == selected["release"]
                    and self.state.get("phase") == "ready-to-restart"
                ):
                    return
                verify_manifest(
                    selected,
                    self.agent.credentials / "ca.pem",
                    self.agent.config["server"],
                )
                self.state = {
                    "state": "running",
                    "release": selected["release"],
                    "started": time.time(),
                    "logs": [],
                }
                self.progress(
                    "Preparing update; your applications can remain open",
                    phase="preparing",
                )
                cache = (
                    self.path.parent / "update-downloads"
                    if self.path.parent != self.agent.run
                    else self.agent.run / "updates"
                ) / selected["release"]
                cache.mkdir(parents=True, exist_ok=True)
                for name in ("boot.efi", "recovery.efi", "recovery.squashfs"):
                    self.progress("Downloading " + name, phase="downloading")
                    from recovery_cache import reuse

                    if not (
                        self.path.parent != self.agent.run
                        and name.startswith("recovery.")
                        and reuse(self.path.parent, selected, name, cache / name)
                    ):
                        download(
                            self.agent.url,
                            selected["release"],
                            name,
                            selected["artifacts"][name],
                            self.agent.credentials,
                            cache / name,
                            lambda **values: self.progress(
                                "Downloading " + name, phase="downloading", **values
                            ),
                        )
                self.progress(
                    "Download complete; checking available boot media",
                    phase="download-complete",
                )
                location = self.agent.run / "cache-location"
                media = self.agent.run / "media"
                candidate = None
                if location.is_file() and media.is_mount():
                    identity = Path(location.read_text().strip())
                    if identity != media / "httpboot-v2/identity":
                        raise ValueError("Boot-media identity location changed")
                    source = subprocess.run(
                        ["findmnt", "-n", "-o", "SOURCE", "--target", str(media)],
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout.strip()
                    if not source.startswith("/dev/"):
                        raise ValueError("Boot medium is not a block device")
                    self.progress(
                        "Writing verified candidate startup files", phase="writing-card"
                    )
                    candidate = media / "httpboot-v2/candidate"
                    candidate.mkdir(parents=True, exist_ok=True)
                    for name in ("boot.efi", "recovery.efi", "recovery.squashfs"):
                        copy_verified(
                            cache / name,
                            candidate / name,
                            selected["artifacts"][name]["sha256"],
                            progress=lambda **values: self.progress(
                                "Writing " + name + " to boot media",
                                phase="writing-card",
                                **values,
                            ),
                        )
                    self.progress(
                        "Flushing candidate boot files", phase="flushing-card"
                    )
                    subprocess.run(["umount", str(media)], check=True)
                    subprocess.run(
                        [
                            "mount",
                            "-t",
                            "vfat",
                            "-o",
                            "rw,nosuid,nodev,noexec,umask=0077",
                            source,
                            str(media),
                        ],
                        check=True,
                    )
                    for name in ("boot.efi", "recovery.efi", "recovery.squashfs"):
                        if (
                            sha256(candidate / name)
                            != selected["artifacts"][name]["sha256"]
                        ):
                            raise ValueError("Boot card readback failed")
                    destination = media / "EFI/BOOT/BOOTX64.EFI"
                    recovery = media / "EFI/HTTPBOOT/RECOVERY.EFI"
                    self.progress(
                        "Preserving previous startup files", phase="preparing-rollback"
                    )
                    # Retain the old startup pair and recovery cache for manual rollback.
                    backup = media / "httpboot-v2/previous"
                    backup.mkdir(exist_ok=True)
                    for old, label in (
                        (destination, "boot.efi"),
                        (recovery, "recovery.efi"),
                        (identity / "recovery.squashfs", "recovery.squashfs"),
                        (identity / "verified-image.json", "verified-image.json"),
                    ):
                        if old.is_file():
                            shutil.copyfile(old, backup / label)
                    from recovery_cache import publish

                    self.progress(
                        "Committing verified recovery generation",
                        phase="committing-recovery",
                    )
                    recovery_generation = publish(identity, selected, candidate)
                    # Recovery must be durable before the default bootstrap can
                    # change. A failed cache commit keeps the working EFI pair.
                    self.progress(
                        "Promoting verified startup files", phase="promoting-card"
                    )
                    copy_verified(
                        candidate / "recovery.efi",
                        recovery,
                        selected["artifacts"]["recovery.efi"]["sha256"],
                    )
                    copy_verified(
                        candidate / "boot.efi",
                        destination,
                        selected["artifacts"]["boot.efi"]["sha256"],
                    )
                    subprocess.run(["umount", str(media)], check=True)
                    subprocess.run(
                        [
                            "mount",
                            "-t",
                            "vfat",
                            "-o",
                            "rw,nosuid,nodev,noexec,umask=0077",
                            source,
                            str(media),
                        ],
                        check=True,
                    )
                    for name, path in (
                        ("boot.efi", destination),
                        ("recovery.efi", recovery),
                        (
                            "recovery.squashfs",
                            recovery_generation / "recovery.squashfs",
                        ),
                    ):
                        self.progress(
                            "Checking promoted " + name, phase="promotion-readback"
                        )
                        if sha256(path) != selected["artifacts"][name]["sha256"]:
                            raise ValueError(
                                "Promoted boot-card readback failed; previous startup files retained"
                            )
                    self.progress("Boot card verified", phase="card-verified")
                else:
                    self.progress(
                        "No enrolled boot card is accessible. Native HTTP startup uses the Server bootstrap.",
                        phase="card-not-applicable",
                    )
                self.agent.call("/v2/deployment", {"release": selected["release"]})
                self.progress(
                    "Ready to restart when you choose",
                    state="completed",
                    phase="ready-to-restart",
                    percent=100,
                )
                try:
                    shutil.rmtree(cache)
                    if candidate is not None:
                        shutil.rmtree(candidate)
                except OSError:
                    self.progress(
                        "Ready to restart; temporary download cleanup will need another attempt",
                        phase="ready-to-restart",
                    )
            except Exception as error:
                message = (
                    "A logged-in user has a blocked save or a system action failed. Check each session, close database applications, then Retry."
                    if isinstance(error, subprocess.CalledProcessError)
                    else str(error)[:1000]
                )
                self.progress(message, state="failed", phase="needs-action")
                self.agent.queue_report()
            finally:
                self.lock.release()

        threading.Thread(target=execute, daemon=True).start()
        return {"ok": True}

    def restart(self):
        if self.state.get("phase") != "ready-to-restart":
            raise ValueError("No verified update is ready to restart")
        if self.lock.locked():
            raise ValueError("Wait for the current update")
        return self.agent.power.start("reboot")
