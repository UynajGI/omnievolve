window.BENCHMARK_DATA = {
  "lastUpdate": 1785596551473,
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
          "id": "c4362e1f6631bc8e71b9895c7c3e9297aaf19114",
          "message": "fix(ci): docker fixture 尝试 pull 镜像失败则 skip + benchmark fail-on-alert=false",
          "timestamp": "2026-07-27T15:25:44+08:00",
          "tree_id": "8c483cd70b724f4a6dc352a3faf84172b788ca97",
          "url": "https://github.com/UynajGI/omnievolve/commit/c4362e1f6631bc8e71b9895c7c3e9297aaf19114"
        },
        "date": 1785137202857,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 1188.457865114876,
            "unit": "iter/sec",
            "range": "stddev: 0.0001877595495846035",
            "extra": "mean: 841.4265489364575 usec\nrounds: 235"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 28268.748421307664,
            "unit": "iter/sec",
            "range": "stddev: 0.0000052842520210800004",
            "extra": "mean: 35.37475324681324 usec\nrounds: 14091"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 1504.9271468778727,
            "unit": "iter/sec",
            "range": "stddev: 0.000006451839560047618",
            "extra": "mean: 664.4839931784097 usec\nrounds: 1466"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 24863.899514634057,
            "unit": "iter/sec",
            "range": "stddev: 0.000002739424971927178",
            "extra": "mean: 40.21895275965999 usec\nrounds: 16723"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 40833.59715339584,
            "unit": "iter/sec",
            "range": "stddev: 0.000006491449437150169",
            "extra": "mean: 24.489637693279665 usec\nrounds: 28716"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 32175.81590760465,
            "unit": "iter/sec",
            "range": "stddev: 0.000004230115790331932",
            "extra": "mean: 31.079242959108715 usec\nrounds: 9125"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 1423.6416825090432,
            "unit": "iter/sec",
            "range": "stddev: 0.000016475646347371062",
            "extra": "mean: 702.4239401571805 usec\nrounds: 635"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 2315.7959440693226,
            "unit": "iter/sec",
            "range": "stddev: 0.000008408337990375459",
            "extra": "mean: 431.81697530862647 usec\nrounds: 2187"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 1566932.2718625902,
            "unit": "iter/sec",
            "range": "stddev: 2.5344096503897604e-7",
            "extra": "mean: 638.1896767058822 nsec\nrounds: 187266"
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
          "id": "6b90d3eebac6bc9fbb6e08a2e9f2e502b4683927",
          "message": "fix: DockerBackend._build_command 使用 shlex.quote 转义参数（修复括号解析错误）",
          "timestamp": "2026-07-27T15:29:55+08:00",
          "tree_id": "243739c10ffdcb7966f6ae691750e7cb292111b2",
          "url": "https://github.com/UynajGI/omnievolve/commit/6b90d3eebac6bc9fbb6e08a2e9f2e502b4683927"
        },
        "date": 1785137446023,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 1458.2534406079878,
            "unit": "iter/sec",
            "range": "stddev: 0.00010950878018234967",
            "extra": "mean: 685.7518536579424 usec\nrounds: 205"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 32728.208640560213,
            "unit": "iter/sec",
            "range": "stddev: 0.0000021101469207967784",
            "extra": "mean: 30.554681772612987 usec\nrounds: 12975"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 1335.0343129649377,
            "unit": "iter/sec",
            "range": "stddev: 0.000006964721918495992",
            "extra": "mean: 749.0444180263277 usec\nrounds: 1287"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 26965.526872814917,
            "unit": "iter/sec",
            "range": "stddev: 0.000003810139492519944",
            "extra": "mean: 37.08438573132951 usec\nrounds: 17577"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 46097.74320981745,
            "unit": "iter/sec",
            "range": "stddev: 0.0000030381300866400662",
            "extra": "mean: 21.69303593558632 usec\nrounds: 29525"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 33921.299217403204,
            "unit": "iter/sec",
            "range": "stddev: 0.00000820867311775469",
            "extra": "mean: 29.480002920612 usec\nrounds: 7875"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 1468.674187691323,
            "unit": "iter/sec",
            "range": "stddev: 0.000024890525525204205",
            "extra": "mean: 680.8862090590334 usec\nrounds: 574"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 2095.2784827431374,
            "unit": "iter/sec",
            "range": "stddev: 0.00003765121795736097",
            "extra": "mean: 477.26352761032535 usec\nrounds: 1992"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 2162900.8242961317,
            "unit": "iter/sec",
            "range": "stddev: 4.769755749663633e-8",
            "extra": "mean: 462.3420495137256 nsec\nrounds: 100453"
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
          "id": "5a992c15bd49661f5b9e12d34fadd21d2777905d",
          "message": "fix: Docker 超时检测简化 — wait() 抛异常即视为 timed_out",
          "timestamp": "2026-07-27T15:36:07+08:00",
          "tree_id": "2572ad0f0bf2e76ab5e304abf4a05b56b55c1897",
          "url": "https://github.com/UynajGI/omnievolve/commit/5a992c15bd49661f5b9e12d34fadd21d2777905d"
        },
        "date": 1785137817398,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 1423.5959542351793,
            "unit": "iter/sec",
            "range": "stddev: 0.00036766410732583336",
            "extra": "mean: 702.4465031844276 usec\nrounds: 314"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 32819.413749799576,
            "unit": "iter/sec",
            "range": "stddev: 0.0000023542577252313924",
            "extra": "mean: 30.46977035066956 usec\nrounds: 12776"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 1335.3316175112525,
            "unit": "iter/sec",
            "range": "stddev: 0.000005990509042598818",
            "extra": "mean: 748.87764723475 usec\nrounds: 1338"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 25719.60803063168,
            "unit": "iter/sec",
            "range": "stddev: 0.0000026000130916822717",
            "extra": "mean: 38.88084137242739 usec\nrounds: 17166"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 46186.59275461237,
            "unit": "iter/sec",
            "range": "stddev: 0.0000016041865358433867",
            "extra": "mean: 21.65130485621579 usec\nrounds: 28994"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 35262.41206587593,
            "unit": "iter/sec",
            "range": "stddev: 0.0000021271011133562604",
            "extra": "mean: 28.35880875454116 usec\nrounds: 7676"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 1488.746167001538,
            "unit": "iter/sec",
            "range": "stddev: 0.000021957913748021617",
            "extra": "mean: 671.706179445006 usec\nrounds: 613"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 1483.4727927046497,
            "unit": "iter/sec",
            "range": "stddev: 0.00000635931182596194",
            "extra": "mean: 674.0939267088359 usec\nrounds: 1419"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 1684347.570110824,
            "unit": "iter/sec",
            "range": "stddev: 2.594165290709972e-7",
            "extra": "mean: 593.7016906398978 nsec\nrounds: 185254"
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
          "id": "1d0593d1decb1c39cfa6e3971ff49a8aea83225a",
          "message": "fix(ci): docker job 设为 continue-on-error（Docker Hub 网络波动不阻塞 CI）",
          "timestamp": "2026-07-27T15:40:44+08:00",
          "tree_id": "6a89683755a4d976a709dbe5eec0670a0501e3e2",
          "url": "https://github.com/UynajGI/omnievolve/commit/1d0593d1decb1c39cfa6e3971ff49a8aea83225a"
        },
        "date": 1785138100546,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 1104.312434465112,
            "unit": "iter/sec",
            "range": "stddev: 0.0003448440823083722",
            "extra": "mean: 905.5408313720229 usec\nrounds: 255"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 27691.44650868445,
            "unit": "iter/sec",
            "range": "stddev: 0.0000073088839505452885",
            "extra": "mean: 36.11223414011201 usec\nrounds: 13966"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 1504.1642634566158,
            "unit": "iter/sec",
            "range": "stddev: 0.0000067223553139968945",
            "extra": "mean: 664.821006784172 usec\nrounds: 1474"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 25050.247493925428,
            "unit": "iter/sec",
            "range": "stddev: 0.0000028011321729229957",
            "extra": "mean: 39.919765273476656 usec\nrounds: 16892"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 43719.158991216675,
            "unit": "iter/sec",
            "range": "stddev: 0.0000018898733815565966",
            "extra": "mean: 22.873267077276196 usec\nrounds: 28898"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 32116.222817134996,
            "unit": "iter/sec",
            "range": "stddev: 0.000004379584568447129",
            "extra": "mean: 31.136911886987818 usec\nrounds: 7218"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 1400.8448176719585,
            "unit": "iter/sec",
            "range": "stddev: 0.000023052533925304165",
            "extra": "mean: 713.8549448052954 usec\nrounds: 616"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 2309.090433234466,
            "unit": "iter/sec",
            "range": "stddev: 0.000009943618464940984",
            "extra": "mean: 433.07095538880503 usec\nrounds: 2264"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 1984515.1255768633,
            "unit": "iter/sec",
            "range": "stddev: 7.371265994187102e-8",
            "extra": "mean: 503.90142514500496 nsec\nrounds: 92166"
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
          "id": "c13a73bc174b13546029f51a79cdd0a9137ec465",
          "message": "feat: max_tokens 可配置一等项（默认 16384），接入 LLMGateway",
          "timestamp": "2026-07-27T15:49:09+08:00",
          "tree_id": "d83ba16bcab6e62dd6a300e7715ca9525b0096c1",
          "url": "https://github.com/UynajGI/omnievolve/commit/c13a73bc174b13546029f51a79cdd0a9137ec465"
        },
        "date": 1785138599769,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 1394.8811437408933,
            "unit": "iter/sec",
            "range": "stddev: 0.00036759912996473236",
            "extra": "mean: 716.9069597701548 usec\nrounds: 348"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 33200.99270145189,
            "unit": "iter/sec",
            "range": "stddev: 0.000002282224836036874",
            "extra": "mean: 30.119581332767492 usec\nrounds: 12996"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 1338.2943562989717,
            "unit": "iter/sec",
            "range": "stddev: 0.000005902216660414017",
            "extra": "mean: 747.2197691735632 usec\nrounds: 1343"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 27102.158151291107,
            "unit": "iter/sec",
            "range": "stddev: 0.0000022617517437321",
            "extra": "mean: 36.89743061854141 usec\nrounds: 16330"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 46750.340744444664,
            "unit": "iter/sec",
            "range": "stddev: 0.00000179520322131424",
            "extra": "mean: 21.39021842570912 usec\nrounds: 29969"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 35910.460136575144,
            "unit": "iter/sec",
            "range": "stddev: 0.000002193661139938489",
            "extra": "mean: 27.847039447469808 usec\nrounds: 8036"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 1479.9139581884547,
            "unit": "iter/sec",
            "range": "stddev: 0.000015543159888591787",
            "extra": "mean: 675.7149592832332 usec\nrounds: 614"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 2121.8236003143893,
            "unit": "iter/sec",
            "range": "stddev: 0.000007330497944910232",
            "extra": "mean: 471.2927124817683 usec\nrounds: 2059"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 2231627.75103106,
            "unit": "iter/sec",
            "range": "stddev: 3.5071101897485564e-8",
            "extra": "mean: 448.10340772020714 nsec\nrounds: 51420"
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
          "id": "272c3f85483dd706f70401c6fb7bc6b2a9d5e638",
          "message": "docs: 同步 2026-07-27 变更（Windows 兼容、CI 修复、max_tokens、管线验证）",
          "timestamp": "2026-07-27T15:56:24+08:00",
          "tree_id": "3901aa2f3523e0a8467d9dce9188dc4435ff1e3c",
          "url": "https://github.com/UynajGI/omnievolve/commit/272c3f85483dd706f70401c6fb7bc6b2a9d5e638"
        },
        "date": 1785139033521,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 1153.2017686109482,
            "unit": "iter/sec",
            "range": "stddev: 0.00011935100105848974",
            "extra": "mean: 867.1509420285728 usec\nrounds: 207"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 28233.546166342818,
            "unit": "iter/sec",
            "range": "stddev: 0.000004346920737167431",
            "extra": "mean: 35.418859328131404 usec\nrounds: 13990"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 1504.3043665767375,
            "unit": "iter/sec",
            "range": "stddev: 0.000006360672355366071",
            "extra": "mean: 664.759088797731 usec\nrounds: 1464"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 25262.544682664702,
            "unit": "iter/sec",
            "range": "stddev: 0.0000026255798724471344",
            "extra": "mean: 39.584294162028954 usec\nrounds: 17215"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 39761.96915157521,
            "unit": "iter/sec",
            "range": "stddev: 0.000007437725490027971",
            "extra": "mean: 25.14965987192272 usec\nrounds: 29974"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 32768.23586991844,
            "unit": "iter/sec",
            "range": "stddev: 0.0000039348626595102564",
            "extra": "mean: 30.517358455601503 usec\nrounds: 9195"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 1419.2606625547342,
            "unit": "iter/sec",
            "range": "stddev: 0.00001950028784728894",
            "extra": "mean: 704.5922052119405 usec\nrounds: 614"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 2314.026823558181,
            "unit": "iter/sec",
            "range": "stddev: 0.00001966111457006782",
            "extra": "mean: 432.147108157693 usec\nrounds: 2182"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 1608215.6742009355,
            "unit": "iter/sec",
            "range": "stddev: 2.4145065621535265e-7",
            "extra": "mean: 621.8071469157046 nsec\nrounds: 169751"
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
          "id": "269975b84aa72248b79e379b4921ce1c43bc8aab",
          "message": "fix: CAS backend Windows encoding + missing ArtifactStore methods\n\n- cas_code_store.py: write_text(encoding='utf-8') fixes SyntaxError on\n  Chinese Windows (GBK locale wrote non-UTF-8 main.py)\n- cas_code_store.py: add store/load/load_text/load_manifest delegates\n  so subprocess_backend._collect_outputs and engine fast_loop work\n- initial_code.py (LJ38): add 140s time budget with graceful early-exit\n  (was exceeding 160s sandbox timeout → score=0)\n- configs: code_backend='cas' (git plumbing fails silently on Windows)\n- llm_gateway/cli/config: mimo-v2.5-pro integration from prev session",
          "timestamp": "2026-07-27T18:54:07+08:00",
          "tree_id": "0de659adbeeec508053aaa61b10e84831d340646",
          "url": "https://github.com/UynajGI/omnievolve/commit/269975b84aa72248b79e379b4921ce1c43bc8aab"
        },
        "date": 1785149707064,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 1020.0080464252898,
            "unit": "iter/sec",
            "range": "stddev: 0.00027022888456254877",
            "extra": "mean: 980.384422950966 usec\nrounds: 305"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 28636.28681039302,
            "unit": "iter/sec",
            "range": "stddev: 0.000004772761640718468",
            "extra": "mean: 34.92072860637323 usec\nrounds: 2863"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 1503.4289845901721,
            "unit": "iter/sec",
            "range": "stddev: 0.0000069732054614753555",
            "extra": "mean: 665.1461494023248 usec\nrounds: 1506"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 24391.214331781146,
            "unit": "iter/sec",
            "range": "stddev: 0.000002782401652270668",
            "extra": "mean: 40.9983687731785 usec\nrounds: 16742"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 42997.52667417908,
            "unit": "iter/sec",
            "range": "stddev: 0.000001780438614705297",
            "extra": "mean: 23.257151686367138 usec\nrounds: 29383"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 32664.827562168302,
            "unit": "iter/sec",
            "range": "stddev: 0.000003916191919322144",
            "extra": "mean: 30.613968437359162 usec\nrounds: 8998"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 1373.9637668496173,
            "unit": "iter/sec",
            "range": "stddev: 0.000023170801571657896",
            "extra": "mean: 727.8212308996441 usec\nrounds: 589"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 2301.3079471589695,
            "unit": "iter/sec",
            "range": "stddev: 0.000014979106503235918",
            "extra": "mean: 434.5355002291322 usec\nrounds: 2183"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 1571561.422380784,
            "unit": "iter/sec",
            "range": "stddev: 2.574812319052098e-7",
            "extra": "mean: 636.3098417655758 nsec\nrounds: 192679"
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
          "id": "92c5f95fd39805b6c38fb3343a3c93d989513f0f",
          "message": "fix: preserve CAS throughput on Unix",
          "timestamp": "2026-07-27T19:28:38+08:00",
          "tree_id": "2a4efb26e1e272e6ae2b29a84dc86af2194f3783",
          "url": "https://github.com/UynajGI/omnievolve/commit/92c5f95fd39805b6c38fb3343a3c93d989513f0f"
        },
        "date": 1785151758238,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 1359.4938798468245,
            "unit": "iter/sec",
            "range": "stddev: 0.00009975257857919404",
            "extra": "mean: 735.5678571445067 usec\nrounds: 7"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 60344.00073781058,
            "unit": "iter/sec",
            "range": "stddev: 9.135419462718765e-7",
            "extra": "mean: 16.571655637234144 usec\nrounds: 18919"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 2099.320451766502,
            "unit": "iter/sec",
            "range": "stddev: 0.000007937122399232396",
            "extra": "mean: 476.3446186400634 usec\nrounds: 2103"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 54338.09698291775,
            "unit": "iter/sec",
            "range": "stddev: 0.000001450398751930616",
            "extra": "mean: 18.403294475225543 usec\nrounds: 29612"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 93485.47650203657,
            "unit": "iter/sec",
            "range": "stddev: 0.0000010516177604138424",
            "extra": "mean: 10.696848723643345 usec\nrounds: 50378"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 67458.2617628925,
            "unit": "iter/sec",
            "range": "stddev: 0.0000027067189875033788",
            "extra": "mean: 14.823981138364891 usec\nrounds: 9013"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 2956.5111936755625,
            "unit": "iter/sec",
            "range": "stddev: 0.00001708852630382203",
            "extra": "mean: 338.2365005548282 usec\nrounds: 901"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 3934.5583927247126,
            "unit": "iter/sec",
            "range": "stddev: 0.000005396840091834226",
            "extra": "mean: 254.15812911788868 usec\nrounds: 3764"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 4030455.189512286,
            "unit": "iter/sec",
            "range": "stddev: 2.906714006352868e-8",
            "extra": "mean: 248.11093362410193 nsec\nrounds: 189466"
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
          "id": "e9ea61fc63c27d291267b89211164f9387ecab23",
          "message": "fix: harden code backends and CLI workflows",
          "timestamp": "2026-07-27T21:17:34+08:00",
          "tree_id": "e74f1c0f82417cc73165d7ec5af0b40d638c128f",
          "url": "https://github.com/UynajGI/omnievolve/commit/e9ea61fc63c27d291267b89211164f9387ecab23"
        },
        "date": 1785158307640,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 1415.8471865147367,
            "unit": "iter/sec",
            "range": "stddev: 0.0006952359110069655",
            "extra": "mean: 706.2909115648347 usec\nrounds: 294"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 42956.30523344635,
            "unit": "iter/sec",
            "range": "stddev: 0.0000016023499527819917",
            "extra": "mean: 23.279469557856356 usec\nrounds: 15357"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 1250.9266399857154,
            "unit": "iter/sec",
            "range": "stddev: 0.00004494789763237366",
            "extra": "mean: 799.4073897182486 usec\nrounds: 1206"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 28114.741494278256,
            "unit": "iter/sec",
            "range": "stddev: 0.0000015429699834873459",
            "extra": "mean: 35.568529065206384 usec\nrounds: 16635"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 46186.191450607555,
            "unit": "iter/sec",
            "range": "stddev: 0.0000012585545564430556",
            "extra": "mean: 21.651492980741228 usec\nrounds: 31271"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 38535.06273835987,
            "unit": "iter/sec",
            "range": "stddev: 0.0000014544642839358115",
            "extra": "mean: 25.950392420265775 usec\nrounds: 9156"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 1365.3053256169258,
            "unit": "iter/sec",
            "range": "stddev: 0.000023725095752982692",
            "extra": "mean: 732.436899818098 usec\nrounds: 549"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 2448.213669336656,
            "unit": "iter/sec",
            "range": "stddev: 0.00000840391385246426",
            "extra": "mean: 408.461080225465 usec\nrounds: 2306"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 2002347.329217907,
            "unit": "iter/sec",
            "range": "stddev: 3.725869341393399e-8",
            "extra": "mean: 499.4138556324232 nsec\nrounds: 96975"
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
          "id": "c81c3066f33ae077dff503f60f627ce451b6dfc2",
          "message": "fix: load sandbox image before CI verification",
          "timestamp": "2026-07-27T21:21:06+08:00",
          "tree_id": "fde670c510cdb1c859d8c7836cc06d84dc7abf90",
          "url": "https://github.com/UynajGI/omnievolve/commit/c81c3066f33ae077dff503f60f627ce451b6dfc2"
        },
        "date": 1785158517128,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 1412.8384380840957,
            "unit": "iter/sec",
            "range": "stddev: 0.00047960205447238936",
            "extra": "mean: 707.7950125394857 usec\nrounds: 319"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 42572.319807200525,
            "unit": "iter/sec",
            "range": "stddev: 0.000002250150951814942",
            "extra": "mean: 23.48944113284763 usec\nrounds: 15535"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 1254.655952088333,
            "unit": "iter/sec",
            "range": "stddev: 0.00003103280152042225",
            "extra": "mean: 797.0312485550588 usec\nrounds: 1211"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 27075.024421323127,
            "unit": "iter/sec",
            "range": "stddev: 0.000007086539840744472",
            "extra": "mean: 36.934408052184175 usec\nrounds: 17635"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 46766.77035896392,
            "unit": "iter/sec",
            "range": "stddev: 0.0000013776412519497634",
            "extra": "mean: 21.38270383702746 usec\nrounds: 30831"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 38150.315360845714,
            "unit": "iter/sec",
            "range": "stddev: 0.000001638779499627064",
            "extra": "mean: 26.212103112162374 usec\nrounds: 9543"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 1388.1026903379905,
            "unit": "iter/sec",
            "range": "stddev: 0.000021466980802797883",
            "extra": "mean: 720.4077961670898 usec\nrounds: 574"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 2443.5273856985195,
            "unit": "iter/sec",
            "range": "stddev: 0.000007490144244274909",
            "extra": "mean: 409.24444139762926 usec\nrounds: 2261"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 1992255.2482902564,
            "unit": "iter/sec",
            "range": "stddev: 4.519381305608229e-8",
            "extra": "mean: 501.9437147213918 nsec\nrounds: 96201"
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
          "id": "cb55586d91be2ad757f81d91fba55eecb1f054be",
          "message": "feat:reproducible-research-benchmark-framework",
          "timestamp": "2026-07-27T22:13:14+08:00",
          "tree_id": "2d386cb73b2c2da3a5b0b0390279dabc12d587ad",
          "url": "https://github.com/UynajGI/omnievolve/commit/cb55586d91be2ad757f81d91fba55eecb1f054be"
        },
        "date": 1785161655385,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 1137.458624944415,
            "unit": "iter/sec",
            "range": "stddev: 0.0001483593187744649",
            "extra": "mean: 879.1528571413905 usec\nrounds: 196"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 27873.262597393907,
            "unit": "iter/sec",
            "range": "stddev: 0.000006399932474331432",
            "extra": "mean: 35.87667559568351 usec\nrounds: 13514"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 1504.946223743905,
            "unit": "iter/sec",
            "range": "stddev: 0.000006339625051834156",
            "extra": "mean: 664.475570105267 usec\nrounds: 1512"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 24817.387615426826,
            "unit": "iter/sec",
            "range": "stddev: 0.000003141217250057811",
            "extra": "mean: 40.29432974558476 usec\nrounds: 16167"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 43657.1243019506,
            "unit": "iter/sec",
            "range": "stddev: 0.000001851396321870181",
            "extra": "mean: 22.905768897731082 usec\nrounds: 28641"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 31932.29116122723,
            "unit": "iter/sec",
            "range": "stddev: 0.000004071440728910419",
            "extra": "mean: 31.316262116957592 usec\nrounds: 6829"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 1417.916641195414,
            "unit": "iter/sec",
            "range": "stddev: 0.000019016957474587275",
            "extra": "mean: 705.2600773180305 usec\nrounds: 582"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 2309.075657326329,
            "unit": "iter/sec",
            "range": "stddev: 0.000013432292867716494",
            "extra": "mean: 433.07372663479407 usec\nrounds: 2279"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 1541713.6166919444,
            "unit": "iter/sec",
            "range": "stddev: 2.813298428465964e-7",
            "extra": "mean: 648.6288952585762 nsec\nrounds: 37480"
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
          "id": "78cbba5bb57db340f1e6e0e0145f53cb85fb0ea5",
          "message": "fix:ci-format",
          "timestamp": "2026-07-27T22:15:08+08:00",
          "tree_id": "375861f2a05afdf0345ab253e656718b70fdfd81",
          "url": "https://github.com/UynajGI/omnievolve/commit/78cbba5bb57db340f1e6e0e0145f53cb85fb0ea5"
        },
        "date": 1785161764487,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 1178.1643188742444,
            "unit": "iter/sec",
            "range": "stddev: 0.0002105363612743983",
            "extra": "mean: 848.7780388354628 usec\nrounds: 206"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 28317.1805272568,
            "unit": "iter/sec",
            "range": "stddev: 0.000005100558968993464",
            "extra": "mean: 35.31425026716366 usec\nrounds: 14037"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 1504.2958960873796,
            "unit": "iter/sec",
            "range": "stddev: 0.000005909322512431632",
            "extra": "mean: 664.7628319674106 usec\nrounds: 1464"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 25211.925173838317,
            "unit": "iter/sec",
            "range": "stddev: 0.0000023348823527288",
            "extra": "mean: 39.66376994636137 usec\nrounds: 16770"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 43766.093420818324,
            "unit": "iter/sec",
            "range": "stddev: 0.0000017492430336691025",
            "extra": "mean: 22.848737957597272 usec\nrounds: 29583"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 32412.221824971533,
            "unit": "iter/sec",
            "range": "stddev: 0.0000035171562596207246",
            "extra": "mean: 30.85255942650511 usec\nrounds: 8927"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 1414.6755016443713,
            "unit": "iter/sec",
            "range": "stddev: 0.000022948672489663427",
            "extra": "mean: 706.8758869702865 usec\nrounds: 637"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 2315.47168068765,
            "unit": "iter/sec",
            "range": "stddev: 0.000019063462122811914",
            "extra": "mean: 431.8774478394914 usec\nrounds: 2291"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 2009410.0473636226,
            "unit": "iter/sec",
            "range": "stddev: 5.630307426644392e-8",
            "extra": "mean: 497.65850494876133 nsec\nrounds: 91241"
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
          "id": "7e8b15eb979ba5d4e5c75d46c5e46584570e4bf2",
          "message": "fix:preserve-unlimited-compute-budget-on-resume",
          "timestamp": "2026-07-28T09:52:46+08:00",
          "tree_id": "2355ca845c7e5f015ad87bd0b79eaf946636da35",
          "url": "https://github.com/UynajGI/omnievolve/commit/7e8b15eb979ba5d4e5c75d46c5e46584570e4bf2"
        },
        "date": 1785203615641,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 196.55576418860753,
            "unit": "iter/sec",
            "range": "stddev: 0.017398776212709736",
            "extra": "mean: 5.087614724137205 msec\nrounds: 58"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 59587.22447435677,
            "unit": "iter/sec",
            "range": "stddev: 9.249725777068239e-7",
            "extra": "mean: 16.78212081232862 usec\nrounds: 20238"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 2078.1054581372164,
            "unit": "iter/sec",
            "range": "stddev: 0.000010956781819764563",
            "extra": "mean: 481.2075326034635 usec\nrounds: 2101"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 52303.7377780871,
            "unit": "iter/sec",
            "range": "stddev: 0.0000020832443577715577",
            "extra": "mean: 19.11909248709477 usec\nrounds: 29842"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 90157.87278965872,
            "unit": "iter/sec",
            "range": "stddev: 8.282143688974563e-7",
            "extra": "mean: 11.091654772434936 usec\nrounds: 50865"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 66995.47634791183,
            "unit": "iter/sec",
            "range": "stddev: 8.864797213917946e-7",
            "extra": "mean: 14.926380921704855 usec\nrounds: 9330"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 2958.808829820719,
            "unit": "iter/sec",
            "range": "stddev: 0.000008258194024982742",
            "extra": "mean: 337.9738460698701 usec\nrounds: 916"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 3860.994985019918,
            "unit": "iter/sec",
            "range": "stddev: 0.000005752816399104225",
            "extra": "mean: 259.0005954112477 usec\nrounds: 3574"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 3997149.002793861,
            "unit": "iter/sec",
            "range": "stddev: 2.7637923177354023e-8",
            "extra": "mean: 250.1783144188612 nsec\nrounds: 186986"
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
          "id": "7cf4dded6bed5b109e55032d7611cd0a0454b7a7",
          "message": "fix: make research baselines fail closed",
          "timestamp": "2026-07-28T17:11:20+08:00",
          "tree_id": "8726de542e347bc842ad109ae4c2f81dbc2467c6",
          "url": "https://github.com/UynajGI/omnievolve/commit/7cf4dded6bed5b109e55032d7611cd0a0454b7a7"
        },
        "date": 1785229957989,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 1190.1849316790588,
            "unit": "iter/sec",
            "range": "stddev: 0.0001220759045117019",
            "extra": "mean: 840.2055624996408 usec\nrounds: 224"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 29116.462056196775,
            "unit": "iter/sec",
            "range": "stddev: 0.0000044107835129181775",
            "extra": "mean: 34.344832077122945 usec\nrounds: 13798"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 1505.005775706693,
            "unit": "iter/sec",
            "range": "stddev: 0.0000053684769403292105",
            "extra": "mean: 664.4492772995761 usec\nrounds: 1511"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 24647.246321222152,
            "unit": "iter/sec",
            "range": "stddev: 0.000002262136683067607",
            "extra": "mean: 40.57248371551204 usec\nrounds: 16611"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 37006.40070387702,
            "unit": "iter/sec",
            "range": "stddev: 0.0000028069966029170285",
            "extra": "mean: 27.022352376334556 usec\nrounds: 26449"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 32500.373288437615,
            "unit": "iter/sec",
            "range": "stddev: 0.0000034641943220524925",
            "extra": "mean: 30.7688773641182 usec\nrounds: 8831"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 1403.8332876688917,
            "unit": "iter/sec",
            "range": "stddev: 0.000019179498540611697",
            "extra": "mean: 712.3352956393638 usec\nrounds: 619"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 2323.223500469164,
            "unit": "iter/sec",
            "range": "stddev: 0.00000884099274141154",
            "extra": "mean: 430.43641724442557 usec\nrounds: 2308"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 1629000.8029950298,
            "unit": "iter/sec",
            "range": "stddev: 2.373813500308214e-7",
            "extra": "mean: 613.8732394492571 nsec\nrounds: 176648"
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
          "id": "0383ae7a8b71c1a47918650039f877f1c249f282",
          "message": "fix: restrict slow-loop proposals to live genes",
          "timestamp": "2026-07-30T03:12:50+08:00",
          "tree_id": "667dffed0f827e78f7e6a2caef918f3bf1ec0cee",
          "url": "https://github.com/UynajGI/omnievolve/commit/0383ae7a8b71c1a47918650039f877f1c249f282"
        },
        "date": 1785352891533,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 1419.5143141702642,
            "unit": "iter/sec",
            "range": "stddev: 0.00009519103858931823",
            "extra": "mean: 704.4663023243418 usec\nrounds: 301"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 32415.82393721795,
            "unit": "iter/sec",
            "range": "stddev: 0.0000024249434241304586",
            "extra": "mean: 30.849131027388715 usec\nrounds: 12921"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 1333.9494235859513,
            "unit": "iter/sec",
            "range": "stddev: 0.000006714103049945755",
            "extra": "mean: 749.653609288858 usec\nrounds: 1313"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 27418.778380396925,
            "unit": "iter/sec",
            "range": "stddev: 0.0000023379823537485875",
            "extra": "mean: 36.47135500081035 usec\nrounds: 16907"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 40818.01836190906,
            "unit": "iter/sec",
            "range": "stddev: 0.0000021158578382168994",
            "extra": "mean: 24.49898452035558 usec\nrounds: 25970"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 35065.94063027405,
            "unit": "iter/sec",
            "range": "stddev: 0.000002196330285643738",
            "extra": "mean: 28.51770070974949 usec\nrounds: 8029"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 1459.2636425622943,
            "unit": "iter/sec",
            "range": "stddev: 0.00002011327802912725",
            "extra": "mean: 685.2771293911759 usec\nrounds: 541"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 2118.3837776502755,
            "unit": "iter/sec",
            "range": "stddev: 0.000007902299442580876",
            "extra": "mean: 472.05799560512406 usec\nrounds: 2048"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 1702003.6670430554,
            "unit": "iter/sec",
            "range": "stddev: 2.3833953410822604e-7",
            "extra": "mean: 587.5427999149564 nsec\nrounds: 176741"
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
          "id": "66458cb040eb061f739f35b8e2c079506dd5bef9",
          "message": "docs: sync verifier PR 1-3 into README, changelog, and QWEN.md guide\n\nCo-authored-by: Qwen-Coder <qwen-coder@alibabacloud.com>",
          "timestamp": "2026-08-01T21:25:31+08:00",
          "tree_id": "61f31ae7092670015f0b3d0b233472a154ebd970",
          "url": "https://github.com/UynajGI/omnievolve/commit/66458cb040eb061f739f35b8e2c079506dd5bef9"
        },
        "date": 1785590992686,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 1264.934878341558,
            "unit": "iter/sec",
            "range": "stddev: 0.00008993974283665121",
            "extra": "mean: 790.5545314009278 usec\nrounds: 207"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 28804.664795717497,
            "unit": "iter/sec",
            "range": "stddev: 0.000004336146298592252",
            "extra": "mean: 34.71659910267985 usec\nrounds: 13819"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 1506.3566049884982,
            "unit": "iter/sec",
            "range": "stddev: 0.0000055887264994664696",
            "extra": "mean: 663.85343064741 usec\nrounds: 1514"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 25004.016658570432,
            "unit": "iter/sec",
            "range": "stddev: 0.0000025822534594653375",
            "extra": "mean: 39.99357437866839 usec\nrounds: 17142"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 36366.11679588821,
            "unit": "iter/sec",
            "range": "stddev: 0.0000028517800188289925",
            "extra": "mean: 27.498124301054506 usec\nrounds: 25575"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 30796.207453091858,
            "unit": "iter/sec",
            "range": "stddev: 0.000004047318616044105",
            "extra": "mean: 32.47153083778836 usec\nrounds: 9858"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 1402.6589412732737,
            "unit": "iter/sec",
            "range": "stddev: 0.000016121345924338894",
            "extra": "mean: 712.9316832303103 usec\nrounds: 644"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 2313.0258807716214,
            "unit": "iter/sec",
            "range": "stddev: 0.000009140348425189346",
            "extra": "mean: 432.3341162384235 usec\nrounds: 2297"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 1925496.406010702,
            "unit": "iter/sec",
            "range": "stddev: 1.889509720910731e-7",
            "extra": "mean: 519.3465938852767 nsec\nrounds: 92422"
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
          "id": "8f070403839445b3089cf28d637cbfe519d55adf",
          "message": "fix: resolve mypy errors across src (CI lint gate)\n\nCo-authored-by: Qwen-Coder <qwen-coder@alibabacloud.com>",
          "timestamp": "2026-08-01T21:36:10+08:00",
          "tree_id": "ea0630a2268e60dc754551450c0d73eede4092c0",
          "url": "https://github.com/UynajGI/omnievolve/commit/8f070403839445b3089cf28d637cbfe519d55adf"
        },
        "date": 1785591580286,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 1098.8480152267605,
            "unit": "iter/sec",
            "range": "stddev: 0.0007052286233363105",
            "extra": "mean: 910.0439607142923 usec\nrounds: 280"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 28487.96462722156,
            "unit": "iter/sec",
            "range": "stddev: 0.000004511911159409187",
            "extra": "mean: 35.1025428838273 usec\nrounds: 13863"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 1502.8538775405757,
            "unit": "iter/sec",
            "range": "stddev: 0.000011135267872084726",
            "extra": "mean: 665.4006852858527 usec\nrounds: 1468"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 25048.36956967575,
            "unit": "iter/sec",
            "range": "stddev: 0.0000025932158330699532",
            "extra": "mean: 39.922758134750126 usec\nrounds: 16534"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 37280.14561545708,
            "unit": "iter/sec",
            "range": "stddev: 0.000002640876567942977",
            "extra": "mean: 26.82392956065548 usec\nrounds: 25994"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 31182.395802697032,
            "unit": "iter/sec",
            "range": "stddev: 0.0000042852060424307965",
            "extra": "mean: 32.06937678321394 usec\nrounds: 8692"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 1396.3432684725553,
            "unit": "iter/sec",
            "range": "stddev: 0.000019143389015752106",
            "extra": "mean: 716.1562794612023 usec\nrounds: 594"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 2307.6801920095168,
            "unit": "iter/sec",
            "range": "stddev: 0.00001481869548796676",
            "extra": "mean: 433.3356084012685 usec\nrounds: 2214"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 1944330.116566586,
            "unit": "iter/sec",
            "range": "stddev: 5.5419220414031536e-8",
            "extra": "mean: 514.3159546208437 nsec\nrounds: 90654"
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
          "id": "14b03318145a28d40b5ebfcabe08206604a64d89",
          "message": "chore: keep shell scripts LF via gitattributes\n\nCo-authored-by: Qwen-Coder <qwen-coder@alibabacloud.com>",
          "timestamp": "2026-08-01T22:18:46+08:00",
          "tree_id": "598b155265c9cd06b3426cb396e8757665efeba4",
          "url": "https://github.com/UynajGI/omnievolve/commit/14b03318145a28d40b5ebfcabe08206604a64d89"
        },
        "date": 1785594417784,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 1466.56190433759,
            "unit": "iter/sec",
            "range": "stddev: 0.00009441120572975246",
            "extra": "mean: 681.8668867930777 usec\nrounds: 106"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 36557.53949772826,
            "unit": "iter/sec",
            "range": "stddev: 0.000001936142088086156",
            "extra": "mean: 27.35413853719946 usec\nrounds: 14848"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 1336.9719507041104,
            "unit": "iter/sec",
            "range": "stddev: 0.00000689763859390395",
            "extra": "mean: 747.9588479573969 usec\nrounds: 1322"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 31118.37695228926,
            "unit": "iter/sec",
            "range": "stddev: 0.000001990663984525061",
            "extra": "mean: 32.135352095425844 usec\nrounds: 19614"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 50412.94977819368,
            "unit": "iter/sec",
            "range": "stddev: 0.0000015843155605464484",
            "extra": "mean: 19.836173134081392 usec\nrounds: 30537"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 42437.70005123376,
            "unit": "iter/sec",
            "range": "stddev: 0.0000018342601345676838",
            "extra": "mean: 23.563953720223527 usec\nrounds: 8427"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 1571.7253679093956,
            "unit": "iter/sec",
            "range": "stddev: 0.000014547968213963729",
            "extra": "mean: 636.2434687493359 usec\nrounds: 608"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 2186.533792783936,
            "unit": "iter/sec",
            "range": "stddev: 0.000007464641340056028",
            "extra": "mean: 457.344863957845 usec\nrounds: 2117"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 2178933.6924410644,
            "unit": "iter/sec",
            "range": "stddev: 4.961094784569115e-8",
            "extra": "mean: 458.94007856645595 nsec\nrounds: 98766"
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
          "id": "c3bac9ac3c3e199888bdc71bdf58e043140bc45b",
          "message": "fix: quote actionlint path only, avoid shellcheck SC2046\n\nCo-authored-by: Qwen-Coder <qwen-coder@alibabacloud.com>",
          "timestamp": "2026-08-01T22:28:11+08:00",
          "tree_id": "58f47a934f4b19e23f071d78716249c00dfd51f2",
          "url": "https://github.com/UynajGI/omnievolve/commit/c3bac9ac3c3e199888bdc71bdf58e043140bc45b"
        },
        "date": 1785594926156,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 1471.9484700320645,
            "unit": "iter/sec",
            "range": "stddev: 0.00005465780223939812",
            "extra": "mean: 679.3716086937583 usec\nrounds: 23"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 47710.47899024478,
            "unit": "iter/sec",
            "range": "stddev: 0.000001451941504835028",
            "extra": "mean: 20.95975603607893 usec\nrounds: 17396"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 1725.958634227346,
            "unit": "iter/sec",
            "range": "stddev: 0.0000061257354117183495",
            "extra": "mean: 579.3881615521259 usec\nrounds: 1727"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 39700.22270932202,
            "unit": "iter/sec",
            "range": "stddev: 0.0000014049095657445514",
            "extra": "mean: 25.188775572414855 usec\nrounds: 25643"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 65026.09175857299,
            "unit": "iter/sec",
            "range": "stddev: 0.0000010682345701993871",
            "extra": "mean: 15.378442298404943 usec\nrounds: 41160"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 53624.53730760184,
            "unit": "iter/sec",
            "range": "stddev: 0.000001520386409412297",
            "extra": "mean: 18.648179550040417 usec\nrounds: 10181"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 2028.1043075279931,
            "unit": "iter/sec",
            "range": "stddev: 0.000011727634642763146",
            "extra": "mean: 493.0712864659687 usec\nrounds: 761"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 2827.1811483763663,
            "unit": "iter/sec",
            "range": "stddev: 0.000005162403413795233",
            "extra": "mean: 353.7092062792984 usec\nrounds: 2739"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 2941977.2996666296,
            "unit": "iter/sec",
            "range": "stddev: 3.4515482886470156e-8",
            "extra": "mean: 339.9074493584009 nsec\nrounds: 144093"
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
          "id": "dc4113b51750f5f69bc82f72905c03c371af8690",
          "message": "fix: use YAML block scalar for actionlint run step\n\nCo-authored-by: Qwen-Coder <qwen-coder@alibabacloud.com>",
          "timestamp": "2026-08-01T22:31:20+08:00",
          "tree_id": "06cd8a0bdaf7770e070fc17c5e5c05cbf17eba77",
          "url": "https://github.com/UynajGI/omnievolve/commit/dc4113b51750f5f69bc82f72905c03c371af8690"
        },
        "date": 1785595121260,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 1142.7425455422776,
            "unit": "iter/sec",
            "range": "stddev: 0.00036716747948857276",
            "extra": "mean: 875.0877473678548 usec\nrounds: 95"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 34095.42604156476,
            "unit": "iter/sec",
            "range": "stddev: 0.000003825146200259195",
            "extra": "mean: 29.329447263129328 usec\nrounds: 15454"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 1504.465942845053,
            "unit": "iter/sec",
            "range": "stddev: 0.000006312361699970611",
            "extra": "mean: 664.6876951623965 usec\nrounds: 1509"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 27617.384487080344,
            "unit": "iter/sec",
            "range": "stddev: 0.0000025264762793657237",
            "extra": "mean: 36.20907694817404 usec\nrounds: 18454"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 47669.0043272107,
            "unit": "iter/sec",
            "range": "stddev: 0.0000017142989798840346",
            "extra": "mean: 20.977992179903246 usec\nrounds: 30562"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 38745.102817516425,
            "unit": "iter/sec",
            "range": "stddev: 0.000003745705451005591",
            "extra": "mean: 25.809713416166392 usec\nrounds: 9697"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 1455.414026703836,
            "unit": "iter/sec",
            "range": "stddev: 0.00001778568997623985",
            "extra": "mean: 687.0897089433447 usec\nrounds: 615"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 2393.927315958132,
            "unit": "iter/sec",
            "range": "stddev: 0.000008832476680131458",
            "extra": "mean: 417.72362650023297 usec\nrounds: 2249"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 2513507.8489094395,
            "unit": "iter/sec",
            "range": "stddev: 4.7188473358186054e-8",
            "extra": "mean: 397.8503589849062 nsec\nrounds: 111149"
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
          "id": "314eef1913ce5ccea8325c88ec12c945482760f5",
          "message": "fix: treat lease expiry as <= now, robust to coarse Windows clock\n\nCo-authored-by: Qwen-Coder <qwen-coder@alibabacloud.com>",
          "timestamp": "2026-08-01T22:54:19+08:00",
          "tree_id": "4a406a527570a35681cb894f2eaf32201683f02f",
          "url": "https://github.com/UynajGI/omnievolve/commit/314eef1913ce5ccea8325c88ec12c945482760f5"
        },
        "date": 1785596551039,
        "tool": "pytest",
        "benches": [
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_store_throughput",
            "value": 1137.1891957248838,
            "unit": "iter/sec",
            "range": "stddev: 0.00020636074130271945",
            "extra": "mean: 879.3611509495264 usec\nrounds: 106"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_load_throughput",
            "value": 33662.30119367686,
            "unit": "iter/sec",
            "range": "stddev: 0.000003934142676582061",
            "extra": "mean: 29.70682230684337 usec\nrounds: 14525"
          },
          {
            "name": "tests/test_benchmark.py::TestArtifactStorePerformance::test_sha256_throughput",
            "value": 1505.0135552322672,
            "unit": "iter/sec",
            "range": "stddev: 0.0000060505858695156055",
            "extra": "mean: 664.4458427124738 usec\nrounds: 1475"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_select_throughput",
            "value": 28028.497661419624,
            "unit": "iter/sec",
            "range": "stddev: 0.0000023192516327362773",
            "extra": "mean: 35.67797361385051 usec\nrounds: 19442"
          },
          {
            "name": "tests/test_benchmark.py::TestMCTSPerformance::test_backpropagate_throughput",
            "value": 46398.108943252024,
            "unit": "iter/sec",
            "range": "stddev: 0.00000164458178654592",
            "extra": "mean: 21.552602525742298 usec\nrounds: 30646"
          },
          {
            "name": "tests/test_benchmark.py::TestNoveltyGatePerformance::test_ast_signature_throughput",
            "value": 38787.93845036346,
            "unit": "iter/sec",
            "range": "stddev: 0.0000035099925932680224",
            "extra": "mean: 25.78121034402718 usec\nrounds: 9513"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_numpy_query_throughput",
            "value": 1459.4015781529731,
            "unit": "iter/sec",
            "range": "stddev: 0.00001859135296777143",
            "extra": "mean: 685.2123603056574 usec\nrounds: 655"
          },
          {
            "name": "tests/test_benchmark.py::TestVectorPerformance::test_zvec_upsert_throughput",
            "value": 2386.079596846118,
            "unit": "iter/sec",
            "range": "stddev: 0.000007741291438525505",
            "extra": "mean: 419.0975025819692 usec\nrounds: 2324"
          },
          {
            "name": "tests/test_benchmark.py::TestProfilerOverhead::test_profiler_disabled_overhead",
            "value": 2558639.012178568,
            "unit": "iter/sec",
            "range": "stddev: 4.6579102064756737e-8",
            "extra": "mean: 390.8327807245244 nsec\nrounds: 113161"
          }
        ]
      }
    ]
  }
}