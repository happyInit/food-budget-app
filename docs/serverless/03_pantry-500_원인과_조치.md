# 영수증 등록 500 — 원인과 조치 (2026-08-14 실측)

## 증상

```
POST  /api/pantry/receipts        1건   InsufficientPrivilege → 500
PATCH /api/pantry/items/{item_id} 11건  InsufficientPrivilege → 500
```

OCR **분석은 성공**하고 «확인하고 등록» 에서 죽는다. 읽기 요청 실패는 0건이다.

## 원인 — **`public` 읽기 권한 하나**

라이브 PG 에 직접 물었다. `pantry` 스키마 권한은 **전부 정상**이다.

```
has_table_privilege(svc_pantry, ...)
  pantry.pantry_item  UPDATE   t
  pantry.pantry_item  INSERT   t
  pantry.ocr_receipt  INSERT   t
  public.item_master  SELECT   f     ← 🔴 이것 하나
```

두 경로가 **똑같이 `public` 을 읽는다.**

| 경로 | 부르는 함수 | 대상 |
|---|---|---|
| `POST /receipts` | `resolve_item_id`(`queries.py:38,39`) · `valid_item_id`(`:140`) | `public.item_master` · `item_alias` |
| `PATCH /items/{id}` | `lookup_shelf_life`(`:191`) — **보관 이동 시 소비기한 재계산** | `public.shelf_life_ref` |

## 왜 권한이 없었나 — **주석이 사실과 달랐다**

`docs/prd/schema-roles.sql` 이 이렇게 적고 GRANT 를 주석 처리해 뒀다.

> *"현재 pantry 서비스 코드에 **public 테이블 SQL 이 0건**이다 → 최소권한으로 안 준다"*

**0건이 아니라 4곳이다.** 그리고 같은 파일 `:175` 는 `svc_ocr` 에 **똑같은 세 테이블**을 이유로 그 롤을 주고 있다 — 형평에도 어긋났다.

🟢 설계 잘못도, 인프라 잘못도 아니다. **온프렘에서는 `fbapp` 단일 롤이라 이 경계가 없었고**, 롤 격리(`0-13`)를 EKS 에 적용하면서 드러났다. 같은 계열이 오늘만 세 번째다(#671 pgsync · #672 pgsync CREATE · 이번 pantry).

## 조치 — **두 곳을 같이 고쳐야 한다**

### ① 이 레포 — 완료

`docs/prd/schema-roles.sql` 의 거짓 주석을 정정하고 GRANT 를 살렸다.
```sql
GRANT mp_data_reader TO svc_pantry;   -- public.item_master · item_alias · shelf_life_ref
```

### ② 🔴 config 레포 — **미완. 이게 없으면 되돌아간다**

`platform/pg/overlays/eks/kustomization.yaml` 의 `svc_pantry` 항목:

```yaml
- name: svc_pantry
  inRoles: []              # ← [mp_data_reader] 로
```

**CNPG 의 `inRoles` 는 배타적**이다. ①만 적용하면 다음 reconcile 에서 **조용히 REVOKE** 되어 며칠 뒤 같은 500 이 재발한다. 같은 파일의 `svc_recipebook`·`svc_chat` 등이 이미 `[mp_data_reader]` 를 갖고 있다 — **`svc_pantry` 만 빠져 있다.**

### ③ 적용

```
kubectl -n data exec -i pg-1 -c postgres -- psql -U postgres -d foodbudget \
  -v ON_ERROR_STOP=1 -f - < docs/prd/schema-roles.sql
```
멱등이라 재실행이 안전하다(파일 13행).

## 검증

```sql
SELECT has_table_privilege('svc_pantry','public.item_master','SELECT');   -- t 가 나와야 한다
```
그 뒤 영수증 등록·보관 이동을 다시 시도한다.
