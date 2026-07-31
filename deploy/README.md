# deploy — food-budget 수집 파이프라인 배포·스케줄 — ⛔ SUPERSEDED

> ## ⛔ 이 문서는 폐기됐다 (2026-07-31, P4). 운영 지침으로 쓰지 말 것.
>
> 여기 적힌 것은 **`.8`(fb-data) VM 위의 Docker Compose 수집 파이프라인** 이야기다.
> 그 VM 은 P2 데이터 컷오버(2026-07-30) 후 정지 → **2026-07-31 에 파괴**됐고, 이 문서가 "정본 경로"로
> 가리키던 `infra/ansible/roles/data_pipeline` 롤도 **같은 날 삭제**됐다. 인벤토리의 `[data]` 그룹까지
> 없어져서 **아래 `ansible-playbook site.yml --limit data` 류 명령은 지금 아무것도 하지 않는다**
> (no hosts matched). §1 의 GitHub Actions CI 도 **Jenkins** 로 대체됐다
> (`.github/workflows/build-push-pipeline.yml` 은 비활성·보존).
>
> **현행 정본**
> | 찾는 것 | 지금 어디 |
> |---|---|
> | 이미지 빌드·push (§1) | 레포 루트 `Jenkinsfile` — `data-pipeline` → `mealplanning/mp-data-pipeline` · `crawler-kurly` → `mealplanning/mp-crawler-kurly`. 아래의 `food-budget/{data-pipeline,crawler-kurly}` 는 구 Harbor 프로젝트 좌표 |
> | 상주 컨슈머 (§2) | config 레포 `pipelines/consumers.yaml`(Deployment 4) + `pipelines/scaledobjects.yaml`(KEDA lag 트리거 4종, 그중 3종 scale-to-zero) |
> | 폴러 스케줄 (§3) | config 레포 `pipelines/pollers.yaml` — CronJob + **`spec.timeZone: Asia/Seoul`**. KST 를 그대로 적으므로 아래 "crontab 은 UTC" 주의문과 UTC 환산 열은 **더 이상 적용되지 않는다** |
> | 만료·집계 배치 | config 레포 `pipelines/pruners.yaml` — `mp-deal-pruner`·`mp-user-data-pruner`·`mp-chat-insights` (compose 상주 → CronJob 전환) |
> | ES 재색인 (1회성) | config 레포 `pipelines/jobs/reindex-recipes-es.yaml` |
> | 배포(CD) | **ArgoCD 단독**. Ansible 은 파이프라인을 더 이상 배포하지 않는다 |
> | 접속·조회·장애대응 | [`mp_k8s_infra_status.md`](../docs/mp_k8s_infra_status.md) **§4.0** |
> | K8s 매니페스트 | config 레포. 아래 §파일 이 "후속 보존용"이라 적은 **`deploy/k8s/` 는 stale 유물**이다 — `mp_k8s_infra_status.md` **§4** IaC 표 |
>
> **아직 유효한 것** (파일이 레포에 실재하고 메커니즘도 그대로)
> - **§2 "로컬/수동 브링업 (개발용)"** — `../docker-compose.yml`(image-only) + `../docker-compose.build.yml`(build override) 둘 다 레포에 있고, "base 단독으로는 `docker compose build` 가 거부된다"는 안전장치도 그대로다. 🔴 단 **붙을 대상이 죽었다** — compose 의 이미지 좌표는 구 Harbor `food-budget/` 이고 `.env` 가 가리키던 데이터티어는 `192.168.0.8` 이다. 로컬에서 쓰려면 엔드포인트를 직접 갈아끼워야 한다.
> - **`deploy/pgsync/`** — 아래 §파일 목록엔 아예 없지만 **살아 있다**. `Jenkinsfile:40` 이 `mp-pgsync` 이미지를 여기(`context: deploy/pgsync`)서 빌드한다.
>   🔴 **단 `schema.json`·`plugins/` 는 "참조"가 아니라 두 레포에 복제돼 있다** — config 레포가 같은 내용을 ConfigMap 에 **인라인**으로 들고 있고(`platform/pgsync/schema-configmap.yaml` = `mp-pgsync-schema` · `plugins-configmap.yaml` = `mp-pgsync-plugins`), 파드는 그 ConfigMap 을 마운트한다. 이미지가 아니라 ConfigMap 이 런타임 정본이므로 **여기 파일만 고치면 클러스터에 반영되지 않는다.** 한쪽을 고치면 반드시 양쪽을 고칠 것. (2026-07-31 대조 시점 `schema.json`·`recipe_servable.py`·`__init__.py` 3종 모두 바이트 동일 — 드리프트 없음)
> - **`deploy/app/`** — 별도 문서(`deploy/app/README.md`)라 이 배너의 대상이 아니다. 다만 그 대상 VM `.9` 도 파괴됐다.
>
> 나머지 스크립트(`push.sh`·`run-poller.sh`·`install-pollers.sh`·`crontab.fb-pollers`·`tests/`)는 파일은
> 남아 있으나 **실행처가 없다** — 호출자였던 `data_pipeline` 롤과 `.8` 의 root 크론이 함께 사라졌고,
> CI(Jenkins·GH Actions) 도 이것들을 돌리지 않는다(`tests/test-run-poller.sh` 는 수동 실행용).
> 폴러별 "왜 이 시각인가" 근거는 `pipelines/pollers.yaml` 이 승계했다(그 파일 첫 줄이 이 문서의
> `crontab.fb-pollers` 를 원본으로 명시).
>
> 아래 원문은 **이력 참고용**으로만 남긴다.

---

CI가 이미지를 Harbor에 올리고 → 현재 `fb-data`가 pull해서 컨슈머 상주 + 폴러 cron으로 돌린다.
정본 스케줄 = `docs/design.md` §7.1·§3.4. 토폴로지 = §8.4.

## 좌표 (design §8.4)
| VM | 좌표 | 역할 |
|----|------|------|
| VM1·Data | `192.168.0.8` | PG·ES·Redis·**Kafka**(:9092) + 현재 크롤러/컨슈머/폴러 |
| VM2·App+AI | `192.168.0.9` | FastAPI·ML |
| VM3·CI+Harbor | `192.168.0.10` | GH Actions 러너(`fb-ci`)·**Harbor** |

이미지: `192.168.0.10/food-budget/{data-pipeline,crawler-kurly}`

## 1. CI — 이미지 빌드/푸시 (자동)
`.github/workflows/build-push-pipeline.yml`. `main`에 `pipelines/**`·`crawler/**`·`Dockerfile` 변경 push 시(또는 수동 `workflow_dispatch`) `fb-ci` 러너에서:
1. `data-pipeline`(`Dockerfile`) + `crawler-kurly`(`crawler/kurly/Dockerfile`) 빌드
2. Trivy 스캔 — `data-pipeline`은 CRITICAL 발견 시 **차단**, `crawler-kurly`(Playwright 브라우저 베이스)는 리포트만
3. Harbor push — `:<sha>` + `:latest` (매 푸시). **릴리스 태그 `:X.Y.Z` 는 수동 `workflow_dispatch` 런에서만** (env `APP_VERSION`, build-push-app 과 통일). 자동 push 는 버전 태그를 안 찍음(불변 보장).

시크릿(레포 설정): `HARBOR_USERNAME`·`HARBOR_PASSWORD` — 전 워크플로 공용.

수동 대안(docker 호스트에서 직접): `docker login 192.168.0.10 && bash deploy/push.sh`

## 2. fb-data 배포 — ansible `data_pipeline` 롤 (pull 기반, 정본 경로)
수집 파이프라인은 **ansible 롤이 pull 배포**한다(`infra/ansible/roles/data_pipeline`). CI가 Harbor에 올린 이미지를 받아 `/opt/data-pipeline`에 **image-only compose + 폴러 스크립트만** 배치 — 소스 트리를 두지 않아 로컬 소스 빌드가 불가능해 드리프트가 원천 차단된다.

```bash
cd infra/ansible
ansible-playbook site.yml --limit data          # tfstate_db · data_tier · data_pipeline
# 특정 릴리스 태그로: -e dp_image_tag=1.1.3    (기본 = roles/data_pipeline/defaults/main.yml 핀)
```
롤이 하는 일: `/opt/data-pipeline/`에 `docker-compose.yml`(image-only) + `deploy/{run-poller.sh,install-pollers.sh,crontab.fb-pollers}` 배치 → `.env`의 `IMAGE_TAG` 핀 → `docker compose pull` → 상주 컨슈머 4개 `up -d` → 폴러 host cron 설치.

> **전제(오퍼레이터 1회 설정)**: Harbor가 self-signed HTTPS → `/etc/docker/daemon.json`에 `"insecure-registries":["192.168.0.10"]` 후 `systemctl restart docker`, 그리고 Harbor pull 가능(`docker login 192.168.0.10`). 배포·폴러 cron은 **root 로 실행**(ansible 기본 become)이므로 root 컨텍스트에서 pull 가능해야 한다. 롤은 비밀·로그인을 만들지 않는다(`.env`는 상주, `IMAGE_TAG` 라인만 관리).
>
> **최초 마이그레이션(구 `/home/ubuntu/food-budget-app` → `/opt/data-pipeline`)**: 롤이 `.env`·크롤상태(`recipe-crawl-state/`)를 구 경로에서 **1회 자동 이전**한다(둘 다 신규 경로에 없을 때만). compose `name: food-budget-app` 고정이라 컨테이너 이름이 유지되고 같은 프로젝트로 재조정된다. 신규 배포 검증 후 **구 소스 트리(`/home/ubuntu/food-budget-app`)는 제거**해야 로컬 빌드 재발이 없다(롤은 안전상 삭제하지 않음).

### 로컬/수동 브링업 (개발용)
정상 배포는 위 pull 경로다. 로컬에서 이미지를 직접 빌드해 띄우려면 build override를 겹친다:
```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml build
docker compose up -d
```
`docker-compose.yml` 단독엔 `build:`가 없어(image-only) `docker compose build`는 "빌드할 서비스 없음"으로 거부된다 — 의도된 안전장치.

## 3. fb-data 폴러 — host cron 스케줄
폴러 cron은 **위 `data_pipeline` 롤이 root 크론에 자동 설치**한다(`install-pollers.sh` 재사용, ansible 기본 become=root). run-poller가 root로 docker·로그(`/var/log/fb-pollers`)·메트릭을 기록한다. 수동 재설치가 필요하면 `/opt/data-pipeline`에서(root):
```bash
# 권장: ansible 재실행 (root 크론 + 레거시 ubuntu 블록 정리까지 일관)
#   cd infra/ansible && ansible-playbook site.yml --limit data --tags data_pipeline
# 수동은 root 로만 (ubuntu 로 실행하면 ubuntu 크론에 중복 설치 → 이중 스케줄):
cd /opt/data-pipeline
sudo bash deploy/install-pollers.sh            # 이미지 pull + 토픽 생성(멱등) + crontab 등록(root)
sudo bash deploy/install-pollers.sh --dry-run  # 등록될 crontab 미리보기
sudo bash deploy/install-pollers.sh --uninstall # 폴러 블록만 제거(root)
```
스케줄(`deploy/crontab.fb-pollers`, design §7.1·§3.4):

> ⚠ **crontab 파일은 UTC 로 적혀 있다.** 게스트 VM TZ=`Etc/UTC` 이고 Debian cron(vixie)은 `CRON_TZ` 를
> 파싱하지 않는다(cronie 확장) — 예전엔 `CRON_TZ=Asia/Seoul` 을 믿고 KST 로 적어서 전 스케줄이 9시간
> 일찍 돌았다. 아래 표의 KST 가 **설계 의도**, 괄호 안이 crontab 에 실제로 적힌 UTC 값.
> 시각을 고칠 땐 둘 다 바꿀 것. (KST=UTC+9 고정, DST 없음)

| 폴러 | 시각(KST) | crontab(UTC) | 소스 | 비고 |
|------|-----------|--------------|------|------|
| `poller-kurly` | 03:30 | `30 18 * * *` | 컬리 가격 | Playwright, 무거움 → 심야 1회 |
| `poller-oasis` | 04:10, 13:10 | `10 19 * * *`, `10 4 * * *` | 오아시스 가격 | 일 2회, 피크(11-12) 회피 |
| `poller-deal-timesale` | 15:05 | `5 6 * * *` | 오아시스 타임세일 | timeSale 15시 리셋 직후 |
| `poller-deal-closesale` | 17:05 | `5 8 * * *` | 오아시스 마감세일 | closeSale 17시 오픈 직후 |
| `poller-recipe` | 일·수 05:00 | `0 20 * * 2,6` | 만개 레시피 | 주 2회, 최신순 재스캔 → Kafka, `RECIPE_CRAWL_STATE_HOST` 상태 볼륨 |
| `poller-price-matview` | 매시 :20 | `20 * * * *` | PG → PG | `retail_unit_price` 물질화 뷰 갱신 + Price 캐시 무효화 |
| `poller-es-recipes` | 일·수 06:30 | `30 21 * * 2,6` | PG → ES 재색인 | 크롤 드레인 후 `recipes` 인덱스 재구축(servable 게이트 내장) |

- UTC 환산 시 **요일도 하루 앞으로 밀린다**: 일(0)→토(6), 수(3)→화(2).

- 각 회차 = `docker compose --profile poller run --rm <svc>` 1회 실행 후 종료(on-demand).
- `run-poller.sh`가 flock으로 중첩 실행 방지 + `/var/log/fb-pollers/<svc>.log` 기록 + node-exporter textfile 메트릭 생성.
- 상주 컨슈머는 `:9401~:9404/metrics`를 열고 Prometheus가 `pipeline-consumers` job으로 scrape.
- `poller-recipe`는 `crawler/10k_recipe` 크롤러를 `--kafka --order date`로 실행 — **최신순 재스캔**으로 신규 레시피(+썸네일)를 `recipe.crawl.raw`에 직접 produce(→ recipe-refiner → PG). 크롤 상태(CSV·`크롤링_상태.json`)는 `RECIPE_CRAWL_STATE_HOST`(기본 `./recipe-crawl-state`) 볼륨에 영속되어 resume/dedup — 첫 실행은 최신 `RESCAN_MAX_PAGES`p까지, 이후 실행은 이미 수집분에 도달하면 조기 종료.
- `poller-price-matview`는 `pipelines/ingest/refresh_price_matview.py`를 실행 — `retail_unit_price`(물질화 뷰)를 `REFRESH ... CONCURRENTLY` 하고 Redis `price:current:*`/`price:hotdeals:*` 캐시를 무효화. **이게 없으면 크롤이 `retail_price`에 쌓여도 조회면(`retail_unit_price`·`retail_item_price_compare`·Price API)에 안 나타난다** — 실제로 배치 로더가 호출하던 이 갱신이 Kafka 스트리밍 전환 후 호출자를 잃어 2026-07-17~21 4일간 stale 했다. 크롤 완료시각 스태거가 아니라 **매시**인 이유는 오아시스 크롤 소요가 4~60분으로 변동해 다시 결합되면 같은 방식으로 깨지기 때문(매시 = 최대 지연 1시간 보장·자가복구). 비용 실측 0.78초/회.
- `poller-es-recipes`는 `pipelines/ingest/index_recipes_es.py`를 실행 — PG의 `recipe`/`recipe_ingredient`를 조인해 `recipes`(ES, nori) 인덱스를 **drop→recreate→전량 재색인**. 서빙 게이트(`source='10K'` + 미매칭 재료 0 strict)는 스크립트에 내장. 크롤(일·수 05:00)이 Kafka→recipe-refiner→PG로 드레인된 뒤 돌도록 **06:30**에 스태거. 재색인 중 인덱스 재생성 수 초 공백이 있으나 저볼륨·새벽이라 alias-swap은 생략(스크립트 주석 참조). ES 접속은 `ESHOST`/`ESPORT`(기본 `192.168.0.8:9200`).

## 파일
- `../Dockerfile` · `../crawler/kurly/Dockerfile` — 두 이미지
- `../docker-compose.yml` — **image-only**(배포용): 컨슈머(상주) + 폴러(profile `poller`) + 토픽생성(profile `tools`)
- `../docker-compose.build.yml` — build override(로컬/수동 빌드 전용, 배포엔 미전달)
- `../infra/ansible/roles/data_pipeline/` — pull 배포 롤(위 §2)
- `push.sh` — 수동 빌드/푸시 (CI 대안)
- `run-poller.sh` · `crontab.fb-pollers` · `install-pollers.sh` — 폴러 스케줄
- `k8s/` — K8s 매니페스트, **지금 미사용**(Docker 집중). 후속 보존용.
