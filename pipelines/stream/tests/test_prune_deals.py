"""외부 Redis·Prometheus 없이 deal-pruner의 성공·폴백 동작을 검증한다."""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class _Metric:
    def labels(self, *_args):
        return self

    def inc(self, *_args):
        return None

    def observe(self, *_args):
        return None

    def set(self, *_args):
        return None

    def set_to_current_time(self):
        return None


def _load_pruner(*, redis_client, pruned: int = 0, active: int = 0):
    fake_redis = types.ModuleType("_redis")
    fake_redis.ZSET_ACTIVE = "retail:deals:active"
    fake_redis.client = Mock(return_value=redis_client)
    fake_redis.prune_expired = Mock(return_value=pruned)

    fake_metrics = types.ModuleType("_metrics")
    for name in (
        "ACTIVE_DEALS",
        "DEALS_PRUNED",
        "LAST_SUCCESS",
        "PROCESSING_SECONDS",
        "RECORDS",
        "SINK_WRITES",
    ):
        setattr(fake_metrics, name, _Metric())
    fake_metrics.start_metrics_server = Mock()

    logger = Mock()
    fake_observability = types.ModuleType("_observability")
    fake_observability.get_pipeline_logger = Mock(return_value=logger)

    redis_client.zcard.return_value = active
    module_path = Path(__file__).parents[1] / "prune_deals.py"
    spec = importlib.util.spec_from_file_location("prune_deals_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {
            "_redis": fake_redis,
            "_metrics": fake_metrics,
            "_observability": fake_observability,
        },
    ):
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module, fake_redis, logger


class PruneDealsTest(unittest.TestCase):
    def test_success_keeps_pruned_count_and_emits_structured_event(self):
        redis_client = Mock()
        module, fake_redis, logger = _load_pruner(
            redis_client=redis_client,
            pruned=3,
            active=7,
        )

        self.assertEqual(module.prune_once(), 3)
        fake_redis.prune_expired.assert_called_once_with(redis_client)
        event = logger.info.call_args.kwargs["extra"]
        self.assertEqual(event["operation"], "deals.prune_expired")
        self.assertEqual(event["record_count"], 3)

    def test_redis_failure_preserves_skip_behavior_without_error_text(self):
        redis_client = Mock()
        redis_client.ping.side_effect = ConnectionError("secret endpoint detail")
        module, fake_redis, logger = _load_pruner(redis_client=redis_client)

        self.assertEqual(module.prune_once(), 0)
        fake_redis.prune_expired.assert_not_called()
        event = logger.warning.call_args.kwargs["extra"]
        self.assertEqual(event["event"], "dependency_unavailable")
        self.assertEqual(event["error_type"], "ConnectionError")
        self.assertNotIn("secret endpoint detail", str(event))


if __name__ == "__main__":
    unittest.main()
