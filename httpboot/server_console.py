"""Private, routed KagNode HTTP Boot console backed by the existing authority."""

import kagnode_core
import hmac
import hashlib
import time
import json
import os
import stat
import re
import secrets
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer as BaseHTTPServer
from urllib.parse import urlsplit, parse_qs, urlencode
from common import atomic
from control_transport import issue, storage_failure
from server_web_assets import HTML, ASSETS, UI_VERSION

PAGES = {"/", "/overview", "/clients", "/accounts", "/images", "/reports", "/access"}
CSP = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"


class ThreadingHTTPServer(BaseHTTPServer):
    """Bound connection count and header-read lifetime for the local listener."""

    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self.permits = threading.BoundedSemaphore(16)
        super().__init__(*args, **kwargs)

    def process_request(self, request, address):
        if not self.permits.acquire(blocking=False):
            try:
                request.sendall(
                    b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.permits.release()
            raise

    def process_request_thread(self, *args):
        try:
            super().process_request_thread(*args)
        finally:
            self.permits.release()


def read_state(authority):
    from boot_reports import sanitize, health
    from approval_wizard import approval_defaults
    from product_version import VERSION

    with authority.db(write=False) as db:
        clients = [
            dict(row)
            for row in db.execute(
                "SELECT id,hardware,code,approved,expires FROM devices"
            )
        ]
        accounts = [
            dict(row)
            for row in db.execute("SELECT name,system_admin FROM accounts ORDER BY uid")
        ]
        for client in clients:
            client["accounts"] = [
                r[0]
                for r in db.execute(
                    "SELECT name FROM assignments WHERE device=? ORDER BY name",
                    (client["id"],),
                )
            ]
        images = []
        if db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='images'"
        ).fetchone():
            for row in db.execute(
                "SELECT id,manifest,active FROM images ORDER BY created DESC LIMIT 20"
            ):
                manifest = json.loads(row["manifest"])
                images.append(
                    {
                        "release": row["id"],
                        "active": bool(row["active"]),
                        "kernel": manifest.get("kernel", "Unknown"),
                        "architecture": manifest.get("architecture", "Unknown"),
                        "size": sum(
                            a.get("size", 0)
                            for a in manifest.get("artifacts", {}).values()
                        ),
                    }
                )
    reports = []
    paths = (authority.database.parent / "reports").glob("*/*.json")
    for path in sorted(paths, key=lambda item: item.stat().st_mtime, reverse=True)[:30]:
        try:
            if path.is_symlink() or path.stat().st_size > 256 * 1024:
                continue
            reports.append(sanitize(json.loads(path.read_text())))
        except (ValueError, OSError):
            continue
    return {
        "health": "Server authority ready",
        "clients": clients,
        "accounts": accounts,
        "images": images,
        "reports": reports,
        "boothealth": health(authority),
        "defaults": approval_defaults(authority),
        "console_version": UI_VERSION,
        "authority_version": VERSION,
    }


class ConsoleConflict(ValueError):
    pass


def update_assignments(authority, data):
    if not isinstance(data, dict) or set(data) != {"device", "accounts"}:
        raise ValueError("Invalid account assignment")
    peer, names = data["device"], data["accounts"]
    if (
        not isinstance(peer, str)
        or not isinstance(names, list)
        or len(names) > 64
        or any(not isinstance(n, str) or not 0 < len(n) <= 128 for n in names)
        or len(set(names)) != len(names)
    ):
        raise ValueError("Invalid Client or accounts")
    with authority.db() as db:
        authority.device(db, peer)
        known = {row[0] for row in db.execute("SELECT name FROM accounts")}
        if not set(names) <= known:
            raise ValueError("Unknown Client account")
        current = {
            row[0]
            for row in db.execute(
                "SELECT name FROM assignments WHERE device=?", (peer,)
            )
        }
        for name in current - set(names):
            if db.execute(
                "SELECT 1 FROM sessions WHERE name=? AND device=?", (name, peer)
            ).fetchone():
                raise ConsoleConflict(
                    "Save work and sign out of the active Client account before removing its assignment."
                )
        for name in current - set(names):
            db.execute(
                "DELETE FROM assignments WHERE name=? AND device=?", (name, peer)
            )
        for name in set(names) - current:
            db.execute(
                "INSERT INTO assignments(name,device) VALUES (?,?)", (name, peer)
            )
    print(
        "HTTP Boot console: account assignments changed for approved Client; count="
        + str(len(names)),
        file=sys.stderr,
        flush=True,
    )
    return {"ok": True}


def existing_authority(database):
    """Attach console operations without running schema or image initialization."""
    from server_v2 import Authority
    from pathlib import Path
    import time

    class ConsoleAuthority(Authority):
        def __init__(self, path):
            self.database = Path(path).resolve(strict=True)
            if not self.database.is_file():
                raise ValueError("An existing Server authority is required")
            self.clock = time.time
            # Never create or migrate a database when starting this web service.
            with sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True) as db:
                db.execute("SELECT name,uid,system_admin FROM accounts LIMIT 0")
                db.execute("SELECT id,code,approved FROM devices LIMIT 0")
                db.execute("SELECT name,device FROM assignments LIMIT 0")

        def close(self):
            pass

    return ConsoleAuthority(database)


def console_credential(path, persist=False):
    """The routed console keeps its private credential across UI-only restarts."""
    if path.is_symlink():
        raise ValueError("Console credential cannot be a symlink")
    if persist and path.exists():
        details = path.stat()
        if (
            not stat.S_ISREG(details.st_mode)
            or stat.S_IMODE(details.st_mode) & 0o077
            or details.st_uid != os.geteuid()
        ):
            raise ValueError(
                "Console credential must be a private file owned by the service account"
            )
        token = path.read_text().strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise ValueError("Invalid stored console credential; rotate it explicitly")
        return token
    token = secrets.token_urlsafe(32)
    atomic(path, token)
    return token


class ConsoleSessions:
    """Short-lived web credentials; native console credentials are never returned."""

    def __init__(self, profiles, clock=time.monotonic):
        self.profiles, self.clock = profiles, clock
        self.entries = {}
        self.lock = threading.RLock()

    def issue(self, subject):
        with self.lock:
            now = self.clock()
            self.entries = {
                key: value
                for key, value in self.entries.items()
                if value["expires"] > now
            }
            if len(self.entries) >= 32:
                raise ValueError(
                    "Too many active console sessions. Lock an existing session or wait for it to expire."
                )
            value = secrets.token_urlsafe(32)
            self.entries[hashlib.sha256(value.encode()).hexdigest()] = {
                "subject": subject,
                "stamp": self.profiles.stamp("console-owner"),
                "expires": now + 1800,
            }
            return value

    def valid(self, credential):
        key = hashlib.sha256(credential.encode()).hexdigest()
        with self.lock:
            entry = self.entries.get(key)
            if not entry:
                return False
            with self.profiles.db() as db:
                linked = db.execute(
                    "SELECT subject FROM links WHERE local_id='console-owner'"
                ).fetchone()
            if (
                entry["expires"] <= self.clock()
                or not self.profiles.enabled()[0]
                or self.profiles.stamp("console-owner") != entry["stamp"]
                or not linked
                or linked[0] != entry["subject"]
            ):
                self.entries.pop(key, None)
                return False
            return True

    def revoke(self, credential):
        with self.lock:
            self.entries.pop(hashlib.sha256(credential.encode()).hexdigest(), None)


def serve(authority, pki, port=8081, credential_name="console-token"):
    if credential_name not in ("console-token", "web-console-token"):
        raise ValueError("Invalid console credential name")
    token = console_credential(
        authority.database.parent / credential_name,
        persist=credential_name == "web-console-token",
    )

    from account_sync import ProfileLinks, AccountLinkError

    profile_links = (
        ProfileLinks(authority.database.parent / "account-sync", "kagnode-httpboot")
        if credential_name == "web-console-token"
        else None
    )

    from account_login import AccountSignIns

    signins = AccountSignIns(profile_links) if profile_links else None
    web_sessions = ConsoleSessions(profile_links) if profile_links else None

    class Handler(BaseHTTPRequestHandler):
        server_version = "KagNodeHTTPBoot"
        sys_version = ""

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *args):
            pass

        def do_GET(self):
            self.respond()

        def do_HEAD(self):
            self.respond()

        def do_POST(self):
            self.respond()

        def send(
            self,
            status,
            raw,
            mime="application/json",
            immutable=False,
            retry_after=None,
            extra_headers=(),
        ):
            self.send_response(status)
            for key, value in [
                ("Content-Type", mime),
                ("Content-Length", str(len(raw))),
                (
                    "Cache-Control",
                    "public, max-age=31536000, immutable" if immutable else "no-store",
                ),
                (
                    "Content-Security-Policy",
                    CSP.replace(
                        "connect-src 'self'",
                        "connect-src 'self' https://nebulacoder.com",
                    ),
                ),
                ("Cross-Origin-Opener-Policy", "same-origin-allow-popups"),
                ("X-Content-Type-Options", "nosniff"),
                ("X-Frame-Options", "DENY"),
                ("Referrer-Policy", "no-referrer"),
                ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
            ]:
                self.send_header(key, value)
            for key, value in extra_headers:
                self.send_header(key, value)
            if retry_after:
                self.send_header("Retry-After", str(retry_after))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(raw)

        def respond(self):
            try:
                host = self.headers.get("Host", "")
                parsed = urlsplit("http://" + host)
                if (
                    parsed.hostname not in ("127.0.0.1", "localhost", "::1")
                    or parsed.username
                    or parsed.password
                    or parsed.path
                    or parsed.query
                    or parsed.fragment
                ):
                    self.send(400, b'{"error":"Unrecognized console host."}')
                    return
                if parsed.port is not None and not 1 <= parsed.port <= 65535:
                    self.send(400, b'{"error":"Unrecognized console host."}')
                    return
                path = urlsplit(self.path).path
                if self.command in ("GET", "HEAD") and path in PAGES:
                    self.send(
                        200,
                        kagnode_core.inject(HTML, "httpboot").encode(),
                        "text/html; charset=utf-8",
                    )
                    return
                if self.command in ("GET", "HEAD") and path.startswith(
                    "/kagnode-core/"
                ):
                    selected = kagnode_core.asset(path)
                    if not selected:
                        self.send(404, b"Core asset unavailable", "text/plain")
                    else:
                        raw, mime = selected
                        self.send(200, raw, mime, True)
                    return
                if self.command in ("GET", "HEAD") and path in ASSETS:
                    mime, body = ASSETS[path]
                    self.send(200, body, mime, True)
                    return
                if self.command in ("GET", "HEAD") and path == "/healthz":
                    self.send(
                        200,
                        json.dumps(
                            {
                                "ok": True,
                                "service": "kagnode-httpboot-web",
                                "version": UI_VERSION,
                            }
                        ).encode(),
                    )
                    return
                if self.command == "GET" and path == "/auth/kagnode/callback":
                    target = {"kagnode_error": "invalid"}
                    try:
                        query = parse_qs(
                            urlsplit(self.path).query,
                            keep_blank_values=True,
                            max_num_fields=8,
                        )
                        if (
                            len(self.path) > 4096
                            or not signins
                            or any(len(values) != 1 for values in query.values())
                        ):
                            raise ValueError("Invalid callback.")
                        browser = next(
                            (
                                part.strip().split("=", 1)[1]
                                for part in self.headers.get("Cookie", "").split(";")
                                if part.strip().startswith("kagnode_httpboot_login=")
                            ),
                            "",
                        )
                        attempt = signins.callback(
                            browser,
                            query.get("state", [""])[0],
                            query.get("iss", [""])[0],
                            query.get("code", [""])[0],
                            query.get("error", [""])[0],
                        )
                        target = {"kagnode_attempt": attempt}
                    except (ValueError, AccountLinkError):
                        pass
                    self.send(
                        303, b"", extra_headers=[("Location", "/?" + urlencode(target))]
                    )
                    return
                if not path.startswith("/api/"):
                    self.send(404, b'{"error":"Console page not found."}')
                    return
                if path == "/api/kagnode-login":
                    browser = next(
                        (
                            part.strip().split("=", 1)[1]
                            for part in self.headers.get("Cookie", "").split(";")
                            if part.strip().startswith("kagnode_httpboot_login=")
                        ),
                        "",
                    )
                    if self.command == "GET":
                        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", browser):
                            browser = secrets.token_urlsafe(32)
                        csrf = signins.csrf(browser) if signins else ""
                        self.send(
                            200,
                            json.dumps(
                                {
                                    "issuer": profile_links.issuer
                                    if profile_links
                                    else "https://nebulacoder.com",
                                    "enabled": bool(signins and signins.enabled()),
                                    "csrf": csrf,
                                }
                            ).encode(),
                            extra_headers=[
                                (
                                    "Set-Cookie",
                                    "kagnode_httpboot_login="
                                    + browser
                                    + "; Path=/; HttpOnly; SameSite=Lax; Max-Age=600",
                                )
                            ],
                        )
                        return
                    expected_csrf = signins.csrf(browser) if signins else ""
                    if (
                        self.command != "POST"
                        or not signins
                        or not browser
                        or not hmac.compare_digest(
                            expected_csrf, self.headers.get("X-CSRF-Token", "")
                        )
                        or self.headers.get("Sec-Fetch-Site")
                        in ("cross-site", "same-site")
                        or self.headers.get("Origin") not in (None, "http://" + host)
                    ):
                        self.send(
                            403,
                            b'{"error":"Reload the local console and use a same-origin request."}',
                        )
                        return
                    lengths = self.headers.get_all("Content-Length", [])
                    if (
                        len(lengths) != 1
                        or self.headers.get("Transfer-Encoding")
                        or self.headers.get_content_type() != "application/json"
                        or not 0 < int(lengths[0]) <= 4096
                    ):
                        raise ValueError("A bounded JSON sign-in request is required.")
                    data = json.loads(self.rfile.read(int(lengths[0])))
                    if not isinstance(data, dict):
                        raise ValueError("Invalid sign-in request.")
                    action, attempt = (
                        data.get("action"),
                        str(data.get("attempt_id", "")),
                    )
                    try:
                        if action == "start":
                            signins.rate(self.client_address[0])
                            result = signins.start_browser(browser, "http://" + host)
                        elif action == "cancel":
                            result = signins.cancel(browser, attempt)
                        elif action == "status":
                            result = signins.status(browser, attempt)
                            if result.get("authorized"):
                                identity = signins.verified(browser, attempt)
                                if identity["local_id"] != "console-owner":
                                    signins.cancel(browser, attempt)
                                    raise AccountLinkError(
                                        "Connect the existing console owner from Console access first. Public administrator signup is unavailable.",
                                        403,
                                    )
                                profile = signins.finish(
                                    browser, attempt, "console-owner"
                                )
                                result = {
                                    "authorized": True,
                                    "continuation": "console",
                                    "console_session": web_sessions.issue(
                                        profile["subject"]
                                    ),
                                    "expires_in": 1800,
                                }
                        else:
                            raise ValueError("Invalid sign-in action.")
                        self.send(200, json.dumps(result).encode())
                    except AccountLinkError as error:
                        self.send(
                            error.status, json.dumps({"error": str(error)}).encode()
                        )
                    return
                received = self.headers.get("Authorization", "").encode()
                bearer = self.headers.get("Authorization", "").removeprefix("Bearer ")
                if not hmac.compare_digest(
                    received, ("Bearer " + token).encode()
                ) and not (
                    web_sessions
                    and self.headers.get("Authorization", "").startswith("Bearer ")
                    and web_sessions.valid(bearer)
                ):
                    self.send(401, b'{"error":"Local console credential required."}')
                    return
                origin = self.headers.get("Origin")
                if (
                    self.headers.get("Sec-Fetch-Site") == "cross-site"
                    or origin
                    and origin != "http://" + host
                ):
                    self.send(
                        403, b'{"error":"Same-origin console requests are required."}'
                    )
                    return
                if path == "/api/console/logout" and self.command == "POST":
                    if web_sessions:
                        web_sessions.revoke(bearer)
                    self.send(200, b'{"ok":true}')
                    return
                if (
                    path == "/api/kagnode-account"
                    or path.startswith("/api/v1/kagnode-core/")
                ) and profile_links is not None:
                    data = {}
                    if self.command == "POST":
                        lengths = self.headers.get_all("Content-Length", [])
                        if (
                            len(lengths) != 1
                            or self.headers.get("Transfer-Encoding")
                            or self.headers.get_content_type() != "application/json"
                        ):
                            raise ValueError(
                                "A bounded JSON account-link request is required."
                            )
                        size = int(lengths[0])
                        if not 0 < size <= 4096:
                            raise ValueError(
                                "Account-link request exceeds its size limit."
                            )
                        data = json.loads(self.rfile.read(size))
                        if not isinstance(data, dict):
                            raise ValueError("Invalid account-link request.")
                    elif self.command not in ("GET", "HEAD"):
                        self.send(405, b'{"error":"Method not allowed."}')
                        return
                    try:
                        if path in (
                            "/api/v1/kagnode-core/whats-new",
                            "/api/v1/kagnode-core/whats-new/dismiss",
                        ):
                            dismissal = path.endswith("/dismiss")
                            if self.command != ("POST" if dismissal else "GET"):
                                self.send(405, b'{"error":"Method not allowed."}')
                                return
                            try:
                                result = (
                                    kagnode_core.dismiss_notice(
                                        "httpboot",
                                        "console-owner",
                                        data.get("id"),
                                        profile_links.notice_dismiss,
                                    )
                                    if dismissal
                                    else kagnode_core.read_notice(
                                        "httpboot",
                                        "console-owner",
                                        profile_links.notice_is_dismissed,
                                    )
                                )
                            except ValueError:
                                self.send(
                                    400,
                                    b'{"error":"This update summary is no longer available."}',
                                )
                                return
                            self.send(200, json.dumps(result).encode())
                            return
                        if path.startswith("/api/v1/kagnode-core/"):
                            action = path.removeprefix("/api/v1/kagnode-core/")
                            if self.command != (
                                "GET" if action == "status" else "POST"
                            ):
                                self.send(405, b'{"error":"Method not allowed."}')
                                return
                            result = kagnode_core.manager_request(
                                "httpboot", action, data
                            )
                        else:
                            result = profile_links.handle(
                                "console-owner",
                                "Server administrator",
                                True,
                                str(data.get("action", "state")),
                                data,
                                "http://" + host,
                            )
                        self.send(200, json.dumps(result).encode())
                    except AccountLinkError as error:
                        self.send(
                            error.status, json.dumps({"error": str(error)}).encode()
                        )
                    return
                if self.command in ("GET", "HEAD") and path == "/api/state":
                    result = read_state(authority)
                elif self.command == "POST" and path == "/api/assignments":
                    lengths = self.headers.get_all("Content-Length", [])
                    if (
                        len(lengths) != 1
                        or self.headers.get("Transfer-Encoding")
                        or self.headers.get_content_type() != "application/json"
                    ):
                        raise ValueError(
                            "A bounded JSON assignment request is required"
                        )
                    size = int(lengths[0])
                    if not 0 < size <= 8192:
                        raise ValueError("Assignment request exceeds size limit")
                    result = update_assignments(
                        authority, json.loads(self.rfile.read(size))
                    )
                elif self.command == "POST" and path == "/api/approve":
                    lengths = self.headers.get_all("Content-Length", [])
                    if len(lengths) != 1 or self.headers.get("Transfer-Encoding"):
                        raise ValueError("A bounded JSON approval request is required.")
                    size = int(lengths[0])
                    if not 0 < size <= 4096 or self.headers.get_content_type() not in (
                        "text/plain",
                        "application/json",
                    ):
                        raise ValueError("Invalid approval request.")
                    data = json.loads(self.rfile.read(size))
                    if (
                        not isinstance(data, dict)
                        or set(data) != set(("code", "accounts"))
                        or not isinstance(data["code"], str)
                        or not re.fullmatch(r"[A-Za-z0-9]{6}", data["code"])
                    ):
                        raise ValueError("Enter the six-character Client pairing code.")
                    if (
                        not isinstance(data["accounts"], list)
                        or len(data["accounts"]) > 64
                        or not all(
                            isinstance(name, str) and 0 < len(name) <= 128
                            for name in data["accounts"]
                        )
                    ):
                        raise ValueError("Choose existing Client accounts.")
                    result = {
                        "device": authority.approve(
                            data["code"],
                            lambda csr, name: issue(pki, csr, name),
                            data["accounts"],
                        )
                    }
                else:
                    self.send(404, b'{"error":"Unknown console operation."}')
                    return
                raw = json.dumps(result).encode()
                if len(raw) > 2 * 1024 * 1024:
                    raise ValueError("Console response exceeds the safe size limit.")
                self.send(200, raw)
            except sqlite3.OperationalError as error:
                body, status, retry = storage_failure(error)
                self.close_connection = True
                self.send(status, json.dumps(body).encode(), retry_after=retry)
            except ConsoleConflict as error:
                self.send(409, json.dumps({"error": str(error)}).encode())
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                self.send(
                    400,
                    b'{"error":"Check the pairing code, selected accounts, and request format."}',
                )
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self.send(
                    500,
                    b'{"error":"The Server could not complete this console request."}',
                )

    if sys.stdout.isatty():
        print(f"Open http://127.0.0.1:{port}/#{token}", flush=True)
    else:
        print(
            f"HTTP Boot local console listening at http://127.0.0.1:{port}/; credential stored in the protected Server state",
            flush=True,
        )
    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        server.serve_forever()
