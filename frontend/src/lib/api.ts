// 데이터 티어 API 클라이언트. 응답 타입 = 각 서비스의 pydantic 모델과 1:1.
// 호출은 /api/* 상대경로 → dev는 vite 프록시, 운영은 게이트웨이가 서비스로 라우팅.
import type { PantryAddBody, PantryItemRow, PantryPatchBody } from './types'

// ── 토큰 seam ───────────────────────────────────────────────────────────────
// account 로그인(useLogin)이 발급한 access 토큰을 localStorage에 저장(setToken) → 요청 시 Authorization 자동 첨부.
// 로그인 전 개발용은 VITE_DEV_TOKEN 폴백(account 로그인/게이트웨이 붙기 전 Dev B 3서비스[recipebook·mealplan·notify] 테스트용).
// 공개 데이터 티어(recipe·price·chat)엔 무해(검증 안 함).
const TOKEN_KEY = 'access_token'
const REFRESH_KEY = 'refresh_token'
const DEV_TOKEN = import.meta.env.VITE_DEV_TOKEN as string | undefined
export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (t: string | null) =>
  t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY)
// refresh 토큰(14일) — access(30분) 만료 시 silent 재발급용. 로그인 시 저장, 로그아웃/만료 시 삭제.
export const getRefreshToken = () => localStorage.getItem(REFRESH_KEY)
export const setRefreshToken = (t: string | null) =>
  t ? localStorage.setItem(REFRESH_KEY, t) : localStorage.removeItem(REFRESH_KEY)
// 세션 종료(로그아웃·refresh 실패) — 두 토큰 모두 제거.
export const clearSession = () => { setToken(null); setRefreshToken(null) }

// access 만료(401) 시 refresh로 새 access 발급. 동시다발 401이 한 번만 갱신하도록 in-flight 프라미스 공유.
let refreshInFlight: Promise<string | null> | null = null
function refreshAccess(): Promise<string | null> {
  const rt = getRefreshToken()
  if (!rt) return Promise.resolve(null)
  if (!refreshInFlight) {
    refreshInFlight = fetch('/api/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ refresh_token: rt }),
    })
      .then(async (r) => {
        if (!r.ok) return null
        const data = (await r.json()) as { access_token: string }
        setToken(data.access_token)
        return data.access_token
      })
      .catch(() => null)
      .finally(() => { refreshInFlight = null })
  }
  return refreshInFlight
}

async function toError(res: Response): Promise<Error> {
  let detail = ''
  try {
    detail = (await res.json())?.detail ?? ''
  } catch {
    /* ignore */
  }
  return new Error(`${res.status} ${res.statusText}${detail ? ` — ${detail}` : ''}`)
}

async function request<T>(method: string, url: string, body?: unknown, retried = false): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = getToken() ?? DEV_TOKEN
  if (token) headers.Authorization = `Bearer ${token}` // A01/A07: 서버가 JWT로 소유자 판정
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
  // access 만료(401) → refresh로 재발급 후 1회 재시도. auth 엔드포인트 자체는 제외(로그인 실패 무한루프 방지).
  if (res.status === 401 && !retried && getRefreshToken() && !url.startsWith('/api/auth/')) {
    const fresh = await refreshAccess()
    if (fresh) return request<T>(method, url, body, true)
    // refresh도 실패 = 세션 하드 만료 → 토큰 정리 + 전역 통지(랜딩으로 유도).
    clearSession()
    window.dispatchEvent(new Event('auth:expired'))
  }
  if (!res.ok) throw await toError(res)
  if (res.status === 204) return undefined as T // No Content (DELETE 등)
  return (await res.json()) as T
}

const getJson = <T>(url: string) => request<T>('GET', url)
const postJson = <T>(url: string, body: unknown = {}) => request<T>('POST', url, body)
const patchJson = <T>(url: string, body?: unknown) => request<T>('PATCH', url, body ?? {})
const putJson = <T>(url: string, body: unknown) => request<T>('PUT', url, body)
const delJson = <T = void>(url: string) => request<T>('DELETE', url)

const qs = (params: Record<string, string | number | undefined>) => {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') sp.set(k, String(v))
  const s = sp.toString()
  return s ? `?${s}` : ''
}

// ── Recipe 서비스 (#18 · #19) ──
export type RecipeCard = {
  id: number
  name: string
  category?: string | null
  cooking_time?: string | null
  level_nm?: string | null
  serving?: string | null
  image_url?: string | null
  source: string
}
export type RecipeListResponse = { recipes: RecipeCard[]; page: number; size: number; total: number }

export type Nutrition = {
  kcal?: number | null
  carb_g?: number | null
  protein_g?: number | null
  fat_g?: number | null
  sodium_mg?: number | null
}
export type Ingredient = {
  seq?: number | null
  ingredient_name?: string | null
  quantity?: string | null
  item_id?: number | null
  ner_status: string
  lowest_source?: string | null
  lowest_krw_per_100g?: number | null
  kurly_krw_per_100g?: number | null
  oasis_krw_per_100g?: number | null
  // 재료 100g당 영양(식약처 food_nutrition, item_id 매칭). 미매칭이면 null.
  // ⚠️ 100g 기준 — 레시피 사용량 환산 아님(수량이 '약간·1큰술' 자유텍스트).
  kcal_100g?: number | null
  protein_100g?: number | null
  carb_100g?: number | null
  fat_100g?: number | null
  sodium_100g?: number | null
  // 레시피 사용량 기준 비용 (min(usage, 1팩) 상한). cost_basis: usage|capped|excluded_liquid|no_convert|no_price
  usage_grams?: number | null
  usage_krw?: number | null
  cost_basis?: string | null
}
export type Step = { step_no: number; description?: string | null; image_url?: string | null }
export type RecipeDetailT = {
  id: number
  source: string
  name: string
  category?: string | null
  cook_method?: string | null
  cooking_time?: string | null
  level_nm?: string | null
  serving?: string | null
  image_url?: string | null
  nutrition: Nutrition
  ingredients: Ingredient[]
  ingredient_cost_total?: number   // usage_krw 합 (제외·미환산 제외; 과소=커버리지 한계)
  steps: Step[]
}

export const searchRecipes = (
  q?: string,
  page = 1,
  size = 20,
  filters?: { cooking_time?: string; level?: string },
) =>
  getJson<RecipeListResponse>(
    `/api/recipes${qs({ q, page, size, cooking_time: filters?.cooking_time, level: filters?.level })}`,
  )

export const getRecipe = (id: number) => getJson<RecipeDetailT>(`/api/recipes/${id}`)

// ── Price 서비스 (#26 · #27 · #28 · #31) ──
export type HotdealItem = {
  retail_product_id: number
  name: string
  source: string
  image_url?: string | null
  url?: string | null                 // 소스(오아시스/컬리) 상품 상세 URL — 클릭 시 구매 페이지 이동
  item_id?: number | null
  price: number
  original_price?: number | null
  discount_rate?: number | null
  deal_type: string
  timedeal_end?: string | null
  unit_price?: number | null
  unit_basis?: string | null
  is_sold_out?: boolean | null
}
export type HotdealResponse = { deals: HotdealItem[] }

export type RecommendItem = {
  item_id: number
  canonical_name: string
  category?: string | null
  kurly_100g?: number | null
  oasis_100g?: number | null
  cheaper_source: string
  cheaper_krw_per_100g: number
  saving_pct: number
}
export type RecommendResponse = { items: RecommendItem[] }

export const getHotdeals = (limit = 20) => getJson<HotdealResponse>(`/api/prices/hotdeals${qs({ limit })}`)
export const getRecommend = (limit = 20) => getJson<RecommendResponse>(`/api/prices/recommend${qs({ limit })}`)

// 품목 이름 검색 (제외 재료 선택 등) — item_master canonical_name 검색
export type ItemSearchItem = { item_id: number; canonical_name: string; category?: string | null }
export const searchItems = (q: string, limit = 20) =>
  getJson<{ items: ItemSearchItem[] }>(`/api/prices/items${qs({ q, limit })}`)

// ── Chat 어시스턴트 (#37 RAG) ──
// services/chat 의 ChatResponse 와 1:1. 생성=템플릿(환각불가), 근거=basis, 액션=버튼.
export type ChatBasis = {
  type: 'price_snapshot' | 'nutrition' | 'recipe_match'
  item_id?: number | null
  source?: string | null
  crawled_at?: string | null
  detail?: string | null
}
export type ChatAction = {
  label: string
  action: 'add_to_cart' | 'open_recipe' | 'open_youtube' | 'navigate' | 'open_url'
  recipe_id?: number | null
  item_id?: number | null
  url?: string | null // open_youtube(유튜브 검색)·open_url(티어2 외부 레시피 링크) 전용
  route?: string | null // navigate 전용 — 인앱 라우트(예 /recipebook?compose=write)
  image_url?: string | null // open_recipe 카드 썸네일
  meta?: string | null // open_recipe 카드 메타(조리시간·난이도·인분·칼로리)
}
export type ChatResponseT = {
  reply: string
  basis: ChatBasis[]
  actions: ChatAction[]
  unanswered: boolean
  session_id?: string | null   // 멀티턴 ON 시 발급/유지된 세션 — 다음 턴에 재전송(팔로우업 승계)
}
// session_id 왕복 = 멀티턴(직전 추천 승계·"다른 추천은?"). Authorization(JWT)은 request()가 자동 첨부.
export const sendChat = (message: string, session_id?: string | null, user_id?: string) =>
  postJson<ChatResponseT>('/api/mealplan/assistant/chat', { message, session_id, user_id })

// ── RecipeBook 서비스 (#20~22 북마크) ──
// services/recipebook 의 BookOut/BookListOut 와 1:1. user_id는 JWT에서(바디에 없음).
export type Bookmark = {
  id: number // bookmark.id (삭제 키)
  recipe_id: number
  name: string
  image_url?: string | null
  cooking_time?: string | null
  level_nm?: string | null
}
export type BookmarkList = { books: Bookmark[] }
export const listBookmarks = () => getJson<BookmarkList>('/api/recipes/book')
export const addBookmark = (recipe_id: number) => postJson<{ id: number }>('/api/recipes/book', { recipe_id })
export const removeBookmark = (bookmark_id: number) => delJson(`/api/recipes/book/${bookmark_id}`)

// ── user_recipe (#24 내 레시피: 수동 등록 + 공유) ──
// services/recipebook 의 UserRecipe* 모델과 1:1. user_id는 JWT에서(바디 없음). origin은 서버가 MANUAL 고정.
// 상세 서빙 시 이름→item_id 매칭으로 최저가·영양이 채워짐(만개 상세와 동일 필드). 미매칭이면 파생값 전부 null.
export type UserRecipeIngredient = {
  name: string
  quantity?: string | null
  item_id?: number | null
  lowest_source?: string | null
  lowest_krw_per_100g?: number | null
  kurly_krw_per_100g?: number | null
  oasis_krw_per_100g?: number | null
  kcal_100g?: number | null
  protein_100g?: number | null
  carb_100g?: number | null
  fat_100g?: number | null
  sodium_100g?: number | null
  // 만개 상세(RecipeDetail)에서만 채워짐 — 유저작성 레시피는 미제공(패널이 100g 폴백)
  usage_grams?: number | null
  usage_krw?: number | null
  cost_basis?: string | null
}
export type UserRecipeListItem = {
  id: number
  title: string
  image_url?: string | null
  is_public: boolean
  created_at: string
}
export type UserRecipeList = { recipes: UserRecipeListItem[] }
export type UserRecipe = {
  id: number
  title: string
  origin: string
  ingredients: UserRecipeIngredient[]
  steps: string[]
  image_url?: string | null
  source_url?: string | null
  cooking_time?: string | null
  serving?: string | null
  level_nm?: string | null
  is_public: boolean
  share_token?: string | null
  created_at: string
}
export type UserRecipeCreateBody = {
  title: string
  ingredients: UserRecipeIngredient[]
  steps: string[]
  image_url?: string | null
  source_url?: string | null
  cooking_time?: string | null
  serving?: string | null
  level_nm?: string | null
}
export type ShareInfo = { share_token: string; is_public: boolean }
export type SharedRecipe = {
  title: string
  ingredients: UserRecipeIngredient[]
  steps: string[]
  image_url?: string | null
  cooking_time?: string | null
  serving?: string | null
  level_nm?: string | null
}

export const listMyRecipes = () => getJson<UserRecipeList>('/api/recipes/mine')
export const getMyRecipe = (id: number) => getJson<UserRecipe>(`/api/recipes/mine/${id}`)
export const createMyRecipe = (body: UserRecipeCreateBody) => postJson<{ id: number }>('/api/recipes/mine', body)
export const deleteMyRecipe = (id: number) => delJson(`/api/recipes/mine/${id}`)
export const shareMyRecipe = (id: number) => postJson<ShareInfo>(`/api/recipes/mine/${id}/share`)
export const unshareMyRecipe = (id: number) => delJson(`/api/recipes/mine/${id}/share`)
// 공개 공유 뷰 — 비인증(로그인 없이 링크로 열람)
export const getSharedRecipe = (token: string) => getJson<SharedRecipe>(`/api/recipes/shared/${encodeURIComponent(token)}`)

// ── shared_recipe (공개 카탈로그 발행) ──
// 발행 = 내 레시피를 레시피 목록에 공개. 검색에서 카탈로그와 합쳐 노출(share_token으로 공개 뷰 이동).
export type PublishInfo = { share_token: string; is_public: boolean }
export type SharedRecipeCard = {
  id: number
  title: string
  image_url?: string | null
  origin: string
  share_token: string
  published_at: string
}
export type SharedRecipeList = { recipes: SharedRecipeCard[] }
export const publishMyRecipe = (id: number) => postJson<PublishInfo>(`/api/recipes/mine/${id}/publish`)
export const unpublishMyRecipe = (id: number) => delJson(`/api/recipes/mine/${id}/publish`)
// 공개 발행 목록/검색 — 비인증
export const listSharedRecipes = (q?: string) =>
  getJson<SharedRecipeList>(`/api/recipes/shared${qs({ q, limit: 30 })}`)

// ── MealPlan 서비스: 장바구니 (#33~36) ──
// budget/remaining 은 예산 seam(account User API) 미배선이면 null → 프론트에서 degrade.
export type CartItemT = {
  id: number
  name: string
  qty: number
  quantity?: string | null
  item_id?: number | null
  lowest_krw_per_100g?: number | null // least(kurly_100g, oasis_100g)
  source?: string | null // 'kurly' | 'oasis' | null
}
export type CartResponse = {
  items: CartItemT[]
  subtotal: number
  budget?: number | null
  remaining?: number | null
}
export type CartItemCreate = {
  name: string
  recipe_id?: number | null
  item_id?: number | null
  retail_product_id?: number | null
  qty?: number
  quantity?: string | null
}
export const getCart = () => getJson<CartResponse>('/api/mealplan/cart')
export const addCartItem = (body: CartItemCreate) => postJson<{ id: number }>('/api/mealplan/cart/items', body)
export const deleteCartItem = (id: number) => delJson(`/api/mealplan/cart/items/${id}`)
export const checkoutCart = () =>
  postJson<{ order: { expense_id: number; amount: number } }>('/api/mealplan/cart/checkout')

// ── MealPlan 서비스: 식비 (#38~40) ──
export type ExpenseCategory = 'GROCERY' | 'DINING' | 'DELIVERY' | 'ETC'
export type ExpenseSource = 'MANUAL' | 'OCR' | 'CART'
export type ExpenseCreate = {
  amount: number
  category: ExpenseCategory
  spent_on: string // 'YYYY-MM-DD'
  memo?: string | null
  source?: ExpenseSource
}
export type CalendarDayT = { date: string; amount: number }
export type CalendarResponse = { days: CalendarDayT[] }
export type ExpenseSummaryT = {
  spent: number // 실구현(SQL sum)
  budget?: number | null // 예산 seam(없으면 null)
  remaining?: number | null // budget - spent (예산 seam)
  saved_ingredients?: number | null // pantry seam(안 버린 재료)
}
export const addExpense = (body: ExpenseCreate) => postJson<{ id: number }>('/api/expenses', body)
export const getCalendar = (month: string) => getJson<CalendarResponse>(`/api/expenses/calendar${qs({ month })}`)
export const getExpenseSummary = (month: string) => getJson<ExpenseSummaryT>(`/api/expenses/summary${qs({ month })}`)

// 성과보기 '식비 구성' — 카테고리별 지출 합 + 비중(0~1). 4종(GROCERY/DINING/DELIVERY/ETC) 항상 반환.
export type CategoryAmountT = { category: ExpenseCategory; amount: number; ratio: number }
export type ExpenseBreakdownT = { month: string; total: number; categories: CategoryAmountT[] }
export const getExpenseBreakdown = (month: string) =>
  getJson<ExpenseBreakdownT>(`/api/expenses/breakdown${qs({ month })}`)

// ── MealPlan 서비스: 추천 (#32) ──
// pantry(재고) seam 미배선이면 recommendations=[] + note (degrade).
export type MealRecommendation = {
  recipe_id: number
  name: string
  score: number
  coverage: number // 보유재료 커버리지(0~1)
  matched: number[]
  expiring_used: number
  est_cost?: number | null
  image_url?: string | null // 레시피 썸네일
}
export type RecommendMealResponse = { recommendations: MealRecommendation[]; note?: string | null }
export const recommendMeals = (body?: { budget?: number; prefer?: string }) =>
  postJson<RecommendMealResponse>('/api/mealplan/recommend', body ?? {})

// ── Notify 서비스 (#41~42 알림함) ──
export type NotificationType = 'LOW_PRICE' | 'EXPIRING' | 'HOTDEAL' | 'BUDGET'
export type AppNotification = {
  id: number
  type: NotificationType
  title: string
  body?: string | null
  payload?: Record<string, unknown> | null
  is_read: boolean
  created_at: string
}
export type NotificationList = { notifications: AppNotification[] }
export const listNotifications = (unread = false) =>
  getJson<NotificationList>(`/api/notifications${qs({ unread: unread ? 'true' : undefined })}`)
export const markNotificationRead = (id: number) =>
  patchJson<{ id: number; is_read: boolean }>(`/api/notifications/${id}/read`)

// ── Account 서비스 (#2·#3·#7·#9·#10) — 로그인/프로필/예산. services/account 모델과 1:1 ──
export type TokenPair = { access_token: string; refresh_token: string; token_type: string }
export type UserProfile = { id: number; email: string | null; nickname: string; provider: string }
export type Budget = { month: string; amount: number } // month = 매월 1일(ISO date)
export type SignupBody = { email: string; password: string; nickname: string }

export const signup = (body: SignupBody) => postJson<{ userId: number }>('/api/auth/signup', body)
export const login = (email: string, password: string) =>
  postJson<TokenPair>('/api/auth/login', { email, password })
export const getMe = () => getJson<UserProfile>('/api/users/me')
export const updateMe = (nickname: string) => patchJson<UserProfile>('/api/users/me', { nickname }) // #8 닉네임 수정
export const deleteMe = () => delJson<void>('/api/users/me') // 회원 탈퇴
export const getBudget = () => getJson<Budget | null>('/api/users/budget') // 미설정 시 null
export const putBudget = (amount: number) => putJson<Budget>('/api/users/budget', { amount })
export const logout = () => postJson<void>('/api/auth/logout', {}) // 스테이트리스 — 서버 no-op, 실제 폐기는 토큰 삭제

// 제외(회피) 재료 — 추천에서 걸러낼 표준품목
export type ExcludedItem = { item_id: number; name: string }
export const getExcludedItems = () => getJson<ExcludedItem[]>('/api/users/excluded-items')
export const addExcludedItem = (item_id: number, name: string) =>
  postJson<ExcludedItem>('/api/users/excluded-items', { item_id, name })
export const removeExcludedItem = (item_id: number) => delJson(`/api/users/excluded-items/${item_id}`)

// 성과보기 '안 버린 재료·폐기' — status별 재고 집계. month 미지정=전체 기간, 지정 시 closed_at 그 달.
export type PantryStatsT = {
  active: number // 현재 보유
  consumed: number // 소비 완료(안 버린 재료)
  discarded: number // 폐기(버림)
  saved_rate?: number | null // consumed/(consumed+discarded) — 종료 0건이면 null
}
export const getPantryStats = (month?: string) => getJson<PantryStatsT>(`/api/pantry/stats${qs({ month })}`)

// ── Pantry 서비스 (#11~15) — '인증 O'(Authorization 자동 첨부). services/pantry PantryItemOut 와 1:1 ──
export const getPantryItems = () => getJson<PantryItemRow[]>('/api/pantry/items')
export const getExpiring = (within_days = 3) =>
  getJson<PantryItemRow[]>(`/api/pantry/expiring${qs({ within_days })}`)
export const addPantryItem = (body: PantryAddBody) => postJson<PantryItemRow>('/api/pantry/items', body)
export const patchPantryItem = (id: number, patch: PantryPatchBody) =>
  patchJson<PantryItemRow>(`/api/pantry/items/${id}`, patch)
export const deletePantryItem = (id: number) => delJson<void>(`/api/pantry/items/${id}`)

// ── OCR 영수증 — 업로드/폴링=OCR 엔진(/api/pantry/ocr, 8010) · 확정=pantry(/api/pantry/receipts, 8005) ──
// 흐름: submitOcr(파일) → job_id → getOcrJob 폴링(DONE) → HITL 편집 → confirmReceipt → 식비를 addExpense 로 기록.
export type PantryStorage = 'ROOM' | 'FRIDGE' | 'FREEZER'
export type OcrItem = {
  raw_text: string
  name: string | null
  item_id: number | null
  quantity: string | null
  price: number | null
  is_food: boolean
  category: string | null      // 식재료/가공식품/비식품/조정/null(미해결)
  storage: PantryStorage | null // null=비-pantry(비식품·조정)
  in_expense: boolean
  needs_review: boolean         // HITL '확인' 하이라이트
  confirmed: boolean
}
export type OcrStatus = {
  status: 'PENDING' | 'DONE' | 'FAILED'
  store: string | null
  purchased_at: string | null   // ISO
  total_amount: number | null
  backend: string | null
  items: OcrItem[]
  reason: string | null         // FAILED 사유
}
export type OcrAccepted = { job_id: string; status: string }

// 이미지 업로드(multipart) — request()는 JSON 전용이라 여기선 FormData 직접(브라우저가 boundary 세팅).
export async function submitOcr(file: File): Promise<OcrAccepted> {
  const fd = new FormData()
  fd.append('image', file)
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = getToken() ?? DEV_TOKEN
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch('/api/pantry/ocr', { method: 'POST', headers, body: fd })
  if (!res.ok) throw await toError(res)
  return (await res.json()) as OcrAccepted
}
export const getOcrJob = (jobId: string) => getJson<OcrStatus>(`/api/pantry/ocr/${jobId}`)

// 확정 → pantry 저장(ocr_receipt·pantry_item) + 식비 서버계산 반환. category/storage/expire_at/keep=HITL 편집값.
export type ReceiptItemConfirm = {
  raw_text?: string | null
  name: string
  item_id?: number | null
  quantity?: string | null
  price?: number | null
  is_food?: boolean
  category?: string | null
  storage?: PantryStorage | null
  expire_at?: string | null    // 'YYYY-MM-DD' (없으면 서버가 shelf_life 추정)
  keep?: boolean               // 냉장고에 담을지(식품만 의미)
}
export type ReceiptConfirm = {
  store?: string | null
  purchased_at?: string | null
  total_amount?: number | null
  items: ReceiptItemConfirm[]
}
export type ReceiptConfirmResult = {
  receipt_id: number
  added_count: number
  expense_amount: number       // 식비(원): 냉장고에 담은(선택) 식품 가격 합
  expense_basis: 'total_anchor' | 'line_sum_fallback' | 'selected_items'
  needs_expense_review: boolean
}
export const confirmReceipt = (body: ReceiptConfirm) =>
  postJson<ReceiptConfirmResult>('/api/pantry/receipts', body)

// 원 단위 천단위 콤마
export const won = (n?: number | null) => (n == null ? '-' : n.toLocaleString('ko-KR'))
