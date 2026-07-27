window.BENCHMARK_DATA = {
  "lastUpdate": 1785136490086,
  "repoUrl": "https://github.com/UynajGI/omnievolve",
  "entries": {
    "Benchmark": [
      {
        "commit": {
          "author": {
            "email": "yuunagi.cn@outlook.com",
            "name": "結凪",
            "username": "UynajGI"
          },
          "committer": {
            "email": "yuunagi.cn@outlook.com",
            "name": "結凪",
            "username": "UynajGI"
          },
          "distinct": true,
          "id": "a5c39aedf88828eb0e91bca1ec3bcf4237784480",
          "message": "fix(ci): 移除 skip-fetch-gh-pages（gh-pages 分支已创建，正常 fetch）",
          "timestamp": "2026-07-27T15:13:53+08:00",
          "tree_id": "19eb9563442aa51cbf1f1c310c0b8b4dd76c1a6e",
          "url": "https://github.com/UynajGI/omnievolve/commit/a5c39aedf88828eb0e91bca1ec3bcf4237784480"
        },
        "date": 1785136489376,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 1083.974180009079,
            "unit": "iter/sec",
            "range": "stddev: 0.0001949927210788226",
            "extra": "mean: 922.531199028767 usec\nrounds: 206"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 27408.071417703333,
            "unit": "iter/sec",
            "range": "stddev: 0.000004854463289705646",
            "extra": "mean: 36.48560253510151 usec\nrounds: 14122"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 1502.7761519911098,
            "unit": "iter/sec",
            "range": "stddev: 0.0000069244402967949275",
            "extra": "mean: 665.4351006801949 usec\nrounds: 1470"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 25143.120141445055,
            "unit": "iter/sec",
            "range": "stddev: 0.0000028521956101479567",
            "extra": "mean: 39.77231124754618 usec\nrounds: 16270"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 43227.058551290604,
            "unit": "iter/sec",
            "range": "stddev: 0.000002002077590975971",
            "extra": "mean: 23.13365825744217 usec\nrounds: 29531"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 32059.9877159669,
            "unit": "iter/sec",
            "range": "stddev: 0.00000488158970848919",
            "extra": "mean: 31.191527858944497 usec\nrounds: 8220"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 1406.6412151106415,
            "unit": "iter/sec",
            "range": "stddev: 0.000022871899696848718",
            "extra": "mean: 710.9133368606318 usec\nrounds: 567"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 2314.5083497573264,
            "unit": "iter/sec",
            "range": "stddev: 0.000014089904389850254",
            "extra": "mean: 432.05720130793605 usec\nrounds: 2141"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 1555710.010320239,
            "unit": "iter/sec",
            "range": "stddev: 2.876493942093482e-7",
            "extra": "mean: 642.7933183988142 nsec\nrounds: 173281"
          }
        ]
      }
    ]
  }
}