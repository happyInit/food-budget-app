#!/usr/bin/env bash
# mp-ai 서버리스·AI 프로젝트 IAM — 생성/갱신 (멱등)
#
# 🔴 이 스택은 Terraform 이 아니다. 사람·수동 IAM 이 이미 그렇게 관리되고 있고
#    (`mealplanning-dev` 그룹·사용자 4명은 콘솔 생성), 여기만 IaC 로 끌어오면
#    "정본이 둘"이 된다. 대신 **정책 문서를 레포에 두고 이 스크립트로만 적용**한다.
#    ⇒ 누가 무엇을 줬는지는 git 이 답한다.
#
# 🔴 계정 ID 는 파일에 `${ACCOUNT_ID}` 로 두고 여기서 채운다 — 이 레포는 공개다.
set -euo pipefail
export AWS_PROFILE=${AWS_PROFILE:-mp-platform}
export AWS_PAGER=""
cd "$(dirname "$0")"

MEMBERS=${MEMBERS:-"geonu jeonghyeon"}   # 🔴 서버리스·AI 담당자만. 4명 전원 그룹에 붙이지 말 것
GROUP=mealplanning-ai
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

echo "① 정책 3종 생성/갱신 (계정 ${ACCOUNT_ID})"
for p in mp-ai-boundary mp-ai-dev mp-ai-guardrails; do
  sed "s/\${ACCOUNT_ID}/${ACCOUNT_ID}/g" "$p.json" > "$TMP/$p.json"
  ARN="arn:aws:iam::${ACCOUNT_ID}:policy/$p"
  if aws iam get-policy --policy-arn "$ARN" >/dev/null 2>&1; then
    # 🔴 버전은 5개가 상한이다 — 가장 오래된 비기본 버전을 지우고 넣는다.
    OLD=$(aws iam list-policy-versions --policy-arn "$ARN" \
      --query 'Versions[?!IsDefaultVersion]|[-1].VersionId' --output text)
    [ "$OLD" != "None" ] && [ "$(aws iam list-policy-versions --policy-arn "$ARN" \
      --query 'length(Versions)' --output text)" -ge 5 ] &&
      aws iam delete-policy-version --policy-arn "$ARN" --version-id "$OLD"
    aws iam create-policy-version --policy-arn "$ARN" \
      --policy-document "file://$TMP/$p.json" --set-as-default --query 'PolicyVersion.VersionId' --output text
  else
    aws iam create-policy --policy-name "$p" --policy-document "file://$TMP/$p.json" \
      --description "mp-ai 서버리스·AI 프로젝트" --query 'Policy.Arn' --output text
  fi
done

echo "② 그룹 + 부착"
aws iam get-group --group-name "$GROUP" >/dev/null 2>&1 || \
  aws iam create-group --group-name "$GROUP" --query 'Group.GroupName' --output text
# 🔴 경계(`mp-ai-boundary`)는 그룹에 붙이지 않는다 — 그건 실행 역할의 천장이지 사람 권한이 아니다.
for p in mp-ai-dev mp-ai-guardrails; do
  aws iam attach-group-policy --group-name "$GROUP" --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/$p"
done

echo "③ 사람"
for u in $MEMBERS; do
  aws iam add-user-to-group --group-name "$GROUP" --user-name "$u" && echo "   + $u"
done

echo "④ 검증 — 되어야 하는 것 / 막혀야 하는 것"
U="arn:aws:iam::${ACCOUNT_ID}:user/$(echo $MEMBERS | awk '{print $1}')"
chk() { printf '   %-46s %s\n' "$2" "$(aws iam simulate-principal-policy \
  --policy-source-arn "$U" --action-names "$1" ${3:+--resource-arns "$3"} ${4:+--context-entries "$4"} \
  --query 'EvaluationResults[0].EvalDecision' --output text)"; }
A=$ACCOUNT_ID
echo "  ── allowed 여야 ──"
chk lambda:CreateFunction   "Lambda mp-ai-*"        "arn:aws:lambda:ap-northeast-2:$A:function:mp-ai-x"
chk bedrock:InvokeModel     "Bedrock"
chk eks:DescribeCluster     "kubectl 용 (필수 유지)"
chk ecr:DescribeImages      "운영 이미지 조회"       "arn:aws:ecr:ap-northeast-2:$A:repository/mealplanning/mp-chat-service"
chk iam:PassRole            "PassRole → lambda"     "arn:aws:iam::$A:role/mp-ai-w" 'ContextKeyName=iam:PassedToService,ContextKeyValues=lambda.amazonaws.com,ContextKeyType=string'
chk ec2:CreateSecurityGroup "SG 생성 (태그 있음)"   "" 'ContextKeyName=aws:RequestTag/Project,ContextKeyValues=mp-ai,ContextKeyType=string'
echo "  ── Deny 여야 ──"
chk lambda:CreateFunction   "Lambda mp-chat"        "arn:aws:lambda:ap-northeast-2:$A:function:mp-chat"
chk eks:DeleteCluster       "클러스터 삭제"
chk iam:CreateUser          "IAM 사용자 생성"
chk iam:CreateRole          "경계 없이 역할 생성"   "arn:aws:iam::$A:role/mp-ai-x"
chk ecr:PutImage            "운영 이미지 push"       "arn:aws:ecr:ap-northeast-2:$A:repository/mealplanning/mp-chat-service"
chk ec2:CreateSecurityGroup "SG 생성 (태그 없음)"
chk s3:GetObject            "백업 버킷"              "arn:aws:s3:::mp-backup-ap2/x"
