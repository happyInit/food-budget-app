"""CRF 재료 NER — in-process 추론(A안, 구현계획 §2).

학습(ml/ingredient-ner/train_crf.py)이 만든 crf_ingredient.pkl을 프로세스 안에서 직접 로드해
자유문장 → 재료 스팬 문자열을 반환한다. 반환값은 그 뒤 extract.py에서 gazetteer matcher로
item_id 매핑되므로(=item_master가 최종 게이트), 이 클래스는 '추출'까지만 책임진다.

⚠️⚠️ **분포 주의 — 현재 모델을 채팅 EXTRACTOR_BACKEND로 쓰지 말 것(=rule 유지).**
   이 CRF는 **레시피 재료 목록**("돼지고기 120g, 양파 10g…")으로만 학습됐다(gold F1 0.924도 그 분포).
   **대화 문장**("돼지고기랑 양파로 뭐 해먹지")에 넣으면 조사·동사째 과다추출한다(train/serve 불일치).
   → 이 구현의 정당한 용도: (1) 레시피 ingredient_raw 구조화, (2) B안(/ner 마이크로서비스) 레퍼런스.
   채팅용 대화체 NER은 대화체 학습데이터 확보 후 별도 학습이 필요하다(백로그, README §다음단계).

⚠️ 피처(_char_features)·_bio_to_spans는 학습 코드와 **정확히 일치**해야 한다(불일치 시 성능 저하).
   train_crf.py의 char_features/bio_to_spans를 복제한 것 — 한쪽 수정 시 반드시 동기화.
   (B안=별도 /ner 마이크로서비스 전환 시 이 클래스 본문만 HTTP 호출로 교체, 인터페이스 동일.)
"""
from __future__ import annotations

import pickle
import re
from pathlib import Path

_HANGUL = re.compile(r"[가-힣]")
_PUNCT = set("(),[]{}·●:：/.-·⅓½¾")


def _ctype(c: str) -> str:
    if c.isdigit():
        return "d"
    if _HANGUL.match(c):
        return "h"
    if c.isspace():
        return "s"
    if c in _PUNCT:
        return "p"
    return "o"


def _char_features(text: str, i: int) -> dict:
    c = text[i]
    f = {"bias": 1.0, "c": c, "ct": _ctype(c)}
    if i > 0:
        f["-1c"], f["-1ct"] = text[i - 1], _ctype(text[i - 1])
        f["-1:0"] = text[i - 1] + c
    else:
        f["BOS"] = True
    if i < len(text) - 1:
        f["+1c"], f["+1ct"] = text[i + 1], _ctype(text[i + 1])
        f["0:+1"] = c + text[i + 1]
    else:
        f["EOS"] = True
    if i > 1:
        f["-2c"] = text[i - 2]
    if i < len(text) - 2:
        f["+2c"] = text[i + 2]
    return f


def _bio_to_spans(labels: list[str]) -> set[tuple[int, int]]:
    spans, start = set(), None
    for i, l in enumerate(labels):
        if l == "B-ING":
            if start is not None:
                spans.add((start, i))
            start = i
        elif l == "I-ING":
            if start is None:
                start = i
        else:
            if start is not None:
                spans.add((start, i))
                start = None
    if start is not None:
        spans.add((start, len(labels)))
    return spans


def _default_model_path() -> Path:
    # ner.py = services/chat/app/pipeline/span_extractor/ner.py → 레포 루트 = parents[5]
    return (Path(__file__).resolve().parents[5]
            / "ml" / "ingredient-ner" / "data" / "model" / "crf_ingredient.pkl")


class CrfSpanExtractor:
    def __init__(self, model_path: str | None = None):
        path = Path(model_path) if model_path else _default_model_path()
        if not path.exists():
            raise FileNotFoundError(
                f"CRF 모델 없음: {path} — ml/ingredient-ner에서 `python train_crf.py` 실행 후 "
                "NER_MODEL_PATH로 경로를 지정하세요(또는 기본경로에 배치). "
                "그때까지 EXTRACTOR_BACKEND=rule 로 폴백 가능."
            )
        with path.open("rb") as fh:
            self._crf = pickle.load(fh)   # sklearn_crfsuite.CRF (unpickle에 패키지 필요)

    async def extract_spans(self, text: str) -> list[str]:
        if not text:
            return []
        labels = self._crf.predict([[_char_features(text, i) for i in range(len(text))]])[0]
        out: list[str] = []
        seen: set[str] = set()
        for s, e in sorted(_bio_to_spans(labels)):
            surf = text[s:e].strip()
            if surf and surf not in seen:
                seen.add(surf)
                out.append(surf)
        return out
