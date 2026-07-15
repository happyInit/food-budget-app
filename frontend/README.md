# 밀플래닝 Frontend — 개발 가이드

월 식비 예산 밀플래닝 앱의 프론트엔드(React + Vite PWA). 데이터 티어 서비스(recipe/price)를 `/api/*` 프록시로 호출한다.

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

## 로컬 실행
```bash
export PATH="/home/kevin/.nvm/versions/node/v24.18.0/bin:$PATH"   # node 고정
npm install
npm run dev        # http://localhost:5173 (점유 시 자동 증가)
npm run build      # tsc -b + vite build (타입체크 겸용)
```
실데이터를 붙이려면 데이터 티어 서비스도 함께 기동:
- recipe `:8001`, price `:8002` (각 `../services/*` 참고)
- `vite.config.ts` 프록시: `/api/recipes → :8001`, `/api/prices → :8002` (운영은 게이트웨이가 동일 라우팅 → 프론트 코드 불변)
- DB/ES: `192.168.0.8`(foodbudget). 접속정보는 `../services/*/.env`(gitignore, 커밋 금지).

## 폴더 구조
```
src/
  main.tsx              # QueryClientProvider(캐시 기본값) + Router 부트스트랩
  App.tsx               # 라우트 정의
  index.css             # 디자인 토큰(@theme) · 애니메이션 · .zoom 유틸
  lib/
    api.ts              # fetch 래퍼 + 엔드포인트 함수 + 응답 타입
    queries.ts          # ★ React Query 훅·캐시키·staleTime 일괄 관리
    types.ts            # DB 행 타입(실 컬럼명)
    data.ts             # mock 데이터(아직 OLTP 미구축 화면용)
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
