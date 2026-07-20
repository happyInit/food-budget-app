# Git 브랜치 전략 — Docker 현행 → K8s 목표

> **성격 = 제안·정리.** Docker 시기의 **현행(as-is)**은 실제 관행·CI 기준으로 확정 기술하고, K8s 시기의 **목표(to-be)**는 옵션+추천을 제시한다. 최종 전략은 팀 결정(§10 역할분담·타임라인과 함께). 관련: 이미지 태깅 3태그(PR #97, CLAUDE.md) · 배포 토폴로지(design.md §8.4).

---

## 1. Docker 현행 (as-is) — GitHub Flow + squash merge

### 모델
**트렁크 = `main` 하나 + 짧은 수명 feature 브랜치.** 별도 `develop`/`release` 브랜치 없음(GitHub Flow).

### 브랜치 네이밍
| prefix | 용도 | 예 |
|---|---|---|
| `feat/` | 기능 추가 | `feat/ranking-popularity-promote` |
| `fix/` | 버그·QA 수정 | `fix/qa-batch-3-tail` |
| `docs/` | 문서 | `docs/design-perf-loadtest` |
| `chore/` | 설정·인프라·잡무 | `chore/…` |

### 흐름
```
main 최신화 → feat/* 브랜치 분기 → 작업·커밋 → PR(리뷰) → squash-merge → 브랜치 삭제
```
- **squash-merge**: PR 1건 = main 커밋 1개(선형 이력). ⚠️ squash라 브랜치가 main의 조상이 아니게 됨 → `git branch -d` 안 먹고 `git branch -D`로 삭제(정상).
- 커밋 컨벤션: `type(scope): 요약` (예: `perf: 부하테스트 병목 개선…`).

### 브랜치 ↔ 배포 결합 (핵심)
현행은 **`main` push = 곧 배포 트리거**. 별도 배포 브랜치 없음.

| 트리거 | CI(GH Actions) | 산출 이미지 | 배포 |
|---|---|---|---|
| `main` push (paths: `services/**`·`frontend/**`·`deploy/app/**`…) | `build-push-app.yml` | `:<sha>` + `:latest` | fb-app-ai compose가 `:latest` pull → **자동 반영** |
| `main` push (paths: `pipelines/**`·`crawler/**`…) | `build-push-pipeline.yml` | `:<sha>` + `:latest` | CD 없음 → fb-data operator가 `IMAGE_TAG` 지정 |
| **`workflow_dispatch`** (수동 릴리스) | app/pipeline 둘 다 | `:<sha>` + **`:X.Y.Z`** + `:latest` | 버전 태그로 핀 배포 |

- **이미지 태깅 = 3태그**(불변성): `:<sha>`(신원·불변) · `:X.Y.Z`(릴리스 핀·불변, **릴리스 런에서만**) · `:latest`(가변 편의). 버전 SoT = 워크플로우 `APP_VERSION` env.
- **환경 = 단일**(프로덕션 = fb-app-ai). staging 환경/브랜치 없음.

### 현행의 약점 (K8s 전환 시 개선 포인트)
- **PR 레벨 테스트 게이트 부재** — `ci-test.yml` 트리거가 좁아(자기 파일 path + 수동) PR·feature 브랜치에서 자동 안 돎. 품질 게이트가 리뷰어 수동에 의존.
- **단일 환경** — dev/prod 분리 없음 → `main` 머지가 곧 프로덕션. 리스크 큰 변경도 완충대 없음.
- **배포 = push 사이드이펙트** — 명시적 "배포" 행위가 아니라 이미지 갱신에 묶임(GitOps 아님).

---

## 2. K8s 목표 (to-be) — ArgoCD GitOps와 엮은 전략

K8s로 가면 **ArgoCD(GitOps)** 가 배포를 소유한다 → "브랜치 전략"의 실제 쟁점은 **"브랜치/이미지태그 ↔ 환경(dev/prod) 매핑을 어떻게 하느냐"**. 세 옵션.

| 옵션 | 방식 | 장점 | 단점 | 캡스톤 적합 |
|---|---|---|---|---|
| **① 트렁크 + GitOps 오버레이** ⭐ | `main` 유지. 배포상태 = config(Kustomize overlay `dev`/`prod`). ArgoCD가 오버레이 감시, 이미지태그 갱신으로 승격 | 현행 GitHub Flow 거의 그대로 · 3태그 전략 재사용(:latest→dev, :X.Y.Z→prod) · 롤백=git revert | config 위치(같은레포 `deploy/` vs 별도 config repo) 결정 필요 | ✅ 최적 |
| ② GitFlow | `main`/`develop`/`release/*`/`hotfix/*` | 정기 릴리스·병렬 개발에 견고 | 5인·8주엔 과함 · 브랜치 관리 비용↑ | △ 과함 |
| ③ 환경 브랜치 | `main`→`staging`→`production` 브랜치, ArgoCD가 브랜치별 감시 | 멘탈모델 단순(브랜치=환경) | 브랜치 간 머지 드리프트 · cherry-pick 지옥 위험 | △ |

### 추천 = 옵션 ① 트렁크 + GitOps 오버레이

**이유**: 현행 GitHub Flow·3태그 이미지 전략을 **깨지 않고** 승격만 GitOps로 승격. 학습 목표(ArgoCD 데모)도 자연스럽게 충족.

```
[코드]  feat/* → PR → squash-merge → main
                                     │  GH Actions: 이미지 빌드·push
                                     ▼
        main push        → :<sha> + :latest      ─┐
        workflow_dispatch → :<sha> + :X.Y.Z + :latest │
                                                      ▼
[배포]  config(Kustomize): overlays/dev  ← :latest (ArgoCD auto-sync, 자동)
                           overlays/prod ← :X.Y.Z (핀 · PR로 태그 bump = 승격)
                                     │  ArgoCD가 desired state 감시·동기화
                                     ▼
                    K8s (앱·AI·Kafka)  ※ PG/ES/Redis = 클러스터 밖(design.md §8.4 하이브리드)
```

**승격(promotion) = 프로덕션 오버레이의 이미지 태그를 `:X.Y.Z`로 올리는 PR 1개.** dev는 `:latest`로 자동 따라감(현행 compose `:latest` 자동배포와 동일 감각). 롤백 = 태그 되돌리는 `git revert`.

### 함께 정해야 할 것 (결정 대기)
- **config 위치**: 같은 레포 `deploy/k8s/`(단순, 앱↔배포 커플링) vs **별도 config repo**(GitOps 정석, 관심사 분리). → 캡스톤은 같은 레포 `deploy/k8s/overlays/{dev,prod}` 권장(운영 단순).
- **PR 테스트 게이트 도입**: K8s 전환 김에 `ci-test.yml`을 **PR 트리거**로 확장(현행 약점 해소). ArgoCD 배포 전제 = "main은 항상 green".
- **ArgoCD 패턴**: app-of-apps(서비스 11개 일괄 관리) + sync waves(DB 마이그레이션 → 앱 순서).
- **환경 수**: dev/prod 2개면 충분(§8.4 2노드 계획과 정렬). staging은 노드 여유 시.
- **DB 마이그레이션 게이트**: 앱 스키마(`schema-production.sql`)는 ArgoCD sync wave 0(preSync Job)로 멱등 적용 — 현행 "앱 스키마 수동 apply" 약점(activity.* 미적용 사례)도 이때 자동화.

---

## 3. 한눈에 — 무엇이 바뀌고 무엇이 유지되나

| | Docker 현행 | K8s 목표(추천 ①) |
|---|---|---|
| 브랜치 모델 | GitHub Flow (trunk + feat/*) | **그대로 유지** |
| 머지 | PR → squash → main | **그대로** |
| 이미지 태그 | 3태그(:sha·:X.Y.Z·:latest) | **그대로 재사용** |
| 배포 주체 | main push → compose `:latest` pull | ArgoCD(GitOps) auto-sync |
| 환경 | 단일(prod) | dev(:latest 자동) + prod(:X.Y.Z 핀 승격) |
| 승격 | (없음) | prod 오버레이 태그 bump PR |
| 롤백 | 이미지 태그 수동 | `git revert`(선언적) |
| 테스트 게이트 | 약함(수동) | PR 트리거로 강화(권장) |

> **결론**: 브랜치 전략 자체(GitHub Flow + squash)는 Docker→K8s 내내 **유지**. 바뀌는 건 "배포를 누가·어떻게 트리거하나"뿐 — push 사이드이펙트 → **GitOps 선언적 승격**. 이 방향이면 팀 재교육 비용 최소 + ArgoCD 학습목표 충족.
