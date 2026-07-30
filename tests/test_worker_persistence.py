import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

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


class WorkerPersistenceTests(unittest.TestCase):
    def test_route_candidates_prefer_configured_dashboard_route_over_loopback(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "deployment-targets.env"
            config.write_text(
                "MEMORY_STARGRAPH_DASHBOARD_URL='https://memory-stargraph.example.test'\n"
                "MEMORY_STARGRAPH_DASHBOARD_CURL_FLAGS='--connect-timeout 5'\n"
                "MEMORY_STARGRAPH_LOCAL_URL='https://127.0.0.1:8788'\n"
                "MEMORY_STARGRAPH_LOCAL_CURL_FLAGS='-k'\n",
                encoding="utf-8",
            )

            records = persistence.route_records(config)

        self.assertEqual(records[0]["base_url"], "https://memory-stargraph.example.test")
        self.assertEqual(records[0]["curl_flags"], ["--connect-timeout", "5"])
        self.assertTrue(str(records[0]["source"]).endswith(":MEMORY_STARGRAPH_DASHBOARD_URL"))
        self.assertFalse(records[0]["loopback"])
        self.assertTrue(records[1]["loopback"])

    def test_save_payload_safely_preserves_markdown_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "run.md"
            source.write_text('---\ntitle: "Quoted"\n---\n\n# Body\n{"x": "$HOME"}\n', encoding="utf-8")

            payload = persistence.save_payload(source)

        self.assertEqual(payload["content"], '---\ntitle: "Quoted"\n---\n\n# Body\n{"x": "$HOME"}\n')
        self.assertEqual(json.loads(json.dumps(payload))["content"], payload["content"])

    def test_tag_payload_requires_a_real_mutation(self):
        with self.assertRaisesRegex(persistence.WorkerPersistenceError, "at least one"):
            persistence.tag_payload([], [])

    def test_verify_tags_detects_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw.json"
            raw.write_text(json.dumps({"content": RUN_MARKDOWN.replace("  - active\n", "")}), encoding="utf-8")

            result = persistence.verify_tags_payload(raw, add=["capture-link"], remove=["active"])

        self.assertTrue(result["ok"])
        self.assertIn("capture-link", result["tags"])
        self.assertNotIn("active", result["tags"])

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

    def test_save_accepts_long_folded_title_and_report_slug(self):
        expected = """---
type: run
title: Memory Stargraph Curator Empty Queue Enrichment Run With A Very Long Title That GBrain May Fold
report_slug: reports/memory-stargraph-capture-link-drain-2026-07-30-sg0171-empty-queue-enrichment-85
status: completed
tags:
  - completed
  - capture-link
---

# Curator Run
"""
        actual = """---
status: completed
report_slug: >-
  reports/memory-stargraph-capture-link-drain-2026-07-30-sg0171-empty-queue-enrichment-85
title: >-
  Memory Stargraph Curator Empty Queue Enrichment Run With A Very Long Title
  That GBrain May Fold
type: run
tags:
  - capture-link
  - completed
---

# Curator Run
"""

        self.assertTrue(persistence._raw_readback_matches(expected, actual))

    def test_save_accepts_timestamp_normalization(self):
        expected = """---
type: run
started_at: '2026-07-30T10:20:40-07:00'
completed_at: 2026-07-30 10:21:40-07:00
tags:
  - completed
---

# Timestamp Run
"""
        actual = """---
completed_at: '2026-07-30T10:21:40-07:00'
started_at: 2026-07-30 10:20:40-07:00
type: run
tags: [completed]
---

# Timestamp Run
"""

        self.assertTrue(persistence._raw_readback_matches(expected, actual))

    def test_save_accepts_reordered_tags(self):
        expected = """---
type: run
tags:
  - completed
  - capture-link
  - memory-stargraph
---

# Tags Run
"""
        actual = """---
type: run
tags:
  - memory-stargraph
  - completed
  - capture-link
---

# Tags Run
"""

        self.assertTrue(persistence._raw_readback_matches(expected, actual))

    def test_save_rejects_true_scalar_mismatch(self):
        expected = "---\ntype: run\nstatus: completed\n---\n\n# Scalar Run\n"
        actual = "---\ntype: run\nstatus: failed\n---\n\n# Scalar Run\n"

        self.assertFalse(persistence._raw_readback_matches(expected, actual))

    def test_save_rejects_true_body_mismatch(self):
        expected = "---\ntype: run\nstatus: completed\n---\n\n# Body Run\n\nExpected body.\n"
        actual = "---\ntype: run\nstatus: completed\n---\n\n# Body Run\n\nDifferent body.\n"

        self.assertFalse(persistence._raw_readback_matches(expected, actual))

    def test_body_policy_allows_only_one_optional_final_newline(self):
        expected = "---\ntype: run\n---\n\n# Body Run\n"
        actual = "---\ntype: run\n---\n\n# Body Run"
        extra = "---\ntype: run\n---\n\n# Body Run\n\n"

        self.assertTrue(persistence._raw_readback_matches(expected, actual))
        self.assertFalse(persistence._raw_readback_matches(expected, extra))

    def test_shell_entrypoint_uses_top_level_curl_and_preserves_payload(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = tmp_path / "deployment-targets.env"
            config.write_text(
                "MEMORY_STARGRAPH_DASHBOARD_URL='https://dashboard.example.test'\n"
                "MEMORY_STARGRAPH_LOCAL_URL='https://127.0.0.1:8788'\n",
                encoding="utf-8",
            )
            fake_bin = tmp_path / "bin"
            fake_bin.mkdir()
            log = tmp_path / "curl.log"
            store = tmp_path / "store.json"
            store.write_text("{}", encoding="utf-8")
            curl = fake_bin / "curl"
            curl.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env python3
                    import json, pathlib, sys, urllib.parse
                    log = pathlib.Path({str(log)!r})
                    store = pathlib.Path({str(store)!r})
                    log.write_text(log.read_text() + " ".join(sys.argv[1:]) + "\\n" if log.exists() else " ".join(sys.argv[1:]) + "\\n")
                    args = sys.argv[1:]
                    output = None
                    if "-o" in args:
                        output = pathlib.Path(args[args.index("-o") + 1])
                    url = next(arg for arg in args if arg.startswith("http://") or arg.startswith("https://"))
                    data = json.loads(store.read_text())
                    def write(payload):
                        text = json.dumps(payload)
                        if output:
                            output.write_text(text)
                        else:
                            print(text)
                    if url.endswith("/api/health"):
                        if "dashboard.example.test" not in url:
                            sys.exit(7)
                        write({{"ok": True}})
                    elif "/api/entity-save/" in url:
                        payload_file = args[args.index("-d") + 1][1:]
                        slug = urllib.parse.unquote(url.split("/api/entity-save/", 1)[1])
                        payload = json.loads(pathlib.Path(payload_file).read_text())
                        data[slug] = payload["content"]
                        store.write_text(json.dumps(data))
                        write({{"ok": True, "slug": slug}})
                    elif "/api/entity-raw/" in url:
                        slug = urllib.parse.unquote(url.split("/api/entity-raw/", 1)[1])
                        write({{"ok": True, "slug": slug, "content": data[slug]}})
                    elif "/api/entity-tags/" in url:
                        payload_file = args[args.index("-d") + 1][1:]
                        slug = urllib.parse.unquote(url.split("/api/entity-tags/", 1)[1])
                        payload = json.loads(pathlib.Path(payload_file).read_text())
                        content = data[slug]
                        for tag in payload.get("remove", []):
                            content = content.replace(f"  - {{tag}}\\n", "")
                        if payload.get("add") and "tags:\\n" in content:
                            content = content.replace("tags:\\n", "tags:\\n" + "".join(f"  - {{tag}}\\n" for tag in payload["add"]), 1)
                        data[slug] = content
                        store.write_text(json.dumps(data))
                        write({{"ok": True, "slug": slug}})
                    else:
                        sys.exit(22)
                    """
                ),
                encoding="utf-8",
            )
            curl.chmod(curl.stat().st_mode | stat.S_IXUSR)
            content = tmp_path / "run.md"
            content.write_text(RUN_MARKDOWN, encoding="utf-8")
            env = {
                **os.environ,
                "PATH": f"{fake_bin}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                "MEMORY_STARGRAPH_AUTOMATION_CONFIG": str(config),
                "MEMORY_STARGRAPH_WORKER_API_RETRIES": "1",
            }

            save = subprocess.run(
                ["bash", "scripts/automation/worker_persistence.sh", "save", "runs/test-run", "--file", str(content), "--json"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            tags = subprocess.run(
                [
                    "bash",
                    "scripts/automation/worker_persistence.sh",
                    "tags",
                    "runs/test-run",
                    "--remove",
                    "active",
                    "--add",
                    "completed",
                    "--json",
                ],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(save.returncode, 0, save.stderr)
            self.assertEqual(tags.returncode, 0, tags.stderr)
            self.assertTrue(json.loads(save.stdout)["ok"])
            self.assertIn("dashboard.example.test", log.read_text())
            self.assertNotIn("127.0.0.1:8788/api/health", log.read_text())


if __name__ == "__main__":
    unittest.main()
