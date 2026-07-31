# 하이브리드 클라우드 계획 — 크로스클라우드 인증 연합
### AWS Bedrock(chat) + GCP Vertex AI(OCR·video) · 정적 키 0(keyless) · PoC 포함

> 작성: 건우(AI) · 2026-07-29 · 상태: **PoC 계획(미착수)** · 목표: 학습/포트폴리오 + 운영 정합
> 관련: `docs/ai-services-deploy-spec.md` · `docs/ai-model-region-hybrid-report.md` · `docs/mp_k8s_infra_migration_plan.md`(PR #300 Bedrock egress/인증) · `mp-ai-k8s-objects.html(로컬 설명본)`
> 원칙: 이 문서는 **설계·계획 수준**(무엇을·왜 설정하나)이며 CLI 런북이 아니다.

---

## 0. 요약 (TL;DR)

- **한 줄**: 하나의 **Kubernetes ServiceAccount 토큰(OIDC)** 을 신원 소스로, **AWS(IRSA/AssumeRoleWithWebIdentity)** 와 **GCP(Workload Identity Federation)** 가 각각 신뢰해 임시 자격을 발급 → **정적 키(AWS 액세스키·GCP SA 키 JSON) 0.**
- **모델 배치**: chat → **AWS Bedrock**(`nova-micro`, 서울) · OCR·video → **GCP Vertex AI**(Gemini). 모델 가용성이 자연히 가른 하이브리드(억지 아님).
- **핵심 성과**: 파드에 장기 비밀이 사라짐 · 두 클라우드 대칭 신원 연합 · 짧은 TTL 자동 갱신.
- **PoC**: P0(OCR→Vertex WIF) → P1(chat→Bedrock keyless) → P2(egress·관측·비용). 기존 경로는 fallback로 유지(비가역 마이그레이션 금지).

---

## 1. 배경 & 목표

### 1.1 왜 하이브리드인가 (근거)
- **모델 가용성이 클라우드를 가른다**: Claude/Nova = AWS Bedrock 전용, **Gemini = GCP(Vertex) 전용**. 실측으로도 Bedrock 네이티브(Nova)는 **한글 OCR 통짜 환각**, Vertex 네이티브(Gemini)는 성공 → 각 클라우드의 강점 모델을 쓰는 하이브리드가 **데이터로 정당화**됨(`ai-model-region-hybrid-report.md`).
- 따라서 "AWS로 통일"도 "GCP로 통일"도 불가 — **하이브리드는 선택이 아니라 귀결**.

### 1.2 목표 / 비목표
| 목표 | 비목표 |
|---|---|
| 정적 장기 키 제거(keyless) | 온프렘 폐기(계속 베이스로 유지) |
| 단일 k8s 신원 → 두 클라우드 연합 | 멀티클라우드 오토스케일/DR |
| 최소권한(모델 호출만) | 두 클라우드에 앱 전면 이중배포 |
| 학습·발표 가치(하이브리드 실증) | 프로덕션 SLA 보장(캡스톤 범위) |

### 1.3 학습 목표(발표에서 증명)
- 키리스 크로스클라우드 인증 연합(왕관 보석) · ESO/시크릿 축소 · 두 클라우드 egress 통제 · 클라우드별 관측·비용.

---

## 2. 현재 상태 (As-Is)

| 워크로드 | ns | 클라우드/모델 | 현 인증 | 문제 |
|---|---|---|---|---|
| chat(밥풀이) | app | Bedrock 이관 예정(`nova-micro`) | 온프렘=**AWS 액세스키**(ESO)→EKS=IRSA (PR #300) | 온프렘 구간 **정적 키** |
| OCR | app | Google AI API(`gemini-3.5-flash-lite`) | **API 키**(ESO) | 정적 키·글로벌(리전 제어 X) |
| video-recipe | ai | Google AI API(Gemini 영상) | **API 키** | 정적 키 |

→ **정적 키가 세 곳에 산재.** 목표는 이를 연합 신원으로 대체.

---

## 3. 목표 아키텍처 (To-Be)

### 3.1 원칙
1. **정적 키 0** — 모든 클라우드 자격은 STS 임시 토큰(짧은 TTL).
2. **단일 신원 소스** — k8s ServiceAccount projected token(OIDC).
3. **최소권한** — chat SA=`bedrock:InvokeModel`만 · ocr/video SA=`aiplatform.user`만.
4. **워크로드=SA=클라우드** 1:1 매핑(파드별 최소 신원).
5. **가역성** — 기존 키 경로를 플래그로 유지(카나리).

### 3.2 흐름
```
        ┌──────────── k8s (온프렘 또는 EKS) — OIDC IdP ────────────┐
        │  projected SA token 발급 (issuer + JWKS 공개, 짧은 TTL)    │
        └───────────────────────────────────────────────────────────┘
   SA:chat  (aud=sts.amazonaws.com)          SA:ocr / SA:video (aud=gcp-wif)
        │                                            │
        ▼ AssumeRoleWithWebIdentity                  ▼ 토큰 교환(external_account)
     AWS STS ─▶ 임시 AWS 자격 ─▶ Bedrock       GCP STS ─▶ 임시 GCP 토큰 ─▶ Vertex AI
                 (nova-micro, 서울)                        (Gemini, 서울/도쿄)
```

### 3.3 신원 매핑
| k8s SA (ns) | aud | 연합 대상 | 권한 | 목적 |
|---|---|---|---|---|
| `chat` (app) | `sts.amazonaws.com` | AWS IAM Role | `bedrock:InvokeModel`(+profile) | Bedrock 호출 |
| `ocr` (app) | GCP WIF provider | GCP 서비스계정 | `roles/aiplatform.user` | Vertex Gemini(vision) |
| `video-recipe` (ai) | GCP WIF provider | GCP 서비스계정 | `roles/aiplatform.user` | Vertex Gemini(영상) |

---

## 4. 전체 고려·설정 항목 (Comprehensive)

### 4.1 공통 — k8s를 OIDC 발급자로
| 설정 항목 | 내용 | 근거·주의 |
|---|---|---|
| Projected SA Token | `serviceAccountToken` 볼륨, audience 지정, TTL 짧게(≤1h) | 파드별 신원·자동 갱신 |
| OIDC discovery 공개 | `issuer` + `/.well-known/openid-configuration` + JWKS를 **공개 접근** | 클라우드 STS가 서명검증. **공개는 JWKS·메타만(비밀 아님)**, TLS 필수 |
| 발급자 신뢰 앵커 | 이 issuer URL이 AWS·GCP 양쪽 신뢰의 뿌리 | EKS=관리형 issuer / **온프렘=직접 노출(난이도↑)** |
| 시계 동기화 | 전 노드 NTP | 토큰 `exp` 검증 실패 방지 |

### 4.2 AWS 축 (chat → Bedrock)
| 설정 항목 | 내용 | 근거·주의 |
|---|---|---|
| IAM OIDC Identity Provider | 클러스터 issuer 등록 | 연합 신뢰 |
| IAM Role | trust=특정 SA+aud · 권한=`bedrock:InvokeModel`(+`aws-marketplace:*` **Claude 쓸 때만**) | chat=Nova라 marketplace 불필요 |
| 자격 소비 | 파드에 `AWS_ROLE_ARN`+`AWS_WEB_IDENTITY_TOKEN_FILE` → boto3 자동 `AssumeRoleWithWebIdentity` | EKS=IRSA 자동 · 온프렘도 동일 패턴 |
| 리전·프로필 | 서울 on-demand 불가 → **cross-region profile**(Claude=`global.`/Nova=`apac.`) | `ai-model-region-hybrid-report.md` |

### 4.3 GCP 축 (OCR·video → Vertex AI)
| 설정 항목 | 내용 | 근거·주의 |
|---|---|---|
| GCP 프로젝트·빌링 | 신규 프로젝트 + Vertex AI API 사용설정 | 3번째 클라우드 신설(비용·거버넌스) |
| Workload Identity Pool + OIDC Provider | provider=클러스터 issuer, allowed audience 지정 | 연합 신뢰 |
| GCP 서비스계정 | `roles/aiplatform.user` · `workloadIdentityUser`로 k8s SA subject 바인딩 | 최소권한 |
| 자격 소비 | **external_account credential config**(SA키 아님·토큰파일 포인터)를 `GOOGLE_APPLICATION_CREDENTIALS` | google-auth가 GCP STS 교환 |
| 모델 매핑 | `gemini-3.5-flash-lite` → Vertex 대응 모델 ID | 핀 규칙 유지·세대 재확인 |
| 리전 | 서울(asia-northeast3) 우선, **quota/403 대비 도쿄/글로벌 폴백** | `ai-model-region-hybrid-report.md` §Vertex |

### 4.4 네트워크 egress (Cilium FQDN)
| 파드 | 허용 FQDN | 주의 |
|---|---|---|
| chat | `bedrock-runtime.ap-northeast-2.amazonaws.com` · **`sts.amazonaws.com`** | STS 누락 시 토큰 교환 실패 |
| ocr·video | `*-aiplatform.googleapis.com` · **`sts.googleapis.com`** · `iamcredentials.googleapis.com` | STS·IAMCredentials 필수 |
| 공통 | CoreDNS(53) 예외 유지 | 정본 §6.1 |

### 4.5 시크릿·구성 (ESO 축소가 성과)
| 항목 | As-Is | To-Be |
|---|---|---|
| AWS 액세스키 | ESO Secret | **제거**(연합) |
| GCP SA 키 JSON | (도입 안 함) | **처음부터 없음**(연합) |
| Gemini API 키 | ESO Secret | **fallback로만 잔존**(카나리 종료 후 제거) |
| 남는 것 | — | role ARN·WIF provider 경로·credential config = **비밀 아닌 ConfigMap** |

### 4.6 관측·비용
| 항목 | 내용 |
|---|---|
| 트레이스 | 스팬에 `cloud=aws|gcp`·`model` 태그 → 크로스클라우드 호출 가시화 |
| 비용 | 클라우드별 분리 집계(현 `gemini-keys`/`bedrock-cred` 분리 정신 계승) · 월 예산 캡 유지 |
| 알림 | Vertex quota/429·Bedrock throttle 대시보드 |

### 4.7 보안·거버넌스
- **최소권한**: 각 SA는 자기 클라우드의 모델 호출 권한만. 크로스 금지.
- **audience 제한**: 토큰 aud를 클라우드별로 분리(재사용 방지).
- **짧은 TTL + 자동 갱신**: 유출 시 노출창 최소화.
- **온프렘 issuer 공개면**: JWKS만·TLS·경로 최소.
- **RBAC**: GCP WIF·IAM Role은 GitOps(ArgoCD/Terraform)로 선언 — 손수정 금지.

---

## 5. 기존 설계와의 정합 — 추가·개선·설정 변경점

### 5.1 변경(개선)
| 대상 | As-Is (기존 문서) | 변경 |
|---|---|---|
| Bedrock 인증 | "온프렘=access key(ESO)→EKS=IRSA" (PR #300) | **온프렘도 keyless**(AssumeRoleWithWebIdentity)로 승격 |
| OCR/video 인증 | Gemini API 키 | **Vertex + WIF**(keyless) |
| ESO 역할 | 다수 시크릿 동기화 | **시크릿 급감**(구성만 남음) |

### 5.2 신규 도입 (설정 필요)
- GCP: 프로젝트·빌링·Vertex API·Workload Identity Pool/Provider·서비스계정.
- AWS: IAM OIDC Provider·IAM Role(웹아이덴티티 trust).
- k8s: OIDC discovery 공개(온프렘)·projected token(aud별)·SA별 분리.
- Cilium: 두 클라우드 STS/엔드포인트 FQDN egress.
- 관측: cloud/model 태그 · 비용 분리.

### 5.3 인프라 담당과 협의 필요
- **OIDC issuer 공개 방식**(온프렘 API서버 노출 vs 정적 JWKS 호스팅 vs EKS 이관 후).
- Cilium FQDN 정책 추가.
- (별건) ranking-serving/ns 배치는 `mp-ai-k8s-objects.html(로컬 설명본)` 확정건과 함께.

### 5.4 k8s 마이그레이션 정합 — GCP가 이전에 편입된다 ★

기존 인프라 이전은 **온프렘 Proxmox k8s → EKS 이식성**(AWS 중심). 이 계획으로 **GCP가 3번째 기질로 그 이전에 편입**된다 — 마이그레이션 목표가 "온프렘→EKS(AWS)"에서 **"온프렘→EKS(AWS) + GCP"** 로 확장된다. 이전 계획에 다음이 추가된다:

| 영역 | 기존(AWS 중심 이전) | GCP 편입으로 추가 |
|---|---|---|
| IaC(Terraform) | AWS·온프렘 리소스 | **GCP provider**: 프로젝트·WIF pool/provider·서비스계정·IAM 바인딩 |
| GitOps(ArgoCD) | k8s 매니페스트 | external_account config·SA·federated 워크로드 선언 |
| 오버레이 | `onprem`/`eks` | (선택) GCP 값 오버레이 |
| 네트워크 | 내부·AWS egress | **GCP egress**(Vertex·`sts.googleapis.com`·`iamcredentials`) |
| 빌링·거버넌스 | AWS 크레딧 | **GCP 프로젝트 빌링·예산 알림·Vertex quota** |
| 신원 | AWS IRSA(계획) | **동일 OIDC issuer를 GCP WIF도 소비**(핵심 재사용) |

**🔴 OIDC issuer = 두 클라우드 공유 임계 의존(신규 SPOF) — 이전 단계와 직결**
- **온프렘 유지 시**: API서버 **OIDC discovery(issuer+JWKS)를 공개 노출**해야 함(MetalLB LB+TLS 또는 JWKS를 정적 오브젝트로 호스팅). → **P0의 실질 선행작업**이자 난제.
- **EKS 이관 시**: **EKS 관리형 OIDC issuer 하나가 AWS IRSA + GCP WIF 둘 다의 앵커** → 턴키.
- ⇒ **연합 난이도가 k8s 이전 단계에 직결**(온프렘=어려움, EKS=쉬움) → **issuer 공개 시점이 곧 이 PoC의 시작점**.
- issuer/JWKS 다운 = **두 클라우드 인증 동시 마비** → 가용성(HA·캐시)·degraded fallback 필수.

### 5.5 추가로 설정·고려할 항목 (보강)

| 항목 | 내용 |
|---|---|
| **Istio egress** | 외부 호출(STS·Bedrock·Vertex)이 사이드카를 지남 → **Istio ServiceEntry/egress + Cilium FQDN 둘 다** 정합(하나만이면 막힘) |
| **정책 강제(keyless 증명)** | **Kyverno/OPA**로 "정적 클라우드 키 Secret 금지" 정책 → 키리스를 선언적으로 보증(발표 근거) |
| **GCP 비용 거버넌스** | 예산 알림·Vertex quota 모니터 — AWS 월 예산 캡과 대칭 |
| **데이터 레지던시** | 영수증=개인정보 → Vertex 리전(서울/도쿄) 선택이 **이전의 데이터 posture**와 연결 |
| **AWS 신원 방식** | IRSA 또는 **EKS Pod Identity**(신형) 택1 |
| **degraded fallback** | issuer 다운·연합 실패 시 기존 키 경로로 **플래그 강등** → 서비스 지속 |

---

## 6. PoC 계획

### 6.1 목표 & 성공기준
- **목표**: "정적 키 0으로 두 클라우드 모델 호출"을 실증.
- **성공기준**: ① 파드에 static key 없음(검증) ② OCR이 Vertex 호출 성공(WIF) ③ chat이 Bedrock 호출 성공(웹아이덴티티) ④ 토큰 만료 후 자동 재발급 확인.

### 6.2 단계
| 단계 | 범위 | 산출물 | 검증 |
|---|---|---|---|
| **P0** | **OCR 한 파드만** GCP WIF 연동(Vertex 호출) | WIF pool/provider·GCP SA·external_account config·OCR 배포 | Vertex 실호출 + `GOOGLE_APPLICATION_CREDENTIALS`에 키 없음 |
| **P1** | **chat** AssumeRoleWithWebIdentity로 keyless 전환 | IAM OIDC provider·IAM Role·projected token(aud=aws) | Bedrock 실호출 + access key 부재 |
| **P2** | egress 정책·관측(cloud 태그)·비용 분리·video-recipe 편입 | Cilium CNP·대시보드 | egress 통제 확인·트레이스 크로스클라우드 |
| 상시 | 기존 키 경로 **flag fallback** | 플래그·롤백 절차 | 카나리 되돌림 성공 |

### 6.3 학습 증명 데모(발표)
- `kubectl exec`로 파드 env·볼륨에 **정적 키 없음** 시연.
- 토큰 강제만료 → 자동 갱신 → 호출 지속.
- 하나의 SA 신원이 두 클라우드에 연합되는 구조 설명.

### 6.4 가드레일
- **타임박스**(예: 1~2주) · **비용 캡**(Vertex/Bedrock 소액) · **카나리·롤백** · 기존 경로 상시 유지.

---

## 7. 리스크 & 완화
| 리스크 | 완화 |
|---|---|
| 온프렘 OIDC issuer 공개 난이도 | JWKS만·TLS / 어려우면 **EKS 이관 후 P1** |
| 서울 Vertex quota/403 | 도쿄/글로벌 리전 폴백 설계 |
| 토큰 exp 실패(시계) | 전 노드 NTP |
| STS FQDN 누락 → 인증 실패 | egress 체크리스트에 STS 포함 |
| 3번째 클라우드 운영부담 | PoC 범위 최소화·타임박스·기존 경로 fallback |
| Claude 쓸 경우 marketplace 권한 | chat=Nova로 회피(필요 시 별도 승인) |

---

## 8. 결정 필요 (Open Questions)
1. **OIDC issuer 공개 시점** — 온프렘 지금 vs EKS 이관 후.
2. **Vertex 리전** — 서울(레지던시) vs 도쿄(안정) vs 글로벌.
3. **GCP 크레딧/빌링** — 신규 프로젝트 비용 주체.
4. **PoC 범위** — P0만(학습 핵심) vs P0~P2 전체.
5. **video-recipe 편입 시점** — 착수(2026-07-24) 진행도에 맞춤.

---

## 9. 용어·참조
- **OIDC projected token**: k8s가 파드에 발급하는 짧은 수명 JWT(신원).
- **IRSA / AssumeRoleWithWebIdentity**: k8s OIDC → AWS IAM Role 임시자격(키리스).
- **Workload Identity Federation(WIF)**: 외부 OIDC → GCP 서비스계정 임시자격(키리스).
- **external_account**: GCP 자격이 SA키가 아니라 외부 토큰을 가리키는 구성.
- 참조: `docs/ai-model-region-hybrid-report.md` · `docs/ai-services-deploy-spec.md` · `docs/mp_k8s_infra_migration_plan.md`(§6 egress·PR #300) · `mp-ai-k8s-objects.html(로컬 설명본)`
