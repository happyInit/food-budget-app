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
  app.py         handler(event, context) — 얇은 껍데기 (패키지형은 handler.py — 아래 표)
  modules.txt    번들에 넣을 레포 모듈(명시적). `-` 로 시작하면 **담았다가 도로 빼는** 경로
  requirements.txt  함수별 락 파일(전이 의존까지 핀 — 없으면 배치 공통을 쓴다)
tests/           AWS 없이 도는 테스트
```

🔴 **진입점 파일 이름이 함수마다 다르다 — 임의로 통일하지 말 것.**

| 앱 모양 | 진입점 파일 | Lambda 핸들러 문자열 | 해당 |
|---|---|---|---|
| 평면(레포 모듈을 파일 단위로 담음) | `app.py` | `app.handler` | 배치 5종 · `video` 2종 · `ocr_api` · `rank_serve` |
| **패키지**(`services/<svc>/app` 을 통째로 담음) | **`handler.py`** | **`handler.handler`** | `chat_api` · `ocr_worker` |

`import app` 은 **패키지가 모듈을 이긴다**(실측). 패키지형에서 진입점까지 `app.py` 로 두면
번들 루트의 `app/` 이 먼저 잡혀 «패키지 app 에 handler 가 없다» 로 죽는다. 규약은
`tests/test_bundle_packaging.py` 가 지킨다.

🔴 **심볼릭 링크는 실체로 풀어서 담는다**(`build.sh` 의 `cp -RL` + 잔존 가드).
`services/{chat,recipe,ocr}/app/vendor/*.py` 는 `pipelines/ingest/*.py` 로 가는 링크다.
`cp -R` 로 담으면 번들 안에서 **끊어진 링크**가 되는데 — 빌드는 성공하고 크기도 정상이라
**첫 호출의 `ModuleNotFoundError` 로만** 드러난다. 실제로 밟았다(2026-08-17 `app/vendor/` 3개).

**지금까지 옮긴 것 11/11 — 코드는 전부 끝났다.**

🔴 «끝» 은 **코드**다. 배포는 별개고 아래 §배포 전 남은 선행 을 볼 것.

🔴 **11 이다(12 가 아니다)** — `notify-consumer` 는 **C-88 로 소거**됐다. 알림 발송이 SQS 컨슈머가
아니라 `price-detect` 안의 `emit_direct`(fan-out SQL 직접 실행)에서 끝난다. 설계서 §6 정정 참조.

| | 함수 | 트리거 | 상태 |
|---|---|---|---|
| 배치 | `shelflife_draft` · `ner_backfill` | 수동 Invoke | ✅ |
| 배치 | `sentiment_batch` · `summarize_batch` · `price_detect` | Scheduler | ✅ |
| 접수·워커 | `video_api` · `video_worker` | ALB · SQS | ✅ |
| 접수·워커 | `ocr_api` · `ocr_worker` | ALB · SQS | ✅ 코드 완비 · **G-06 은 여전히 미결**(아래) |
| 서비스 | `chat_api` | ALB | ✅ 번들 40.2MB · **배포는 NodePort 배선(P) 선행** |
| 서비스 | `rank_serve` | ALB | ✅ **컨테이너 이미지**(libgomp) — zip 아님 |
| ~~컨슈머~~ | ~~`notify_consumer`~~ | — | ⛔ **소거(C-88)** — `price_detect` 가 흡수 |

🔵 `video` 2종이 **접수·워커의 본**이다 — `ocr` 은 G-06 이 풀리면 같은 계약(`common/jobs.py`)을
그대로 쓰고 이미지 전달 경로만 다르게 붙인다. 설계 = `docs/serverless/01_접수-워커_분할설계.md`.

🔴 **`ocr` 2종은 코드가 끝났지만 G-06 이 «어느 경로로 올릴지» 를 정해야 한다** —
그리고 그 결정에는 이제 **막힌 선택지가 하나 있다**:

| | 값 | 출처 |
|---|---|---|
| ALB → Lambda **요청 본문 상한** | **1 MB** | AWS 공식 문서 "Limits"(2026-08-17 확인) |
| OCR 업로드 상한 `max_image_bytes` | 8 MB | `services/ocr/app/config.py` |
| 휴대폰 영수증 사진 통상 | 2 ~ 5 MB | — |

즉 **현행 `POST /api/pantry/ocr` 를 그대로 Lambda 에 붙이면 대부분의 사진이 못 올라간다.**
ALB 가 함수를 부르기도 전에 끊는다(파드/Envoy 에서는 안 나던 문제고, **올릴 수 없는 고정 상한**이다).
⇒ 접수 함수는 **presigned S3 PUT** 경로를 열어 두고(`POST /api/pantry/ocr/upload-url`),
1 MB 이하 사진은 기존 방식 그대로 받는다. 어느 쪽이든 **큐에는 좌표(`bucket`/`key`)만** 흐르고
(SQS 본문 상한 256KB < 사진) **워커와 폴링은 안 바뀐다.**
🔴 **프론트 변경 여부가 G-06 의 실제 쟁점**이다 — presigned 경로를 쓰려면 업로드 단계가 하나 는다.

🔴 **`chat_api` 는 «준비 완료» 지 «배포 가능» 이 아니다.** PG(Pooler)·ES 가 K8s 내부 DNS
(`pg-pooler.data.svc`)라 Lambda 가 이름을 해석하지 못한다 — **NodePort + 노드 사설 IP** 배선이
선행이다. 그때 바뀌는 것은 `PGHOST`·`ESHOST` **환경변수뿐**이고 코드는 안 바뀐다.

## 🔴 `rank_serve` 만 컨테이너다 — 그리고 그게 유일한 예외다

`lightgbm` 은 OpenMP 런타임(`libgomp.so.1`)을 요구하는데 그건 **파이썬 휠이 아니라 OS 패키지**다.
zip 번들에는 OS 패키지를 넣을 자리가 없어서 `import lightgbm` 이 그 자리에서 죽는다.

⚠️ *"lightgbm 을 빼고 sklearn 폴백만 쓰면 zip 으로 되지 않나"* — 된다. 하지만 그러면
**정식 LambdaMART 를 못 쓴다**(폴백은 GradientBoosting). 배포 방식 때문에 모델 품질을
떨어뜨리는 선택이라 컨테이너 쪽이 맞다.

🔵 **컨테이너로 가면 «마커 함정» 이 사라진다** — zip 은 호스트에서 `pip download --platform`
으로 받느라 환경 마커가 빌드 기계 인터프리터로 평가돼 의존성이 조용히 빠졌다
(2026-08-14 `typing-extensions`). 이미지 **안에서** 설치하면 그 문제가 없다.
그래서 이 함수의 requirements 만 **락이 아니라 범위 핀**이다.

### 이미지를 굽는 CI 잡은 **아직 없다** (일부러)

기존 `build:*` 잡들은 K8s 서비스 이미지를 굽고 **config 레포에 태그를 핀**하는 흐름이다.
Lambda 이미지는 핀할 config 가 없어 그 틀에 안 맞는다. 그리고 **배포 권한이 아직 없어**
지금 구워도 아무 데도 못 올린다. 권한이 오면 이 잡 하나만 더하면 된다:

```bash
aws s3 cp s3://mp-ai-model-ap2/ranker.pkl ./ranker.pkl        # C-20 — 모델을 이미지에 굽는다
docker build --platform linux/arm64 \                          # 🔴 C-29 Graviton. 빼면 첫 호출에서 exec format error
  -f serverless/ai_rank_serve/Dockerfile -t "$ECR/mp-ai-rank-serve:$SHA" .
trivy image --severity CRITICAL --ignore-unfixed --exit-code 1 "$ECR/mp-ai-rank-serve:$SHA"
docker push "$ECR/mp-ai-rank-serve:$SHA"
aws lambda update-function-code --function-name mp-ai-rank-serve --image-uri "$ECR/...:$SHA"
```

## 배포 전 남은 선행 — 코드로 못 푸는 것들

| | 무엇 | 막는 것 |
|---|---|---|
| **권한** | Lambda 생성·배포 권한(역할·SG 포함) | **11종 전부** |
| **NodePort** | PG(Pooler)·ES 를 VPC 에서 이름으로 못 찾는다 | `chat_api` · `rank_serve` · `ocr_worker` |
| **G-06** | 영수증 이미지 전달 경로(프론트 변경 여부) | `ocr_api` 의 **운영 형상**(코드는 양쪽 다 됨) |
| **S3·SQS** | 업로드 버킷 · 잡 큐 · DLQ 생성 | `ocr` 2종 · `video` 2종 |

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
