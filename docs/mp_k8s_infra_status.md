# 인프라 현황 (Kubernetes) — SSOT

> **팀 공유용 인프라 상태 단일 소스.** `CLAUDE.md §인프라`가 이 문서를 가리킨다. **인프라 변경 시 여기를 갱신한다.**
> 최초 작성 2026-07-24 (SSOT 이관) · **2026-07-27 전면 갱신** — 계획 검증 인터뷰의 결정 18건 반영(단계 재편·호스트 확보·CI 전환 완료 등). 결정 근거 = [`mp_k8s_infra_migration_plan.md`](./mp_k8s_infra_migration_plan.md)
>
> 🟢 **클러스터 + 기반 스택 가동** (2026-07-27) — 호스트 B 3노드(kubeadm 1.34.10 + Cilium 1.19.6) 위에 MetalLB·OpenEBS·cert-manager·MinIO·ESO·관측·Istio·ArgoCD 까지 올라갔다. **P0 완료 (2026-07-28)** — 마지막 항목이던 S3 백업·복구 왕복은 **P2 직전 선행조건으로 이동**(같은 날 결정 — 무백업 노출 창은 P2 컷오버부터라 게이트 위치만 옮긴 것, 데이터 티어 전 증명 원칙 유지). §0 표가 정확한 현황이다.
> 🟢 **LGTM 선배포** (2026-07-28) — P4 항목이던 "LGTM in-cluster" 중 **스택 세우기만 앞당겨** Loki·Tempo·Alloy 가 **ArgoCD Application**(platform AppProject)으로 가동. **컷오버(알림 20개·Slack·`.11` 철거)는 P4 유지** — 상세·근거 = §4.3.
> 🟢 **운영·장애대응·접속도 이 문서가 정본이다** (2026-07-31, P4) — 구 Docker 트랙 문서 [`docker-infra-status.md`](./docker-infra-status.md) 는 **폐기**됐다. 살아 있던 부분(호스트 C `.10` · 하이퍼바이저 `.12`)은 **§4.0·§4.1 로 승계 완료**.
>
> | 용도 | 문서 |
> |---|---|
> | **인프라 SSOT (목표 아키텍처·구축 현황·운영·접속)** | **이 문서** |
> | 이전 결정·근거·컷오버 절차 (why/how) | [`mp_k8s_infra_migration_plan.md`](./mp_k8s_infra_migration_plan.md) |
> | ⛔ 구 Docker 4-VM 트랙 (**폐기 2026-07-31** — 사고 이력 참고용) | [`docker-infra-status.md`](./docker-infra-status.md) |
> | **P1 앱 이전 담당자 핸드오프** | [`mp_k8s_p1_app_handoff.md`](./mp_k8s_p1_app_handoff.md) |
> | **P2 데이터 이전 런북** (2026-07-28 확정) | [`mp_k8s_p2_data_runbook.md`](./mp_k8s_p2_data_runbook.md) |
>
> **역할 분담**: 이 문서는 *무엇이 서 있는가(what)*, 플랜은 *왜 그렇게 정했고 어떻게 옮기는가(why/how)*. 결정을 바꿀 때는 플랜에서 바꾸고 여기로 반영한다.

---

## 0. 한눈에 요약

| 항목 | 상태 |
|---|---|
| 물리 호스트 A (`192.168.0.12`, i7-10700F/32GB) | ✅ 가동 — **Docker 앱·데이터 트랙 종료**(`.9`·`.8` 정지) · `k8s-worker-a1`(`.20`) 호스팅 |
| **물리 호스트 B** (클러스터용, 32GB) | ✅ **가동** — Proxmox 9.1.1(호스트명 `k8s1`) @ `.22` · **템플릿 9002 이관 완료** (2026-07-27) |
| **물리 호스트 C** (CI/CD·레지스트리, `.10`) | ✅ **가동** — Harbor·Jenkins·SonarQube. 구 fb-ci-harbor VM 의 `.10`·인증서 승계 |
| **CI = Jenkins** (호스트 C, 레포 루트 `Jenkinsfile`) | ✅ **전환 완료** — GitHub 웹훅 즉시 트리거(`ci.mealbong.cloud` → Cloudflare Tunnel, 2026-07-29). GH Actions 러너 은퇴(트리거 비활성) |
| **Harbor 신규 프로젝트** `mealplanning/` | ✅ 앱 10종 `:1.1.9` 베이스라인 (구 `food-budget/*` 이미지는 구 VM 과 함께 소멸 예정 — 백필 안 함) |
| **K8s 노드 VM 3대** (Terraform · 호스트 B) | ✅ **생성 완료** (2026-07-27) — `k8s-master` `.17`(6GB·2c) · `k8s-worker-b1` `.18` · `k8s-worker-b2` `.19`(11GB·6c 각) · swap 없음 |
| K8s 클러스터 (master ×1 + worker ×4, **노드 램프** §1) | ✅ **5노드 Ready** — P0 3노드(2026-07-27) → P1 worker-a1 합류(4노드) → **P4 worker-a2 합류(2026-07-31, 5노드 완성)**. kubeadm **1.34.10** · **kube-proxy 미설치**(Cilium 대체) · containerd 2.2.6 |
| Cilium (CNI · kube-proxy 대체 · WireGuard) | ✅ **1.19.6** — `kubeProxyReplacement: true` · Tunnel(VXLAN) · WireGuard(peers 2) · `ipam.mode=kubernetes`(podCIDR `10.244.0.0/16`) · cluster health 3/3 |
| Istio (sidecar 메시 + Gateway API) | ✅ **컨트롤플레인** 1.30.3 — istiod + **istio-cni**(Cilium conflist 에 체이닝 실증: `['cilium-cni','istio-cni']`) + **Gateway API CRD v1.6.1**. Gateway·HTTPRoute 실물은 P1 |
| MetalLB (L2, 풀 `.14`–`.16`) | ✅ **0.16.1** — 풀 `autoAssign=false`(게이트웨이 전용 강제) · 스모크: 풀 미지정=Pending / 지정=`.14` 할당 + LAN HTTP 200 |
| OpenEBS LVM LocalPV (동적 프로비저닝) | ✅ **1.9.1** — SC `openebs-lvm`(기본·Delete) + `openebs-lvm-retain`(Retain), 둘 다 WaitForFirstConsumer. 워커 2대 왕복 검증 완료 |
| MinIO (Loki·Tempo 백엔드 · 모델 아티팩트 — **단일 replica·B 고정**) | ✅ **차트 5.4.0 / RELEASE.2025-09-07** — PVC 50Gi · zone=host-b 고정 · 버킷 loki·tempo·models 생성됨 |
| 데이터 티어 in-cluster (PG·ES·Redis·Kafka HA + PGSync) | ✅ **P2 완료(2026-07-30 새벽 전환창)** — 열화 ~25분·**유실 0**(41테이블 일치)·roll-forward. PG=CNPG 2인스턴스(타임라인 2·복제 lag ms 급·**memory 2Gi req=lim** 2026-07-30 QoS 보강) · ES=ECK 3노드 green · Kafka=Strimzi 3브로커 · Redis=master+replica+Sentinel3(클라이언트 Sentinel-aware) · PGSync CDC 가동. 상세·함정 = [런북](./mp_k8s_p2_data_runbook.md) |
| **레시피 검색 + PGSync 안정 alias** (T-3, 2026-08-03) | ⏳ **중간 전환·E2E 보고 있음, 최종 close 대기** — 앱 읽기와 PGSync 쓰기 모두 `recipes_live` 고정 alias 사용 → `recipes_v2`(nori·명시 매핑·replica 1). 실행 에이전트가 PG=ES 8,963건·검색 13/275건·CRUD CDC·role park를 보고했지만 정확한 라이브 조회 시각이 기록되지 않았다. config ops SSOT 선행 merge(`PENDING_AFTER_CONFIG_MERGE`)와 timestamp가 있는 재검증 전에는 최종 수치·완료 판정으로 사용하지 않는다. 상세 = §7.1-3a |
| **`.8`(fb-data) 은퇴** | ✅ **정지 완료(2026-07-30)** — vmid 201, **P4까지 디스크 보존**(최후 보험·onboot 0). 최종덤프 = `s3://mp-backup-ap2/pg-final/2026-07-30/`(SHA256 왕복 검증). 인벤토리 제거·`.11` 스크레이프 제거(#382) 완료 — `.9` 와 동일 선례 |
| **모니터링 컷오버 (구 P4 알림·관측 이관 — 2026-07-30 조기 실행)** | ✅ **완료** — ① 규칙·스크레이프 이식(PodMonitor 2·PrometheusRule: pipeline·pg·pgsync·container-memory, config#24·25) ② **Slack 라우팅 인클러스터**(웹훅 = fb-secrets→ESO→`api_url_file`, 테스트 알람 양 채널 실증, #383) ③ 물리 계층 편입(`.12` 온도·`.10` — additionalScrapeConfigs 4종+규칙 9종, #384·config#26) ④ 로그 재지향(`.10`·`.11` alloy → Loki NodePort 31100, config#27·#385 — *31100 은 같은 날 `.15` 게이트웨이로 대체·회수, 아래 "내부 Gateway" 행*) ⑤ **Grafana 대시보드 13장 무수정 이식**(uid 정합)+remoteWrite 브리지 제거(config#28·29·#386). **`.11` 은 역할 전무 — 정지·철거 대기** |
| 관측 (kube-prometheus-stack + metrics-server) | ✅ **87.20.0 + 3.13.1** — Prometheus(B 고정·PVC 30Gi·15d·**additionalScrapeConfigs 로 `.12`·`.10` 물리 계층 편입**) · Grafana(**대시보드 13장 이식 + sidecar searchNamespace ALL**) · **Alertmanager = Slack 라우팅 가동**(2026-07-30 컷오버 — slack-default/critical·웹훅은 ESO `mp-alertmanager-slack`) · node-exporter 는 **kube-system**(PSS) |
| **관측 — LGTM** (Loki·Tempo·Alloy, **ArgoCD 관리**) | ✅ 2026-07-28 선배포(§4.3) → ✅ **컷오버 완료(2026-07-30)** — Loki 가 클러스터 밖 로그까지 수신(`.10`·`.11` alloy → `https://loki.mealbong.cloud` 게이트웨이 경유 — 과도기 NodePort 31100 은 회수), 예비 스택 아님·프로덕션 관측 정본. ✅ **Tempo 트레이스 유입 가동(2026-07-30)** — Istio Telemetry 100%·OTLP(§4.3 함정 ④ 해소, 규칙 2종은 첫 블록 후 편입) |
| ArgoCD (CD, GitOps — **유일한 CD**) | ✅ **10.2.1 가동 완료** — **뿌리 2개**: `mealplanning-root`(앱, `argocd/applications/`) · **`platform-root`**(플랫폼, `platform/argocd/` — 2026-07-29 신설, prune 끔). AppProject 4 = `mealplanning`·`mealplanning-root`·`platform`(P2 확장 완료)·`platform-root` + **앱 트랙 연결 실증 완료**(§4.2, 2026-07-28). 앱 Application 적용은 P1(앱 담당자) |
| **P2 플랫폼 배선** (2026-07-29 — 런북 §2-A-3) | ✅ **platform AppProject 3종 확장**: sourceRepos 6(LGTM+오퍼레이터 차트 4+config 레포) · destinations 7(+`data`+오퍼레이터 ns 4) · 클러스터 스코프 5종(+CRD·Validating/Mutating 웹훅 — **`helm template --include-crds` 실렌더링으로 확정**, 추측 아님) · **오퍼레이터 ns 4개 생성**(`cnpg-system`·`elastic-system`·`strimzi-system`·`redis-operator-system`, PSS baseline) · **platform-root 가동**. 오퍼레이터·데이터 CR child 는 아직 없음(⑥ 매니페스트) |
| External Secrets Operator (**Kubernetes provider**) | ✅ **2.8.0** — 정본 ns `fb-secrets` + 읽기전용 SA · `ClusterSecretStore/fb-kubernetes` Ready |
| S3 오프사이트 백업 | ✅ **왕복 증명 완료 (2026-07-29)** — 버킷 `mp-backup-ap2`(ap-northeast-2). CNPG barman-cloud 플러그인 + `ObjectStore` CR 경로로 **`Backup` CR → S3 → 별도 클러스터 `bootstrap.recovery` → 40테이블 중 39개 행수 완전 일치**(1개 차이는 `.8` 컨슈머가 계속 쓰는 테이블의 단조 증가분). 백업 79초 / 복원 54초. 상세·함정 = 런북 §2-B |
| cert-manager | ✅ **v1.21.0** — 로컬 CA 승계 `ClusterIssuer/fb-local-ca` Ready(새 CA 를 만들지 않아 신뢰 재배포 불필요) |
| 클러스터 공통 오브젝트 | ✅ zone 레이블(`topology.kubernetes.io/zone=host-b`) · ns 5종+PSS · PriorityClass 3종 |
| **공개 Gateway `.14` + HTTPRoute 10** (P1) | ✅ **2026-07-28 가동·검증** — `mp-gw-public`(HTTP 80. TLS 는 라우팅 검증 후 별건) · nginx `/api/*` 13경로 이관 · **`.9` 대비 18경로 응답 100% 일치**(불일치 0) · 업로드 한도 복원(EnvoyFilter buffer 15Mi — object_spec §5.6 정정분). 정본 = config 레포 `gateway/`. ✅ **유입 전환 완료(2026-07-28) — `.14` 가 정식 입구**(앞단 프록시·DNS 없음 → 접속 주소만 `.9`→`.14`. 정적 자산·SPA 딥링크까지 동일 검증) · ✅ **HA 완료(2026-08-01)** — `replica 2`(**노드·물리호스트 둘 다 분산**) + **hard TSC 2계층**(hostname + zone) + `nodeTaintsPolicy: Honor` + `matchLabelKeys: [pod-template-hash]` + `mp-gw-public-pdb`. 경로 = `Gateway.spec.infrastructure.parametersRef` → ConfigMap `mp-gw-public-params`([§5.4](#54-공개-게이트웨이-ha--외부-유입-spof-해소-2026-08-01)·[§5.5](#55-다중-replica-분산을-보장으로-승격--hard--honor--matchlabelkeys-2026-08-01)). 🔴 **ns 이전 완료(2026-08-06) — 이제 `app` 이 아니라 전용 ns `mp-ingress` 다**(cloudflared 도 함께. 근거=쿼터 결합, [§5.10](#510-공개-진입점-ns-분리--app--mp-ingress-2026-08-06-532-)). **HTTPRoute 12개는 `app` 잔류.** 정본 = config 레포 `ingress/`(GW 일체) + `gateway/`(라우트) |
| **P3 스케일 — Pooler·HPA·KEDA** (2026-07-30 밤) | ✅ **완료** — 앱 9개가 **CNPG Pooler(PgBouncer transaction)** 경유(예외 = ocr·ranking-serving·파이프라인·PGSync 직결) · 앱 풀 10→**5**+prepare 비활성 · **account HPA**(ContainerResource 70%·min2·max4) · **KEDA 2.20.1** + ScaledObject 4종, 컨슈머 3종 **scale-to-zero**. 🔴 핵심 실증 = account 4 replica 에서도 **PG 커넥션 12/100**(Pooler 가 흡수). 상세·함정 = [§5.1](#51-p3-스케일-실행-기록-2026-07-30). ✅ **scale-to-zero 사각지대용 lag 알람 4종 가동(2026-07-31, §5.2)** |
| **내부 Gateway `.15` + 이름 6종** (2026-07-30) | ✅ **가동·실증** — `mp-gw-internal`(observability, **platform 프로젝트** — mealplanning 은 observability 미허용) · `https://<이름>.mealbong.cloud` 6종(grafana·minio 콘솔·loki·jenkins·sonarqube·harbor **UI만** — pull 경로는 `.10` 직결 불변) · **LE 와일드카드 1장**(DNS-01·70초 발급) + 와일드카드 A레코드(`*`→`.15`, DNS-only) · 80 은 전량 301 · 호스트 C 백엔드 = **ServiceEntry**(EndpointSlice 는 ArgoCD 기본 제외로 미적용 — §3 수칙) · Harbor 는 로컬 CA 검증 재암호화(DR SIMPLE·SAN=IP 핀) · **NodePort 2종(30300·31100) 회수 완료**. 정본 = config 레포 `gateway-internal/` — 이로써 "LB 는 게이트웨이 전용 상시 2개" 완성 |
| **앱 관측 브리지** (in-cluster 수집 → `.11` remote_write) | ✅ 2026-07-28 개통 → ✅ **은퇴(2026-07-30, #386)** — 존재 이유(.11 Grafana 대시보드 연속성)가 대시보드 이식으로 소멸해 remoteWrite 제거. ServiceMonitor `mp-app-services`(수집 자체)는 인클러스터 관측의 정본으로 존치. **클러스터→`.11` 마지막 의존 단절** |
| **`.9`(fb-app-ai) 은퇴** | ✅ **정지 완료(2026-07-28)** — 인벤토리에서 제거 · `.11` 의 `fastapi-*` 잡 9개 회수. **VM 은 디스크 보존**(파괴 안 함) → 롤백 = VM 기동(컨테이너 restart 정책). `.env` 백업 = `/home/team6/backups/dot-env-20260728/`. 🔴 순서 수칙: `PrometheusTargetDown` 이 `up == 0` 전역 규칙이라 **잡 제거 → 반영 → 정지** 순이어야 알람 폭풍이 없다 |
| **구 `fb-ci-harbor`(VM 203) 파괴** | ✅ **완료(2026-07-28)** — 디스크 220GB 회수(150+70) · **`.10` IP 충돌 지뢰 영구 제거**(2026-07-27 실발생분). 구 `food-budget/*` 이미지 소멸은 계획상 수용 |

**P0 대부분 완료** (2026-07-27) — 전 과정이 IaC 다: Terraform(노드 VM 3대) → Ansible `k8s.yml`(베이스라인 → `kubeadm init` → 조인 → Cilium → 공통 오브젝트 → 기반 스택 8종). **플레이북 전체 재실행 = `changed=0`**.

**실측으로 검증한 것**: **master 하드 파워오프 중 인그레스 무중단 151/151**(§1.0) · 3노드 Ready · cilium health 3/3 · 크로스노드 ClusterIP+CoreDNS = HTTP 200(kube-proxy 없이 eBPF LB) · 워커 2대 PVC 왕복 · MetalLB 풀 미지정=Pending/지정=`.14`+LAN HTTP 200 · CNI 체이닝 `['cilium-cni','istio-cni']` · `kubectl top` 응답 · master 상주 **1,938Mi = allocatable 의 41%**(6GB 상향 판단의 실측 근거).

**P0 완료 (2026-07-28)** — 기반 스택·라우팅 락·master 킬 테스트·config 레포 연결(app-of-apps 가동)·LGTM 선배포까지 전부 ✅. 마지막 항목이던 **S3 백업·복구 왕복은 P2 직전 선행조건으로 이동**(2026-07-28 결정 — §5 P2 행).

**P1 완료 (2026-07-28)** — 앱 11 워크로드 + Gateway `.14` 유입 전환 + `.9` 정지·worker-a1 합류(4노드). **P2 완료 (2026-07-30 새벽)** — 데이터 티어·파이프라인 전환창(유실 0·roll-forward)·`.8` 정지. **모니터링 컷오버 완료 (2026-07-30)** — 구 P4 의 알림·관측 이관을 당겨 실행("철거 예정 인프라에 과도기 투자 안 함" 결정): 규칙·Slack·물리 계층 스크레이프·로그 재지향·대시보드까지 인클러스터가 정본. **P3 스케일 완료 (2026-07-30 밤)** — Pooler·풀 축소·account HPA·KEDA scale-to-zero(§5.1).

🔴 **서 있지 않은 것 = [§7 미조치 감사 부채](#7-미조치-감사-부채-전수-감사-2026-08-02)** (2026-08-02 전수 감사 + 이후 라이브 재검증). §0~§5 는 세운 것만 적혀 있어 **그것만 읽으면 실제보다 견고해 보인다.** 아래 ✅ 들과 **같은 무게로** 읽어야 하는 것: **PGSync 가 조용히 멈추면 PG primary 가 위험**(프로브 없음 · §7.1-4) · **Harbor 정기 백업 0건**(§7.1-6) · **cluster-admin 토큰 만료 없음**(§7.2-1) · **host-a 상실을 b1·b2 가 수용 못 함**(§7.3-5). ~~라이브 검색 nori 부재~~와 ~~`recipes` DR 폴백 단일 사본~~은 2026-08-03 해소(§7.1-2·3·3a). ~~audit 없음~~도 2026-08-03 해소(§5.9).

**P4 대부분 완료 (2026-07-31)** — **`.11` 정지** · **worker-a2 합류로 5노드 완성** · **Kafka 브로커 재배치**(b1 정족수 SPOF 해소) · **은퇴 VM 3대(`.8`·`.9`·`.11`) 파괴**(⚠️ `.11` 의 07-16~07-28 메트릭은 사본 없이 소멸 — §5.3). **a1 램 12→14GB 는 보류 결정**(실익 약함 — §5.3 ④). **ansible 롤 은퇴 완료**(`monitoring`·`data_tier`·`data_pipeline`·`tfstate_db` — ⚠️ `k8s_platform_apps` 는 **존치**, 종전 목록이 틀렸다). **`docker-infra-status.md` 폐기 완료**(2026-07-31 — SUPERSEDED 배너 + 호스트 C·하이퍼바이저 부분을 §4.0·§4.1 로 승계). 상세 = [§5.3](#53-p4-실행-기록-2026-07-31--진행-중).

---

## 1. 목표 토폴로지 — 노드는 램프로 늘어난다

**호스트 A 의 RAM 은 현행 VM 과 K8s 워커를 동시에 수용하지 못한다** (31GiB 에 VM 26GB 상주). 그래서 노드는 한 번에 5대가 아니라 **컷오버 단계를 따라 3→4→5 대로 늘어난다**:

```
P0        Host B 만 3노드:  master 6GB + worker-b1 11GB + worker-b2 11GB
          (Host A 는 현행 프로덕션 VM 그대로)
P1 후     구 .10 VM 파괴 + .9 정지 → Host A 여유 ~12GB
          → worker-a1 (~12GB) 생성 = 4노드  ← §2.1 HA 배치가 이때부터 실물 성립
P4        .11 정지(RAM 6GB 회수) → **worker-a2 (11GB) 생성 = 5노드** ✅ 2026-07-31
          → worker-a1 을 14GB 로 확장 (미완) · .8·.9·.11 디스크 파괴 (미완)
```

⚠️ **a2 는 계획의 14GB 가 아니라 11264MB 로 만들었다**(2026-07-31 결정) — b1/b2 와 같은 스펙으로 맞췄다.
RAM 예산(호스트 A 32GB): a1 14336(확장 후) + a2 11264 = 25GB → 여유 ~7GB로, 호스트 B(28/32)와 비슷한 수준이다.
**전제는 `.11` 정지** — 되살리면 6GB 가 빠져 예산이 깨진다(tfvars 주석에 명시).

```
최종:  Host A (.12, 32GB)             Host B (.22, 32GB)
       ├─ worker-a1  14GB (확장 대기)  ├─ master     6GB
       └─ worker-a2  11GB ✅          ├─ worker-b1 11GB
                                      └─ worker-b2 11GB

Host C (.10 — 클러스터 밖, K8s 미참여 · VirtualBox 위 Ubuntu 24.04)
└─ Harbor · Jenkins(컨트롤러 + 고정 docker 에이전트) · SonarQube   ✅ 가동 중
```

⚠️ **master 는 6GB — 3GB 로 잡지 말 것**(2026-07-27 상향). apiserver 메모리는 노드 수가 아니라 **watch 캐시**(전역 watch 컨트롤러 10개 · ArgoCD LIST-all)가 정하고, taint 를 걸어도 DaemonSet 이 master 에 올라와 0.6–1GB 를 먹는다 → 상주 추정 **2.3–4.4GB**. 사후 증설은 단일 컨트롤플레인 재부팅을 요구한다. 계산 근거 = [플랜 §2.2](./mp_k8s_infra_migration_plan.md).

⚠️ **Proxmox 호스트명이 직관과 반대다**: 호스트 B = `k8s1` · 호스트 A = `k8s2`. 무해하지만 콘솔·태스크 로그를 볼 때 혼동 주의. 호스트 B 는 **Proxmox 클러스터 없이 스탠드얼론**으로 운용한다(2026-07-27 확정 — 2노드 quorum 함정 + "컨트롤플레인 장애가 타 계층으로 번지는 결합 회피" 원칙. clusterjoin 시도 흔적은 해체 완료). 템플릿 `9002` 사본이 B 에 있어 K8s 노드 VM 클론 소스로 쓴다.

🔴 **호스트 C 의 VirtualBox 어댑터는 반드시 브리지 모드.** NAT 면 `.10` 을 LAN 에서 못 받고, **클러스터 노드가 Harbor 에서 이미지를 못 당겨 배포가 전면 실패**한다. (현재 브리지로 가동 중 — 어댑터 설정 변경 금지.)

**배치 원칙** — 무흔적 급사 3회(2026-07-19·07-21×2)가 **전부 호스트 A**였다. 그래서:
- **master·quorum 다수(ES 2 · Kafka 2 · Redis Sentinel 2) = 호스트 B**
- **PG·Redis primary = 호스트 A** (페일오버 중재자가 B에 있으므로 primary가 B면 B 급사 시 자동 승격 불가)
- **Prometheus·MinIO = 호스트 B 고정** (A 급사 시 관측·모델 경로 생존 — 로컬 PV 라 노드 고정)

→ *실측된 장애 모드*(A 급사)에서 자동 복구가 성립한다. 근거 = [`mp_k8s_infra_migration_plan.md §2.2·§5.2`](./mp_k8s_infra_migration_plan.md).

### 1.0 master 강제종료 실측 (2026-07-27)

`qm stop`(하드 파워오프 — 우리가 겪은 "무흔적 급사"와 같은 조건)으로 §2.1 의 주장을 실측했다.
대상: nginx 2 replica(워커 1대씩) + MetalLB LB `.14`, 1초 간격 샘플링.

| 항목 | 실측 |
|---|---|
| **인그레스 중단** | **0** — 151 샘플 전부 HTTP 200(apiserver 부재 71 샘플 포함) |
| apiserver 부재 | 3분 3초 (의도적 대기 포함) |
| **복구** | **전원 투입 → 26초 만에 apiserver 응답** (kubelet 활성 +17초) |
| 서빙 파드 재시작 | **0** (양쪽 워커) · cilium **agent** 도 워커에서 0 |

⚠️ **다만 "아무 일도 안 일어난다"는 아니다** — apiserver 를 상시 watch 하는 컴포넌트는 재시작한다:
cert-manager 1회 · cainjector 4회 · cilium-**operator** 3회 · kube-state-metrics 5회.
전부 apiserver 복귀 후 자동 회복했고 데이터패스와 무관하다(에이전트는 eBPF 맵으로 계속 서빙).
→ **"변경 능력만 잃고 서빙은 유지"가 실측으로 성립.** P1 에서 실제 Istio Gateway·앱 경로로 한 번 더 확인한다.

🔴 이 테스트가 **증명하지 않는 것**: master 부재 중 cilium-agent 가 재시작되면 그 노드는 복구하지 못한다
(`k8sServiceHost` = master IP 직접). 단일 master 의 구조적 한계이며 물리 3대 전에는 못 없앤다.

### 1.0.1 Cilium 라우팅 모드 = **VXLAN 확정·락** (2026-07-27 실측)

⚠️ **지금은 반쪽만 측정 가능하다** — 노드 3대가 전부 호스트 B *안*이라 노드 간 트래픽이 물리 NIC 를
타지 않는다. 그래서 측정된 것은 **캡슐화·암호화의 CPU 비용**이지 링크 특성이 아니다.

| 경로 | 대역폭 |
|---|---|
| 파드→파드 (VXLAN + WireGuard) | **2.25 Gbps**(4스트림) / **2.37 Gbps**(단일 스트림) |
| 호스트→호스트 (캡슐화·암호화 없음) | **40.2 Gbps** |

**해석이 중요하다**: 비율(18배)이 아니라 **절대값**을 봐야 한다. 호스트 A↔B 물리 링크는 **1 GbE** 이고,
암호화·캡슐화를 전부 켠 상태의 CPU 천장이 **2.25 Gbps = 실배선의 2배 이상**이다.
→ 실링크에서는 VXLAN 이든 native 든 **선을 먼저 채운다. 라우팅 모드를 throughput 근거로 고르는 논리는
이 숫자로 사실상 무력해졌다.** 단일 스트림이 4스트림과 같은 것도 같은 얘기다(코어 병렬성이 아니라
암호화·캡슐화 처리 자체가 천장).

native 로 갈 이유로 남는 것: ① 패킷당 CPU 절감 ② MTU 효율(VXLAN 헤더 50B ≈ 3~4% 페이로드 손실)
③ 디버깅 단순성. 전제 조건(전 노드 같은 L2)은 A·B 가 같은 `/24` 라 충족한다.

**남은 측정 2건 — ⓐ·ⓑ 모두 해소(ⓐ 2026-07-28 · ⓑ 2026-07-29)**: ⓐ ~~A↔B 실링크 대역·지연~~ → ✅ **실측 완료**
(worker-a1 `.20` ↔ worker-b1 `.18`, iperf3 10초): **939 Mbits/sec · RTT 평균 0.194ms · 손실 0%**
= 1GbE 라인레이트. **VXLAN 락 판단이 실링크에서도 확증됐다** — 파드 간 CPU 천장 2.25Gbps 보다
물리선 0.94Gbps 가 먼저 차므로 라우팅 모드를 native 로 바꿔도 얻을 게 없다(§1.0.1 근거 유지).
ⓑ **집계 대역** → ✅ **해소(2026-07-29 P2 리허설 실측)** — 물리 링크 `nic0` 1GbE 양단(A `.12` ↔ B `.22`)
5초 간격 샘플링. **최대 부하 = PG 재-basebackup 구간 59.7 MB/s = 1GbE 의 50.0%**(A tx 59.61 ↔ B rx 59.69
양방향 대칭), 그 외 리허설 구간 피크 7.5 MB/s = 6.3%. 판정 기준(지속 ~70%)에 닿지 않아 **go** —
배치 조정·본딩 불요. 🔴 다만 **단일 스트림이 이미 절반을 쓴다** — basebackup 을 Kafka RF=3 복제·ES 샤드
리커버리와 겹치면 합산이 선을 넘을 수 있으니 동시 실행을 피한다. 상세 = [P2 런북 §7.1](./mp_k8s_p2_data_runbook.md).

### 1.0.2 🔴 호스트 B KSM 메모리 오염 사건 (2026-07-28) — KSM 영구 비활성

**증상**: master VM 에서만 서로 다른 바이너리 다수가 랜덤 주소 크래시 — GPF 10건(ansible python3 ×8·apport ×2,
01:12~03:19 UTC) + helm 세그폴트 + **kube-apiserver SIGSEGV 2회**(`fatal error: fault`) + etcd 크래시 1회.
전형적 **게스트 메모리 오염** 패턴. 워커 2대·호스트 dmesg 무결(MCE/EDAC 없음)·발룬 3 VM 전부 꺼짐.

**정황**: LGTM 선배포로 VM 상주가 늘며 호스트 B 램 90%(VM 28.7G/32G) → **ksmtuned 공격 모드,
KSM 병합 4.75GB**(125만 페이지) 상태. master 는 ansible 이 단명 프로세스를 다량 스폰해 CoW 가 가장 격렬한 VM.

**조치(2026-07-28, 승인 완료)**: `echo 2 > /sys/kernel/mm/ksm/run`(정지+전량 언머지) + `ksmtuned` stop·disable.
언머지 후 호스트 used 25.0→29.5GB·free ~2.5GB·스왑 폭주 없음. **이후 동일 워크로드(플레이북 전체) 재현 = GPF 0·크래시 0.**
비상 대비로 **etcd 스냅샷 확보**(`snap-emergency-20260728.db` 38MB — master `/var/lib/etcd/` + 오프 VM 사본, sha256 검증).

- 🔴 **호스트 B 에 KSM 을 다시 켜지 말 것**(재구축 시 ksmtuned 재활성 주의 — 이 조치는 IaC 밖 수동 설정이다)
- 관찰 방법: `ssh ubuntu@.17 'sudo dmesg -T | grep -cE "general protection|segfault"'` — 당시 기준선 **10**(2026-07-28. ⚠️ 이후 재부팅으로 **0 리셋** — 아래 참조)
- 여파: KSM 절약분이 사라져 호스트 B 여유 ~2.5GB — 부족해지면 워커 11→10GB 감축이 예비안

**🔴 재발 확인 (2026-07-28 오후) — KSM 무죄, 물리 RAM 유력으로 승격.** KSM 완전 off 상태에서
GPF 10→**12**: `landscape-sysinfo`(05:07 UTC)·`unattended-upgrades`(06:14 UTC, **libapt-pkg C++**
— 파이썬 아님). 둘 다 **부하와 무관한 유휴 시스템 데몬**이고, 같은 시간대에 돌린 무거운 ansible 런들은
무사 — 랜덤 시점·랜덤 바이너리·랜덤 주소 = 전형적 램 오염. 워커 2대·호스트 dmesg 는 여전히 0건
→ **master VM 이 앉은 물리 램 영역 불량**이 최유력. etcd 스냅샷 2호 확보(`snap-20260728-2.db`, 오프 VM).
- 🔴 **다음 조치 = memtest86+** (호스트 B 전체 다운 수 시간 — 일정 사용자 결정 대기). 불량 주소 확인 시
  선택지: RAM 교체 또는 Proxmox 커널 `memmap` 으로 불량 영역 마스킹(저예산 대안)
- 임시 완화 후보: master VM cold restart 로 램 배치 재추첨(컨트롤플레인 1~2분 부재 — 서빙 유지는
  §1.0 실측으로 성립. 단 **복불복**이며 수리가 아니다)

**🔴 오염이 디스크까지 도달 — etcd WAL 파손·스냅샷 복원 (2026-07-28 저녁).** memtest 준비로 VM 을
정상 종료 후 재기동하자 etcd 가 `walpb: crc mismatch` 로 크래시루프 — **램 오염이 etcd WAL 에 쓰레기를
써 넣었고 그게 디스크에 남은 것**(램 불량 가설의 물증이자, 오염 창의 쓰기가 신뢰 불가함을 실증).
**복원 절차(성공 — 이대로가 etcd 복구 런북이다)**: ① 사전 스냅샷(`snap-20260728-3-premtest.db`,
셧다운 7분 전·sha256 양측 검증) ② kubelet stop ③ `ctr -n k8s.io run … registry.k8s.io/etcd:3.6.5-0
etcdutl snapshot restore <snap> --name k8s-master --initial-cluster … --data-dir <new>`(호스트에 etcdutl
없어도 이미지로 실행) ④ 파손 `member` → `member.bad` 로 보존·복원본 투입 ⑤ kubelet start →
컨트롤플레인 1/1 · 노드 3 Ready · ArgoCD 전 앱 정상 복귀. **유실 = 0**(7분 창은 셧다운 준비 중이라 무변화).
- 교훈: **스냅샷은 "파괴적 작업 직전" 반드시** — 이번 건이 관행의 실전 검증. S3 오프사이트(P2 게이트)의
  필요성도 재실증(이번엔 스냅샷이 로컬에 있어 살았지만, 호스트 통째 손실이면 오프사이트만 남는다)
- 재부팅 후 GPF 기준선 리셋 = **0**(새 카운트 시작 — 램 배치 재추첨 효과 여부는 memtest 가 판정)
- 잔여물: master `/var/lib/etcd/member.bad`(파손 원본 — memtest 결론 후 삭제) · memtest86+ 설치·grub
  엔트리는 야간 실행용으로 존치
- 🔴 **memtest 는 아직 미실행**(2026-07-28 저녁 확인: 호스트 B 는 16:15 에 일반 pve 커널로 복귀,
  `grub-editenv list` 의 `next_entry` 비어 있음 = 원샷 엔트리가 장전된 적 없음). 실행 = `qm shutdown 301/302/303`
  → `grub-reboot memtest86+ && reboot`. **LVM 이라 원샷 플래그가 자동으로 안 지워진다** — memtest 후
  Proxmox 로 복귀할 때 GRUB 수동 선택 + `grub-editenv /boot/grub/grubenv unset next_entry` 필요

### 1.0.3 🔴 worker-b1 읽기 데이터 오염 (2026-07-29) — **오염이 두 번째 VM 으로 확산**

§1.0.2 는 master VM 이야기였다. **worker-b1 에서도 같은 계열의 오염이 확인됐고, 이번엔 "랜덤 크래시"가 아니라
읽는 바이트가 실제로 달라지는 것**을 재현 가능한 형태로 잡았다.

**재현 (수 초, 읽기 전용)** — 같은 이미지의 같은 파일을 **파드를 바꿔가며** 해시한다:

| 읽은 시점 | b1 | b2(대조군) |
|---|---|---|
| 최초 | `7daf3866…` | `713eb8a6…` |
| 이미지 재pull 후(스냅샷 재사용) | `7daf3866…` | — |
| 스냅샷 purge + **실제 재다운로드** 후 | `e6dad178…` | — |
| 그 다음 파드에서 ×4회 연속 | `5ea5dc9b…`(4회 동일) | `713eb8a6…`(3회 동일) |

**한 프로세스 안에서는 항상 같고**(페이지캐시), **파드를 새로 뜨우면 매번 다른 값**이 나온다 →
디스크에서 페이지캐시로 올리는 경로에서 깨진다. b2·a1 은 몇 번을 읽어도 정본(`713eb8a6…`) 그대로다.
디스크 I/O 에러·EDAC/MCE 기록은 **없다**(조용한 오염).

**어떻게 드러났나**: alloy(471MB 바이너리)가 b1 에서만 21시간 크래시루프.
`cannot allocate 144115188080050176-byte block` = **2⁵⁷ + 4MiB** — 4MiB 요청의 57번 비트만 켜진 값이다
(바이너리 안 상수가 깨진 결과). 격리 순서 = 프로브 4개(상태 없음 / 상태 사본 / **로그 미마운트** / **b2 동일 스펙**)
→ 앞 3개는 b1 에서 동일하게 즉사, b2 것만 정상 → tail 상태·로그 내용·컨테이너 한도 전부 배제되고 **노드만 남았다**.
직전 정황으로 커널 로그에 `clang` 세그폴트 3연발(07:28, CPU 3·5·2 · 동일 IP)이 남아 있다.

**조치**: 손상 스냅샷 7개를 chainID 로 지목해 purge → 재다운로드(1.1초 로컬 재사용 → **7.9초 실다운로드**로 바뀜)
→ alloy 4노드 전부 `2/2 Running`·재시작 0 복구. 🔴 **단 이건 증상 제거일 뿐 수리가 아니다** —
새로 받은 파일조차 정본 해시와 다르다(그 오염이 우연히 무해한 자리에 떨어졌을 뿐).

- 🔴 **P2 함의**: 이 노드에 **데이터 티어를 올리면 안 된다.** PG/ES/Kafka 는 큰 파일을 끊임없이 읽고 쓰는데,
  b1 은 그 경로에서 **조용히** 바이트를 바꾼다(체크섬을 켜도 "손상 감지 후 정지"가 될 뿐 예방이 아니다).
  memtest 가 "언젠가"에서 **P2 착수 전 선행조건**으로 승격됐다 — §5 P2 행 참조.
- 🔴 **containerd 는 이런 오염을 못 잡는다**: pull 시점에만 digest 를 검증하고, 압축해제된 스냅샷은
  이후 재검증하지 않는다. 게다가 **레이어 blob 이 지워져도 chainID 스냅샷이 있으면 unpack 을 건너뛴다**
  → "이미지 삭제 + 재pull" 로는 절대 안 고쳐진다(1.1초 = 로컬 재사용의 신호). 반드시 스냅샷까지 지울 것.
- **점검 도구**(재사용 가능): `python3 verify-blobs.py`(blob 이름=sha256 자체검증) ·
  `purge-snapshots.py --apply`(config 의 diffID → chainID 계산 → 스냅샷 지목 삭제). 순서 = **taint 로 파드
  재생성 차단 → 이미지 참조 제거 → 스냅샷 purge → untaint**(안 그러면 DaemonSet 이 즉시 참조를 되잡는다)
**전수 점검 (2026-07-29 — `infra/scripts/audit-layers.py`)**

🔴 **blob 검증만으로는 부족하다**: containerd 2.x 는 unpack 후 레이어 blob 을 버려서(`discard_unpacked_layers`)
콘텐츠 스토어에는 매니페스트·config 만 남는다(b1 실측 = **133개·0.16GB, 불일치 0**). 실제 컨테이너 파일 내용은
**체크섬이 없는 스냅샷**에만 있다. → 유일한 검증 수단 = **chainID 단위 노드 간 트리해시 대조**
(같은 chainID = 어느 노드에서든 같은 내용이어야 한다).

| 검사 | 결과 |
|---|---|
| b1 Committed 레이어 | **219개** 해시 |
| b1 자체 재현성(페이지캐시 비우고 2회) | **불일치 0** — 노드 전반의 읽기는 안정적이다 |
| b1 ↔ b2 공통 94개 | **불일치 1개** |
| b1 ↔ a1 공통 64개 | **불일치 1개**(같은 레이어) |
| 그 1개 | `sha256:048d7d40…` = **단일 파일 레이어 `/usr/bin/alloy`(471MB)** |

→ **오염은 그 파일 하나에 국한**됐고 나머지는 세 노드가 바이트 단위로 동일하다. 그 파일에서만 지금까지
**5가지 값**이 관측됐다(`7daf3866`→`e6dad178`→`5ea5dc9b`→`06d3451d`→`613d9689`) — 노드 전체가 아니라
**가장 큰 파일 하나의 영역이 불안정**한 모양이다.

**최종 조치·검증**: purge+재다운로드를 **2회** 수행(1회차는 새로 받은 것조차 정본과 달랐다 — 오염 창이
아직 열려 있었거나 그 디스크 영역이 나쁘다는 뜻) → 2회차에서 정본 `713eb8a6…` 일치(4회 연속 동일) →
**전수 재대조 = b2 와 94개 불일치 0 · a1 과 64개 불일치 0**, alloy 4노드 `2/2 Running`·재시작 0.

- ⚠️ 이 결과는 **"지금 디스크 위 내용이 정합하다"**는 뜻이지 **하드웨어가 무죄라는 뜻이 아니다.**
  같은 파일을 다시 받았을 때 한 번은 또 깨졌다 — memtest(P2 선행조건 ②)는 그대로 유효하다.
- 재점검 방법: `sudo python3 infra/scripts/audit-layers.py /tmp/lay-<node>.json` 을 노드들에서 돌리고
  공통 chainID 의 해시를 비교한다(캐시 비우고 2회 = 읽기 안정성까지 같이 본다).

**하드웨어 판정 (2026-07-29 · 무중단 조사분)**

| 갈래 | 실측 | 판정 |
|---|---|---|
| **호스트 B 램** | `dmidecode`: DDR4 16GB×2 · 🔴 **`Error Correction Type: None`**(Total Width 64 = Data Width 64) | **비-ECC** → MCE/EDAC 무기록은 **무죄 증거가 아니다**. 조용한 오염이 설계상 정상 동작 |
| **저장 경로** | VM 은 전부 `pve` VG = **PV `/dev/sdb3` 단독**(CT1000MX500SSD1). Reallocated 0 · Pending 0 · Offline_Uncorrectable 0 · Reported_Uncorrect 0 · 수명 83% 잔여 · UDMA_CRC 3 | **정상** — 저장 매체 기인 가능성 낮음 |
| (참고) `/dev/sda` | CT250MX500SSD1 · **수명 10% 잔여(90% 소진)** · 그러나 파티션이 전부 **NTFS**(구 Windows)로 Proxmox 미사용 | 우리와 무관 |

🔴 **확정 (2026-07-29 02:01 UTC · `stressapptest` 10분, b1 VM 내부 4GB)** — 추정 단계 종료.

```
Status: FAIL - test discovered HW problems
Stats: Found 396320 hardware incidents          ← 10분 만에 39.6만 건
Hardware Error: miscompare at 0x…(0x1af2b0187) read:0xf5ff… expected:0xffff…  'OneZero~128'
                                               reread 도 같은 값
```

판정 근거 3가지 — **고정·국소 결함**이다(간헐적 랜덤 오염이 아니다):
1. **stuck-at 비트**: `expected 0xffff…` 인데 `0xf5ff…`(비트 1·3 이 0), 반대로 `expected 0x0000…` 에
   `0x8600…`(비트 1·2·7 이 1). 특정 셀이 값을 못 바꾸는 전형적 모습.
2. **read == reread** — 다시 읽어도 같은 값 = 읽기 경로의 우연이 아니라 메모리 내용 자체가 틀리다.
3. 🔴 **주소가 극도로 몰려 있다**: 게스트 물리 `0x1af2b0187` ~ `0x1af2b138f` = **약 4.6KB 범위**
   (사실상 물리 페이지 1~2개). 램 전체가 아니라 **한 자리**가 죽었다.

→ **그래서 마스킹이 원리적으로 완전히 유효한 케이스다** — 그 페이지만 안 쓰면 증상이 사라진다.
⚠️ 단 위 주소는 **게스트 물리 주소**다. 배제는 **호스트 물리 주소** 기준이라 호스트 레벨 검사가 필요하다
(`CONFIG_MEMTEST=y` 확인됨 → 부팅 옵션 `memtest=4` 로 호스트가 직접 찾아 예약. 결함이 이렇게 단단하면
약한 커널 검사로도 잡힐 가능성이 매우 높다).

**비용 판단**: 통짜 기계 교체는 불필요하다. 디스크 정상 · CPU 정상 · **불량은 램 한 자리**다.
선택지 = ① `memtest=4` 마스킹(무료·재부팅 1회) ② 램 페어 교체(수만 원, 확정 수리).

🔴 **결정 = 램 교체 (2026-07-29, 사용자 확정)** — `memtest=4` 마스킹·memtest86+ 진단은 **채택하지 않는다**.
불량이 고정·국소라 마스킹으로도 가릴 수 있었지만, 원인이 이미 하드웨어로 확정된 이상 **부품 교체가 확정 수리**다.
→ §1.0.2 의 "다음 조치 = memtest86+"는 **이 결정으로 대체됨**. 아래 격리도 **원복했다**(2026-07-29).

- 🔴 **교체 후 검증은 호스트 레벨이어야 한다** — 게스트(b1) 안 `stressapptest` 는 **그 VM 에 배정된 페이지만**
  훑으므로 "불량 발견"에는 충분했어도 **"새 램이 깨끗함"의 증명은 못 된다**(32GB 중 일부만 본다).
  → **교체 직후·Proxmox 부팅 전에 GRUB 메뉴의 `Memory test (memtest86+x64.efi)` 로 최소 1패스**
  (엔트리 실재 확인 2026-07-29 · memtest86+ 7.20 · UEFI). **호스트가 어차피 꺼져 있는 시점이라 추가 다운타임 0.**
  부팅 메뉴에서 직접 고르면 `grub-reboot` 원샷 플래그 함정(LVM 에서 자동 해제 안 됨)도 안 밟는다.
- 그 **다음** 단계로 `stressapptest -M 4096 -s 600 -m 3 -W`(b1) + 카나리 — 이건 램 검증이 아니라
  **실제 워크로드 경로 확인**이다. 참고: 불량 시 이 검사는 10분에 39.6만 건을 냈다(재현성 확보).
- 한 짝만 교체할 계획이면 **교체 전에도** memtest86+ 를 돌려 실패 주소로 슬롯/스틱을 특정할 것.

**교체 완료·검증 (2026-07-29 12:00 KST)** — 램 교체됨: 두 슬롯 모두 `M378A2K43CB1-CTD` = **매칭 페어**
(교체 전에는 ChannelB 가 `…DB1-CTD` 로 리비전 혼용이었다). 32GB·2667 MT/s 인식, ECC 는 여전히 None(같은 플랫폼).

| 검사 | 결과 |
|---|---|
| **stressapptest ×3 VM 동시**(master 2GB · b1 7GB · b2 6GB = 15.3GB, 각 600초) | 🟢 **전부 `Status: PASS`** — 누적 **33.2TB** 전송, **hardware incidents 0** |
| ↳ 그중 b1 (교체 전과 동일 조건) | 🟢 **0건** ← **교체 전 같은 검사에서 396,320건** |
| 카나리 b1·b2 (교체 전 baseline 과 대조) | 🟢 direct·cached 양 경로 일치 — 정전·교체를 건너 512MB 파일 무손상 |
| alloy 바이너리(과거 오염 대상) 3회 읽기 | 🟢 정본 `713eb8a6…` 일치 |
| 이미지 레이어 전수 대조(b1 ↔ b2, 공통 chainID 65) | 🟢 **불일치 0** |
| 정전 왕복 | 🟢 4노드 Ready · etcd `health: true` · 비정상 파드 0 (7/28 과 달리 WAL 파손 없음) |

🟢 **호스트 레벨 검증 완료 (2026-07-29 13:0x KST) — P2 선행조건 ② 종결**

| 검사 | 결과 |
|---|---|
| **memtest86+ 1패스**(GRUB 엔트리, 32GB 전량·베어메탈) | 🟢 **Errors: 0 · PASS** |
| **커널 `memtest=4`**(부팅 시 자동, 커널 구간 제외 거의 전량) | 🟢 `early_memtest: # of tests: 4` 실행 · **`bad mem` 0건**(예약된 불량 구간 없음, 램 31GB 그대로) |
| 정전 왕복 후 클러스터 | 🟢 4노드 Ready · etcd `healthy` · **비정상 파드 0** · `.14` HTTP 200 |
| 카나리 b1·b2 (교체 전 baseline 대조) | 🟢 direct·cached 일치 |
| ArgoCD | 🟢 8 Synced + 11 OutOfSync(= mp-* 앱 child, **P1 상태 그대로**) |

→ **`memtest=4` 는 검증 후 원복**(`/etc/default/grub` 에서 제거 + `update-grub`, grub.cfg 잔존 0 확인).
상시로 두면 매 부팅마다 검사가 붙는다.

⚠️ **재기동 직후 ArgoCD 함정**(실측): 앱 19개를 **동시에** hard refresh 하면 repo-server 의 `helm pull` 이
`timeout after 1m30s` 로 무더기 실패해 `Unknown` 이 된다(노드 egress 는 정상이었다 — DNS·HTTPS 실측 OK).
**하나씩, 이전 것이 끝난 뒤에** 리프레시하면 정상 복귀한다. 재부팅 후 `Unknown` 이 보이면 이걸 먼저 의심할 것.
- ⚠️ **교체 전까지는 b1 이 계속 오염시킨다** — 아래 격리를 되돌렸으므로 워크로드가 다시 올라간다.
  부품 대기 중 다시 빼고 싶으면 `kubectl cordon k8s-worker-b1` 한 줄이면 된다(소개 절차는 아래 표 그대로).

**격리 조치 (2026-07-29 · 무중단 수행 → 램 교체 결정에 따라 같은 날 원복)** — 재격리가 필요할 때의 절차로 남긴다.

| 조치 | 내용 |
|---|---|
| `kubectl cordon k8s-worker-b1` | 신규 스케줄 차단 |
| 워크로드 소개(疏開) | 18개 파드를 a1·b2 로 이동. **비정상 파드 0**, 앱 스모크 정상(`.14` HTTP 200) |
| 🔴 게이트웨이 | **단일 복제였고 하필 b1** — 그냥 지우면 유입 단절이라 **2개로 늘려 다른 노드에 띄운 뒤** b1 것을 뺐다. **당분간 2개 유지**(호스트 B 재부팅 때 b2 가 내려가도 a1 이 유입을 받는다). 재부팅·수리 완료 후 1개로 환원 |
| 🔴 CoreDNS | **2개 전부 b1 에 있었다** — 동시에 지우면 DNS 단절이라 **하나씩** 옮겼다 |
| 카나리 | `node.kubernetes.io/unschedulable` **toleration 추가** — 워크로드는 빼되 **감시는 남긴다**(cordon 상태에서 실행 확인 완료) |
| ⬜ 남은 것 | **`tempo-0` 는 b1 에 묶여 있다**(OpenEBS 로컬 PV `storage-tempo-0` — 노드 이동 불가). 예비 관측 스택이라 영향은 낮지만, **그 파드는 여전히 불량 램 위에서 돈다**. 옮기려면 PVC 삭제(=로컬 트레이스 유실, 완성 블록은 MinIO 에 있음)가 필요 — 수리 방식 확정 후 판단 |

b1 잔류 = **DaemonSet 7 + tempo-0** 뿐. 노드 분포 = master 10 · a1 26 · **b1 8** · b2 30.

**원복 (2026-07-29 · 램 교체 결정 직후)**: `uncordon k8s-worker-b1` · 게이트웨이 replicas **2→1**(a1 상주) ·
검증 = 비정상 파드 0 · `.14` HTTP 200. **카나리는 유지**한다 — 램 교체가 실제로 먹혔는지 확인해 줄 장치라
교체·검증 완료 전까지 지우지 않는다(삭제 = `kubectl delete -f infra/diagnostics/bitrot-canary.yaml`).
b1 에 `memtester`·`stressapptest` 도 설치된 채 둔다(교체 후 검증에 그대로 쓴다).

**카나리 감시 (2026-07-29 가동 — `infra/diagnostics/bitrot-canary.yaml`)**

512MB 고정 파일을 30분마다 다시 읽어 해시 변화를 본다. **b1(용의자) + b2(대조군)** 두 벌 —
b1 만 울리면 노드 국소, 둘 다면 호스트 B 전체다. 두 경로를 분리해 어느 계층인지도 같이 나온다:
`direct`(O_DIRECT = 저장 경로) · `cached`(페이지캐시 = 메모리 경로). 불일치 시 **Job 실패**로 남는다
(`backoffLimit: 0` — 재시도가 성공하면 사건이 묻히므로 금지). 확인 = `kubectl -n kube-system get jobs -l app=mp-bitrot-canary`.
초기 검증 통과(양 노드 baseline 생성 + 재검사 direct·cached 모두 일치).

- 🔴 **아직 자동 알람은 없다** — 아래 브리지 필터 때문. 지금은 **사람이 Job 상태를 봐야** 한다.
- memtest 로 원인이 확정되면 이 파일째 삭제한다(임시 진단물).

🔴 **P1 관측 브리지가 `namespace="app"` 만 전달한다 (2026-07-29 실측)**

```
remoteWrite[0].writeRelabelConfigs = [{action: keep, regex: app, sourceLabels: [namespace]}]
```

즉 **in-cluster 지표 중 app ns 것만 `.11` 로 간다.** 확인: `.11` 의 `kube_pod_info` = 12개(전 클러스터 아님),
`up{job="kube-state-metrics"}` 없음. 여파가 둘이다:

1. **카나리(kube-system)는 `.11` 에서 알람을 걸 수 없다.** 규칙을 걸려면 keep 규칙을 넓혀야 한다
   (권장 = 전량 개방이 아니라 **대상 시리즈만 추가 keep** — 예: `kube_job_status_failed{job_name=~"mp-bitrot-canary.*"}`).
2. 🔴 **P2 계획에 직접 걸린다** — 런북 Q9 는 "in-cluster 수집 → remote_write → `.11` 규칙 평가"를 전제로
   PG·PGSync 규칙을 재작성한다고 돼 있는데, **CNPG·PGSync 지표는 `data` ns** 라 현재 필터에서 전부 버려진다.
   P2 전에 이 필터를 손보지 않으면 **새 알림 규칙이 조용히 아무것도 평가하지 않는다.**
✅ **결정: VXLAN 유지·락** (2026-07-27). 처리량 근거가 사라진 상태에서 native 가 주는 건 MTU 3~4% 인데,
전환은 Cilium agent 재시작 + **파드 네트워크 순단**을 요구한다 — 얻는 것보다 지불이 크다.
따라서 "A↔B 실링크 측정을 기다린다 → worker-a1 을 앞당긴다"는 일정 모순도 함께 해소됐다(측정을 기다릴 이유가 없다).

🔴 **재검토 트리거는 성능이 아니라 링크 포화다** — P2 직전 집계 측정에서 1GbE 가 포화하면
답은 라우팅 모드가 아니라 **NIC 본딩·2.5GbE·배치 조정**이다(라우팅 모드로는 3~4% 밖에 못 되찾는다).
근거 상세 = [플랜 §3.2](./mp_k8s_infra_migration_plan.md).

### 1.1 IP 주소 배치 (192.168.0.0/24)

| 대역 | 용도 | 상태 |
|---|---|---|
| `.8` · `.9` · `.11` | ~~구 VM 3대 (fb-data · fb-app-ai · fb-monitoring)~~ — **2026-07-31 P4 에서 실물 파괴**(§5.3 ⑤) | 🟢 **회수 완료 — 재사용 가능** |
| `.10` | **물리 호스트 C** (Harbor·Jenkins·SonarQube — 구 fb-ci-harbor VM 에서 IP·인증서 승계, **영구**) | ✅ 사용 중 |
| `.12` | 물리 호스트 A (Proxmox `k8s2`) | 사용 중 |
| `.14`–`.16` | **MetalLB IP 풀** (`.14` 공개 GW · `.15` 내부 GW · `.16` 카나리·업그레이드 일시 병행용 여유) | 예약 |
| **`.17`–`.19`** | **K8s 노드 3대** — `k8s-master` · `k8s-worker-b1` · `k8s-worker-b2` (호스트 B) | ✅ 사용 중 |
| **`.20`–`.21`** | **K8s 노드 2대 (호스트 A)** — `k8s-worker-a1`(2026-07-28 합류) · `k8s-worker-a2`(2026-07-31 합류, **5노드 완성**) | ✅ 사용 중 — 🔴 **할당 직전 실점유 확인 필수**(arp/ping 스윕 + 공유기 DHCP 예약 대조. `.13` 도 예약해 뒀다가 타인 VBox 장비가 물고 있어 폐기했다). 점유 시 다음 빈 IP 로 밀고 **tfvars·pg_hba·이 표를 같은 값으로 정렬** |
| **`.22`** | **물리 호스트 B** (Proxmox `k8s1`) | ✅ 사용 중 |

🔴 **공유기 DHCP 범위가 `.14`–`.21`(예약 대역)과 겹치면 ARP 충돌**("가끔 안 됨" 형 장애) — 시작 주소를 **`.23` 이상**으로. **확인 생략하고 진행함**(2026-07-27 결정): 대역은 `1–254` 전체가 DHCP 후보지만 사용자 간 암묵적 합의로 운용되며, 노드 생성 전 `.14`–`.21` 8개 주소가 ping 무응답인 것만 확인했다. → 나중에 산발적 단절·`Duplicate address detected` 가 나오면 **1순위 용의자**. 특히 MetalLB VIP(`.14`–`.16`)는 gratuitous ARP 로 광고하므로 정적 노드 IP 보다 충돌에 민감하다. *(`.13` 은 타인 장비(VirtualBox 게스트)가 상주해 예약에서 제외 — 구 계획의 호스트 B 예약분이었으나 `.22` 로 변경. `.177` 예약도 폐기 — 호스트 C 가 `.10` 승계.)*

---

## 2. 컴포넌트 구성 (확정 사양)

결정 근거는 전부 [`mp_k8s_infra_migration_plan.md`](./mp_k8s_infra_migration_plan.md)에 있다. 여기는 *무엇으로 정해졌는가*만 적는다.

**버전 핀 (2026-07-27 설치분)** — 🔴 **상한을 정하는 건 Cilium 이다**: 최신 릴리스 1.19.6 이 e2e 검증한 K8s = **1.31–1.34**. Istio 1.30 은 1.32–1.36 을 덮으므로 교집합 최댓값이 1.34 다. **1.35·1.36 으로 올리지 말 것** — kube-proxy 대체(eBPF)는 K8s API·커널 결합이 깊어 "하위호환으로 될 수도"에 걸 자리가 아니다. 1.33 은 이미 EOL. ⚠️ 1.34 EOL = **2026-10-27** → Cilium 1.20 릴리스 후 `kubeadm upgrade` 로 1.35 (무중단 마이너 업그레이드 = 발표 데모 소재).

| 대상 | 핀 | 비고 |
|---|---|---|
| Kubernetes | **1.34.10** | `apt-mark hold` (kubelet·kubeadm·kubectl) — 마이너 자동 상승 = 스큐 파손 |
| Cilium | **1.19.6** | Helm 차트. 값 = `/etc/kubernetes/cilium-values.yaml`(→ 나중에 config 레포로 이관) |
| containerd | **2.2.6** | Docker 공식 저장소. ⚠️ 2.x 는 pause 키 이름이 `sandbox`(1.7 = `sandbox_image`) |
| Helm | **3.21.3** | Helm 4 회피 — ArgoCD 번들 렌더러가 3.x 계열이라 렌더 결과를 맞춘다 |
| MetalLB | **0.16.1** | FRR-K8s 끔(BGP 전용). 풀 `autoAssign=false` |
| OpenEBS LVM LocalPV | **1.9.1** | SC 2종. 노드 VG = `openebs-vg`(scsi2) |
| cert-manager | **v1.21.0** | CRD 를 차트가 관리(`crds.enabled`) |
| MinIO | 차트 **5.4.0** / 이미지 **RELEASE.2025-09-07T16-13-09Z** | ⚠️ GitHub 릴리스 태그 ≠ 이미지 태그(§3) |
| kube-prometheus-stack | **87.20.0** (Operator v0.92.1) | node-exporter 는 **끄고**(`nodeExporter.enabled=false`) kube-system 에 별도 |
| prometheus-node-exporter | **4.56.1** | kube-system 배치 — 호스트 접근 필요(§3) |
| metrics-server | **3.13.1** | `--kubelet-insecure-tls`(정석 전환 = kubelet `serverTLSBootstrap` + CSR 승인) |
| External Secrets | **2.8.0** | Kubernetes provider |
| Istio | **1.30.3** | base + istiod + cni(체이닝) |
| Gateway API | **v1.6.1** | standard 채널 |
| ArgoCD | **10.2.1** (v3.4.5) | platform AppProject + Application 3(LGTM) — 앱 트랙 배선은 §4.2 대기 |
| Loki | 차트 **7.1.0** (3.6.8) | **SingleBinary**·MinIO 백엔드·168h — ArgoCD Application(§4.3) |
| Tempo | 차트 **1.24.4** (2.9.0) | 모놀리식·MinIO 백엔드·168h — ArgoCD Application(§4.3) |
| Alloy | 차트 **1.11.0** (v1.18.0) | DaemonSet·**kube-system**(hostPath) — ArgoCD Application(§4.3) |

| 계층 | 구성 | 상태 |
|---|---|---|
| **컨트롤플레인** | **kubeadm 직접** (Kubespray 기각 — 플랜 §2.5) · master ×1 (VIP/HAProxy 불필요) · etcd 스냅샷 → S3 · **metrics-server**(HPA 전제) | 🔶 init 완료(1.34.10, `controlPlaneEndpoint=.17:6443` · kubelet 예약 명시) · **etcd 스냅샷·metrics-server 미착수** |
| **CNI** | Cilium (eBPF) · kube-proxy 대체 · `socketLB.hostNamespaceOnly=true` 🔴 | ✅ 1.19.6 — `cni.exclusive=false` 도 선반영(Istio CNI 체이닝 전제) |
| **라우팅 모드** | ✅ **VXLAN 확정·락** (2026-07-27 실측 — 예상이던 native 를 뒤집음) | ✅ 가동 중. 근거 = §1.0.1 / [플랜 §3.2](./mp_k8s_infra_migration_plan.md) |
| **노드 간 암호화** | Cilium WireGuard (파드 간 — 호스트 네트워크까지 덮으려면 `nodeEncryption` 별도) | ✅ `cilium_wg0` peers 2 (`nodeEncryption: Disabled`) |
| **외부 LB** | MetalLB (L2) · 풀 `.14`–`.16` · **`type: LoadBalancer` 는 게이트웨이 전용 — 상시 2개**(공개 `.14` + 내부 `.15`), 개별 서비스 노출 금지 | ✅ 2026-07-30 완성 |
| **남북 L7** | Gateway API · 구현체 = Istio · TLS 종단 | ⬜ |
| **서비스 메시** | Istio **sidecar** (ambient 기각) · **app ns 11 워크로드**(FastAPI 9 + frontend + ranking-serving)만 주입 · data·pipeline ns 제외 | ⬜ |
| **스토리지** | OpenEBS LVM LocalPV (CSI · RWO · WaitForFirstConsumer) — **RWX 금지** | 🔶 워커에 VG `openebs-vg`(150G) 준비됨 · **CSI 오퍼레이터·StorageClass 미설치** |
| **오브젝트** | MinIO(내부: Loki·Tempo 백엔드·모델 아티팩트) — **단일 replica(SNSD)·호스트 B 고정·"전 컴포넌트 HA"의 문서화된 예외** + AWS S3(백업, ap-northeast-2) | ⬜ |
| **접근통제** | 표준 NetworkPolicy + Cilium CNP FQDN egress (Gemini — chat·ocr) | ⬜ |
| **Secret** | ESO — **백엔드 = Kubernetes provider**(전용 소스 ns 의 Secret, 적재는 Ansible←secrets.yml). EKS 시 백엔드만 Secrets Manager+IRSA 로 교체 | ⬜ |
| **인증서** | cert-manager (온프렘 CA Issuer → EKS 시 ACM/LE 로 교체) | ⬜ |
| **관측** | **kube-prometheus-stack**(Prometheus Operator · ServiceMonitor · PrometheusRule — 알림규칙 20개 이관) · Prometheus 로컬 PV·**호스트 B 고정** · Loki·Tempo(MinIO 백엔드) · Grafana·Alertmanager 는 기존 설정 승계 · Hubble · Istio telemetry | ⬜ |
| | *Mimir 기각(규모 1~15%·알림경로 길어짐 — 플랜 §9.1) · P1 과도기 = in-cluster Prometheus **agent 모드** → `.11` remote_write(알림 자산 무손실)* | |
| **CI** | **Jenkins** (호스트 C · 레포 루트 `Jenkinsfile` · 고정 docker 에이전트) — CATALOG 14 이미지 + `RELEASE_VERSION` 릴리스 태깅 + pytest·Trivy 게이트 + SonarQube(측정) · 트리거 = **GitHub 웹훅 즉시**(`ci.mealbong.cloud` → Cloudflare Tunnel) | ✅ **가동** |
| **CD** | **ArgoCD 가 유일한 CD** (GitOps · 별도 config 레포 · overlays/onprem·eks · **config 레포 핀은 `:sha`** — `:latest` 금지). Jenkins 는 배포하지 않는다. **클러스터 자동 CD 가동·실증**(2026-07-29): Jenkins config 커밋(mealbong-ci) → **ArgoCD 즉시 웹훅**(in-cluster cloudflared → argocd-server `/api/webhook` 만 노출) → auto-sync(안전모드). 3분 폴링 없이 config push→~2초. 은퇴 예정 compose `.9` 만 수동 | ✅ **가동** |
| **레지스트리** | Harbor (호스트 C `.10`) · 프로젝트 **`mealplanning/`** · 앱 트랙 베이스라인 `:1.1.9` (파이프라인 트랙 1.1.10+ 과 별개) | ✅ **가동** |
| **CronJob 시간대** | `spec.timeZone: Asia/Seoul` — 현행 크론탭의 UTC 환산(vixie-cron `CRON_TZ` 미지원 우회)을 KST 로 복원 | ⬜ |

### 2.1 데이터 티어 (in-cluster · ✅ P2 구축·컷오버 완료 2026-07-30)

> 아래 표는 설계 사양. 실가동 상태·이후 보강(PG memory 2Gi req=lim — BestEffort 커널 OOM 1순위 해소)은 §0 표 참조. Pooler 앱 전환·검증은 P3.

| | 구성 | 배치 | RAM |
|---|---|---|---|
| **PG** (CloudNativePG) | primary + standby · **비동기 복제** 🔴 | primary=A · standby=B | 2×2 = 4GB |
| **ES** (ECK) | 3 노드 · `number_of_replicas: 1` · 🔴 **인증 켬 + HTTP TLS 끔**(암호화는 WireGuard 담당 — PG-SSL 비채택과 동일 논리) · **nori 커스텀 이미지**(`mp-elasticsearch-nori`) | B에 2 · A에 1 | 3×1.5 = 4.5GB |
| **Kafka** (Strimzi) | KRaft combined 3 · RF=3 · `min.insync.replicas=2` 🔴 · `auto.create.topics.enable=false` | B에 2 · A에 1 | 3×1 = 3GB |
| **Redis** | primary + replica + Sentinel ×3 · **비영속 유지** 🔴 | primary=A · Sentinel B에 2 | ~1.2GB |
| **Pooler** (PgBouncer) | CNPG `Pooler` CRD · `transaction` 모드 · replica 2 + PDB 🔴 | A·B 분산 | ~0.3GB |
| **PGSync** | Deployment **replicas=1 고정**(복제 슬롯=단일 소비자) · `pg-rw` **직접 접속**(Pooler 우회 — LISTEN/NOTIFY) · PriorityClass 는 app 급(서빙 인덱스 생산자) | — | ~0.3GB |
| **redis-pgsync** | 비영속 Deployment 1 — **앱 Redis 와 통합 금지**(AOF 사고 격리 교훈) | — | ~0.1GB |
| | | **합계** | **~13.4GB** |

> **CNPG·ECK 는 클라우드 서비스가 아니다.** 이름의 "Cloud"는 *cloud-native*(K8s 네이티브)를 뜻하며, 둘 다 **우리 클러스터에 설치하는 오퍼레이터**다. 매니지드(RDS·OpenSearch·MSK)로 갈아타지 않는다.
>
> 🔴 **오퍼레이터·컴포넌트 버전 핀 정본 = [런북 §1.1](./mp_k8s_p2_data_runbook.md)**(2026-07-28 확정). 여기에 값을 복사해 두지 않는다 — 이원화되면 어느 쪽이 최신인지 알 수 없다. **차트 기본값을 그대로 쓰면 PG 18·ES 9 가 서는 함정**이 있으니 매니페스트를 손대기 전에 그 표를 볼 것.

### 2.2 네임스페이스 (메시 경계 = ns 경계)

| ns | 담는 것 | 메시 | PSS enforce(실물) |
|---|---|---|---|
| `app` | FastAPI 9 + frontend + **ranking-serving** = **11 워크로드** | **ON** | **restricted** + `istio-injection: enabled` |
| `data` | PG·ES·Kafka·Redis(오퍼레이터 생성) + **PGSync·redis-pgsync** | OFF | **baseline**(warn/audit=restricted) |
| `pipeline` | Kafka 컨슈머 4 + CronJob 11 + **ranking-retrain** | OFF | **baseline**(warn/audit=restricted) |
| `observability` · `argocd` · `*-system` | 관측·CD·오퍼레이터 | OFF | **baseline**(warn/audit=restricted) |

🔴 **data·pipeline 을 baseline 으로 둔 이유** = 오퍼레이터(CNPG·ECK·Strimzi)가 만드는 파드를 restricted 로 막으면
P2 에서 원인 찾기 어려운 실패가 난다. **단 baseline 도 특권 initContainer 는 거부** — ECK 의
`vm.max_map_count` init 이 여기 걸려서 노드 sysctl 선반영으로 우회한다(런북 §9-9).
**PriorityClass 실값**(매니페스트에 이 이름 그대로 — 없는 이름 = 스케줄 거부):
`data-critical` 1000000 · `app-normal` 100000 · `pipeline-low` 1000. 정의 = `roles/k8s_cluster_base`.

*youtube(영상 추출)는 워크로드가 아니다 — `ml/video-recipe/` 는 코드만 존재하고 어느 서비스에도 배선돼 있지 않다(미통합). 통합 시점에 배선·ns 를 결정한다.*

### 2.3 워크로드 네이밍 규칙 (2026-07-28 확정)

**`Service` 는 bare(`account`·`recipe`…), 그 외 오브젝트는 `mp-` 접두사.**

| 대상 | 이름 | 예 |
|---|---|---|
| **Service** `metadata.name` | **bare** (접두사 X) | `account`, `recipe`, `chat` |
| Deployment·ExternalSecret·타깃 Secret·ArgoCD Application `metadata.name` | `mp-<svc>` | `mp-account`, `mp-account-secrets` |
| `app:` 라벨 (Service selector·Prometheus 그룹핑·`OTEL_SERVICE_NAME`) | **bare** (논리 신원) | `app: account` |
| 공유 오브젝트(`app-common` ConfigMap 등) | 서술형 이름 유지 | `app-common` |

- 🔴 **왜 Service 만 bare 인가** — Service 이름이 곧 클러스터 DNS 다. 서비스 간 호출과 frontend nginx 리버스프록시가 **전부 bare 이름**으로 서로를 부른다(`http://account:8004`, `nginx.conf: set $u recipe:8001`). Service 에 `mp-` 를 붙이면 이 계약이 전부 깨진다(NXDOMAIN). 반대로 Deployment/App 이름은 아무도 DNS 로 안 읽으므로 접두사가 무해하다. → mp-mealplan 파드에서 `account`·`pantry`·`ranking-serving` bare DNS 해석 실증(2026-07-28).
- `mp-` 의 목적 = kubectl/ArgoCD 목록에서 앱 워크로드를 한눈에 식별(이미지·Harbor 프로젝트 `mealplanning/mp-*` 와 정합). DNS·라벨 신원과는 분리한다.
- **네임스페이스는 선례가 갈린다** — 티어 ns 는 bare(`app`·`data`·`pipeline`·`observability`·`cost`), 그 뒤에 만든 건 `mp-`(`mp-users` 2026-08-01 · **`mp-ingress` 2026-08-06**). 시스템 ns 는 업스트림 관례(`cnpg-system`·`cert-manager`…)를 따른다(§1.2 주석). → **새 ns 는 `mp-` 를 붙인다**(CLAUDE.md 명명 규칙 "이름을 새로 짓는 전부"). 기존 bare ns 를 리네임하지는 않는다 — 참조를 깨뜨리는 비용이 일관성 이득보다 크다.
- 이미지 레포는 `mp-<svc>-service`(백엔드 8) · `mp-ranking-serving` · `mp-frontend`(‑service 접미사 없음).
- **frontend 는 PSS restricted 대응으로 nginx 를 `listen 8080`(비특권 포트)으로 재빌드**한다 — 포트 80 은 NET_BIND_SERVICE 를 요구하는데 restricted 가 금지한다.

---

## 3. 🔴 구축 시 반드시 지킬 것 (사고 이력 기반)

전부 **실제로 겪은 사고**에서 나온 항목이다. 상세 = [`docker-infra-status.md §7`](./docker-infra-status.md)(⛔ 폐기됐지만 **사고 원문은 거기에만** 보존돼 있다) · [`mp_k8s_infra_migration_plan.md §10`](./mp_k8s_infra_migration_plan.md).

- **Kafka**: `auto.create.topics.enable=false` · `KafkaTopic` CRD 가 토픽 생성의 **유일 경로** · **PV 실사용 검증**
  - 근거: 2026-07-20 브로커 자동생성이 `create_topics.py`를 무력화(1파티션 사고) · 2026-07-21 `KAFKA_LOG_DIRS` 미배선으로 recreate 시 **토픽 전멸**
- **Cilium**: `socketLB.hostNamespaceOnly=true` — 없으면 Istio 사이드카가 가로챌 ClusterIP가 사라져 **mTLS가 조용히 깨진다**
- 🔴 **PSS restricted × Istio 자동생성 파드 = 반복되는 3연타.** `app` ns 에 뭔가 새로 뜨지 않으면 **먼저 PSS 를 의심**한다. 지금까지 셋 다 같은 뿌리(Istio 가 만들어 주는 파드가 restricted 요건을 안 채움)였다:
  ① istio-init(root+NET_ADMIN) → `pilot.cni.enabled=true` 로 istio-validation 전환 ② frontend nginx 80 → 비특권 이미지 8080 ③ **Gateway 파드 seccompProfile 누락 → `gateways.securityContext`**(2026-07-28). ⚠️ ③은 **Service 가 `.14` 를 정상으로 받아서** 겉보기엔 정상이고 파드만 0 개다 — `PROGRAMMED=False` 와 ReplicaSet 이벤트를 봐야 보인다
- **Gateway 업로드 한도**: Envoy 는 본문 크기 제한이 **없다**(nginx 와 "다른" 게 아니라 없음 — 실측). `client_max_body_size` 대체물로 **EnvoyFilter buffer 필터**를 반드시 같이 올린다 — 안 하면 무제한 업로드가 열린다(object_spec §5.6)
- **Redis**: 영속성(AOF/RDB) **끄기** — 2026-07-22 호스트 급사 → AOF 손상 → PGSync 16시간 크래시루프(무알람)
- **PG**: 2 인스턴스에서 **동기 복제 금지** — standby 사망 시 primary 쓰기 정지
- **DB 커넥션**: HPA 를 켜면 파드마다 풀이 생겨 `max_connections`(100)에 부딪힌다 → **CNPG `Pooler`(transaction) 가 HPA 의 전제.** psycopg3 prepared statement 충돌·PGSync LISTEN/NOTIFY 우회 = P2 검증항목 (`mp_k8s_infra_object_spec.md §4.5`)
- **ES**: 노드 `vm.max_map_count=262144` (ECK 기동 전) · **ECK 는 인증 강제** — 앱 3곳(recipe·chat db.py + `pipelines/ingest/_db.py`) basic_auth 필요, PGSync 는 env 2개
- **NetworkPolicy**: default-deny 시 CoreDNS(53)·istiod(15012) egress + kubelet probe ingress 예외 필수 · **pipeline ns → data ns**(PG·Kafka) 허용 잊지 말 것
- **DHCP**: 공유기 할당 범위가 `.14`–`.21`(예약 대역)과 겹치지 않을 것, 시작 주소 `.23` 이상 — **확인은 생략하고 진행함**(§1.1). 산발적 단절 시 1순위 용의자
- **게스트 디스크 이름은 scsi 인덱스 순서와 다르다** — 워커 실측(2026-07-27): `scsi1`(containerd 40G) = **`/dev/sdc`**, `scsi2`(OpenEBS 150G) = **`/dev/sdb`**. Ansible 은 `/dev/sdX` 를 하드코딩하지 말고 **`/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_drive-scsiN`** 를 쓸 것 — 뒤바뀌면 **OpenEBS VG 용 raw 디스크를 containerd 용으로 mkfs** 한다(스토리지 계층이 조용히 사라짐). 호스트 C 의 `docker_data_disk=/dev/sdb` 관례를 그대로 복사하면 밟는 함정
- **호스트 C 인벤토리**: `[ci]` 그룹(= `vms` 자식)으로 관리한다 — base 롤은 VirtualBox 대응 완료(qemu-guest-agent 스킵), `group_vars/ci.yml` 에 `docker_data_disk` **의도적 명시됨**(2026-07-27). 디스크 구성을 바꾸면 그 값을 먼저 갱신할 것. *(구 계획의 "cicd 그룹 분리" 수칙은 이 방식으로 대체됨)*
- **호스트 C 브리지 어댑터** (§1) — NAT 면 이미지 pull 불가
- 🔴 **RWO 단일 replica 워크로드는 `strategy: Recreate`** — 기본 RollingUpdate 는 새 파드를 먼저 띄우는데 로컬 PV 는 두 번 마운트할 수 없다 → 새 파드가 `verifyMount: device already mounted` 로 영원히 ContainerCreating. MinIO 에서 실제로 밟았다(2026-07-27). PGSync 등 같은 성질에 모두 해당
- 🔴 **`nodeName` 직접 지정 금지** — 스케줄러를 건너뛰므로 `WaitForFirstConsumer` PVC 가 영영 Pending 이다(선택 노드 주석이 안 붙는다). 노드 고정은 반드시 `nodeSelector`/affinity 로
- 🔴 **호스트 접근이 필요한 워크로드(node-exporter 류)는 `kube-system` 에** — hostNetwork·hostPID·hostPath·hostPort 는 PSS `baseline` 에서 거부된다. ns 를 privileged 로 낮추지 말고 워크로드를 옮긴다(관측 ns 의 Grafana·MinIO 가드를 지키기 위해)
- ⚠️ **차트 서브차트 토글은 부모 조건 키를 봐야 한다** — kube-prometheus-stack 의 node-exporter 는 `prometheus-node-exporter.enabled` 가 아니라 **`nodeExporter.enabled`** 로 꺼진다(Chart.yaml 의 condition). 별칭에 false 를 줘도 그대로 렌더된다
- ⚠️ **GitHub 릴리스 태그 ≠ 컨테이너 이미지 태그** — MinIO 는 GitHub 최신(2025-10-15)의 이미지가 quay 에 없어 ImagePullBackOff. 이미지 핀은 레지스트리 태그 목록에서 확인할 것
- **단일 파일 bind mount**: 파일을 교체하면 inode가 바뀌어 컨테이너가 고아 inode를 계속 본다 → SIGHUP 리로드가 무력. 재생성 필요 (K8s 에서는 ConfigMap 으로 해소)
- 🔴 **compose→K8s 이행 워크로드의 리소스 limit 은 첫 실전에서만 드러난다**(2026-07-30 실측): `.8` compose 는 무제한이라 실사용량을 아무도 몰랐고, 컬리 폴러(chromium)가 limit 1Gi 에서 즉시 OOMKill(실측 피크 1131Mi → 2Gi). **이행 워크로드는 첫 실행을 반드시 관찰하고, limit 은 피크 실측 기반으로 재조정**한다
- 🔴 **데이터 파드 무리소스(BestEffort) 금지** — PG 가 무리소스로 배포돼 커널 OOM 점수 최악(1000) = 순간 스파이크 시 노드의 첫 희생자였다(2026-07-30 발견·해소). kubelet 축출은 PriorityClass 가 막지만 **커널 OOM 은 QoS/request 만 본다** — memory req=lim(object_spec §13.9)이 데이터 티어 전 컴포넌트 필수
- 🔴 **전용 이미지의 선택 COPY = 빌드 시점 임포트 canary 필수**(2026-07-30 실측): 컬리 이미지가 `pipelines/stream/` 파일을 골라 COPY 하는데, 의존이 늘어난 리팩터링(`_topics` 분리)을 Dockerfile 이 안 따라가 폴러가 런타임에 전멸. 선택 COPY 뒤에 `RUN python -c "import …"` 카나리를 반드시 둔다(#380)
- **대형 ConfigMap(>256KB) 은 ArgoCD ServerSideApply 필수**(2026-07-30 실측): client-side apply 의 last-applied 어노테이션 한도에 걸려 sync 가 죽는다 — `argocd.argoproj.io/sync-options: ServerSideApply=true`(Grafana 대시보드 CM 에서 실발생, config#29)
- 🔴 **ArgoCD 는 기본으로 Endpoints·EndpointSlice 를 안 본다**(2026-07-30 실측): v3 기본 `resource.exclusions` 가 둘을 감시·적용에서 통째로 제외 — 수동 EndpointSlice 를 git 에 둬도 **sync Succeeded 인데 조용히 미적용**(관리 목록에 아예 안 뜸 → 백엔드 503). 클러스터-밖 백엔드는 **Istio ServiceEntry**(+HTTPRoute `backendRefs: {group: networking.istio.io, kind: Hostname}`)로 등록한다 — gateway-internal 호스트 C 3종에서 실발생·전환(config#32)
- ⚠️ **상주 에이전트에 CPU 캡 금지** — `.10` alloy 가 cpus 0.3 캡에서 호스트 부하 시 CFS 스로틀링으로 **프로세스는 살고 HTTP·로그만 죽는 웨지** 2회(2026-07-30). object_spec §13.7 과 같은 계열 — 메모리 캡만 유지
- 🔴 **은퇴시킨 VM 은 tfvars 에 `started = false` 를 박고 `on_boot` 도 거기에 연동한다**(2026-07-31 실측). 손으로 `qm stop` 만 하면 **다음 `terraform apply` 가 선언 상태(켜짐)로 되돌린다** — a2 추가 plan 이 `1 to add, 2 to change` 로 나왔고 그 2건이 `.8`·`.11` 의 `started/on_boot false → true` 였다. 그대로 적용했다면 **구 데이터 티어(PG·Kafka·ES + root 크론 파이프라인)가 K8s 와 이중 가동**된다. `on_boot` 은 미선언 시 프로바이더 기본값 `true` 라 별도로 막아야 한다 — 실제로 `.9` 는 정지 상태인데 `onboot=1` 이었다(07-28부터 장전). **호스트 A 는 무흔적 급사 3회 이력이 있어 "재부팅될 리 없다"는 가정이 성립하지 않는다.**
- 🔴 **`terraform apply` 는 게스트를 재부팅시킬 수 있다 — 유지보수창에서만**(2026-07-19 사고, 구 `docker-infra-status.md §7` 승계). VM 의 `initialization`(cloud-init) 변경은 게스트 재부팅을 유발한다. 그때 재부팅이 **게스트의 커널 업데이트(initramfs 재생성) 도중에 걸려 initrd 가 파손**됐고, GRUB 이 ext4 저널을 재생하지 못해 부팅이 행 걸렸다(호스트에서 `kpartx`+`fsck` 로 복구, 데이터 손실 0). 같은 apply 에서 재부팅된 VM 이 하필 state backend 를 담고 있어 state 저장도 실패했다(당시 PG backend — 지금은 S3 라 그 결합은 없다). **스펙 변경 apply 전에 게스트의 unattended-upgrade 미실행을 확인할 것.**
- 🔴 **`topologySpreadConstraints` 의 zone 단위는 노드 겹침을 못 막는다 — hostname 단위를 함께 걸어라**(2026-07-31 실측). Kafka `combined`(controller+broker) 3노드가 zone 제약(`host-b 2 · host-a 1`)을 **만족한 채** host-b 몫 2개가 **같은 `k8s-worker-b1`** 에 얹혀 있었다. b1 하나가 죽으면 **KRaft 정족수 3중 2를 잃어 Kafka 가 통째로 정지**한다(RF=3 도 그 순간 무의미). zone 은 "물리 호스트 분산", hostname 은 "노드 분산" 으로 **다른 축**이다. ⚠️ 두 제약 모두 대칭이라 *"다수가 B"* 까지는 표현하지 못한다 — 그건 최초 배치로 잡고 문서에 남긴다.
- 🔴 **로컬 PV 에서 워크로드 "재배치" 는 스케줄링이 아니라 볼륨 문제다 — 대가는 "데이터 원본이 어디 있나"가 정한다**(2026-07-31 실측). 로컬 PV 는 파드를 노드에 못 박으므로 옮기려면 **PVC 를 버리고 목적지에서 새로 만들어야** 하고, 그 순간 그 볼륨의 내용은 사라진다. 그래서 이동 후보는 용량이 아니라 **원본이 밖에 있는지**로 고른다 — Loki(청크·인덱스가 MinIO(S3)에 있고 로컬은 `/var/loki` WAL·캐시) = 싸다 / Prometheus(메트릭 이력 전부)·MinIO(Loki·Tempo 블록+모델 아티팩트) = 실데이터 손실. 그리고 **목적지의 VG 여유를 먼저 확인**할 것 — Kafka 재배치가 b2 의 `openebs-vg` 여유 16Gi 에서 막혔다(요구 20Gi).
- 🔴 **알람 규칙은 "시계열이 항상 있다"를 전제하지 말 것 — 조용한 결측 한 번이 `for:` 규칙을 통째로 무력화한다**(2026-07-31 실측). Prometheus 는 스크레이프에서 사라진 시계열에 staleness 마커를 넣어 **즉시** 없는 것으로 만들고, instant 벡터 규칙은 그 순간 알람이 사라져 **`for:` 시계가 0 부터 다시 센다.** kafka-exporter 가 `kafka_consumergroup_lag_sum` 을 한 스크레이프씩 누락하는 탓에, 새 lag 알람의 `for: 15m` 이 **최장 연속 참 구간 14.5분**으로 미달해 **발화 자체가 불가능**한 상태로 들어갈 뻔했다(§5.2). 새 규칙을 넣을 때는 ① 대상 지표의 결측률을 `count_over_time` 으로 먼저 재고 ② 임계를 뒤집어(`>= 0` 등) **과거 구간 재생으로 최장 연속 참 구간이 `for:` 를 넘는지** 확인한다. "지금 발화 안 함"은 정상과 **영영 안 우는 규칙**을 구분해 주지 않는다

---

## 4. IaC

| 구성 | 위치 | K8s 이전 시 변화 |
|---|---|---|
| **Terraform** | [`infra/terraform/`](../infra/terraform) | 유지 — **Proxmox(A·B) 전용.** state = PG 원격 backend(⚠️ **P2 에 S3 백엔드로 이관** — VM PG 가 K8s 로 가면 "state 가 자기가 만든 클러스터 안에" 있는 순환 의존이 된다. 런북 Q4·§2-B). 호스트 B 는 **별개 스탠드얼론이라 provider alias `b`**(`vms_k8s.tf` = K8s 노드 3대). **호스트 C 는 대상 아님**(VirtualBox — 프로바이더 안 씀). ⚠️ 은퇴 VM 203 은 **state 에서 제거해 추적 제외** — tfvars 에 되살리면 `.10` 이 호스트 C 와 충돌 |
| **Ansible** | [`infra/ansible/`](../infra/ansible) | 유지 — **K8s 는 전용 플레이북 `k8s.yml`**(롤 `k8s_node`·`k8s_control_plane`·`k8s_worker_join`·`k8s_cilium`). 🔴 **K8s 노드는 `vms` 그룹에 넣지 않는다** — site.yml 의 base 롤이 `docker_data_disk`(/dev/sdb)를 포맷하고 워커의 sdb 는 OpenEBS raw 디스크다. **호스트 C = `[ci]` 그룹**(base 롤 VirtualBox 대응 완료). 서비스 배포 롤은 ArgoCD 로 이관 |
| **Jenkins** | 레포 루트 `Jenkinsfile` + `roles/jenkins`(compose) | ✅ 가동 — CATALOG 14 이미지·릴리스 태깅. JCasC 코드화는 후속 |
| **매니페스트** | `deploy/k8s/` | ⚠️ **stale** — ECR·placeholder 시절 유물이고 앱 매니페스트는 부재. 재작성 필요 |
| **ArgoCD 선언** | 별도 config 레포 | 신규 (P0) — 이미지 핀은 `:sha` |

### 4.0 클러스터 접속 (`kubectl`)

master 노드에서는 root·`ubuntu` 둘 다 `~/.kube/config` 가 배치돼 있다(`k8s_control_plane` 롤). 로컬 워크스테이션에서 쓰려면:

```bash
# 1) 클라이언트 버전 맞추기 — kubectl 은 apiserver ±1 마이너까지만 지원(스큐)
curl -LO https://dl.k8s.io/release/v1.34.10/bin/linux/amd64/kubectl
curl -LO https://dl.k8s.io/release/v1.34.10/bin/linux/amd64/kubectl.sha256
echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check
install -m 0755 kubectl ~/.local/bin/kubectl        # sudo 불필요

# 2) kubeconfig 를 **머지**한다 (기존 컨텍스트를 덮어쓰지 말 것)
ssh ubuntu@192.168.0.17 'sudo cat /etc/kubernetes/admin.conf' > /tmp/mp-k8s.conf
#    kubeadm 기본 이름(cluster=kubernetes / user=kubernetes-admin)은 흔해서 충돌한다
#    → cluster·user·context 를 mp-k8s / mp-k8s-admin / mp-k8s 로 바꾼 뒤 머지
cp ~/.kube/config ~/.kube/config.bak
KUBECONFIG=~/.kube/config:/tmp/mp-k8s.conf kubectl config view --flatten > /tmp/merged
install -m 0600 /tmp/merged ~/.kube/config
kubectl config use-context mp-k8s
```

**내부 도구 상시 접속 — 이름·HTTPS 로 통일** (2026-07-30, 내부 게이트웨이 `.15` — LAN 전용·LE 인증서):

| 주소 | 대상 | 로그인 |
|---|---|---|
| `https://grafana.mealbong.cloud` | Grafana (구 NodePort 30300 — 회수됨) | admin / `secrets.yml:grafana_admin_password` |
| `https://minio.mealbong.cloud` | MinIO 콘솔 | fbadmin / `secrets.yml:minio_root_password` |
| `https://loki.mealbong.cloud` | Loki API (alloy push 유입구 — 구 31100 회수됨) | 무인증(구 노출 수위 등가) |
| `https://jenkins.mealbong.cloud` | Jenkins UI (호스트 C `.10` 프록시) | 기존 계정 |
| `https://sonarqube.mealbong.cloud` | SonarQube UI (호스트 C 프록시) | 기존 계정 |
| `https://harbor.mealbong.cloud` | Harbor **UI 만** (호스트 C 프록시) | 기존 계정 — 🔴 docker/containerd pull·push 는 계속 `192.168.0.10` 직결 |

DNS = Cloudflare 와일드카드 A(`*.mealbong.cloud`→`192.168.0.15`, DNS-only) — 인터넷 DNS 장애 시 이름이 안 풀리므로 그때는 아래 port-forward 또는 서비스 직결(IP)로. 정본 = config 레포 `gateway-internal/`.

**port-forward (비상용·게이트웨이 우회)** — 전부 ClusterIP(외부 노출은 게이트웨이 전용 규칙 §3.3):

```bash
kubectl -n observability port-forward svc/kube-prometheus-stack-grafana 3000:80
kubectl -n observability port-forward svc/kube-prometheus-stack-prometheus 9090:9090
kubectl -n observability port-forward svc/minio-console 9001:9001
kubectl -n argocd       port-forward svc/argocd-server 8080:443                   # ArgoCD (admin)
#   ArgoCD 초기 비번: kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d
#   🔴 최초 로그인 후 비번 변경 + argocd-initial-admin-secret 삭제
```

⚠️ `admin.conf` 는 **cluster-admin 자격증명**이다(무기한·취소 불가). 팀 공용으로 뿌리지 말 것 — 사람별 계정은 ESO·OIDC 도입 시점에 별도로 판단한다. 임시로 나눠줄 땐 `kubectl create token` 기반 ServiceAccount 토큰을 쓴다.

**클러스터 밖 접속 — 호스트 C·물리 호스트** (2026-07-31 `docker-infra-status.md §4` 승계. 구 VM `.8`·`.9`·`.11` 주소는 전부 소멸):

```bash
ssh ubuntu@192.168.0.10       # 호스트 C (Harbor·Jenkins·SonarQube) — VirtualBox 위 Ubuntu 24.04
ssh root@192.168.0.12         # 물리 호스트 A (Proxmox k8s2) — VM 과 달리 root 접속
https://192.168.0.12:8006     # Proxmox 웹 UI (호스트 A `k8s2`, root@pam)
https://192.168.0.22:8006     # Proxmox 웹 UI (호스트 B `k8s1`, root@pam)
https://192.168.0.10          # Harbor 레지스트리 직결 — docker/containerd pull·push 경로(로컬 CA HTTPS)
```

- 비밀값은 전부 `infra/ansible/secrets.yml`(gitignored) — Harbor admin·SonarQube DB·Proxmox root 등. 문서에 값을 적지 않는다.
- 🔴 **Harbor 는 이름(`harbor.mealbong.cloud`)이 UI 전용**이다. 이미지 pull·push 는 위 `192.168.0.10` 직결을 계속 쓴다(위 표 참조).
- 로컬 CA HTTPS 라 **브라우저에는 `infra/certs/ca.crt` 를 임포트**해야 경고가 안 뜬다(팀원 설치법 = [`ca-setup.md`](./ca-setup.md)). 서버·노드 쪽 신뢰는 Ansible `ca_trust` 롤이 넣는다 → **`insecure-registries` 설정 불필요**.
- SSH 키는 (초기) cloud-init 주입 + (운영) Ansible `team_ssh_keys`. 팀원 추가 = 공개키를 `infra/ansible/roles/team_ssh_keys/files/<이름>.pub` 에 넣고 `ansible-playbook site.yml --tags team_keys` (**additive** — 기존 키 보존).

### 4.2 GitOps config 레포 — **생성·배선 완료 (2026-07-28) · 소유자 배포키 등록만 남음**

**레포 생성됨**: `happyInit/mealplanning-config` (private, 앱 담당자 작성). 실구조는 **app-of-apps** —
`argocd/applications/*.yaml`(child Application — root 가 자동으로 집는 구조) + `services/<svc>/base` +
`overlays/onprem·eks`. *(종전 문서의 `apps/` 디렉토리 가정은 이 실구조로 대체.)* `account.yaml` 정합
확인 완료: `project: mealplanning` · `namespace: app` · **자동 sync = 안전모드 가동**(2026-07-29, config #3 — `selfHeal·prune off` 로 Istio sidecar 드리프트 sync 루프 회피·수동편집 미복구) + **ArgoCD 즉시 웹훅**으로 config push 시 3분 폴링 없이 즉시 refresh→동기화(plan §7.3).

**배선 적용 완료** (2026-07-28, `--tags argocd` · failed=0): 정본 Secret(fb-secrets) → ESO 복제
Ready(SecretSynced) → `argocd` ns repository Secret(라벨 확인) + AppProject `mealplanning` 생성.

| 항목 | 값 |
|---|---|
| 자격증명 경로 | `fb-secrets` ns Secret(정본) → **ESO** → `argocd` ns repository Secret. 🔴 ArgoCD 에 직접 안 박는다 |
| AppProject | `mealplanning` — 배포 허용 ns = **app·data·pipeline** 뿐, 클러스터 스코프 리소스 생성 금지(`clusterResourceWhitelist: []`) · `mealplanning-root` — argocd ns 에 `argoproj.io/Application` 만 · `platform` — **sourceRepos = grafana 차트 1개 · destinations = observability·kube-system · 클러스터 스코프 = ClusterRole·Binding 2종**(정의 = `roles/k8s_argocd` defaults·templates) |
| ⚠️ P2 예정 변경 | 🔴 **platform AppProject 3종 동시 확장**(런북 Q1) — 오퍼레이터·데이터 CR 을 `project=platform` 으로 담으려면 sourceRepos(+차트 4·config 레포) · destinations(+data·오퍼레이터 ns) · 클러스터 스코프(+CRD·웹훅)를 **전부** 넓혀야 한다. 하나만 고치면 child sync 가 그대로 죽는다 |
| 정본 | 배선(Secret·ExternalSecret·AppProject) = **Ansible `roles/k8s_argocd`** / 앱 매니페스트 = **config 레포**(argocd/applications + services) |
| 배포키 | `secrets.yml: argocd_repo_ssh_key`(2026-07-28 생성, ed25519) — ✅ **소유자 등록 완료**(read-only) |
| URL 일치 규칙 | 🔴 repository Secret 의 URL 과 Application `source.repoURL` 은 **문자열까지 일치**해야 한다(ssh/https 혼용 금지) — 현재 둘 다 `git@github.com:happyInit/mealplanning-config.git` ✓ |

✅ **연결 실증 완료 (2026-07-28)** — 소유자가 배포키 등록 후 끝단까지 검증: ① 배포키로 `git ls-remote`
읽기 인증 성공 ② **임시 Application(sync 없음)으로 ArgoCD 실 fetch 실증** — 비교 연산 `OutOfSync`(정상 —
미배포 상태) · revision 이 레포 HEAD 와 일치 · ComparisonError 없음(= `services/account/overlays/onprem`
**kustomize 렌더도 통과**). 실증 후 임시 Application 철거(전례 동일 패턴). **앱 Application 적용(app-of-apps
root)은 P1 에 앱 담당자 런북으로 진행한다** — 배선은 인프라 몫, 배포는 앱 트랙 몫.

**app-of-apps root 지원 (2026-07-28 추가)** — 앱 담당자가 root(`mealplanning-root` Application)를 먼저
적용해 봤더니 `InvalidSpecError` 로 막혀 있었다(실측): root 는 **argocd ns 에 child Application 오브젝트를**
만들어야 하는데 `mealplanning` 프로젝트 허용 ns 는 app·data·pipeline 뿐. mealplanning 에 argocd ns 를
추가하는 안은 화이트리스트가 전역(`*/*`)이라 기각 → **root 전용 AppProject `mealplanning-root` 신설**
(destination = argocd ns 만 · 리소스 = `argoproj.io/Application` 한 종류만). 울타리 검증 완료(임시 root 로
비교 통과 후 철거). 🔴 **root Application 의 `spec.project` 는 `mealplanning-root` 여야 한다** — child 는
지금처럼 `mealplanning`. ✅ **전환 완료(2026-07-28)** — 앱 담당자가 root project 변경, root **Synced/Healthy**
도달(automated sync 로 account 인수). child account = OutOfSync/Missing 은 정상(실배포는 P1 수동 sync).
**app-of-apps 가동 — config 레포 트랙 전체 종결.**

✅ **repository Secret 단일화 완료 (2026-07-28)** — 앱 담당자가 같은 URL 로 수동 시크릿
(`mealplanning-config-repo`)을 만들어 둬 중복이었다(ArgoCD 는 동일 URL 시크릿이 여럿이면 비결정 픽 —
간헐 실패형 장애 예약). **합의 후 수동본 삭제, 정본 = ESO 경유 `repo-food-budget-config` 하나**로 단일화.
삭제 직후 refresh 는 DeadlineExceeded 가 한 번 났고(사용 중 시크릿 제거의 과도기) **hard refresh 로
정상 복귀 — ESO 자격증명의 실사용까지 이때 확증됐다**(그전 성공은 수동본을 탔을 수 있음). 앱 담당자의
GitHub 배포키·레포·Application 은 전부 그대로. **배선은 클러스터에 1회** — 팀원별 반복 작업이 아니다
(팀원에게 필요한 건 레포 write 와 클러스터/ArgoCD 접근뿐).

⚠️ **GitHub 권한 구조 주의** — 개인 계정 레포는 **소유자 1명만 admin**이고 콜라보레이터는 전부 write 로 고정된다
(admin·maintain 롤은 조직 레포 전용). 그래서 **배포키·브랜치 보호·웹훅은 소유자만** 만질 수 있다.
P2 의 Jenkins 자동 태그 커밋에는 **쓰기 가능한** 자격증명이 하나 더 필요한데 그것도 소유자 몫이다.

🔴 **ArgoCD Application 삭제는 캐스케이드가 아니다** — `resources-finalizer.argocd.argoproj.io` 가 없으면
Application 을 지워도 **배포된 리소스는 그대로 남는다**(실측 확인). P1 에서 앱을 걷어낼 때 주의.

### 4.3 ArgoCD 플랫폼 트랙 — LGTM 선배포 (2026-07-28 가동)

P4 항목이던 "LGTM in-cluster 이전" 중 **스택 세우기만 앞당겼다** (리스크 검사 후 확정 — 근거는
[플랜 §9](./mp_k8s_infra_migration_plan.md): P1 브리지가 메트릭만 커버해 K8s 앱 로그가 P1~P3 동안
`kubectl logs` 뿐이던 공백 해소 + 워커 예산표 §2.2 가 이미 Loki 1G·Tempo 2G 를 포함 + 3노드가 전부
호스트 B 안이라 물리 1GbE 를 안 탄다). ~~컷오버는 P4 유지 — 예비 스택~~ → ✅ **컷오버 완료(2026-07-30,
§0 "모니터링 컷오버" 행)** — 알림규칙·Slack·대시보드·클러스터-밖 로그 수신(`.15` 게이트웨이 경유 — 과도기 31100 회수)까지
**인클러스터가 프로덕션 관측 정본**. `.11` 철거만 남음(아래 ⑤ 의 "무알람" 제약도 해소 — 이 스택 자체가 알림 주체).

| 항목 | 값 |
|---|---|
| 구성 | **Loki**(SingleBinary·PVC 10Gi·retention 168h) · **Tempo**(모놀리식·PVC 10Gi·168h) — observability ns / **Alloy**(DaemonSet 3노드, 파드 로그 테일 → Loki) — **kube-system**(hostPath 필수 → node-exporter 수칙) |
| 백엔드 | MinIO 버킷 `loki`·`tempo`(P0 생성분). **자격증명은 Secret `lgtm-minio-creds` + `-config.expand-env=true`** — values 평문 금지 |
| 관리 | **ArgoCD Application ×3** (project=**platform**, automated+selfHeal+prune, finalizer 포함) · 소스 = **공개 Helm 차트 레포 직접**(자격증명·config 레포 불요) · values = Application 인라인 |
| 정본 | AppProject `platform`·`platform-root` + **platform-root Application** = **`roles/k8s_argocd`**(존치) / **child Application 3 = config 레포 `platform/argocd/`**(2026-07-29 이사) / Secret·데이터소스 CM = `roles/k8s_platform_apps`(은퇴 대기 — 부속 2개만 남음). 순서 고정 = git 추가 → **root 인수 확인** → **같은 날** 롤 은퇴 |
| Grafana | kps Grafana sidecar 가 `grafana_datasource` 라벨 CM(`lgtm-grafana-datasources`)을 자동 로드 — Loki `:3100`·Tempo `:3200`. kps values 무변경 |
| 검증(2026-07-28) | 3 Application Synced/Healthy · 플랫폼 ns 8종 로그 유입 · **강제 flush → MinIO 청크 실증** · Tempo 폴러 무에러 · master +136Mi(limits 256Mi 내) · 재실행 `changed=0` |
| 🔴 사고 → **worker-b1 데이터 오염 발견**(2026-07-29, 상세 = [§1.0.3](#103-worker-b1-읽기-데이터-오염-2026-07-29)) | 증상 = **Alloy 가 b1 에서만 크래시루프**(2026-07-28 07:35 KST~, 재시작 204회) → 그동안 **b1 파드 로그가 Loki 에 미유입**. ⚠️ **Application 이 `Progressing` 이라 Healthy 검사·알람 어디에도 안 걸렸다** — 위 "검증"의 Synced/Healthy 가 통과한 이유이자 **관측 스택 자체의 사각지대**. 원인은 메모리 한도가 아니라 **b1 의 데이터 오염**이었다(추적 경위 = §1.0.3). 조치 = 손상 스냅샷 7개 purge + 재다운로드 → **alloy 4노드 전부 2/2 Running·재시작 0 복구**. 한도 512Mi 상향은 무관하지만 유지(DaemonSet 한도는 가장 바쁜 노드 기준이 맞다) |

**차트 함정 (실측 — 값 바꿀 때 재확인)**: ① Loki 기본 모드 = SimpleScalable + chunks-cache(memcached 8Gi)
— SingleBinary 로 갈 때 **read/write/backend replicas 를 명시적으로 0** 으로 꺼야 한다(validate.yaml 이
deploymentMode 무관하게 검사 → ComparisonError 로 실측). ② Tempo `_ports.tpl` 이
`receivers.jaeger.*` 를 직접 참조 — **jaeger 수신자를 제거하면 렌더가 죽는다**(기본값 유지).
③ Loki 는 `persistence.storageClass`, Tempo 는 `persistence.storageClassName`(키가 다름).
④ ~~트레이스 유입 배선은 소비자가 생기는 P1 에서~~ → ✅ **배선 완료(2026-07-30, #393)** — `meshConfig.extensionProviders`(`mp-tempo-otlp`→`tempo:4317`) + Telemetry `mp-mesh-tracing`(istio-system·**샘플링 100%** — 트래픽 규모상 저장 무시 가능, 커지면 숫자만 낮춤). 정본 = **`roles/k8s_istio` 한 집**(행선지·지시서는 반쪽만으론 무의미한 한 쌍 — 레포 안 찢음). istiod 재시작 불요(동적 반영), 앱 경유 스팬 실증. **보류하던 tempo 규칙 2종은 첫 블록 flush 후 config 레포 rules.yaml 로 편입**.
⑤ in-cluster Alertmanager 수신자 없음 + `.11` 은 파드 CIDR 을 못 봄 → **이 스택이 죽어도 무알람**
(예비 스택이라 수용 — ServiceMonitor 는 켜 둬서 in-cluster Prometheus 로 수동 확인 가능).

### 4.1 IaC 경계 — 호스트 C · 하이퍼바이저

> **2026-07-31 승계** — 폐기된 `docker-infra-status.md` 에서 **살아 있는 부분만**(호스트 C `.10` · 하이퍼바이저 `.12`) 여기로 옮겼다. 그 문서는 이제 이력 참고용이고 여기가 정본이다.

**Terraform = Proxmox(A·B) 전용 / Ansible = 호스트 C 포함 전체.**

호스트 C 는 VirtualBox 라 Terraform 밖이지만 **Ansible `[ci]` 그룹으로 관리한다**(가동 중 — Harbor·Jenkins·SonarQube 전부 롤로 배포됨). 레지스트리는 클러스터 복구의 전제(이미지가 없으면 아무것도 못 뜬다)라 손구성 금지.

- **실체** = VirtualBox 위 **Ubuntu 24.04**(클러스터 미참여). 구 `fb-ci-harbor` VM 의 `.10` IP·인증서를 승계했고 그 VM 은 2026-07-28 파괴됐다. 인벤토리 상 호스트명은 여전히 `fb-ci-harbor`(**기존 실물 이름 — 리네임 별건**)
- 🔴 **VirtualBox 어댑터 = 브리지 모드 고정**(§1) — NAT 면 `.10` 을 LAN 에서 못 받아 클러스터 배포가 전면 실패한다
- **docker 전용 디스크 = `/dev/sdb`** — `group_vars/ci.yml` 에 **의도적으로 명시**돼 있다(`all.yml` 암묵 상속에 안 맡김). 🔴 **호스트 C 디스크 구성을 바꾸면 그 값을 먼저 갱신할 것** — base 롤이 이 값을 포맷·마운트 대상으로 쓴다
- **`[ci]` 는 `[vms]` 의 자식**이라 site.yml 의 전-호스트 플레이 5개가 그대로 닿는다. `vms` 그룹의 실구성원은 이제 호스트 C 하나뿐이지만 **그룹은 유지**한다(호스트 C 전용 플레이와 전-VM 플레이의 구분을 잃지 않기 위해 — 인벤토리 주석)

**적용 롤** (site.yml — `hosts: vms` 플레이 5개 + `hosts: ci` 플레이)

| 롤 | 무엇 | 단독 실행 |
|---|---|---|
| `base` | Docker Engine + compose 플러그인 · `/var/lib/docker` = 전용 디스크 · `ubuntu` docker 그룹. **VirtualBox 대응 완료**(qemu-guest-agent 는 `ansible_virtualization_type` 으로 스킵) | — |
| `team_ssh_keys` | 팀원 공개키 additive 배포 | `--tags team_keys` |
| `ca_trust` | 로컬 CA 신뢰(시스템 + docker) → **`insecure-registries` 불필요** | — |
| `monitoring_agents` | node-exporter(`:9100`)·cAdvisor(`:8080`)·Alloy(`:12345`). 2026-07-27 스킵 철회 — 호스트 C 는 클러스터 **밖**이라 인클러스터 관측이 영원히 못 보고, Harbor 는 무감시면 안 되는 SPOF | `--tags monitoring_agents` |
| `ioburst_watch` | 디스크 읽기 폭주 워처(**임시 진단**, `ioburst_enabled`) — 원래 4-VM 상주분이라 지금은 호스트 C 에만 남았다 | `--tags ioburst` |
| `harbor` | Harbor v2.15.2 (`:80` + **`:443` 로컬 CA HTTPS**, data `/data`, 인증서 `/opt/harbor-certs`) | `--tags harbor` |
| `jenkins` | Jenkins LTS-jdk17 — UI `:8081`(**컨테이너 8080 매핑** · 호스트 8080 은 cAdvisor 점유) · JNLP `:50000` · 홈 = named volume `jenkins_jenkins_home` · **호스트 docker.sock 마운트**로 빌드·push | `--tags jenkins` |
| `sonarqube` | SonarQube community + 전용 PG15 — `:9000`. Jenkins 가 분석 전송(**측정만·비차단**) | `--tags sonarqube` |
| `cloudflared` | Cloudflare Tunnel `mp-ci` — `ci.mealbong.cloud` 의 **`/github-webhook/` 경로만** → `localhost:8081`. 포트포워딩 0 · Jenkins UI 는 인터넷 미노출(UI 는 LAN 전용 `jenkins.mealbong.cloud`) | `--tags cloudflared` |
| `harbor_backup` | Harbor DB·암호화키(`/data/secret`)·설정·인증서 → **`s3://mp-harbor-backup-ap2`**, 매일 **02:20 KST** systemd timer. 이미지 blob 은 제외(CI 재빌드 가능) | `--tags harbor_backup` |
| `jenkins_backup` | `JENKINS_HOME`(secrets·credentials·jobs·plugins·users) → **`s3://mp-jenkins-backup-ap2`**, 매일 **02:40 KST**. workspace·caches 등 재생성 가능분 제외 | `--tags jenkins_backup` |

- ~~`github_runner`~~ — 은퇴(Jenkins 대체, 2026-07-27 플레이에서 제거. 롤 디렉터리만 롤백 대비 보존)
- **호스트 C 재구축 = 수동 VM 생성 + Ansible** — 이 한 스텝만 IaC 밖이다
- **호스트 publish 포트**: `80`·`443`(Harbor) · `8080`(cAdvisor) · `8081`·`50000`(Jenkins) · `9000`(SonarQube) · `9100`(node-exporter, host-net) · `12345`(Alloy). **새 컨테이너로 호스트 포트를 열 때 이 목록을 먼저 볼 것**
- **감시**: 인클러스터 Prometheus 가 `additionalScrapeConfigs` 로 직접 긁는다 — job `vm-node`·`vm-cadvisor`·`vm-alloy`(instance `fb-ci-harbor`). Alloy 로그는 `https://loki.mealbong.cloud` 로 송신(§0 모니터링 컷오버 ④)
- 🔴 **Harbor 재부팅 자동기동 함정 (해소 — PR #270)**: 호스트 재부팅 시 Docker 가 `restart: always` 를 **동시** 기동해 `harbor-log`(syslog 수신) 이 리스닝하기 전에 나머지가 뜨며 **생성 단계에서 8개가 Exited(128)**. compose `depends_on` 은 부팅 자동재시작 경로에 적용되지 않는다 → **`harbor.service`**(Type=oneshot · `docker.service` 이후 `compose up -d` · RemainAfterExit)로 순서를 보장한다. 실피해는 "재부팅 때마다 CI 의 Harbor 로그인 스텝 실패"였다
- **취약점 게이트**: 이미지 빌드 직후·push **전**에 `aquasec/trivy:0.72.0`(핀) 스캔 — **CRITICAL(fixable) 이면 파이프라인 실패**(취약 이미지 Harbor 반입 차단). HIGH 는 비차단. 컨테이너로 실행하고 DB 는 `trivy-cache` 볼륨 → **Harbor RAM 부담 0**. Harbor 자체의 scan-on-push 통합은 RAM 이유로 미채택. 정본 = 레포 루트 `Jenkinsfile`
- **백업 대상 전체**: etcd 스냅샷 · PG(barman-cloud PITR) · ES 스냅샷 · **Harbor**(위) · **`JENKINS_HOME`**(위) · Secret 암호화 사본 → 전부 S3

#### 하이퍼바이저 (`.12` 호스트 A) — Terraform 밖 · `hypervisor.yml` 전용

물리 Proxmox 자체는 **Terraform 대상이 아니다**(Terraform 은 그 위의 VM 만 만든다). Ansible 로는 **`hypervisor.yml` 하나만** 닿고(인벤토리 `[hypervisor]` = `fb-proxmox` `.12` **단독**), 얹는 것은 감시 에이전트(`node_exporter_host` 롤)뿐이다. 접속 계정은 VM 과 달리 **root**(`group_vars/hypervisor.yml`, `become: false`).

```bash
ansible-playbook hypervisor.yml   # .12 전용 — node-exporter(네이티브 apt, :9100). 접속은 root
ansible-playbook site.yml         # 호스트 C 전용 (.12 는 안 닿음)
```

**호스트 A(`.12`) 물리 구성** *(구 문서 §1 승계 — 수치는 2026-07-23 실측이라 VM 3대 파괴 후 여유는 더 늘었다)*

- Proxmox VE **9.1.1** · 노드명 `k8s2` · **standalone**(클러스터 미구성) · 웹 `https://192.168.0.12:8006`
- 시스템 디스크 `sdb`(WD Blue 1TB SSD) → VG `pve` = root 96G(xfs) + swap 8G + **thin `local-lvm` 643G**. 스토리지 = `local`(dir) · `local-lvm`(thin) — **ZFS 아님(XFS)**
- 클론 템플릿 = **`9002` `ubuntu-2404-template-agent`**(cloud-init + **qemu-guest-agent 사전설치** — Terraform 이 쓰는 정본. 없으면 `apply` 가 agent IP 리포팅을 기다려 최대 30분 행) · `9001` 은 롤백용 원본
- 브리지 = `vmbr0`(물리 업링크·관리망 `192.168.0.0/24`) + **`vmbr1`**(host-only `10.10.10.0/24`, host=`.1` — Terraform `proxmox_network_linux_bridge.internal`). ⚠️ **`vmbr1` 은 구 4-VM 전용이었고 그 VM 들은 파괴됐다. K8s 노드는 NIC 1장(vmbr0)만 쓴다** — 호스트 B 에는 `vmbr1` 자체가 없다

🔴 **site.yml 플레이는 `hosts: all` 이 아니라 `hosts: vms` 다.** `all` 은 Ansible 이 인벤토리의 모든 호스트를 자동 포함하는 암묵 그룹이라 `[all:children]` 에서 빼는 것으로는 하이퍼바이저를 못 막는다. 막지 않으면 `base` 롤이 `.12` 에 Docker 를 깔고, 더 나쁘게는 `docker_data_disk: /dev/sdb` 를 전용 디스크로 잡는데 **`.12` 의 `/dev/sdb` 는 전 VM 스토리지가 올라간 `pve` VG 디스크**다. **3중으로 막아뒀다** — ① `hosts: vms` ② `base` 롤 선두의 `assert`(hypervisor 그룹이면 실패) ③ `group_vars/hypervisor.yml` 의 `docker_data_disk` 무효값 덮어쓰기. **새 전-호스트 플레이를 추가할 때 `all` 로 쓰지 말 것.**

**온도 감시** (2026-07-22 신설 — 무흔적 급사 3회 후속, §1 배치 원칙의 근거):

- 스크레이프 = 인클러스터 Prometheus job **`hypervisor`**(instance `fb-proxmox`, `additionalScrapeConfigs`). 알람 규칙은 config 레포 `monitoring/rules-physical.yaml` 이 정본 — 2026-07-30 모니터링 컷오버 ③ 으로 `.11` 에서 이식됐다
- 지표 = `node_hwmon_temp_celsius`. 센서 해독 — `chip=platform_coretemp_0`: `temp1`=Package, `temp2`~`temp9`=Core 0~7 / `chip=0000:00:01_0_…`: nouveau GPU(GTX 1060)
- 임계는 하드코딩하지 않고 **센서가 스스로 보고하는 한계치**에 맞춘다(`_max_` = CPU 80·GPU 95 / `_crit_` = CPU 100·GPU 105) → **`MpHypervisorTempHigh`·`MpHypervisorTempCritical`·`MpHypervisorTempCritAlarm`**. 호스트는 살아 있고 exporter 만 죽은 경우는 **`MpHypervisorExporterDown`**. *(2026-07-31 config 레포 `monitoring/rules-physical.yaml` 대조 확인 — 이식하면서 **`Mp` 접두사가 붙었다.** 구 `.11` 시절의 무접두사 이름으로 검색하면 안 나온다. 같은 파일에 호스트 C·VM 용 `MpHostCDown`·`MpVMDiskUsageHigh`·`MpVMDockerDiskUsageHigh`·`MpVMContainerMemoryNearLimit` 도 있다.)*
- 실측 추이(구 `.11` TSDB 기준·**원본은 소멸**, §5.3): 유휴 평균 61~67°C, 이상부하 시 평균 78.4·최대 88°C → `_crit_` 100 에는 미달이라 **발열로 급사를 설명하기는 여전히 어렵다**. 원인 미확정 상태 유지
- ⚠️ **호스트 A(`.12`) 급사는 이제 실시간으로 잡힌다** — Prometheus 가 호스트 B 고정이라 A 와 함께 죽지 않는다(구 구조는 Prometheus 가 `.12` 위 VM 이라 구조적으로 불가능했다). 🔴 **단 호스트 B(`.22`) 자신은 사각지대다** — B 에는 node-exporter 도, B 를 보는 외부 관측도 없다(스크레이프 대상 = `.12`·`.10` 뿐)
- (참고) `.12` 의 `/dev/sda` 250GB(구 Windows·NTFS)는 **SMART 수명 96% 소진**(2026-07-22 실측) — `pve` VG 에 없어 VM 과 무관하지만 **어떤 용도로도 신규 편입하지 말 것**. ⚠️ 호스트 B 에도 같은 계열의 250GB `sda`(NTFS·미사용)가 **따로** 있다 — [§1.0.3](#103-worker-b1-읽기-데이터-오염-2026-07-29) 의 디스크 표는 B 것이다(혼동 주의)

---

## 5. 이전 절차 (2026-07-27 재편 — 앱 먼저)

**"상태없는 것부터"로 재편됐다** — 앱 좌표가 전부 env 라 VM 데이터 티어를 그대로 보게 할 수 있어, 데이터-먼저 안의 근거였던 "브릿지 비용"이 소멸했기 때문. 단계별 상세·롤백·체크리스트 = [`mp_k8s_infra_migration_plan.md §10`](./mp_k8s_infra_migration_plan.md).

| 단계 | 내용 | 상태 |
|---|---|---|
| 선행 | ~~호스트 B·C 확보 · CI Jenkins 전환 · Harbor 이전~~ | ✅ **완료** |
| P0 | 호스트 B 3노드 · 기반(Cilium·Istio·MetalLB·OpenEBS·MinIO·cert-manager·ESO·ArgoCD·kube-prometheus-stack·metrics-server) · **라우팅 모드 iperf3 측정·락** · ~~백업·복구 경로 검증~~(→P2 직전) | ✅ **완료(2026-07-28)** — LGTM 선배포(§4.3)·config 레포 연결·app-of-apps 가동(§4.2)까지. **S3 백업·복구 왕복은 P2 직전으로 이동**(2026-07-28 결정) |
| P1 | **앱 이전** — Gateway(`.14`)+HTTPRoute+앱 11(env=VM 데이터 좌표) → 유입 전환(nginx→GW) · in-cluster Prometheus agent→`.11` remote_write · `.9` 정지(`.env` 백업 완료)→보존 · 구 `.10` VM 파괴 · worker-a1 생성 = 4노드 | ✅ **완료(2026-07-28)** — §0 표 해당 행들 |
| P2 | 선행 ①②(S3 왕복·램 교체+memtest) ✅ 2026-07-29 종결 · 리허설 1회 완주 ✅ · **데이터 티어 + 파이프라인 전환창** — 구축·따라잡기·프로모트+파이프라인 동시 전환+앱 좌표 갱신 | ✅ **완료(2026-07-30 새벽)** — 열화 ~25분·**유실 0**(41테이블 일치)·roll-forward·`.8` 정지. 실행 기록·함정 = [런북](./mp_k8s_p2_data_runbook.md) |
| P3 | **스케일** — Pooler 검증 → 앱 풀 축소 → account HPA → KEDA lag 스케일링 | ✅ **완료(2026-07-30 밤)** — 순서대로 완주·전 단계 실측. 상세 = [§5.1](#51-p3-스케일-실행-기록-2026-07-30) |
| P4 | 정리 — ~~LGTM 컷오버(알림규칙·Slack·대시보드·agent 재지향)~~ ✅ **2026-07-30 조기 완료**("철거 예정 인프라에 과도기 투자 안 함" 결정 — §0 "모니터링 컷오버" 행) · **남은 것 = `.8`·`.9`·`.11` VM 해체**(현재 정지·보존) · worker-a1 14GB 확장 + worker-a2 = **5노드 완성** · ansible `monitoring`·`data_tier`·`data_pipeline` 롤 은퇴 정리 | ⬜ **VM 해체·5노드만 잔여** |

### 5.1 P3 스케일 실행 기록 (2026-07-30)

**순서가 곧 설계다** — Pooler → 풀 축소 → HPA → KEDA. 어기면 "HPA 를 켰는데 오히려 느려진다"(커넥션 고갈 대기).

| 단계 | 한 일 | 실측 |
|---|---|---|
| ① Pooler 전환 | 앱 기본 좌표 `pg-rw` → **`pg-pooler`**(transaction). `price` 1/9 카나리 후 전체 | 부하 450건·동시 25 → **951 req/s · p50 7ms · p95 21ms** · 5xx 0 |
| ② 풀 축소 | 9개 서비스 `max_size` → **5**(하드코딩 4개는 env 화) + **`prepare_threshold=None`** | 동일 쿼리 8회(임계 5) 후 prepared **0개** |
| ③ account HPA | **ContainerResource**(cpu, container=account) 70% · min 2 · max 4 | 부하 → **10초 만에 2→4**, 종료 후 300s 안정화 뒤 2 복귀 |
| ④ KEDA | 차트 2.20.1 · ScaledObject 4종(Kafka lag) → **min 0** 3종 | **0→1 깨어남 10초** · scale-to-zero 도달 · 콜드스타트 14초 |

**🔴 이 프로젝트의 핵심 가설이 숫자로 증명됐다** — account 가 **4 replica** 로 늘어난 순간의 PG 커넥션:
**Pooler 경유 12개 / `max_connections` 100**. Pooler 없이 HPA 를 켰다면 [object_spec §4.5](./mp_k8s_infra_object_spec.md) 의 계산대로 커넥션이 곱해져 벽에 부딪혔을 것이다.

**🔴 Pooler 예외 3종**(각 overlay 의 `pg-direct.yaml` 에 해제 조건 명시):
- **ocr** — 세션 `SET statement_timeout`·`read_only` 가드가 transaction 풀링에서 **조용히 무효화**된다(에러가 아니라 가드 소실이라 더 위험)
- **ranking-serving** — `psycopg.connect` 직접 호출이라 prepare_threshold 기본값(5) 그대로
- 파이프라인·PGSync — 애초에 `app-common` 을 안 읽는다(각자 좌표). PGSync 는 LISTEN/NOTIFY 라 세션 필수
  둘 다 HPA 대상이 아니라(§9.3) 다중화 이득이 0 — **위험만 있고 얻을 게 없는 이전**이라 제외했다.

**🔴 KEDA min 0 의 전제 = 커밋된 오프셋** — 커밋이 없는 그룹은 KEDA 가 lag 를 **0 으로 보고**해 파드가 0 으로 내려간 뒤 **영영 안 깨어난다**(메시지는 쌓이는데 아무도 안 먹는 조용한 실패). 그래서 `recipe-refiner` 만 **min 1 유지**했었다 — 이 컨슈머는 레시피를 PG 에 적재하고 PGSync 가 ES 로 복제해 **사용자 검색에 노출**되므로 오프셋 확보용 합성 메시지를 넣을 수 없다. → ✅ **2026-08-02 05:00 KST 만개레시피 크론이 실제로 커밋해 min 0 전환 완료([§5.8](#58-만개레시피-크롤-첫-실행-관찰--리소스-lag-keda-2026-08-02))**. 이로써 컨슈머 4종 전부 scale-to-zero.
✅ **그 어긋남은 2026-08-02 해소·판정 완료** — `keda_scaler_metrics_value{scaledObject="mp-recipe-refiner"}` 가 **10시간 내내 정확히 3**(= 파티션 수)이던 현상은 **오프셋 무효 시 파티션당 1 을 반환하는 폴백**(`scaleToZeroOnInvalidOffset` 기본 false)이 맞았다. 크롤로 실 오프셋이 커밋되자 **같은 지표가 3 → 0** 으로 바뀌었다(크롤 구간 최대 7 = 실 lag). 위험의 방향도 예상대로 **"안 깨어난다"가 아니라 "안 내려간다"** 였다 — 커밋 전에 min 0 을 걸었으면 지표가 3 에 붙잡혀 **파드가 영영 0 으로 안 내려갔을 것**이다. 상세 = [§5.8](#58-만개레시피-크롤-첫-실행-관찰--리소스-lag-keda-2026-08-02).
✅ **lag 알람 = 2026-07-31 해소(§5.2)**.

**실행 중 드러난 함정**:
- **ArgoCD 가 HPA·KEDA 와 `replicas` 를 두고 다툰다** — 매니페스트에 `replicas` 가 있으면 sync 마다 오토스케일러 결정을 되돌린다. account Deployment·컨슈머 4종에서 **필드를 제거**했다(없으면 apply 가 live 값을 안 건드린다).
- **KEDA 는 `APIService` 를 만든다** — platform AppProject 의 `clusterResourceWhitelist` 에 없어 추가했다. 없으면 외부 메트릭 API 등록이 막혀 **lag 를 영영 못 읽는다**(파드는 뜨는데 스케일만 안 되는 조용한 실패). 차트를 미리 `helm template --include-crds` 로 렌더해 클러스터 스코프 5종을 세어 잡았다.
- **`pollingInterval`·`cooldownPeriod` 는 min 0 에서만 유효** — KEDA 가 min 1 시절 "not relevant" 경고로 알려준다.
- **`grep -E` 로 코드 스캔하지 말 것** — `execute("SET` 의 괄호가 정규식 메타문자로 해석돼 **거짓 음성**이 났다(처음에 "비호환 코드 0건"으로 오판). 고정문자열(`grep -F`)로 재스캔해 ocr 의 세션 SET 을 발견했다.

### 5.2 P3 잔여부채 ① 해소 — KEDA scale-to-zero lag 알람 (2026-07-31)

컨슈머 3종이 `minReplicaCount: 0` 이 되면서 **"메시지는 쌓이는데 컨슈머가 0"** 이 조용히 발생할 수 있게 됐다(alloy 웨지 29h · PGSync 크래시루프 16h 와 같은 계열). 정본 = config 레포 `pipelines/monitoring.yaml`(PR #58·#60).

**들어가 보니 "알람 부재"가 아니라 알람에 구멍이 있었다** — 기존 `MpKafkaConsumerLagGrowing` 의 조건이 `lag > 100 **and** deriv(lag[10m:]) > 0` 였다. `deriv > 0` 은 "아직 늘고 있을 때만" 참인데 우리 프로듀서는 전부 CronJob 폴러라 **버스트 후 평평**하다 → 크론이 밀어넣고 끝나면 **백로그가 남은 채 알람이 스스로 해제된다.** 잡으려던 국면이 정확히 그것이라 규칙을 대체했다.

| 규칙 | for | 잡는 것 |
|---|---|---|
| `MpConsumerIdleWithBacklog` | 10m | lag>0 인데 replica 0 — scale-to-zero 고유의 조용한 실패 |
| `MpConsumerBacklogStuck` | 15m | lag>100 지속(구 Growing 대체) — 웨지·크래시루프 컨슈머까지 커버 |
| `MpKedaScalerErrors` | 15m | 스케일러가 트리거를 못 읽어 결정이 마지막 값에 고착 — 선행 신호 |
| `MpConsumerLagUnobserved` | 1h | lag 시계열 자체가 소멸(오프셋 만료·익스포터 이상) = 감시자가 눈먼 상태 |

전부 `severity: warning`(#monitoring). 설계 원칙 3가지:
- 🔴 **감시 지표는 KEDA 가 아니라 kafka-exporter 를 본다** — 고장난 당사자의 자기 신고에 기대면 KEDA 가 멈춘 국면을 못 잡는다. KEDA 지표는 `MpKedaScalerErrors` 에만 쓴다.
- `keda-operator`·`metrics-apiserver` 다운은 스택 기본 `TargetDown` 이 이미 커버 → 중복 규칙을 두지 않았다.
- `recipe-refiner` 는 `MpConsumerLagUnobserved` 에서 **의도적 제외**(커밋 오프셋이 없어 시계열 자체가 없다) — 넣으면 첫날부터 상시 발화한다. min 0 전환 때 함께 편입.

**🔴 발견 — kafka-exporter 가 `lag_sum` 시계열을 조용히 누락한다 (기전 미규명)**

규칙 검증 중 `kafka_consumergroup_lag_sum` 이 한 스크레이프씩 사라지는 것을 발견했다. 좁힌 근거:

- 익스포터를 직접 반복 스크레이프해 **원문 바이트를 대조** → 결측 응답은 정상 응답과 **763줄이 완전히 동일**하고 `kafka_consumergroup_lag_sum{consumergroup="retail-refiner",…}` **한 줄만** 없다. 같은 응답 안에 그 값의 **재료인 파티션별 `kafka_consumergroup_lag` 3개**와, 소스상 lag_sum **바로 앞 줄에서 조건 없이 방출되는 `current_offset_sum`** 은 멀쩡히 있다.
- `scrape_samples_scraped` 가 결측 시 651 / 정상 652 로 **딱 1개 적다.** Prometheus 중복샘플 카운터 0, 익스포터 로그 오류 0줄 → **Prometheus 가 아니라 익스포터가 안 낸 것.**
- 바이너리는 업스트림 **kafka_exporter v1.9.0 정품**(리비전 `8ec2407…` = v1.9.0 태그 SHA 일치, Strimzi 패치본 아님). 소스 `kafka_exporter.go` 683~688 상 두 지표는 조건 없이 연달아 방출되므로 **코드만 봐선 불가능한 조합** — 기전은 규명하지 못했다. 업스트림에 동일 보고 없음.

**조치 = 결함 시계열에 대한 의존 제거** — `lag_sum`(익스포터가 합산) → **`sum(kafka_consumergroup_lag)`**(파티션별을 우리가 합산).

| 24시간 실측 | 30초 초과 공백 | 최대 공백 |
|---|---|---|
| `lag_sum` | retail **387회** · user-event 23회 · price-anomaly 27회 | 180초 |
| `sum(kafka_consumergroup_lag)` | **전 그룹 0회** | 30초(= 스크레이프 간격) |

두 값은 동시 존재 구간에서 **완전히 일치**한다(3시간 최대 절대오차 0). `max_over_time` 은 `[2m]` 로 **이중 방어로만** 남겼다 — 새 지표는 감싸지 않아도 공백이 없지만, 이 익스포터가 시계열을 조용히 떨어뜨린다는 게 실증된 이상 `for` 시계 리셋은 계속 막아둔다.
⚠️ **다른 대시보드·쿼리가 `lag_sum` 을 쓰면 같은 함정에 빠진다.**

**실행 중 드러난 함정**:
- 🔴 **"지금 발화 안 함"은 검증이 아니다** — 임계를 뒤집어(`>= 0`) 과거 3시간을 재생해 보니 구 식은 **최장 연속 참 구간 14.5분**으로 `for: 15m` 에 미달, 즉 **retail-refiner 에 대해 한 번도 발화할 수 없는 규칙**이었다(신 식 = 361/361점·180.5분). 일반 수칙으로 §3 에 편입.
- **`pipelines` ArgoCD 앱은 auto-sync 가 꺼져 있다**(데이터·파이프라인 계열 공통) — config 레포 머지만으로는 반영되지 않는다. `Application` 의 `operation` 필드에 일회성 sync 를 걸어 반영했고(prune·selfHeal 불변), PrometheusRule 갱신 후 **Prometheus 규칙 재로드까지 약 50초**가 더 걸린다(operator → ConfigMap → reloader).

**남은 것**: 임계 100/15m 조정 → ⏸ **2026-08-08(수) 크롤로 이월**. 일요일 실적은 나왔으나(recipe 피크 **5**, retail 피크 608·`>100` 지속 **2.0분**) **같은 날 `recipe-refiner` 를 min 1→0 으로 바꿔 그 측정이 대표성을 잃었다** — 상세·근거 = [§5.8](#58-만개레시피-크롤-첫-실행-관찰--리소스-lag-keda-2026-08-02).

### 5.3 P4 실행 기록 (2026-07-31 · 진행 중)

**되돌릴 수 있는 것부터** 순서를 잡았다: `.11` 정지 → a2 생성 → Kafka 재배치 → (미완) a1 확장 → (미완) VM 파괴.
디스크가 제약이 아니어서(호스트 A local-lvm 556GB 여유) **최후 보험인 정지 VM 디스크를 마지막까지 들고 간다.**

| 단계 | 한 일 | 실측 |
|---|---|---|
| ① `.11` 정지 | graceful shutdown · 디스크 100G+40G 보존 · `onboot 0` | 스크레이프 타깃 0 확인 후 정지 → 클러스터 56/56 UP 무영향 · 호스트 A RAM 6GB 회수 |
| ② a2 생성·조인 | vmid 305 · `.21` · 6코어 11264MB · 50/40/150GB (b1/b2 동일 스펙) | **5노드 Ready** · zone=host-a · OpenEBS VG 150G · CiliumNode 5 · join `ok=46 changed=23 failed=0` |
| ③ Kafka 재배치 | `combined-2` 를 b1 → **b2** (PVC 재생성) + hostname spread 제약 추가 | 브로커 3대가 서로 다른 노드(host-b 2 · host-a 1) · under-replicated **0** · 정족수 정상 |
| ④ a1 램 12→14GB | ⏸ **보류 결정** — 실익이 약하다 | a1 은 이미 워커 중 최대(allocatable 10,736Mi · 요청 71% · 실사용 67%)이고 압박은 b1 77% · b2 80% 에 있어 a1 확장으로는 안 풀린다. 계획의 14GB 는 a2 도 14GB 이던 시절 숫자다 |
| ⑤ `.8`·`.9`·`.11` 파괴 | ✅ **완료** — Terraform 선언에서 걷어내(`vms = {}`) apply 로 파괴 | plan `0 add / 0 change / 3 destroy` · 잔존 LV 없음 · 씬풀 19.69%→**7.19%**(여유 516→596GiB) |
| ⑥ ansible 롤 은퇴 | ✅ **완료** — 롤 4종 + 플레이 2개 + 빈 그룹 2개 삭제 | 삭제 = `monitoring`·`data_tier`·`data_pipeline`·**`tfstate_db`**(540KB·32파일) · `vms` = 호스트 C 단독 · `--check failed=0` |

**🔴 ①에서 잡은 것 — apply 했으면 은퇴 VM 이 되살아났다.** a2 만 추가한 plan 이 `1 to add, 2 to change` 로 나왔고 그 2건이 `.8`·`.11` 의 `started/on_boot false → true` 였다. §3 수칙으로 편입했다.

**🔴 ③이 드러낸 두 겹의 문제**:
1. **정족수 SPOF** — zone spread 는 만족한 채 `combined-0`·`combined-2` 가 둘 다 b1 에 있었다. b1 상실 = 3중 2 상실 = Kafka 정지. → hostname `maxSkew: 1` 추가(config#62).
2. **볼륨 편중** — 옮기려던 b2 의 `openebs-vg` 여유가 **16Gi**(요구 20Gi)라 막혔다. b2 134Gi/150Gi 사용(prometheus 30 · minio 50 · kubecost 32 · es 10 · loki 10 · alertmanager 2)인 반면 b1 80Gi · a2 150Gi 가 놀고 있었다. **zone B = {b1, b2}** 이므로 배치 원칙을 깨지 않고 분산할 수 있어, **Loki 를 zone→hostname(b1)으로 좁혀** 10Gi 를 회수했다(청크·인덱스는 MinIO 에 있어 이동 비용이 가장 싼 워크로드). 두 문제 모두 §3 수칙으로 편입.

**위험 변화**(③ 전후):

| 사건 | 이전(0·2 가 b1) | 지금 |
|---|---|---|
| 노드 1대 상실 | 🔴 정족수 붕괴 → Kafka 정지 | ✅ 생존 |
| 호스트 A 상실(급사 3회 이력) | ✅ 생존 | ✅ 생존 |
| 호스트 B 상실 | 🔴 붕괴 | 🔴 붕괴 (물리 2대 구성의 한계) |

**절차상 발견**: cordon 이 걸린 노드가 있으면 **오퍼레이터의 롤링 재시작이 그 노드에서 막힌다** — 제약 반영으로 Strimzi 가 브로커를 롤링할 때 `combined-1` 이 a1 cordon 때문에 `FailedScheduling` 이 났다(uncordon 직후 자동 해소). cordon 전에 그 노드에 오퍼레이터 관리 워크로드가 있는지 볼 것.

**⚠️ ⑤ 로 잃은 것 — 알고 내린 결정**: `.11` 디스크의 Prometheus TSDB 에 있던 **2026-07-16~07-28 메트릭**(보존 15d)이 **사본 없이 소멸**했다. 인클러스터 Prometheus 는 **07-28 09:59 부터**라 그 구간(호스트 급사 3회·온도 추이·PGSync 크래시루프 원본)은 복구할 수 없다. 남아 있는 것 = `.8` 최종 PG 덤프(`s3://mp-backup-ap2/pg-final/2026-07-30/`, SHA256 검증) · `.9` 의 `.env`(`/home/team6/backups/dot-env-20260728/`).

**🔴 회수된 것은 디스크뿐이다** — 정지된 VM 은 이미 RAM 을 반납했으므로 파괴로 돌아오는 RAM 은 0 이다. 그리고 씬 프로비저닝이라 **선언 390G 이 아니라 실사용 약 80GiB** 가 회수된다. "VM 을 지우면 그만큼 자원이 생긴다" 는 직관은 여기서 성립하지 않는다.

**🔴 ⑥ 이 정정한 것 — 은퇴 대상 목록 자체가 틀려 있었다.** 종전 기록은 `monitoring`·`data_tier`·`data_pipeline`·**`k8s_platform_apps`** 4종이었는데, 실측 결과 **둘 다 틀렸다**:

- **`k8s_platform_apps` 는 살아 있다 — 지우면 안 된다.** LGTM Application 3종(loki·tempo·alloy)은 `platform-root` 로 넘어갔지만, 이 롤이 배포하는 `lgtm-minio-creds`·`minio` 시크릿은 **ArgoCD 미관리**(추적ID 없음)라 이 롤이 **유일한 공급원**이다. 은퇴시키려면 ESO/config 로 먼저 이관해야 한다(별건·미착수).
- **`tfstate_db` 가 빠져 있었다 — 이쪽이 죽은 롤이다.** 근거 = state backend 가 **S3 로 이관됐다**(`infra/terraform/backend.tf`, 2026-07-29 — "인프라를 만드는 도구의 상태가 그 인프라 안에 있는" 순환 의존을 끊으려고). PG `terraform_state` DB 는 P2 런북 §4.1-⑤ 에서 DROP 됐고, 나머지 역할(앱 `foodbudget` DB·postgres-exporter)도 CNPG 로 넘어갔다.

**삭제 전 검증한 것**(`roles/monitoring` 이 유일한 실질 리스크였다 — 대시보드·알람 정의가 여기 있었다):

| 자산 | 승계 확인 |
|---|---|
| Grafana 대시보드 13종 | 파일명 **완전 일치**로 config 레포 `monitoring/dashboards/` 에 존재 · 인클러스터 CM `app/mp-grafana-dashboards`(13키) 라이브 |
| `alert-rules.yml` 알람 20종 | **20/20 대응 확인 · 순손실 0.** `Mp` 접두사 그대로 13종 · `VMDown`→`MpHostCDown` · `DiskUsageHigh`→`MpVMDiskUsageHigh` · `DockerDiskUsageHigh`→`MpVMDockerDiskUsageHigh` · `ContainerMemoryNearLimit`→`MpContainerMemoryNearLimit`+`MpVM~` · `DataPollerStale`+`DataPollerLastRunFailed`→`MpPollerStale`+`KubeJobFailed`/`KubeJobNotCompleted` · `KafkaConsumerLagGrowing`→`MpConsumerBacklogStuck`/`IdleWithBacklog`/`LagUnobserved` · `PrometheusTargetDown`→`TargetDown`·`Watchdog` = kps 빌트인 |
| Slack 웹훅(`slack_webhook_url`) | `fb-secrets` ns Secret `alertmanager-slack` → ESO 로 observability 투사 |
| 교차 참조 | 죽는 롤 4종을 다른 롤이 template/copy 로 참조하는 곳 **0건** · `groups['vms']` 사용처는 `roles/monitoring/templates/prometheus.yml.j2` 뿐이라 롤과 함께 소멸 |

**`monitoring_agents` 는 존치**다(혼동 주의 — 이름이 비슷하다). 호스트 C 는 클러스터 밖이라 인클러스터 모니터링이 영원히 못 보고, alloy 는 이미 `https://loki.mealbong.cloud`(내부 GW `.15`)로 쏘고 있어 `.11` 의존이 없다.

**남은 부채**: ~~b2 여유 6Gi~~ → **해소(2026-07-31)**. 원인이던 `cost/kubecost-local-store` 32Gi 를 포함해 kubecost 4개 컴포넌트를 a2 로 옮겼다 — b2 여유 **38Gi** 회복. ~~남은 P4 잔여 = `docker-infra-status.md` 폐기(호스트 C 부분 승계)~~ → **완료(2026-07-31)** — SUPERSEDED 배너 + 호스트 C·하이퍼바이저 승계(§4.0·§4.1) + 참조처 정리. 남은 P4 잔여 = `k8s_platform_apps` 의 MinIO 자격증명 ESO 이관(그 뒤에야 이 롤도 은퇴 가능).

**🔴 ⑥ 이 부수로 드러낸 기존 결함 — `site.yml` 풀런은 지금 이 워크스테이션에서 완주 못 한다.** 롤 삭제와 무관하게 원래 그랬고, 검증차 `--check` 를 돌리다 걸렸다:

| 증상 | 실체 |
|---|---|
| `'sonarqube_db_password' is undefined` | 🔴 **레포 결함** — `roles/sonarqube` 가 요구하는데 `secrets.yml.example` 에 **키 자체가 없었다**. 추가했다(2026-07-31). 실사용 값은 호스트 C `/opt/sonarqube/docker-compose.yml`(0640) 안에만 있다 — 새 값을 넣으면 가동 중 SonarQube 가 깨진다 |
| `cloudflared_tunnel_credentials is not defined` | 로컬 `secrets.yml` 공백(`.example` 에는 있음) |
| `backup_s3_access_key is not defined` | 로컬 `secrets.yml` 공백(`.example` 에는 있음) |
| `ioburst_watch` 가 `--check` 에서 실패 | **check-mode 아티팩트**(유닛 파일이 실제로 안 써져 `systemctl enable` 이 못 찾음). 실런은 정상. 단 이걸로 **호스트 C 에 워처가 배포된 적 없다**는 사실이 확인됐다 — 이 롤은 "임시 진단" 도구이므로 철수 여부를 별도 판단할 것 |

→ 위 4건을 제외한 `--check` 는 **`failed=0`**. 3건 제외 조합별 결과는 커밋 메시지에 남겼다.

---

### 5.4 공개 게이트웨이 HA — 외부 유입 SPOF 해소 (2026-08-01)

**문제**: 백엔드 11종에는 spread 가 걸려 있는데 **정작 입구가 무방비**였다. `mp-gw-public-istio` = `replica 1` · `k8s-worker-b2` 단독 · TSC·affinity·PDB 전무 → **b2 상실 = 외부 유입 전면 차단**.

**🔴 Deployment 를 직접 고치면 안 된다.** `mp-gw-public-istio` 는 `Gateway/mp-gw-public` 이 소유하고 istiod(`istio.io-gateway-controller`)가 관리한다 — 손으로 `replicas` 를 박으면 재조정에 되돌려진다. istiod 가 인정하는 유일한 경로가 **`Gateway.spec.infrastructure.parametersRef` → 같은 ns 의 ConfigMap**(허용 키 5개: `service`·`deployment`·`serviceAccount`·`horizontalPodAutoscaler`·`podDisruptionBudget`, 값은 렌더 결과 위의 **오버레이**).

| 한 일 | 실측 |
|---|---|
| ConfigMap `mp-gw-public-params` — `deployment` 오버레이 = `replicas 2` + TSC | `deploy .spec.replicas` = **2** · 파드 스펙에 TSC 반영 |
| TSC = **soft 2계층**(`ScheduleAnyway`·`maxSkew 1`) — ① `kubernetes.io/hostname` ② `topology.kubernetes.io/zone` | 파드 2개가 **다른 노드 + 다른 물리 호스트**(`k8s-worker-a2`=host-a · `k8s-worker-b2`=host-b) · EndpointSlice 2개 전부 `ready=true`. **①만 있을 때는 둘 다 host-a 로 몰렸다** — 아래 참조 |
| PDB `mp-gw-public-pdb`(`minAvailable 1`) — **직접 매니페스트** | `ALLOWED DISRUPTIONS = 1` · `pdb -n mp-ingress`(당시 `-n app` — §5.10 이전) 에 게이트웨이 PDB **1개만**(istiod 중복 생성 없음) |
| 유입 무영향 확인 | `Gateway` **PROGRAMMED=True · ADDRESS=192.168.0.14 유지** · `curl` **12/12 = 200** · 파드 restarts **0** |
| 쿼터 영향 | `3080m/4032Mi` → **`3090m/4128Mi`**(+10m·+96Mi) = **6Gi 의 67%** |

**🔴 `parametersRef` 가 먹었다는 증거 = managedFields 소유권 이동.** 반영 전 `istio.io/gateway-controller` 는 `f:replicas` 를 **소유하지 않았고**(기본값 소유자 = kube-controller-manager), 반영 후 **`replicas`·`topologySpreadConstraints` 를 둘 다 Apply 로 소유**한다. 즉 우리가 얹은 게 아니라 **istiod 가 그렇게 렌더**한 것 — 재조정에 되돌려지지 않는다.

**🔴 PDB 는 `parametersRef` 키를 일부러 안 썼다.** `podDisruptionBudget` 키를 넣으면 istiod 가 PDB 를 **또** 만들어 같은 파드에 2개가 걸린다(소유자 이원화). 직접 매니페스트 1개만 둔다 — 대신 셀렉터를 Deployment 이름이 아니라 **Gateway API 표준 라벨** `gateway.networking.k8s.io/gateway-name: mp-gw-public` 에 맞춰야 한다(그 Deployment 는 istiod 파생물이라 이름 규칙이 우리 소유가 아니다).

**TSC 는 최종적으로 hard 다** — soft 로 시작했다가 **soft 로는 지켜지지 않음이 실측돼** 승격했다(아래 §5.5).

**위험 변화**:

| 사건 | 이전(b2 단독) | 1차(hostname TSC · a1+a2) | **지금(2계층 TSC · a2+b2)** |
|---|---|---|---|
| 노드 1대 상실 | 🔴 외부 유입 전면 차단 | ✅ 생존 | ✅ 생존 |
| 노드 drain(자발적) | 🔴 무방비 | ✅ PDB 가 동시 축출 차단 | ✅ PDB 가 동시 축출 차단 |
| **호스트 A 상실**(급사 3회 이력) | ✅ 생존(b2 에 있었으므로) | 🔴 **양쪽 다 상실** | ✅ 생존 |
| 호스트 B 상실 | 🔴 전면 차단 | ✅ 생존 | ✅ 생존 |

**🔴 교훈 — 노드를 가르는 것과 호스트를 가르는 것은 다르다.** 1차 반영은 `kubernetes.io/hostname` TSC 만 걸었고, 그 결과 파드가 **a1·a2** 에 떴다. 노드는 갈라졌지만 **둘 다 물리 호스트 A** 다. 하필 **급사 3회가 전부 호스트 A**(§1.0.2·배치 원칙)라, 노드 단위 SPOF 를 없애는 대신 **호스트 단위 SPOF 를 새로 만든 꼴**이었다 — 이전(b2 단독)은 호스트 A 급사에 오히려 생존했으므로, **실제로 일어난 적 있는 고장 모드에 대해선 일시적으로 나빠졌다.**

→ `topology.kubernetes.io/zone`(`host-a`/`host-b`, 전 노드에 이미 존재) TSC 를 한 겹 더 얹어 해소. **재실측 = `k8s-worker-a2`(host-a) + `k8s-worker-b2`(host-b)** · `PROGRAMMED=True`·`.14` 유지 · `curl` **12/12 = 200** · 쿼터 `3090m/4128Mi` 불변.

⚠️ **이 패턴은 게이트웨이만의 문제가 아니다.** 워커 4대 중 2대씩이 같은 물리 호스트에 묶여 있으므로, "노드 분산 = 고가용" 이라고 적어 둔 다른 워크로드도 **zone 기준으로 다시 봐야** 한다.

→ 실제로 다시 봤고, 게이트웨이 밖에서도 깨져 있었다. 그 후속이 §5.5.

---

### 5.5 다중 replica 분산을 "보장"으로 승격 — hard + Honor + matchLabelKeys (2026-08-01)

§5.4 의 "다른 워크로드도 zone 기준으로 다시 봐야 한다" 를 실행한 결과. **네임스페이스 전수 감사**에서 두 건이 걸렸다.

| 워크로드 | 배치 | zone TSC |
|---|---|---|
| `mp-recipe` (2, HPA min2/max4 + PDB) | a1 + a2 = **전부 host-a** | 있었음(soft) |
| `mp-frontend` (2, PDB) | b1 + b2 = **전부 host-b** | 있었음(soft) |
| `mp-account` (2, HPA + PDB) | b2 + a2 ✅ | 있었음(soft) |

**제약이 있는데도 깨져 있었다.** 즉 문제는 "제약을 안 걸어서" 가 아니었다.

#### 세 번의 반복 — 매번 검증이 뒤집었다

| PR | 조치 | 검증 결과 |
|---|---|---|
| config #85 | replica 2 + hostname TSC + PDB | 🔴 a1+a2 = 전부 host-a (§5.4) |
| config #86 | + zone TSC(soft) | ⚠️ a2+b2 로 갈라졌으나 **보장 아님** |
| config #87 | **hard(DoNotSchedule) + nodeTaintsPolicy: Honor** | 🔴 frontend·게이트웨이가 **다시 a1+a2** |
| config #88 | **+ matchLabelKeys: [pod-template-hash]** | ✅ 4/4 분산 · 롤아웃 2회 반복에도 유지 |

#### 🔴 왜 hard 만으론 부족했나 (핵심)

TSC 는 스케줄 시점에 `labelSelector` 에 걸리는 **모든** 파드를 센다 — 롤링 업데이트 중엔 **아직 안 죽은 구 ReplicaSet 파드**가 거기 낀다.

```
구 파드가 host-b 에 1개 존재
  → 신규① host-a 배치   (host-a 1 / host-b 1, skew 1 → 통과)
  → 신규② host-a 배치   (host-a 2 / host-b 1, skew 1 → 통과!)
  → 구 파드 종료        → host-a 2 / host-b 0
```

**매 순간 제약은 지켜졌는데 최종 상태가 몰린다.** hard/soft 의 문제가 아니다. `matchLabelKeys: [pod-template-hash]` 는 들어오는 파드의 pod-template-hash 를 `labelSelector` 에 AND 해 **같은 RS 파드만** 세게 한다 → 구 파드가 빠지고 신규①=0/0, 신규②=1/0 이 되어 반대 zone 이 강제된다. K8s 1.34 에서 `MatchLabelKeysInPodTopologySpread` 기본 활성(beta).

#### 🔴 nodeTaintsPolicy: Honor 는 hard 의 필수 동반자

기본값 `Ignore` 면 host-a 가 통째로 죽어도 host-a 가 **"파드 0개 도메인"** 으로 계산에 남는다 → 죽은 파드를 host-b 로 옮기면 skew 2 라 거부 → **Pending**. *막으려던 바로 그 장애에서 복구가 막힌다.*
`Honor` 는 급사·cordon 노드에 붙는 `NoSchedule` 테인트(파드가 톨러레이션 미보유)를 보고 그 노드를 도메인 계산에서 제외한다. ⚠️ 파드 기본 not-ready/unreachable 톨러레이션은 `effect: NoExecute` **전용**이라 `NoSchedule` 변종에 안 걸린다 → 제외가 실제로 성립한다.

#### 🪤 topologyKey 중복 금지 — 조용히 망가지는 함정

처음엔 기존 `tier: backend` 제약 위에 `app: <svc>` 제약을 **덧붙였다.** 그런데 `topologySpreadConstraints` 의 strategic-merge patchMergeKey 가 **`topologyKey`** 다. 같은 축 항목이 둘이면 병합이 깨진다 — `kubectl apply --dry-run=server` 에서 병합 결과의 **`maxSkew` 가 소실**됐다(`doesn't match $setElementOrder list`).

**API 검증은 `(topologyKey, whenUnsatisfiable)` 쌍만 보므로 통과한다.** 즉 apply 경로에서만 조용히 망가진다. 실제로 `mp-account` 는 라이브에 hostname 항목이 둘(tier soft + app soft)이던 탓에 이 사고가 나서 **hostname 제약을 통째로 잃었다**(zone 하나만 남음). 복구 = ArgoCD `ServerSideApply=true` 로 재sync.
→ **워크로드당 topologyKey 는 유일하게 유지한다.** 그래서 덧붙이지 않고 교체했다.

#### selector 변경 — `tier: backend` → `app: <svc>`

기존 `tier: backend` 는 **의도된 설계**였다(2026-07-31). 11종 중 10종이 replica 1 이라 자기 파드만 세는 제약은 셀 게 하나뿐이라 아무 일도 안 하므로, tier 로 묶어 **네임스페이스 blast radius 를 줄이는** 것이 목적이었다. 그 주석은 *"이건 HA 가 아니다 — 진짜 HA 는 replicas>=2 + PDB 이며 별건"* 이라고 스스로 적어 뒀다.

recipe·account 가 그 "별건" 에 해당하게 됐으므로(HPA + PDB) app 단위로 교체했다. **replica 1 인 10종은 tier 제약을 그대로 유지** — 그쪽 전제는 여전히 유효하고, 그 제약들의 selector 가 `tier: backend` 라 recipe·account 파드도 계속 카운트에 잡힌다.

#### 검증 결과 (전부 실측)

| 항목 | 결과 |
|---|---|
| 렌더 + `kubectl apply --dry-run=server` | 4종 configured · 경고 **0** |
| 배치 | **4/4 zone 1:1** (gw·recipe·frontend·account) |
| **롤아웃 내구성 ×2회** | 4/4 유지 · Pending **0** |
| **롤아웃 중 트래픽** | **3,294 / 3,294 = 200**(실패 0) |
| Gateway | `PROGRAMMED=True` · `.14` 유지 |
| PDB 4종 | 전부 ALLOWED ≥ 1 |
| 쿼터 | 3400m / 4352Mi (6core/6Gi 의 **71%**) |
| ArgoCD 4종 | Synced / Healthy |
| `drain --dry-run=server` a2 | `node drained` · PDB 차단 **0** |
| 전 네임스페이스 감사 | app·data·kube-system 전부 양 호스트 |

#### 🔴 남은 구멍 — HPA scale-down 은 zone 을 안 본다 (실증됨)

**TSC 는 스케줄만 관여한다. 축소 대상 선정은 ReplicaSet 컨트롤러 몫이고, 그건 zone 을 보지 않는다.**

```
recipe 3 replica:  b1(host-b) · b2(host-b) · a2(host-a)
HPA 3 → 2 축소 후: b1(host-b) · b2(host-b)      ← host-a 것이 삭제됨
```

노드당 파드 수가 동률(1/1/1)이라 컨트롤러의 spread 랭킹이 갈라주지 못하고, 기동시각·재시작수 같은 기준으로 결정된다. **즉 scale-up → scale-down 을 한 번 돌면 분산이 깨질 수 있다.** (복구 = 롤아웃 1회. matchLabelKeys 덕에 그 뒤엔 결정적으로 갈라진다.)

- **노출 범위**: HPA 가 붙은 `mp-recipe`·`mp-account` 만. 나머지는 고정 replica 라 해당 없음.
- **창(window)**: 축소 시점 ~ 다음 배포. config 레포에 `mealplanning-ci` 이미지 핀 커밋이 잦아 실무상 짧지만 **상한은 없다.**
- ✅ **해소 — descheduler CronJob 도입(2026-08-01, 30분 주기). [§5.6](#56-descheduler-cronjob--hpa-축소로-깨진-분산의-자동-복구-2026-08-01)**

#### 그 밖에 남은 것

- ✅ **drain 실검증 완료(2026-08-02)** — `kubectl drain k8s-worker-a2 --ignore-daemonsets --delete-emptydir-data` 실행. 아래 §5.7.
- **용량은 TSC 로 못 푸는 별개 리스크** — host-a 상실 시 전부 b1·b2 두 노드로 몰리는데 **b1 메모리 요청률이 이미 84%** 다.
- `es-es-b`(StatefulSet 단위 host-b 2개)는 **정상** — ES 클러스터 전체는 `es-es-a-0`(host-a) + `es-es-b-0/1`(host-b) 로 양 호스트에 걸쳐 있고 quorum 다수가 B 인 것은 배치 원칙대로다.

---

### 5.6 descheduler CronJob — HPA 축소로 깨진 분산의 자동 복구 (2026-08-01)

§5.5 가 남긴 구멍(**TSC 는 스케줄 시점만 관여 → HPA scale-down 이 zone 분산을 깬다**)의 해소. 정본 = config 레포 `platform/argocd/descheduler.yaml`.

#### 동작 — descheduler 는 파드를 만들지 않는다

```
descheduler(위반 감지 → 최소 파드 축출)
  → ReplicaSet(대체 파드 생성)
  → 스케줄러(같은 RS 파드가 반대 zone 에 남아 있으므로 hard TSC + matchLabelKeys 가 배치 강제)
```
**축출만 하고, 올바른 자리로 보내는 건 §5.5 의 TSC 다.** 둘은 한 세트라 한쪽만 두면 성립하지 않는다.

⚠️ 이벤트 기반이 아니라 **주기적 리컨사일러**다(Deployment 모드도 내부 타이머 폴링이라 동일하다 — CronJob 이라서 생기는 지연이 아니다). 위반 발생 ~ 다음 실행 사이 **최대 30분 창**은 설계상 수용한 것이다: 위반이 드물고(HPA 축소 뒤에만), 복구가 멱등이며, 노출은 HPA 붙은 2종(`mp-recipe`·`mp-account`)뿐이다.

#### CronJob 을 고른 이유 (Deployment 아님)

| | CronJob | Deployment |
|---|---|---|
| 탐지 방식 | 주기 폴링 | **주기 폴링(동일)** |
| 조용한 실패 감지 | Job 단위 이벤트 → 알람 용이 | 파드는 Running·내부만 에러면 **Healthy 로 보임** |
| policy 변경 반영 | 매 실행이 새 파드 → 자동 | 재시작 필요(바인드마운트 함정) |
| 유휴 자원 | 0 | 상시 ~50–100Mi |
| Prometheus 메트릭 | ❌ 파드 단명으로 스크레이프 유실 | ✅ 연속 수집 |

메트릭을 잃는 대가로 **조용한 실패 감지**를 얻는 교환이다. 이 프로젝트 함정 목록이 전부 그 계열이라 그렇게 골랐다. 축출 관측은 Loki 로그로 한다.

#### 범위를 좁힌 설정

🔴 **차트 기본값은 8개 플러그인을 전부 켠다**(`LowNodeUtilization`·`RemoveDuplicates` 등). 우리가 요청한 적 없는 재배치까지 하므로 프로파일을 **통째로 대체**해 딱 하나만 남겼다.

| 설정 | 값 | 근거 |
|---|---|---|
| 활성 플러그인 | `RemovePodsViolatingTopologySpreadConstraint` 하나 | |
| `constraints` | `DoNotSchedule` 만 | soft 까지 넣으면 replica 1 서비스 10종의 tier 단위 soft 제약이 대상이 되어 무의미한 축출이 계속 난다 |
| `namespaces.include` | `[app]` | data·pipeline·kube-system 대상 밖 |
| `PodsWithoutPDB` 보호 | 켬 | **최종 안전선** — PDB 가진 4종 밖으로 손이 못 간다 |
| `nodeFit` / `minReplicas` / `minPodAge` | `true` / `2` / `5m` | Pending 루프 방지 · 단일 replica 보호 · 롤아웃과 안 싸움 |
| `maxNoOfPodsToEvictTotal` | `2` | 폭주 상한 |
| PDB(`minAvailable: 1`) | (Eviction API) | 두 replica 동시 축출 **불가** |

버전 = 공식 호환 매트릭스가 **1:1**(descheduler `v0.34` ↔ k8s `v1.34`) → `0.34.0` 고정. 우리 K8s 는 1.34.10 apt hold 이고 그 상한은 Cilium 이 정한 것이라 안 움직인다.

#### 🪤 배포 중 밟은 함정 2개 — 둘 다 "조용히" 계열

**① `PodsWithLocalStorage` 보호를 켜면 descheduler 가 완전한 no-op 이 된다.**
처음엔 *"기본 보호를 다 켜두는 게 안전하다"* 고 판단해 `defaultDisabled` 를 비웠다. 그랬더니 위반을 만들어 돌려도 `evictedPods=0`. `--v=5` 로 원인이 나왔다 — **app ns 파드 20개 전부**가 이 사유로 필터링됐다:
```
"Pod fails the following checks" checks="pod has local storage and is protected against eviction"
```
원인 = **Istio 사이드카가 주입하는 emptyDir**(`workload-socket`·`credential-socket`·`workload-certs`·`istio-envoy`·`istio-data`). 즉 **메시에 들어간 모든 파드가 자동으로 "로컬스토리지 보유"** 가 된다.
🔴 무서운 건 **Job 은 `Complete`, `evictedPods=0`, Application 은 `Healthy`** 라는 점이다. 위반을 일부러 만들어 확인하지 않았으면 영원히 못 봤다.
안전성은 실측으로 확인했다 — 대상 4종의 emptyDir 은 **전부 Istio 주입분**이고 앱 자체 emptyDir 은 **0 개**다(소켓·인증서·envoy 런타임 = 재기동 시 재생성).

**② `minPodAge` 는 축출만 막는 게 아니라 skew 계산에서도 파드를 지운다.**
플러그인은 도메인별 파드 수를 셀 때 **축출 가능한 파드만** 센다(`topologyspreadconstraint.go` 의 *"for each evictable pod"* 루프). 실증 = recipe 2개가 둘 다 host-a 인데 그중 하나가 생성 3분차라 host-a 가 **1** 로 세어져 `skew 1` → *"already balanced"* 로 스킵. **6분차 재실행에서 정상 축출.**
⇒ 신규 파드가 낀 위반은 **최대 5분 늦게** 감지된다. 30분 주기에서 실질 영향은 "이번 런이 아니라 다음 런에 고쳐진다" 수준이라 수용한다. 값을 줄이면 롤아웃과 싸울 위험이 커진다.

#### 검증 (실측)

| 단계 | 결과 |
|---|---|
| 렌더 | `helm template` → 정책이 우리 프로파일 하나로 대체됨(기본 8종 소거) |
| dry-run | `kubectl apply --dry-run=server` 5개 오브젝트 통과 |
| 🪤 렌더가 잡은 것 | `limits.cpu 500m` 이 차트 기본에서 살아남음(Helm 맵 병합) → `cpu: null` 로 제거 |
| **no-op 경로** | 위반 없는 상태에서 Job `Complete` · `evictedPods=0` |
| **의도적 위반 생성** | `pod-deletion-cost` 로 소수 zone 파드를 지정 삭제 → recipe 2개가 전부 host-a |
| **복구 실증** | `"Evicted pod" cr5tf node=k8s-worker-a1` → 대체 파드가 **`k8s-worker-b2`(host-b)** 에 배치 → `a2(host-a) + b2(host-b)` |

#### 알람 — 원인·결과 한 쌍

`monitoring/rules.yaml` 의 `mp-descheduler` 그룹(신설):
- `MpDeschedulerNotRunning` — 90분(30분 스케줄 **3회**) 무성공 또는 suspend
- `MpDeschedulerAbsent` — CronJob 오브젝트 소멸(`absent()`)

🔴 **이 둘이 잡는 건 "안 도는" 경우뿐이다.** "돌긴 도는데 아무것도 안 하는" 경우(위 함정 ①)는 못 잡는다 — 그건 기존 **`MpDeploymentPodsOnSingleZone`**(결과 기반, 20분 창)이 잡는다. 두 알람은 대체재가 아니라 **원인·결과 한 쌍**이라 한쪽만 두면 안 된다.
검증 = PromQL 4종 실측(정상임계 0건 / **임계 뒤집기 1건** / absent 0건 / **absent 뒤집기 1건**) + 규칙 `health=ok`·`inactive`. *"0 발화"를 정상으로 오독하지 않도록 식이 값을 낸다는 것까지 확인했다.*

#### 🔴 IaC 밖 — AppProject `platform`

descheduler 차트 레포를 쓰려면 `AppProject/platform` 의 `sourceRepos` 화이트리스트에 추가해야 하는데, 당시 판단은 **"그 AppProject 는 git 에 없다"** 였고 그래서 `kubectl patch` 로 한 줄 추가했다.
- kubecost 는 같은 벽에 부딪히자 `project: default`(전권)로 우회했다 — 가드레일을 포기하는 방식이라 따라가지 않았다.

> ✅ **해소됨 — 다만 사실관계가 반쯤 틀렸었다**(2026-08-06 확인).
> `platform` AppProject 는 **그때도 IaC 안에 있었다**(`k8s_argocd/templates/argocd-platform-project.yaml.j2`, 2026-07-28 신설). 즉 위의 `kubectl patch` 는 **다음 playbook 이 되돌릴 드리프트**였다 — 실제로 2026-08-03 에 `argocd_platform_source_repos` 에 descheduler 줄을 넣어 정리했고, 그 주석에 *"AppProject 를 라이브에서 patch 하면 다음 playbook 이 되돌린다. sourceRepos·destinations 추가는 반드시 git 부터"* 라고 교훈이 남았다.
> 진짜로 git 에 없던 건 **`mealplanning`(앱 트랙) AppProject** 였고, 그건 [§5.10](#510-공개-진입점-ns-분리--app--mp-ingress-2026-08-06-532-)에서 IaC 편입했다.
> 🔴 **교훈은 "AppProject 를 손으로 고치지 말 것"으로 남는다** — 두 프로젝트 다 이제 Ansible 이 `kubectl diff` → `apply` 로 관리한다.

---

### 5.7 drain 실검증 — §5.5·§5.6 이 실제 노드 정비를 견디는가 (2026-08-02)

§5.5(hard TSC)·§5.6(descheduler)을 넣을 때 **계산상으로만 확인**하고 남겨뒀던 것. `k8s-worker-a2` 를 실제로 drain 해서 확인했다.

#### ✅ 통과한 것

| 확인 | 결과 |
|---|---|
| PDB 순차 축출 | 4종(gw-public·recipe·frontend·account)이 **한 번에 하나씩** 빠지고 drain 이 멈추지 않음 → `node/k8s-worker-a2 drained` |
| 재스케줄 | 4종 전부 `k8s-worker-a1` 로 이동하며 **zone 1:1 유지**(a1/host-a + b1·b2/host-b) |
| **hard TSC 가 Pending 을 만들지 않음** | app ns Pending **0**. hard 승격 때 가장 걱정했던 실패 모드인데 실제로 안 났다 |
| 유입 무영향 | 게이트웨이 `curl` **20/20 = 200** · `PROGRAMMED=True` · `.14` 유지 |
| uncordon 후 | 전 노드 Ready · 전체 Pending **0** · kubecost 4종 정상 복귀 |

#### ⚠️ 이 drain 이 증명하지 **못한** 것

**`nodeTaintsPolicy: Honor` 는 여전히 미검증이다.** a2 만 cordon 되고 a1 은 살아 있어 host-a 도메인이 계속 존재했다. Honor 가 값을 하는 국면은 **host-a 가 통째로 사라질 때**(a1·a2 동시 상실 → 그 zone 이 도메인에서 빠져야 생존 zone 으로 failover 가능)라, 노드 1대 drain 으로는 그 경로를 안 탄다. 과장하지 말 것.

#### 🔴 새로 드러난 것 — LocalPV 워크로드는 drain 하면 무조건 내려간다

drain 중 `cost` ns 파드 4개가 **Pending** 으로 남았다:
```
0/5 nodes are available: 1 untolerated taint, 1 unschedulable,
3 node(s) didn't match Pod's node affinity/selector
```
원인 = kubecost PV 3종이 **OpenEBS LVM LocalPV 라 `k8s-worker-a2` 에 결박**돼 있다(`pv.spec.nodeAffinity` = a2 고정). LocalPV 는 정의상 노드를 못 벗어나므로 그 노드가 unschedulable 인 동안은 **어디에도 뜰 수 없다.** uncordon 즉시 전부 복귀했다.

**운영상 의미**: `openebs-lvm` PVC 를 쓰는 워크로드는 **그 노드를 drain 하는 순간 다운타임이 확정**된다. PDB 로도 못 막고(축출은 성공하고 재스케줄이 실패한다) TSC 로도 못 푼다. replica 를 늘려도 소용없다 — PV 가 노드에 묶여 있기 때문.
- 현재 해당 대상 = **kubecost 뿐**(비필수 관측 도구라 허용 가능).
- ⚠️ 데이터 티어(PG·ES·Kafka·Redis)는 오퍼레이터가 **replica 별로 각자의 LocalPV** 를 갖는 구조라 사정이 다르다 — 노드 하나가 빠져도 나머지 replica 가 서비스한다. 위 문제는 **단일 replica + LocalPV** 조합에서만 생긴다.
- 🔴 앞으로 LocalPV 워크로드를 늘릴 때는 *"이건 그 노드와 생사를 같이한다"* 를 전제로 배치할 것. 노드 정비 계획에 그 다운타임을 넣어야 한다.

---

### 5.8 만개레시피 크롤 첫 실행 관찰 — 리소스·lag·KEDA (2026-08-02)

`mp-poller-recipe`(일·수 05:00 KST)의 **K8s 이전 후 첫 실행**. §3 수칙 *"이행 워크로드는 첫 실행을 반드시 관찰하고 limit 은 피크 실측 기반으로 재조정한다"* 의 이행이자, §5.2 가 남긴 **부채 2건(KEDA min 0 전환 · lag 임계 조정)** 의 판정 근거.

#### 실행 결과

```
LAST_SCHEDULE 2026-08-01T20:00:00Z (= 05:00 KST 정시)  →  Complete 11m30s
7,280건 검증 → Kafka produce 407건 → recipe.crawl.raw
후속 체인 전부 Complete: mp-poller-recipe-review(06:00) · mp-poller-es-recipes(06:30)
```

#### ① 리소스 limit — **재조정 불필요** (수칙 이행 완료)

| 폴러 | 피크 메모리 | limit | 여유 |
|---|---|---|---|
| **`mp-poller-recipe`** | **59.0 Mi** | 512Mi | **8.7×** |
| `mp-poller-recipe-review` | 62.3 Mi | 512Mi | 8.2× |
| `mp-poller-kurly`(전례·§3) | 855.4 Mi | 2Gi | 2.4× |

CPU 피크 **0.12 core**. 🔑 **컬리와 자릿수가 다른 이유 = chromium 미사용.** 순수 HTTP 크롤이라 7,280건을 스트리밍 처리해도 59Mi 에 머문다. 512Mi 유지가 맞고 request 128Mi 도 그대로 둔다(절감 69Mi 는 표준값을 깨뜨릴 값어치가 없다).
**PVC** `mp-recipe-crawl-state` = **1.9 Mi / 973 Mi (0.2%)** — CSV 4종이 그 정도다.

🪤 **`kubelet_volume_stats_*` 는 볼륨이 마운트된 동안에만 존재한다.** CronJob PVC 는 실행 중에만 잡히므로 평시 조회하면 **0 건**이다(클러스터 전체로는 17 시리즈 존재). 소급 조회는 `max_over_time(...[8h])` 로 해야 한다. ⇒ **CronJob 전용 PVC 는 사용량 알람을 걸 수 없다**(대부분의 시간 시계열이 없어 `absent` 계열도 상시 발화). 지금은 0.2% 라 무해하지만, 크롤 산출물이 커지면 감시 공백이 된다.

#### ② KEDA 지표 이상 — **판정 완료** (§5.2 ⚠️ 해소)

§5.2 가 *"min 0 전환 전에 KEDA 로그로 판정할 것"* 으로 남겼던 건. 로그 대신 **크롤 전후 지표 비교로 확정**됐다.

| 시점 | `keda_scaler_metrics_value{scaledObject="mp-recipe-refiner"}` |
|---|---|
| 크롤 전(12h offset) | **3** = `recipe.crawl.raw` 파티션 수 |
| 크롤 구간 최대 | **7** (= 실 lag) |
| 현재(오프셋 커밋 후·idle) | **0** |

⇒ 가설이 맞았다: **오프셋 무효 시 파티션당 1 을 반환하는 폴백**(`scaleToZeroOnInvalidOffset` 기본 false). 위험의 방향도 예상대로 **"안 깨어난다"가 아니라 "안 내려간다"** 였다 — 커밋 전에 min 0 을 걸었다면 지표가 3 에 붙잡혀 **파드가 영영 0 으로 안 내려갔을 것**이다.

#### ③ `recipe-refiner` min 1 → 0 — **전환 완료** (config #93)

게이트 조건(커밋 오프셋 확보)이 충족됐다.
```
커밋 오프셋  part0 137 + part1 129 + part2 141 = 407   ← produce 수와 정확히 일치
lag         0 / 0 / 0
전환 후     deploy replicas 0 · 파드 0 · ScaledObject ready=True active=False
```
🔴 **replica 0 에서도 lag 시계열이 살아 있음을 확인**(0/0/0, 커밋 오프셋 137/129/141). kafka-exporter 가 활성 멤버가 아니라 **브로커의 커밋 오프셋**에서 읽기 때문이다 — 이게 min 0 의 전제 그 자체다.

**오프셋 만료 = 유일한 시한폭탄.** Kafka 는 그룹이 **비는 순간부터** retention 을 센다. 실측 `offsets.retention.minutes=10080`(**7일**) vs 크롤 최대 간격 **4일**(수→일) → 여유 3일. ⚠️ 크롤이 7일 넘게 멈추면 오프셋이 만료돼 종전 상태로 회귀한다 → 그걸 잡으라고 `MpConsumerLagUnobserved` 에 `recipe-refiner` 를 추가했다(종전 3종 → 4종. 나머지 두 규칙은 **시계열이 있어야** 울리므로 이것만이 만료를 잡는다).

#### ④ lag 임계 100/15m — ⏸ **이월 (내가 만든 변경 때문에 오늘 데이터가 무효)**

| 컨슈머 | lag 피크 | `>100` 지속 |
|---|---|---|
| **recipe-refiner** | **5**(파티션별 최대 3) | **0분** |
| retail-refiner | 608 | **2.0분** (`for: 15m` 대비 여유 13분) |

임계 100 은 recipe 기준 20배 과하고 retail 기준 상시 초과 — **성격이 다른 컨슈머를 한 임계로 덮고 있다.** 다만 실제로 판별하는 건 `for: 15m` 쪽이고, 가장 바쁜 retail 도 2분만 초과하므로 "바쁨 vs 막힘" 은 제대로 갈리고 있다.

🔴 **그런데 위 recipe 피크 5 는 쓸 수 없다** — 같은 날 min 1→0 으로 바꿨기 때문이다. 저 값은 *컨슈머가 상시 떠 있던 구 설정*의 산물이고, min 0 에서는 KEDA 가 깨우는 동안(폴링 30s + 파드 기동) lag 이 쌓여 **다음 크롤의 피크가 확실히 더 높다.** 조건을 바꿔놓고 바뀌기 전 데이터로 임계를 조이면 안 된다.

#### 다음 크롤(2026-08-05 수 05:00 KST)에 볼 것 — 3건

1. **`recipe-refiner` 깨어남(0→1)** — min 0 하의 **첫 실전**. 합성 주입이 불가하므로(산출물이 사용자 검색에 노출) 이 기회뿐이다. 실패 시 롤백은 `minReplicaCount: 1` 한 줄
2. **lag 피크** — min 0 하의 대표값. 이게 나와야 ④ 임계를 조인다
3. **폴러 리소스 재확인** — 1회 관측이라 대표성 확인용(59Mi 가 안정적인지)

---

**과도기 명시 사항**: ① P2 전까지 자동 CD 없음(앱 변경 = 수동 반영) ② P1~P2 앱 파드 egress 에 `192.168.0.8`(VM 데이터) ipBlock 허용 — P2 에서 제거 ③ 파드→VM 구간은 WireGuard 미적용(현행 compose 와 동일한 평문 — 후퇴 아님).

---

### 5.9 CIS 후속 하드닝 — 감사 로그 · PSA · observability netpol (2026-08-03)

kube-bench 1회 실측(`mp_k8s_cis_benchmark_2026-08-03.md`)의 후속. **FAIL 13건 중 10건 해소.**
전부 IaC 다 — 마스터에 손으로 넣으면 다음 `kubeadm upgrade`·노드 재구축에서 조용히 사라진다.

| 조치 | CIS | 산출물 | 상태 |
|---|---|---|---|
| profiling 끄기 ×3 · kubelet 파일 권한 0600 | 1.2.15·1.3.2·1.4.1 / 4.1.1·4.1.9 | app **#495** | ✅ 라이브 |
| **apiserver 감사 로그** | 1.2.16~19 · 3.2.1~3.2.2 | app **#503** | ✅ 라이브 |
| **PSA 라벨 — 무라벨 ns 10개** | 5.2.x (자체발굴) | app **#505** | ✅ 라이브 |
| **observability NetworkPolicy** | 5.3.2 (자체발굴) | config **#130** | 📦 머지 · **미적용**(수동 sync) |
| etcd 디렉터리 소유권 | 1.1.12 | — | ⬜ 의도적 후순위(단일 멤버 etcd) |

**적용 = `ansible-playbook k8s.yml --tags cis_hardening --limit k8s-master`** (profiling + 감사로그 동시) ·
**`--tags psa`**(라벨). 스위치는 `group_vars/k8s_nodes.yml` 의 `cis_profiling_disabled`·`cis_audit_enabled`·`k8s_psa_enabled`.
⚠️ `cis_hardening` 은 컨트롤플레인 정적 파드를 재시작한다 — **kubectl 이 약 25초 끊겼다 복귀**(실측). 배포 중 금지.
백업 → `kubeadm config validate` 게이트 → 재생성 → `readyz`+CM/스케줄러 확인 → **실패 시 자동 롤백**이 붙어 있다.

#### 감사 로그 — 설계상 지킬 것

정책 = `roles/k8s_control_plane/templates/audit-policy.yaml.j2`.
잡음(`leases`·`events`·헬스URL·CP 컴포넌트 읽기) `None` → **RBAC 오브젝트·`pods/exec|attach|portforward`·워크로드 변경** `RequestResponse` → **Secret·ConfigMap 은 `Metadata` 까지만**.

🔴 **Secret 을 `RequestResponse` 로 올리지 말 것.** 평문 값이 로그 파일에 남아 etcd aescbc 암호화(§7 백업전략·#445)가 그 순간 무의미해진다.
🔴 **디스크 상한이 곧 안전장치**: `maxsize 100MB × (maxbackup 10 + 1) = 최대 1.1GB`. 상한 없이 켜면 마스터 디스크가 차고 **apiserver 가 선다** = 클러스터 정지.

#### 🔴 가동 직후 드러난 미결 — 보존창 13시간

디스크는 막았는데 **그 상한이 곧 보존 한계**였다. 실측(979초 창):
전체 **22.2 KB/s = 1.97 GB/일 → 보존 13.4시간**. 그런데 `pods/portforward` 가 **감사 바이트의 89.7%** 다 —
`192.168.0.160`(`kubectl/v1.34.10`, user `kubernetes-admin`)이 `mp-account`·`mp-price` 로 **초당 약 30건** port-forward 를 계속 건다.
그것만 빼면 0.20 GB/일 = **130시간(5.4일)**.

즉 아침에 사고를 발견하면 **전날 밤 증거가 이미 회전돼 없다.**
① 원인 워크스테이션 정리(정공법·정책 변경 0, 담당자 전달됨) ② `audit-log-maxbackup` 10→30(상한 3.1GB, 마스터 여유 43G 라 무해) ③ `omitStages` 에 `ResponseStarted` 추가(절반 절감, 대신 **안 끝나는 exec 세션이 안 보인다**).
상세 = `mp_k8s_cis_benchmark_2026-08-03.md §3.1`.

> 💡 감사 로그가 가동 90초 만에 "관리자 자격증명으로 API 서버를 초당 30회 두드리는 워크스테이션" 을 스스로 찾아냈다. 배경 = `admin.conf` 공유 상태(RBAC Phase 2 컷오버 전).

#### PSA — 🔴 수준은 반드시 dry-run 으로 정한다

`enforce` 는 **이미 도는 파드를 쫓아내지 않는다.** admission 게이트라 *다음 생성* 때 거부된다 —
잘못 걸면 지금은 멀쩡하다가 **노드 드레인·업그레이드 시점에 터진다.** 그래서 10개 전부
`kubectl label ns <ns> pod-security.kubernetes.io/enforce=<lv> --overwrite --dry-run=server` 의 위반 경고로 정했다.

- **privileged 4** = `kube-system`·`istio-system`·`metallb-system`·`openebs` — cilium·istio-cni·metallb-speaker·lvm-localpv-node 가 hostPath·privileged·hostNetwork 를 써서 **baseline 도 위반**. 낮추면 그 컴포넌트가 다음 재시작에 안 뜬다
- **baseline 3** = `cert-manager`·`external-secrets`(restricted 위반 0건이지만 오퍼레이터 ns 방침) · `default`(팀의 `kubectl run` 디버그 보존)
- **restricted 3** = `kube-public`·`kube-node-lease`·`cilium-secrets`(파드 영구 0)

현재 **전 ns 100%** = restricted 6 / baseline 14 / privileged 4. 무라벨 ns 재발은 `--tags psa` 의 assert 가 배포 시점에 잡는다.

#### observability netpol — ✅ 라이브 (v2, config #130 → #135)

`platform/policies-observability/` (config) · Application = `platform/argocd/policies-observability.yaml`.
최종 = **NetworkPolicy 8 + CiliumNetworkPolicy 1**.
🔴 **project 는 `platform` 이다** — `mealplanning` AppProject 의 destinations 가 app·data·pipeline 뿐이라 observability 를 쓰면 ArgoCD 가 sync 를 거부한다.
🔴 **수동 sync 다.** 관측 스택을 잘못 끊으면 *끊긴 걸 알려줄 수단(Prometheus)이 같이 죽는다.*

🔴 **v1 은 내부 도구 7종을 통째로 끊었다.** 원인 = `ipBlock` 이 Cilium 에서 사실상 `world` 신원에만
걸린다는 것을 몰랐다(LB 유입은 노드 `cilium_host`=파드 CIDR 로 SNAT 되어 온다).
→ v2 에서 **게이트웨이 전면개방**(원복) + **CiliumNetworkPolicy 엔티티**(`host`·`remote-node`·`kube-apiserver`)로 분리.
전말·교훈은 `docs/mp_netpol_zerotrust_flow.md §7.1`.

**v2 검증(2026-08-03, 임시 allow-all 제거 후 단독 상태)**: 내부 도구 7종 정상 · Hubble 드롭 **전 노드 0** ·
스크레이프 **71 up / 1 down**(DOWN 1 = 기존 kubecost) · 전환 유발 재시작 **0** ·
`operations → prometheus:9090` 파드 내부 호출 **200** ·
🔴 **카나리 경로는 Cilium BPF 정책맵 직접 조회로 확인**(`rollouts-controller → 9090/TCP Allow`).
분석 질의는 롤아웃 중에만 흘러 트래픽으로는 검증이 안 되고, 테스트 파드를 띄우면 Prometheus 타깃을 오염시킨다.

유입 화이트리스트는 Hubble 실측(`hubble observe --to-namespace observability`, 에이전트 5개 합산) 기반이다.
🔴 단 **`argo-rollouts` → Prometheus:9090 만 실측에 안 잡힌다**(위 이유). 빼면 **다음 배포에서 분석이
실패해 자동 롤백**되고, 증상이 "카나리가 이유 없이 abort" 라 원인 찾기가 매우 어렵다.

#### 🔴 netpol 적용 범위 결정 (2026-08-03)

observability 를 붙이면서 *"그럼 나머지 ns 는?"* 이 제기됐고, **범위를 결정으로 기록**했다 —
정본 = `docs/mp_netpol_zerotrust_flow.md §9`.

요지: 적용 = 워크로드 5 ns(파드 **77**) / 미적용 = 플랫폼·오퍼레이터 13 ns(파드 **75**).
미적용 75 중 **26(35%)은 hostNetwork 라 netpol 로 통제 자체가 안 된다**(kube-system 37 중 21).
→ 플랫폼 ns 는 **실익 낮음 + 오퍼레이터 조용한 정지 위험**을 근거로 후순위.

**✅ 1순위는 당일 처리됐다 — `app→data` 포트 제한(config #138)**: ns 전체 무제한 → **5포트**
(5432·6379·26379·9200·9092). 닫힌 것 = **9300 ES transport**(노드로 클러스터 합류하는 경로)·
9091/9090/8443 Kafka 내부·9114/9121 익스포터·8000 CNPG failsafe.
검증 = 드롭 0 · 파드 재시작 0 · conntrack 에 9200·26379 **새로 성립**(통과 실증) · BPF 정책맵 `ANY` 0개.
⚠️ 포트만 좁혔고 **"어느 서비스가"는 그대로다** — 침해된 recipe 는 여전히 PG:5432 에 닿는다(감사 §7.2-3 의 본론).

남은 순서 = ① **서비스별 app→data**(위 한계) → ② observability egress → ③ 오퍼레이터 ns.
🔴 `external-secrets` 는 2위에서 **내렸다** — ESO 는 K8s provider 라 비밀을 **apiserver 에 SA 토큰으로**
읽는다. 파드가 털리면 그 경로는 netpol 로 못 막고(막으면 ESO 가 죽는다), 밖에서 ESO 에 접속해도
비밀을 돌려주는 포트가 없다. **RBAC 문제이지 네트워크 문제가 아니다.**

🔴 **netpol 검증 방법 = `mp_netpol_zerotrust_flow.md §10`.** 하루에 세 번 "확인했다"의 근거가 틀렸다
(ipBlock 관례 답습 · Hubble 짧은 버퍼 · 메시 안 소켓 테스트). 질문별로 도구가 다르다 —
설계는 **설정 파일**, 현재 연결은 **conntrack**, 실제 허용은 **BPF 정책맵**, 파손 감지는 **Hubble DROPPED**.

---

### 5.10 공개 진입점 ns 분리 — `app` → `mp-ingress` (2026-08-06, #532 ③)

공개 Gateway `mp-gw-public`(.14)과 cloudflared 를 전용 ns 로 옮겼다. **무중단 아님** — 서비스 비운영 시간대에 계획 단절로 진행했다(`.14` 해제→재취득 구간).

#### 🔴 근거는 쿼터 하나로 좁혀졌다

진입점 격리를 처음 제기한 건 "인터넷 접점이 앱과 같은 신뢰 경계에 있다"였는데 그건 **#532 ② 의 양방향 default-deny 가 해결했다.** ns 분리로만 풀리는 건 하나였다:

> `mp-app-quota`(6Gi/6cpu)를 앱과 진입점이 **공유**한다 → account·recipe HPA 가 2→4 로 붙고 롤아웃이 겹치면 **게이트웨이 surge 파드가 못 뜬다.**

→ **`mp-ingress` 에는 ResourceQuota 를 두지 않는다.** 씌우면 가른 이유가 소멸한다. LimitRange(BestEffort 방지)만.
근거·표 상세 = [`object_spec §1.2`](./mp_k8s_infra_object_spec.md).

#### 무엇이 어디로

| | 위치 | 왜 |
|---|---|---|
| Gateway·params CM·PDB·EnvoyFilter·Issuer×2·Certificate·CF토큰 ES·Harbor pull ES | **`mp-ingress`** (config `ingress/`) | 전부 **같은 ns 전제 참조**(`parametersRef`·`certificateRefs`·DNS-01 솔버) — 하나라도 남으면 조용히 깨진다 |
| cloudflared 3종 | **`mp-ingress`** | 오리진이 GW |
| **HTTPRoute 12개** | **`app` 잔류** (config `gateway/`) | 🟢 backendRef 가 app ns Service 라 남기면 ReferenceGrant **0개**, 옮기면 **12개**. cross-ns 는 "라우트→GW 부착" 한 곳뿐이고 `allowedRoutes: Selector` + `parentRef.namespace` **두 줄**로 끝난다 |

구 `gateway/kustomization.yaml` 이 `namespace: app` 을 강제해 둘을 한 ns 에 묶었으므로 **디렉터리를 갈랐다**. ArgoCD 앱도 2개로: `mp-ingress`(path `ingress`) · `mp-policies-ingress`(path `platform/policies-ingress`) — **둘 다 수동 sync**(공개 유입의 유일한 입구라 "머지=강제"가 되면 안 된다).

#### 🔴 cross-ns 로 바뀌어 고친 참조 — 빠뜨리면 전부 "조용히" 계열

- `allowedRoutes: Same → Selector(app)` — Same 이면 mp-ingress 에 라우트가 0개라 **리스너가 라우트 없이 떠서 전 경로 404**. `All` 이 아니라 Selector 다(임의 ns 가 공개 경로를 못 만들게).
- **`netpol-frontend`·`netpol-backend` ingress 에 `namespaceSelector`** ← 가장 위험. 표준 netpol 의 `podSelector` 는 **정책과 같은 ns 만** 본다 → 0개 매칭 = 사이트 전면 불가.
- `netpol-gateway` egress 의 backend·frontend (반대 방향, 같은 이유)
- observability tempo ingress 에 `mp-ingress` 추가 — 빠뜨리면 **GW 트레이스가 무증상 소멸**
- cloudflared 오리진 `.app.svc` → `.mp-ingress.svc` — 빠뜨리면 전면 502

#### 🪤 착수 전엔 안 보였던 블로커 2개

1. **`AppProject/mealplanning` 이 어느 레포에도 없었다** — 손으로 apply 된 상태로만 존재. `destinations` 에 새 ns 를 안 넣으면 ArgoCD 가 배포를 거부하고, `clusterResourceWhitelist: []` 라 ns 도 못 만든다. **→ 이번에 IaC 편입 완료**(`k8s_argocd` 롤, 라이브 실물과 렌더 결과 완전 일치 확인). ⚠️ §5.6 의 "AppProject 는 git 에 없다"는 **`platform` 얘기였고 그건 2026-08-03 에 이미 해소**됐다 — 남아 있던 건 `mealplanning` 뿐이었다.
2. **cloudflared 는 Deployment 에 `imagePullSecrets` 가 없다** — 전적으로 **default SA** 의존(Harbor 이미지). 새 ns 엔 pull secret ES + SA 패치가 **둘 다** 필요. observability 의 내부 GW 선례는 이미지가 공개(`registry.istio.io`)라 이 함정을 안 덮는다.

#### 단절을 줄인 두 가지 (재현 시 그대로 할 것)

1. **인증서 선발급** — Gateway 없이 Issuer·CF토큰 ES·Certificate 만 먼저 적용해 발급(≈1.5분)을 단절 밖으로 뺐다. Gateway 를 같이 넣으면 `.14` 를 구 GW 가 쥐고 있어 충돌한다.
2. **정책을 워크로드보다 먼저 적용** — 새 cloudflared 파드가 정책 아래서 태어나 DNS 학습이 정상적으로 일어난다. → **#532 ① 에서 50초 502 를 냈던 `toFQDNs` 학습 함정이 아예 발생하지 않았다**(“apply + `rollout restart` 한 묶음” 수칙이 이 경로에선 불필요).

⚠️ **manual sync 는 prune 이 꺼져 있어 구 오브젝트가 남는다.** app ns 의 params CM·PDB·EnvoyFilter·Issuer×2·Cert·ES 2종·정책 4개를 손으로 지워야 `mp-policies` 가 Synced 로 돌아온다.

#### 검증 (전부 실측)

공개 URL 200×10 · LAN https 200 · LAN http **301**(리다이렉트 생존) · `/api/recipes` 200 실데이터 · HTTPRoute 12개 `Accepted=True`(parentNS=mp-ingress) · LE 인증서 신규 발급 · 드롭 0 · app ns 파드 전부 Ready.
**분리 효과** = app 쿼터 `3060m/6 · 3904Mi/6Gi`, `mp-ingress` 쿼터 **없음**.

---

## 6. 미결

1. **이전 착수 시점** — 선행조건은 충족. 5인 역할분담·9주 타임라인과의 정합만 남음
2. ~~**Cilium 라우팅 모드 최종**~~ → ✅ **해소(2026-07-27): VXLAN 확정·락**(§1.0.1). ~~집계 대역 측정~~ → ✅ **해소(2026-07-29 P2 리허설): 최대 59.7MB/s = 1GbE 의 50%, go**(§1.0.1·런북 §7.1)
3. ~~**Redis 오퍼레이터 선정**~~ → ✅ **해소(2026-07-29 실측 4라운드)**: OT-Container-Kit 유지 + 이미지 v0.26.0 + Sentinel 인라인 + **클라이언트 Sentinel-aware(분기 C — 접속 4곳 수정 완료, 이미지 ≥1.2.0)**. 근거 = `mp_k8s_redis_ha_handoff.md §4`
4. **PR 시점 pytest 게이트 공백** — 러너 은퇴로 GH `ci-test` 사망, Jenkins 는 main 머지 후에만 검사. 후속 = Jenkins 멀티브랜치 PR 빌드
5. ~~**호스트 B 물리 RAM 판정**~~ → ✅ **해소(2026-07-29)**: worker-b1 하드웨어 메모리 불량 실증(10분 39.6만 건) → **램 교체 + memtest86+ 1패스 PASS**(§1.0.3)

---

## 7. 미조치 감사 부채 (전수 감사 2026-08-02)

> P3·P4 까지 세운 것의 **반대편 목록**이다. §0~§5 가 "무엇이 서 있는가"라면 여기는 **"서 있지 않은 것 중 알고 있는 것"**이다.
> 원 감사 = read-only 에이전트 6기로 라이브 클러스터·양쪽 레포·문서 정본을 훑은 결과. **기록 시점(2026-08-02)에 전부 라이브 재검증했고, 재검증에서 뒤집힌 6건은 §7.7 에 따로 뺐다.**
>
> 🔴 **이 절은 조치 계획이 아니다.** 우선순위·착수 시점은 팀 판단이고, 여기에 임의로 P5 를 만들지 않는다. 항목이 해소되면 그 줄을 취소선 + 근거로 바꾼다(§6 관례와 동일).
> ⚠️ **재검증 근거를 각 항목에 남겼다** — "감사가 그랬다"가 아니라 **지금 직접 확인 가능한 형태**여야 6주 뒤에도 쓸 수 있다.
> ⚠️ 같은 날 실행된 **Stage3 1차 부하테스트**([`mp_k6_stage3_peak_viral.md` 부록 A](./mp_k6_stage3_peak_viral.md))가 감사 항목 몇 개를 **실측으로 덮었다** — 그쪽이 더 강한 증거라 §7.3-4·§7.4-1·§7.4-2·§7.4-4 는 부록 A 기준으로 적었다.

### 7.1 데이터 내구성 — 가장 아픈 축

| # | 발견 | 실측 근거 (2026-08-02 재검증) |
|---|---|---|
| 1 | **ES 백업 0건 — 사실이지만 *의도된 결정*이다. 진짜 문제는 문서 상충** | `GET _snapshot` → `{}` · `GET _slm/policy` → `{}` (리포지토리 자체 미등록). 🔴 **그런데 이건 부채가 아니다** — 백업 정본 [`mp_k8s_backup_strategy.md`](./mp_k8s_backup_strategy.md) `:27`·`:108` 이 **"ES·Redis·Kafka 는 의도적 백업 제외(재파생/재수집)"** 로 결정했고, 리허설에서 **재색인 7초**를 실측했다(`:47` — 종전 목표 "RPO 12h·RTO 2h" 를 실측이 대체). **실제 부채는 구 문서다**: `backup-strategy.md:76-78`(Docker 시절)에 *"매일 14시·02시 S3 snapshot·14일 보존 · RTO 2시간"* 이 **superseded 표기 없이 살아 있다** → 원 감사 에이전트가 이걸 읽고 **"설계됐는데 구현된 적 없음"으로 오독했다**. 조치 = 구 문서 superseded 표기(§7.5-3 `design.md §8.4` 와 같은 부류) |
| 2 | ~~**DR 폴백 `recipes` 인덱스 = 단일 사본, worker-b2 종속**~~ → ✅ **#9 해소(2026-08-03)** | 라이브 `_cat/indices/recipes` = **green · pri 1 · rep 1 · docs 5,900**. 즉시 `_settings` 변경뿐 아니라 `pipelines/ingest/index_recipes_es.py`의 create 설정도 replica 1로 고쳐 다음 drop→recreate 뒤에도 유지된다. 특정 b2 단일 사본 부채는 종료 |
| 3 | 🔴 **라이브 검색 인덱스에 한국어 분석기가 없다** → ⏳ **T-3 중간 해소 보고(2026-08-03)** | 앱 읽기·PGSync 쓰기를 안정 alias `recipes_live`로 통일한 뒤 nori/keyword 매핑·replica 1의 `recipes_v2`를 검증했다는 실행 보고가 있다. PG·ES 8,963건·분석 결과·API 13/275건·CRUD CDC 수치는 정확한 조회 시각이 없어 최종값이 아니다. config ops SSOT merge 뒤 재검증해야 취소선/완료로 바꾼다. 구현·gate = 아래 §7.1-3a |
| 4 | 🔴 **PGSync 가 조용히 멈추면 PG primary 가 죽는다** | PGSync 안정 slot `foodbudget_recipes_live`의 CDC 소비를 CRUD로 확인했다는 중간 보고가 있다. 하지만 daemon의 liveness/readiness probe 부재와 `MpPGSyncDown`의 **"떠 있는데 일 안 하는"** 사각지대는 그대로다. `max_slot_wal_keep_size=-1`도 무제한이다. T-2가 retained-WAL 알람을 **1GiB/critical**로 앞당겼지만 이는 백스톱이지 소비 정지 감지가 아니다. 또한 구 `foodbudget_recipes_pgsync` slot이 inactive 상태로 WAL을 계속 보존하므로, bounded rollback window 종료 시 slot과 `public._view`의 정확히 두 행(`recipe`, `recipe_ingredient`) 각각의 `indices` 배열에서 구 값을 한 원자적 교체로 함께 제거해야 한다(§7.1-3a) |
| 5 | **Kafka·ES·MinIO 알람 0건** | 우리가 쓴 알람 35개에 `MpES*`·`MpKafka*`·`MpMinIO*` 가 없다. PrometheusRule 은 `mp-pg`·`mp-pgsync`·`mp-redis-ha`(데이터) + `mp-app-sli`·`mp-container-memory`·`mp-descheduler`·`mp-physical-layer`·`mp-tempo`·`mp-workload-spread`·`mp-pipeline` 뿐 → **ES yellow/red · 브로커 상실 · MinIO 포화가 전부 무성**이다. MinIO 는 단일 replica 예외(§0)라 특히 아프다 |
| 6 | **Harbor·Jenkins 정기 백업이 안 돌고 있다** | 롤이 설치해야 할 유닛(`mp-harbor-backup.{service,timer}` · `mp-jenkins-backup.{service,timer}`)이 **호스트 C 에 없다** — `/etc/systemd/system` 에는 앱 유닛 `harbor.service`·`jenkins.service` 만. 근인 = 로컬 `infra/ansible/secrets.yml` 에 **`backup_s3_*` 키 0건** → 롤 첫 태스크 assert 에서 막힌다. S3 에 있는 건 `s3://mp-backup-ap2/jenkins/jenkins-home-20260729.tar.gz.enc` **1건(2026-07-29·164MB)** 이 전부이고 이후 갱신이 없다. **`harbor/` 프리픽스는 존재하지 않는다.** *(호스트 C 에 도는 `mp-source-backup.timer` = 월간 소스 백업으로 별건.)* Jenkins 는 JCasC 도 없어 자격증명·마스터키가 `JENKINS_HOME` 안에만 있다 → **레지스트리는 클러스터 복구의 전제**라는 `CLAUDE.md` 의 IaC 경계 근거가 지금 실물로 성립하지 않는다 |
| 7 | **`data` ns 워크로드가 root** | `mp-pgsync`·`mp-redis-pgsync` — pod·container securityContext **둘 다 빈 값**(plain Deployment 라 오퍼레이터가 넣어주지 않는다). PGSync 는 PG 복제 자격증명을 들고 **DB 와 같은 ns 에서 root** 로 돈다 |

#### 7.1-3a ⏳ T-3 안정 alias 전환 — 중간 검증·남은 merge/lifecycle gate (2026-08-03)

서로 다른 두 근인을 분리해야 한다.

1. **검색 품질 근인** — nori 플러그인은 3노드에 있었지만 index settings/mapping을 생성하는 tracked
   경로가 없었다. PGSync가 동적 매핑으로 `recipes_pgsync`를 먼저 만들면서 analyzer와 exact mapping이
   빠졌다. canonical mapping artifact는 config 레포 `ops/pgsync-stable-alias/recipes-index.json`이며,
   이 app 변경보다 먼저 merge돼야 한다(`PENDING_AFTER_CONFIG_MERGE`).
2. **세대교체 충돌 근인** — PGSync의 logical index 이름을 물리 세대명으로 썼고 그 이름에서 slot이
   파생됐다. `recipes_v2`로 직접 바꾸면 `foodbudget_recipes_v2`가 필요해 bootstrap 권한 충돌이
   반복된다. 앱과 PGSync의 논리 이름을 `recipes_live`로 고정해 physical generation과 slot identity를
   분리했다.

```
PG recipe / recipe_ingredient
        │
        │ PGSync CDC (slot: foodbudget_recipes_live)
        ▼
recipes_live  ──alias──▶  recipes_v2
        ▲                   ├─ nori korean analyzer
        │                   ├─ keyword/boolean 명시 매핑
mp-recipe ES_INDEX          └─ primary 1 + replica 1
```

- config 레포 `platform/pgsync/schema-configmap.yaml`은 #119에서 **`recipes_live`**가 됐다. 앱 레포
  `deploy/pgsync/schema.json` 사본 변경은 config ops SSOT merge 뒤에만 merge한다.
- Recipe Rollout도 **`ES_INDEX=recipes_live`**다. 다음 재색인은 새 물리 세대를 만든 뒤 final-sync
  barrier로 변경분 반영을 증명하고 alias를 원자적으로 옮긴다. 앱 재배포나 새 slot 이름은 필요 없다.
- `recipes_v2`는 `name`·`ingredient_names`에 `korean` analyzer를, exact 필드에는
  `keyword`, `servable`에는 `boolean`을 명시했다. PGSync 동적 매핑에 다시 기대지 않는다.

##### 중간 라이브 검증 보고 — 최종 close 증거 아님

아래 값은 실행 에이전트 완료 보고에서 왔고 정확한 라이브 조회 시각이 기록되지 않았다. 11:10~11:25 KST
baseline과도 별개다. config ops SSOT merge 뒤 새 timestamp로 다시 측정하기 전에는 최종 수치로 인용하지 않는다.

| 항목 | 2026-08-03 실측 |
|---|---|
| ArgoCD | `pg`·`pgsync`·`mp-recipe` 모두 Synced/Healthy |
| alias | `recipes_live`가 `recipes_v2` 한 곳을 가리키며 alias 쓰기 성공 |
| 정합 | PG 8,963행 = ES 8,963문서 |
| 분석 | `김치찌개 → ['김치찌개','김치','찌개']` |
| 실제 API | `김치찌개` 13건 · `김치` 275건 |
| CDC | 테스트 recipe INSERT→UPDATE→DELETE가 ES에 순서대로 반영되고 최종 잔재 없음 |
| 권한 영향 | 관련 table owner는 계속 `fbapp`; superuser·table ownership 변경 없음 |

##### bootstrap identity와 slot lifecycle

stock PGSync full bootstrap은 한 세션에서 table-owner 검사와 replication slot 생성을 모두 수행한다.
runtime `pgsync` role만으로는 기존 trigger를 DROP할 수 없고, `fbapp`만으로는 slot을 만들 수 없는
권한 분리가 있었다. 이를 우회해 slot만 손으로 만든 것이 아니라 CNPG `DatabaseRole/mp-pgsync-bootstrap`을
일회성 migration identity로 사용했다.

활성 시에는 `REPLICATION`, `INHERIT`, `inRoles: [fbapp, pgsync]`,
`connectionLimit: 10`과 임시 password Secret을 부여했다. 이 role로 stock full bootstrap을 한 번
실행해 안정 slot `foodbudget_recipes_live`, `_view.indices`, trigger를 같은 작업에서 만들었다.
bootstrap 뒤에는 다음 상태로 park했다.

```
NOLOGIN · NOREPLICATION · inRoles=[] · connectionLimit=1
disablePassword=true · password NULL · superuser/createdb/createrole/bypassrls=false
```

재활성화할 때는 preflight가 stable slot/`_view`/trigger의 재구축 필요를 확인한 DR·artifact 복구 창에서만
`disablePassword: true`를 **반드시 제거하거나 false로 바꾼 뒤**
`passwordSecret`을 지정한다. CNPG CRD에서 `disablePassword: true`와 `passwordSecret`은
상호 배타다. DB role의 password NULL과 K8s basic-auth Secret 부재는 서로 다른 gate다. bootstrap이
끝나면 role park와 임시 Secret 삭제를 각각 검증한다.

##### 🔴 T-3 close 조건

기능 전환 중간 보고는 있지만 아래 선행 merge·운영 정리·재검증 전에는 T-3를 완료 처리하지 않는다.

1. **config ops SSOT 선행 merge** — `ops/pgsync-stable-alias/`의 PR/commit은 아직
   `PENDING_AFTER_CONFIG_MERGE`다. config merge·SHA 기록 뒤 app 문서/schema를 merge하고 최종 검증한다.
2. **구 slot·metadata 폐기** — `foodbudget_recipes_pgsync`는 inactive여도 WAL을 계속 보존한다.
   rollback window에 종료 시각을 붙이고, 끝나면 `public._view`의 정확히 두 행(`recipe`,
   `recipe_ingredient`) 각각의 `indices` 배열에서 `recipes_pgsync` 값만 한 원자적 교체로 함께 제거한다.
   두 행과 `recipes_live` 값은 보존한다. 무기한 보존은 rollback이 아니라 WAL 누수다.
3. **임시 Secret 삭제** — owner/ExternalSecret/Argo tracking 없는
   `data/mp-pgsync-bootstrap-db`를 제거하고 absence를 확인한다.
4. **재현 가능한 bootstrap/preflight/final-sync** — 이번 실행은 삭제된 ad-hoc Job과 수동 ES/SQL 검증에
   의존했다. tracked runbook 또는 GitOps Job으로 role 활성화 → full bootstrap → ACL/CRUD/count 검증
   → park/Secret 삭제를 고정하고, stock bootstrap 전에 slot·`_view`·trigger 상태를 검사해야 한다.
   정상 generation swap에는 bootstrap 대신 alias 전환 직전 final-sync/LSN barrier가 필요하다.
5. **rollback 실행안 고정** — 전환 뒤 구 인덱스는 CDC를 소비하지 않아 곧 stale해진다. 구 consumer
   catch-up, LSN final barrier, manifest가 아직 없으므로 단순 alias rollback은 실행 절차가 아니라
   설계 스케치다. tracked runbook이 완성되기 전에는 현장에서 실행하지 않는다.

카테고리 필드의 ES 매핑은 `keyword`로 바로잡혔지만, 실제 서빙 대상 `source='10K'`의
`category` 원천값이 전부 NULL인 데이터 문제는 별개로 남아 있다. 따라서
`category=국&찌개 → 103건`은 T-3 성공 기준이 아니며 크롤러/정제 파이프라인 이슈로 추적한다.

### 7.2 보안

| # | 발견 | 실측 근거 (2026-08-02 재검증) |
|---|---|---|
| 1 | 🔴 **cluster-admin ServiceAccount 2개 + 만료 없는 토큰** | `mp-users` ns SA 5개. ClusterRoleBinding — `mp-bongsu-cluster-admin`·`mp-taehyun-cluster-admin` = **cluster-admin**, `geonu`·`jungeun`·`junghyun` = `view`. 그 위에 RoleBinding(ClusterRole `edit`) **4건** = `app/mp-geonu-edit` · `pipeline/mp-geonu-edit` · `pipeline/mp-jungeun-edit` · `observability/mp-junghyun-edit` → **해당 ns Secret 전권**. 토큰 5개 전부 `kubernetes.io/service-account-token`(legacy = **만료 없음**). ~~그리고 kube-apiserver 커맨드에 **`--audit-*` 플래그가 0개** → 유출돼도 탐지 수단이 없다.~~ → 🟢 **audit 부분은 2026-08-03 해소**(§5.9) — 감사 로그 가동으로 "누가 무엇을 언제" 는 남는다. **토큰 만료 없음은 그대로 미해결.** 🔴 종전 서술("`team-access` ns SA 1개·읽기전용")은 **낡았다** — `team-access` ns 는 **NotFound** 다 |
| 2 | 🔴 **`mp-operations` 가 공용 인터넷 너머 제3자 PG 로 평문 전송** | 라이브 env: `PGHOST=211.46.52.152` · `PGPORT=15432` · `PGUSER=team2` · `PGDATABASE=postgres` · **`sslmode` 미설정**. 앱 소스에 하드코딩은 없다(= config 레포 주입) |
| 3 | **AuthorizationPolicy 0건 — 인증은 하는데 인가를 안 한다** | `kubectl get authorizationpolicy -A` → 0건 · `virtualservice` 0건 · 앱용 `DestinationRule` 0건(유일한 DR = `observability/mp-harbor-ext-tls`). mTLS STRICT 로 *누구인지*는 증명하는데 *허용되는지*는 아무도 안 본다. 게다가 `app/mp-backend` netpol 의 egress 중 `data` ns 규칙에 **`ports` 가 없다**(전 포트 허용) → **침해된 recipe 파드가 account 와 동일한 DB 도달 범위**를 갖는다. Kafka 리스너도 `plain/9092` · `tls=false` · **인증 없음** |
| 4 | **Harbor 레지스트리 스캔 0건 · CI 는 HIGH 를 통과시킨다** | `GET /api/v2.0/scanners` → **`[]`**(스캐너 미등록 → 스캔 리포트가 생길 수 없다). `mealplanning` 프로젝트 = repo 18개·2.7GB. CI 게이트는 `Jenkinsfile:207` 의 `trivy image --scanners vuln --severity CRITICAL --ignore-unfixed --exit-code 1` → **HIGH 는 정책적으로 통과**다. 이미지 서명·SBOM·베이스 digest 핀 전부 없음 |

### 7.3 가용성·용량

| # | 발견 | 실측 근거 (2026-08-02 재검증) |
|---|---|---|
| 1 | **엣지에 레이트리밋·WAF 가 없다** | EnvoyFilter 는 `app/mp-gw-request-body-limit`(15MiB buffer) **1개뿐**. connection limit·라우트 타임아웃·WAF 0 |
| 2 | **서킷 브레이킹 0건 — 전파는 이미 관측됐다** | 앱용 DestinationRule 이 없어 `outlierDetection`·`connectionPool` 부재. 실측 근거 = [`mp_k8s_loadtest_design.md:30`](./mp_k8s_loadtest_design.md) — **500VU 에서 account 지연이 mealplan·chat 으로 전파**, account 예산조회 **최대 14,112ms** / mealplan cart **최대 8,120ms**. *(⚠️ 최대 응답시간이다 — 원 감사가 "cart p95 8,120ms" 로 옮겼는데 p95 아니다)* |
| 3 | **app ns 파드 19개 전부 priority 0** | `priorityClassName` 이 전부 `<none>`. `app-normal`(100000) 은 만들어만 두고 **app ns 에서 미사용** — 실사용자는 엉뚱하게 `data` ns 의 PGSync 2종이다. `pipeline-low`(1000)·`data-critical`(1000000) 은 정상 적용. → **노드 메모리 압박 시 크롤러 배치가 결제 경로보다 오래 산다** |
| 4 | **HPA 2개가 구조적으로 발화 불가** | `mp-account`(request cpu **500m**) · `mp-recipe`(**300m**), 둘 다 ContainerResource 70%. 실측 사용량은 **3~4m = request 의 0.8~1.3%** → 파드당 350m/210m 을 찍어야 스케일하는데 실사용이 1% 대다. 라이브 표시도 `cpu: 0%/70%`. request 가 실사용의 **60~100배**라 오토스케일이 장식이다. ⚠️ **단 "HPA 를 더 붙이자"가 답은 아니다** — recipebook 은 Stage3 통제 실험으로 **HPA 무효가 실증됐다**(§7.4-2) |
| 5 | 🔴 **host-a 상실을 b1·b2 가 수용하지 못한다** | 노드 메모리 **요청률** — a1 67%(7,202Mi) · a2 58%(5,651Mi) · b1 **84%**(8,248Mi) · b2 73%(7,152Mi). allocatable = b1·b2 각 9,728Mi → **b1+b2 여유 합 ≈ 4.0GiB 로 a1+a2 상주 ≈ 12.6GiB 를 못 받는다.** 게다가 a1 의 `pg-1`·`es-es-a-0`·`kafka-combined-1`·`mp-redis-1` 은 **LocalPV 라 애초에 이동 자체가 불가**다. 이전 감사의 "83% 로 수용"은 LocalPV 워크로드를 계산에서 빼서 나온 수치였다 → **TSC·PDB 로 못 푸는 문제**(노드 증설/재배분 영역, §5.5 잔여부채 5와 같은 뿌리) |

### 7.4 앱 ↔ 인프라 정합 (앱 측 — 인프라 판단에 종속되는 것만)

> 🔴 **앱 결함의 추적 정본은 GitHub Issues 다**(여기가 아니다 — 정본 이원화 금지). 그런데도 이 절을 인프라 SSOT 에 남기는 이유는 **캐시·HPA·replica·알람 설계 판단이 이 사실들에 종속**되기 때문이다. "Redis 를 HA 로 만들 가치가 있나"를 판단할 근거가 인프라 문서 밖에 있으면 다음 사람이 또 같은 자리에서 헤맨다.

| # | 발견 | 실측 근거 (2026-08-02 재검증) |
|---|---|---|
| 1 | 🔴 **캐시 전략이 도메인과 반대로 서 있다 (Stage3 가 이걸 병목으로 지목했다)** | Redis 는 실측 **8키·3MB** 인데 페일오버를 4라운드 실검증하고 전용 핸드오프 문서까지 썼다. 정작 `GET /api/recipes/{id}` 는 `get_detail`(execute 7) + `_load_refs`(2) = **PG 왕복 9회**이고, recipe 서비스 코드에 **redis/cache 참조가 0건**이다. 그중 `retail_item_price_compare` 는 matview 위의 **VIEW**(`pipelines/ingest/migrate_retail_crawl.py:102` = `CREATE OR REPLACE VIEW`) → **매 요청 GROUP BY 재집계**. ⇒ 이건 취향 문제가 아니다 — Stage3 1차가 **측정으로 도달한 처방이 "결과 캐시"** 였다(아래 2). 인프라 측 함의: **Redis HA 에 쓴 노력 대비 Redis 를 실제로 쓰는 경로가 없다** |
| 2 | 🔴 **바이럴 경로의 천장은 실측됐고, 스케일로 안 풀린다** | `/api/recipes/shared/{token}` → recipebook `shared` 라우터(`routers.py:143`), **인증 불요**(코드 주석 명시)·캐시 없음·**PG 왕복 5회**(토큰 조회 1 + `enrich_ingredients` 4 — `services/recipebook/app/queries.py:24-75`). Stage3 1차 실측([`mp_k6_stage3_peak_viral.md` 부록 A](./mp_k6_stage3_peak_viral.md), 2026-08-02): hotkey knee ≈ **250~350 rps**(200rps=71.9ms ✓ / **400rps=3.08s abort**). 🔴 **통제 scale-test `recipebook` 1→3 이 p95 를 전혀 안 낮췄다**(3.08s → 3.08s, 3 pod 각 ~250m **CPU 여유**) → 병목은 pod 도 앱 풀도 아니라 **다운스트림 PG enrich** 다. 게다가 부하 중 **`pg-2`(replica)는 idle 인데 enrich 읽기가 전부 `pg-1`(primary)로 간다.** ⇒ **처방은 HPA/replica 가 아니라 ① 왕복 배칭·조인 ② 결과 캐시 ③ 읽기 라우팅.** 별건으로 `?q=`(`shared_search`)는 선행 와일드카드 ILIKE + jsonb 캐스트 seq scan 이라 행 누적에 **p95 52ms → 2.77s** 선형 악화(처방 = `pg_trgm` GIN). 멘토 피드백의 "레시피북 공유 fan-out"이 정확히 이 경로다 |
| 3 | 🔴 **예산 앱인데 돈이 안 맞을 수 있고 조용하다** | 영수증→재고→지출이 **브라우저가 코디네이터**다 — `frontend/src/lib/queries.ts:430-439` 가 `addExpense()` 실패를 `catch { /* pantry는 이미 저장됨 */ }` 로 삼킨다(재시도·보상 없음). saga·outbox·정합성 배치 전무. **HTTP 쓰기에 idempotency key 0건**(레포 유일한 hit = `services/mealplan/app/events.py:35` 의 Kafka `enable.idempotence`, 무관) |
| 4 | **유저 레시피는 구조적으로 검색에 안 잡힌다 (팔로우 기능은 아예 없다)** | 팔로우 = 스키마·코드·PRD 전부 **0건**. 유저 레시피는 `recipebook` 스키마(`user_recipe`·`shared_recipe`·`bookmark`·`extract_job`)인데 PGSync 는 `public` 만 감시 → `GET /api/recipes?q=` 가 **유저 레시피를 반환할 수 없고** 프론트가 별도 PG-ILIKE 로 클라이언트 병합한다. **조리시간·난이도 필터를 켜면 유저 레시피가 통째로 사라진다.** ✅ **Stage3 가 실측으로 확정**(부록 A.3 H10): `catalog_es_hits` = **0** — 코드 근거가 아니라 관측으로 ES 미노출이 확인됐다 |
| 5 | **fan-out 수신자가 사실상 0** | `price.price_watch` **5행** · `notify.notification_setting` **0행**(작성자 없음 — UI 가 localStorage 에 저장) · 탐지 CronJob·컨슈머 미배포 · 알림 전달 = DB row 폴링인데 `refetchInterval` 없음(새로고침 전엔 안 보임). 즉 멘토 피드백의 **"다자간 트래픽" 기둥이 현재 0-수신자 INSERT 경로**다 |

### 7.5 관측·프로세스

| # | 발견 | 실측 근거 (2026-08-02 재검증) |
|---|---|---|
| 1 | **알람이 증상을 안 본다** | 우리 알람 **35개**(전체 169개 중 나머지는 Helm 차트 제공). 그중 **유저 경로 SYMPTOM 은 2개** — `MpAppHighP95Latency`·`MpAppHighErrorRate`. 나머지는 원인 지표다. **SLO·에러버짓·번레이트 0건**(유일한 멀티윈도 번레이트는 차트가 준 `KubeAPIErrorBudgetBurn` = apiserver 용) |
| 2 | **git 밖 오브젝트 2개 — 손 apply 상태** | `Telemetry/istio-system/mp-mesh-tracing` 이 config 레포에 **없다**(grep 0건) · `randomSamplingPercentage: 100`. `AppProject/platform` 도 같은 부류(config 레포에 `kind: AppProject` **0건**, §5.5 잔여부채 1). → **샘플링을 줄이려면 먼저 git 으로 가져와야 한다**(라이브만 고치면 다음 재구축에서 사라진다) |
| 3 | 🔴 **`design.md §8.4` 가 낡았고, 그걸 대체할 ADR 이 없다** | §8.4 는 4-VM Docker 토폴로지(**VM1 = PG+ES+Redis+Kafka**)를 서술한다 — 실제로는 전부 in-cluster(§2.1). 마이그레이션 플랜 §12 가 스스로 "ADR 후보"라고 적었는데 **`docs/adr/` 는 0건**이다. 즉 **프로젝트 최대 인프라 결정이 `CLAUDE.md` 배너 한 줄과 이 문서로만 지탱**된다 |
| 4 | **피크 집중률이 문서 간 2배 차이 — 측정 도구는 꺼져 있다** | `design.md` (DAU 500 추정 단락) "피크 **~30%** 집중" vs `mp_k6_stage3_peak_viral.md §3.1 A4` "**60%**". λ 가 여기 정비례해 부하 등가표 전체가 흔들린다. 🔴 그런데 `EVENT_PRODUCE_ENABLED: "false"`(config 레포 `services/mealplan/base/configmap.yaml:9`) 라 `activity.user_event` 가 **37행**뿐 — **가장 논쟁적인 가정(k=3.0)을 측정할 도구를 만들어놓고 꺼둔 상태**다. 켜고 2주면 가정 4개가 실측으로 바뀐다 |
| 5 | **config 레포 `platform/policies/README.md` 가 사실과 정반대** | 문서: *"NetworkPolicy 는 의도적으로 아직 없다 … 실측: netpol 은 argocd ns 의 자기방어 6개뿐"*. 라이브: **NetworkPolicy 18 + CiliumNetworkPolicy 10**. 읽는 사람이 "여긴 netpol 없음"으로 판단하면 정책을 중복 신설하거나 기존 것을 지운다 |

### 7.6 P0-D — 착수했다가 의도적으로 미룬 것

`pipelines/kustomization.yaml:31-55` 의 RFC-6902 **`op: add` 는 merge 가 아니라 replace** 다. `/spec/.../securityContext` 전체를 통째로 갈아치우므로 base 의 `runAsNonRoot`·`readOnlyRootFilesystem` 이 **렌더에서 증발**한다.

- 라이브 확인: pipeline CronJob 들의 pod securityContext = **`{"seccompProfile":{"type":"RuntimeDefault"}}` 단독**(= `runAsNonRoot` 없음) → 파이프라인 워크로드가 root 로 돈다.
- 안전장치: **config#98 `scripts/policy-baseline.txt` 에 위반 54건을 동결**했다(파일 89줄 = 주석 포함). 새 위반만 실패하고 기존 54건은 통과한다. 현재 `python3 scripts/validate.py` = **통과**(경고 1 = kubeconform 미설치).
- 🔴 **2026-08-05 크롤 관찰 이후에 할 것.** 기전을 고쳐 `readOnlyRootFilesystem` 이 실제로 먹으면 **Playwright 크롤러(`mp-poller-kurly`)가 tmp 쓰기 때문에 깨진다** → `emptyDir` 배선이 선행이다.

### 7.7 🔴 원 감사 보고 중 **재검증에서 뒤집힌 것** (기록 시점 정정)

**감사 결과를 그대로 옮기지 않았다.** 아래는 2026-08-02 재검증에서 틀렸거나 낡은 것으로 드러난 항목이다 — **§7.1~§7.6 에는 정정된 값만 들어가 있다.**

| 원 감사 보고 | 재검증 결과 (2026-08-02) |
|---|---|
| **worker-a2 에 앱 파드 0개** (`tier=backend` a1:6/b1:4/b2:4/a2:0) | ❌ **낡았다** — 실측 분포 **a1:3 / a2:5 / b1:3 / b2:3**. a2 가 오히려 최다다. §5.6 descheduler + 재스케줄로 해소된 것으로 보인다. *(단 "11개 백엔드 TSC 가 `ScheduleAnyway` 라 강제력 없다"는 서술 자체는 여전히 사실 — 지금 균형은 보장이 아니라 결과다)* |
| `price_watch` **0행** | ❌ **5행**으로 늘었다. "fan-out 수신자 0" 서술의 근거는 `notification_setting` 0행 쪽만 유효하다(§7.4-5 반영) |
| NetworkPolicy **21개** | ⚠️ **18개** (CiliumNetworkPolicy 10 은 일치) |
| **`edit` SA 3개** | ⚠️ RoleBinding **4건** / 사용자 **3명**(geonu 가 app·pipeline 두 곳) |
| **Harbor·Jenkins 백업 0건** | ⚠️ 절반만 사실 — **정기 백업(타이머)이 없는 건 맞다**. 다만 Jenkins 는 2026-07-29 수동 1회분이 S3 에 있다(`jenkins/jenkins-home-20260729.tar.gz.enc`). Harbor 는 **진짜 0건** |
| 알람 **34개** | ⚠️ **35개** — config#96 의 `MpTempoDown` 이 반영됐다 |
| `recipes` 인덱스가 **"b2 단독"** | ✅ **감사 당시에는 사실, #9로 해소(2026-08-03)** — 당시 primary가 `es-es-b-0`@`k8s-worker-b2` 단독이었다. 현재는 **green · pri 1 · rep 1 · docs 5,900**이고 인덱서 create 설정도 rep 1이라 재생성 후 유지된다 |
| **ES 백업이 "설계됐는데 구현된 적 없다"** | ❌ **오독이었다** — 백업 정본은 ES 를 **의도적으로 제외**(재파생, 재색인 7초 실측)했다. 감사가 읽은 건 superseded 미표기 상태로 남아 있는 **구 문서**(`backup-strategy.md:76-78`)다. 정정판 = §7.1-1 |
| **cart p95 8,120ms** | ⚠️ **p95 가 아니다** — `mp_k8s_loadtest_design.md:30` 의 500VU **최대 응답시간**이다(account 예산조회 14,112ms 동반). "전파가 관측됐다"는 결론은 유효 |
| **공유 경로 p99 1.000초 = 앱 최악** | ❌ **근거를 못 찾았다** — 어느 문서에도 그 수치가 없다(있는 건 목표 임계 `p95 < 1s` 와 **미측정 가설** H8·H9). 대체 = Stage3 1차 실측 **knee 250~350rps · 400rps 에서 3.08s abort**(§7.4-2) |
| **recipebook 은 `replica 1 · HPA 없음`이 부채** | ❌ **처방이 반증됐다** — 통제 scale-test 1→3 이 p95 를 전혀 안 낮췄다(3.08s→3.08s, CPU 여유). recipebook 은 **HPA 대상이 아니다.** 부채의 위치가 스케일이 아니라 **enrich 왕복·캐시·읽기 라우팅**으로 옮겨간다(§7.4-2) |
| 공유 경로 **PG 왕복 5회** | ✅ 맞다(토큰 조회 1 + `enrich_ingredients` **4**). *기록 중 핸들러만 세고 5회를 1회로 잘못 셌다가 정정 — `enrich_ingredients` 를 빼먹으면 이 경로의 비용이 5배 과소평가된다* |

**이게 남기는 교훈 두 개.**

1. **감사 보고는 관측 시점의 사진이다.** 30여 건 중 **11건이 나흘도 안 돼 뒤집혔다** — `worker-a2` 는 이미 해소된 문제를 고치려 들 뻔했고, `recipebook HPA` 는 실측이 정반대 처방을 냈고, ES 백업은 **부채가 아니라 문서 상충**이었다. → **§7 항목에 착수할 때는 착수 직전에 그 줄의 재검증 명령을 한 번 더 돌린다.**
2. 🔴 **뒤집힌 6건 중 3건의 원인은 "라이브가 변했다"가 아니라 "문서를 잘못 읽었다"** 다(ES 백업·cart p95·p99 1.0초). superseded 미표기 문서가 살아 있으면 **읽는 쪽이 성실해도 틀린 결론에 도달한다** — §7.5-3·§7.5-5 와 같은 뿌리이고, 이게 이 절에서 가장 값싸게 고칠 수 있는 부채다.

---

*이 문서는 인프라 상태 변경 시 갱신한다. 결정을 바꿀 때는 [`mp_k8s_infra_migration_plan.md`](./mp_k8s_infra_migration_plan.md)에서 바꾸고 여기로 반영한다. 구 Docker 스택 문서 [`docker-infra-status.md`](./docker-infra-status.md) 는 2026-07-31 폐기 — 사고 이력 참고용으로만 남는다.*
