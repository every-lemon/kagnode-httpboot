"""Console provider sessions never expose or replace the local Server credential."""

import http.client
import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "httpboot"))
import account_sync
import server_console
from test_v2_web_console import RoutedConsoleTests


class WebProviderTests(unittest.TestCase):
    def setUp(self):
        original = account_sync.ProfileLinks

        def factory(*args, **kwargs):
            self.links = original(*args, **kwargs, transport=self.transport)
            return self.links

        self.profile_patch = patch.object(
            account_sync, "ProfileLinks", side_effect=factory
        )
        self.profile_patch.start()
        self.addCleanup(self.profile_patch.stop)
        self.device = {}
        self.cookie = ""
        self.csrf = ""
        self.subject = "fixture-owner"
        RoutedConsoleTests.setUp(self)

    def tearDown(self):
        RoutedConsoleTests.tearDown(self)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=20
        )
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def transport(self, method, endpoint, data=None, token=None):
        if endpoint == "browser/start":
            self.device = data
            return {
                "request_id": "Q" * 43,
                "authorization_uri": self.links.issuer
                + "/oauth/authorize?request="
                + "Q" * 43,
                "expires_in": 600,
            }
        if endpoint == "device":
            self.device = data
            return {
                "device_code": "D" * 43,
                "user_code": "ABCDE-12345",
                "verification_uri_complete": "https://nebulacoder.com/account/apps/device?code=ABCDE12345",
            }
        if endpoint == "token":
            now = time.time()
            return {
                "scope": "profile.read email.read",
                "access_token": "A" * 43,
                "refresh_token": "R" * 43,
                "authorization": {
                    "issuer": self.links.issuer,
                    "subject": self.subject,
                    "client_id": "kagnode-httpboot",
                    "installation": self.device["installation"],
                    "purpose": "sign_in",
                    "nonce": self.device["nonce"],
                    "auth_time": now - 1,
                    "approved_at": now,
                    "issued_at": now,
                    "expires_at": now + 120,
                },
            }
        if endpoint.startswith("profile?"):
            return {
                "issuer": self.links.issuer,
                "subject": self.subject,
                "name": "Fixture console owner",
                "photo": "",
            }
        return {}

    def link(self):
        with self.links.db() as db:
            db.execute(
                "INSERT INTO links VALUES(?,?,?,?,?,0)",
                (
                    "console-owner",
                    self.subject,
                    json.dumps(
                        {
                            "issuer": self.links.issuer,
                            "subject": self.subject,
                            "name": "Owner",
                            "photo": "",
                        }
                    ),
                    "O" * 43,
                    time.time(),
                ),
            )

    def provider(self, body=None, csrf=True, origin=None):
        headers = {
            "Cookie": self.cookie,
            "Content-Type": "application/json",
            "X-CSRF-Token": self.csrf if csrf else "wrong",
        }
        if origin:
            headers["Origin"] = origin
        status, returned, raw = self.request(
            "POST" if body else "GET",
            "/api/kagnode-login",
            json.dumps(body) if body else None,
            headers,
        )
        value = json.loads(raw)
        if not body:
            self.cookie = returned["Set-Cookie"].split(";")[0]
            self.csrf = value["csrf"]
        return status, value

    def confirm(self):
        self.provider()
        status, started = self.provider({"action": "start"})
        self.assertEqual(status, 200, started)
        from urllib.parse import urlencode

        status, headers, raw = self.request(
            "GET",
            "/auth/kagnode/callback?"
            + urlencode(
                {
                    "state": self.device["state"],
                    "iss": self.links.issuer,
                    "code": "C" * 43,
                }
            ),
            headers={"Cookie": self.cookie},
        )
        self.assertEqual(status, 303, raw)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        return self.provider({"action": "status", "attempt_id": started["attempt_id"]})

    def test_provider_session_requires_existing_owner_and_never_leaks_original_credential(
        self,
    ):
        self.link()
        status, result = self.confirm()
        self.assertEqual(status, 200, result)
        self.assertEqual(result["continuation"], "console")
        session = result["console_session"]
        self.assertNotEqual(session, self.token)
        self.assertNotIn(self.token, json.dumps(result))
        self.assertNotIn("A" * 43, json.dumps(result))
        self.assertNotIn("R" * 43, json.dumps(result))
        auth = {
            "Authorization": "Bearer " + session,
            "Content-Type": "application/json",
        }
        self.assertEqual(self.request("GET", "/api/state", headers=auth)[0], 200)
        self.assertEqual(
            self.request("POST", "/api/console/logout", "{}", auth)[0], 200
        )
        self.assertEqual(self.request("GET", "/api/state", headers=auth)[0], 401)
        self.assertEqual(
            self.request(
                "GET", "/api/state", headers={"Authorization": "Bearer " + self.token}
            )[0],
            200,
        )

    def test_unlinked_identity_has_no_console_access_or_native_account_creation(self):
        status, result = self.confirm()
        self.assertEqual(status, 403, result)
        with self.authority.db(write=False) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0], 1
            )

    def test_admin_disable_revokes_provider_session_and_keeps_local_credential(self):
        self.link()
        _, result = self.confirm()
        auth = {"Authorization": "Bearer " + result["console_session"]}
        self.links.handle("console-owner", "Owner", True, "policy", {"enabled": False})
        self.assertEqual(self.request("GET", "/api/state", headers=auth)[0], 401)
        self.assertEqual(
            self.request(
                "GET", "/api/state", headers={"Authorization": "Bearer " + self.token}
            )[0],
            200,
        )
        self.assertFalse(self.provider()[1]["enabled"])

    def test_provider_csrf_and_origin_are_required(self):
        self.provider()
        self.assertEqual(self.provider({"action": "start"}, csrf=False)[0], 403)
        self.assertEqual(
            self.provider({"action": "start"}, origin="https://evil.test")[0], 403
        )

    def test_session_pool_is_bounded_expires_and_disconnect_invalidates(self):
        self.link()
        now = [1000]
        sessions = server_console.ConsoleSessions(self.links, clock=lambda: now[0])
        issued = [sessions.issue(self.subject) for _ in range(32)]
        with self.assertRaises(ValueError):
            sessions.issue(self.subject)
        self.assertTrue(sessions.valid(issued[0]))
        now[0] += 1801
        self.assertFalse(sessions.valid(issued[0]))
        fresh = sessions.issue(self.subject)
        self.links.handle("console-owner", "Owner", True, "disconnect")
        self.assertFalse(sessions.valid(fresh))

    def test_disconnected_owner_cannot_be_restored_by_an_old_continuation(self):
        from account_login import AccountSignIns
        from account_sync import AccountLinkError

        self.link()
        signins = AccountSignIns(self.links)
        browser = "B" * 43
        attempt = signins.start(browser, "https://console.example.test")["attempt_id"]
        signins.status(browser, attempt)
        self.links.handle("console-owner", "Owner", False, "disconnect")
        with self.links.db() as db:
            db.execute(
                "UPDATE sign_in_attempts SET link_stamp=? WHERE id=?",
                (self.links.stamp("console-owner"), attempt),
            )
        with self.assertRaises(AccountLinkError):
            signins.finish(browser, attempt, "console-owner")
        self.assertFalse(
            self.links.state("console-owner", "Owner", refresh=False)["connected"]
        )


if __name__ == "__main__":
    unittest.main()
