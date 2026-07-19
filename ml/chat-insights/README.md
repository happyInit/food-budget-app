# 챗 인사이트 — 대화 로그 분석·개인화·의도학습 (prep-ahead)

RAG 챗봇(밥풀이) 대화 로그(`chat.chat_message`)가 쌓이면 **사람 개입 없이** 돌아가는
3종 배치. 랭킹 재학습(`ml/recipe-ranking/retrain.py`)과 동일 사상 — **데이터 없으면 skip,
쌓이면 자동 가동**.

```bash
python run.py --synth          # 합성 데이터로 end-to-end 검증(DB 불필요)
python run.py                  # 실 chat_message(없으면 skip 안내) 1회
python run.py --loop 86400     # 주기(compose 서비스, 일 1회)
```

## 3종 산출

| # | 산출 | 무엇 | 소비처 |
|---|------|------|--------|
| 1 | **리포트** (`reports.py`) | 일일/임계 대화 집계 → 의도분포·미응답률·**커버리지 갭** | 데이터 담당(사람) |
| 2 | **선호 신호** (`preferences.py`) | 유저별 선호·비선호 재료·예산 민감도 → jsonl | 랭킹 재학습 피처 + 챗 응답 개인화 |
| 3 | **의도 분류기** (`intent_model.py`) | 발화→의도 학습(FastText/sklearn) | 챗 의도분류 규칙 보강 |

- `reports/chat/{daily,threshold}/` · `reports/chat/preference-signals/` · `INTENT_MODEL_PATH`

## prep-ahead 게이트 (전부 비치명 skip)
- `chat.chat_message` **미마이그레이션** → skip (스키마·쓰기경로 **#127** 대기).
- 최근 대화 **0건** → skip (데이터 축적 대기).
- 의도 학습셋 **부족**(<200건·<3클래스) → skip (규칙 유지).
- 리포트 **LLM 서술**: `REPORT_GEMINI_API_KEY`(비용격리 전용, #179 결정 Gemini Flash) 있으면
  자동 첨부, 없으면 구조화 지표만 — 키 주입 시 자동 업그레이드.

## 남은 활성 조건 (내 코드 밖)
1. `chat.chat_message` 스키마 프로덕션 적용 (인프라/데이터)
2. 백엔드 `chat_message` 쓰기 경로 (#127, 태현)
3. 동의 확정 (#131) · (선택) `REPORT_GEMINI_API_KEY` 주입

→ 위가 채워지면 이 배치는 그대로 무인 가동. 코드는 준비 완료.

## 구성
`_data.py`(읽기·graceful skip) · `synth.py`(합성) · `reports.py` · `preferences.py`
· `intent_model.py` · `run.py`(오케스트레이터·loop) · `tests/`
