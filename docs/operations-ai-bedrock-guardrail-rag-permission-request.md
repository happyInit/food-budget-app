# Operations AI 파트 AWS 권한 요청 — Bedrock Guardrails + RAG(직접구현)

요청자 `arn:aws:iam::689192361171:user/jeonghyeon` (Operations AI 파트) · 작성 2026-08-14 · 필요 시점 즉시

범위: 리소스 이름을 `mp-operations-*` 로 못박습니다. 다른 파트 리소스(AI·알림 파트의 `mp-ai-*`,
그 외 서비스)에는 닿지 않습니다.

## 0. 왜 지금 요청하는가

현재 `bedrock:InvokeModel`/`Converse`(RCA·챗봇용 Nova Micro 호출)는 이미 동작 중입니다
(로컬 Docker 컴포즈에서 실제 호출 검증 완료, 2026-08-14). 다음 두 가지를 이어서 만들려는데
각각 막힙니다.

1. **RCA가 근거 없는 내용을 지어내지 못하게 막는 안전장치(Guardrails)** — 지금은 코드
   프롬프트로만 "Evidence Package에 없는 내용은 답하지 말라"고 지시하고 있는데, 이건 모델이
   지시를 어겨도 걸러줄 방법이 없습니다. Bedrock Guardrails의 Contextual Grounding Check로
   전환하려면 Guardrail 리소스 생성 권한이 필요합니다.
2. **런북(장애 대응 문서) 기반 RAG** — 임베딩 모델 호출(`InvokeModel`)은 이미 되는 걸
   확인했지만(§3 참고), 임베딩 벡터를 저장할 곳이 필요합니다. Bedrock Knowledge Base 같은
   관리형 서비스가 아니라 **기존 psycopg 기반 코드 안에서 직접 구현**하기로 했습니다(§4의
   판단 근거 참고) — 이 방식이면 IAM 쪽에서 새로 받을 권한은 Guardrails 외에 없습니다.

## 1. 요약 — 두 덩어리입니다

| # | 무엇 | 어떻게 주면 되나 | 위험도 |
|---|---|---|---|
| ① | Bedrock Guardrails 관리 | 아래 §5 커스텀 정책 `mp-operations-bedrock-guardrail` 부착 | 🟢 낮음 (모델 호출 안전장치 추가일 뿐, 삭제/변경 리소스 없음) |
| ② | (참고) RAG용 신규 권한 | **없음** — 기존 `InvokeModel` 권한과 PG(psycopg) 접근만으로 구현 | — |

②는 요청할 게 없다는 걸 명시하기 위해 적어둡니다 — Knowledge Base·S3·OpenSearch Serverless·
IAM PassRole은 필요하지 않습니다(§4).

## 2. 권한별 사유 — 무엇을 하려고 필요한가

### ① Guardrails

| 권한 | 왜 필요한가 |
|---|---|
| `bedrock:CreateGuardrail` | RCA/챗봇용 Guardrail 정의 생성 — Contextual Grounding Check(응답이 넘겨준 Evidence Package 근거를 벗어나면 차단) + 유해 콘텐츠 필터 |
| `bedrock:UpdateGuardrail` | 그라운딩 임계값·필터 강도를 검증하며 조정 |
| `bedrock:GetGuardrail` | 현재 설정 조회 |
| `bedrock:ListGuardrails` | 목록 확인 |
| `bedrock:DeleteGuardrail` | 실험용으로 만들었다가 정리 |
| `bedrock:ApplyGuardrail` | 실제 RCA/챗봇 호출(`Converse`)에 Guardrail을 얹어서 씀 — 이게 없으면 Guardrail을 만들어도 호출 시 적용이 안 됨 |

비용: Guardrails는 상시 과금되는 인프라가 아니라 **호출량 기준 소액 종량제**입니다.
RCA/챗봇은 저빈도 호출(사용자가 조사를 시작할 때만)이라 월 청구액은 무시할 수준으로 예상됩니다.

### ② RAG — 왜 새 권한이 필요 없는가

- **벡터스토어**: Bedrock Knowledge Base(관리형, 기본 벡터스토어인 OpenSearch Serverless는
  상시 과금)를 검토했으나, 팀 예산 제약(학생 예산·상시과금 금지 원칙)과 맞지 않아 기각했습니다.
  대신 이미 Operations가 쓰고 있는 PostgreSQL 접근 방식(psycopg3, `docs`/CLAUDE.md 확정 원칙)
  그대로, 런북 텍스트와 임베딩 벡터를 일반 테이블에 저장하고 애플리케이션 코드(numpy)로
  코사인 유사도를 계산해 검색합니다. `pgvector` 같은 DB 확장도 필요 없어 `CREATE EXTENSION`
  권한 요구 자체가 없습니다.
- **임베딩 모델 호출**: `amazon.titan-embed-text-v2:0`을 실제로 `invoke_model`로 호출해
  성공을 확인했습니다(2026-08-14, 로컬 Docker에서 boto3 직접 테스트) — 이미 갖고 있는
  `bedrock:InvokeModel` 권한 범위 안에 있고, 모델 ARN을 제한하는 정책이 걸려 있지 않은
  것으로 보입니다. 추가 요청이 필요 없습니다.
- 따라서 S3(런북 원본 저장)·IAM PassRole·OpenSearch Serverless·Bedrock Knowledge Base 관련
  권한은 이번 요청에 포함하지 않습니다.

## 3. 검증 완료 사항 (요청 전 실측)

- `bedrock:InvokeModel`로 `apac.amazon.nova-micro-v1:0`(RCA/챗봇 응답 생성) 호출 성공 —
  로컬 Docker `operations-api` 컨테이너에서 실제 자유질문·mock/bedrock provider 전환까지 확인.
- `bedrock:InvokeModel`로 `amazon.titan-embed-text-v2:0`(RAG 임베딩) 호출 성공 — 별도 권한
  요청 없이 됨을 확인.
- 위 두 가지는 이미 되므로 이번 요청은 순수하게 Guardrails 리소스 관리 권한만 다룹니다.

## 4. 붙여넣을 정책 — `mp-operations-bedrock-guardrail`

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "GuardrailManage",
      "Effect": "Allow",
      "Action": [
        "bedrock:CreateGuardrail",
        "bedrock:CreateGuardrailVersion",
        "bedrock:UpdateGuardrail",
        "bedrock:GetGuardrail",
        "bedrock:DeleteGuardrail"
      ],
      "Resource": "arn:aws:bedrock:ap-northeast-2:689192361171:guardrail/*",
      "Condition": {
        "StringLike": {
          "aws:RequestTag/Name": "mp-operations-*"
        }
      }
    },
    {
      "Sid": "GuardrailList",
      "Effect": "Allow",
      "Action": "bedrock:ListGuardrails",
      "Resource": "*"
    },
    {
      "Sid": "GuardrailApply",
      "Effect": "Allow",
      "Action": "bedrock:ApplyGuardrail",
      "Resource": "arn:aws:bedrock:ap-northeast-2:689192361171:guardrail/*"
    }
  ]
}
```

주의: `CreateGuardrail`은 IAM 리소스 레벨 태그 조건을 요청 시점에 걸 수 없는 액션일 수 있어,
관리자가 부착할 때 `aws:RequestTag` 조건 지원 여부를 콘솔/CLI로 먼저 확인 부탁드립니다.
지원이 안 되면 `Resource: "arn:...:guardrail/*"`로 계정 전체 Guardrail에 대한 생성 권한이 되므로,
그 경우 Guardrail 이름 자체를 `mp-operations-*`로 짓는 것으로 범위를 대신 지키겠습니다.

## 5. 실행 역할(IAM Role) — 현재 상태와 남은 확인사항

Guardrails 자체는 Lambda처럼 별도 실행 역할이 필요한 리소스가 아닙니다 — 호출 주체가
이미 갖고 있는 `bedrock:*` 권한 경로에 `ApplyGuardrail`만 추가되면 됩니다.

다만 지금 로컬 검증은 개인 IAM 사용자(`user/jeonghyeon`)의 access key로 하고 있고,
**AWS 배포(EC2/EKS) 시 `operations-api`가 쓸 별도 IAM Role/Instance Profile은 아직
만들어지지 않은 것으로 확인됩니다.** boto3는 로컬 access key → EC2 Instance Profile로
코드 변경 없이 자동 전환되는 설계이므로(CLAUDE.md 확정 원칙), 이 Role은 이번 Guardrails
요청과 별개로 AWS 배포 준비 단계에서 한 번은 만들어야 합니다. 이번 요청 범위에는
포함하지 않고, 배포 착수 시점에 별도로 확인·요청하겠습니다.
