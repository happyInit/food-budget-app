# 크롤 운반 Kafka → S3/SQS 전환 런북 (C-44)

> 신설 2026-08-10. 정본 결정 = `docs/mp_aws_prep_checklist.md` **C-44**(Kafka 전면 제거) · 선행 `0-28`·`0-31`.
> 이 문서는 *실행 절차*의 정본이다. 결정을 바꾸지 않는다 — 어긋나면 체크리스트가 이긴다.

```
   지금   크롤러 → Kafka(3브로커) → 리파이너 → PG
   목표   크롤러 → 파일 → S3 incoming/ → SQS → KEDA → 리파이너 → PG
```

이관 후에도 **크롤은 온프렘 상시 프로덕션**이다(C-3). 그래서 이 경로의 왼쪽 절반은 이관 뒤에도 그대로 남고,
컷오버는 **리파이너를 온프렘에서 AWS 로 옮기는 것**뿐이다. 큐도 버킷도 그날 새로 태어나지 않는다.

---

## 0. 착수 전 — C-44 서술 중 실측과 다른 것 3가지

체크리스트를 고치지 않았다(다른 세션 소유). **여기 적어두고 보고만 한다.**

| C-44 서술 | 실측 | 근거 |
|---|---|---|
| 크롤러 3종 전부 파일 출력 모드가 있다 | **2종만.** `10k_recipe` 는 `--out` 이 아예 없고 CSV 4종은 resume/dedup 전용이라 스키마가 다르다 | `crawler/10k_recipe/10k_recipe_crawler.py` argparse = `--kafka`·`--limit`·`--order` 뿐 |
| 🟢 Python 코드 변경 0 | **거짓.** ① 업로드 코드 ② `10k_recipe` 출력 신설 ③ 컨슈머 3종 SQS 전환 | 아래 "무엇을 만들었나" |
| 크롤 CronJob 의 volumeMounts 가 [] | `mp-poller-recipe` 는 **이미 PVC 를 쓴다**(`mp-recipe-crawl-state` 1Gi, `/data/recipe-crawl`) | `pipelines/base/pollers.yaml` |

🔴 특히 첫 줄이 위험하다 — 그대로 믿고 `mp-poller-recipe` 에서 `--kafka` 만 빼면 **레시피 적재가 조용히 0이 된다.**
크롤은 돌고 CSV 는 쌓이는데 PG 에는 아무것도 안 들어간다.

---

## 1단계 — AWS 리소스 생성 (파이프라인 무영향)

```bash
cd infra/terraform/aws
cp backend.conf.example backend.conf
terraform init -backend-config=backend.conf
terraform plan          # 🔴 IAM 사용자 2개 생성이 들어 있다 — 권한 부족이면 여기서 드러난다
terraform apply
terraform output queue_urls
```

만들어지는 것: 버킷 `mp-crawl-ap2` · 큐 `mp-crawl-{retail,deal,recipe}`(+DLQ 3) · IAM 사용자 2.

이어서 **액세스 키 발급(수동 1회)** — Terraform 이 만들지 않는다(비밀이 tfstate 에 평문으로 남기 때문):

```bash
aws iam create-access-key --user-name mp-crawl-uploader
aws iam create-access-key --user-name mp-crawl-refiner-onprem
```

출력값을 **터미널 밖으로 흘리지 말고** `fb-secrets` 의 Secret `pipeline-secrets` 에 4개 property 로 넣는다:
`CRAWL_UPLOADER_ACCESS_KEY_ID` · `CRAWL_UPLOADER_SECRET_ACCESS_KEY` ·
`CRAWL_REFINER_ACCESS_KEY_ID` · `CRAWL_REFINER_SECRET_ACCESS_KEY`.

**여기서 멈춰도 되는가** — 된다. 아무것도 이 리소스를 참조하지 않는다.
**되돌리기** — `terraform destroy` (버킷이 비어 있어야 한다) + `aws iam delete-access-key`.

---

## 2단계 — 컬리 하나만 dual-write (카나리)

🔴 **전환이 아니라 병행이다.** `--kafka` 를 그대로 두고 `--s3` 를 **더한다.**

```
   Kafka 경로  poller-kurly --kafka → retail.crawl.raw → mp-retail-refiner    → PG   (계속 프로덕션)
   S3 경로     poller-kurly --s3    → S3 → SQS         → mp-retail-refiner-s3 → PG   (그림자)
```

같은 실행의 같은 레코드가 양쪽으로 가고, 적재 SQL 이 전부 `on conflict do nothing` 이라 이중 도착이 무해하다.
**대조군을 얻는 것이 목적**이다 — 컬리 수확량은 실행마다 흔들려서(2026-08-03 907 유실, 08-04 3,346건)
어제 값과 비교하는 것으로는 새 경로의 정오를 판정할 수 없다.

### 순서

1. **app PR 머지** → Jenkins 가 `mp-crawler-kurly` · `mp-data-pipeline` 을 빌드한다.
2. 🔴 **config 의 이미지 태그를 손으로 올린다.** Jenkins 의 config 태그 커밋 스테이지는 앱 워크로드만
   대상이라 `data-pipeline`·`crawler-kurly` 는 **스킵한다**(Jenkinsfile 296). 이걸 빼먹으면 매니페스트만
   새 인자를 쓰고 이미지는 옛것이라 `--s3` 를 모르는 바이너리가 `unrecognized arguments` 로 죽는다.
3. config PR 의 `REPLACE_WITH_AWS_ACCOUNT_ID` 2곳을 `terraform output queue_urls` 값으로 채운다
   (`pipelines/base/consumers.yaml` · `pipelines/base/scaledobjects.yaml`).
4. config PR 머지 → `pipelines` 는 **auto-sync** 라 그대로 나간다.
   🔴 `mp-policies-pipeline` 은 **수동 sync** 다 — netpol 을 따로 밀어야 한다:
   ```bash
   kubectl patch application -n argocd mp-policies-pipeline --type merge \
     -p '{"operation":{"sync":{"revision":"HEAD"}}}'
   ```
   ⚠️ 이걸 빼먹으면 업로드가 **RST 없이 무한 대기**한다(Cilium 은 미허용 목적지에 SYN 을 드롭한다 —
   2026-08-03 컬리 97% 유실이 같은 양식이었다).

### 사전 점검 (03:30 전에)

```bash
kubectl -n pipeline get secret mp-crawl-uploader mp-crawl-refiner \
  -o go-template='{{range .items}}{{.metadata.name}} {{range $k,$v := .data}}{{$k}} {{end}}{{"\n"}}{{end}}'
kubectl -n pipeline get cnp mp-pipeline-fqdn-s3-upload mp-pipeline-fqdn-aws-consume
kubectl -n pipeline get scaledobject mp-retail-refiner-s3
kubectl -n keda logs deploy/keda-operator --tail=50 | grep -i sqs   # 스케일러가 큐를 읽는지
```

**여기서 멈춰도 되는가** — 된다. Kafka 경로가 그대로 프로덕션이다.
**되돌리기** — CronJob 인자에서 `--out`·`--s3` 두 개를 빼고 `mp-retail-refiner-s3` Deployment·ScaledObject 를
지운다. 이미지·볼륨은 남겨도 무해하다. **Kafka 쪽은 애초에 손댄 적이 없다.**

---

## 3단계 — 한 주기(03:30) 관찰과 판정

### 판정 기준 — "두 경로가 같은 결과를 냈는가"

```bash
# ① 크롤러가 두 싱크 다 성공으로 마감했는가 (dests 에 kafka 와 s3 가 둘 다 있어야 한다)
kubectl -n pipeline logs job/$(kubectl -n pipeline get job -o name | grep kurly | tail -1 | cut -d/ -f2) \
  | grep -E 'crawl_uploaded|crawler_succeeded|crawler_failed'

# ② 객체가 올라갔는가 · 크기가 말이 되는가
aws s3 ls s3://mp-crawl-ap2/incoming/retail/kurly/$(date +%F)/ --human-readable

# ③ 리파이너가 그 객체를 다 먹었는가 (record_count 가 크롤 건수와 같아야 한다)
kubectl -n pipeline logs deploy/mp-retail-refiner-s3 --tail=100 | grep object_ingested

# ④ 큐가 비었는가 (남아 있으면 처리가 안 끝났거나 삭제가 안 된 것)
aws sqs get-queue-attributes --queue-url <retail 큐> \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible

# ⑤ DLQ 가 비어 있는가 (0 이어야 한다)
aws sqs get-queue-attributes --queue-url <retail DLQ> --attribute-names ApproximateNumberOfMessages

# ⑥ 격리된 레코드가 없는가
aws s3 ls s3://mp-crawl-ap2/failed/ --recursive | head
```

### 통과 조건

- ③의 `record_count` == ①의 크롤 건수
- ④ 큐 0 / ⑤ DLQ 0 / ⑥ `failed/` 비어 있음
- PG 쪽에 **새 중복이 생기지 않았다**(멱등 확인):
  ```sql
  select source, count(*) from crawl_raw
   where kind='product' and crawled_at::date = current_date group by source;
  ```
  → dual-write 인데도 `kurly` 행 수가 크롤 건수와 같아야 한다(두 배가 되면 멱등 가정이 깨진 것 = 중단).

🔴 **하나라도 어긋나면 4단계로 가지 않는다.** 2단계 되돌리기는 언제든 1분이다.

---

## 4단계 — 나머지 5개 전환

통과 확인 후, 같은 방식으로 dual-write 를 붙인다(인자만 추가):

| CronJob | 추가 인자 | 스트림 |
|---|---|---|
| `mp-poller-oasis-dawn` · `-noon` | `--out /work/oasis.jsonl --s3` | retail |
| `mp-poller-deal-timesale` · `-closesale` | `--out /work/deal.jsonl --s3` | deal |
| `mp-poller-recipe` | `--out /data/recipe-crawl/recipe.jsonl --s3` | recipe |

⚠️ `mp-poller-recipe` 만 emptyDir 이 아니라 **기존 PVC 경로**를 쓴다(`workingDir` 가 이미 거기다).
PVC 는 1Gi 이고 레시피 JSONL 은 회차당 수 MB 라 여유가 있지만, **누적되지 않게 매 회차 덮어쓴다**(`w` 모드).

그리고 `mp-deal-notifier-s3` · `mp-recipe-refiner-s3` Deployment + ScaledObject 를 추가한다
(`consume_deal.py` · `consume_recipe.py` 는 이미 있다).

**여기서 멈춰도 되는가** — 된다. 여전히 Kafka 가 프로덕션이다.
**되돌리기** — 2단계와 같다(인자 제거 + `-s3` 워크로드 삭제).

---

## 5단계 — `--kafka` 제거 → Kafka 철거

🔴 **두 하위 단계를 하루 이상 벌린다.**

### 5-a. 크롤러에서 `--kafka` 제거 (Kafka 는 아직 살아 있다)

CronJob 6건에서 `--kafka` 만 뺀다. 구 컨슈머(`mp-retail-refiner` 등 3종)는 **그대로 둔다** —
KEDA 가 lag 0 을 보고 0으로 내리므로 자원을 안 먹고, 되돌리기가 인자 하나 복원으로 끝난다.

**되돌리기** — `--kafka` 를 다시 넣는다. 토픽·컨슈머그룹·오프셋이 그대로라 즉시 복귀한다.

### 5-b. Kafka 삭제 (되돌리기 비용이 처음으로 커지는 지점)

순서가 있다 — 뒤집으면 ArgoCD 가 지운 것을 되살린다:

1. ArgoCD Application `kafka` · `strimzi-operator` 를 **먼저** 비자동화하거나 제거
   (안 하면 매니페스트만 지워도 self-heal 이 되돌린다)
2. config 에서 구 컨슈머 3종 Deployment + ScaledObject(kafka 트리거) 삭제
3. `data/kafka/**` · `platform/strimzi/**` 삭제 → PDB 3개 · KafkaTopic · KafkaNodePool · kafka-exporter 동반 소멸
4. `strimzi-system` ns 삭제
5. `pipelines/base/configmap.yaml` 에서 `KAFKA_BOOTSTRAP` 제거
6. app 레포: `pipelines/stream/consume_*.py`·`produce_*.py`·`_kafka.py`·`_dlq.py`·`create_topics.py`·
   `replay_dlq.py` 정리 (**0-29 의 답이 필요하다** — `_dlq.py` 의 `record_savepoint`·`is_permanent` 는
   Kafka 무관이고 새 경로가 쓰고 있으니 그 둘은 살려서 옮긴다)
7. 크롤러 Dockerfile 에서 `confluent-kafka` 와 `pipelines/stream/*` COPY 정리

회수: **950m CPU / 3,456 MiB**.

**되돌리기** — 여기서부터는 "Strimzi 재설치 + 토픽 재생성"이다. 데이터는 안 돌아온다(오프셋·미처리 메시지 소멸).
그래서 5-b 는 **4단계가 최소 3주기 이상 무사한 뒤**에 한다.

---

## 아직 안 정해진 것

| # | 항목 | 막고 있는 것 |
|---|---|---|
| ① | `mp-user-event-sink` · `mp-price-anomaly-notifier` 처분 | **#585 답**(08-12). 자생 토픽 2종을 PG 직접 쓰기로 갈지 SQS 경유로 갈지 |
| ② | `pipelines/stream/` 15개 모듈 처분 (0-29) | ① 에 종속 |
| ③ | 온프렘 정적 IAM 키 (열린 항목 ③) | 구조적으로 해소 불가 — 온프렘은 EKS 밖이라 IRSA 가 없다. 범위 축소로 갚았다(prefix 한정·신원 2분리) |
| ④ | 큐 가시성 타임아웃 900s 의 적정성 | 3단계에서 객체 1개 처리 시간을 재고 나서 조정 |
