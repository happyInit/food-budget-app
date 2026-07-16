"""파이프라인 로그 규격과 민감정보 제외를 검증한다."""
from __future__ import annotations

import json
import logging
import unittest

from _observability import JsonFormatter


class JsonFormatterTest(unittest.TestCase):
    def test_required_pipeline_fields_and_allowlist(self):
        record = logging.LogRecord(
            "data-pipeline.retail-refiner",
            logging.ERROR,
            __file__,
            1,
            "record processing failed",
            (),
            None,
        )
        record.event = "pipeline_record_rejected"
        record.component = "retail-refiner"
        record.topic = "retail.crawl.raw"
        record.consumer_group = "retail-refiner"
        record.error_type = "ValueError"
        record.password = "must-not-leak"
        record.payload = {"product_id": 123}

        payload = json.loads(JsonFormatter(environment="test").format(record))

        self.assertEqual(payload["service"], "data-pipeline")
        self.assertEqual(payload["event"], "pipeline_record_rejected")
        self.assertEqual(payload["component"], "retail-refiner")
        self.assertEqual(payload["topic"], "retail.crawl.raw")
        self.assertEqual(payload["error_type"], "ValueError")
        self.assertNotIn("password", payload)
        self.assertNotIn("payload", payload)


if __name__ == "__main__":
    unittest.main()
