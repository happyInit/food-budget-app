"""SQS 수신 루프 — 객체 1개 = 메시지 1건 (C-44).

구 Kafka 컨슈머와 **전달 단위가 다르다**:
    Kafka  메시지 1건 = 레코드 1건   · 오프셋을 COMMIT_EVERY(200)마다 커밋
    SQS    메시지 1건 = 객체 1개(= 크롤 1회분 N건) · 객체를 다 넣고 나서 메시지 삭제

그래서 재전달의 폭발 반경이 다르다 — 파드가 중간에 죽으면 그 객체를 **처음부터** 다시 읽는다.
적재 SQL 이 전부 `on conflict do nothing` 이라 재처리 자체는 무해하다(load_retail.py).

🔴 순서 계약: **DB 커밋 → 메시지 삭제.** 뒤집으면 커밋 전에 죽었을 때 그 크롤분이 통째로 사라진다
   (구 Kafka 경로의 "DB 먼저 → 오프셋" 과 같은 규칙이다).
"""
import json
import os
from urllib.parse import unquote_plus

from _s3 import client, region  # noqa: F401 — region 은 재수출(컨슈머가 로그에 찍는다)

DEFAULT_VISIBILITY_EXTENSION = 900  # 큐의 visibility_timeout_seconds 와 맞춘다 (terraform sqs.tf)


def queue_url() -> str:
    url = os.environ.get("MP_SQS_URL")
    if not url:
        raise RuntimeError("MP_SQS_URL 이 없다 — 컨슈머가 어느 큐를 볼지 정해지지 않았다")
    return url


def sqs_client():
    return client("sqs")


def _objects(body: dict):
    """S3 이벤트 알림 → (버킷, 키) 목록.

    🔴 S3 는 알림을 붙이는 순간 `s3:TestEvent` 를 한 번 보낸다. Records 가 없으므로 여기서
       빈 목록이 되고, 호출측은 그 메시지를 **정상 삭제**한다. 안 지우면 3회 재전달 뒤
       DLQ 로 들어가 "실패 1건"이 영구히 남아 알림을 오염시킨다.
    """
    out = []
    for rec in body.get("Records") or []:
        s3 = rec.get("s3") or {}
        name = (s3.get("bucket") or {}).get("name")
        key = (s3.get("object") or {}).get("key")
        if name and key:
            out.append((name, unquote_plus(key)))  # 키는 URL 인코딩돼서 온다
    return out


def consume(handle, *, log, component, url=None, idle_exit=None, should_run=lambda: True, sqs=None):
    """큐를 비울 때까지 돈다. handle(bucket, key, heartbeat) 가 정상 반환하면 메시지를 삭제한다.

    handle 이 예외를 올리면 삭제하지 않는다 → 가시성 타임아웃 뒤 재전달되고, 3회 실패하면
    큐의 redrive 정책이 DLQ 로 보낸다. (레코드 단위 영구실패는 handle 안에서 `failed/` 로
    격리하고 정상 반환하는 것이 계약이다 — 객체 하나가 통째로 DLQ 로 가면 안 된다.)

    idle_exit: 빈 수신이 이 초 수만큼 이어지면 종료(KEDA scale-to-zero 와 같이 쓴다).
    """
    sqs = sqs or sqs_client()
    url = url or queue_url()
    idle = 0.0
    handled = 0

    while should_run():
        resp = sqs.receive_message(
            QueueUrl=url,
            MaxNumberOfMessages=1,   # 객체 1개가 곧 배치다 — 한 번에 여러 개를 쥐면 가시성만 태운다
            WaitTimeSeconds=20,      # long polling
        )
        messages = resp.get("Messages") or []
        if not messages:
            idle += 20.0
            if idle_exit and idle >= idle_exit:
                log.info("sqs consumer idle exit", extra={
                    "event": "service_stopped", "component": component,
                    "result": "completed", "record_count": handled})
                break
            continue

        idle = 0.0
        for msg in messages:
            receipt = msg["ReceiptHandle"]

            def heartbeat(seconds=DEFAULT_VISIBILITY_EXTENSION, _r=receipt):
                """처리가 길어질 때 가시성을 연장한다 — 안 하면 남의 파드가 같은 객체를 또 집는다."""
                sqs.change_message_visibility(QueueUrl=url, ReceiptHandle=_r, VisibilityTimeout=seconds)

            try:
                body = json.loads(msg["Body"])
            except json.JSONDecodeError:
                log.exception("sqs message body is not json", extra={
                    "event": "pipeline_record_rejected", "component": component,
                    "error_type": "JSONDecodeError", "retryable": False})
                sqs.delete_message(QueueUrl=url, ReceiptHandle=receipt)  # 재시도해도 같은 결과다
                continue

            targets = _objects(body)
            if not targets:
                # s3:TestEvent 를 포함한 "우리가 처리할 것이 없는" 메시지
                log.info("sqs message has no s3 records — dropping", extra={
                    "event": "sqs_message_skipped", "component": component})
                sqs.delete_message(QueueUrl=url, ReceiptHandle=receipt)
                continue

            for bucket_name, key in targets:
                handle(bucket_name, key, heartbeat)   # 실패하면 예외가 그대로 올라가 삭제를 막는다
                handled += 1

            sqs.delete_message(QueueUrl=url, ReceiptHandle=receipt)   # 🔴 DB 커밋 뒤에만 여기 온다

    return handled
