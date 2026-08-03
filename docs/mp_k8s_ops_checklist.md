# mp-k8s 운영 점검 체크리스트 — 일반 체크리스트 ↔ 우리 스택 대조 (실행용)

> **목적**: 외부 k8s 실무 체크리스트(일반론: Longhorn·Patroni·Fluentd·Kyverno…)를 **우리 실제 스택으로 번역** + 서버에서 바로 돌릴 `kubectl` 명령 + **우리 정본(오브젝트 시방서 등) 연결**.
> **작성** 2026-08-03 · 라이브 대조본 · 관리자 kubeconfig(마스터 `.17` `admin.conf`) 전제.
> **정본 연결**: 📘 = `docs/mp_k8s_infra_object_spec.md` 섹션 · 그 외 문서는 파일명 명시.
> **범례**: ✅ 우리도 함/해당 · 🔄 다른 걸로 대체 · ⚠️ 갭(안 함) · ❌ 우리 구조상 무관

---

## 0. 스택 번역표 (일반 도구 → 우리 실제)

| 체크리스트(일반) | 우리 실제 | 정본 |
|---|---|---|
| Longhorn / Ceph | **OpenEBS LVM LocalPV** (노드 로컬, RWX 금지) | 📘 §6 |
| MinIO(주 스토리지) | **MinIO = 관측(LGTM) 백엔드·단일 replica** + **S3 = 백업** | 📘 §6 · `mp_k8s_backup_strategy.md` |
| Patroni / Stolon | **CNPG (CloudNativePG)** — patronictl 없음 | 📘 §8 |
| MongoDB | **없음** | — |
| Redis(범용) | **OT-Container-Kit** RedisReplication + Sentinel | 📘 §8 |
| Elasticsearch | **ECK** (auth 켬·HTTP TLS 끔) | 📘 §8 |
| Linkerd | **Istio**(sidecar) | 📘 §11 |
| kube-proxy | **Cilium** kubeProxyReplacement(eBPF) — kube-proxy 미설치 | `mp_k8s_infra_status.md` |
| Ingress(nginx) | **Gateway API(구현체 Istio)** + MetalLB — HTTPRoute(VS/DR 아님) | 📘 §5 |
| Fluentd/EFK | **Loki + Alloy (PLG)** | `mp_k8s_infra_status.md` |
| Prometheus | **kube-prometheus-stack** (동일) | `mp_k8s_infra_status.md` |
| Kyverno/Gatekeeper | **없음** ⚠️ | — |
| Falco | **없음** ⚠️ | — |
| kube-bench(CIS) | ✅ **1회 실측 완료(2026-08-03)** | `mp_k8s_cis_benchmark_2026-08-03.md` |
| Trivy(operator) | **Trivy = CI(Jenkinsfile) 게이트만** | — |
| Jenkins k8s dynamic agent | **Jenkins = 클러스터 밖 host C(.10) docker** | `mp_k8s_infra_status.md §4.1` |
| Deployment(앱) | **Argo Rollouts**(canary, 배포전략 S6) — `get rollout` | 📘 §9 |

---

## 1. 동적 스토리지 & 데이터 지속성 · 📘 §6

**● Longhorn 디스크 용량 & I/O 병목** — *스토리지 프로비저너의 볼륨 용량·복제 상태.*
🔄 Longhorn 아님 → **OpenEBS LVM LocalPV**. Longhorn UI 없음.
```bash
kubectl get sc
kubectl -n openebs get pod
kubectl get pv -o custom-columns=NAME:.metadata.name,CAP:.spec.capacity.storage,SC:.spec.storageClassName,STATUS:.status.phase
```

**● MinIO / S3 오브젝트 스토리지** — *오브젝트 스토어 디스크·버킷 라이프사이클.*
🔄 MinIO는 주 스토리지 아님 = **관측(LGTM) 백엔드·단일 replica**. 오프사이트 실체 = **AWS S3**(백업).
```bash
kubectl -n observability get pod -l app=minio
```

**● Dynamic Provisioning & StorageClass** — *기본 SC·PV ReclaimPolicy가 명세와 맞는지.* ✅
```bash
kubectl get sc          # openebs-lvm(기본·Delete) / openebs-lvm-retain(Retain)
kubectl get pv -o custom-columns=NAME:.metadata.name,RECLAIM:.spec.persistentVolumeReclaimPolicy
```

**● (객체상세) PVC/PV 상태 & Volume Binding** — *Pending PVC·바인딩 모드.*
✅ 우리 SC = **WaitForFirstConsumer** → 소비자 없는 CronJob의 Pending은 정상.
```bash
kubectl get pvc -A | grep -v Bound
```

**● (객체상세) Longhorn Volume/Replica Health** — ❌ Longhorn 없음. LVM은 노드 로컬이라 replica 개념 없음(노드 헬스로 대체).

---

## 2. 데이터베이스 안정성 · 📘 §8 (오퍼레이터 CR) · §4.5 (Pooler)

**● StatefulSet & 클러스터링 상태** — *PG/Mongo/ES 클러스터 노드 상태.*
🔄 **오퍼레이터 CR**로 봄(Patroni 아님, Mongo 없음, CNPG는 STS도 아님).
```bash
kubectl -n data get cluster pg -o wide                              # CNPG
kubectl -n data get pod -l cnpg.io/cluster=pg -L cnpg.io/instanceRole
kubectl -n data get elasticsearch es                                # ECK, HEALTH=green
kubectl -n data get redisreplication mp-redis
kubectl -n data get kafka,kafkatopic                                # Strimzi, RF=3
```

**● DB 백업 & 복구 (WAL/Oplog)** — *스냅샷·PITR 정기동작·RPO/RTO 충족.* **(선생님 핵심 항목)**
✅ **2계층 — 오프사이트 + 온사이트**. 📘 `mp_k8s_backup_strategy.md §4 · §4.1`
- **오프사이트(DR 정본)** = CNPG barman 연속 WAL + 정기 base → S3, 보존 30일
- **온사이트(빠른 논리복구)** = `pg_dump -Fc` → 인클러스터 MinIO, 매일 04:00 KST, 보존 7일
  ✅ **신설·E2E 검증 완료(2026-08-03)** — 238MB → 23MB · 약 30초. Job 안에서 `pg_restore --list` 로
  검증해 **오브젝트 50개 미만이면 업로드 자체를 중단**한다
- 🔴 **온사이트는 DR 이 아니다** — MinIO 가 단일 replica·`worker-b2` LocalPV 라 **사본 0개**이고
  PG 와 같은 사이트다. 사이트 상실의 답은 **S3 하나뿐**. 둘의 역할이 다르다(PITR ↔ 테이블 단위 즉시 복원)
```bash
kubectl -n data get scheduledbackup,backup      # 오프사이트: mp-pg-daily, LAST BACKUP<24h
kubectl -n data get cronjob mp-pg-onsite-dump   # 온사이트: 04:00 Asia/Seoul
```

**● Redis / Elastic 메모리 관리** — *Redis maxmemory·OOM, ES JVM heap.* ✅
```bash
kubectl -n data describe pod mp-redis-0 | grep -i -A2 "Limits\|oom"
kubectl -n data logs es-es-a-0 | grep -i "OutOfMemory" | tail   # 노드셋 a/b — 파드는 es-es-a-0·es-es-b-{0,1}
```

**● (객체상세) StatefulSet Pod Order & VolumeClaimTemplate** — *Ordered 기동·Headless DNS.* ✅ (ES/Kafka/Redis)
```bash
kubectl -n data get sts -o custom-columns=NAME:.metadata.name,READY:.status.readyReplicas,DESIRED:.spec.replicas
```

**● (객체상세) DB Connection Pool & Throttle** — *PG max_connections 포화·풀링.*
✅ **CNPG Pooler(PgBouncer)** — 실증: 4 replica에서도 커넥션 12/100. 📘 §4.5
```bash
kubectl -n data get pooler pg-pooler
kubectl -n data exec pg-1 -c postgres -- psql -tAc \
  "select count(*),state from pg_stat_activity group by state;"
```

---

## 3. MSA 네트워크 & Service Mesh · 📘 §5 (Gateway) · §11 (메시) · §4 (Service)

**● mTLS 인증서 만료 & 설정** — *서비스 간 mTLS Strict·CA/사이드카 인증서 유효기간.*
✅ **PeerAuth STRICT**. 워크로드 인증서는 **Istio 자동회전**(만료 대상 아님), 관리 대상은 **cert-manager TLS**.
```bash
kubectl get peerauthentication -A       # mp-app-strict-mtls = STRICT
kubectl get certificate -A              # cert-manager NotAfter
```

**● Envoy Sidecar 리소스 오버헤드** — *사이드카 CPU/메모리 증가로 노드 압박.* ✅
```bash
kubectl top pod -A --containers | grep istio-proxy | sort -k4 -h | tail
```

**● Ingress/Egress Gateway & 라우팅** — *게이트웨이·라우팅 규칙 일치·외부연결.*
🔄 Ingress 아님 = **Gateway API**. VS/DR 안 씀 → HTTPRoute.
```bash
kubectl get gateway,httproute -A        # mp-gw-public(.14)/mp-gw-internal(.15), PROGRAMMED=True
istioctl analyze -A                     # (istioctl 있으면) 에러 0
```

**● (객체상세) Service & Endpoints 매핑** — *셀렉터 불일치로 Endpoints 비는지.* ✅
```bash
kubectl get endpoints -A -o jsonpath='{range .items[?(@.subsets==null)]}{.metadata.namespace}{"/"}{.metadata.name}{"\n"}{end}'
```

**● (객체상세) Istio CRD 동기화** — *Envoy 설정 SYNCED/STALE.* ✅
```bash
istioctl proxy-status                   # 전부 SYNCED
```

**● NetworkPolicy 격리 통신** — *ns별 default-deny·화이트리스트.*
✅ **netpol + CiliumNetworkPolicy**(tier별, mp-policies 앱). 📘 §10 · `mp_netpol_zerotrust_flow.md`
```bash
kubectl get netpol,ciliumnetworkpolicy -A
```

---

## 4. 쿠버네티스 보안 & 컴플라이언스 · 📘 §10 (보안) · §7 (비밀)

**● Kube-bench CIS Benchmark** — *노드/컨트롤플레인 CIS 보안기준 충족.*
✅ **1회 실측 완료(2026-08-03)** → 📘 `mp_k8s_cis_benchmark_2026-08-03.md`
결과: control-plane 48P/**10F**/48W · worker 16P/**3F**/6W. **진짜 조치대상 = 5건**(나머지는 우리 아키텍처상 오탐/보류).
🟢 **같은 날 4건 조치 완료 — 위 숫자는 감사 시점(오전) 스냅샷이다. 재실행하면 달라진다.**
- ✅ **감사 로그(audit) 활성화** — 가장 큰 실질 갭이었다(**#503**)
- ✅ profiling=false ×3 (apiserver/controller/scheduler) · ✅ kubelet 파일 권한 0600 ×2 (**#495**)
- ⬜ etcd 디렉터리 소유권 — 단일 멤버라 **의도적 후순위**(유일한 미착수)
- ⏸ *보류(고치면 깨짐)*: `1.2.5` kubelet CA, `1.2.30` SA 토큰
```bash
# 재실행(감사 시에만·읽기전용·실행 후 삭제):
kubectl apply -f docs/manifests/kube-bench-audit.yaml
kubectl -n kube-system logs job/mp-kube-bench-master
kubectl delete -f docs/manifests/kube-bench-audit.yaml
```

🔴 **WARN 54건 질문이 나오면** — *"전부 `(Manual)` 입니다"* 가 답이다(Automated WARN **0건**, 실측).
CIS 원문이 *"Minimize wildcard use…"* 처럼 **기준이 조직마다 다른** 항목을 "사람이 판단"으로 분류해 놨고,
kube-bench 는 판정하지 않고 항상 WARN 을 낸다 → **우리 상태와 무관하게 항상 뜨는 값**이다.
즉 이 도구는 *설정 플래그·파일권한*은 전수 스캔하지만 *"정책이 적절한가"* 는 **스캔하지 않는다.**
→ 그래서 WARN 은 **질문지**로 쓴다. 우리 답(2026-08-03 실측):

| Manual 항목 | 우리 답 |
|---|---|
| `5.1.1` cluster-admin 최소화 | 바인딩 4개 — kubeadm 기본 2 + **의도적 2**(`bongsu`·`taehyun`). 5인 중 2명만 admin |
| `5.2.x` Pod Security | ns 라벨로 강제 — **전 ns 100%**(restricted 6 / baseline 14 / privileged 4). 무라벨 10개는 2026-08-03 채움(**#505**) |
| `5.3.2` ns별 netpol | app 3(+CNP 4) · data 8(+1) · pipeline 2(+5) · argocd 6 · observability 7(**적용 대기** — config #130) |
| `5.3.1` CNI netpol 지원 | Cilium 1.19.6 — NetworkPolicy + CiliumNetworkPolicy 둘 다 사용 |

**답해본 결과 드러난 갭 2건**(→ §9) = `observability` ns netpol 0개 · 시스템 ns PSA 라벨 없음.
→ 🟢 **둘 다 같은 날 처리**: PSA 는 라이브(#505) · netpol 은 작성·머지 완료, **적용만 대기**(config #130).

**● 감사 로그(audit)** — *"누가 무엇을 언제 했나" 를 사후에 물을 수단.*
✅ **2026-08-03 가동**(#503). 정책 = `roles/k8s_control_plane/templates/audit-policy.yaml.j2`
(잡음 `None` → RBAC·exec·워크로드 변경 `RequestResponse` → 🔴 **Secret 은 `Metadata` 까지만**).
```bash
# 마스터에서 — 플래그·정책·로그가 다 있어야 한다
sudo grep -E 'audit-|profiling' /etc/kubernetes/manifests/kube-apiserver.yaml
sudo ls -la /var/log/kubernetes/audit/          # audit.log 존재·증가
# 🔴 보존창 확인(§9 미결 항목): 상한 1.1GB 라 증가 속도가 곧 보존 기간이다
sudo du -sh /var/log/kubernetes/audit/
```
🔴 **Secret 을 `RequestResponse` 로 올리지 말 것** — 평문 값이 로그에 남아 etcd 암호화가 무의미해진다.

**● Kyverno / Gatekeeper Policy** — *root·privileged 금지, 이미지 레지스트리 allowlist를 admission에서 강제.*
⚠️ **없음 = 갭**. 단 GitOps+RBAC로 이미지 출처가 이미 Harbor 고정이라 한계효용 작음(도입 보류).

**● Falco 런타임 위협 탐지** — *컨테이너 내 이상행위 실시간 탐지.* ⚠️ **없음 = 갭**(운영부담 커서 보류).

**● RBAC & NetworkPolicy** — *과도한 cluster-admin·ns default-deny.*
✅ **k8s_team_rbac Phase1**(사람별 role) + netpol. 📘 `mp_k8s_rbac_plan.md`
```bash
kubectl get clusterrolebindings -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.roleRef.name}{"\n"}{end}' | grep -i cluster-admin
kubectl get rolebinding,clusterrolebinding -A | grep -iE 'mp-|team'
```

**● (객체상세) ServiceAccount & 과도권한** — *wildcard(*) verb 보유 role.* ✅
```bash
kubectl get clusterrole -o json | grep -B3 '"\*"' | grep '"name"' | head
```

**+ 우리 추가 강점**(선생님 리스트 밖) — **etcd at-rest 암호화(aescbc) 라이브** + **ESO 비밀관리**. 📘 §7
```bash
sudo grep encryption-provider-config /etc/kubernetes/manifests/kube-apiserver.yaml   # 마스터에서
kubectl get clustersecretstore          # fb-kubernetes = Valid
```

---

## 5. 모니터링 & 옵저버빌리티 · 📘 `mp_k8s_infra_status.md`(관측)

**● Prometheus TSDB & Retention** — *메트릭 보존·Targets DOWN.* ✅ kube-prometheus-stack
```bash
kubectl -n observability get pod | grep -E "prometheus|kube-state"
kubectl -n observability exec prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
  wget -qO- localhost:9090/api/v1/targets | grep -o '"health":"[a-z]*"' | sort | uniq -c
```

**● Alertmanager 알림 채널** — *경보가 Slack로 가는지.* ✅
```bash
kubectl -n observability get pod alertmanager-kube-prometheus-stack-alertmanager-0
```

**● Fluentd/Loki/ES 로그 수집 병목** — *콜렉터 버퍼·저장 용량.*
🔄 Fluentd 아님 = **Loki + Alloy(PLG)**.
```bash
kubectl -n kube-system get ds | grep alloy
kubectl -n observability logs loki-0 --tail=30
```

---

## 6. CI/CD 파이프라인 (Jenkins) · 📘 `mp_k8s_infra_status.md §4.1` (host C)

**● Jenkins Dynamic k8s Agent Pods** — *빌드 slave 파드 생성/정리·docker socket 보안.*
❌ **무관** — Jenkins는 **클러스터 밖 host C(.10) docker**. k8s 동적 에이전트 안 씀.
```bash
ssh ubuntu@192.168.0.10 'docker ps --format "{{.Names}}\t{{.Status}}"'   # jenkins/harbor/sonarqube
```

**● Private Registry (Harbor) & Image Scanning** — *이미지 취약점 스캔·ImagePullSecrets.*
✅ **Harbor(host C) + Trivy(Jenkinsfile 게이트, CRITICAL fixable 차단)**. 스캔 = **CI 단계**.
```bash
kubectl get secret -A | grep -i dockerconfigjson
kubectl -n argocd get application | grep -iv "Synced.*Healthy"    # CD(ArgoCD) 이상만
```

---

## 7. 워크로드 · 노드 · 기본 인프라 · 📘 §2 · §3 · §9 · §13 · §1

**● Drawio 아키텍처 ↔ 실제 일치성** — *문서 ns/포트/경로가 실 클러스터와 맞는지.*
✅ 우리 문서 = 📘 §1(ns)·§5(Gateway).
```bash
kubectl get ns
kubectl get svc,httproute -A
```

**● Node 상태 & Kubelet 커널 파라미터** — *Ready, swapoff, sysctl.* ✅ (노드-레벨은 SSH)
```bash
kubectl get nodes -o wide
kubectl describe nodes | grep -A5 Conditions | grep -iE "Pressure|Ready"
# 노드에서: swapon --show(비어야) ; sysctl net.ipv4.ip_forward(=1)
```

**● Pod Resource Limit/Request** — *limits 누락 → OOM Killer·HPA 무력화.* ✅ 📘 §13
```bash
kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.namespace}{"/"}{.metadata.name}{" -> "}{.spec.containers[*].resources.limits}{"\n"}{end}' | grep -v "map\[" | head
```

**● (객체상세) HPA & Autoscaling** — *HPA 존재·임계값, TARGETS `<unknown>`=metrics-server 문제.*
✅ **account/recipe(HPA 2~4) + pipeline(KEDA scale-to-zero)**. 타겟=**Rollout**(배포전략 S6). 📘 §9
```bash
kubectl get hpa -A
kubectl get scaledobject -A
kubectl get rollout -A
```

**● (객체상세) Pod Probe (Liveness/Readiness/Startup)** — *오설정 → 롤링업데이트 실패·무한재시작.* ✅ 📘 §3
```bash
kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.name}{" L:"}{.spec.containers[0].livenessProbe.httpGet.path}{" R:"}{.spec.containers[0].readinessProbe.httpGet.path}{"\n"}{end}' | grep -v " L: R:$" | head
```

**● (객체상세) RestartCount & OOMKilled** — *CrashLoop·ExitCode 137(OOM).*
```bash
kubectl get pods -A --sort-by=.status.containerStatuses[0].restartCount | tail -15
kubectl get events -A --field-selector reason=OOMKilling --sort-by=.lastTimestamp
```

**● (객체상세) Scheduling constraints (Anti-Affinity)** — *같은 노드 쏠림 방지.*
✅ 배치원칙(master·quorum·PG primary 노드 분산) + **PDB**.
```bash
kubectl get pdb -A
kubectl get pod -n data -o wide --sort-by=.spec.nodeName
```

**● (객체상세) Node Conditions & Pressure / Events** — *Disk/Memory/PID Pressure·Warning 이벤트.*
```bash
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .status.conditions[?(@.status=="True")].type}{.}{" "}{end}{"\n"}{end}'
kubectl get events -A --field-selector type=Warning --sort-by=.metadata.creationTimestamp | tail -30
```

---

## 8. 요약 — 선생님 항목 대비 우리 매핑

| 상태 | 항목 |
|---|---|
| ✅ **동등/충족** | 스토리지·DB(**백업 2계층 — 오프사이트 S3 + 온사이트 MinIO**)·mesh mTLS·netpol·RBAC·**CIS 감사 + 후속조치 10/13**·**감사로그(audit) 가동**·**PSA 전 ns 100%**·관측·리소스·HPA·Probe·노드 |
| 🔄 **대체(설명 필요)** | Longhorn→OpenEBS · Patroni→CNPG · Ingress→Gateway API · Fluentd→Loki/Alloy · Jenkins k8s에이전트→host C docker |
| ⚠️ **갭** | Kyverno · Falco · **감사로그 보존창 13h**(§9) · observability netpol **적용 대기**(작성·머지는 끝) · CIS etcd 소유권 1건 |
| ❌ **무관** | MongoDB · Longhorn replica · Jenkins 동적에이전트 |

## 9. 남은 갭 & 조치

| 갭 | 상태 | 조치 |
|---|---|---|
| ~~**CIS 후속 5건**~~ | ✅ **4/5 완료(2026-08-03)** | profiling ×3 + kubelet 권한 0600 = **#495** · **감사로그 = #503** — 전부 IaC(kubeadm ClusterConfig / Ansible)로 라이브. 남은 1건 = etcd 디렉터리 소유권(단일 멤버 etcd라 **의도적 후순위**). 상세 = `mp_k8s_cis_benchmark_2026-08-03.md §3` |
| 🔴 **감사로그 보존창 13시간** | **신규(2026-08-03) · 미결** | 상한 1.1GB 는 지켰는데 그게 곧 보존 한계다. **`pods/portforward` 가 감사 바이트의 89.7%** — `192.168.0.160` 이 초당 ~30건 port-forward. 그것만 멈추면 **5.4일로 자동 복귀**(담당자 전달됨). 차선 = `audit-log-maxbackup` 10→30. 상세·선택지 = `mp_k8s_cis_benchmark_2026-08-03.md §3.1` |
| ~~**PG 온사이트 백업**~~ | ✅ **완료(2026-08-03)** | `CronJob/mp-pg-onsite-dump` 04:00 KST → MinIO `mp-pg-onsite` 버킷. **라이브 E2E 검증됨**. config 레포 `platform/pg/onsite-backup.yaml` 외 4파일. 📘 `mp_k8s_backup_strategy.md §4.1` |
| **observability ns netpol** | 🟡 작성·머지 완료 · **적용 대기** | config **#130** — default-deny(Ingress) + Hubble 실측 기반 유입 화이트리스트 + MinIO egress 잠금, 총 7개. **수동 sync**(automated 미설정)라 머지만으론 안 나간다. 🔴 잘못 끊으면 *끊긴 걸 알려줄 수단(Prometheus)이 같이 죽으므로* ①baseline→②crossns→③minio-egress 순으로 하나씩 sync·확인. 절차 = config PR #130 본문 |
| ~~**시스템 ns PSA 라벨 없음**~~ | ✅ **완료(2026-08-03)** | app **#505** — 무라벨 10개에 라벨 부여, **전 ns 100%**(restricted 6 / baseline 14 / privileged 4). 수준은 전부 `--dry-run=server` 위반 실측으로 결정. 🔴 `enforce` 는 **도는 파드를 안 쫓아내고** 다음 생성 때 거부하므로, 값 변경 시 반드시 dry-run 먼저. 무라벨 ns 재발은 `--tags psa` 의 assert 가 잡는다 |
| **Kyverno/Falco** | 미도입(인지된 갭) | 우선순위 낮음 — GitOps+RBAC로 상당부분 커버, 리뷰 시 "인지된 갭"으로 명시 |

> 🔴 **아래 2건은 kube-bench 가 준 게 아니다.** WARN 54건(전부 `Manual`)을 "질문지"로 보고
> 하나씩 우리 증거로 답해보다가 **답이 안 나오는 칸**으로 드러난 것이다.
> 검사기의 FAIL 만 봤다면 못 찾았다 — 이 사용법 자체가 설명거리다.

## 부록. 정본 문서 인덱스

| 영역 | 문서 |
|---|---|
| 오브젝트 상세(§1~13) | `docs/mp_k8s_infra_object_spec.md` (📘) |
| 인프라 현황·접속·관측·host C | `docs/mp_k8s_infra_status.md` |
| 백업 전략 | `docs/mp_k8s_backup_strategy.md` |
| CIS 감사 실측 | `docs/mp_k8s_cis_benchmark_2026-08-03.md` |
| RBAC | `docs/mp_k8s_rbac_plan.md` |
| netpol 제로트러스트 | `docs/mp_netpol_zerotrust_flow.md` |
