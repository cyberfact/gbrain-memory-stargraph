import unittest

from scripts.automation import retrieval_quality_benchmark as benchmark


class RetrievalQualityBenchmarkTests(unittest.TestCase):
    def test_benchmark_uses_three_fresh_sources_plus_one_stale_contradiction(self):
        receipt = benchmark.run_benchmark(started_at="2026-08-01T07:00:00-07:00")

        self.assertEqual(receipt["schema"], benchmark.SCHEMA_VERSION)
        self.assertTrue(receipt["privacy"]["synthetic_corpus"])
        self.assertFalse(receipt["privacy"]["production_user_data_mutated"])
        self.assertEqual(receipt["corpus"]["fresh_source_count"], 3)
        self.assertEqual(receipt["corpus"]["stale_contradiction_count"], 1)
        self.assertEqual(receipt["summary"]["question_count"], 10)
        self.assertTrue(all(receipt["gate"].values()))

    def test_each_question_has_fresh_session_and_expected_evidence_receipt(self):
        receipt = benchmark.run_benchmark(started_at="2026-08-01T07:00:00-07:00")

        session_ids = [case["session_id"] for case in receipt["cases"]]
        self.assertEqual(len(session_ids), len(set(session_ids)))
        for case in receipt["cases"]:
            self.assertTrue(case["fresh_session"])
            self.assertIn("expected_slugs", case["expected_source_coverage"])
            self.assertIn("used_slugs", case["expected_source_coverage"])
            self.assertIn("freshness_provenance", case)
            self.assertTrue(case["answer_success"])
            self.assertTrue(case["recall_success"])
            self.assertFalse(case["fallback"]["used"])
            self.assertFalse(case["fallback"]["degraded"])

    def test_stale_contradiction_is_pruned_to_current_source(self):
        receipt = benchmark.run_benchmark(started_at="2026-08-01T07:00:00-07:00")
        case = next(row for row in receipt["cases"] if row["id"] == "alpha-route-current")

        self.assertIn("8788", case["answer"])
        self.assertNotIn("7000", case["answer"])
        self.assertEqual(
            case["contradiction_pruning"]["pruned_slugs"],
            ["synthetic/retrieval-quality/source-alpha-stale"],
        )
        self.assertTrue(case["contradiction_pruning"]["success"])

    def test_out_of_scope_question_abstains_without_approval_or_mutation(self):
        receipt = benchmark.run_benchmark(started_at="2026-08-01T07:00:00-07:00")
        case = next(row for row in receipt["cases"] if row["id"] == "out-of-scope-abstention")

        self.assertEqual(case["resolver"]["choice"], "abstain_no_mutation")
        self.assertFalse(case["resolver"]["auto_approved"])
        self.assertFalse(case["resolver"]["mutated_production"])
        self.assertEqual(case["expected_source_coverage"]["expected"], 0)
        self.assertEqual(case["expected_source_coverage"]["used_slugs"], [])

    def test_gate_fails_on_true_answer_mismatch(self):
        question = dict(benchmark.QUESTIONS[0])
        question["expected_answer_terms"] = ["not in corpus"]

        case = benchmark.run_question(question, benchmark.SYNTHETIC_CORPUS, 1)

        self.assertFalse(case["answer_success"])


if __name__ == "__main__":
    unittest.main()
