# 챗봇 비선호 ↔ 마이 페이지 제외재료 — 양방향 연동 (핸드오프)

> **작성:** 건우(AI) · **수신:** 백엔드(account) · 인프라(인증/Gateway) · 제품(동의)
> **상태:** **챗봇 측 코드 완료(flag OFF)** · account API 완료 · **블로커 = 인증(JWT)** 하나
> **관련:** `chat-conversation-data-plan.md`(개인화 P1) · `services/account`(제외재료 API) · `services/chat`(연동)

## 1. 무엇
챗봇 세션 개인화("돼지고기 빼줘")와 **마이 페이지 영속 제외재료**(`account.user_excluded_item`)를 **양방향 동기화**:
- **READ**: 마이 페이지 제외재료 → 챗봇 추천에서 자동 제외(설정이 대화에도 반영).
- **WRITE**: 챗봇 "빼줘" → 마이 페이지에 영속(대화가 설정에도 반영).

## 2. 현재 상태 — 조각별
| 조각 | 상태 | 소관 |
|---|---|---|
| account 제외재료 API (`GET/POST/DELETE /users/excluded-items`, JWT 스코프) | ✅ **완료** | 백엔드 |
| 챗봇 세션 비선호(감지·누적·추천 필터) | ✅ **완료** | AI |
| 챗봇↔account 연동 코드 (`account_client.py` + main 배선) | ✅ **완료(flag OFF)** | AI |
| **인증(JWT/Gateway)** | ❌ **없음** | **인프라/백엔드** ← **유일 블로커** |

## 3. 챗봇 측(내 몫) — 이미 되어 있음
- `services/chat/app/pipeline/account_client.py`: account API 호출(read `get_excluded_item_ids`, write `add_excluded_items`). **남의 테이블 직접 안 건드리고 API만**. 실패·비활성 전부 graceful(현동작 무변경).
- `main.py`: 비선호 등록 시 `add_excluded_items` 호출(영속), 추천 시 세션 비선호 + `get_excluded_item_ids` **합산 적용**.
- **`Authorization` 헤더를 그대로 account에 포워딩**(유저 대신 호출).
- 기본 **OFF**(`account_integration_enabled=False`) → 인증·설정 없으면 **무동작**(현재 세션-스코프와 동일).

## 4. 완성에 필요한 것 (요구사항)
### ① 인증 (인프라/백엔드) — 핵심
- account 제외재료 API가 **JWT 소유자 스코프**(`get_current_user`)라, 챗봇이 **유저 JWT를 받아 account에 포워딩**할 수 있어야 함.
- 필요: Gateway/User 서비스로 **JWT 발급 + 챗봇 요청에 `Authorization` 헤더 전달**. (현재 챗봇 인증 부재 = 프로젝트 전반 갭.)

### ② 배포 설정 (인프라)
```
ACCOUNT_INTEGRATION_ENABLED=true
ACCOUNT_BASE_URL=http://<account-svc-host>:<port>
```

### ③ 동의 (제품/데이터)
- 대화 발화를 **영속 유저 설정으로 저장**하는 것 → 수집 동의 트랙에 포함(`chat-conversation-data-plan §4`). 동의 유저만 write.

## 5. 활성화 체크리스트
- [ ] JWT/Gateway로 챗봇에 유저 인증 전달(①)
- [ ] chat `.env`에 `ACCOUNT_INTEGRATION_ENABLED`·`ACCOUNT_BASE_URL`(②)
- [ ] 동의 게이팅 합의(③)
- [ ] → 플래그 ON, **코드 변경 없이** 양방향 연동 동작

## 6. 담당 경계
- **AI(건우)**: 챗봇 측 연동 코드·필터(완료). account 테이블 **직접 안 씀**, API만.
- **백엔드(account)**: 제외재료 API(완료) 유지.
- **인프라**: 인증(JWT)·배포 설정.
- **제품/데이터**: 영속화 동의.
