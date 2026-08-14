#!/usr/bin/env bash
# 대시보드 EC2 트랙 IAM — 생성/갱신 (멱등)
#
# 🔴 이 스택은 Terraform 이 아니다. 사람·수동 IAM 이 이미 그렇게 관리되고 있어
#    (`mealplanning-dev`·`mealplanning-ai` 그룹은 콘솔 생성) 여기만 IaC 로 끌어오면 정본이 둘이 된다.
#    `infra/iam/mp-ai/apply.sh` 와 같은 방식 — 정책 문서를 레포에 두고 이 스크립트로만 적용한다.
#
# 🔴 계정 ID·서브넷·VPC 는 파일에 `${...}` 로 두고 여기서 채운다 — 이 레포는 공개다.
#    서브넷·VPC 는 **Name 태그로 조회**한다. ID 를 박아두면 재생성 때 조용히 어긋난다.
#
# ── 이 스크립트가 만드는 울타리 ────────────────────────────────────────────────
#   ① 서브넷   `RunInstances` Allow 의 subnet ARN 이 하나뿐 → 다른 서브넷엔 못 띄운다
#   ② VPC      SG 조작은 `ec2:Vpc` 조건으로 service VPC 안에서만
#   ③ 태그     `Component=finops-dashboard` 없이는 인스턴스를 못 만들고, 만든 뒤에도 못 만진다
#   ④ 이름     IAM 역할·인스턴스 프로파일은 `mp-dashboard-*` 만, 그것도 경계 정책 필수
#   🔴 ①만으로는 울타리가 안 된다 — EIP·IAM·SSM·S3·Secrets 에는 서브넷 개념 자체가 없다.
#
# ── 🔴 정현(jeonghyeon) 처리 ──────────────────────────────────────────────────
#   `mp-ai-guardrails` 가 `ec2:RunInstances`·SG·`mp-backup-ap2` 를 **explicitDeny** 하므로,
#   그 그룹에 남아 있는 한 여기서 Allow 를 아무리 붙여도 안 열린다(Deny 가 항상 이긴다).
#   ⇒ `mealplanning-ai` 그룹에서 빼고 `mp-ai-dev` 를 user 에 직접 붙여 AI 트랙 권한은 유지한다.
#     (정은의 `mp-finops-dev` 가 이미 같은 형태다 — 사람마다 다른 정책은 user 직부착)
#   그 대가로 사라지는 `mp-ai-guardrails` 의 보호는 `mp-dashboard-guardrails` 가 대신 받는다.
#   🔴 단 완전히 같지는 않다 — mp-ai 쪽 `Project=mp-ai` SG 태그 강제는 여기 없다.
set -euo pipefail
export AWS_PROFILE=${AWS_PROFILE:-mp-platform}
export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION:-ap-northeast-2}
export AWS_PAGER=""
cd "$(dirname "$0")"

MEMBERS=${MEMBERS:-"jungeun jeonghyeon"}
GROUP=mealplanning-dashboard
SUBNET_NAME=${SUBNET_NAME:-mp-subnet-public-ap-northeast-2a}
VPC_NAME=${VPC_NAME:-mp-vpc-service}
# 🔴 대시보드 스택 state 는 `mp-backup-ap2` 와 **다른 버킷**이어야 한다.
#    같은 버킷이면 guardrails 의 `DenyProtectedBuckets` 와 충돌해 둘 중 하나를 포기하게 된다
#    (백업 버킷을 열거나, state 를 못 쓰거나). 스택을 쪼개면 그 선택 자체가 사라진다.
STATE_BUCKET=${STATE_BUCKET:-mp-dashboard-tfstate-ap2}

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
SUBNET_ID=$(aws ec2 describe-subnets --filters "Name=tag:Name,Values=$SUBNET_NAME" \
  --query 'Subnets[0].SubnetId' --output text)
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=tag:Name,Values=$VPC_NAME" \
  --query 'Vpcs[0].VpcId' --output text)
[ "$SUBNET_ID" = "None" ] && { echo "서브넷 '$SUBNET_NAME' 없음"; exit 1; }
[ "$VPC_ID" = "None" ] && { echo "VPC '$VPC_NAME' 없음"; exit 1; }
echo "계정 $ACCOUNT_ID · 서브넷 $SUBNET_ID · VPC $VPC_ID · state 버킷 $STATE_BUCKET"

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
fill() { sed -e "s/\${ACCOUNT_ID}/${ACCOUNT_ID}/g" \
             -e "s/\${DASHBOARD_SUBNET_ID}/${SUBNET_ID}/g" \
             -e "s/\${SERVICE_VPC_ID}/${VPC_ID}/g" \
             -e "s/\${STATE_BUCKET}/${STATE_BUCKET}/g" "$1"; }

# 🔴 dev/ops 를 쪼갠 이유는 취향이 아니라 **관리형 정책 상한 6144자**다(공백은 안 세므로
#    들여쓰기를 지워도 안 줄어든다). dev = 인프라를 만드는 권한 / ops = 그 위에서 일하는 권한.
#    나중에 문장을 추가할 때 어느 쪽이 상한에 가까운지 먼저 재고 넣을 것.
echo "① 정책 4종 생성/갱신"
for p in mp-dashboard-boundary mp-dashboard-dev mp-dashboard-ops mp-dashboard-guardrails; do
  fill "$p.json" > "$TMP/$p.json"
  python3 -m json.tool "$TMP/$p.json" >/dev/null   # 문법 사고를 apply 전에 잡는다
  ARN="arn:aws:iam::${ACCOUNT_ID}:policy/$p"
  if aws iam get-policy --policy-arn "$ARN" >/dev/null 2>&1; then
    # 🔴 버전 상한이 5다 — 가장 오래된 비기본 버전을 지우고 넣는다.
    if [ "$(aws iam list-policy-versions --policy-arn "$ARN" --query 'length(Versions)' --output text)" -ge 5 ]; then
      OLD=$(aws iam list-policy-versions --policy-arn "$ARN" \
        --query 'Versions[?!IsDefaultVersion]|[-1].VersionId' --output text)
      aws iam delete-policy-version --policy-arn "$ARN" --version-id "$OLD"
    fi
    aws iam create-policy-version --policy-arn "$ARN" --policy-document "file://$TMP/$p.json" \
      --set-as-default --query 'PolicyVersion.VersionId' --output text
  else
    aws iam create-policy --policy-name "$p" --policy-document "file://$TMP/$p.json" \
      --description "대시보드 EC2 트랙 (Operations AI + FinOps 공용)" --query 'Policy.Arn' --output text
  fi
done

echo "② 그룹 + 부착"
aws iam get-group --group-name "$GROUP" >/dev/null 2>&1 || \
  aws iam create-group --group-name "$GROUP" --query 'Group.GroupName' --output text
# 🔴 경계(`mp-dashboard-boundary`)는 그룹에 붙이지 않는다 — 그건 인스턴스 역할의 천장이지 사람 권한이 아니다.
for p in mp-dashboard-dev mp-dashboard-ops mp-dashboard-guardrails; do
  aws iam attach-group-policy --group-name "$GROUP" --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/$p"
done

echo "③ 사람"
for u in $MEMBERS; do
  aws iam add-user-to-group --group-name "$GROUP" --user-name "$u" && echo "   + $u"
done

echo "④ 🔴 정현 — mealplanning-ai 탈퇴 + mp-ai-dev 직부착 (Deny 제거)"
if aws iam get-group --group-name mealplanning-ai --query 'Users[].UserName' --output text | grep -qw jeonghyeon; then
  aws iam attach-user-policy --user-name jeonghyeon \
    --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/mp-ai-dev"      # 먼저 붙이고
  aws iam remove-user-from-group --group-name mealplanning-ai --user-name jeonghyeon  # 그 다음 뗀다
  echo "   jeonghyeon: mealplanning-ai 탈퇴 · mp-ai-dev 직부착"
else
  echo "   (이미 처리됨)"
fi

echo "⑤ 검증 — 되어야 하는 것 / 막혀야 하는 것"
A=$ACCOUNT_ID
chk() { printf '   %-44s %-11s %s\n' "$3" "$(aws iam simulate-principal-policy \
  --policy-source-arn "arn:aws:iam::$A:user/$1" --action-names "$2" \
  ${4:+--resource-arns "$4"} ${5:+--context-entries "$5"} \
  --query 'EvaluationResults[0].EvalDecision' --output text)" "($1)"; }
for u in $MEMBERS; do
  echo "  ── $u : allowed 여야 ──"
  chk "$u" ec2:RunInstances       "그 서브넷에 인스턴스" "arn:aws:ec2:ap-northeast-2:$A:subnet/$SUBNET_ID"
  chk "$u" ssm:StartSession       "대시보드 셸" "arn:aws:ec2:ap-northeast-2:$A:instance/i-0test" \
      'ContextKeyName=ssm:resourceTag/Component,ContextKeyValues=finops-dashboard,ContextKeyType=string'
  chk "$u" s3:PutObject           "TF state (락파일)" "arn:aws:s3:::$STATE_BUCKET/tfstate/dashboard.tfstate"
  chk "$u" iam:PassRole           "인스턴스 롤 넘기기" "arn:aws:iam::$A:role/mp-dashboard-ec2" \
      'ContextKeyName=iam:PassedToService,ContextKeyValues=ec2.amazonaws.com,ContextKeyType=string'
  chk "$u" eks:DescribeCluster    "kubectl 용 (필수 유지)"
  echo "  ── $u : Deny 여야 ──"
  chk "$u" ec2:RunInstances       "다른 서브넷" "arn:aws:ec2:ap-northeast-2:$A:subnet/subnet-0000000000000dead"
  chk "$u" ssm:StartSession       "EKS 노드 셸" "arn:aws:ec2:ap-northeast-2:$A:instance/i-0test" \
      'ContextKeyName=ssm:resourceTag/Name,ContextKeyValues=mp-eks-node,ContextKeyType=string'
  chk "$u" eks:DeleteCluster      "클러스터 삭제"
  chk "$u" s3:GetObject           "백업 버킷" "arn:aws:s3:::mp-backup-ap2/x"
  chk "$u" iam:CreateUser         "IAM 사용자 생성"
  chk "$u" ecr:PutImage           "운영 이미지 push" "arn:aws:ecr:ap-northeast-2:$A:repository/mealplanning/mp-chat-service"
done
