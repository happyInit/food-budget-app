"""재료 표면형 정규화 — 철자·외래어 변형을 item_master가 아는 표준철자로 前처리.

matcher(gazetteer)는 suffix/prefix로 형태변화(백다다기오이→오이)는 잡지만, **문자 자체가
다른 철자변형**(요구르트 vs 요거트)은 못 잡는다. 이 층이 그 갭만 메운다 — item_master를
바꾸지 않는 **AI 소유 읽기전용 색인**(정규화 인덱스). extract에서 matcher 호출 직전 前처리.

성능: 런타임은 정규식 몇 개 + dict 룩업뿐(<1ms, 네트워크·LLM 없음). 똑똑한 일(후보생성)은
전부 오프라인 빌더(tools/build_alias.py)로 밀어 사용자 응답속도 무영향.

2계층:
- Tier1 생산적 규칙(_RULES): "요구르트→요거트"처럼 규칙 1개가 다수 복합어를 커버. 코드.
- Tier2 alias 테이블(data/aliases.json): 규칙으로 못 잡는 일회성 변형. 빌더가 후보 → head 검토 확정.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.config import settings

# Tier1 생산적 철자·외래어 규칙 (변형패턴 → 표준철자).
# ⚠️ 방향(→ 오른쪽)은 item_master 실제 canonical에 맞춰야 함 — tools/build_alias.py가 스냅샷으로 검증.
#    아래는 시드. 빌더 검토로 확정/추가한다(임의 확장 금지, 오정규화 위험).
_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile("요구르트"), "요거트"),
]

_DEFAULT_ALIAS = Path(__file__).resolve().parent.parent / "data" / "aliases.json"


class SpanNormalizer:
    def __init__(self, alias_path: str | Path | None = None):
        path = Path(alias_path) if alias_path else _DEFAULT_ALIAS
        raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        # '_' 시작 키(주석) 제외, 키는 공백제거로 정규화
        self._alias = {k.replace(" ", ""): v for k, v in raw.items() if not k.startswith("_")}

    def normalize(self, surface: str) -> str:
        s = (surface or "").strip()
        if not s:
            return s
        for pat, repl in _RULES:          # Tier1 생산적 규칙
            s = pat.sub(repl, s)
        return self._alias.get(s.replace(" ", ""), s)   # Tier2 일회성 변형(공백무시 키)


_singleton: SpanNormalizer | None = None


def get_normalizer() -> SpanNormalizer:
    """프로세스 1회 로드(정적 테이블). extract에서 재사용."""
    global _singleton
    if _singleton is None:
        _singleton = SpanNormalizer(settings.alias_path or None)
    return _singleton
