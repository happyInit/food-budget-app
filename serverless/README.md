# `serverless/` — AI 함수의 Lambda 진입 계층

**계산 로직은 여기 없다.** 배치는 `pipelines/ingest/`, 서비스는 `services/` 에 그대로 있고,
이 트리는 *"Lambda 가 그것을 어떻게 부르는가"* 만 담는다. **문이지 방이 아니다.**

```
common/          함수 12종이 공유하는 이식 계층
  runtime.py     event 번역 · 시간 가드 · 로깅
  secrets.py     Secrets Manager → os.environ 어댑터
  jobs.py        잡 상태 · 단일비행 락 · 결과 캐시 · SQS 전송   (접수·워커가 공유)
  alb.py         ALB 이벤트 ↔ HTTP 응답 번역                    (접수 함수가 공유)
ai_<함수>/
  app.py         handler(event, context) — 얇은 껍데기
  modules.txt    번들에 넣을 레포 모듈(명시적)
  requirements.txt  함수별 락 파일(전이 의존까지 핀 — 없으면 배치 공통을 쓴다)
tests/           AWS 없이 도는 테스트
```

**지금까지 옮긴 것 7/11**

🔴 **11 이다(12 가 아니다)** — `notify-consumer` 는 **C-88 로 소거**됐다. 알림 발송이 SQS 컨슈머가
아니라 `price-detect` 안의 `emit_direct`(fan-out SQL 직접 실행)에서 끝난다. 설계서 §6 정정 참조.

| | 함수 | 트리거 | 상태 |
|---|---|---|---|
| 배치 | `shelflife_draft` · `ner_backfill` | 수동 Invoke | ✅ |
| 배치 | `sentiment_batch` · `summarize_batch` · `price_detect` | Scheduler | ✅ |
| 접수·워커 | `video_api` · `video_worker` | ALB · SQS | ✅ |
| 접수·워커 | `ocr_api` · `ocr_worker` | ALB · SQS | ⏸ **G-06 선행**(영수증 이미지 전달 경로) |
| 서비스 | `chat_api` · `rank_serve` | ALB · HTTP | ⏸ `rank_serve` 는 **이미지 강제**(libgomp) |
| ~~컨슈머~~ | ~~`notify_consumer`~~ | — | ⛔ **소거(C-88)** — `price_detect` 가 흡수 |

🔵 `video` 2종이 **접수·워커의 본**이다 — `ocr` 은 G-06 이 풀리면 같은 계약(`common/jobs.py`)을
그대로 쓰고 이미지 전달 경로만 다르게 붙인다. 설계 = `docs/serverless/01_접수-워커_분할설계.md`.

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

## 핸들러가 **일부러 안 노출하는** CLI 인자

| 함수 | 뺀 것 | 왜 |
|---|---|---|
| `summarize-batch` | `--audit` · `--compare` | 사람이 눈으로 대조하는 모드. `audit` 은 원문 표본으로 **로그를 덮고**, `compare` 는 후보 모델을 나란히 돌려 **호출 비용이 배**로 든다 |
| `price-detect` | `--emit` (Kafka) | 🔴 **AWS 에 Kafka 가 없다**(C-44). AWS 경로는 `emit_direct` 하나뿐(C-88) |
| `price-detect` | `--json` | Lambda 는 `/tmp` 만 쓸 수 있고 그 파일은 실행이 끝나면 아무도 못 본다 |

## 실패를 어떻게 알리나

| | CLI(CronJob) | Lambda |
|---|---|---|
| 정상 | 종료코드 0 | 요약 dict 반환 |
| fan-out 일부 실패 | `sys.exit(1)` | **`FanoutIncomplete` 예외** |

CronJob 은 **종료코드로만** 성패를 안다. Lambda 에는 종료코드가 없어 **예외가 그 자리**다 —
조용히 성공으로 반환하면 *"알림이 통째로 멈춘 걸 아무도 모르는"* 상태가 그대로 재현된다.
