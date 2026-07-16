# deploy — food-budget 수집 파이프라인 배포·스케줄

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
3. Harbor push (`:<sha>` + `:latest`)

시크릿(레포 설정): `HARBOR_USERNAME`·`HARBOR_PASSWORD` — 전 워크플로 공용.

수동 대안(docker 호스트에서 직접): `docker login 192.168.0.10 && bash deploy/push.sh`

## 2. fb-data 배포 — 상주 컨슈머
```bash
git pull                      # 이 repo 체크아웃
cp .env.example .env && vi .env   # KAFKA_BOOTSTRAP=192.168.0.8:9092 · PG* · REDIS_URL 채우기
docker compose pull           # Harbor에서 latest
docker compose up -d          # retail-refiner · deal-notifier · recipe-refiner · deal-pruner
```
> Harbor가 self-signed HTTPS → `/etc/docker/daemon.json`에 `"insecure-registries":["192.168.0.10"]` 후 `systemctl restart docker`, 그리고 `docker login 192.168.0.10`.

## 3. fb-data 폴러 — host cron 스케줄
```bash
bash deploy/install-pollers.sh            # 이미지 pull + 토픽 생성(멱등) + crontab 등록
bash deploy/install-pollers.sh --dry-run  # 등록될 crontab 미리보기
bash deploy/install-pollers.sh --uninstall # 폴러 블록만 제거
```
스케줄(KST, `deploy/crontab.fb-pollers`, design §7.1·§3.4):

| 폴러 | 시각(KST) | 소스 | 비고 |
|------|-----------|------|------|
| `poller-kurly` | 03:30 | 컬리 가격 | Playwright, 무거움 → 심야 1회 |
| `poller-oasis` | 04:10, 13:10 | 오아시스 가격 | 일 2회, 피크(11-12) 회피 |
| `poller-deal-timesale` | 15:05 | 오아시스 타임세일 | timeSale 15시 리셋 직후 |
| `poller-deal-closesale` | 17:05 | 오아시스 마감세일 | closeSale 17시 오픈 직후 |
| `poller-recipe` | 일·수 05:00 | 만개 레시피 | 주 2회, 최신순 재스캔 → Kafka, `RECIPE_CRAWL_STATE_HOST` 상태 볼륨 |

- 각 회차 = `docker compose --profile poller run --rm <svc>` 1회 실행 후 종료(on-demand).
- `run-poller.sh`가 flock으로 중첩 실행 방지 + `/var/log/fb-pollers/<svc>.log` 기록 + node-exporter textfile 메트릭 생성.
- 상주 컨슈머는 `:9401~:9404/metrics`를 열고 Prometheus가 `pipeline-consumers` job으로 scrape.
- `poller-recipe`는 `crawler/10k_recipe` 크롤러를 `--kafka --order date`로 실행 — **최신순 재스캔**으로 신규 레시피(+썸네일)를 `recipe.crawl.raw`에 직접 produce(→ recipe-refiner → PG). 크롤 상태(CSV·`크롤링_상태.json`)는 `RECIPE_CRAWL_STATE_HOST`(기본 `./recipe-crawl-state`) 볼륨에 영속되어 resume/dedup — 첫 실행은 최신 `RESCAN_MAX_PAGES`p까지, 이후 실행은 이미 수집분에 도달하면 조기 종료.

## 파일
- `../Dockerfile` · `../crawler/kurly/Dockerfile` — 두 이미지
- `../docker-compose.yml` — 컨슈머(상주) + 폴러(profile `poller`) + 토픽생성(profile `tools`)
- `push.sh` — 수동 빌드/푸시 (CI 대안)
- `run-poller.sh` · `crontab.fb-pollers` · `install-pollers.sh` — 폴러 스케줄
- `k8s/` — K8s 매니페스트, **지금 미사용**(Docker 집중). 후속 보존용.
