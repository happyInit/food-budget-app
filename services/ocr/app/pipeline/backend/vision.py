"""VisionBackend — Gemini Vision 단독 OCR(팀장 결정 2026-07-16).

이미지 1장을 Gemini 멀티모달에 넣어 매장·합계·품목을 **구조화 JSON**으로 한 번에 받는다
(탐지+인식+레이아웃을 모델이 처리 → 좌표 파서 불필요). 근거 없는 값은 null, 날조 금지.

⚠️ 유료 API(AGENTS.md 유료예외 — 팀 재승인 문서화 대상). GEMINI_API_KEY 필요.
⚠️ 프롬프트·모델은 실물 영수증 PoC로 튜닝 전제(`ai-spec.md §7`).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.pipeline.backend.base import ParsedItem, ParsedReceipt

_SYSTEM = (
    "너는 한국 마트/편의점 영수증 파서다. 주어진 영수증 이미지에서 정보를 추출해 "
    "아래 JSON 스키마로만 답하라. 설명·마크다운 없이 JSON 객체 하나만 출력한다.\n"
    "{\n"
    '  "store": 매장명 문자열 또는 null,\n'
    '  "purchased_at": "YYYY-MM-DD HH:MM:SS" 또는 null,\n'
    '  "total_amount": 합계 금액 숫자 또는 null,\n'
    '  "items": [\n'
    '    {"raw_text": 영수증 원문 라인, "name": 품목명(정리), "quantity": 수량/단위 또는 null,\n'
    '     "price": 금액 숫자, "is_food": 식재료면 true·봉투/할인/포인트/결제수단이면 false}\n'
    "  ]\n"
    "}\n"
    "가격 정렬(중요): 각 품목의 price는 **그 품목과 같은 줄**에 적힌 금액이다. 가격을 위/아래 줄로 옮기지 마라. "
    "할인·쿠폰·행사차감은 **음수 price**로, name엔 그 할인 명칭(예 '웹쿠폰할인')을 넣어 **별도 항목**으로 둔다"
    "(식품 품목에 음수를 붙이지 마라). 할인·쿠폰은 is_food=false.\n"
    "규칙: 근거 없는 값은 null. 금액·품목을 지어내지 마라. 읽을 수 없으면 raw_text만 채우고 나머지는 null."
)
_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_FALSE_STR = {"false", "0", "no", "n", "f", ""}


def _mime(image: bytes) -> str:
    return "image/png" if image[:8] == _PNG_SIG else "image/jpeg"


def _downscale(image: bytes, max_side: int) -> bytes:
    """큰 사진 축소 — 업로드·처리시간·비용↓(영수증 텍스트는 ~1600px면 충분). PIL 없으면 원본 유지."""
    try:
        import io

        from PIL import Image
    except ImportError:
        return image
    try:
        im = Image.open(io.BytesIO(image))
        im.load()
    except Exception:  # noqa: BLE001 — 열기 실패 시 원본 그대로 모델에 맡김
        return image
    if max(im.size) <= max_side:
        return image
    ratio = max_side / max(im.size)
    im = im.convert("RGB").resize((round(im.width * ratio), round(im.height * ratio)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue()


_TRANSIENT = ("503", "429", "500", "unavailable", "overloaded", "high demand", "try again", "rate limit")


def _is_transient(exc: Exception) -> bool:
    # 일시적 서버측 오류(과부하·레이트리밋) — 재시도로 회복 가능. 타임아웃(빈 str)은 여기 안 걸림.
    s = str(exc).lower()
    return any(t in s for t in _TRANSIENT)


def _to_bool(v, default: bool = True) -> bool:
    # 모델이 불린을 문자열('false')로 줄 수 있어 방어 — bool('false')=True 오판 방지.
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() not in _FALSE_STR
    if v is None:
        return default
    return bool(v)


def _str_or_none(v) -> str | None:
    # 모델이 수량·이름을 숫자로 줄 수 있어 str 강제(Pydantic str 검증 실패 방지).
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _dec(v) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _dt(v) -> datetime | None:
    if not v:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(v).strip(), fmt)
        except ValueError:
            continue
    return None


def _to_receipt(data: dict, backend: str) -> ParsedReceipt:
    items = []
    for it in data.get("items") or []:
        if not isinstance(it, dict):
            continue
        items.append(ParsedItem(
            raw_text=_str_or_none(it.get("raw_text")) or "",
            name=_str_or_none(it.get("name")),
            quantity=_str_or_none(it.get("quantity")),
            price=_dec(it.get("price")),
            is_food=_to_bool(it.get("is_food", True)),
        ))
    return ParsedReceipt(
        items=items,
        store=_str_or_none(data.get("store")),
        purchased_at=_dt(data.get("purchased_at")),
        total_amount=_dec(data.get("total_amount")),
        backend=backend,
    )


class VisionBackend:
    name = "vision"

    def __init__(self, api_key: str, model: str, timeout_s: float = 60.0, max_side: int = 1600):
        from google import genai  # 지연 import — 백엔드 미사용 시 의존성 불필요
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY 없음 — .env 확인 (OCR_BACKEND=vision 필수)")
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._timeout = timeout_s
        self._max_side = max_side

    async def parse(self, image: bytes) -> ParsedReceipt:
        from google.genai import types  # 지연 import — 백엔드 미사용 시 google-genai 불필요
        image = _downscale(image, self._max_side)   # 큰 사진 축소(속도·비용↓)
        contents = [
            types.Part.from_bytes(data=image, mime_type=_mime(image)),
            "이 영수증을 스키마대로 파싱해줘.",
        ]
        cfg = types.GenerateContentConfig(
            system_instruction=_SYSTEM, response_mime_type="application/json", temperature=0.0,
            # OCR은 인식·추출 작업(추론 불필요) → thinking 끄면 비용 ~63%↓·지연↓·정확도 동일(실측).
            thinking_config=types.ThinkingConfig(thinking_budget=0))
        resp = None
        for attempt in range(3):                    # 최대 3회(2회 재시도) — 503/429 일시 과부하 대응
            try:
                resp = await asyncio.wait_for(
                    self._client.aio.models.generate_content(
                        model=self._model, contents=contents, config=cfg),
                    timeout=self._timeout,
                )
                break
            except Exception as exc:  # noqa: BLE001
                if attempt < 2 and _is_transient(exc):
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise
        try:
            data = json.loads(resp.text or "{}")
        except json.JSONDecodeError:
            data = {}
        return _to_receipt(data, backend=self.name)
