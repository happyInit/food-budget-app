#!/usr/bin/env python3
"""OCR 모델 드리프트 카나리 — "운영 config 가 여전히 수용되는가"만 본다.

**왜 필요한가.** `-latest` 별칭 드리프트로 `thinking_config` 가 거부돼 OCR 이 전량 400 실패한
사고가 있었다(PR #272). 그래서 팀 규칙은 **모델 버전 핀**인데, Vertex AI 는 서빙 빌드를
`version=default` 로만 알려줘 **핀을 강제할 수단이 없다**(`docs/ai-verification-backlog.md` §1.11).

    api_key  version = 3.5-flash-lite-07-2026     ← 날짜 빌드 노출
    vertex   version = default                    ← 가려짐

날짜 접미 모델 ID(`...-07-2026`·`-001`·`@07-2026`)는 Vertex 에서 전부 404 라 실측으로 배제됐다.
남은 방어는 **드리프트를 사후에라도 빨리 아는 것** 뿐이다.

**무엇을 검사하지 않는가 — 이게 설계의 핵심이다.**
출력을 스냅샷과 비교하는 카나리는 **오탐만 낸다.** temperature=0 이어도 결과가 실행마다
흔들린다는 것을 실측했다(같은 영수증 8회에 품목 수·가격이 갈렸다 — 계획서 §4.7). 서빙이
동적 배칭이라 배치 구성에 따라 부동소수점 리덕션 순서가 바뀌고, 근소한 확률차에서 argmax 가
뒤집히기 때문이다. 따라서 **품목·금액은 판정 근거로 쓰지 않는다.**

대신 **결정적인 것만** 본다:
  1. 운영 config(`system_instruction`+`response_mime_type`+`temperature`+`thinking_config`)가
     그대로 **수용되는가** — 거부되면 그게 PR #272 의 실제 양상이다.
  2. 응답이 **JSON 으로 파싱되는가** — `response_mime_type` 이 무시되기 시작하면 여기서 걸린다.

⚠️ `VisionBackend.parse()` 를 쓰지 않는 이유: 거기엔 "thinking 거부되면 빼고 재시도" 폴백이
있어 **거부를 삼켜버린다**(서비스는 살지만 카나리는 눈이 먼다). 그래서 실제 운영 객체의
`_config()`·`_client`·`_model` 을 그대로 재사용하되 호출만 직접 한다 — 설정을 복붙하지 않으므로
누가 `vision.py` 를 고치면 카나리도 자동으로 따라간다.

**영수증 이미지는 합성한다.** 실물 영수증에는 카드번호·매장 주소가 찍혀 있어 레포에 넣을 수
없다. 합성 이미지로도 "config 수용 여부"는 동일하게 측정된다 — 판정 근거가 인식 품질이 아니기
때문이다.

    사용:  python -m app.config_canary                  ← ocr 이미지 안에서(/app)
           python -m app.config_canary --backend vertex
    종료:  0=정상 · 1=드리프트 감지(운영 config 거부) · 2=설정/환경 오류

주 1회 크론 권장. 1회 호출이라 비용은 사실상 0(≈0.5원).

⚠️ **왜 `services/ocr/app/` 에 있나** — 처음 `pipelines/monitor/` 에 뒀는데 그 위치로는 **운영에서
실행이 불가능하다.** 파이프라인 이미지(`mp-data-pipeline`)는 `pipelines/`·`crawler/`·`ml/chat-insights/`
만 COPY 하고 **`services/` 를 담지 않는다**(실측: 라이브 파드에 `/app/services` 없음). 카나리는
`app.config`·`app.pipeline.backend.vision` 을 임포트하므로 **ocr 이미지에 함께 실려야** 한다.
검사 대상과 같은 이미지에 있는 것이 맞기도 하다 — 운영이 쓰는 그 코드로 검사해야 의미가 있다.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json

_LINES = [
    "        영     수     증",
    "  카나리마트 테스트점",
    "------------------------------",
    " 1 양파                 2,000",
    " 1 우유                 3,500",
    "------------------------------",
    " 합  계                 5,500",
]


def _synth_receipt() -> bytes:
    """합성 영수증 PNG. 고정 텍스트라 매 실행 동일한 입력이 보장된다."""
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (420, 260), "white")
    d = ImageDraw.Draw(im)
    for i, line in enumerate(_LINES):
        d.text((16, 16 + i * 32), line, fill="black")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


async def _probe(backend_name: str) -> tuple[bool, str]:
    """운영 config 를 그대로 태워 수용 여부만 판정. (정상?, 메시지)"""
    from google.genai import types

    from app.config import settings
    from app.pipeline.backend.factory import get_ocr_backend
    from app.pipeline.backend.vision import VisionBackend

    # `--backend` 오버라이드는 운영 설정을 잠시 덮어쓴다. 1회성 CLI 프로세스라 안전하고,
    # 이렇게 해야 아래 팩토리가 **운영과 같은 경로로** 그 백엔드를 만든다.
    if backend_name:
        settings.genai_backend = backend_name
    kind = settings.genai_backend
    # 🔴 운영과 **같은 팩토리**로 만든다. 인자를 여기서 나열하면 반드시 갈라진다 —
    #    실제로 2026-08-03 에 두 번 갈라졌다:
    #      ① gcp_sa_key_json 누락 → make_client 가 조용히 ADC 폴백 → K8s 엔 ADC 가 없어
    #         DefaultCredentialsError → 그게 API 호출 try 에 잡혀 **"드리프트 감지"로 오보**됐다.
    #      ② gemini_timeout_s·image_max_side 를 안 넘겨 VisionBackend 기본값(60s·1600)이 쓰였다
    #         = 운영과 **다른 조건**으로 검사하고 있었다(아무도 몰랐다).
    #    팩토리를 쓰면 운영에 인자가 늘어도 카나리가 자동으로 따라간다.
    #
    # 🔴 이 호출은 try **밖**이다 — 설정·자격증명 오류는 여기서 터져야 main() 의
    #    exit 2(설정/환경)로 간다. try 안이면 exit 1(드리프트)로 오보된다(위 ①이 그랬다).
    be = get_ocr_backend()
    if not isinstance(be, VisionBackend):
        return False, f"OCR_BACKEND={settings.ocr_backend!r} — 이 카나리는 vision 백엔드 전용이다"
    # 운영과 **같은** config 객체 — 복붙이 아니라 재사용.
    cfg = be._config(types, with_thinking=True)  # noqa: SLF001
    image = _synth_receipt()
    contents = [types.Part.from_bytes(data=image, mime_type="image/png"),
                "이 영수증을 스키마대로 파싱해줘."]
    try:
        resp = await be._client.aio.models.generate_content(  # noqa: SLF001
            model=be._model, contents=contents, config=cfg)  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        # 폴백이 없으므로 거부가 그대로 드러난다 — 이것이 PR #272 의 양상이다.
        return False, f"운영 config 거부됨 (model={be._model} backend={kind}): {exc}"
    try:
        json.loads(resp.text or "")
    except (json.JSONDecodeError, TypeError):
        return False, f"JSON 아님 — response_mime_type 무시 의심: {(resp.text or '')[:120]!r}"
    return True, f"정상 (model={be._model} backend={kind})"


def main() -> int:
    ap = argparse.ArgumentParser(description="OCR 운영 config 수용 여부 카나리")
    ap.add_argument("--backend", default="", choices=["", "api_key", "vertex"],
                    help="미지정 시 설정값(GENAI_BACKEND) 사용")
    args = ap.parse_args()
    try:
        ok, msg = asyncio.run(_probe(args.backend))
    except Exception as exc:  # noqa: BLE001  — 설정·자격증명 문제는 드리프트와 구분한다
        print(f"⚠️  카나리 실행 불가(설정/환경): {exc}")
        return 2
    print(("✅ " if ok else "🔴 드리프트 감지 — ") + msg)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
