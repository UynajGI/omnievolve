window.BENCHMARK_DATA = {
  "lastUpdate": 1785136933132,
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
      },
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
          "id": "3a2e9ef808e1dd1fff808409bf2d86406d9be8c1",
          "message": "fix(test): CandidateArtifact 构造参数修正（source_code→candidate_id+language）",
          "timestamp": "2026-07-27T15:17:51+08:00",
          "tree_id": "6eb2c2a7245f9f0d3b6c1c28aabc4ee4398e24f7",
          "url": "https://github.com/UynajGI/omnievolve/commit/3a2e9ef808e1dd1fff808409bf2d86406d9be8c1"
        },
        "date": 1785136722001,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 920.9917306762758,
            "unit": "iter/sec",
            "range": "stddev: 0.0003159719564268969",
            "extra": "mean: 1.0857860789539437 msec\nrounds: 38"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 52395.787975271465,
            "unit": "iter/sec",
            "range": "stddev: 0.0000021047457837822566",
            "extra": "mean: 19.085503599486977 usec\nrounds: 10558"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 1382.867409213986,
            "unit": "iter/sec",
            "range": "stddev: 0.000006437990300667399",
            "extra": "mean: 723.1351272992935 usec\nrounds: 1359"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 30974.64294054019,
            "unit": "iter/sec",
            "range": "stddev: 0.000004038700093909031",
            "extra": "mean: 32.2844722349061 usec\nrounds: 17504"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 49590.31695889951,
            "unit": "iter/sec",
            "range": "stddev: 0.000001642625287377346",
            "extra": "mean: 20.165227030688282 usec\nrounds: 30432"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 41628.91893240855,
            "unit": "iter/sec",
            "range": "stddev: 0.0000018728044443073545",
            "extra": "mean: 24.02176241049319 usec\nrounds: 8380"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 1567.1806292091244,
            "unit": "iter/sec",
            "range": "stddev: 0.000022058878332575462",
            "extra": "mean: 638.0885402499191 usec\nrounds: 559"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 3212.1152491490443,
            "unit": "iter/sec",
            "range": "stddev: 0.000007798921093865938",
            "extra": "mean: 311.3213326529678 usec\nrounds: 2940"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 2238390.0647739763,
            "unit": "iter/sec",
            "range": "stddev: 4.5299447377719163e-8",
            "extra": "mean: 446.7496598279335 nsec\nrounds: 104800"
          }
        ]
      },
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
          "id": "401430ac28026b404998e77dd45de27a964ff2d5",
          "message": "style: ruff format test_docker_backend",
          "timestamp": "2026-07-27T15:21:22+08:00",
          "tree_id": "af4d8d0cdf410e97f20a86871b07336de52e30bd",
          "url": "https://github.com/UynajGI/omnievolve/commit/401430ac28026b404998e77dd45de27a964ff2d5"
        },
        "date": 1785136932842,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 1173.8740164210972,
            "unit": "iter/sec",
            "range": "stddev: 0.00047639755652861506",
            "extra": "mean: 851.8801728389869 usec\nrounds: 243"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 29049.548117485025,
            "unit": "iter/sec",
            "range": "stddev: 0.000004079455658759947",
            "extra": "mean: 34.4239433933947 usec\nrounds: 13638"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 1502.095645699727,
            "unit": "iter/sec",
            "range": "stddev: 0.000007801292881216111",
            "extra": "mean: 665.7365680160575 usec\nrounds: 1507"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 24473.896799588543,
            "unit": "iter/sec",
            "range": "stddev: 0.0000024300969211162235",
            "extra": "mean: 40.85986012725248 usec\nrounds: 16658"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 43806.570944245505,
            "unit": "iter/sec",
            "range": "stddev: 0.0000017238259365748927",
            "extra": "mean: 22.827625592351033 usec\nrounds: 28907"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 31856.443237134525,
            "unit": "iter/sec",
            "range": "stddev: 0.0000035926580492876788",
            "extra": "mean: 31.390823908248386 usec\nrounds: 8541"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 1431.201375027227,
            "unit": "iter/sec",
            "range": "stddev: 0.000015676541908869287",
            "extra": "mean: 698.7136942772823 usec\nrounds: 664"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 2321.565720040797,
            "unit": "iter/sec",
            "range": "stddev: 0.000007413243157458256",
            "extra": "mean: 430.743782684053 usec\nrounds: 2310"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 1616031.8217700883,
            "unit": "iter/sec",
            "range": "stddev: 2.5950889566329587e-7",
            "extra": "mean: 618.799695976698 nsec\nrounds: 177620"
          }
        ]
      }
    ]
  }
}