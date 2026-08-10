# 밀플래닝 Frontend — 개발 가이드

월 식비 예산 밀플래닝 앱의 프론트엔드(React + Vite PWA). 데이터 티어(recipe/price/chat) + 유저 서비스(account·pantry)를 `/api/*` 프록시로 호출한다. 인증은 **Bearer 토큰(localStorage)**.

## 정본 문서
| 종류 | 위치 |
|---|---|
| 화면 스펙(정본) | `references/화면정의서.xlsx`(SCR-001~022) = `../docs/design/frontend specification.xlsx` |
| 기능 명세(정본) | `../docs/service-spec-handoff.md` |
| API 명세 | `../docs/design/api-spec.md` |
| 렌더 시안 | `references/밀플래닝 확정본.html` (25MB, **git 제외 — 로컬만**) |

> 참고: `references/프론트엔드 화면정의서.pdf`는 일부 낡음(컬러 그린·레시피탐색 버튼 등). 대조는 xlsx/service-spec 우선.

## 화면 (SCR-001~022)
인증(001–004) · 홈(005) · 냉장고/OCR(006–009) · 레시피(010–011) · 밀플래닝(012) · 장바구니(013) · 식비(014–016) · 알림/마이/레시피북(017–019) · YouTube추출(020) · 핫딜(021) · 어시스턴트(022)

---

## 스택
- **React 19** + **Vite 8** + **TypeScript**
- **React Router 7** (SPA 라우팅)
- **@tanstack/react-query 5** — 서버 데이터 페칭·캐싱 (아래 §데이터 참고)
- **Tailwind 4**(`@theme` 토큰) + 인라인 `style` 혼용
- **PWA** (홈화면 설치 + 최저가·유통기한 임박 푸시 지향)
- zustand/vaul/lucide 설치돼 있으나 **현재 미사용**(인라인 스타일·자체 useState로 처리 중)
- **인증**: Bearer 토큰을 localStorage에 저장(`api.ts`의 `getToken`/`setToken`), 요청 시 Authorization 자동 첨부(zustand 대신 최소 seam)
- **테스트**: **vitest** — 순수 매핑/검증 로직(`lib/pantry.ts`·`lib/auth.ts`)만 단위 테스트(`npm test`). 컴포넌트는 타입체크+빌드로 검증

## 로컬 실행
```bash
export PATH="/home/kevin/.nvm/versions/node/v24.18.0/bin:$PATH"   # node 고정
npm install
npm run dev        # http://localhost:5173 (점유 시 자동 증가)
npm run build      # tsc -b + vite build (타입체크 겸용)
```
실데이터를 붙이려면 백엔드 서비스도 함께 기동(각 `../services/*` 참고):
- recipe `:8001` · price `:8002` · chat `:8003` · **account `:8004`(auth·user)** · **pantry `:8005`(재고)**
- **Dev B(PR #70)**: recipebook `:8006` · mealplan `:8007` · notify `:8008`
- 포트 SoT = **CONVENTIONS §5**(서비스별 고정·무충돌, Dockerfile `--port`와 일치). 필요 시 `VITE_*_ORIGIN`으로 오버라이드. 라우팅은 아래 표.
- **인증 필요 화면(냉장고·마이·예산·레시피북·장바구니·식비·알림)은 로그인 후 동작**(토큰 저장). 로그인 없이는 401/빈 상태.
- DB/ES: `192.168.0.8`(foodbudget). 접속정보는 `../services/*/.env`(gitignore, 커밋 금지).

### `vite.config.ts` 프록시 (⚠️ prefix 매칭 + 삽입 순서 우선)
프록시는 경로 prefix로 매칭하고 **먼저 선언된 것이 이긴다** → 더 구체적인 경로를 반드시 위에 둔다.
| prefix | → 서비스 | 비고 |
|---|---|---|
| `/api/recipes/book` | recipebook `:8006` | **반드시 `/api/recipes`보다 먼저** |
| `/api/recipes` | recipe `:8001` | |
| `/api/mealplan/assistant` | chat `:8003` | **반드시 `/api/mealplan`보다 먼저** |
| `/api/mealplan` · `/api/expenses` | mealplan `:8007` | 장바구니·식비·추천 |
| `/api/notifications` | notify `:8008` | 알림함 |
| `/api/pantry` | pantry `:8005` | 냉장고 재고 |
| `/api/auth` · `/api/users` | account `:8004` | 로그인·프로필·예산 |
| `/api/prices` | price `:8002` | |

운영은 게이트웨이가 동일 라우팅 → 프론트 코드 불변.

### 인증 (개발용 dev 토큰 shim)
Dev B 엔드포인트(recipebook·mealplan·notify)는 **전부 JWT 필요**(`get_current_user`). account 로그인/게이트웨이가 붙기 전까지는 개발용 토큰을 `.env.local`(gitignore)에 넣어 `Authorization: Bearer`로 실어 보낸다(`lib/api.ts`의 `VITE_DEV_TOKEN`).
🔴 **`JWT_SECRET` 에 코드 기본값(폴백)은 없다** — 비었거나 32자 미만이면 서비스가 **기동에 실패**한다
(체크리스트 0-12: placeholder 로 무증상 기동하면 토큰 위조가 가능해진다). 로컬 값은 `../dev-up.sh` 가
`.env.dev-jwt`(gitignored)에 1회 생성해 재사용하므로, 아래 발급 스크립트도 **그 값을 읽어서** 쓴다.

```bash
# 서비스와 동일 secret으로 access JWT 발급 (sub=1, HS256, exp 원하는 만큼)
JWT_SECRET="$(cat ../.env.dev-jwt)" python - <<'PY'
import datetime as dt, os, jwt
now = dt.datetime.now(dt.timezone.utc)
print(jwt.encode({"sub":"1","typ":"access","iat":now,"exp":now+dt.timedelta(days=3650)},
                 os.environ["JWT_SECRET"], algorithm="HS256"))
PY
# 출력 토큰을 frontend/.env.local 에:  VITE_DEV_TOKEN=<토큰>
```
- 3서비스는 **같은 `JWT_SECRET`**(= `.env.dev-jwt` 한 값)로 기동해야 이 토큰을 검증한다.
- **부팅**(scratchpad venv, 실 DB): 각 `../services/<name>`에서
  `env PGPASSWORD=… JWT_SECRET="$(cat ../../.env.dev-jwt)" PYTHONPATH=. <venv>/bin/uvicorn app.main:app --port 800X`
  (또는 `.env` 채워두면 됨 — `.env.example` 복사 후 `PGPASSWORD`·`JWT_SECRET` 기입).
- `user_id`는 크로스서비스 **논리 bigint**(FK 없음)라 `sub=1`이면 계정 테이블이 비어도 동작.
- account 로그인이 나오면 `.env.local`을 지우고 로그인 세션 토큰으로 대체 → 호출부(api.ts) 불변.

> ⚠️ **seam degrade**: mealplan의 예산(account User API)·재고(pantry API)는 아직 미배선 → `budget`/`remaining`/`saved_ingredients`는 `null`, 추천(#32)은 `[]`+`note`. 프론트는 이걸 정상 degrade로 처리(예산 잔여 "연동 예정", 추천 "예시 추천"). account·pantry 가동 후 실배선.

## 폴더 구조
```
src/
  main.tsx              # QueryClientProvider(캐시 기본값) + Router 부트스트랩
  App.tsx               # 라우트 정의
  index.css             # 디자인 토큰(@theme) · 애니메이션 · .zoom 유틸
  lib/
    api.ts              # fetch 래퍼(+토큰 seam getToken/setToken) + 엔드포인트 함수 + 응답 타입
    queries.ts          # ★ React Query 훅·캐시키·staleTime·뮤테이션 일괄 관리
    types.ts            # DB/OLTP 행 타입(실 컬럼명) — 재고·유저 포함
    pantry.ts           # 순수: 재고 행→표시VM·D-day·긴급도 (vitest)
    auth.ts             # 순수: 금액 파싱·회원가입 검증 (vitest)
    data.ts             # mock 데이터(아직 미연동 화면용 — Home 등)
    format.ts nav.ts    # 포맷 · 네비 정의
  components/
    layout/AppShell.tsx # GNB 헤더 + 모바일 드로어 + 플로팅(챗·알림)
    Modal.tsx           # 중앙 모달 + 슬라이드업 시트 겸용
    NotificationPanel · ChatWidget · AddToCartModal · PerformancePanel
    forms/              # 모달 콘텐츠 폼(재료추가·지출·OCR·레시피작성·YouTube)
  pages/                # 화면별 컴포넌트(라우트당 1개)
public/icons/
    app-icon.png        # 마스코트 = 앱 아이콘 + 로고 + 챗봇 공용 (정중앙 크롭본)
    app-icon-full.png   # 원본 백업 / pug.png(구 로고, 미사용)
```

---

## 데이터 페칭 · 캐싱 (중요)

**모든 서버 데이터는 React Query로 페칭한다.** 직접 `fetch`/`useEffect` 페칭 금지(캐시·중복요청·로딩처리를 놓침). 구 커스텀 `useFetch` 훅은 제거됨.

### 왜 프론트 캐시인가
백엔드 캐시(Redis)는 DB 부하만 줄일 뿐 매 화면전환에 네트워크 왕복이 남아 스피너가 계속 뜬다. 프론트 캐시는 **재방문 시 메모리에서 즉시 렌더(네트워크 0)** 라 체감 로딩이 확실히 빨라지고 인프라 추가도 없다.

### 원칙: 데이터 성격별 staleTime
`staleTime` = "이 시간 안엔 fresh로 보고 재요청 안 함". `lib/queries.ts`의 `STALE` 상수로 관리.

| 데이터 | staleTime | 이유 |
|---|---|---|
| 레시피 검색·상세·티저 | **30분** (`STALE.recipe`) | 크롤링 정적 — 거의 안 변함 |
| 핫딜·추천(지금 싼 재료) | **2분** (`STALE.price`) | 가격은 자주 변함 |
| 전역 기본값(main.tsx) | 5분 | 그 외 |

> ⚠️ 가격·예산 같은 mutable 데이터에 긴 staleTime을 걸면 낡은 값이 보인다. 새 쿼리 추가 시 성격에 맞는 staleTime을 반드시 지정.

### 적용된 최적화
- **hover prefetch** — 레시피 카드에 마우스를 올리면 상세를 미리 fetch(`usePrefetchRecipe`) → 클릭 시 즉시 진입. (RecipeSearch·홈 티저)
- **placeholderData(keepPreviousData)** — 검색어·필터를 바꿔도 이전 결과 유지하며 로드 → 빈 화면·스피너 깜빡임 없음.
- **useInfiniteQuery** — 레시피 무한스크롤. 페이지별 캐시 + 수동 페이지네이션 제거.
- **refetchOnWindowFocus: false** — 탭 포커스마다 재요청 안 함(main.tsx 기본값).
- **loading="lazy"** — 화면 밖 콘텐츠 이미지 지연 로드.

### 새 데이터 붙이는 법
1. `lib/api.ts`에 엔드포인트 함수 + 응답 타입 추가.
2. `lib/queries.ts`에 `useXxx` 훅 추가 — `queryKey`(캐시 식별) + `staleTime`(성격별) 지정.
3. 페이지에서 `const { data, error, isLoading } = useXxx()`.
   - `error`는 `Error | null` → 문구엔 `error.message`.
   - 초기 스피너 `isLoading`, 무한스크롤 추가로딩 `isFetchingNextPage`.

```ts
// lib/queries.ts 패턴
export function useRecipe(id: number) {
  return useQuery({
    queryKey: ['recipe', id],   // 이 키로 캐시·prefetch 매칭
    queryFn: () => getRecipe(id),
    staleTime: STALE.recipe,    // 30분 재방문 즉시
    enabled: Number.isFinite(id),
  })
}
```

### 인증 필요 엔드포인트 · 뮤테이션
- **인증**: `api.ts`의 `request()`가 토큰(localStorage `access_token`, 없으면 dev `VITE_DEV_TOKEN` 폴백)을 `Authorization: Bearer`로 자동 첨부 → 엔드포인트 함수는 그냥 호출하면 된다. 로그인 = `useLogin`(성공 시 `setToken`), 로그아웃 = `useLogout`(토큰+캐시 삭제). 유저 조회 훅(`useMe`·`useBudget`)은 `enabled: !!getToken()`.
- **뮤테이션(OLTP)**: `useMutation` + `onSuccess`에서 관련 캐시 `invalidateQueries`. 캐시키는 `KEYS` 상수(`lib/queries.ts`). OLTP(유저 소유)는 `staleTime` 짧게(`OLTP_STALE` 30초). `checkout`은 cart + `['expense']` 둘 다 invalidate(지출을 만들므로), `usePutBudget`→`['budget']`.
  ```ts
  export function useAddCartItem() {
    const qc = useQueryClient()
    return useMutation({
      mutationFn: (body: CartItemCreate) => addCartItem(body),
      onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.cart }), // 장바구니 다시 읽기
    })
  }
  ```
- **순수 로직 분리**: 매핑·검증·파싱은 `lib/pantry.ts`·`lib/auth.ts`로 빼서 **vitest로 test-first**(`*.test.ts`), 컴포넌트는 얇게 유지. 새 서비스(mealplan·expense 등)도 이 패턴을 따른다.

### 후속 후보 (아직 안 함)
- **localStorage 영속화**(`persistQueryClient`) — 새로고침/재접속에도 캐시 유지. staleTime 관리 주의.
- **레시피 카드 이미지 `<img loading="lazy">` 전환** — 현재 배경이미지(div)라 lazy 미적용. 그리드가 무거워지면 검토.
- **ES 검색 전환** — 첫 검색 지연이 커지면(현재 PG `ILIKE '%..%'` + OFFSET) `config.search_backend="es"`로. *프론트 캐시=재방문 빠르게, ES=첫 검색 빠르게* 역할 분담.

---

## 디자인 규칙
- **컬러**: 브랜드 주황 `#F26419`(최신 확정), 잉크 네이비 `#17264A`.
- **형태**: `radius 0` 직각 스퀘어. 곡선은 마스코트·썸네일 원형만 예외.
- **폰트**: 제목(h1~h3)·헤더 = Paperlogy(디스플레이) / 본문·숫자 = Pretendard. `index.css`의 `--font-display` 한 줄로 교체.
- **아이콘/이모지 미사용** — 텍스트·형태로 위계 표현(정의서 규칙). 마스코트 이미지만 예외.
- **등록·입력은 전부 모달/시트** — `Modal`(center/sheet) 재사용. 페이지 이동 지양.
- **이미지 호버 줌** — 컨테이너 `.zoom-wrap` + 이미지 `.zoom`.

## 검증(시각)
WSL에서 헤드리스 크롬으로 dev 서버를 캡처한다.
```bash
"/mnt/c/Program Files/Google/Chrome/Application/chrome.exe" \
  --headless=new --disable-gpu --hide-scrollbars --window-size=1280,900 \
  --virtual-time-budget=15000 --screenshot="C:\temp\x.png" "http://127.0.0.1:5173/home"
```
- 웹폰트/비동기 데이터까지 잡으려면 `--virtual-time-budget` 넉넉히(≥12000).
- ⚠️ 헤드리스 CSS 뷰포트 최소가 ~500px라 **진짜 390px 모바일은 축소 렌더** — 폭 검증은 실기기/에뮬레이터 필요.
