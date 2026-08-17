"""`mp-ai-ocr-api` 의 Lambda 진입점 — 영수증 **접수**와 결과 **폴링**.

`video-api` 와 같은 형태다(접수는 모델을 안 부른다). 다른 것은 **입력이 URL 이 아니라 이미지**
라는 점 하나인데, 그 하나가 설계를 가른다.

━━ 🔴 G-06 이 왜 «미결» 인지 — 숫자로 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    ALB → Lambda 요청 본문 상한 = **1 MB** (AWS 공식 문서 "Limits", 2026-08-17 확인)
    OCR 업로드 상한(`settings.max_image_bytes`) = **8 MB**
    휴대폰 영수증 사진 실측 통상 = **2 ~ 5 MB**

즉 **현행 `POST /api/pantry/ocr` 를 그대로 Lambda 에 붙이면 대부분의 사진이 못 올라간다.**
ALB 가 함수를 부르기도 전에 413 으로 끊는다. 파드(Istio/Envoy)에서는 안 나던 문제다.
🔴 이건 «튜닝하면 되는 값» 이 아니다 — ALB-Lambda 통합의 고정 상한이라 올릴 수 없다.

그래서 **경로를 하나 더 둔다**. 결정권은 팀장(G-06)에 있으므로 **둘 다 열어 두고**,
어느 쪽으로 정해지든 **워커와 폴링은 안 바뀌게** 만든다.

  ① 큰 사진 (권장·기본)   POST /api/pantry/ocr/upload-url  → presigned PUT URL
                          브라우저가 **S3 로 직접** 올린다 (ALB 를 안 지난다 → 상한 없음)
                          POST /api/pantry/ocr  {"job_id": "..."}   → 접수
  ② 작은 사진 (호환)      POST /api/pantry/ocr  <이미지 바이트>      → 접수
                          1 MB 이하일 때만 성립한다. 프론트 변경 없이 도는 경로다.

둘 다 **끝은 같다** — 이미지는 S3 에 있고, 큐에는 `{job_id, bucket, key}` 만 흐른다.
🔵 SQS 본문에 이미지를 못 싣는 이유도 같은 축이다(SQS 상한 256KB < 사진).

━━ 폴링 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    GET /api/pantry/ocr/{job_id}   → 200 상태 (현행 라우트·응답 모양 그대로)

🔴 잡 키는 `ocr:job:{}` — `services/ocr/app/store.py` 의 것과 **같은 키**다(`JOB_NS=ocr`).
   이관 도중 접수는 파드가 받고 폴링은 Lambda 가 받는 국면이 실제로 생기는데, 키가 갈리면
   그때 **잡을 못 찾는다.**
"""
from __future__ import annotations

import base64
import os
import sys
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve()
if str(_HERE.parents[1]) not in sys.path:
    sys.path.insert(0, str(_HERE.parents[1]))

from common import alb, jobs                       # noqa: E402
from common.runtime import log_start, logger       # noqa: E402

FUNCTION = "mp-ai-ocr-api"
log = logger(FUNCTION)

# 🔴 **`JOB_NS=ocr` 를 안 걸면 조용히 video 키에 쓴다.** 기본값이 "video" 라서다.
#    그러면 폴링은 `ocr:job:*` 를 보는 파드와 어긋나 «잡을 못 찾음» 이 되는데, 에러가
#    아니라 404 로 보여서 원인을 한참 못 찾는다. INIT 에서 즉시 터뜨린다.
if jobs.NS != "ocr":
    raise RuntimeError(f"JOB_NS 가 {jobs.NS!r} 이다 — OCR 함수는 'ocr' 이어야 한다")

QUEUE_URL = os.environ.get("OCR_JOBS_QUEUE_URL", "")
BUCKET = os.environ.get("OCR_UPLOAD_BUCKET", "")
PREFIX = os.environ.get("OCR_UPLOAD_PREFIX", "receipts")

# 🔴 ALB 상한(1MB)보다 **낮게** 잡는다. base64 로 오는 경우 원본의 4/3 배가 되므로
#    "본문 1MB" 는 원본 약 768KB 다. 여유를 두고 700KB 로 자른다 — 여기서 막지 않으면
#    ALB 가 대신 막는데 그쪽 413 은 우리 문구가 아니라 **원인을 알 수 없는 에러**로 보인다.
INLINE_MAX_BYTES = int(os.environ.get("OCR_INLINE_MAX_BYTES", str(700 * 1024)))
PRESIGN_TTL_S = int(os.environ.get("OCR_PRESIGN_TTL_S", "300"))

_s3 = None


def s3():
    global _s3
    if _s3 is None:
        import boto3                               # 런타임 제공 — 번들에 안 넣는다

        _s3 = boto3.client("s3")
    return _s3


def _object_key(job_id: str) -> str:
    return f"{PREFIX.strip('/')}/{job_id}"


def _upload_url(event: dict) -> dict:
    """①의 앞단 — 브라우저가 **S3 로 직접** 올릴 URL 을 발급한다.

    🔵 job_id 를 **여기서** 만들어 준다. 클라이언트가 짓게 하면 남의 job_id 로 덮어쓸 수 있다.
    """
    if not BUCKET:
        return alb.error(503, "업로드가 아직 준비되지 않았어요.")
    job_id = uuid.uuid4().hex
    content_type = (alb.body(event).get("content_type") or "image/jpeg").strip()
    try:
        url = s3().generate_presigned_url(
            "put_object",
            Params={"Bucket": BUCKET, "Key": _object_key(job_id), "ContentType": content_type},
            ExpiresIn=PRESIGN_TTL_S,
        )
    except Exception:                              # noqa: BLE001
        log.exception("🔴 %s presigned URL 발급 실패", FUNCTION)
        return alb.error(503, "잠시 후 다시 시도해 주세요.")
    return alb.reply(200, {"job_id": job_id, "upload_url": url,
                           "content_type": content_type, "expires_in": PRESIGN_TTL_S})


def _image_bytes(event: dict) -> bytes | None:
    """②의 입력 — ALB 가 준 본문에서 이미지 바이트를 꺼낸다.

    🔴 ALB 는 **content-type 에 따라** base64 로 싸서 준다(text/*·application/json 등만 원문).
       이미지는 항상 싸여 오므로 `isBase64Encoded` 를 반드시 봐야 한다.
    """
    raw = event.get("body") or ""
    if not raw:
        return None
    if event.get("isBase64Encoded"):
        try:
            return base64.b64decode(raw)
        except Exception:                          # noqa: BLE001
            return None
    return raw.encode("utf-8", "replace")


def _submit(event: dict) -> dict:
    if not BUCKET:
        return alb.error(503, "영수증 분석이 아직 준비되지 않았어요.")

    body = alb.body(event)
    job_id = (body.get("job_id") or "").strip()

    if job_id:
        # ① presigned 로 이미 S3 에 올라간 경우. **실제로 올라왔는지 확인한다** —
        #    안 하면 «없는 객체» 를 큐에 넣고 워커가 실패해야만 유저가 알게 된다.
        try:
            s3().head_object(Bucket=BUCKET, Key=_object_key(job_id))
        except Exception:                          # noqa: BLE001
            return alb.error(400, "업로드가 완료되지 않았어요. 사진을 다시 올려 주세요.")
    else:
        # ② 인라인 바이트. 1MB 상한 때문에 작은 사진에서만 성립한다.
        data = _image_bytes(event)
        if not data:
            return alb.error(400, "빈 이미지")
        if len(data) > INLINE_MAX_BYTES:
            # 🔴 «용량 초과» 로 끝내지 않고 **다음 수단을 알려 준다.** 이 경로는 원래 좁다.
            return alb.error(413, "사진이 커요. 업로드 URL을 먼저 받아 주세요"
                                  " (POST /api/pantry/ocr/upload-url).")
        job_id = uuid.uuid4().hex
        try:
            s3().put_object(Bucket=BUCKET, Key=_object_key(job_id), Body=data)
        except Exception:                          # noqa: BLE001
            log.exception("🔴 %s S3 업로드 실패 · job=%s", FUNCTION, job_id)
            return alb.error(503, "잠시 후 다시 시도해 주세요.")

    jobs.put_job(job_id, {"status": "PENDING"})
    try:
        jobs.enqueue(QUEUE_URL, {"job_id": job_id, "bucket": BUCKET, "key": _object_key(job_id)})
    except Exception:                              # noqa: BLE001
        # 🔴 큐 전송이 실패했는데 PENDING 을 남기면 **아무도 처리하지 않는 잡**이 되고
        #    유저는 폴링만 계속한다. 정직하게 실패로 답한다(video-api 와 같은 규약).
        jobs.put_job(job_id, {"status": "FAILED", "reason": "queue_unavailable"})
        log.exception("🔴 %s 큐 전송 실패 · job=%s", FUNCTION, job_id)
        return alb.error(503, "잠시 후 다시 시도해 주세요.")

    log.info("■ %s 접수 · job=%s", FUNCTION, job_id)
    return alb.reply(202, {"job_id": job_id, "status": "PENDING"})


def _poll(job_id: str) -> dict:
    payload = jobs.get_job(job_id)
    if payload is None:
        return alb.error(404, "알 수 없는 job_id")
    return alb.reply(200, payload)


def handler(event, context):
    """ALB 가 부른다. 경로 3개를 메서드 + 꼬리 세그먼트로 가른다."""
    method, path = alb.method(event), alb.path(event)
    log_start(log, FUNCTION, {"method": method, "path": path}, context)

    tail = alb.tail_segment(path)
    if method == "POST":
        if tail == "upload-url":
            return _upload_url(event)
        return _submit(event)
    if method == "GET":
        # `/api/pantry/ocr` 로 GET 이 오면 job_id 자리가 'ocr' 다 — 폴링이 아니다.
        if not tail or tail == "ocr":
            return alb.error(400, "job_id 가 필요해요.")
        return _poll(tail)
    return alb.error(405, "지원하지 않는 메서드예요.")
