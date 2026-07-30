# AI 파트 인프라 배선 리포트 — 2026-07-30

내가 **직접 적용한 것**, **담당자가 해야 하는 것**, **권한이 막혀 사용자가 실행해야 하는 것**을
분리해 적었다. 각 항목은 실측 근거를 달았다.

---

## 0. 이 클러스터에서 무엇이 가능하고 무엇이 불가능한가 (배선 설계의 전제)

배선을 시작하기 전에 클러스터 구조를 먼저 읽었고, 그 결과가 아래 설계를 전부 결정했다.

| 실측 | 배선에 미친 영향 |
|---|---|
| `app` 네임스페이스 전체가 **ArgoCD 관리** (`mp-ocr` Application `Synced`) | Deployment·ExternalSecret 을 `kubectl` 로 고치면 **다음 git 동기화 때 조용히 사라진다** → 영구 수단으로 부적합 |
| `syncPolicy.automated.selfHeal: **false**`, `prune: **false**` | 수동 변경이 즉시 되돌려지진 않는다. 그래서 더 위험하다 — 한동안 잘 돌다가 무관한 커밋 하나에 원복된다 |
| 매니페스트 정본 = **별도 저장소 `happyInit/mealplanning-config`** | 접근 불가(404). 매니페스트 변경은 **내가 못 한다** → 아래 §2 로 넘긴다 |
| `prune: false` 덕분에 ArgoCD 가 **미추적 리소스를 지우지 않는다** | 내가 만든 KafkaTopic 은 **안전하게 생존한다** → 토픽은 직접 만들 수 있다 |
| ESO 백엔드 = `fb-secrets/app-secrets`, **ArgoCD 비관리**(tracking-id 없음) | **시크릿 값은 내가 직접·영구적으로 넣을 수 있다** |
| `mp-ocr` 에 `envFrom: secretRef: mp-ocr-secrets` 가 **이미 걸려 있다** | 키를 env 로 받으면 **Deployment 를 아예 안 고쳐도 된다** ← 이게 §1.1 설계의 근거 |
| `app` ns = PodSecurity **enforce=restricted**, uid 10001, `readOnlyRootFilesystem` | 키를 **파일로 마운트하려면** 볼륨·`defaultMode`·마운트 경로까지 Deployment 를 고쳐야 한다 → 피했다 |

> **설계 원칙:** 배선 diff 가 작을수록 운영에서 깨질 자리가 적다.
> 그래서 "파일 마운트 + Deployment 수정" 대신 "env + ExternalSecret 한 줄"을 골랐다.

---

## 1. 내가 직접 적용한 것 ✅

### 1.1 Vertex 자격증명을 env(JSON 원문)로 받는 경로 — 코드 완료

`services/ocr/app/pipeline/backend/genai_client.py` 에 `GCP_SA_KEY_JSON` 경로를 추가했다.

- **하위호환**: 값이 비면 **종전 ADC 자동탐색 그대로**다. 로컬·CI 는 영향 없다.
- **스코프 명시**: `cloud-platform`. 서비스 계정 자격증명은 스코프가 비면 403 으로 떨어져
  "키는 맞는데 권한이 없다"는 혼란스러운 실패가 된다.
- **키 유출 차단**: 예외 메시지에 키 원문을 넣지 않는다. 테스트로 고정했다.

**검증**: `GOOGLE_APPLICATION_CREDENTIALS` 를 **지운 상태에서** 실제 SA 키 JSON 만으로
`gemini-3.5-flash-lite` 실호출 성공. 잘못된 값 2종(비 JSON·형식 불일치)이 각각 다른
메시지로 거부되고 키가 새지 않는 것도 확인. OCR 테스트 **34건 통과**(신규 4건 포함).

### 1.2 `price.anomaly.detected` 토픽 생성 — **운영 구멍이었다**

`.dlq` 는 있는데 **본 토픽이 없었다.** 클러스터가 `auto.create.topics.enable=false` 라,
없는 토픽에 produce 하면 `produce()` 는 성공한 것처럼 반환되고 **`flush()` 에서야 타임아웃**한다.
→ 로그에는 "발행함"만 남고 **알림은 전량 유실**된다. 가장 나쁜 실패 모양이다.

DLQ 5개를 먼저 만들면서 본 토픽은 이미 있는 줄로 넘긴 것이 원인이다.
나머지 4개 컨슈머의 본 토픽(`retail.crawl.raw`·`retail.deal.raw`·`recipe.crawl.raw`·
`events.user.activity`)은 정상 존재한다.

- 매니페스트: `deploy/k8s/price-anomaly-topic.yaml` (파티션 3 / 복제 3 / 보존 7d)
- **적용 완료 · `READY=True` 확인**

### 1.3 `retail_product.volume_ml` 백필 — 0% → 101건 (#286)

상품명 파싱을 **SQL 뷰에서 파이썬 쓰기 시점으로** 옮겼다(`retail_norm.parse_volume_ml`).

**발견한 살아있는 오류**:

```
Ai선별 제주 하우스감귤 2kg(L-2L)   → 뷰가 `2L` 을 2,000ml 로 읽어 895원/100ml
```

`L-2L` 은 농산물 **크기 등급**(S/M/L/2L/3L)이지 부피가 아니다. **2kg 감귤 박스에 부피
단가가 붙어 있었다.** 터지지 않는 실패라 아무도 몰랐다.

- 운영 5,495건 실측: 부피 표기 106건 중 **101건 산출**. 못 읽은 5건은 **전부 올바른 거부**
  (감귤 `L-2L`, 계란 `2XL(왕란)`×2, `200g/L사이즈`, `LA 갈비 500g`) → 진짜 부피 상품은 100%.
- 묶음은 **곱한다**(`65ml×20개`→1,300). 65 로 두면 100ml 단가가 20배 부푼다.
- **모르면 None.** NULL 은 단가가 안 나올 뿐이지만, 틀린 숫자는 조용히 잘못된 가격을 판다.
- **백필 101행 적용 완료.** 테스트 23건 추가(파이프라인 전체 139건 통과).

### 1.4 #57 — 이미 해결돼 있음을 실측 확인 후 종료

레시피 품질 게이트는 **이미 STOP 인지로 고쳐져 있고 운영 색인에도 반영돼 있었다.**

| 지표 | 값 |
|---|---|
| 구(strict) 게이트 | 4,069 |
| 신(STOP 인지) 게이트 | **5,639** |
| **ES `recipes` 인덱스 문서 수** | **5,639** ← 정확히 일치 |

이슈의 구체 사례 `야들한 소갈비찜`(id=7979)도 `GET /recipes/_doc/7979` → `found: true`.
근거를 달아 **이슈 종료**했다.

---

## 2. 담당자 몫 — `mealplanning-config` 저장소 변경 (내가 접근 불가)

아래 두 곳만 고치면 Vertex 전환이 끝난다. **Deployment 볼륨·securityContext 는 건드리지 않는다.**

### 2.1 `ExternalSecret mp-ocr-secrets` — 항목 1개 추가

`services/ocr/overlays/onprem` 경로. 기존 3개(`PGPASSWORD`·`JWT_SECRET`·`GEMINI_API_KEY`) 아래에:

```yaml
  - secretKey: GCP_SA_KEY_JSON
    remoteRef:
      key: app-secrets
      property: GCP_SA_KEY_JSON
```

> 값은 이미 백엔드 시크릿에 넣어야 한다 → §3.1 (사용자 실행분).

### 2.2 `Deployment mp-ocr` — env 3개 추가

기존 `OCR_BACKEND` 옆에 나란히. **이 3개는 비밀이 아니다** — 롤백 레버라서 git diff 로
보이는 편이 낫다.

```yaml
  - name: GENAI_BACKEND
    value: "vertex"          # 문제 시 "api_key" 로 되돌리면 즉시 원복
  - name: GCP_PROJECT_ID
    value: "mealplanning-503911"
  - name: GCP_LOCATION
    value: "global"
```

> ⚠️ **`GCP_LOCATION=global` 인 이유** — `gemini-3.5-flash-lite` 가 `asia-northeast3`(서울)에
> **아직 배치되지 않았다.** 영수증은 개인정보라 리전 고정이 원칙이지만, 현재 모델이 리전
> 배치 이전이라 불가피하게 global 로 간다. 서울 배치 후 이 값만 바꾸면 된다.
> (그래서 코드는 `GCP_LOCATION` 에 **기본값을 두지 않는다** — 조용히 글로벌로 붙는 일이 없어야 한다.)

### 2.3 아직 매니페스트가 없는 것들

| 대상 | 파일(내 저장소에 준비됨) | 비고 |
|---|---|---|
| #9 이상탐지 스케줄 | `deploy/k8s/price-anomaly.yaml` | 토픽은 §1.2 로 준비 완료 |
| video 라우트·오버레이 | `deploy/k8s/video-route.yaml` | **이미지 미빌드** — Jenkinsfile 에 `video` 항목은 추가함 |
| DLQ 알림 | `deploy/k8s/dlq-alert.yaml` | 토픽 5개는 적용 완료 |
| 데이터 불변식 검사 | `deploy/k8s/data-invariants.yaml` | |
| 소비기한 재계산 | `deploy/k8s/pantry-expire-recompute.yaml` | 현재 대상 0건(§4.3) |
| OCR 드리프트 카나리 | `deploy/k8s/ocr-config-canary.yaml` | |

---

## 3. 권한이 막혀 **사용자가 직접 실행**해야 하는 것

두 명령 모두 자동 권한 분류기에 차단됐다(자격증명 주입 · 파괴적 DDL). 우회하지 않았다.

### 3.1 SA 키를 백엔드 시크릿에 넣기

```bash
base64 -w0 ~/.gcp/mp-vertex-ai.json | ssh ubuntu@192.168.0.17 \
  'B64=$(cat); umask 077; printf "{\"data\":{\"GCP_SA_KEY_JSON\":\"%s\"}}" "$B64" > /tmp/.p$$.json; \
   kubectl -n fb-secrets patch secret app-secrets --patch-file /tmp/.p$$.json; rm -f /tmp/.p$$.json'
```

- **`patch` 여야 한다.** `create --dry-run | apply` 는 시크릿을 통째로 교체해 기존 11개 키를 날린다.
- 값은 stdin 으로만 흐른다 — 명령행에 넣으면 `ps`·셸 히스토리에 남는다.
- **영향 범위 0**: 기존 ExternalSecret 들은 `property` 로 키를 골라 읽으므로,
  §2.1 이 적용되기 전까지 이 키를 읽는 곳이 없다.

### 3.2 `retail_unit_price` 뷰 마이그레이션

```bash
ssh ubuntu@192.168.0.17 'kubectl -n data exec -i pg-1 -c postgres -- \
  psql -U postgres -d foodbudget -v ON_ERROR_STOP=1 -f -' \
  < ~/food-budget-app/docs/prd/migrations/2026-07-30l_volume_ml_view.sql
```

- **`BEGIN; … ROLLBACK;` 예행으로 이미 검증했다.** 의존 뷰 2개
  (`retail_item_piece_compare`·`retail_item_price_compare`)가 정상 복원됨(127·377행).
- 물질화 뷰라 `CREATE OR REPLACE` 가 안 되어 `DROP … CASCADE` 가 들어간다. 그래서 차단됐다.
- **적용 효과**: 부피 단가 80 → 79. 줄어드는 1건이 §1.3 의 감귤이다 — **정당한 손실 0**.

---

## 4. 운영에서 "동작 X" 였던 항목 처리 결과

| 항목 | 이전 | 지금 |
|---|---|---|
| #9 발행 경로 | ❌ 토픽 없음 → 알림 전량 유실 | ✅ **토픽 생성·READY** (스케줄 배포는 §2.3) |
| #57 서빙 제외 | ❌ 1,308건 억울한 탈락 | ✅ **이미 해결됨 확인**(색인 5,639) · 이슈 종료 |
| #286 부피 단가 | ❌ 0% + 감귤 오류 | ✅ **백필 101건** · 뷰는 §3.2 대기 |
| Vertex 전환 | ❌ 자격증명 경로 없음 | ✅ **코드·실호출 검증 완료** · 배선은 §2·§3.1 |
| #11 video | ❌ 이미지 없음 | ⏸️ Jenkinsfile 항목 추가함. 빌드는 CI 게이트 정상화 후 |
| #10 리뷰 자동화 | ❌ AWS 자격증명 없음 | ⏸️ §6 가이드 |

### 4.3 소비기한 — 미검수 상태로 진행한 결과

`shelf_life_ref`: CURATED 467 · **AI_DRAFT 153(미검수, 전부 FRIDGE)** · FOODKEEPER 1,111.

**미검수는 병목이 아니었다.** AI_DRAFT 153건은 이미 적재돼 있고, 조회는
`CURATED → FOODKEEPER → AI_DRAFT` 순이라 검수본을 덮지 않는다.

`expire_at` 재계산을 운영에 돌려본 결과 **대상 0건**이다. ACTIVE 81건 중 `expire_at` 이
NULL 인 25건의 내역:

- `item_id` 없음 **5건** (`아이스크림`·`황도 825G`·`야채` — 품목 매칭 실패)
- 참조표 없음 **7건**
- 참조표 있으나 **결과가 과거 13건** ← 등록일이 7/16~20 이라 보존일을 더해도 이미 지났다

마지막 13건이 0건의 이유이고, **이것은 의도된 동작이다** — 행동 가능성이 없는 알림을
만들지 않는다(안전규칙 2). 즉 검수를 기다릴 이유가 없었고, 지금 검수해도 결과는 같다.

---

## 5. gazetteer 정책 (#130) — 지금 골라야 하는 것과 그 이유

### 왜 선택이 필요한가

NER 은 문장에서 **스팬만** 뽑는다. 그 스팬을 표준코드로 바꾸는 건 `item_master`/alias 몫이다.
→ **NER 정확도의 상한이 이 정규화 계층에 걸린다.** 지금 `make_matcher` 의 strip 매칭이
수식어를 무차별로 벗겨 체계적으로 오분류한다:

```
간장게장 → 간장      🔴 게장이 완전 오분류 (prefix strip)
양념치킨 → 닭고기    ⚠️ 조리형태 소실
대추방울토마토 → 방울토마토
볶음김치·열무김치 → 김치
```

개별 케이스를 땜빵하면 다음 케이스가 또 나온다. **규칙을 정해야 끝난다.**

### 골라야 하는 것 ① — 보존 세트를 **코드**에 둘까 **데이터**에 둘까

이게 진짜 결정이다(PR #54 의 열린 Q4).

| | A. `gazetteer.py` 코드 상수 | B. `item_master` 메타(데이터) |
|---|---|---|
| 누가 고치나 | **나(AI 파트)** | 태현(데이터 오너) |
| 반영 속도 | 배포 필요 | **DB 업데이트 즉시** |
| 리뷰 | git diff 로 보임 | DB 변경은 이력이 약함 |
| 테스트 | **단위 테스트로 고정 가능** | 재현 테스트가 어려움 |
| 적합한 것 | 매칭 **로직**, 소수의 안정적 상수 | 품목별 예외, 계속 늘어나는 목록 |

**내 권고 = 갈라서 둔다.**
- **로직**(strip 순서·exact 우선·토큰 경계) → 코드. 테스트로 고정된다.
- **보존 수식어 클래스 목록**·별칭 감사 결과·granularity 판정 → **데이터**. 계속 늘어나고,
  판단 주체가 데이터 오너다.

지금 막혀 있는 건 이 경계에 대한 **합의**다. 코드로 정하면 내가 오늘 진행할 수 있고,
데이터로 정하면 `item_master` 스키마에 컬럼이 필요해 태현과 일정을 맞춰야 한다.

### 골라야 하는 것 ② — granularity 기준 (약 258건이 여기 걸림)

복합어를 **별도 품목으로 둘지, base 로 뭉갤지**의 일관 규칙:

| 후보 | 규칙 | 결과 예시 | 대가 |
|---|---|---|---|
| **가**. 가격 비교 가능성 기준 | 소매에서 **따로 팔리면** 별도 품목 | 방울토마토≠토마토, 열무김치≠김치 | 품목 수 증가, 매칭률 하락 |
| **나**. 조리 대체 가능성 기준 | 레시피에서 **바꿔 쓸 수 있으면** 같은 품목 | 대추방울토마토=방울토마토 | 최저가 비교가 부정확해짐 |
| **다**. 혼합(권고) | **가격은 가**, 레시피 매칭은 **나** | 두 레이어를 따로 | 매핑 테이블 유지비 |

우리 서비스는 **최저가 비교가 핵심**이라 가격 축에서는 `가`가 맞다. 다만 레시피 재료
매칭까지 `가`로 가면 매칭률이 떨어진다. 그래서 **다(혼합)** 를 권고한다.

### 즉시 처리 가능한 것 (정책과 무관)

- ③ **prefix strip 금지** — `간장게장 → 간장` 은 명백한 오분류다. 정책 논의 없이 지금 끌 수 있다.
- ④ **짧은 별칭(≤2자) 323개 감사** — "독립 토큰일 때만 매칭"으로 좁히면 오탐이 크게 준다.
  ⚠️ 단, `닭`·`배`·`굴` 처럼 **진짜 1글자 품목**이 있어 일괄 삭제는 안 된다(과거에 내가
  `length<=1` 로 자르려다 이 셋을 잡을 뻔했다).

> **결정만 주면**: ③④ 는 오늘 진행, ①② 는 합의 후 진행.

---

## 6. AWS 키 발급 가이드 (#10 리뷰 감성분석용)

팀장 계정으로 **IAM 사용자**를 만들어 **Bedrock 전용 권한만** 준다. 루트 키는 절대 쓰지 않는다.

### 6.1 콘솔 절차

1. AWS 콘솔 → **IAM** → 사용자 → **사용자 생성**
   - 이름: `mp-bedrock-review` (용도가 이름에 드러나야 나중에 회수 판단이 쉽다)
   - **콘솔 액세스 체크 해제** — 프로그래밍 방식만 쓴다
2. **권한 직접 연결** → 정책 생성 → JSON 에 아래를 넣는다

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["bedrock:InvokeModel"],
    "Resource": [
      "arn:aws:bedrock:ap-northeast-2::foundation-model/anthropic.claude-3-5-sonnet-*",
      "arn:aws:bedrock:ap-northeast-2::foundation-model/amazon.nova-micro-*"
    ]
  }]
}
```

> `AmazonBedrockFullAccess` 를 붙이지 마라. 모델 학습·프로비저닝까지 열린다.
> **필요한 건 `InvokeModel` 하나뿐이다.**

3. 사용자 → **보안 자격 증명** → **액세스 키 만들기** → 사용 사례 **"애플리케이션 외부에서 실행"**
4. `Access key ID` + `Secret access key` 를 받는다. **Secret 은 이 화면에서만 보인다.**

### 6.2 사전 확인 — 모델 액세스

Bedrock 은 계정별로 모델을 **먼저 활성화**해야 한다.
콘솔 → **Bedrock** → `ap-northeast-2`(서울) → **Model access** →
`Claude 3.5 Sonnet`·`Nova Micro` **Request access**. 승인 전에는 키가 맞아도 `AccessDenied` 다.

### 6.3 클러스터에 넣기

§3.1 과 같은 방식으로 `fb-secrets/app-secrets` 에 두 키를 추가하고,
`mp-*-secrets` ExternalSecret 에 항목을 추가한다(§2.1 과 동형).

```
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_REGION=ap-northeast-2
```

> 파이프라인 이미지에는 `boto3>=1.35` 를 이미 넣어 뒀다(`pipelines/ingest/requirements.txt`).

### 6.4 주의

- **키를 저장소에 커밋하지 마라.** 루트의 `geonu_accessKeys.csv` 는 `.gitignore` 에 잡혀
  추적되지 않는 것을 확인했다(유출 아님). 그대로 두면 된다.
- 90일 주기 회전을 권한다. IAM → 액세스 키 → 비활성화 후 삭제.

---

## 7. CI 게이트(#389) — PR 체크 X 표시의 원인

### 관측

| PR | 커밋 수 | Jenkins `pr-merge` |
|---|---|---|
| #373 | 1 | **SUCCESS** |
| #379 | 4 | ERROR |
| #397 | 6 | ERROR |
| #387 | 26 | ERROR → (재푸시 후) **PENDING** |

에러 메시지: `This commit cannot be built`.

### 해석

**단일 커밋만 성공하고 다중 커밋이 실패**하는 패턴이다. 이 메시지는 Jenkins GitHub Branch
Source 가 **PR 을 대상 브랜치와 병합한 커밋을 만들지 못했을 때** 낸다 — 빌드 실패가 아니라
빌드 **이전** 단계다. 원인은 **shallow clone** 으로 보인다.

이건 #389 에서 내가 미리 적어둔 그 지점이다:

> ⚠️ 3점 diff(`origin/${CHANGE_TARGET}...HEAD`)는 **non-shallow 클론 전제** →
> Multibranch 컷오버 시 shallow 해제 필요(**STEP3**)

**STEP3 없이 Multibranch 가 켜진 상태**로 보인다.

### 확인이 필요한 부분

Jenkins(`192.168.0.10:8081`)가 익명 접근에 **403** 을 주어 빌드 로그를 못 봤다. 위는
상관관계 기반 추정이고, 로그 한 줄이면 확정된다. **인프라 담당 확인 요청** —
Multibranch 잡의 **Behaviours → Advanced clone behaviours → Shallow clone 해제**
(또는 depth 를 충분히 크게).

---

## 8. 열린 PR 충돌 현황

**충돌난 PR 3건은 전부 `wjsusl98-cloud` 소유**다 — 내(`ge-onu`) PR 이 아니라 내가 고칠 수 없다.

| PR | 작성자 | 규모 | 상태 |
|---|---|---|---|
| #367 fix(k8s) 그라파나 계정 소멸 | wjsusl98-cloud | 1 파일 +6/-1 | CONFLICTING |
| #317 docs 부하테스트 통합 | wjsusl98-cloud | 17 파일 +470/-1,736 | CONFLICTING |
| #315 docs 보안 준수사항 통합 | wjsusl98-cloud | 7 파일 +53/-350 | CONFLICTING |
| **#387 (내 것)** | ge-onu | — | **MERGEABLE** ✅ |

#367 은 1파일 6줄이라 리베이스가 쉽고, #317·#315 는 문서 대량 삭제라 main 의 후속 문서
변경과 부딪힌 것으로 보인다. **작성자에게 리베이스 요청**이 맞다.

`#399` 는 `happyInit` 이 올린 **폐기용 PR**이다(제목에 `throwaway, DO NOT MERGE`).
#389 게이트 검증용이라 그대로 두면 된다.

모든 열린 PR 이 `BLOCKED / REVIEW_REQUIRED` 다 — **리뷰 승인이 있어야 병합된다.**

---

## 9. 담당자별 요약

**인프라 담당**
1. `mealplanning-config` — ExternalSecret 항목 1개(§2.1) + Deployment env 3개(§2.2)
2. Jenkins Multibranch **shallow clone 해제**(§7) ← PR 체크 X 의 원인
3. §2.3 매니페스트 6종 반영

**데이터 담당(태현)**
4. gazetteer 정책 ①②(§5) — 코드/데이터 경계와 granularity 기준

**건우(나) — 결정 나오면 즉시**
5. gazetteer ③④(prefix strip 금지·짧은 별칭 감사)는 **정책과 무관하게 바로 가능**
6. video 이미지 빌드(CI 게이트 정상화 후)

**사용자 직접 실행**
7. §3.1 SA 키 주입 · §3.2 뷰 마이그레이션 · §6 AWS 키 발급
