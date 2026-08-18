"""`mp-ai-ocr-worker` 의 Lambda 진입점 — SQS 로 받은 영수증을 실제로 읽는다.

접수(`mp-ai-ocr-api`)가 넘긴 `{job_id, bucket, key}` 하나를 받아 S3 에서 이미지를 꺼내고,
`services/ocr` 의 `process_image` 를 **그대로** 써서 파싱·분류한 뒤 잡 상태를 마감한다.
분할은 **일이 도는 자리를 옮기는 것**이지 로직을 다시 짜는 것이 아니다.

🔴 **진입점이 `handler.py` 인 이유** = 번들에 `services/ocr/app` 이 `app/` 패키지로 들어간다.
   같은 자리에 `app.py` 를 두면 `import app` 이 패키지를 집어 핸들러를 못 찾는다.
   ⇒ Lambda 핸들러 문자열은 **`handler.handler`** (chat 과 같은 규칙 · `serverless/README.md`).

🔴 **분할하면서 새로 생기는 것 3건** — `video-worker` 와 같은 축이고, 한 가지가 다르다:

  ① **락이 없다. 없는 게 맞다.** video 는 «같은 URL 은 한 번만 분석» 이 성립해 URL 로 락을
     걸지만, OCR 의 입력은 **이 유저의 이 사진 한 장**이라 중복 제거할 대상이 없다.
     실제로 `services/ocr/app/store.py` 에도 잡 키 하나뿐이다.
     ⇒ `jobs.acquire()` 를 부르면 `JOB_NS=ocr` 에는 lock 계약이 없어 **즉시 터진다**(의도).

  ② **SQS 는 중복 전달이 가능하다**(표준 큐 = 최소 1회). 락이 없으니 방어는 **잡 상태**로 한다 —
     이미 DONE/FAILED 로 끝난 잡이면 모델을 부르지 않고 그대로 끝낸다. 유료 API(Gemini Vision)
     라 이 한 줄이 곧 비용이다.

  ③ **실패가 조용해진다.** 워커 실패는 재시도 뒤 DLQ 로 가는데, 그동안 잡은 `PENDING` 이라
     **유저가 영원히 기다린다.** 마지막 시도에서 반드시 `FAILED` 를 남긴다.
     🔴 마지막이 아닐 때는 **일부러 예외를 올린다** — 그래야 SQS 가 재시도한다.

🔵 **처리한 이미지는 지운다.** 영수증은 개인정보고, 파싱이 끝나면 원본을 둘 이유가 없다.
   실패했을 때는 **남긴다** — 재시도가 같은 객체를 다시 읽어야 한다. 마지막 시도까지 실패하면
   그때 지운다. (버킷 수명주기 규칙은 별건이다 — 인프라 소관.)
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# 번들 루트 = import 루트. build.sh 가 `services/ocr/app` 을 `app/` 로 통째로 넣는다.
# 레포에서 직접 돌릴 때(테스트)는 `services/ocr` 도 봐야 `app.pipeline...` 이 잡힌다.
_HERE = Path(__file__).resolve()
for _p in (_HERE.parents[1], _HERE.parents[2] / "services" / "ocr"):
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common import jobs                            # noqa: E402
from common.runtime import log_start, logger       # noqa: E402
from common.secrets import inject                  # noqa: E402

FUNCTION = "mp-ai-ocr-worker"
log = logger(FUNCTION)

# 🔴 PG(`svc_ocr`)와 Gemini 키를 이 함수가 **실제로 쓴다.** 배치 5종만 이 줄을 갖고 있었고
#    여기엔 없었다(2026-08-18 실배포에서 발견) — 그러면 접수는 202 로 통과하는데 처리만
#    조용히 실패한다. 그 조합이 제일 안 보인다(유저는 «접수됐다» 를 보고 기다린다).
# 🔵 핸들러 밖 = INIT 1회. 웜 스타트에서 다시 돌지 않는다.
inject()

# 🔴 **`JOB_NS=ocr` 를 안 걸면 조용히 video 키에 쓴다.** 기본값이 "video" 라서다.
#    그러면 폴링은 `ocr:job:*` 를 보는 파드와 어긋나 «잡을 못 찾음» 이 되는데, 에러가
#    아니라 404 로 보여서 원인을 한참 못 찾는다. INIT 에서 즉시 터뜨린다.
if jobs.NS != "ocr":
    raise RuntimeError(f"JOB_NS 가 {jobs.NS!r} 이다 — OCR 함수는 'ocr' 이어야 한다")

# 🔴 이 값은 **함수 타임아웃보다 짧아야** 한다. 길면 Lambda 가 먼저 잘리고, 그러면 ③의
#    "마지막 시도에 FAILED 를 남긴다" 가 **실행되지 않는다** — 잡이 PENDING 에 영영 남는다.
OCR_TIMEOUT_S = float(os.environ.get("OCR_TIMEOUT_S", "90"))

_s3 = None


def s3():
    global _s3
    if _s3 is None:
        import boto3                               # 런타임 제공 — 번들에 안 넣는다

        _s3 = boto3.client("s3")
    return _s3


def _done_payload(receipt) -> dict:
    """현행 `_run_job` 의 DONE 본문과 **키까지 같게** 만든다 — 프론트가 이미 이 모양을 읽는다.

    🔴 여기서 모양을 «정리» 하면 안 된다. 폴링은 이 JSON 을 그대로 돌려주므로
       필드 하나만 달라져도 프론트가 조용히 빈 값을 그린다.
    """
    return {
        "status": "DONE",
        "store": receipt.store,
        "purchased_at": receipt.purchased_at.isoformat() if receipt.purchased_at else None,
        "total_amount": float(receipt.total_amount) if receipt.total_amount is not None else None,
        "backend": receipt.backend,
        "items": [
            {
                "raw_text": it.raw_text, "name": it.name, "item_id": it.item_id,
                "quantity": it.quantity,
                "price": float(it.price) if it.price is not None else None,
                "is_food": it.is_food, "category": it.category, "storage": it.storage,
                "in_expense": it.in_expense, "needs_review": it.needs_review,
                "confirmed": False,
            }
            for it in receipt.items
        ],
    }


def _fail_reason(exc: Exception) -> str:
    """현행 `_run_job` 의 문구 규약을 그대로 옮긴다 — 유저가 읽는 문장이다."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "시간 초과 — 사진이 크거나 서버가 느려요. 다시 시도해 주세요."
    return str(exc) or type(exc).__name__


def _discard(bucket: str, key: str) -> None:
    """영수증 원본을 지운다. 실패해도 잡 처리에는 영향을 주지 않는다."""
    try:
        s3().delete_object(Bucket=bucket, Key=key)
    except Exception:                              # noqa: BLE001
        log.warning("⚠️ %s 원본 삭제 실패 · s3://%s/%s", FUNCTION, bucket, key)


def _process(body: dict) -> dict:
    job_id, bucket, key = body.get("job_id"), body.get("bucket"), body.get("key")
    if not job_id or not bucket or not key:
        # 우리가 만든 메시지가 아니다 — 재시도해도 같으므로 조용히 버린다(DLQ 로 보낼 이유 없음).
        log.warning("⚠️ %s 잘못된 메시지 · %s", FUNCTION, list(body))
        return {"skipped": "bad_message"}

    # ② 중복 전달 방어 — 이미 끝난 잡이면 유료 모델을 다시 부르지 않는다.
    existing = jobs.get_job(job_id)
    if existing and existing.get("status") in ("DONE", "FAILED"):
        log.info("■ %s 중복 전달 · 이미 %s · job=%s", FUNCTION, existing["status"], job_id)
        return {"job_id": job_id, "status": existing["status"], "duplicate": True}

    obj = s3().get_object(Bucket=bucket, Key=key)
    image = obj["Body"].read()

    # 지연 import — 여기까지 와야 무거운 것들(google-genai·psycopg)이 필요해진다.
    from app.pipeline.backend.factory import get_ocr_backend   # noqa: PLC0415
    from app.pipeline.process import process_image             # noqa: PLC0415

    async def _run():
        return await asyncio.wait_for(process_image(image, get_ocr_backend()),
                                      timeout=OCR_TIMEOUT_S)

    try:
        receipt = asyncio.run(_run())
    except Exception as exc:                       # noqa: BLE001
        # 🔴 여기서 잡아 **다시 올린다** — 상태 마감·재시도 판단은 handler 가 한다(③).
        #    그래야 "마지막 시도인가" 를 한 곳에서만 판단한다.
        log.exception("🔴 %s 파싱 실패 · job=%s", FUNCTION, job_id)
        raise

    jobs.put_job(job_id, _done_payload(receipt))
    _discard(bucket, key)                          # 개인정보 — 끝났으면 원본을 두지 않는다
    log.info("■ %s 완료 · job=%s · 품목 %d", FUNCTION, job_id, len(receipt.items))
    return {"job_id": job_id, "status": "DONE", "items": len(receipt.items)}


def handler(event, context):
    """SQS 가 부른다. 배치 크기 1 이 계약이지만 여러 건이 와도 각각 처리한다."""
    records = jobs.sqs_records(event)
    log_start(log, FUNCTION, {"records": len(records)}, context)

    results = []
    for body, received in records:
        job_id = body.get("job_id")
        try:
            results.append(_process(body))
        except Exception as exc:                   # noqa: BLE001
            last = jobs.is_last_attempt(received)
            log.exception("🔴 %s 처리 실패 · job=%s · 수신 %d회 · 마지막=%s",
                          FUNCTION, job_id, received, last)
            if last:
                # ③ 마지막 시도 — 잡을 반드시 끝낸다. 안 그러면 DLQ 로 가고 유저는 PENDING 을 본다.
                if job_id:
                    jobs.put_job(job_id, {"status": "FAILED", "reason": _fail_reason(exc)})
                if body.get("bucket") and body.get("key"):
                    _discard(body["bucket"], body["key"])   # 더 시도 안 하므로 원본을 남길 이유가 없다
                results.append({"job_id": job_id, "status": "FAILED"})
            else:
                # 🔴 아직 재시도가 남았다 — **예외를 올려야** SQS 가 다시 준다.
                #    여기서 삼키면 성공으로 간주돼 메시지가 사라지고 잡이 PENDING 에 영영 남는다.
                #    🔵 원본도 일부러 안 지운다 — 재시도가 같은 객체를 다시 읽어야 한다.
                raise

    return {"processed": len(results), "results": results}
