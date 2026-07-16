"""OCR 백엔드 선택 — OCR_BACKEND env로 구현체 결정(챗봇 get_generator 패턴).

현재: vision만(팀장 결정). tesseract/vision_first(FallbackOcrBackend)는 향후 자리.
"""
from __future__ import annotations

from app.config import settings
from app.pipeline.backend.base import OcrBackend


def get_ocr_backend() -> OcrBackend:
    if settings.ocr_backend == "vision":
        from app.pipeline.backend.vision import VisionBackend
        return VisionBackend(settings.gemini_api_key, settings.gemini_model,
                             settings.gemini_timeout_s, settings.image_max_side)
    # 향후: "tesseract" / "vision_first"(FallbackOcrBackend([Vision, Tesseract])) — docs §4
    raise ValueError(f"OCR_BACKEND={settings.ocr_backend!r} 미지원 (현재 vision만)")
