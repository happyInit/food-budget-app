"""임시 SpanExtractor 구현 — CRF NER 완성 전까지 사용 (구현계획 §2 참고).

gazetteer.make_matcher()는 "이미 분리된 재료명 1건"을 받는 함수라 자유 문장엔
그대로 못 쓴다. 조사/구분자 분할 + n-gram 토큰 윈도우로 후보를 만들고, 각 후보를
matcher에 통과시켜 method가 exact/suffix인 것만 채택한다(token/prefix는 자유
문장 위에서 오탐 위험이 커서 보수적으로 제외 — 정확도는 §6 수기 샘플로 검증 필요).
"""
import re

_SEP = re.compile(r"(?:이랑|랑|하고|와|과)(?=\s|$)|[,、]")
_TOKEN = re.compile(r"[가-힣A-Za-z0-9]+")
# 조사가 명사에 바로 붙는 경우(공백/구분자 없음) — "대파로" 같은 형태를 "대파"로 정규화.
# 긴 조사를 먼저 매칭해야 짧은 조사가 일부만 떼어내는 실수를 피함(예: "으로" 전체 제거, "로"만 아님).
_PARTICLE = re.compile(r"(?:에서|한테|까지|부터|보다|이랑|하고|으로|만큼|는|은|이|가|을|를|도|만|의|에|로)$")


def _strip_particle(token: str) -> str:
    stripped = _PARTICLE.sub("", token)
    return stripped if stripped else token


def _candidates(text: str) -> list[str]:
    normalized = _SEP.sub(" ", text)
    raw_tokens = _TOKEN.findall(normalized)
    stripped_tokens = [_strip_particle(t) for t in raw_tokens]

    seen: set[str] = set()
    ordered: list[str] = []

    for tokens in (raw_tokens, stripped_tokens):
        for n in (1, 2, 3):
            for i in range(len(tokens) - n + 1):
                cand = "".join(tokens[i : i + n])
                if cand and cand not in seen:
                    seen.add(cand)
                    ordered.append(cand)
    return ordered


class RuleBasedSpanExtractor:
    def __init__(self, matcher, stop: set[str], normalizer=None):
        self._matcher = matcher
        self._stop = stop
        self._normalizer = normalizer   # 철자변형 정규화(파세리→파슬리) — 매칭 전에 적용해야 유효

    def _lookup(self, cand: str):
        """후보 1건 → (정규화문자열, item_id, method). 불채택이면 None."""
        if cand in self._stop:
            return None
        # 정규화를 matcher 조회 직전에 — 변형표기는 사전 매칭 전에 표준철자로 바꿔야 잡힘
        norm = self._normalizer.normalize(cand) if self._normalizer else cand
        if norm in self._stop:
            return None
        item_id, _canonical, method = self._matcher(norm)
        if item_id is None or method not in ("exact", "suffix"):
            return None
        return norm, item_id, method

    async def extract_spans(self, text: str) -> list[str]:
        hits = [h for h in (self._lookup(c) for c in _candidates(text)) if h]

        # ⚠️ 조사가 붙은 형태가 **다른 품목**으로 접미매칭되는 오탐을 걷어낸다.
        #    실측(2026-07-29): "양파로" → 접미매칭 → item 2572 '파로'(곡물 farro).
        #    "양파로 볶음밥"이 양파 + 파로를 함께 추출해, 유저가 말한 적 없는 재료가
        #    컨텍스트에 들어간다(추천 입력을 오염시킨다).
        #    조사를 뗀 형태가 **다른 품목으로 매칭**되면 그쪽이 진짜다(조사는 명사에 붙으므로,
        #    조사째 다른 품목에 걸리는 것은 우연이다).
        by_norm = {n: i for n, i, _m in hits}
        spans: list[str] = []
        for norm, item_id, method in hits:
            if method == "suffix":
                base = _strip_particle(norm)
                if base != norm and base in by_norm and by_norm[base] != item_id:
                    continue                      # 조사 낀 접미 오탐 — 버린다
            spans.append(norm)
        return spans
