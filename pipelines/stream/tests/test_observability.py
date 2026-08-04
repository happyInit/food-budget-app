"""파이프라인 로그 규격과 민감정보 제외를 검증한다."""
from __future__ import annotations

import json
import logging
import sys
import unittest

from _observability import JsonFormatter


class SomeError(Exception):
    pass


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

    def test_newly_allowed_fields_are_serialized(self):
        record = logging.LogRecord(
            "data-pipeline.kurly", logging.ERROR, __file__, 1, "crawl failed", (), None
        )
        record.category_code = "F222"
        record.failed_categories = [{"code": "F222", "reason": "timeout"}]
        record.reason = "timeout"
        record.record_count = 3

        payload = json.loads(JsonFormatter(environment="test").format(record))

        self.assertEqual(payload["category_code"], "F222")
        # 리스트는 _json_value 가 str 로 바꾼 값 그대로 담긴다.
        self.assertEqual(payload["failed_categories"], str(record.failed_categories))
        self.assertEqual(payload["reason"], "timeout")
        self.assertEqual(payload["record_count"], 3)

    def test_error_field_is_still_excluded(self):
        record = logging.LogRecord(
            "data-pipeline.kurly", logging.ERROR, __file__, 1, "crawl failed", (), None
        )
        record.error = "repr(SomeError('secret-ish'))"

        payload = json.loads(JsonFormatter(environment="test").format(record))

        self.assertNotIn("error", payload)

    def test_exc_info_is_serialized_as_traceback(self):
        record = logging.LogRecord(
            "data-pipeline.kurly", logging.ERROR, __file__, 1, "crawl failed", (), None
        )
        try:
            raise SomeError("boom")
        except SomeError:
            record.exc_info = sys.exc_info()

        payload = json.loads(JsonFormatter(environment="test").format(record))

        self.assertIn("SomeError", payload["exception"])
        self.assertIn("Traceback", payload["exception"])

    def test_no_exception_key_when_no_exc_info(self):
        record = logging.LogRecord(
            "data-pipeline.kurly", logging.INFO, __file__, 1, "ok", (), None
        )

        payload = json.loads(JsonFormatter(environment="test").format(record))

        self.assertNotIn("exception", payload)


if __name__ == "__main__":
    unittest.main()
