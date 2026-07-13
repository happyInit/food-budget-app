# Chat Service — RAG 챗봇 MVP

`docs/chat-assistant-ai.md` §2의 5단계 파이프라인(①질문분석 ②병렬검색 ③컨텍스트조립 ④생성 ⑤응답조립) 축소 구현.
설계 배경·스코프 결정은 구현계획(`~/.claude/plans/zesty-mapping-firefly.md`, 세션 종료 후엔 이 README와 코드 주석이 정본) 참고.

## 스코프

- **생성 백엔드**: TemplateGenerator만(`GENERATOR_BACKEND=template`, 확정 사항 — `docs/design.md` §9). 무료·승인 불필요.
- **재료 추출**: `EXTRACTOR_BACKEND=rule`(기본) — CRF NER 완성 전까지 `gazetteer.py` 기반 규칙 대체.
  NER 완성 시 `app/pipeline/span_extractor/ner.py`의 `CrfSpanExtractor`만 구현하고 `EXTRACTOR_BACKEND=ner`로 전환하면 됨(다른 파일 변경 불필요).
- **검색 소스**: ES(레시피) · PG(마켓컬리/오아시스 가격) · PG(영양) 3개 실구현 + Pantry/User(재고·예산) 1개 스텁(`available=False`, 스키마·서비스 부재).
- **인증 없음**: Gateway/User 서비스가 없어 JWT 검증 불가 — `user_id`는 옵션 필드로만 받고 검증 안 함.

## 로컬 실행 (Docker 없이)

전제: `pipelines/ingest/index_recipes_es.py`를 먼저 실행해 ES `recipes` 인덱스가 채워져 있어야 함(레포 루트에서, `pipelines/ingest/requirements.txt` 설치 후).

```bash
cd services/chat
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# .env는 레포 루트에 둔다 (app/vendor/_db.py가 python-dotenv로 레포 루트 .env를 읽음)
# 레포 루트 .env.example 참고 — PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD, ESHOST/ESPORT

uvicorn app.main:app --reload --port 8001
```

```bash
curl localhost:8001/health
curl -X POST localhost:8001/chat -H 'Content-Type: application/json' \
  -d '{"message":"두부랑 대파로 뭐 해먹지"}'
```

## 테스트

```bash
pytest tests/
```

## 알려진 한계

- `RuleBasedSpanExtractor`의 자유 문장 매칭 정확도는 사전 검증 안 됨 — 배포 전 수기 질문 샘플 20~30개로 확인 필요.
- 예산 파싱은 `N만원`/`N원` 패턴만 지원(`2만 5천원` 같은 복합 표기는 놓침).
- 가드레일 출력대조·비용상한은 템플릿 모드라 실제 강제 안 함(`app/pipeline/guardrails.py`의 TODO 참고) — 유료 생성 백엔드 전환 시 채울 자리.
