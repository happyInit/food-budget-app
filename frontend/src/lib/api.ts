// 데이터 티어 API 클라이언트. 응답 타입 = services/recipe·price 의 pydantic 모델과 1:1.
// 호출은 /api/* 상대경로 → dev는 vite 프록시, 운영은 게이트웨이가 서비스로 라우팅.
import type { PantryAddBody, PantryItemRow, PantryPatchBody } from './types'

// 토큰 seam — account 로그인이 발급한 access 토큰을 localStorage에서 읽어 Authorization 헤더로 첨부.
// 로그인 플로우(PR3)가 setToken 하면 이후 '인증 O' API에 자동 첨부. 없으면 미첨부(공개 데이터 티어는 그대로).
const TOKEN_KEY = 'access_token'
export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (t: string | null) =>
  t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY)

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}` // A01/A07: 서버가 JWT로 소유자 판정
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(url, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = ''
    try {
      detail = (await res.json())?.detail ?? ''
    } catch {
      /* ignore */
    }
    throw new Error(`${res.status} ${res.statusText}${detail ? ` — ${detail}` : ''}`)
  }
  if (res.status === 204) return undefined as T // DELETE 등 no-content
  return (await res.json()) as T
}

const getJson = <T>(url: string) => request<T>('GET', url)
const postJson = <T>(url: string, body: unknown) => request<T>('POST', url, body)
const patchJson = <T>(url: string, body: unknown) => request<T>('PATCH', url, body)
const putJson = <T>(url: string, body: unknown) => request<T>('PUT', url, body)
const delJson = <T>(url: string) => request<T>('DELETE', url)

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
  action: 'add_to_cart' | 'open_recipe'
  recipe_id?: number | null
  item_id?: number | null
}
export type ChatResponseT = {
  reply: string
  basis: ChatBasis[]
  actions: ChatAction[]
  unanswered: boolean
}
export const sendChat = (message: string, user_id?: string) =>
  postJson<ChatResponseT>('/api/mealplan/assistant/chat', { message, user_id })

// ── Account 서비스 (#2·#3·#7·#9·#10) — 로그인/프로필/예산. services/account 모델과 1:1 ──
export type TokenPair = { access_token: string; refresh_token: string; token_type: string }
export type UserProfile = { id: number; email: string | null; nickname: string; provider: string }
export type Budget = { month: string; amount: number } // month = 매월 1일(ISO date)
export type SignupBody = { email: string; password: string; nickname: string }

export const signup = (body: SignupBody) => postJson<{ userId: number }>('/api/auth/signup', body)
export const login = (email: string, password: string) =>
  postJson<TokenPair>('/api/auth/login', { email, password })
export const getMe = () => getJson<UserProfile>('/api/users/me')
export const getBudget = () => getJson<Budget | null>('/api/users/budget') // 미설정 시 null
export const putBudget = (amount: number) => putJson<Budget>('/api/users/budget', { amount })
export const logout = () => postJson<void>('/api/auth/logout', {}) // 스테이트리스 — 서버 no-op, 실제 폐기는 토큰 삭제

// ── Pantry 서비스 (#11~15) — '인증 O'(Authorization 자동 첨부). services/pantry PantryItemOut 와 1:1 ──
export const getPantryItems = () => getJson<PantryItemRow[]>('/api/pantry/items')
export const getExpiring = (within_days = 3) =>
  getJson<PantryItemRow[]>(`/api/pantry/expiring${qs({ within_days })}`)
export const addPantryItem = (body: PantryAddBody) => postJson<PantryItemRow>('/api/pantry/items', body)
export const patchPantryItem = (id: number, patch: PantryPatchBody) =>
  patchJson<PantryItemRow>(`/api/pantry/items/${id}`, patch)
export const deletePantryItem = (id: number) => delJson<void>(`/api/pantry/items/${id}`)

// 원 단위 천단위 콤마
export const won = (n?: number | null) => (n == null ? '-' : n.toLocaleString('ko-KR'))
