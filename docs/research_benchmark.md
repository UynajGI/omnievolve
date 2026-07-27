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

Workers should append one JSON object per completed run to
`.omnievolve/research/results.jsonl`:

```json
{"run_id":"…","task":"sort","variant":"full","seed":0,
 "status":"completed","score":0.73,"cost_usd":0.02,"wall_sec":41.2}
```

Aggregate results and calculate deterministic bootstrap confidence intervals
and confidence-aware regressions against the full variant:

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

CAS is the default code backend. Git remains optional for workflows that need
human-readable lineage, but its text merge is not treated as semantic
crossover.
