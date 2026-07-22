"""MetricValue 类型测试."""

from omnievolve.utils.metric import MetricValue, WorstMetricValue


class TestMetricValueComparison:
    def test_maximize_higher_is_better(self):
        a = MetricValue(0.9, maximize=True)
        b = MetricValue(0.8, maximize=True)
        assert a > b

    def test_maximize_lower_is_worse(self):
        a = MetricValue(0.8, maximize=True)
        b = MetricValue(0.9, maximize=True)
        assert not (a > b)

    def test_minimize_lower_is_better(self):
        a = MetricValue(0.1, maximize=False)
        b = MetricValue(0.2, maximize=False)
        assert a > b

    def test_minimize_higher_is_worse(self):
        a = MetricValue(0.2, maximize=False)
        b = MetricValue(0.1, maximize=False)
        assert not (a > b)

    def test_equal_values(self):
        a = MetricValue(0.5, maximize=True)
        b = MetricValue(0.5, maximize=True)
        assert a == b
        assert not (a > b)
        assert not (b > a)


class TestWorstMetricValue:
    def test_worst_is_worse_than_any(self):
        worst = WorstMetricValue()
        good = MetricValue(0.5, maximize=True)
        assert good > worst
        assert not (worst > good)
        assert worst.is_worst

    def test_worst_none_value(self):
        worst = WorstMetricValue()
        assert worst.value is None


class TestMetricValueEdgeCases:
    def test_none_value_is_worst(self):
        m = MetricValue(None, maximize=True)
        assert m.is_worst

    def test_none_vs_none(self):
        a = MetricValue(None, maximize=True)
        b = MetricValue(None, maximize=True)
        assert not (a > b)

    def test_string_representation(self):
        assert "↑" in str(MetricValue(0.5, maximize=True))
        assert "↓" in str(MetricValue(0.5, maximize=False))
