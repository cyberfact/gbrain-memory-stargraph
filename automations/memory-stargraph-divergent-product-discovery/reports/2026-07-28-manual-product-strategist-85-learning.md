---
type: learning
title: Do not promote strategy parents while a P1 runtime blocker owns the current validation loop
run: runs/memory-stargraph-divergent-product-discovery-manual-20260728t161121-0700-85
goal: goals/memory-stargraph-continuous-learning-local-knowledge-os
product: products/memory-stargraph
created_at: '2026-07-28T16:24:00-07:00'
tags:
  - learning
  - memory-stargraph
  - product-discovery
  - prioritization
---

# Do not promote strategy parents while a P1 runtime blocker owns the current validation loop

When Product Strategist evidence finds a strong broad opportunity, first dedupe against the strategy backlog and the current implementation backlog. If a P1 blocker already controls the core validation loop, keep adjacent strategy opportunities as proposals rather than promoting extra SG implementation TODOs.

Evidence from [[runs/memory-stargraph-divergent-product-discovery-manual-20260728t161121-0700-85]]: SG-0167 already covers the Ask Yoda OpenClaw provider/model/agent configuration follow-up, and strategy parents already cover customer preflight, graph-quality cockpit, evidence cards, and vertical workflow pack scope. Promoting another SG TODO before SG-0167 would add backlog noise and make product validation weaker, not stronger.

Reusable rule: divergent discovery should sharpen Product Owner choice. It should not turn every strategic direction into implementation work when the existing backlog already contains the critical next validation step.
