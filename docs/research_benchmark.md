# Research benchmark protocol

OmniEvolve is a single-machine research framework. Research data is admissible
only after enabled runtime mechanisms are live, auditable, independently
ablatable, and deterministically resumable. The historical v4 pilot is
engineering calibration data and is invalid for inference.

## Default Fast Loop R&D program

Normal runs and the default research matrix keep Slow Loop disabled. The
canonical control matrix uses four arms: `random_search`, `single_agent`,
`no_novelty`, and `no_slow_loop` (the full Fast Loop baseline). Generate it
with five to ten paired seeds:

```bash
omnievolve research plan \
  --seeds 0,1,2,3,4 \
  --eval-repetitions 3 \
  --output .omnievolve/research/fast-loop-matrix.json
```

Run operator, selector, context-retrieval, and evaluator-repeat experiments as
separate matrices so each comparison changes one mechanism at a time:

```bash
omnievolve research plan-operator  --output .omnievolve/research/operator-matrix.json
omnievolve research plan-selector  --output .omnievolve/research/selector-matrix.json
omnievolve research plan-context   --output .omnievolve/research/context-matrix.json
omnievolve research plan-evaluator --output .omnievolve/research/evaluator-matrix.json
```

All of these protocols explicitly set `evolution.self_evolve_enabled=false`.
Use `--task` and `--seed-limit 1` during `research execute` for an exploratory
smoke run before draining a paired matrix. The Slow Loop protocol below is a
separate, explicitly requested study and remains gated.

## Fixed 45-run pilot

The pilot crosses three tasks (`sort`, `nqueens`, and `circle_packing`), five
variants, and three paired search seeds:

- `full`
- `random_search`
- `single_agent`
- `no_novelty`
- `no_slow_loop`

`full` explicitly enables the real paired-arm Slow Loop canary;
`no_slow_loop` explicitly disables it.

Before generating the pilot manifest, calibrate evaluator noise on each frozen
initial candidate. Calibration runs with `gens=0`, CAS, fake embeddings, no
mutation, and no LLM calls. It starts at three measurements and automatically
stops when the two-sided 95% CI half-width resolves a normalized 5% effect, or
at ten measurements:

```bash
omnievolve research calibrate \
  --calibration .omnievolve/research/calibration.json

omnievolve research plan-pilot \
  --seeds 11,22,33 \
  --calibration .omnievolve/research/calibration.json \
  --output .omnievolve/research/pilot-matrix.json
```

`plan-pilot` fails closed when the calibration report is absent or incomplete.
Every job has a stable ID that includes the calibrated evaluator repeat count,
a `pilot` protocol label, and explicit configuration overrides. The search
runner passes `evolution.eval_repetitions` through the unified
`EvaluationService`; this is distinct from rerunning an entire search.
`random_search` is a genuine LLM-free baseline: every slot applies a
deterministic, task-agnostic AST mutation. It does not run Director, Coder,
Critic, novelty, crossover, or the Slow Loop.

```bash
omnievolve research execute \
  --output .omnievolve/research/pilot-matrix.json \
  --workers 2 --gens 5 --population 4 \
  --max-attempts 3 \
  --results .omnievolve/research/pilot-results.jsonl
```

The pilot passes only when:

- provenance/replay pollution is zero;
- non-algorithmic failures are at most 5%;
- every cell has at least two valid paired seeds;
- deterministic replay passes;
- cost is known or explicitly excluded from comparison.

Paired-seed variance then determines the formal seed count for 80% power at 5%
significance and a 5% normalized effect. Clamp the answer to 5–10 seeds. If ten
is still insufficient, report the study as underpowered rather than expanding
the claim.

## Formal matrix

Only after the pilot gate, generate the existing nine-task, five-variant formal
matrix with the power-selected seed count:

```bash
omnievolve research plan-slow \
  --seeds 0,1,2,3,4 \
  --eval-repetitions 3 \
  --output .omnievolve/research/slow-loop-formal-matrix.json

omnievolve research execute \
  --output .omnievolve/research/slow-loop-formal-matrix.json \
  --workers 2 --gens 5 --population 4 \
  --max-attempts 3 \
  --results .omnievolve/research/results.jsonl
```

The local queue is persistent. Enqueue is idempotent, leases are recoverable,
and concurrency is bounded. Permanent configuration, authentication, and
integrity errors are not retried. Timeouts, rate limits, and transient provider
failures use bounded exponential backoff. Each attempt retains independent
provenance and resource usage.

Each isolated run records frontier trajectory, best-of-budget, success,
repetition statistics, token/cost totals, wall time, strict replay evidence,
and a failure category:

```json
{"schema_version":2,"run_id":"...","protocol":"pilot","task":"sort",
 "variant":"full","seed":11,"status":"completed",
 "frontier_auc":0.71,"best_of_budget":0.73,"success_rate":1.0,
 "score_ci_low":0.69,"score_ci_high":0.74,
 "cost_known":true,"cost_usd":0.02,"total_tokens":1432,
 "wall_sec":41.2,"failure_category":null}
```

Unknown model price is represented as `cost_usd = null` and
`cost_known = false`; it never participates as zero cost.

```bash
omnievolve research analyze \
  --results .omnievolve/research/results.jsonl \
  --deterministic-replay-passed \
  --output .omnievolve/research/report.json
```

Reports include paired-seed effects for frontier AUC, best-of-budget, success
rate, measurement confidence intervals, tokens, wall time, known cost, and
failure classes. Pilot analysis is fail-closed unless the deterministic replay
invariant is explicitly confirmed. Cost is required by default; use
`--exclude-cost` only when the protocol explicitly excludes cost before
analysis. The report includes the pilot gate and the maximum paired-variance
seed recommendation across comparisons, capped at 5–10 with an explicit
`underpowered_at_ten` flag.

## Evaluation and replay requirements

- Use candidate, evaluator version, stable environment version, seed, and split
  as the replay identity.
- Keep correctness cases and benchmark/reference code in read-only hidden
  mounts with SHA-256 integrity digests.
- Reject evaluator/test peeking before sandbox execution.
- Route every fidelity through `EvaluationService`: static validation,
  anti-cheat, progressive stages, hidden tests, repeated benchmark, robust
  aggregation, and commit.
- Require `run(N) == run(K) + resume(N-K)` under fake LLM/embedding for
  normalized lineage, artifact hashes, scores, router state, budget ledger, and
  checkpoint state.
- Report failed seeds and costs alongside scores; never silently drop failures.

## Fast Loop ablations

Run these as independent Fast Loop experiments. They do not depend on passing
the separate Slow Loop pilot gate:

1. operator UCB/Thompson versus a fixed mutation mix;
2. parent-selector alternatives versus `lineage_ucb`;
3. context retrieval budgets 4/8/16;
4. one versus three evaluator measurements per candidate;
5. a minimal behavior-cell archive versus the current archive.

Generate their manifests independently:

```bash
omnievolve research plan-operator \
  --seeds 0,1,2,3,4 \
  --output .omnievolve/research/operator-portfolio-matrix.json

omnievolve research plan-selector \
  --seeds 0,1,2,3,4 \
  --output .omnievolve/research/selector-matrix.json

omnievolve research plan-context \
  --seeds 0,1,2,3,4 \
  --output .omnievolve/research/context-matrix.json

omnievolve research plan-evaluator \
  --seeds 0,1,2,3,4 \
  --output .omnievolve/research/evaluator-matrix.json

omnievolve research plan-qd \
  --seeds 0,1,2,3,4 \
  --output .omnievolve/research/qd-archive-matrix.json
```

`operator_fixed`, `selector_lineage_ucb`, `context_retrieval_8`,
`evaluator_repeat_1`, and `qd_off` are the respective baselines. Analysis
groups by protocol before pairing, applies
an exact paired randomization test with Holm correction, and reports paired
effect, standardized effect, and Cliff's delta. Unknown provider prices remain
`cost_usd = null, cost_known = false` from the call ledger through the CLI and
are excluded from all cost comparisons.

Do not enable both together, and do not rewrite the search state as full
MAP-Elites before their independent evidence is available. True DAG MCGS,
rollouts, PUCT, and continuous steady-state async also remain out of scope.

Reference-edge graph credit remains a separate paired ablation:

```bash
omnievolve research plan-reference \
  --seeds 0,1,2,3,4 \
  --output .omnievolve/research/reference-credit-matrix.json
```

CAS is the default code backend. Git remains optional for human-readable
provenance, but text merge is not treated as semantic crossover. The canonical
selector is `lineage_ucb`; `progressive_mcgs` is a deprecated compatibility
alias for one schema cycle.
