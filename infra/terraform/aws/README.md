# infra/terraform/aws — 크롤 운반 경로 (S3 + SQS + IAM)

C-44(Kafka 전면 제거)의 AWS 쪽 실물. **이 레포에서 처음 만드는 AWS 리소스**다.

```
   크롤러(온프렘) → S3 incoming/ → S3 이벤트 → SQS → KEDA → 리파이너 → PG
```

이관 후에도 **크롤은 온프렘 상시 프로덕션**(C-3)이라 왼쪽 절반은 그대로 남고,
컷오버는 오른쪽 리파이너를 온프렘에서 AWS 로 옮기는 것뿐이다. 버킷도 큐도 그대로다.

## 이 스택이 만드는 것

| | 이름 | 비고 |
|---|---|---|
| S3 버킷 1 | `mp-crawl-ap2` | SSE-S3 · 퍼블릭 차단 · `incoming/` 90일 · `failed/` 365일 |
| SQS 큐 3 | `mp-crawl-{retail,deal,recipe}` | 가시성 900s · 보존 14일 · long polling 20s |
| SQS DLQ 3 | `mp-crawl-*-dlq` | maxReceiveCount 3 |
| IAM 사용자 2 | `mp-crawl-uploader` · `mp-crawl-refiner-onprem` | 인라인 정책. **액세스 키는 미포함** |

비용: 객체 6개/일 · 저장 4.7MB/일 → 사실상 $0. SQS 는 KEDA 폴링 포함 월 약 26만 요청으로
**무료 한도(100만) 안**이다.

## 객체 키 규약

```
incoming/<stream>/<source>/<yyyy-mm-dd>/<run-id>.jsonl
failed/<stream>/<source>/<yyyy-mm-dd>/<run-id>/<seq>.json

  stream ∈ retail | deal | recipe    큐 3개와 1:1 (= 구 Kafka 토픽 3종)
  source ∈ kurly | oasis | 10k       구 Kafka 메시지 헤더 `source` 와 1:1
  run-id = <UTC타임스탬프>-<파드이름>   Job 까지 역추적된다
```

🔴 체크리스트 `0-28`③ 의 표기(`incoming/<소스>/<날짜>/<실행ID>.jsonl`)와 다르다 — **stream 층을 하나 넣었다.**
소스와 스트림이 1:1 이 아니기 때문이다: `oasis` 한 크롤러가 `--categories` 면 retail, `--deal` 이면 deal 로
간다(구조상 Kafka 도 레코드별로 토픽을 갈랐다 — `oasis_crawler.py` 의 `kafka_sink`). 소스만으로 prefix 를
만들면 S3 이벤트가 큐를 못 고른다.

## apply

```bash
cp backend.conf.example backend.conf     # gitignored
terraform init -backend-config=backend.conf
terraform plan
terraform apply
```

🔴 **권한**: 이 스택은 S3 버킷 생성 · SQS 생성 · **IAM 사용자 생성**을 한다.
`mp-backup` 프로필은 백업 전용으로 발급된 키라 IAM 권한이 없을 공산이 크다
(그 자격증명으로 `mp-backup-ap2` 의 버전관리를 못 켰다 — `../backend.tf`).
권한 부족이면 `-var profile=<관리자프로필>` 로 apply 한다. **backend 프로필은 별개**로 `backend.conf` 가 정한다.

## 액세스 키 — Terraform 이 만들지 않는다

`aws_iam_access_key` 를 쓰면 **비밀이 tfstate 에 평문으로 들어간다.** state 는 `mp-backup-ap2` 에 있고
그 버킷은 버전관리조차 못 켠 상태다. 장기 자격증명을 거기 두면 열린 항목 ③(정적 키 = 유일한 보안 후퇴)을
넓히는 짓이다. 그래서 apply 후 **수동 1회**:

```bash
aws iam create-access-key --user-name mp-crawl-uploader        # 업로더용
aws iam create-access-key --user-name mp-crawl-refiner-onprem  # 리파이너·KEDA 용
```

출력된 키는 **터미널에 남기지 말고** 바로 비밀 저장소(`fb-secrets` → ESO → `mp-pipeline-secrets`)로 넣는다.
로테이션은 `1-29`(로테이션 절차) 대상에 이 2건을 추가한다 — 주입이 `envFrom.secretRef` 라
**값만 바꾸면 도는 파드는 옛 키를 계속 쓴다.** 교체 = 값 교체 + `rollout restart` 가 한 묶음이다.

## 되돌리기

```bash
terraform destroy
```

🔴 단 **버킷에 객체가 남아 있으면 destroy 가 실패한다**(의도된 안전장치 — `force_destroy` 를 안 켰다).
크롤 데이터를 정말 버릴 결심이 서면 비운 뒤 다시 destroy 한다. 되돌리기가 파이프라인에 주는 영향은
**단계에 달렸다** — 크롤러가 아직 `--kafka` 를 달고 있는 동안에는 이 스택을 통째로 지워도 파이프라인은 안 멈춘다.
단계별 되돌리기는 `docs/mp_crawl_s3_migration_runbook.md` 참조.
