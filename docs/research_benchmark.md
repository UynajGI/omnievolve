# Research benchmark protocol

OmniEvolve is scoped as a single-machine research framework. Its canonical
comparison protocol contains nine heterogeneous executable tasks, five fixed
random seeds by default, and five variants:

- `full`
- `random_search`
- `single_agent`
- `no_novelty`
- `no_slow_loop`

Generate the 225-run manifest without making model API calls:

```bash
omnievolve research plan \
  --seeds 0,1,2,3,4 \
  --output .omnievolve/research/matrix.json
```

Each job has a stable ID and explicit configuration overrides. It can therefore
be idempotently inserted into `JobStore`, drained by `LocalTaskExecutor` with a
bounded worker count, and retried after transient failure.

`random_search` is a genuine LLM-free baseline: every slot independently applies
one deterministic, task-agnostic AST mutation to the frozen initial program.
Its mutation seed is derived from the experiment seed, generation, slot, island,
and parent source, so replay does not depend on thread scheduling. It does not
run Director, Coder, Critic, novelty, crossover, or the Slow Loop.

Validate the complete execution chain on `sort` before spending the full matrix
budget:

```bash
omnievolve research execute \
  --output .omnievolve/research/matrix.json \
  --task sort --seed-limit 2 \
  --workers 2 --gens 2 --population 2 \
  --results .omnievolve/research/pilot-results.jsonl
```

After the pilot is clean, drain all 225 runs. The queue database is persistent,
so the same command resumes queued work rather than duplicating it:

```bash
omnievolve research execute \
  --output .omnievolve/research/matrix.json \
  --workers 2 --gens 5 --population 4 \
  --max-attempts 3 \
  --results .omnievolve/research/results.jsonl
```

The executor appends one JSON object per completed or terminally failed run.
Each run uses isolated DB/artifact/vector directories and records a replay
command, Git commit, token/cost totals, wall time, and raw repetition scores:

```json
{"run_id":"…","task":"sort","variant":"full","seed":0,
 "status":"completed","score":0.73,"scores":[0.73],
 "cost_usd":0.02,"total_tokens":1432,"llm_calls":6,
 "candidate_counts":[9],"checkpoint_generations":[5],"wall_sec":41.2}
```

The executor rejects a superficially completed run if it did not reach the
requested generation, produced no evolved candidate, or (for an LLM variant)
recorded no successful LLM call. Such runs go through the bounded retry queue
and are never included as zero-token benchmark successes.

Aggregate results and calculate deterministic bootstrap confidence intervals
and confidence-aware regressions against the full variant. The report also makes
an explicit paired `full - no_slow_loop` decision: simplify only when the entire
bootstrap interval is below zero; keep when it is above zero; otherwise report
the result as inconclusive without deleting the feature.

```bash
omnievolve research analyze \
  --results .omnievolve/research/results.jsonl \
  --output .omnievolve/research/report.json
```

Evaluation requirements:

- Use a fixed candidate, evaluator version, environment version, seed, and split
  to form the replay identity.
- Keep correctness cases and benchmark/reference code in read-only hidden
  mounts with SHA-256 integrity digests.
- Reject explicit evaluator/test peeking before sandbox execution.
- Repeat noisy microbenchmarks and rank using a conservative confidence bound.
- Report failed seeds and costs alongside scores; never silently drop failures.

Reference-edge graph credit is intentionally not added as a sixth canonical
variant, so the principal matrix remains exactly 225 runs. Generate its separate
paired 90-run ablation with:

```bash
omnievolve research plan-reference \
  --seeds 0,1,2,3,4 \
  --output .omnievolve/research/reference-credit-matrix.json
```

CAS is the default code backend. Git remains optional for workflows that need
human-readable lineage, but its text merge is not treated as semantic
crossover. The default mechanical crossover is AST/semantic; LLM fusion can be
enabled as the higher-cost fallback.
