import gc
import http.client
import io
import json
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
import weakref
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

LIBRARY = Path(__file__).resolve().parents[1] / "httpboot"
sys.path.insert(0, str(LIBRARY))
from control_transport import Server, ca, request, storage_failure
from server_v2 import Authority
from image_delivery import ImageHandler
import server_console


class DatabaseLifetimeTests(unittest.TestCase):
    def test_commits_keep_the_wal_and_readers_remain_independent(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "authority.db"
            authority = Authority(database)
            wal = Path(str(database) + "-wal")
            try:
                self.assertTrue(wal.is_file())
                inode = wal.stat().st_ino
                for value in ("first", "second"):
                    with authority.db() as db:
                        self.assertEqual(
                            db.execute("PRAGMA synchronous").fetchone()[0], 2
                        )
                        db.execute(
                            "INSERT OR REPLACE INTO settings VALUES ('fixture',?)",
                            (value,),
                        )
                    self.assertEqual(wal.stat().st_ino, inode)
                with authority.db() as writer:
                    writer.execute(
                        "UPDATE settings SET value='third' WHERE key='fixture'"
                    )
                    with authority.db(write=False) as reader:
                        self.assertEqual(
                            reader.execute(
                                "SELECT value FROM settings WHERE key='fixture'"
                            ).fetchone()[0],
                            "second",
                        )
                with self.assertRaises(ValueError):
                    with authority.db() as writer:
                        writer.execute(
                            "UPDATE settings SET value='rollback' WHERE key='fixture'"
                        )
                        raise ValueError("abort fixture transaction")
                backup = Path(temporary) / "backup.db"
                with (
                    closing(sqlite3.connect(database)) as source,
                    closing(sqlite3.connect(backup)) as destination,
                ):
                    source.backup(destination)
                    self.assertEqual(
                        destination.execute(
                            "SELECT value FROM settings WHERE key='fixture'"
                        ).fetchone()[0],
                        "third",
                    )
            finally:
                authority.close()
            authority.close()
            self.assertFalse(wal.exists())
            with closing(sqlite3.connect(database)) as reader:
                self.assertEqual(
                    reader.execute(
                        "SELECT value FROM settings WHERE key='fixture'"
                    ).fetchone()[0],
                    "third",
                )

    def test_committed_data_survives_exit_without_connection_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "authority.db"
            code = """import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from server_v2 import Authority
a=Authority(Path(sys.argv[2]))
with a.db() as db:
    assert db.execute('PRAGMA synchronous').fetchone()[0]==2
    db.execute("INSERT INTO settings VALUES ('durability','committed')")
assert Path(sys.argv[2]+'-wal').exists()
os._exit(0)
"""
            subprocess.run(
                [sys.executable, "-c", code, str(LIBRARY), str(database)],
                check=True,
                timeout=30,
            )
            with closing(sqlite3.connect(database)) as reader:
                self.assertEqual(
                    reader.execute("PRAGMA integrity_check").fetchone()[0], "ok"
                )
                self.assertEqual(
                    reader.execute(
                        "SELECT value FROM settings WHERE key='durability'"
                    ).fetchone()[0],
                    "committed",
                )

    def test_unused_authority_releases_its_idle_connection(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "authority.db"
            authority = Authority(database)
            reference = weakref.ref(authority)
            self.assertTrue(Path(str(database) + "-wal").exists())
            del authority
            gc.collect()
            self.assertIsNone(reference())
            self.assertFalse(Path(str(database) + "-wal").exists())


class DatabaseTransportTests(unittest.TestCase):
    def test_bootstrap_client_does_not_require_server_sqlite_library(self):
        code = """import importlib.abc,sys
class NoSQLite(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname in ('sqlite3','_sqlite3'):
            raise ImportError('SQLite is unavailable in this bootstrap fixture')
sys.meta_path.insert(0,NoSQLite())
sys.path.insert(0,sys.argv[1])
import boot_client_v2,control_transport,image_delivery
assert callable(control_transport.request)
assert callable(image_delivery.download)
assert 'sqlite3' not in sys.modules and '_sqlite3' not in sys.modules
"""
        subprocess.run(
            [sys.executable, "-S", "-c", code, str(LIBRARY)], check=True, timeout=10
        )

    def test_busy_codes_and_older_python_messages_are_sanitized(self):
        for code, message, expected in (
            (None, "database is locked", 503),
            (None, "database table is locked: private_table", 503),
            (None, "database schema is locked: private_schema", 503),
            (None, "disk I/O error: /private/path", 500),
            (5 | (2 << 8), "private context", 503),
            (6, "private context", 503),
            (8, "database is locked", 500),
        ):
            with self.subTest(code=code, message=message):
                error = sqlite3.OperationalError(message)
                if code is not None:
                    error.sqlite_errorcode = code
                with self.assertLogs("control_transport", level="WARNING") as logs:
                    body, status, retry = storage_failure(error)
                self.assertEqual(status, expected)
                self.assertEqual(retry, "1" if status == 503 else None)
                self.assertNotIn("private", " ".join(logs.output) + json.dumps(body))

    def test_real_lock_has_a_bounded_busy_response_without_submission_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pki = root / "pki"
            ca(pki, "127.0.0.1")
            authority = Authority(root / "authority.db")
            calls = []
            fault = [None]

            def app(method, path, peer, address, data):
                calls.append(path)
                if fault[0] is not None:
                    raise fault[0]
                try:
                    with authority.db() as db:
                        db.execute(
                            "INSERT INTO settings VALUES ('submission','applied')"
                        )
                except sqlite3.OperationalError as error:
                    fault[0] = error
                    raise
                return {"ok": True}

            server = Server(("127.0.0.1", 0), pki, app)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            blocker = sqlite3.connect(authority.database)
            blocker.execute("BEGIN IMMEDIATE")
            context = ssl.create_default_context(cafile=str(pki / "ca.pem"))
            connection = http.client.HTTPSConnection(
                "127.0.0.1", server.server_port, context=context, timeout=25
            )
            try:
                connection.request(
                    "POST",
                    "/fixture",
                    body="{}",
                    headers={"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                body = json.loads(response.read())
                self.assertEqual(response.status, 503)
                self.assertEqual(response.getheader("Retry-After"), "1")
                self.assertEqual(body["code"], "storage_busy")
                self.assertNotIn(str(root), json.dumps(body))
                connection.close()
                blocker.rollback()
                self.assertEqual(len(calls), 1)
                with self.assertRaisesRegex(ValueError, "Control HTTP 503"):
                    request(
                        "https://127.0.0.1:" + str(server.server_port),
                        "/fixture",
                        {},
                        ca_file=pki / "ca.pem",
                    )
                self.assertEqual(
                    len(calls),
                    2,
                    "A failed submission must not be automatically replayed",
                )
                with authority.db(write=False) as db:
                    self.assertIsNone(
                        db.execute(
                            "SELECT value FROM settings WHERE key='submission'"
                        ).fetchone()
                    )
                fault[0] = sqlite3.OperationalError(
                    "private database details: " + str(root)
                )
                connection = http.client.HTTPSConnection(
                    "127.0.0.1", server.server_port, context=context, timeout=5
                )
                connection.request("POST", "/fixture", body="{}")
                response = connection.getresponse()
                body = json.loads(response.read())
                self.assertEqual(response.status, 500)
                self.assertEqual(body["code"], "storage_unavailable")
                self.assertNotIn(str(root), json.dumps(body))
            finally:
                connection.close()
                blocker.close()
                server.shutdown()
                server.server_close()
                thread.join(3)
                authority.close()

    def test_server_shutdown_releases_the_authority_connection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pki = root / "pki"
            ca(pki, "127.0.0.1")
            authority = Authority(root / "authority.db")
            server = Server(("127.0.0.1", 0), pki, authority)
            self.assertTrue(Path(str(authority.database) + "-wal").exists())
            server.server_close()
            self.assertFalse(Path(str(authority.database) + "-wal").exists())

    def test_image_storage_failure_does_not_append_a_second_response(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pki = root / "pki"
            ca(pki, "127.0.0.1")
            failure = sqlite3.OperationalError("private database path: " + str(root))
            failure.sqlite_errorcode = getattr(sqlite3, "SQLITE_BUSY", 5)
            after_headers = [False]
            payload = b"qualified image fixture"

            class Transfer(io.BytesIO):
                def __exit__(self, *args):
                    self.close()
                    raise failure

            def open_image(*args):
                if not after_headers[0]:
                    raise failure
                return Transfer(payload), {"size": len(payload), "sha256": "0" * 64}

            app = SimpleNamespace(images=SimpleNamespace(open=open_image))
            server = Server(("127.0.0.1", 0), pki, app, handler=ImageHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            context = ssl.create_default_context(cafile=str(pki / "ca.pem"))
            connection = None
            try:
                for streamed in (False, True):
                    after_headers[0] = streamed
                    connection = http.client.HTTPSConnection(
                        "127.0.0.1", server.server_port, context=context, timeout=5
                    )
                    with self.assertLogs("control_transport", level="WARNING") as logs:
                        connection.request(
                            "GET", "/v2/image/fixture/filesystem.squashfs"
                        )
                        response = connection.getresponse()
                        body = response.read()
                        if streamed:
                            self.assertEqual(response.status, 200)
                            self.assertEqual(body, payload)
                            self.assertEqual(connection.sock.recv(1), b"")
                        else:
                            self.assertEqual(response.status, 503)
                            self.assertEqual(json.loads(body)["code"], "storage_busy")
                    self.assertNotIn(str(root), " ".join(logs.output))
                    connection.close()
            finally:
                if connection:
                    connection.close()
                server.shutdown()
                server.server_close()
                thread.join(3)

    def test_console_reads_while_a_writer_is_busy_and_reports_storage_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            authority = Authority(root / "authority.db")
            ready = threading.Event()
            servers = []

            def make_server(address, handler):
                server = ThreadingHTTPServer(address, handler)
                servers.append(server)
                ready.set()
                return server

            blocker = sqlite3.connect(authority.database)
            blocker.execute("BEGIN IMMEDIATE")
            connection = None
            thread = None
            try:
                with patch.object(
                    server_console, "ThreadingHTTPServer", side_effect=make_server
                ):
                    thread = threading.Thread(
                        target=server_console.serve,
                        args=(authority, root / "pki", 0),
                        daemon=True,
                    )
                    thread.start()
                    self.assertTrue(ready.wait(5))
                    connection = http.client.HTTPConnection(
                        "127.0.0.1", servers[0].server_port, timeout=3
                    )
                    connection.request("GET", "/api/state")
                    response = connection.getresponse()
                    response.read()
                    self.assertEqual(response.status, 401)
                    headers = {
                        "Authorization": "Bearer "
                        + (root / "console-token").read_text()
                    }
                    connection.request("GET", "/api/state", headers=headers)
                    response = connection.getresponse()
                    body = json.loads(response.read())
                    self.assertEqual(response.status, 200)
                    self.assertEqual(body["health"], "Server authority ready")
                    failure = sqlite3.OperationalError(
                        "private database path: " + str(root)
                    )
                    failure.sqlite_errorcode = getattr(sqlite3, "SQLITE_BUSY", 5)
                    with (
                        patch.object(authority, "approve", side_effect=failure),
                        self.assertLogs("control_transport", level="WARNING") as logs,
                    ):
                        connection.request(
                            "POST",
                            "/api/approve",
                            body=json.dumps({"code": "AAAAAA", "accounts": []}),
                            headers=headers,
                        )
                        response = connection.getresponse()
                        body = json.loads(response.read())
                        self.assertEqual(response.status, 503)
                        self.assertEqual(response.getheader("Retry-After"), "1")
                        self.assertEqual(body["code"], "storage_busy")
                    self.assertNotIn(
                        str(root), " ".join(logs.output) + json.dumps(body)
                    )
            finally:
                if connection:
                    connection.close()
                blocker.rollback()
                blocker.close()
                for server in servers:
                    server.shutdown()
                    server.server_close()
                if thread:
                    thread.join(3)
                authority.close()


if __name__ == "__main__":
    unittest.main()
