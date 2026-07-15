# 재료 NER — 약지도 라벨링 파이프라인 (초안)

> CRF 재료 NER(`ai-spec.md §1`)의 **학습 데이터 자동 라벨링** 초안. AI 담당(건우) 소유.
> 저장 정책 = **모델 X**(`prd/ner-requirements-to-data.md §2.3`): 스냅샷·라벨·모델은 AI-side 아티팩트(git→추후 S3). PG는 1회 스냅샷만 읽고 오프라인 학습.

---

## 문제

CRF는 "문장 어디가 재료명인지"(span)를 학습하는데, 사람이 라벨링한 데이터가 0건이다. 대신 **약지도(weak supervision)**: EPIS gold 재료명(정형)을 **사전**으로 삼아 COOKRCP01 자유텍스트에 자동 매칭해 1차 라벨을 만든다.

- 사전(gold): EPIS `ingredient_name`(정형 재료명, ner_status=LABELED)
- 타깃(라벨 대상): COOKRCP01 `ingredient_raw`(자유텍스트, ner_status=RAW)
- 10K(만개)는 TDM 옵트아웃이라 **학습 제외**(`source != '10K'`).

## 파이프라인

```
① export_corpus.py  PG 1회 스냅샷 → data/corpus.jsonl(타깃) + data/dict.txt(사전)
② weak_label.py     사전 정제 + 최장·비겹침 문자매칭 → data/labeled.jsonl (문자단위 BIO)
③ (후속) train_crf  sklearn-crfsuite 학습 → 모델 아티팩트(git)
④ (후속) 챗봇 연동   CrfSpanExtractor 구현 → services/chat EXTRACTOR_BACKEND=ner
```

## 실행

```bash
pip install -r requirements.txt          # export만 psycopg 필요 (라벨링은 순수 파이썬)
python export_corpus.py                  # 레포 루트 .env의 PG* 사용
python weak_label.py
```

## 실측 결과 (2026-07-15, 실데이터)

| 지표 | 값 |
|---|---|
| 타깃 텍스트 | 1,143 (COOKRCP01 RAW) |
| 사전(정제 후) | 676 (EPIS gold, `[섹션]` 접두 제거·≥2자) |
| 생성 span | 11,798 |
| span≥1 텍스트 | **1,141 / 1,143 = 99.8%** |
| 평균 span/텍스트 | 10.3 |
| train / test (결정적 20%) | 897 / 246 |

예: `연근 20g, 고구마 20g, 감자 20g, 당근 20g, 소금적당량` → `[연근·고구마·감자·당근·소금]` ✅

## ⚠️ 알려진 한계 (HITL 보정 전제 — 약지도라 노이즈 있음)

1. **1자 재료 누락**: `잣·팥·물·파`는 오탐 방지로 `_MIN_LEN=2` 필터에 걸려 미라벨. → 화이트리스트로 선별 복원 필요.
2. **사전 recall 갭**: EPIS 사전에 없는 재료는 0매칭(예: `백미·크렌베리·귀리`). → item_master alias로 사전 증강 검토(단, 육류 뭉갬 이슈=PR #54와 별개로 span 탐지에만 사용).
3. **부분 매칭**: `돼지고기살코기` → `돼지고기`만(살코기 누락). CRF가 문맥으로 보정 기대.
4. **섹션어 오탐**: `[시럽]` 같은 섹션 라벨이 재료로 잡히는 경우 소수.

→ CRF 학습 전 **샘플 수십 건 육안 검수 + HITL 보정**이 전제(`ner-training-data-spec §0`).

## 다음 단계

1. 샘플 검수로 라벨 품질 확인 → 사전 화이트리스트/증강으로 recall·noise 조정
2. `train_crf.py`: 문자 n-gram·위치·사전멤버십 피처 + sklearn-crfsuite 학습, span F1 ≥ 0.85 목표(`ai-spec.md §1`)
3. `CrfSpanExtractor`(services/chat `span_extractor/ner.py`) 구현 → `EXTRACTOR_BACKEND=ner` 스왑
4. 형태소 단위(현재 문자 단위) 검토 — nori 등, 정확도 여지

## 산출물·저장

- `data/`(코퍼스·라벨)는 재생성 가능이라 **git 미포함**(`.gitignore`). 검수·확정된 최종 코퍼스와 학습 모델은 추후 git 아티팩트로 커밋(모델 X).
