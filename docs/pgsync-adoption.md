# PGSync 도입 런북 (PG→ES 색인 동기화)

정본 결정: `docs/design.md` §330 (PGSync 채택, 2026-07-14). 이 문서 = **착수 런북**(프리컨디션·유지보수창·브링업 절차). 배경/결정 근거는 PR·설계문서 참조.

## 왜 / 현재
- 현재 PG→ES 색인 = **cron 폴러 `poller-es-recipes`**(주2회 전량 재색인, PR #96) — 퀵윈이자 폴백.
- 목표 = **PGSync**로 준실시간 CDC 동기화(레시피 변경 → ES 즉시 반영). 완성 후 cron 은 DR 폴백으로 보존.
- PGSync **7.1.0**(공식 이미지 arm64 전용 → amd64 자체 빌드 `deploy/pgsync/Dockerfile`) = `wal_level=logical` 논리슬롯(내장 `test_decoding`) + 트리거(`pg_notify`) 기반. Redis = 체크포인트/큐. ⚠️ 데몬(`-d`)은 슬롯 자동생성 안 함 → **`bootstrap` 명령 선행 필수**.

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
| 2 | 분리 Redis `redis-pgsync`(noeviction·비영속, :6380) | 이 PR (`data_tier` role) | ✗ (새 컨테이너) |
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

### C. PGSync 브링업 (다음 PR — 위 결정 반영)
- `schema.json`(recipe root + recipe_ingredient nested — **PGSync 조립트리**; transform 플러그인이 **평탄 ES 문서**로 변환 + `servable` 계산 + 코퍼스 skip), PGSync 서비스(.8, `bootstrap` → `pgsync -d`), 체크포인트(파일), 초기싱크 → cutover(배치 인덱서와 인덱스명 충돌 회피).

## 결정 완료 (Phase C, 2026-07-16 확정)
1. **servable 게이트 = B(쿼리타임 필터)** — 전건 색인 + `servable` boolean + `search.py` `{"term":{"servable":true}}`. A(플러그인 드롭)는 non-servable 전이 시 stale 잔존이라 배제. **servable=STATIC**(gate=`source='10K'` AND 미매칭 `item_id` 0건, price/nutrition 조인 없음 — `pipelines/ingest/index_recipes_es.py` 확인) → PGSync가 native로 포착(동적 리프레시 불필요). **하이브리드**: source(10K vs 학습코퍼스 EPIS/COOKRCP01)=불변→transform-skip(코퍼스 미색인) / strict item_id매칭=변동→쿼리 flag. flag=transform 계산(검색 전용, `get_detail`은 PG 직접이라 미사용 → PG 컬럼/트리거 불필요).
2. **ES 문서 형태 = 평탄** — 現 인덱스 `ingredient_names`(text)+`ingredient_item_ids`(keyword) 유지 → `search.py` 무변경. 중첩은 8.8× 쓰기증폭·중첩쿼리 2~5× 비용이나 현재 재료별 상관쿼리 없음 → 재료별 수량/상관 검색 로드맵 확정 시 재색인(수초)으로 전환.
3. **체크포인트 = 파일** (`CHECKPOINT_PATH` 볼륨, `REDIS_CHECKPOINT=False` 기본) — redis-pgsync는 큐 전용, 유실 시 슬롯 WAL 재생으로 복구, AOF 내구성 부담↓.
   → **2026-07-22: redis-pgsync 영속성(AOF+RDB) 완전히 끔.** 이 결정의 논리적 귀결이자, 실제로 물린 사고의 수습이다 — 호스트 급사 때 쓰던 중이던 AOF 가 포맷 손상(`Bad file format ... appendonly.aof.2.incr.aof`)으로 남아 redis 기동 실패 → pgsync 16시간 크래시루프. 버려도 되는 큐에 내구성 비용만 내고 기동 실패 리스크를 산 셈이었다. 상세 = 아래 §운영 사고.

**컷오버 필수 변경**: `search.py`의 `search_es`에 servable 필터 추가(리스트+검색 양쪽; 現 '인덱스=servable집합' 가정 → '전건+필터' 전환). schema.json 필드 = `index_recipes_es.py`의 `_actions` 매핑 동일 + `servable`(steps 미색인 유지).

## 운영 안전장치 (필수)
- **슬롯 lag 모니터링**: 논리슬롯이 멈추면 WAL 이 `/var/lib/docker` 에 무한 축적 → 디스크 full → PG 쓰기 전면중단. `PGReplicationSlotRetainedWALHigh`·`DockerDiskUsageHigh` 가 백스톱(단일노드라 물리 안전장치 없음).
- **PGSync 정지 감지**(2026-07-22 추가): `PGSyncDown`(컨테이너 소멸 10분) · `PGSyncCrashLooping`(15분간 3회+ 재시작). 둘 다 `severity=critical` → Slack `#alerts-critical`. **왜 슬롯 알람만으론 부족한가** — 크롤이 안 도는 동안엔 잔류 WAL 이 KB 단위라 `RetainedWALHigh`(5GB)는 며칠이 지나도 안 뜬다. 즉 슬롯 알람은 *디스크 파열* 백스톱이지 *정지* 조기경보가 아니다.
- swap 0 → 2~4G 스왑 권장(별도 작업).
- **롤백**: PGSync 중지 → `SELECT pg_drop_replication_slot('<slot>')`(WAL 즉시 해제) → (선택) 트리거·`_view`·`wal_level` 원복(재시작 필요, 가급적 유지).

## 운영 사고 — 2026-07-22 redis AOF 손상 → pgsync 16시간 정지

**타임라인**: 7/21 14:45Z `.12` 호스트 급사(전원) → redis-pgsync 가 AOF 쓰던 중 차단 → 22:52Z VM 부팅 → redis 기동 실패 반복 → pgsync 448회 크래시루프 → 7/22 06:43Z 수동 복구. **알람 0건.**

**연쇄**: AOF 가 잘림이 아니라 **포맷 손상**이라 `aof-load-truncated yes` 가 못 살림
(`# Bad file format reading the append only file appendonly.aof.2.incr.aof`)
→ redis 컨테이너가 안 뜨니 compose 네트워크에 이름 자체가 없음
→ pgsync 는 `ConnectionError: Error -3 connecting to redis-pgsync:6379. Temporary failure in name resolution` 로 exit 255.

⚠️ **진단 함정**: pgsync 로그는 매 재시작마다 초기싱크 진행줄로 도배돼 원인이 안 보인다. `docker logs pgsync 2>&1 | grep -icE "error|traceback"` 로 파야 나오고, **근인은 pgsync 가 아니라 redis** 다.

**복구**(무손실 — 큐는 버려도 되고 재개 지점은 `pgsync_checkpoint` 파일 볼륨에 있다):
```bash
docker stop redis-pgsync pgsync
sudo mv /var/lib/docker/volumes/data-tier_redis_pgsync_data/_data/appendonlydir{,.bak-crash}
docker start redis-pgsync && sleep 5 && docker start pgsync
```
사전 확인: **PG 행수 == ES `docs.count`** 이고 슬롯 `retained_wal` 이 KB 급이면 큐에 밀린 게 없다는 뜻.
사후 확인: `pg_replication_slots` 의 `restart_lsn`/`confirmed_flush_lsn` 전진. ⚠️ pgsync 는 **~180초 주기**(`REPLICATION_SLOT_CLEANUP_INTERVAL`)로 슬롯을 전진시키므로 1분 관찰로는 멈춘 것처럼 보인다 — 3분 이상 간격으로 볼 것.

**항구 대책** (이 변경):
1. redis-pgsync **영속성 제거**(`--save "" --appendonly no`) — 손상될 파일 자체를 없앰.
2. **컨테이너 레벨 알람 신설** `PGSyncDown`·`PGSyncCrashLooping`.
3. **죽은 룰 `PGReplicationSlotInactive` 삭제** — expr 의 `pg_replication_slots_slot_is_active` 는 **존재하지 않는 메트릭명**(실제 = `pg_replication_slot_slot_is_active` / `pg_replication_slots_active`)이라 애초에 발화 불가였다. 게다가 이름을 고쳐도 못 쓴다: PGSync 7.1.0 은 LISTEN/NOTIFY 방식이라 **`active=0` 이 정상 스테디상태**다.

⚠️ **크래시루프 룰 설계 메모**: `changes(container_start_time_seconds[15m])` 로는 못 잡는다 — 그건 컨테이너 *생성*시각이라 docker 가 같은 컨테이너를 재시작해도 안 변한다(실측 0). 대신 cadvisor 가 docker `RestartCount` 를 `restartcount` **라벨**로 노출해 재시작마다 새 시계열이 생기는 성질을 이용한다:
`count by(name, instance) (count_over_time(container_last_seen{name=~"pgsync|redis-pgsync"}[15m])) > 2`
7일 실측 임계값 근거 — 정상 = 항상 1, 단발 재배포 = 2, 이번 크래시루프 = 3~6.

## 참고
- PGSync 공식 스펙 조사(7.1.0) 요약 = 메모리 `pgsync-preconditions`.
- `design.md §330` 정합(프리컨디션 반영)·§331 servable 게이트 드리프트 정정은 후속(팀 확인).
