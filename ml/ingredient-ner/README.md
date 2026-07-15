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
① export_corpus.py    PG 1회 스냅샷 → corpus.jsonl(타깃) + dict.txt(EPIS) + dict_item_master.txt
② weak_label.py       사전 증강+정제 + 섹션마스크 + 최장/1자경계 매칭 → labeled.jsonl (문자 BIO)
  measure_coverage.py 개선 before/after 커버리지 실측(진단용)
③ (후속) train_crf    sklearn-crfsuite 학습 → 모델 아티팩트(git)
④ (후속) 챗봇 연동     CrfSpanExtractor 구현 → services/chat EXTRACTOR_BACKEND=ner
```

## 실행

```bash
pip install -r requirements.txt          # export만 psycopg 필요 (라벨링은 순수 파이썬)
python export_corpus.py                  # 레포 루트 .env의 PG* 사용
python weak_label.py
```

## 실측: 개선 before/after (2026-07-15, 실데이터 1,143 텍스트)

초안(EPIS 사전만) → 개선(사전 증강 + 1자 화이트리스트 + 섹션 마스킹). `measure_coverage.py`:

| 지표 | before | after | Δ |
|---|---|---|---|
| 사전(다자어) | 676 | **1,381** (+item_master) | +705 |
| 고유 재료표현 | 421 | **702** | **+281 (+67%)** |
| 총 span | 11,798 | **13,387** | +1,589 |
| 평균 span/텍스트 | 10.3 | **11.7** | +1.4 |
| 재료 문자비율 | 24.9% | **28.7%** | +3.8pp |
| span≥1 텍스트 | 99.8% | 99.9% | +0.1 |
| 0건 텍스트 | 2 | 1 | −1 |

> span≥1은 이미 포화(99.8%)라 변화가 작지만, **재료를 얼마나 깊게 잡느냐(고유표현 +67%·총 span +1,589)**가 핵심 개선. train/test(결정적 20%) = 897/246.

## 해결한 한계 (초안 → 개선)

| # | 한계 | 해결방법 | 검증 |
|---|---|---|---|
| 2 | 사전 recall 갭 (`백미·크렌베리·귀리` 0매칭) | **item_master(canonical+alias) 사전 증강** — 공공데이터만, span 탐지용이라 육류 코드 이슈(#54)와 무관 | `백미 150g, 크렌베리 15g, 귀리 20g` → `[백미·크렌베리·귀리]` ✅ |
| 1 | 1자 재료 누락 (`잣·팥`) | **화이트리스트 1자어 + 토큰경계 매칭** — "팥 15g"는 잡고 "팥소"는 제외 | `잣 3g …` → 잣 ✅ · `[팥소]팥 15g` → 팥 ✅ |
| 4 | 섹션어 오탐 (`[시럽]`) | **섹션 마커(`[..]`·`●..:`) 마스킹** — 원문·오프셋 보존하며 라벨만 금지 | `… [시럽] 물엿 3g` → 시럽 제외, 물엿만 ✅ |
| 3 | 부분 매칭 (`돼지고기살코기`→`돼지고기`) | 사전 증강으로 일부 완화. 잔여는 CRF 문맥 보정 기대 | 낮은 우선순위 |

**여전히 약지도** — 자동 라벨이라 잔여 노이즈 있음. CRF 학습 전 **샘플 육안 검수 + HITL 보정** 전제(`ner-training-data-spec §0`). 사전에 없는 완전 신규 재료는 후속 **자기학습(부트스트래핑)**으로 확장.

## 다음 단계

1. 샘플 검수로 라벨 품질 확인 → 사전 화이트리스트/증강으로 recall·noise 조정
2. `train_crf.py`: 문자 n-gram·위치·사전멤버십 피처 + sklearn-crfsuite 학습, span F1 ≥ 0.85 목표(`ai-spec.md §1`)
3. `CrfSpanExtractor`(services/chat `span_extractor/ner.py`) 구현 → `EXTRACTOR_BACKEND=ner` 스왑
4. 형태소 단위(현재 문자 단위) 검토 — nori 등, 정확도 여지

## 산출물·저장

- `data/`(코퍼스·라벨)는 재생성 가능이라 **git 미포함**(`.gitignore`). 검수·확정된 최종 코퍼스와 학습 모델은 추후 git 아티팩트로 커밋(모델 X).
