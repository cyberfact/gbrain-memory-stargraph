import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.automation import recurring_worker_bridge as bridge


class RecurringWorkerBridgeTests(unittest.TestCase):
    def make_request(self, **overrides):
        payload = bridge.make_request(
            overrides.pop("role", "daily_learning_intake"),
            overrides.pop("operation", "evidence"),
            overrides.pop("invocation_id", "learning-bridge-test-0001"),
            overrides.pop("expected_commit", "abc123"),
            nonce=overrides.pop("nonce", "nonce-bridge-0001"),
            synthetic=overrides.pop("synthetic", True),
            bundle_file=overrides.pop("bundle_file", None),
        )
        payload.update(overrides)
        return payload

    def test_role_and_operation_allowlists_reject_cross_role_work(self):
        with self.assertRaisesRegex(bridge.BridgeError, "unsupported role"):
            bridge.make_request("product_owner", "evidence", "bad-role-0001", "abc123")
        with self.assertRaisesRegex(bridge.BridgeError, "unsupported operation"):
            bridge.make_request("daily_learning_intake", "remediate", "bad-op-0001", "abc123")
        with self.assertRaisesRegex(bridge.BridgeError, "unsafe identifier"):
            bridge.make_request("daily_learning_intake", "evidence", "bad-Upper-0001", "abc123")

    def test_submit_is_offline_idempotent_and_replay_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = self.make_request()
            first = bridge.submit_request(root, request)
            second = bridge.submit_request(root, dict(request))
            self.assertEqual(first["status"], "submitted")
            self.assertEqual(second["status"], "already_submitted")
            changed = dict(request)
            changed["expected_commit"] = "def456"
            with self.assertRaisesRegex(bridge.BridgeError, "replay"):
                bridge.submit_request(root, changed)

    def test_learning_evidence_bundle_has_required_slots_and_phase_heartbeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            values = bridge.validate_request(self.make_request())
            with (
                mock.patch.object(bridge, "local_health", return_value={"ok": True, "ui_version": "V1.0.174"}),
                mock.patch.object(bridge, "gbrain_get", return_value=(True, "body")),
                mock.patch.dict(os.environ, {"MEMORY_STARGRAPH_RECURRING_BRIDGE_ENABLED": "1"}),
            ):
                evidence = bridge.gather_learning_evidence(root, values)
            self.assertEqual(evidence["evidence_schema"], "memory-stargraph-learning-evidence-v1")
            self.assertEqual(evidence["evaluator"]["question_count"], 10)
            self.assertEqual(evidence["retrieval_quality_benchmark"]["summary"]["question_count"], 10)
            self.assertTrue(all(evidence["retrieval_quality_benchmark"]["gate"].values()))
            self.assertFalse(evidence["resolver_metrics"]["approval_required"])
            state = bridge.read_state(root)
            self.assertIn("heartbeat_at", state)
            self.assertEqual(state["active_role"], "daily_learning_intake")

    def test_sre_evidence_is_read_only_and_has_incident_classification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            values = bridge.validate_request(self.make_request(role="sre_daily_reliability"))
            with mock.patch.object(bridge, "local_health", return_value={"ok": True, "ui_version": "V1.0.174"}):
                evidence = bridge.gather_sre_evidence(root, values)
            self.assertEqual(evidence["evidence_schema"], "memory-stargraph-sre-evidence-v1")
            self.assertFalse(evidence["incident_classification"]["incident"])
            self.assertFalse(evidence["incident_classification"]["remediation_attempted"])
            self.assertEqual(evidence["metrics"]["resolver"]["events_created"], 0)
            baseline = evidence["metrics"]["retrieval_quality_baseline"]
            self.assertEqual(baseline["summary"]["question_count"], 10)
            self.assertTrue(all(baseline["gate"].values()))

    def test_decision_bundle_validates_slug_prefixes_and_todo_duplicate_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bridge.ensure_dirs(root)
            bundle_path = root / "bundles" / "decision.json"
            bundle = {
                "role": "daily_learning_intake",
                "operation": "persist",
                "invocation_id": "learning-bridge-test-0001",
                "decision_type": "todo_planned",
                "artifacts": [
                    {
                        "kind": "todo",
                        "slug": "notes/memory-starmap-todo-list/bridge-test-todo",
                        "duplicate_policy": {"dedupe_key": "bridge-test", "checked_existing": True},
                        "markdown": "---\ntype: task\nstatus: planned\n---\n# Bridge Test\n",
                    }
                ],
            }
            bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
            values = bridge.validate_request(self.make_request(operation="persist", bundle_file=str(bundle_path)))
            with mock.patch.object(bridge, "gbrain_put") as put:
                result = bridge.persist_decision(root, values)
            self.assertEqual(result["artifact_count"], 1)
            put.assert_called_once()

    def test_gbrain_put_falls_back_to_stargraph_save_and_raw_readback(self):
        calls = []

        def fake_run_cmd(args, **kwargs):
            calls.append(args)
            if args[:3] == ["gbrain", "put", "runs/memory-stargraph-learning-test"]:
                return bridge.subprocess.CompletedProcess(args, 1, "", "cli failed")
            if "/api/entity-save/runs%2Fmemory-stargraph-learning-test" in args[-1]:
                return bridge.subprocess.CompletedProcess(args, 0, json.dumps({"ok": True}), "")
            if "/api/entity-raw/runs%2Fmemory-stargraph-learning-test" in args[-1]:
                return bridge.subprocess.CompletedProcess(args, 0, json.dumps({"content": "---\nstatus: completed\n---\nBody"}), "")
            return bridge.subprocess.CompletedProcess(args, 1, "", "unexpected")

        with mock.patch.object(bridge, "run_cmd", side_effect=fake_run_cmd):
            bridge.gbrain_put("runs/memory-stargraph-learning-test", "---\nstatus: completed\n---\nBody")

        self.assertTrue(any("/api/entity-save/runs%2Fmemory-stargraph-learning-test" in call[-1] for call in calls))
        self.assertTrue(any("/api/entity-raw/runs%2Fmemory-stargraph-learning-test" in call[-1] for call in calls))

    def test_markdown_readback_allows_normalized_frontmatter_but_rejects_body_change(self):
        expected = "---\ntype: run\nstatus: completed\ntags:\n- synthetic\n- sg0179\n---\n# Title\n\nBody\n"
        normalized = "---\ntype: run\ntitle: Title\nstatus: completed\ntags:\n  - sg0179\n  - synthetic\n---\n# Title\n\nBody\n"
        changed = "---\ntype: run\nstatus: completed\ntags:\n  - synthetic\n---\n# Title\n\nChanged\n"
        self.assertTrue(bridge.markdown_readback_matches(expected, normalized))
        self.assertFalse(bridge.markdown_readback_matches(expected, changed))

    def test_decision_bundle_rejects_unsafe_slug_and_missing_duplicate_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bridge.ensure_dirs(root)
            bundle_path = root / "bundles" / "decision.json"
            bundle = {
                "role": "daily_learning_intake",
                "operation": "persist",
                "invocation_id": "learning-bridge-test-0001",
                "decision_type": "todo_planned",
                "artifacts": [{"kind": "todo", "slug": "secrets/outside", "markdown": "---\nstatus: planned\n---\n# Bad\n"}],
            }
            bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
            values = bridge.validate_request(self.make_request(operation="persist", bundle_file=str(bundle_path)))
            with self.assertRaisesRegex(bridge.BridgePhaseError, "slug outside role allowlist"):
                bridge.persist_decision(root, values)

    def test_decision_bundle_rejects_uppercase_artifact_slugs_before_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bridge.ensure_dirs(root)
            bundle_path = root / "bundles" / "decision.json"
            bundle = {
                "role": "daily_learning_intake",
                "operation": "persist",
                "invocation_id": "learning-bridge-test-0001",
                "decision_type": "no_action",
                "artifacts": [{
                    "kind": "run",
                    "slug": "runs/memory-stargraph-learning-Bad",
                    "markdown": "---\nstatus: completed\n---\n# Bad\n",
                }],
            }
            bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
            values = bridge.validate_request(self.make_request(operation="persist", bundle_file=str(bundle_path)))
            with self.assertRaisesRegex(bridge.BridgePhaseError, "lowercase"):
                bridge.persist_decision(root, values)

    def test_process_one_evidence_terminalizes_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bridge.submit_request(root, self.make_request(expected_commit="abc123"))
            with (
                mock.patch.object(bridge, "current_commit", return_value="abc123"),
                mock.patch.object(bridge, "gather_learning_evidence", return_value={"evidence_schema": "memory-stargraph-learning-evidence-v1"}),
                mock.patch.dict(os.environ, {"MEMORY_STARGRAPH_RECURRING_BRIDGE_ENABLED": "1"}),
            ):
                processed = bridge.process_one(root)
            self.assertEqual(processed["status"], "processed")
            result = bridge.read_status(root, "learning-bridge-test-0001", "evidence")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["result"], "evidence_bundle_completed")
            self.assertFalse(bridge.lock_path(root).exists())

    def test_crash_recovery_terminalizes_stale_processing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bridge.ensure_dirs(root)
            request = self.make_request()
            processing = bridge.processing_path(root, request["nonce"])
            processing.write_text(json.dumps(request), encoding="utf-8")
            old = bridge.time.time() - bridge.PROCESSING_TIMEOUT_SECONDS - 5
            os.utime(processing, (old, old))
            recovered = bridge.recover_stale_processing(root)
            self.assertEqual(recovered, ["learning-bridge-test-0001"])
            result = bridge.read_status(root, "learning-bridge-test-0001", "evidence")
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["result"], "processing_timeout_recovered")

    def test_bridge_disabled_by_default_and_health_reports_102_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(bridge.BridgeError, "disabled"):
                bridge.run_loop(root, max_iterations=1)
            health = bridge.health(root)
            self.assertFalse(health["current_process_runner_enabled"])
            self.assertIn("daily_learning_intake", health["allowed_roles"])
            self.assertTrue((health["daemon_state"] or {}).get("configured_remote_runner_disabled", True))


if __name__ == "__main__":
    unittest.main()
