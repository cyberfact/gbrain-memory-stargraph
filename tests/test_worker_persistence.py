import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import unquote, urlparse

from scripts.automation import worker_persistence as persistence


RUN_MARKDOWN = """---
type: run
title: Worker Persistence Acceptance
tags:
  - active
  - capture-link
  - implementing
status: implementing
active_change: false
---

# Worker Persistence Acceptance
"""


TERMINAL_MARKDOWN = """---
type: run
title: Worker Persistence Acceptance
tags:
  - capture-link
  - completed
status: completed
active_change: false
---

# Worker Persistence Acceptance
"""


class FakeCurl:
    def __init__(self, failures: int = 0):
        self.failures = failures
        self.nodes: dict[str, str] = {}
        self.calls: list[list[str]] = []

    def __call__(
        self,
        command,
        input=None,
        text=None,
        capture_output=None,
        timeout=None,
        check=None,
    ):
        del text, capture_output, timeout, check
        self.calls.append(list(command))
        if command[0] == "gbrain":
            raise AssertionError("direct gbrain fallback should not be used")
        if self.failures:
            self.failures -= 1
            return subprocess.CompletedProcess(command, 7, "", "Failed to connect to 127.0.0.1 port 8788")
        path = urlparse(command[-1]).path
        if "-X" not in command:
            slug = unquote(path.split("/api/entity-raw/", 1)[1])
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps({"ok": True, "slug": slug, "content": self.nodes[slug]}),
                "",
            )
        payload = json.loads(input or "{}")
        if path.startswith("/api/entity-save/"):
            slug = unquote(path.split("/api/entity-save/", 1)[1])
            self.nodes[slug] = str(payload.get("content") or "")
            return subprocess.CompletedProcess(command, 0, json.dumps({"ok": True, "slug": slug}), "")
        if path.startswith("/api/entity-tags/"):
            slug = unquote(path.split("/api/entity-tags/", 1)[1])
            content = self.nodes[slug]
            for tag in payload.get("remove", []):
                content = content.replace(f"  - {tag}\n", "")
            insertion = "".join(f"  - {tag}\n" for tag in payload.get("add", []))
            if insertion and "tags:\n" in content:
                content = content.replace("tags:\n", "tags:\n" + insertion, 1)
            self.nodes[slug] = content
            return subprocess.CompletedProcess(command, 0, json.dumps({"ok": True, "slug": slug}), "")
        return subprocess.CompletedProcess(command, 22, "", f"unsupported route {path}")


class WorkerPersistenceTests(unittest.TestCase):
    def test_route_prefers_configured_dashboard_route_over_loopback(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "deployment-targets.env"
            config.write_text(
                "MEMORY_STARGRAPH_LOCAL_URL='https://memory-stargraph.example.test'\n"
                "MEMORY_STARGRAPH_LOCAL_CURL_FLAGS='-k --connect-timeout 5'\n",
                encoding="utf-8",
            )

            route = persistence.resolve_worker_route(config)

        self.assertEqual(route.base_url, "https://memory-stargraph.example.test")
        self.assertEqual(route.curl_flags, ("-k", "--connect-timeout", "5"))
        self.assertNotEqual(route.base_url, persistence.DEFAULT_WORKER_API_BASE_URL)

    def test_save_retries_loopback_refusal_and_verifies_once_by_slug(self):
        fake = FakeCurl(failures=1)
        route = persistence.WorkerRoute("https://memory-stargraph.example.test", ("-k",), "test")

        with mock.patch("scripts.automation.worker_persistence.subprocess.run", side_effect=fake):
            result = persistence.save_raw("runs/test-run", RUN_MARKDOWN, route=route, retries=3)

        self.assertTrue(result["ok"])
        self.assertEqual(fake.nodes["runs/test-run"], RUN_MARKDOWN)
        save_calls = [call for call in fake.calls if "/api/entity-save/runs%2Ftest-run" in call[-1]]
        self.assertEqual(len(save_calls), 2)
        self.assertTrue(all("https://memory-stargraph.example.test" in call[-1] for call in fake.calls))

    def test_tag_mutation_releases_active_and_implementing_with_raw_readback(self):
        fake = FakeCurl()
        fake.nodes["runs/test-run"] = RUN_MARKDOWN
        route = persistence.WorkerRoute("https://memory-stargraph.example.test", (), "test")

        with mock.patch("scripts.automation.worker_persistence.subprocess.run", side_effect=fake):
            result = persistence.mutate_tags(
                "runs/test-run",
                add=["completed"],
                remove=["active", "implementing"],
                route=route,
            )

        self.assertTrue(result["ok"])
        self.assertIn("completed", result["tags"])
        self.assertNotIn("active", result["tags"])
        self.assertNotIn("implementing", result["tags"])

    def test_save_accepts_canonicalized_frontmatter_order(self):
        expected = """---
type: run
status: completed
result: completed
tags:
  - completed
  - capture-link
---

# Same Body
"""
        actual = """---
result: completed
type: run
tags:
  - capture-link
  - completed
status: completed
---

# Same Body
"""

        self.assertTrue(persistence._raw_readback_matches(expected, actual))

    def test_direct_gbrain_is_disabled_by_default_when_worker_api_fails(self):
        fake = FakeCurl(failures=3)
        route = persistence.WorkerRoute("https://memory-stargraph.example.test", (), "test")

        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch("scripts.automation.worker_persistence.subprocess.run", side_effect=fake):
                with self.assertRaises(persistence.WorkerPersistenceError):
                    persistence.save_raw("runs/test-run", TERMINAL_MARKDOWN, route=route, retries=2)


if __name__ == "__main__":
    unittest.main()
