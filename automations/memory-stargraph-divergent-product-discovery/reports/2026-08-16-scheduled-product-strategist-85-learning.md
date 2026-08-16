---
type: Learning
title: Do Not Duplicate Planned Blocker Gates
goal: goals/memory-stargraph-continuous-learning-local-knowledge-os
product: products/memory-stargraph
status: active
source_run: runs/memory-stargraph-divergent-product-discovery-20260816t040209-0700-85
source_report: reports/memory-stargraph-divergent-product-discovery-20260816t040209-0700-85
tags:
  - discovery
  - learning
  - memory-stargraph
  - product-strategy
---

# Do Not Duplicate Planned Blocker Gates

When a weekly outcome gate is degraded because a single planned root TODO already exists, Product Strategy should not promote a duplicate TODO for adjacent symptoms. It should document adjacent opportunities, keep strategy rows as inputs, and let the canonical planned item resolve first.

Evidence from `runs/memory-stargraph-divergent-product-discovery-20260816t040209-0700-85`: weekly outcomes were 8/9 with the degraded gate explained by planned SG-0207; active tags were clear; resolver pending proposals were zero; configured-target attestation was current; SG-0206 had just restored resolver readiness; activation remained 1/6 and search probes were empty, but those were adjacent proposals rather than stronger current blockers.

Reusable rule: if the current blocker is already represented as a planned SG TODO, a Product Strategy run should return `completed_no_new_todo` unless it finds a clearly distinct evidence-backed gap that cannot be handled by the existing item.

