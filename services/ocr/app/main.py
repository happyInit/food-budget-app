"""OCR 서비스 — 독립 FastAPI(챗봇 services/chat과 동형). `docs/ocr-service-design.md`.

백엔드 담당은 이 서비스를 **그대로 프록시**로 붙이면 된다(챗봇처럼) — OCR 로직 재구현 불필요.
API는 `design/api-spec.md #16·17` 그대로: POST/GET /api/pantry/ocr.

⚠️ 스켈레톤: job 저장이 **인메모리**다. 프로덕션은 `ocr_receipt(_item)` PG 저장으로 교체
   (§아래 TODO 지점). HITL 확정→pantry/expense 반영은 백엔드 담당 구간.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.config import settings
from app.models import OcrAcceptedResponse, OcrItemOut, OcrStatusResponse
from app.pipeline.backend.factory import get_ocr_backend
from app.pipeline.process import process_image

_log = logging.getLogger("ocr")
state: dict = {}
# 인메모리 job 저장 — TODO(백엔드): ocr_receipt(_item) PG 저장으로 교체(스키마 §3.2)
_JOBS: dict[str, OcrStatusResponse] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    state["backend"] = get_ocr_backend()   # 시작 시 1회(Vision 클라이언트 등)
    yield


app = FastAPI(title="food-budget-app OCR service", lifespan=lifespan)

_DEMO_HTML = Path(__file__).parent / "static" / "demo.html"


@app.get("/")
async def demo() -> FileResponse:
    """시연용 영수증 업로드 UI (같은 오리진 → CORS 불필요). API만 쓰려면 /api/pantry/ocr 직접 호출."""
    return FileResponse(_DEMO_HTML)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "backend": settings.ocr_backend}


async def _run_job(job_id: str, image: bytes) -> None:
    try:
        receipt = await process_image(image, state["backend"])
        _JOBS[job_id] = OcrStatusResponse(
            status="DONE",
            store=receipt.store,
            purchased_at=receipt.purchased_at.isoformat() if receipt.purchased_at else None,
            total_amount=float(receipt.total_amount) if receipt.total_amount is not None else None,
            backend=receipt.backend,
            items=[
                OcrItemOut(
                    raw_text=it.raw_text, name=it.name, item_id=it.item_id,
                    quantity=it.quantity,
                    price=float(it.price) if it.price is not None else None,
                    is_food=it.is_food, confirmed=False,
                )
                for it in receipt.items
            ],
        )
    except Exception as exc:  # noqa: BLE001 — job 실패는 응답으로, 서비스는 유지
        # 예외를 로그에 남긴다(빈 str 예외=TimeoutError 등 진단용) + reason은 타입명 fallback.
        _log.exception("OCR job %s 실패", job_id)
        reason = str(exc) or type(exc).__name__      # TimeoutError는 str()이 빈값 → 타입명 사용
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            reason = "시간 초과 — 사진이 크거나 서버가 느려요. 다시 시도해 주세요."
        _JOBS[job_id] = OcrStatusResponse(status="FAILED", reason=reason)


async def _accept(image: UploadFile) -> OcrAcceptedResponse:
    data = await image.read()
    if not data:
        raise HTTPException(400, "빈 이미지")
    if len(data) > settings.max_image_bytes:
        raise HTTPException(413, "이미지 용량 초과")
    job_id = uuid.uuid4().hex
    _JOBS[job_id] = OcrStatusResponse(status="PENDING")
    # TODO(백엔드): BackgroundTasks/큐 + ocr_receipt PENDING row 생성. 스켈레톤은 즉시 태스크.
    asyncio.create_task(_run_job(job_id, data))
    return OcrAcceptedResponse(job_id=job_id, status="PENDING")


@app.post("/api/pantry/ocr", response_model=OcrAcceptedResponse, status_code=202)
async def upload_receipt(image: UploadFile = File(...)) -> OcrAcceptedResponse:
    return await _accept(image)


@app.get("/api/pantry/ocr/{job_id}", response_model=OcrStatusResponse)
async def get_result(job_id: str) -> OcrStatusResponse:
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "알 수 없는 job_id")
    return job
