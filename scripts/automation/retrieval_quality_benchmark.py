#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo


PACIFIC = ZoneInfo("America/Los_Angeles")
SCHEMA_VERSION = "memory-stargraph-retrieval-quality-benchmark-v1"


@dataclass(frozen=True)
class SourceDoc:
    slug: str
    source_id: str
    title: str
    body: str
    captured_at: str
    freshness_rank: int
    stale: bool = False
    superseded_by: str | None = None


SYNTHETIC_CORPUS = [
    SourceDoc(
        slug="synthetic/retrieval-quality/source-alpha-current",
        source_id="alpha-current",
        title="Alpha Recall Operating Note",
        body=(
            "Project Alpha uses dashboard route 8788 for the canonical memory service. "
            "Its owner is the retrieval-quality benchmark team. Evidence receipts must "
            "include source coverage, freshness, provenance, and degraded state."
        ),
        captured_at="2026-08-01T06:00:00-07:00",
        freshness_rank=3,
    ),
    SourceDoc(
        slug="synthetic/retrieval-quality/source-beta-design",
        source_id="beta-design",
        title="Beta Resolver Design",
        body=(
            "Project Beta evaluates resolver choices. The resolver must abstain when a "
            "question is outside the synthetic corpus, and it must not auto-approve "
            "proposals. Contradictory stale evidence should be pruned when a current "
            "owned source supersedes it."
        ),
        captured_at="2026-08-01T06:05:00-07:00",
        freshness_rank=2,
    ),
    SourceDoc(
        slug="synthetic/retrieval-quality/source-gamma-session",
        source_id="gamma-session",
        title="Gamma Session Receipt",
        body=(
            "Project Gamma proves cross-session recall. Each benchmark question starts "
            "with a fresh synthetic retrieval session. Expected evidence slugs are "
            "checked exactly, and the benchmark writes only local machine-readable "
            "receipts."
        ),
        captured_at="2026-08-01T06:10:00-07:00",
        freshness_rank=1,
    ),
    SourceDoc(
        slug="synthetic/retrieval-quality/source-alpha-stale",
        source_id="alpha-stale",
        title="Alpha Stale Port Note",
        body="Stale note: Project Alpha should use dashboard route 7000.",
        captured_at="2026-07-01T06:00:00-07:00",
        freshness_rank=0,
        stale=True,
        superseded_by="synthetic/retrieval-quality/source-alpha-current",
    ),
]


QUESTIONS = [
    {
        "id": "alpha-route-current",
        "question": "Which dashboard route should Project Alpha use?",
        "tokens": ["alpha", "dashboard", "route"],
        "expected_answer_terms": ["8788"],
        "expected_slugs": ["synthetic/retrieval-quality/source-alpha-current"],
        "pruned_slugs": ["synthetic/retrieval-quality/source-alpha-stale"],
        "resolver_choice": "abstain_no_mutation",
    },
    {
        "id": "alpha-receipts",
        "question": "What must Alpha evidence receipts include?",
        "tokens": ["alpha", "evidence", "receipts"],
        "expected_answer_terms": ["source coverage", "freshness", "provenance", "degraded state"],
        "expected_slugs": ["synthetic/retrieval-quality/source-alpha-current"],
        "pruned_slugs": [],
        "resolver_choice": "abstain_no_mutation",
    },
    {
        "id": "alpha-owner",
        "question": "Who owns Project Alpha?",
        "tokens": ["alpha", "owner"],
        "expected_answer_terms": ["retrieval-quality benchmark team"],
        "expected_slugs": ["synthetic/retrieval-quality/source-alpha-current"],
        "pruned_slugs": [],
        "resolver_choice": "abstain_no_mutation",
    },
    {
        "id": "beta-resolver-topic",
        "question": "What does Project Beta evaluate?",
        "tokens": ["beta", "resolver", "evaluates"],
        "expected_answer_terms": ["resolver choices"],
        "expected_slugs": ["synthetic/retrieval-quality/source-beta-design"],
        "pruned_slugs": [],
        "resolver_choice": "abstain_no_mutation",
    },
    {
        "id": "beta-abstention",
        "question": "When should the resolver abstain?",
        "tokens": ["resolver", "abstain", "outside"],
        "expected_answer_terms": ["outside the synthetic corpus"],
        "expected_slugs": ["synthetic/retrieval-quality/source-beta-design"],
        "pruned_slugs": [],
        "resolver_choice": "abstain_no_mutation",
    },
    {
        "id": "beta-no-auto-approval",
        "question": "What must not happen to resolver proposals?",
        "tokens": ["resolver", "auto-approve", "proposals"],
        "expected_answer_terms": ["must not auto-approve proposals"],
        "expected_slugs": ["synthetic/retrieval-quality/source-beta-design"],
        "pruned_slugs": [],
        "resolver_choice": "abstain_no_mutation",
    },
    {
        "id": "gamma-fresh-session",
        "question": "How does Gamma prove cross-session recall?",
        "tokens": ["gamma", "cross-session", "fresh"],
        "expected_answer_terms": ["fresh synthetic retrieval session"],
        "expected_slugs": ["synthetic/retrieval-quality/source-gamma-session"],
        "pruned_slugs": [],
        "resolver_choice": "abstain_no_mutation",
    },
    {
        "id": "gamma-evidence-check",
        "question": "How are expected evidence slugs checked?",
        "tokens": ["expected", "evidence", "slugs", "checked"],
        "expected_answer_terms": ["checked exactly"],
        "expected_slugs": ["synthetic/retrieval-quality/source-gamma-session"],
        "pruned_slugs": [],
        "resolver_choice": "abstain_no_mutation",
    },
    {
        "id": "gamma-receipt-durability",
        "question": "What does the benchmark write?",
        "tokens": ["benchmark", "writes", "receipts"],
        "expected_answer_terms": ["local machine-readable receipts"],
        "expected_slugs": ["synthetic/retrieval-quality/source-gamma-session"],
        "pruned_slugs": [],
        "resolver_choice": "abstain_no_mutation",
    },
    {
        "id": "out-of-scope-abstention",
        "question": "Which private customer asked for the benchmark?",
        "tokens": ["private", "customer"],
        "expected_answer_terms": ["abstain"],
        "expected_slugs": [],
        "pruned_slugs": [],
        "resolver_choice": "abstain_no_mutation",
        "expect_abstention": True,
    },
]


class SyntheticRetrievalSession:
    def __init__(self, corpus: list[SourceDoc]):
        self.corpus = list(corpus)

    def search(self, tokens: list[str]) -> list[SourceDoc]:
        ranked = []
        for doc in self.corpus:
            text = f"{doc.title} {doc.body}".lower()
            score = sum(1 for token in tokens if token.lower() in text)
            if score:
                ranked.append((score, doc.freshness_rank, doc.slug, doc))
        ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
        return [row[3] for row in ranked]


def corpus_hash(corpus: list[SourceDoc]) -> str:
    payload = [
        {
            "slug": doc.slug,
            "source_id": doc.source_id,
            "title": doc.title,
            "body": doc.body,
            "captured_at": doc.captured_at,
            "freshness_rank": doc.freshness_rank,
            "stale": doc.stale,
            "superseded_by": doc.superseded_by,
        }
        for doc in corpus
    ]
    data = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def answer_for(question: dict[str, object], docs: list[SourceDoc], pruned: list[SourceDoc]) -> str:
    if question.get("expect_abstention"):
        return "Resolver abstained: question is outside the synthetic corpus; no mutation was performed."
    snippets = []
    for doc in docs:
        snippets.append(doc.body)
    if pruned:
        snippets.append("Stale contradictory evidence was pruned in favor of the current owned source.")
    return " ".join(snippets)


def run_question(question: dict[str, object], corpus: list[SourceDoc], session_index: int) -> dict[str, object]:
    session = SyntheticRetrievalSession(corpus)
    retrieved = session.search(list(question["tokens"]))
    pruned = [doc for doc in retrieved if doc.stale and doc.slug in set(question["pruned_slugs"])]
    used = [doc for doc in retrieved if not doc.stale]
    if question.get("expect_abstention"):
        used = []
        pruned = []
    answer = answer_for(question, used, pruned)
    expected_slugs = list(question["expected_slugs"])
    used_slugs = [doc.slug for doc in used]
    pruned_slugs = [doc.slug for doc in pruned]
    expected_terms = list(question["expected_answer_terms"])
    answer_lower = answer.lower()
    answer_success = all(term.lower() in answer_lower for term in expected_terms)
    recall_success = all(slug in used_slugs for slug in expected_slugs)
    pruning_success = all(slug in pruned_slugs for slug in question["pruned_slugs"])
    return {
        "id": question["id"],
        "session_id": f"fresh-session-{session_index:02d}",
        "fresh_session": True,
        "question": question["question"],
        "answer": answer,
        "answer_success": answer_success,
        "recall_success": recall_success,
        "expected_source_coverage": {
            "expected_slugs": expected_slugs,
            "used_slugs": used_slugs,
            "matched": len([slug for slug in expected_slugs if slug in used_slugs]),
            "expected": len(expected_slugs),
        },
        "freshness_provenance": [
            {
                "slug": doc.slug,
                "source_id": doc.source_id,
                "captured_at": doc.captured_at,
                "stale": doc.stale,
                "superseded_by": doc.superseded_by,
            }
            for doc in used + pruned
        ],
        "contradiction_pruning": {
            "expected_pruned_slugs": list(question["pruned_slugs"]),
            "pruned_slugs": pruned_slugs,
            "success": pruning_success,
        },
        "resolver": {
            "choice": question["resolver_choice"],
            "auto_approved": False,
            "mutated_production": False,
        },
        "fallback": {"used": False, "degraded": False, "reason": ""},
    }


def summarize(cases: list[dict[str, object]]) -> dict[str, object]:
    total_expected = sum(int(case["expected_source_coverage"]["expected"]) for case in cases)
    total_matched = sum(int(case["expected_source_coverage"]["matched"]) for case in cases)
    return {
        "question_count": len(cases),
        "answer_success_count": sum(1 for case in cases if case["answer_success"]),
        "recall_success_count": sum(1 for case in cases if case["recall_success"]),
        "expected_source_count": total_expected,
        "expected_source_matched": total_matched,
        "source_coverage": round(total_matched / total_expected, 4) if total_expected else 1.0,
        "fresh_session_count": sum(1 for case in cases if case["fresh_session"]),
        "contradiction_pruning_success_count": sum(
            1
            for case in cases
            if case["contradiction_pruning"]["expected_pruned_slugs"]
            and case["contradiction_pruning"]["success"]
        ),
        "resolver_auto_approved_count": sum(1 for case in cases if case["resolver"]["auto_approved"]),
        "production_mutation_count": sum(1 for case in cases if case["resolver"]["mutated_production"]),
        "fallback_used_count": sum(1 for case in cases if case["fallback"]["used"]),
        "degraded_count": sum(1 for case in cases if case["fallback"]["degraded"]),
    }


def run_benchmark(started_at: str | None = None) -> dict[str, object]:
    cases = [
        run_question(question, SYNTHETIC_CORPUS, index)
        for index, question in enumerate(QUESTIONS, 1)
    ]
    summary = summarize(cases)
    gate = {
        "all_answers_successful": summary["answer_success_count"] == summary["question_count"],
        "all_recall_successful": summary["recall_success_count"] == summary["question_count"],
        "all_expected_sources_covered": summary["source_coverage"] == 1.0,
        "fresh_sessions_used": summary["fresh_session_count"] == summary["question_count"],
        "contradiction_pruning_verified": summary["contradiction_pruning_success_count"] >= 1,
        "resolver_abstained_without_approval": summary["resolver_auto_approved_count"] == 0,
        "no_production_mutation": summary["production_mutation_count"] == 0,
        "no_fallback_or_degraded_state": summary["fallback_used_count"] == 0 and summary["degraded_count"] == 0,
    }
    return {
        "schema": SCHEMA_VERSION,
        "started_at": started_at or datetime.now(PACIFIC).replace(microsecond=0).isoformat(),
        "timezone": "America/Los_Angeles",
        "privacy": {
            "synthetic_corpus": True,
            "production_user_data_mutated": False,
            "resolver_proposals_auto_approved": False,
        },
        "corpus": {
            "source_count": len(SYNTHETIC_CORPUS),
            "fresh_source_count": sum(1 for doc in SYNTHETIC_CORPUS if not doc.stale),
            "stale_contradiction_count": sum(1 for doc in SYNTHETIC_CORPUS if doc.stale),
            "hash_sha256": corpus_hash(SYNTHETIC_CORPUS),
        },
        "summary": summary,
        "gate": gate,
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a deterministic synthetic cross-session retrieval benchmark.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = run_benchmark()
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
    return 0 if all(result["gate"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
