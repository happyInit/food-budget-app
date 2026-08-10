# config 레포 인계 명세 — 보안 3건 (0-14c · 0-14d · prom-operator PoLP)

> 이 세 건은 **`happyInit/mealplanning-config` 에서 고쳐야 한다.** 앱 레포에서 할 수 있는 게 없어
> "무엇을 어떻게 바꿔야 하는지"만 적어 넘긴다.
> 실측은 전부 2026-08-09 라이브 기준이고, **값은 한 번도 조회하지 않았다**(이름·개수만).

관련: `docs/mp_aws_prep_checklist.md` (0-14c · 0-14d · 0-16 · C-24) · `docs/mp_k8s_rbac_plan.md` §11~§13

---

## A. 0-14c — 워크로드별 ServiceAccount 신설

### 지금 상태 (실측)

| ns | 워크로드 | `default` SA 사용 | 전용 SA |
|---|---|---|---|
| **app** | **14** (Deploy 11 + Rollout 2 + CronJob 1) | **14 / 14** | 0 |
| **pipeline** | **23** (Deploy 5 + CronJob 17 + 단독 Job 1) | **23 / 23** | 0 |
| data | 11 | 8 | 3 (CNPG `pg`·`pg-pooler`, Strimzi `kafka-kafka`) |
| observability | 9 | 0 | 9 |

app·pipeline 에 존재하는 SA 는 **`default` 하나뿐**이다.

⚠️ 체크리스트는 pipeline 을 22 로 센다. Deploy 5 + CronJob 17 기준이면 맞고,
소유자 없는 단독 Job `mp-reindex-recipes-es`(2026-07-29 생성, 11일째 잔존)를 포함하면 **23** 이다.

### 왜 0-16 의 선행인가

```
① 을 건너뛰고 Pod Identity association 을 걸면
   → 롤이 `default` SA 에 붙는다
   → pipeline 23개 워크로드가 **전부** 그 IAM 권한을 갖는다
   → 폭발 반경 불변. "0-16 완료" 체크하고도 실제 보안 개선이 0이다
```

C-24 의 **층2 방어**(association 을 특정 SA 에만 + 롤 자체를 최소권한)가 이것 없이는 성립하지 않는다.

### 🔴 함정 — SA 를 새로 만들면 이미지 pull 이 죽는다

**`imagePullSecrets` 를 SA 가 단독 공급하고 있다.**

- `default` SA 에 `imagePullSecrets: [harbor]` 가 걸린 ns = **app · pipeline · data · mp-ingress** 4곳
- Harbor(`192.168.0.10`) 이미지를 쓰는 워크로드 **41개 중 40개가 podspec 에 `imagePullSecrets` 를 안 적었다** — 전적으로 `default` SA 에서 상속받는다
- 예외 1건 = `argo-rollouts/rollouts-argo-rollouts` (전용 SA + podspec 에 직접 명시)
- **비-default SA 중 `imagePullSecrets` 를 가진 것은 클러스터 전체에 0개**

⇒ **새 SA 에 `imagePullSecrets: [harbor]` 를 복사하지 않으면 그 워크로드는 `ImagePullBackOff` 로 죽는다.**
영향 범위는 40개다(널리 알려진 cloudflared 1건이 아니다).

### 제안 형상

```yaml
# services/<svc>/base/serviceaccount.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: mp-<서비스>                 # 🔴 CLAUDE.md 명명 규칙 = mp- 접두
  namespace: <ns>
imagePullSecrets:
  - name: harbor                    # 🔴 빠뜨리면 ImagePullBackOff
automountServiceAccountToken: false # 아래 A-2
---
# 워크로드
spec:
  template:
    spec:
      serviceAccountName: mp-<서비스>
```

**전환은 워크로드 하나씩.** SA 를 먼저 만들고(무해), 그 다음 워크로드가 그걸 가리키게 한다.
롤백 = `serviceAccountName` 한 줄 되돌리기.

### A-2. 부수 — `automountServiceAccountToken` 이 app 과 pipeline 사이에서 갈린다

| ns | true | false | 미설정 | 실제 토큰 마운트 |
|---|---|---|---|---|
| **app** | 0 | **14** | 0 | **0 / 16 파드** |
| **pipeline** | 0 | 0 | **23** | 🔴 **37 / 37 파드 전부** |

파드 `.spec.volumes` 의 `kube-api-access-*` projected 볼륨 유무로 전수 확인한 실측이다(추정 아님).

현재 `pipeline/default` SA 의 실효 권한은 discovery 수준이라 **당장의 피해는 없다.**
문제는 **누군가 `default` SA 에 RoleBinding 을 하나 붙이는 순간 23개 워크로드가 동시에 그 권한을 얻는다**는 것이다.
→ SA 분리와 **같은 PR 에서** `automountServiceAccountToken: false` 를 함께 넣는다.

---

## B. 0-14d — `mp-pipeline-secrets` 를 db용 / aws용 2개로 분리

### 지금 상태 (실측)

`pipeline/mp-pipeline-secrets` = **6키**

| 키 | 크기 | 분류 |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | 20 B | 🟠 AWS |
| `AWS_SECRET_ACCESS_KEY` | 40 B | 🟠 AWS |
| `ES_PASSWORD` | 40 B | DB |
| `PGPASSWORD` | 8 B | DB |
| `DATA_GO_KR_SERVICE_KEY` | **0 B** | DB(빈 값) |
| `REPORT_GEMINI_API_KEY` | **0 B** | DB(빈 값) |

🔴 **주입 방식이 전부 `envFrom.secretRef` 한 가지다.** `env[].valueFrom.secretKeyRef` **0건** ·
`volumes[].secret` **0건** → **어떤 워크로드도 개별 키를 고르지 않는다. 전원이 6키 전량을 받는다.**
그래서 AWS 키만 빼는 것이 불가능하고, 분리가 필요하다.

### 자격증명 보유 : 실제 사용

**22 : 2.** `boto3`/`bedrock` 을 import 하는 파이프라인 파일은 3개인데 그중 매니페스트가 있는 건 2개다:

| 파일 | 매니페스트 |
|---|---|
| `pipelines/ingest/score_review_sentiment.py` | CronJob `mp-score-review-sentiment` |
| `pipelines/ingest/summarize_reviews.py` | CronJob `mp-summarize-reviews` |
| `pipelines/ingest/draft_shelf_life.py` | ❌ **없음** (docstring 의 수동 CLI 뿐) |

나머지 20개는 AWS 키를 **받기만 하고 안 쓴다**.

### 소비 객체 수 — 58 이지만 사람이 고칠 건 23

| | 수 | 비고 |
|---|---|---|
| 매니페스트 | **22** | Deployment 5 + CronJob 17 |
| 런타임 Job | **36** | 35 = CronJob 의 자식 · 1 = 소유자 없는 단독 Job |
| 합 | 58 | ⚠️ **중복 포함**(35개는 17개 CronJob 이 낳은 것) |
| **사람이 작성한 오브젝트** | **23** | Deploy 5 + CronJob 17 + 단독 Job 1 |

**Job 정리 상태**: `ttlSecondsAfterFinished` **설정 0건**(Job 36/36 · CronJob 17/17 미설정).
축적이 36 에서 멈춘 건 TTL 때문이 아니라 `successfulJobsHistoryLimit=2` / `failedJobsHistoryLimit=3` /
`concurrencyPolicy=Forbid` 덕이다.
🔴 **예외 1건** — 단독 Job `mp-reindex-recipes-es` 는 소유 CronJob 이 없어 GC 주체도 TTL 도 없다 → **11일째 잔존**.
전환할 때 이 Job 은 손으로 지워야 한다.

### 제안 형상

```yaml
# ① db용 — 20개 워크로드가 이것만 받는다
mp-pipeline-secrets        # ES_PASSWORD · PGPASSWORD · DATA_GO_KR_SERVICE_KEY · REPORT_GEMINI_API_KEY
# ② aws용 — 2개 CronJob 만 추가로 받는다
mp-pipeline-aws-secrets    # AWS_ACCESS_KEY_ID · AWS_SECRET_ACCESS_KEY

# 워크로드
envFrom:
  - secretRef: { name: mp-pipeline-secrets }
  - secretRef: { name: mp-pipeline-aws-secrets }   # ← score-review-sentiment · summarize-reviews 에만
```

ExternalSecret 도 둘로 나눈다(원본은 `fb-secrets/pipeline-secrets` 그대로, `remoteRef` 만 갈라 쓴다).

**전환 순서** (무중단)
```
1) mp-pipeline-aws-secrets ExternalSecret 신설      ← 아무도 안 씀. 무해
2) AWS 쓰는 CronJob 2개에 envFrom 추가              ← 이 시점에 양쪽에서 같은 키를 받는다
3) mp-pipeline-secrets 에서 AWS 키 2개 제거          ← 여기서 20개가 자격증명을 잃는다
4) 잔존 Job 정리: mp-reindex-recipes-es 수동 삭제
5) 다음 스케줄에서 CronJob 2개가 정상 도는지 확인
```
🔴 3번 뒤 첫 실행까지 최대 **3.5일**이 빈다(`mp-score-review-sentiment` = `0 7 * * 0,3`).
그 사이엔 깨져도 모른다 → 3번 직후 `kubectl create job --from=cronjob/…` 로 한 번 수동 실행해 확인할 것.

### 🔴 0-16 범위 정정도 함께

정적 AWS 키는 **2세트**다. 체크리스트가 pipeline 만 세고 있었다.

| 시크릿 | 판정 | 근거(실측) |
|---|---|---|
| `pipeline/mp-pipeline-secrets` | 🟠 **AWS** | 위 |
| `data/mp-pg-backup-s3` | 🟠 **AWS** | ObjectStore `mp-pg-backup` → `endpoint=https://s3.ap-northeast-2.amazonaws.com` |
| `data/mp-pg-onsite-minio` | 🟢 **MinIO** | 소비자 CronJob 의 `MINIO_ENDPOINT=http://minio.observability.svc:9000` |
| `observability/lgtm-minio-creds` | 🟢 **MinIO** | loki·tempo 가 envFrom 으로 소비. ESO 관리도 아니다 |

⚠️ **뒤 둘을 범위에서 명시적으로 빼지 않으면 "정적 키 0" 목표가 영원히 미달성으로 보인다.**
Pod Identity 로 대체 불가능한 것들이다(MinIO 는 AWS 가 아니다).

---

## C. `kube-prometheus-stack-operator` 의 전역 secrets 권한 (신규)

### 왜 이게 안건인가

RBAC 작업(0-14) 중 실측된 상승 경로의 **중간 노드**다.

```
observability ns 에 쓰기 권한이 있는 사람
  └ (SA 토큰 발급 · exec · pods create · deployments patch 중 아무거나)
     └ SA observability/kube-prometheus-stack-operator
          ClusterRole 규칙 = {apiGroups:[""], resources:[configmaps, secrets], verbs:["*"]}
          ClusterRoleBinding = **전 ns 적용**
          실측: get secrets -n {mp-users, fb-secrets, kube-system, data, app} = 전부 yes
        └ fb-secrets 37키 · CNPG 비밀번호 · 사람 토큰 전부 열람
```

앱 레포(`0-14`)에서는 **사람 쪽 권한을 좁혀** 이 노드에 못 닿게 막았고(관측 티어에서 워크로드 쓰기 제거),
`mp-users` 의 admin 장수 토큰을 없애 **종착지**도 잘랐다.
남은 건 **노드 자체가 과대 권한**이라는 사실이고, 그건 Helm 차트 기본값이라 여기 소관이다.

### 검토 대상 (⚠️ 결정 아님 — 깨질 위험이 있어 실험이 선행돼야 한다)

prometheus-operator 는 ServiceMonitor/ScrapeConfig 가 참조하는 basicAuth·TLS Secret 을
**임의 ns 에서** 읽어야 해서 넓은 권한을 요구한다. 무작정 좁히면 스크레이프가 조용히 죽는다.

| 안 | 내용 | 위험 |
|---|---|---|
| A. `verbs` 축소 | `["*"]` → `["get","list","watch"]` | 낮음. operator 가 Secret 을 **쓰는** 경우(알림 설정 생성 등)가 있는지 확인 필요 |
| B. ns 제한 | 차트의 `namespaces.releaseNamespace`/`additional` 로 감시 ns 를 한정 | 중간. 지금 ServiceMonitor 는 여러 ns 에 있다(21개) |
| C. 유지 + 사람 쪽만 차단 | 0-14 가 이미 한 것 | 🟢 현재 상태. 추가 작업 0 |

🔴 **지금 당장 필요한 건 아니다** — 0-14 로 사람 경로가 끊겼다. 이건 심층 방어 항목이고,
**A 부터 실험**하는 것이 비용 대비 효과가 좋아 보인다. **실험 없이 적용하지 말 것.**

---

## D. 참고 — 0-15(ES PoLP)는 이미 완료돼 있다

체크리스트 `0-15` 는 *"소비자 5곳 중 4곳이 `elastic` 슈퍼유저"* 라고 적고 있으나 **현행과 다르다**(2026-08-09 실측).
이슈 #521 도 CLOSED 다.

| 소비자 | 계정 | 출처 |
|---|---|---|
| chat · recipe (app) | `mp_recipe_reader` | `app/app-common` ConfigMap |
| 파이프라인 | `mp_pipeline_writer` | `pipeline/mp-pipeline-env` ConfigMap |
| `mp-pgsync` | `mp_pgsync_writer` | env (구: `es-es-elastic-user` 직접 마운트) |
| exporter | `mp_elasticsearch_exporter` | env |

- `es-es-elastic-user` 를 직접 참조하는 워크로드 **0개** (이슈 #521 함정 ② 해소)
- ECK `spec.auth.roles` = `mp-es-roles` Secret → **롤이 IaC 안에 있다** (곁다리 발견도 해소)
- 비밀번호 3종 = `fb-secrets/data-secrets` → ESO → `data/mp-es-service-accounts`
- 코드 기본값도 `os.environ.get("ES_USER", "")` — `elastic` 폴백 없음

**남은 것은 선택사항 하나** — `spec.auth.disableElasticUser: true` 미설정(전환 순서 5단계).
켜기 전에 ECK 오퍼레이터가 `elastic` 을 안 쓰는지 확인이 선행돼야 한다(`elastic-internal` 을 따로 쓰는 것으로 보이나 미검증).
HTTP TLS 가 꺼진 것(`selfSignedCertificate.disabled: true`)은 **확정 결정대로**이고 이 항목 범위 밖이다.

→ 체크리스트의 `0-15` 를 **완료로 정정**해야 한다.
