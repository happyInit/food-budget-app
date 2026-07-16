# PGSync 도입 런북 (PG→ES 색인 동기화)

정본 결정: `docs/design.md` §330 (PGSync 채택, 2026-07-14). 이 문서 = **착수 런북**(프리컨디션·유지보수창·브링업 절차). 배경/결정 근거는 PR·설계문서 참조.

## 왜 / 현재
- 현재 PG→ES 색인 = **cron 폴러 `poller-es-recipes`**(주2회 전량 재색인, PR #96) — 퀵윈이자 폴백.
- 목표 = **PGSync**로 준실시간 CDC 동기화(레시피 변경 → ES 즉시 반영). 완성 후 cron 은 DR 폴백으로 보존.
- PGSync 7.1.0 = `wal_level=logical` 논리슬롯(내장 `test_decoding`) + 트리거(`pg_notify`) 기반. Redis = 체크포인트/큐.

## Phase 0 실측 (2026-07-16, `.8`)
- PG `tfstate-db` = **postgres 16.14**, 슈퍼유저 `terraform`, 앱DB `foodbudget`(소유 `fbapp`). `wal_level=replica`, slots/senders **10/10**(PGSync 는 슬롯 1 필요), `max_wal_size` 1GB, **슬롯 0개**, pg_wal 80MB.
- `recipe`/`recipe_ingredient` 소유 `fbapp`, PK 있음, **6786/52994**행. ES `recipes` **3178 docs**(servable).
- Redis(app) `allkeys-lru`·256MB·비영속. 디스크 `/var/lib/docker` **37G 여유**·swap 0.
- ⚠️ `tfstate-db`는 **Terraform state 백엔드 겸용** → 재시작 시 tf state 접근도 잠깐 끊김.
- SSH: `ubuntu@192.168.0.8`.

## 프리컨디션 상태

| # | 항목 | 위치 | disruptive? |
|---|------|------|-------------|
| 1 | 전용 `pgsync` role + grants | 이 PR (`tfstate_db` role) | ✗ (role 생성) |
| 2 | 분리 Redis `redis-pgsync`(noeviction+AOF, :6380) | 이 PR (`data_tier` role) | ✗ (새 컨테이너) |
| 3 | 슬롯 WAL·`/var/lib/docker` 디스크 알람 | 이 PR (`alert-rules.yml`) | ✗ |
| 4 | `pgsync_db_password` 볼트 추가 | **팀** (`secrets.yml`) | ✗ |
| 5 | `wal_level=logical` + PG 재시작 | **유지보수창** | ✔ 전면다운 ~수초 |
| 6 | PGSync 서비스 + `schema.json` + 게이트 | **다음 PR**(결정 후) | ✗ |

## 적용 순서

### A. 비-disruptive (이 PR 머지 후 — 재시작 없음)
1. `infra/ansible/secrets.yml` 에 `pgsync_db_password` 추가 (`app_db_password` 와 같은 곳).
2. ansible 재실행 → pgsync role·grants·`redis-pgsync`·알람 적용. **PG 재시작 없음**(role 생성·새 컨테이너뿐).
3. 검증:
   ```bash
   docker exec tfstate-db psql -U terraform -d foodbudget -c "\du pgsync"          # Replication 속성
   docker exec tfstate-db psql -U terraform -d foodbudget -c "\dp recipe"          # pgsync 에 SELECT/TRIGGER
   docker exec redis-pgsync redis-cli config get maxmemory-policy                   # => noeviction
   ```

### B. Disruptive (유지보수창 — 피크 11-12·17-18·명절·진행중 terraform 회피)
4. `wal_level` → logical:
   ```bash
   docker exec tfstate-db psql -U terraform -d foodbudget -c "ALTER SYSTEM SET wal_level='logical'"
   docker restart tfstate-db     # postgres:16 = SIGINT fast shutdown → ~수초
   docker exec tfstate-db psql -U terraform -d foodbudget -Atc "show wal_level"   # => logical
   ```
   - `ALTER SYSTEM` 은 `postgresql.auto.conf`(볼륨 영속)에 기록 → 재시작·재생성에도 유지. slots/senders 는 이미 10 이라 **변경 없음**.
   - 영향: 앱(.9)·컨슈머 4개·tf state 접근이 재시작 동안 끊김(자동 재접속). **사전 공지**.
   - IaC 대안(재현성↑, 팀 결정): `tfstate_db` compose 에 `command: ["postgres","-c","wal_level=logical"]` — 단 적용=재시작.

### C. PGSync 브링업 (다음 PR — 아래 결정 선행)
- `schema.json`(recipe root + recipe_ingredient nested), PGSync 서비스(.8, `bootstrap` → `pgsync -d`), 체크포인트, 초기싱크 → cutover(배치 인덱서와 인덱스명 충돌 회피).

## 미결정 (Phase C 전 팀 결정)
1. **servable 게이트** — PGSync 스키마엔 WHERE/filter 없음(메인테이너 확인). 두 방법:
   - **(A) 플러그인 드롭**: `_source`(부모+중첩 재료) 검사해 미매칭 재료 있으면 색인 스킵. ⚠️ delete 아님 → 나중 non-servable 되면 **stale 잔존**.
   - **(B) query-time 필터**(권장): 전건 색인 + `recipe` boolean 플래그(PG 트리거/생성컬럼) + `search.py` 필터 → 무효화 시 확실히 사라짐.
2. **ES 문서 형태** — 중첩 재료객체 vs 평탄화(현 인덱스는 `ingredient_names` 평탄) → `search.py` 쿼리 영향.
3. **체크포인트** — 파일(`CHECKPOINT_PATH` 볼륨, `REDIS_CHECKPOINT=False` 기본) vs `redis-pgsync`.

## 운영 안전장치 (필수)
- **슬롯 lag 모니터링**(이 PR): 논리슬롯이 멈추면 WAL 이 `/var/lib/docker` 에 무한 축적 → 디스크 full → PG 쓰기 전면중단. `PGReplicationSlotRetainedWALHigh`·`PGReplicationSlotInactive`·`DockerDiskUsageHigh` 가 조기경보(단일노드라 물리 안전장치 없음).
- swap 0 → 2~4G 스왑 권장(별도 작업).
- **롤백**: PGSync 중지 → `SELECT pg_drop_replication_slot('<slot>')`(WAL 즉시 해제) → (선택) 트리거·`_view`·`wal_level` 원복(재시작 필요, 가급적 유지).

## 참고
- PGSync 공식 스펙 조사(7.1.0) 요약 = 메모리 `pgsync-preconditions`.
- `design.md §330` 정합(프리컨디션 반영)·§331 servable 게이트 드리프트 정정은 후속(팀 확인).
