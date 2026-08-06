# CLAUDE.md — food-budget-app (월 식비 예산 기반 밀플래닝)

작업 전 필독. **설계 정본 = `docs/design.md`** (소스오브트루스, 재파생 금지).
⚠️ 단 **인프라 부분(`design.md §8.4` 온프렘·하이브리드)은 superseded** — 인프라는 아래 §인프라의 SSOT 를 따른다.

## 프로젝트
월 식비 예산 기반 밀플래닝 앱. 레시피 재료 추출 → 마켓컬리 현재가 비교 → 예산 계획·추적.
AI 해커톤 + 인프라 캡스톤 겸용 (5인, 8-9주).

## 절대 제약
- **AI 전부 CPU** (GTX 1060 3GB → GPU 학습 불가). CRF/XGBoost/LightGBM만. *(예외: YouTube 영상 추출은 외부 Gemini API — AGENTS.md 절대제약 3 예외 참조)*
- **학생 예산** — GPU 인스턴스 금지, AWS Spot+셀프호스트.
- **데이터** — 공공 오픈데이터/공식 API + **교육용 비상업 크롤링 허용** (마켓컬리·오아시스마켓 신선+가공, 만개의레시피).
  단, 비상업 목적·비공개 전제. *(쿠팡 크롤은 robots+Akamai 블로커로 보류 → 마켓컬리로 대체, design.md §3·§8)*

## 기술 스택 (확정)
**단일 언어(Python): FastAPI API + ML + 데이터 파이프라인.**
PG(OLTP + 경량 가격 이력) + Elasticsearch(레시피+상품 검색) + Redis. *(ClickHouse 드롭 — 고볼륨 시계열 승격 시 재도입)*
Kafka(Strimzi) + KEDA. **kubeadm(온프렘 → EKS 이식 전제), Terraform, Jenkins + Harbor + ArgoCD.**
프론트=React/Vite/PWA. → 상세 §6

## 명명 규칙 — 🔴 새로 만드는 것은 전부 `mp-` (`fb-` 금지)

**앞으로 생성하는 모든 이름은 `mp-` 접두사를 쓴다.** 대상 = K8s 오브젝트·이미지·S3 버킷/프리픽스·VM·볼륨·DB 롤·레포·브랜치 등 **이름을 새로 짓는 전부**.
🔴 **`fb-`(food-budget 시절 잔재)는 신규에 절대 쓰지 않는다** — 내가 임의로 `fb` 를 섞어 제안하는 것도 금지(예: ~~`mp-fb-backup`~~ → `mp-backup`).
- 예외 = **기존 실물 이름**(`fb-data`·`fb-app-ai`·`fb-secrets` ns·`fb-local-ca`·`fb-kubernetes` SecretStore 등)은 **그대로 참조**한다. 리네임은 별건이고, 참조를 깨뜨리면 배포가 죽는다.
- K8s 상세 규칙(= `Service` 는 bare `account`·`recipe`…, 그 외 오브젝트는 `mp-` 접두사)은 `docs/mp_k8s_infra_status.md §2.3`.

## 인프라 (IaC) — SSOT = `docs/mp_k8s_infra_status.md`

**인프라 상태·세부의 단일 소스 = `docs/mp_k8s_infra_status.md`** (목표 아키텍처·구축 현황·사고기반 필수수칙). **인프라 변경 시 거기 갱신.**
이전 결정·근거·컷오버 절차(why/how) = **`docs/mp_k8s_infra_migration_plan.md`**.
**P1 앱 이전을 맡는 사람은 `docs/mp_k8s_p1_app_handoff.md` 부터 읽는다** (P0 산출물·함정·아직 없는 것).

> 🟢 **P0 클러스터 가동 시작** (2026-07-27) — 호스트 B 에 3노드(`k8s-master` `.17` · `k8s-worker-b1` `.18` · `k8s-worker-b2` `.19`), **kubeadm 1.34.10** (kube-proxy 미설치) + **Cilium 1.19.6**(kubeProxyReplacement · VXLAN · WireGuard) 까지 Ready. 그 위에 **기반 스택까지 가동** — MetalLB(풀 `.14`–`.16`) · OpenEBS LVM(SC 2종) · cert-manager(로컬 CA 승계) · MinIO · ESO · kube-prometheus-stack+metrics-server · Istio 1.30.3(+istio-cni·Gateway API CRD) · ArgoCD. **+ LGTM 선배포**(2026-07-28) — Loki·Tempo·Alloy 를 **ArgoCD Application**(platform AppProject)으로 가동, 컷오버(알림·`.11` 철거)는 P4 유지 — status §4.3. IaC = Terraform `vms_k8s.tf` + Ansible `k8s.yml`(**전체 재실행 `changed=0`**). **P0 완료(2026-07-28) → P1 앱 이전 완료(2026-07-28, 4노드·Gateway `.14` 유입) → 🎉 P2 데이터 컷오버 완료(2026-07-30 새벽 — 유실 0·roll-forward·`.8` 정지) → 모니터링 컷오버 완료(2026-07-30 — 구 P4 를 당김: 규칙·Slack 알림·물리계층 스크레이프·로그·대시보드 전부 인클러스터 정본, `.11` 은 역할 전무·철거 대기)**. → **🎉 P3 스케일 완료(2026-07-30 밤)** — 앱 9개 **CNPG Pooler 경유**·풀 10→5·**account HPA**·**KEDA scale-to-zero**(컨슈머 3종 min 0). 핵심 실증 = account 4 replica 에서도 PG 커넥션 12/100. 다음 = **P4**(`.8`·`.9`·`.11` VM 해체 + worker-a1 14GB 확장·a2 = 5노드). 상세는 `docs/mp_k8s_infra_status.md §5.1`.
> **버전 핀**: K8s `1.34.10`(apt hold) · Cilium `1.19.6` · containerd `2.2.6` · Helm `3.21.3`. **K8s 1.34 는 Cilium 이 정한 상한**(1.19.6 e2e = 1.31–1.34) — 1.35·1.36 으로 올리지 말 것.
> **운영·장애대응·접속의 정본은 이제 K8s 쪽**(`docs/mp_k8s_infra_status.md` §4.0 — kubectl·**내부 도구 = `https://<이름>.mealbong.cloud` 6종**(내부 게이트웨이 `.15`, 2026-07-30 — 구 Grafana `:30300`·loki `:31100` NodePort 회수)·ArgoCD). ⛔ `docs/docker-infra-status.md` 는 **폐기됐다**(2026-07-31 P4 — `.8`·`.9`·`.11` 실물 파괴). 살아 있던 **호스트 C(`.10`)·하이퍼바이저(`.12`) 내용은 `docs/mp_k8s_infra_status.md` §4.0(접속)·§4.1(구성·롤·포트·운영 함정)로 승계**됐다. 그 문서는 **사고 이력 원문 참고용으로만** 남는다.

- **목표 토폴로지**: 물리 3대 — 클러스터용 A·B(**Proxmox**, **kubeadm 직접**[Kubespray 기각] master ×1 + worker ×4, **노드 램프 3→4→5대** — status §1) + **호스트 C `.10`**(Harbor·Jenkins·SonarQube, 클러스터 밖 · **VirtualBox 위 Ubuntu 24.04** — 구 fb-ci-harbor 의 IP·인증서 승계, ✅ 가동).
  🔴 **호스트 C 는 VirtualBox 어댑터를 반드시 브리지 모드로** — NAT 면 `.10` 을 LAN 에서 못 받고, 클러스터 노드가 Harbor 에서 이미지를 못 당겨 **배포가 전면 실패**한다.
- **네트워킹**: Cilium(eBPF·kube-proxy 대체·WireGuard) · MetalLB L2(풀 `.14`–`.16` — **LB 는 게이트웨이 전용, 상시 2개**) · Gateway API(구현체 Istio) · **Istio sidecar 메시**(app ns 11 워크로드).
- **데이터 티어**: 전부 in-cluster·**전 컴포넌트 HA**(단 **MinIO 는 단일 replica·B 고정 — 문서화된 예외**) — PG(CloudNativePG) · ES(ECK — **인증 켬·HTTP TLS 끔**) · Redis(Sentinel) · Kafka(Strimzi RF=3) + PGSync. 스토리지 = OpenEBS LVM LocalPV(동적 프로비저닝, **RWX 금지**) · 오브젝트 = MinIO(내부) + S3(백업).
  *CNPG·ECK 의 "Cloud"는 cloud-native 를 뜻한다 — 클라우드 서비스가 아니라 우리 클러스터에 설치하는 오퍼레이터다. 매니지드로 갈아타지 않는다.*
- **CI/CD**: **Jenkins(CI, 호스트 C) → config 레포 `:sha` 커밋 → ArgoCD(CD)**. 상세·정본 = 아래 **§CI/CD 구조**. *(구 서술 "pollSCM 1분 · P2 전 자동 CD 없음"은 2026-08-02 정정 — Multibranch+웹훅이고 CD 는 자동이다.)*
- **배치 원칙**: 급사 3회가 전부 호스트 A → **master·quorum 다수·Prometheus·MinIO 는 B**, **PG·Redis primary 는 A**.
- **IaC 경계** — **Terraform = Proxmox(A·B) 전용 / Ansible = 호스트 C 포함 전체.** 호스트 C 는 VirtualBox 라 Terraform 밖이지만(VirtualBox 프로바이더 안 씀), **Ansible 은 SSH 만 닿으면 되므로 대상에 포함한다.** Harbor·Jenkins 를 손으로 올리면 그 머신이 죽었을 때 레지스트리 복구가 기억에 의존하게 되는데, 레지스트리는 클러스터 복구의 전제라 특히 아프다. → 호스트 C 재구축 = **수동 VM 생성 + Ansible**(이 한 스텝만 IaC 밖).
- **Terraform** = `infra/terraform/` — Proxmox VM 프로비저닝(`bpg/proxmox` · **템플릿 `9002`** 클론 — agent 사전설치본. `9001` 은 롤백용 원본). **state = S3 원격 backend**(`mp-backup-ap2` 버킷 · 잠금 = S3 네이티브 락파일 `use_lockfile`, DynamoDB 불요 · 자격증명 = `~/.aws` 프로필 `mp-backup`). *구 PG backend(fb-data `terraform_state` DB)는 **2026-07-29 폐기** — 그 PG 가 Terraform 이 관리하는 클러스터 위로 이사하면서 "인프라를 만드는 도구의 상태가 그 인프라 안에 있는" 순환 의존이 되기 때문. 근거 = `infra/terraform/backend.tf` 주석.* `terraform init -backend-config=backend.conf && terraform plan/apply`. 비밀 = `credentials.env`·`backend.conf`(**gitignored**).
- **Ansible** = `infra/ansible/` — 노드 베이스라인 + (현행) 서비스 배포. **멱등** · remote_user=`ubuntu`·become.
  `site.yml`(**`vms` 그룹 = 이제 호스트 C `.10` 단독** — `.8`·`.9`·`.11` 은 2026-07-31 P4 에서 파괴) · `hypervisor.yml`(**물리 `.12` 전용** — node-exporter 온도감시) · `ansible vms -m ping && ansible-playbook site.yml`(특정 롤 = `--tags <name>`).
  **존치 롤**(K8s 이후에도 씀) = `base`·`harbor`·`ca_trust`·`team_ssh_keys`·`node_exporter_host`·`monitoring_agents`(호스트 C 포함) + `jenkins`·`sonarqube`·`cloudflared`(CI 웹훅 터널)·`harbor_backup`·`jenkins_backup`(→ S3).
  🔴 **`k8s_platform_apps` 도 존치다** — LGTM Application 은 `platform-root`(ArgoCD)로 넘어갔지만 그 백엔드 자격증명(`lgtm-minio-creds`·`minio` 시크릿)은 **ArgoCD 미관리**라 이 롤이 유일한 공급원이다. ESO/config 로 이관하기 전에는 지우지 말 것.
  ~~**대체될 롤** = `data_tier`·`monitoring`·`data_pipeline`·`tfstate_db`~~ → **은퇴 완료**(2026-07-31 P4 — 롤·플레이 삭제. 승계처 = CNPG·ECK·Strimzi·Redis 오퍼레이터 / pipeline ns 워크로드 / kube-prometheus-stack+config 레포 `monitoring/`. `tfstate_db` 는 backend 가 S3 로 가면서 소멸). ~~`github_runner`~~ = **삭제 완료**(2026-07-31 P4 — 2026-07-27 플레이 제거의 유예를 끝냈다. 롤 디렉터리 + `group_vars/ci.yml` 변수 3종[`github_repo`·`runner_name`·`runner_labels`] + `secrets.yml.example` 의 `github_runner_pat` 까지 소거. 승계처 = `jenkins` 롤. 🔴 PAT 는 **GitHub 에서 revoke** 해야 실제로 끝난다 — 파일 삭제 ≠ 토큰 무효화). ~~`cd_deploy_key`~~ = **삭제 완료**(2026-07-31 P4 — 롤 + `infra/certs/deploy_key{,.pub}` + `certs/.gitignore` 규칙까지 폐기). 이 롤과 `.github/workflows/build-push-app.yml` 의 `deploy` 잡은 **같은 CD 경로의 양쪽 끝**이었다(키를 심는 쪽 / 쓰는 쪽) — 러너 은퇴·`.9` 파괴·CD 정본 ArgoCD 확정 **세 가지가 동시에** 무너져 함께 걷었다. 🔴 남은 조치 = GitHub 레포 시크릿 **`DEPLOY_SSH_KEY` 삭제**. ⚠️ ArgoCD 가 쓰는 `argocd_repo_ssh_key` 는 **완전히 별개**다(혼동 주의). 호스트 C 롤별 세부(포트·백업·함정)는 `docs/mp_k8s_infra_status.md §4.1`.
  🔴 **호스트 C 는 `[ci]` 그룹(= `vms` 자식)으로 관리한다** (2026-07-27 확정 — 구 "cicd 분리" 수칙 대체). base 롤은 VirtualBox 대응 완료(qemu-guest-agent 는 `ansible_virtualization_type` 으로 스킵), `docker_data_disk` 는 `group_vars/ci.yml` 에 명시돼 있다(`/dev/sdb`).
  🔴 **다만 그 값은 사실과 다르다 — 호스트 C 에 `/dev/sdb` 는 없다**(2026-07-31 실측: `sda` 100G 단일 = `sda1` 1M + `sda2` 100G `/`. `sr0` 는 CD-ROM). 즉 **`/var/lib/docker` 는 전용 디스크가 아니라 루트 파일시스템 위에 있다.** base 롤이 `stat` not-exists 로 조용히 스킵해서 무해했을 뿐, 종전 서술("호스트 C 전용 docker 디스크 실재")은 **틀렸다**.
  🔴 **이게 중요한 이유**: 단일 98GB 파일시스템(**여유 27.9GB**)에 OS·**Harbor 이미지 블롭**·`JENKINS_HOME`·SonarQube 데이터가 전부 얹혀 있다. 무언가 디스크를 채우면 **Harbor 가 죽고 클러스터 배포가 전면 실패**한다. 호스트 C 에 뭘 얹을지 판단할 때 **RAM(여유 6.6GB)이 아니라 디스크가 제약**이다 — 급사 증거 싱크를 Prometheus/Loki 가 아니라 평문 로그로 간 이유가 이것이다(§4.x).
  🔴 **site.yml 플레이는 `hosts: all` 이 아니라 `hosts: vms`** — `all` 은 인벤토리 전 호스트를 자동 포함해 하이퍼바이저까지 닿고, 그러면 `base` 롤이 `.12` 의 `/dev/sdb`(= 전 VM 스토리지 `pve` VG)를 docker 전용 디스크로 포맷 시도한다. 새 전-호스트 플레이를 추가할 때 `all` 로 쓰지 말 것(`base` 롤에 방어 assert 있음). 상세(3중 방어) = `docs/mp_k8s_infra_status.md §4.1 "하이퍼바이저"`.
- **팀 SSH 키 추가**: 공개키를 `infra/ansible/roles/team_ssh_keys/files/<이름>.pub`에 넣고 `ansible-playbook site.yml --tags team_keys` (**additive** — 기존 키 보존·잠금방지, 멱등).
- **비밀(전부 gitignored)**: `ansible/secrets.yml` · `terraform/credentials.env`·`backend.conf` · `infra/certs/*.key`(로컬 CA).
- **접속 정보** = `docs/mp_k8s_infra_status.md §4.0` (kubectl · 내부 도구 6종 `https://<이름>.mealbong.cloud` · 호스트 C SSH·Harbor 직결 · Proxmox 웹 UI A·B). **이관 완료 2026-07-31** — 구 `docker-infra-status.md §4` 의 VM 주소는 전부 죽었다.

## 로컬에서 작업하는 방법 — 🔴 코드는 로컬, 클러스터는 `ssh wsl-dev` 너머

> 2026-08-04 신설. 클러스터는 **작업용 컴퓨터의 LAN 안에만** 있다 — 개인 노트북에서 `kubectl` 이 직접 닿지 않는다.
> 그래서 **편집·테스트는 로컬 / 클러스터 조작은 SSH 경유**로 갈린다. 접속 정보 정본은 `docs/mp_k8s_infra_status.md §4.0`.

### 1. 코드 = 로컬 클론
클론 → 편집 → 테스트 → 브랜치 → **PR**.
🔴 **이 레포는 PR 리뷰 필수 — 직접 머지 금지.** (config 레포 `mealplanning-config` 는 직접 머지 허용 — 역할이 다르다, §CI/CD)

### 2. 클러스터 = `ssh wsl-dev '<명령>'`

```bash
ssh wsl-dev 'kubectl get pods -n app'
ssh wsl-dev 'kubectl -n argocd get applications'
ssh wsl-dev 'kubectl logs -n app deploy/mp-account --tail=100'
```

- `wsl-dev` = **각자 로컬 `~/.ssh/config` 에 두는 별칭**이다. 🔴 **이 레포는 공개(public)라 실주소·계정·포트를 커밋하지 않는다** — 값은 팀 내부 채널 / `docs/mp_k8s_infra_status.md §4.0` 에서 받는다.
  ```
  Host wsl-dev
    HostName <작업용 컴퓨터 주소>      # Tailscale 100.x 대역
    User <계정>
    Port <포트>
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
  ```
  키 등록은 `ssh-copy-id wsl-dev` **한 번**(그때만 비밀번호). 이후 무암호 = 비대화형 —
  스크립트·에이전트가 `ssh wsl-dev '...'` 를 돌리려면 이게 전제다(`BatchMode=yes` 로 확인).
- 🔴 **원격에 `argocd` CLI 는 없다.** ArgoCD 조작은 전부 kubectl 로 한다(수동 sync 명령 = §CI/CD "ArgoCD — 뿌리가 둘").
- 원격 작업용 컴퓨터에도 클론이 있다: `~/food-budget-app` · `~/mealplanning-config`.
  🔴 **로컬 클론과 별개다** — 편집·push 는 로컬에서, 원격 클론은 조회용. 양쪽에서 동시에 고치면 갈린다.

### 3. 로컬에서 앱 띄우기 — ⚠️ `dev-up.sh`·`dev-db.sh` 는 지금 그대로는 안 뜬다

두 스크립트의 기본값이 **`fb-data` VM `192.168.0.8`** 인데 그 VM 은 **P4(2026-07-31)에서 파괴**됐다.
(2026-08-04 실측: `.8:5432` = `No route to host`.) `dev-db.sh` 는 "WSL 에서 실행" 전제라 더더욱 옛 구조다.

현행 데이터 티어는 **인클러스터**다 — PG = `data/pg`(CNPG, 접속은 **`data/pg-pooler:5432`**) ·
ES = `data/es-es-http:9200` · Redis = `data/mp-redis:6379`.
로컬에서 붙이려면 **SSH 터널 + 원격 port-forward** 를 겹친다:

```bash
# 원격의 kubectl port-forward 를 로컬 5432 로 끌어온다
ssh -L 5432:localhost:5432 wsl-dev 'kubectl -n data port-forward svc/pg-pooler 5432:5432'
```

그 뒤 **환경변수로 덮어쓴다** — 두 스크립트 다 `${VAR:-기본값}` 이라 파일을 고칠 필요가 없다:
```bash
PGHOST=localhost ./dev-up.sh
```
🔴 자격증명은 커밋 금지 — CNPG 가 만든 시크릿에서 꺼내 쓴다.

### 4. 배포 확인
머지 후 흐름은 Jenkins → config 레포 → ArgoCD(§CI/CD). 반영 확인은 SSH 로:
```bash
ssh wsl-dev 'kubectl -n argocd get applications | grep -v Synced'   # 안 맞는 것만
ssh wsl-dev 'kubectl -n app get rollouts'
```

## CI/CD 구조 — 🔴 **CI 는 Jenkins 다. GH Actions 가 아니다.**

> 2026-08-02 기록. **이미 전부 구축·가동 중이다** — 웹훅·자격증명·ArgoCD 배선까지 끝나 있다.
> 새로 만들거나 다른 도구로 옮기지 말 것.

### 레포 2개 — 역할이 다르다

| 레포 | 담는 것 | CI |
|---|---|---|
| `happyInit/food-budget-app` (여기) | 앱 소스 · Dockerfile · `Jenkinsfile` · `infra/`(Terraform·Ansible) · `docs/` | **Jenkins** (루트 `Jenkinsfile`) |
| `happyInit/mealplanning-config` | K8s 매니페스트만 (desired state). ArgoCD 가 watch | **없음** — `python3 scripts/validate.py` 수동 |

config 레포 로컬 클론 = `/home/team6/mealplanning-config`. 🔴 **앱 소스는 거기 없다.**

### 흐름 — push 한 번이 배포까지 간다

```
GitHub push/PR
  └→ 웹훅 https://ci.mealbong.cloud/github-webhook/     (cloudflared 터널, 이 경로만 노출)
      └→ Jenkins Multibranch Pipeline (GitHub Branch Source 스캔)
          ├ 빌드 대상 결정 (변경 감지 · SERVICES 파라미터로 수동 지정 가능)
          ├ pytest 게이트   (카탈로그 `test:true` 10종만 · 실패 시 그 서비스 중단)
          │                 🔴 crawler-kurly 는 `reqs:''`·`cov:'.'` — requirements.txt 를 만들면
          │                    Dockerfile 인라인 핀과 진실이 둘이 된다(가드 테스트는 의존성 0)
          ├ SonarQube      (측정만 — 비차단)
          ├ docker build → Trivy 게이트 (CRITICAL·--ignore-unfixed · **차단**)
          ├ Harbor push    192.168.0.10/mealplanning/mp-<이름>:<sha> + :latest [+ :X.Y.Z]
          │                 앱 11종은 `mp-<서비스>-service`, 그 외는 접미사 없음
          │                 (mp-frontend · mp-ranking-serving · mp-pgsync · mp-data-pipeline
          │                  · mp-crawler-kurly · mp-elasticsearch-nori)
          └ config 레포 커밋  ← **CD 인계 지점**
              kustomize edit set image → services/<svc>/overlays/onprem 의 newTag=:sha
              credential 'config-repo-deploy-key' (SSH 쓰기키)
              🔴 `branch 'main'` 일 때만. PR 빌드는 CD 스킵(배포 금지)
                  └→ ArgoCD 가 config 레포를 보고 클러스터에 반영
```

- Jenkins 는 **컨테이너**로 돌고 호스트 docker.sock 을 쓴다. 소스가 필요한 도구 컨테이너는
  `docker run --rm --volumes-from jenkins -w "$WORKSPACE/…"` 로 워크스페이스를 물려받는다.
  그 컨테이너들은 **root 로 돌므로** 끝나고 `chown` 으로 소유권을 되돌린다(post 스테이지).
- `DOCKER_CONFIG` 를 워크스페이스로 격리한다 — 공유 `~/.docker/config.json` 이면 한 빌드의
  `docker logout` 이 다른 빌드의 세션을 지워 push 가 산발적으로 실패한다.
- `triggers` 블록은 **없다**(Multibranch 는 웹훅 스캔으로 뜬다). 구 `pollSCM` 은 단일 Pipeline 시절 것.

### ArgoCD — 뿌리가 둘

`mealplanning-root`(앱, `argocd/applications/`) · `platform-root`(플랫폼, `platform/argocd/`).
서로 남의 디렉터리를 안 봐서 한쪽 실수가 다른 트랙으로 안 번진다.

🔴 **auto-sync 여부가 앱마다 다르다** (2026-08-06 실측 — automated 30 / manual 16).
앱 서비스 13종(`mp-account`…`mp-video`)·오퍼레이터·root 2개·관측(alloy/loki/tempo)·kubecost
·`pipelines`·`mp-cloudflared`(뒤 둘은 2026-08-03 승격) 는 **automated**.
**manual 16개** = `app-common` · `gateway` · `gateway-internal` · `monitoring` ·
**`mp-ingress`**(공개 진입점 실체 — 2026-08-06 신설) ·
`mp-policies{,-data,-ingress,-observability,-pipeline}` · 데이터 CR 6종(`pg` `pooler` `es` `kafka` `redis` `pgsync`).
머지만으로 안 나가므로 수동 sync 가 필요하다:
```
kubectl patch application -n argocd <앱> --type merge -p '{"operation":{"sync":{"revision":"HEAD"}}}'
```
🔴 **`envFrom.configMapRef` 는 파드 기동 시점에 주입된다.** ConfigMap(`app-common`)을 바꾸고 sync 해도
도는 파드는 옛 값을 그대로 쓴다 → 해당 워크로드 `rollout restart` 가 별도로 필요하다.
체크섬 어노테이션이 없어 ArgoCD 가 자동으로 굴려주지 않는다(개선 후보).

### 🔴 GH Actions 는 죽어 있다 — 되살릴 수 없다

`.github/workflows/` 의 3개(`build-push-app`·`build-push-pipeline`·`ci-test`)는 전부
`runs-on: [self-hosted, fb-ci]` 인데 **러너가 은퇴(2026-07-27)·Ansible 롤까지 삭제(2026-07-31)** 됐다.
트리거도 `workflow_dispatch` 만 남겨 비활성화돼 있다. **파일은 Jenkins 이관 레퍼런스일 뿐이다.**

⚠️ **2026-08-02 실수 기록** — 이 구조를 모르고 config 레포에 GH Actions 워크플로를 추가한 적이 있다
(config#98 → config#100 으로 원복). 돌지 않는 껍데기였고, 남겨두면 "여긴 Actions 로 CI 한다"로 읽혀
CI 정본이 둘로 보인다. **config 레포에 `.github/` 를 만들지 말 것.**

## 스키마·서비스 정본 (SSOT — 2026-07-15 확정)
- **앱 OLTP 스키마 = `docs/prd/schema-production.md`** (적용 DDL `docs/prd/schema-production.sql`). ⚠️ `schema-app-oltp.md`는 참고 초안(superseded — **수정 X**). 데이터 티어 = `docs/prd/schema-public-data.sql`.
- **구조**: 스키마-퍼-서비스 하이브리드(단일 PG·role 격리·`data` 공유 읽기). FK 정책 — 크로스-서비스=논리 `bigint`값(JWT 신뢰) / 같은 스키마=진짜 FK / `data`=진짜 FK. 크로스-서비스 데이터는 **DB 조인 말고 API 호출**.
- **백엔드 서비스 코드 컨벤션 = `services/CONVENTIONS.md`**, 정본 레퍼런스 = **`services/account/`** (AppCtx 주입 seam · raw psycopg · DB-free 테스트).
- **도메인 용어집 = `CONTEXT.md`** (표준 품목·Gazetteer·소비기한·레시피북). 용어: ~~유통기한~~ → **소비기한**(2023 개정, docs 정렬 완료).
- **DB 접근 = psycopg3 + `row_factory=dict_row`** (2026-07-15 결정, ORM/Alembic 미사용). 마이그레이션 = 멱등 DDL(`schema-production.sql`). *(K8s 이전 후 CNPG 가 운용 — `docs/mp_k8s_infra_status.md §2.1`)*
- **이미지 태깅 = 3태그** (2026-07-16 확정, PR #97): `:<sha>`(불변 신원) + `:X.Y.Z`(릴리스 핀·불변) + `:latest`(가변 편의). **버전 태그 `:X.Y.Z`는 릴리스 런에서만** 빌드·push — 자동 `main` push 는 `:<sha>`+`:latest`만(불변성 + 부분빌드 landmine 회피). **앱·파이프라인은 별개 버전 트랙**(따로 올림). 내부 semver: **MAJOR**=마이그레이션급·계약파괴 / **MINOR**=하위호환 기능 / **PATCH**=버그픽스·설정.
  - **이 정책은 CI 구현체와 무관하게 유지된다** — 현행 구현 = **Jenkins `RELEASE_VERSION` 파라미터**(SERVICES 명시 강제·트랙 별칭 `app`/`pipeline`, 레포 루트 `Jenkinsfile`). GH Actions 는 비활성·보존(트리거 = `workflow_dispatch` 만). 🔴 단 **되살릴 수 없는 상태다** — 세 워크플로 전부 `runs-on: [self-hosted, fb-ci]` 인데 러너가 은퇴(2026-07-27)·롤까지 삭제(2026-07-31)됐다. 파일은 이관 레퍼런스일 뿐, 재활성화는 러너 재등록이 선행돼야 한다. **앱 트랙 = 신 Harbor `mealplanning/` 에서 `:1.1.9` 로 재시작**(2026-07-27, 파이프라인 트랙 1.1.10· 과 무관). K8s/config 레포 핀은 **`:sha`**(`:latest` 금지 — ArgoCD 감지·롤백 불가). 규칙 상세 = `docs/mp_k8s_infra_migration_plan.md §7.3~7.4`.

## 커스텀 AI (ChatGPT-moat, 전부 CPU)
- P0: 한식 재료 NER(CRF) · 최저가 알림(통계 이상탐지, ⚠️ baseline 4주→오탐↑)
- P1: 신선도 예측(XGBoost) · 레시피 랭킹(LightGBM)
- P2: 챗봇(의도분류+템플릿)
- 영양소 분석 = DB 룩업 (AI 아님)
- ~~드롭~~: 할인 주기 예측(LightGBM) — 8주로 할인 사이클 부족(예측 불가)

## 데이터소스
- 마켓컬리 (신선+가공, 현재가+경량 이력, 핵심 SKU 정기 폴링 일1~2회 + 롱테일 온디맨드) ⚠️ robots·ToS 회색지대
- 오아시스마켓 (신선+가공, 판매가+경량 이력, 카테고리 폴링 가격 일1~2회 + 딜 15/17시 + 롱테일 온디맨드) ⚠️ robots·ToS 회색지대
- 만개의레시피 크롤링 (레시피 DB, 주 1회)
- YouTube Data API + Gemini (유저 URL → 멀티모달 추출 → CRF NER, 온디맨드 · 유료 API 예외 승인)
- 유저 영수증 OCR (냉장고 재고 + 캘린더 식비)
- ⏸ 보류: 쿠팡 크롤 (robots+Akamai 블로커 → 마켓컬리로 대체)
- ❌ 드롭: 지마켓 타임딜(Cloudflare 차단 → 오아시스 타임/마감세일로 대체, design.md §3.3), 냉장고를부탁해(공식 구조화 0건 → 레시피=만개의레시피 단일, design.md §3.3), 도매시장 경락가, KAMIS, 식약처 COOKRCP01, 기상청, 온라인가격, 할인 예측·엥겔지수, ClickHouse(고볼륨 승격 시 재도입)

## 멘토 피드백 (2026-07 멘토링 지적사항)
- **정량적 데이터 근거 보강** — DAU·트래픽 추정치·저장량 등 숫자 기반 설계 필요
- **다자간(multi-party) 트래픽** — 최저가 알림 fan-out(마켓컬리 통제 소스) + 레시피북 공유
- **예측 가능한 트래픽 스파이크** — 일일 피크타임 (11-12시, 17-18시) 메인 / 명절 보조

## 작업 규칙 (중요)
- **문서 수정 전 물어보고, 확정된 것만 기록.** 내 추천을 결정처럼 쓰지 말 것.
- 학습 목적: 손으로 이해하며 — 완성품 덤프 X, 조각내 설명 먼저.
- 설계 결정: 숫자+근거로 종이 위에서. 실인프라 테스트 제안 X.

## 미정 (사용자 결정 대기 — 임의로 정하지 말 것)
- **5인 역할분담 + 9주 타임라인** — (K8s 이전은 **P3 까지 완료** — 남은 정합 대상 = P4 VM 해체·5노드 시점·owner 별 알림 채널 세분화)
- ~~**Redis 오퍼레이터 선정**~~ → ✅ **해소(2026-07-29 실측 4라운드)**: OT-Container-Kit 유지 + **이미지 v0.26.0** + **Sentinel 은 `RedisReplication.spec.sentinel` 인라인** + **클라이언트는 Sentinel-aware(분기 C)**. master **Service** 는 노드 상실 국면에서 갱신되지 않는다(오퍼레이터가 ordinal-0 고집) — 그래서 Service 가 아니라 Sentinel 을 본다. 근거 = `docs/mp_k8s_redis_ha_handoff.md §4`

> ✅ **해소됨**(임의 재논의 금지, 근거는 `docs/mp_k8s_infra_migration_plan.md`): CNI = **Cilium** · 서비스 메쉬 = **Istio sidecar**(ambient 기각) · Gateway API 구현체 = **Istio** · 외부 LB = **MetalLB**(Cilium LB IPAM 기각) · IP 풀 = `.14`–`.16` · 부트스트랩 = **kubeadm 직접**(Kubespray 기각) · 메트릭 = **Prometheus 유지**(Mimir 기각) · **Cilium 라우팅 모드 = VXLAN 확정·락**(2026-07-27 실측 — CPU 천장 2.25Gbps > 물리 1GbE 라 선이 먼저 찬다. 예상이던 native 를 뒤집음) + **2026-07-27 확정분**: 컷오버 = **앱 먼저 P0~P4** · CD = **ArgoCD 단독**(과도기 수동) · ESO 백엔드 = **K8s provider** · ES = **인증 켬+HTTP TLS 끔** · 관측 = **kube-prometheus-stack + metrics-server** · LB = **GW 전용 2개** · MinIO = **단일 replica 예외** · CronJob = **KST**(`spec.timeZone`) · P2 따라잡기 = **PG만 복제**(ES 재파생·Kafka 드레인).

## Agent skills

### Issue tracker

Issues live in GitHub Issues on `happyInit/food-budget-app` via the `gh` CLI; external PRs are **not** a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary — `needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

`docs/adr/`는 존재하며 현재 `0001-deployment-strategy-canary.md`가 카나리 배포전략 결정을 기록한다.
그 밖의 기존 결정은 계속 각 영역 정본 문서에 인라인으로 있다 — 인프라 결정·근거는
`docs/mp_k8s_infra_migration_plan.md`, 해소된 결정 목록은 이 문서 §인프라 하단의 "✅ 해소됨" 줄이다.
새 ADR을 만들거나 상태를 바꿀 때는 `docs/agents/domain.md`의 규칙과 기존 ADR 번호를 먼저 확인한다.
