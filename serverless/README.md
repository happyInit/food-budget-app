# `serverless/` — AI 함수의 Lambda 진입 계층

**계산 로직은 여기 없다.** 배치는 `pipelines/ingest/`, 서비스는 `services/` 에 그대로 있고,
이 트리는 *"Lambda 가 그것을 어떻게 부르는가"* 만 담는다. **문이지 방이 아니다.**

```
common/          함수 12종이 공유하는 이식 계층
  runtime.py     event 번역 · 시간 가드 · 로깅
  secrets.py     Secrets Manager → os.environ 어댑터
ai_<함수>/
  app.py         handler(event, context) — 얇은 껍데기
tests/           AWS 없이 도는 테스트
```

## 원칙 — 모르는 값은 코드에 박지 않는다

AWS 실물(주소·시크릿 이름·아키텍처)은 아직 확인 전이다. 그래서 **전부 환경변수로 받는다.**
확인 뒤에 바뀌는 것은 **설정이지 이 트리의 코드가 아니다.**

| 환경변수 | 무엇 | 예 |
|---|---|---|
| `MP_SECRET_NAMES` | 읽을 Secrets Manager 시크릿(쉼표) | `mp/prod/pipeline-secrets,mp/prod/data-secrets` |
| `MP_SECRET_KEYS` | 꺼낼 키(`환경변수명=시크릿필드명`) | `PGPASSWORD,ES_PASSWORD=ES_PIPELINE_WRITER_PASSWORD` |
| `PGHOST` `PGPORT` `PGUSER` … | 접속 대상 | 확인 후 기입 |
| `LOG_LEVEL` | 기본 `INFO` | |

둘 중 하나라도 비면 시크릿 주입을 **건너뛴다** — 로컬·CLI 실행이 그대로 돈다.

## 아직 안 한 것 (실물 확인 후)

**패키징**(zip / 컨테이너 · arm64 휠) · **Terraform 함수 정의** · **큐·스케줄 생성**.
셋 다 서브넷 ID·역할 ARN·아키텍처 같은 **실물 값**이 있어야 정해진다.
