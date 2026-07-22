# 챗봇 대화 분석 리포트 (data owner 전달)

밥풀이(RAG 챗봇) 대화 로그(`chat.chat_message`)를 주기 분석해 **데이터 담당자에게 전달**하는
리포트가 쌓이는 디렉터리. 리포트 생성기(후속)가 파일을 여기에 쓰고, 담당자가 읽는다.

> ⚠️ 실데이터는 `chat.chat_message` **쓰기 경로(#127)**가 열려야 흐른다. 그 전까지는
> 합성 입력으로 생성기를 검증(랭킹 스캐폴드와 동일 전략). 스키마·쓰기 준비되면 자동 가동.

## 디렉터리 구조

```
reports/chat/
├── daily/                  # 일일 사용/품질 리포트 (§1.3) — 매일 1건
├── threshold/              # 임계·이상 리포트 (§1.4) — 지표 임계 돌파 시 트리거
└── preference-signals/     # 장기 개인화용 선호 신호 추출 (랭킹 피처로 환류)
```

## 명명 규칙 (시간순 정렬 + 트리거 식별)

| 종류 | 파일명 | 예 |
|------|--------|-----|
| 일일 | `daily/YYYY-MM-DD.md` | `daily/2026-07-19.md` |
| 임계 | `threshold/YYYY-MM-DDTHH-MM_<trigger>.md` | `threshold/2026-07-19T14-03_unanswered-spike.md` |
| 선호신호 | `preference-signals/YYYY-MM-DD.jsonl` | `preference-signals/2026-07-19.jsonl` |

- 날짜 앞자리 → 파일시스템 정렬이 곧 시간순.
- `<trigger>`: 무응답률 급증(`unanswered-spike`)·특정 의도 폭증·오프토픽 증가 등.
- 선호신호는 사람이 읽는 리포트가 아니라 **기계 소비용**(랭킹 재학습 피처) → `.jsonl`.

## 전달 흐름

```
chat_message → [리포트 생성기 배치] ──┬─ daily/·threshold/  → 데이터 담당자(사람이 읽음)
   (일일/임계 트리거)                  └─ preference-signals/ → 개인화 랭킹 피처로 환류(자동)
```

- **인적 게이트(의도된 것)**: daily/threshold 리포트는 담당자가 읽고 판단 — 자동화 대상 아님(원 목적).
- **자동 환류**: preference-signals는 랭킹 재학습(`ml/recipe-ranking/retrain.py`)이 소비 → 사람 개입 없이 개인화에 반영.

## 분석 LLM — Gemini Flash (결정)

리포트의 대화 분석에는 LLM이 필요하다. **Gemini 2.5 Flash** 채택.

**왜 이 모델인가**
1. **벤더 일원화** — 챗봇이 이미 Gemini(`gemini-flash-lite-latest`) 사용. 같은 SDK·키 관리·비용
   모니터링·월 상한(#155) 패턴을 그대로 재사용 → 신규 의존성 0.
2. **작업 적합** — 리포트는 요약·집계·이상탐지(프런티어 추론 불필요). Flash급으로 충분.
   챗봇은 지연민감이라 flash-**lite**를 쓰지만, 리포트는 배치(지연 무관)이고 분석 품질이
   조금 더 중요해 한 단계 위 **Flash**를 권장(비용 차이 미미).
3. **긴 컨텍스트** — 하루치 대화 수천 건을 묶어 분석 → Gemini의 큰 컨텍스트 윈도우 유리.
4. **비용** — 배치·저빈도라 총비용이 작다. 일일 대화 5천건(≈입력 1M 토큰) 분석 기준
   하루 수백 원, 월 1만 원 미만 규모. 비용이 문제면 `REPORT_GEMINI_MODEL`을 flash-lite로
   한 줄 다운시프트 가능. 챗봇과 동일한 **월 상한(cost-break)**을 리포트 배치에도 적용.

**대안 대비**: Gemini Pro는 추론↑이나 ~15–20배 비싸고 리포트엔 과함. Claude/GPT는 품질 좋으나
신규 벤더·키가 늘어 운영 복잡도만 증가(현 규모에선 이득 없음).

## 필요한 API 키 (담당자=건우 제공)

챗봇·OCR과 동일한 **비용 격리** 원칙 → 리포트 전용 키를 별도로 둔다(챗봇 quota·상한과 독립,
개별 회수 가능). 리포트 생성기 활성 전 `.env`에 주입 필요:

```
REPORT_GEMINI_API_KEY=<발급받은 리포트 전용 Gemini 키>   # 필수 — 없으면 생성기 fail-fast(무해)
REPORT_GEMINI_MODEL=gemini-3.5-flash                     # 기본(버전 핀). 비용 절감시 gemini-3.5-flash-lite
REPORT_MONTHLY_BUDGET_WON=3000                           # 리포트 배치 월 상한(초과시 생성 skip)
```

> 생성기는 키가 없으면 **동작 안 하고 조용히 skip**(기존 파이프라인 무손상). 키가 주입되고
> chat_message가 흐르면 자동으로 리포트를 쌓기 시작한다.
