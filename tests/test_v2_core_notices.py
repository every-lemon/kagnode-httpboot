"""The local console requires its bearer and same-origin boundary for notices."""

import json
import unittest
from unittest.mock import patch
import test_v2_web_console as fixtures
import server_console

EVENT = {
    "available": True,
    "notice": {
        "id": "a" * 64,
        "version": "5.0.6",
        "title": "Interface updated",
        "items": ["Improved shared controls."],
    },
}


class CoreNotices(unittest.TestCase):
    setUp = fixtures.RoutedConsoleTests.setUp
    tearDown = fixtures.RoutedConsoleTests.tearDown
    request = fixtures.RoutedConsoleTests.request

    def test_console_notice_requires_credential_and_same_origin(self):
        url = "/api/v1/kagnode-core/whats-new"
        headers = {
            "Authorization": "Bearer " + self.token,
            "Content-Type": "application/json",
        }
        with patch.object(
            server_console.kagnode_core, "manager_request", return_value=EVENT
        ):
            self.assertEqual(self.request("GET", url)[0], 401)
            status, _, body = self.request("GET", url, headers=headers)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), EVENT)
            self.assertEqual(
                self.request(
                    "POST",
                    url + "/dismiss",
                    json.dumps({"id": "a" * 64}),
                    {**headers, "Origin": "https://other.test"},
                )[0],
                403,
            )
            self.assertEqual(
                self.request(
                    "POST", url + "/dismiss", json.dumps({"id": "b" * 64}), headers
                )[0],
                400,
            )
            self.assertEqual(
                self.request(
                    "POST", url + "/dismiss", json.dumps({"id": "a" * 64}), headers
                )[0],
                200,
            )
            self.assertEqual(
                json.loads(self.request("GET", url, headers=headers)[2]),
                {"available": True, "notice": None},
            )

    def test_console_admin_policy_uses_core_adapter_after_authentication(self):
        headers = {
            "Authorization": "Bearer " + self.token,
            "Content-Type": "application/json",
        }
        with patch.object(
            server_console.kagnode_core,
            "manager_request",
            return_value={"summaries": False},
        ) as manager:
            self.assertEqual(
                self.request(
                    "POST",
                    "/api/v1/kagnode-core/policy",
                    json.dumps({"summaries": False}),
                    headers,
                )[0],
                200,
            )
            manager.assert_called_once_with("httpboot", "policy", {"summaries": False})
            self.assertEqual(
                self.request("GET", "/api/v1/kagnode-core/policy", headers=headers)[0],
                405,
            )


if __name__ == "__main__":
    unittest.main()
