"""DataLeakageDetector 测试."""

from omnievolve.agents.data_leakage import DataLeakageDetector, DataLeakageResult


class TestHeuristicCheck:
    def test_perfect_score_detected(self):
        detector = DataLeakageDetector()
        result = detector.check("code", "task", score=1.0, baseline_score=0.5)
        assert result.has_leakage
        assert "Perfect score" in result.reason

    def test_anomaly_multiplier_detected(self):
        detector = DataLeakageDetector(anomaly_multiplier=10.0)
        result = detector.check("code", "task", score=0.95, baseline_score=0.05)
        assert result.has_leakage
        assert "19.0x baseline" in result.reason

    def test_normal_score_passes(self):
        detector = DataLeakageDetector()
        result = detector.check("code", "task", score=0.7, baseline_score=0.5)
        assert not result.has_leakage

    def test_no_baseline_passes(self):
        detector = DataLeakageDetector()
        result = detector.check("code", "task", score=0.95, baseline_score=0.0)
        assert not result.has_leakage


class TestLLMCheck:
    def test_no_llm_skips(self):
        detector = DataLeakageDetector(llm=None)
        result = detector.check("code", "task", score=0.99, baseline_score=0.5)
        # heuristic catches it (score == 1.0 threshold not met, but > 0.95)
        # no LLM available, so heuristic result stands
        assert isinstance(result, DataLeakageResult)


class TestDataLeakageResult:
    def test_dataclass(self):
        r = DataLeakageResult(has_leakage=False, reason="", confidence="low")
        assert not r.has_leakage
        assert r.confidence == "low"
