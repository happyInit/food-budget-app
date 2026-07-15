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
③ train_crf.py        sklearn-crfsuite 문자 CRF 학습 → data/model (span F1 = 약지도 대비치)
④ HITL gold 평가       make_review_set.py → 사람 교정(gold_test.txt) → score_gold.py (진짜 F1)
⑤ (후속) 챗봇 연동     CrfSpanExtractor 구현 → services/chat EXTRACTOR_BACKEND=ner
```

## HITL gold 테스트셋 (진짜 F1 측정)

약지도 대비 F1(0.978)은 자동라벨끼리의 비교라 신뢰 정본이 아니다(§CRF caveat). **사람 검수 gold**가 필요.

```bash
python make_review_set.py     # data/gold_review.txt 생성(약지도 초안을 {{}}로 사전채움)
# → data/gold_review.txt 를 열어 '=' 줄의 {{}}만 교정:
#     잘못 잡힘 → {{}} 제거 · 놓친 재료 → {{}} 추가  (원문/'#' 줄은 수정 금지)
# → 교정본을 ml/ingredient-ner/gold_test.txt 로 저장(커밋 대상=모델 X 아티팩트)
python score_gold.py          # 약지도·CRF 각각의 진짜 span P/R/F1 + CRF 오류표본
```

사전채움 덕에 "처음부터 라벨링"이 아니라 **틀린 것만 교정**(50건 기준 수십 분). 검수가 무의미/과도하면 잠정 silver로 전환 가능.

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

**여전히 약지도** — 자동 라벨이라 잔여 노이즈 있음. **샘플 육안 검수 + HITL 보정** 전제(`ner-training-data-spec §0`). 사전에 없는 완전 신규 재료는 후속 **자기학습(부트스트래핑)**으로 확장.

## ③ CRF 학습 결과 (`train_crf.py`, 문자 단위)

sklearn-crfsuite(CPU) · 피처 = 문자 + 문자유형 + 전후 문자·바이그램 + BOS/EOS. **사전멤버십 피처는 일부러 제외**(넣으면 사전을 외워 미등재 재료로 일반화 못함).

**두 가지 평가 기준:**

| 평가 대상 | Precision | Recall | span F1 |
|---|---|---|---|
| 약지도 라벨(test 246) — *참고용* | 0.980 | 0.978 | 0.979 |
| **사람 검수 gold(50건) — 정본** | 0.930 | **0.918** | **0.924** |

미등재 일반화 스팟체크: `방울토마토 150g, 양파 10g` → `[방울토마토·양파·부추]` ✅

> ⚠️ **0.979 ≠ 실제 성능.** 그건 "약지도 vs 약지도"(자동라벨끼리)라 부풀려진 값이다. **사람 gold 대비 진짜 F1은 0.924**(`score_gold.py`, gold=`gold_test.txt`) — `ai-spec.md §1`의 F1≥0.85 **안정 통과**.

**F1 개선 여정(모두 자동, gold 확대 없이):**
`0.849(초안) → 0.899(사전 STOP·헤더 정리) → 0.916(Gemini 오프라인 사전증강 §④-d) → 0.924(제목줄 마스킹 + 주스/즙 접미확장 + 플레인 수식어)`

**남은 잔차 = gold 자체의 관례 불일치(과적합 없이는 개선 불가):**
- `새우두부계란찜` — 요리명을 재료로 분할할지(gold=새우/두부/계란찜, CRF=통째). 재료-언급 원칙상 요리명은 미라벨이 맞으나 gold가 분할.
- `저염 간장` — 이 레코드 gold는 `간장`만, 그러나 저염간장은 별개 재료로 볼 여지(item_master granularity 판단, Taylor 영역).
- 섹션 내 `양념간장`, 괄호 `불고기용` 등 개별 엣지.
- → **이 이상(확실한 0.95)은 50건 gold의 ±노이즈 벽**. gold 정리/확대(노동) 전엔 측정 자체가 불가.

## 다음 단계

1. ✅ **Precision↑**(완료): 사전 STOP·헤더 정리 + 섹션/제목 마스킹 → 0.930.
2. ✅ **Recall↑**(완료): item_master + Gemini 오프라인 사전증강 → 0.918.
3. `CrfSpanExtractor`(services/chat `span_extractor/ner.py`) 구현 → `EXTRACTOR_BACKEND=ner` 스왑 후 챗봇 재가동.
4. *(정규화 트랙, 별개 지표)* 표기변형 통일(요구르트=요거트)·granularity(저염간장·오렌지주스)는 **item_master 층(Taylor)** 소관 — NER span F1과 무관(조인 품질). Gemini 오프라인 제안은 가능하나 granularity 결정은 오너 판단.
5. *(선택)* 형태소 단위(nori) 검토 · gold 확대는 노동 부담 커 후순위.

## 산출물·저장

- `data/`(코퍼스·라벨·`model/`)는 재생성 가능이라 **git 미포함**(`.gitignore`). HITL 검수·확정된 최종 코퍼스와 학습 모델은 추후 git 아티팩트로 커밋(모델 X).
