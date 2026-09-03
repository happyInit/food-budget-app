#!/usr/bin/env bash
# 포트폴리오 스택 스모크 검증 — DNS 전환 전에 이게 전부 통과해야 한다.
#
#   ./smoke.sh                       # 호스트 내부(프론트 :8080)
#   ./smoke.sh https://portfolio.mealbong.cloud   # 터널 경유
set -uo pipefail
cd "$(dirname "$0")"
BASE="${1:-http://localhost:8080}"
PASS=0; FAIL=0
chk() { # 이름 기대코드 경로 [grep패턴]
  local name="$1" want="$2" path="$3" pat="${4:-}"
  local body code
  body=$(curl -s -m 15 -w $'\n%{http_code}' "$BASE$path" 2>/dev/null)
  code="${body##*$'\n'}"; body="${body%$'\n'*}"
  if [ "$code" != "$want" ]; then
    printf "  FAIL %-34s 기대 %s / 실제 %s\n" "$name" "$want" "$code"; FAIL=$((FAIL+1)); return
  fi
  if [ -n "$pat" ] && ! printf '%s' "$body" | grep -q "$pat"; then
    printf "  FAIL %-34s 응답에 '%s' 없음: %.90s\n" "$name" "$pat" "$body"; FAIL=$((FAIL+1)); return
  fi
  printf "  ok   %-34s %s\n" "$name" "$code"; PASS=$((PASS+1))
}

echo "== 대상: $BASE =="
chk "프론트 로드"            200 "/"                                    "<div id=\"root\""
chk "레시피 검색(ES)"        200 "/api/recipes?q=%EA%B9%80%EC%B9%98"    '"recipes"'
chk "레시피 필터(cooking_time)" 200 "/api/recipes?cooking_time=30%EB%B6%84%EC%9D%B4%EB%82%B4" '"recipes"'
chk "공유 레시피 카탈로그"    200 "/api/recipes/shared"                  ""
chk "핫딜"                   200 "/api/prices/hotdeals"                 ""
chk "시세 추천"              200 "/api/prices/recommend"                ""
chk "인증 필요(내 프로필)"   401 "/api/users/me"                        ""
chk "인증 필요(알림함)"      401 "/api/notifications"                   ""
chk "인증 필요(냉장고)"      401 "/api/pantry/items"                    ""
chk "인증 필요(장바구니)"    401 "/api/mealplan/cart"                   ""
chk "OCR 잡 조회(미존재)"    404 "/api/pantry/ocr/nonexistent"          ""
chk "영상 추출 조회(미존재)" 404 "/api/recipes/extract/nonexistent"     ""
chk "챗 GET 불가(POST 전용)" 405 "/api/mealplan/assistant/chat"         ""

echo
echo "  통과 $PASS · 실패 $FAIL"
[ "$FAIL" -eq 0 ] || exit 1
