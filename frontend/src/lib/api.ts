// 데이터 티어 API 클라이언트. 응답 타입 = services/recipe·price 의 pydantic 모델과 1:1.
// 호출은 /api/* 상대경로 → dev는 vite 프록시, 운영은 게이트웨이가 서비스로 라우팅.

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!res.ok) {
    let detail = ''
    try {
      detail = (await res.json())?.detail ?? ''
    } catch {
      /* ignore */
    }
    throw new Error(`${res.status} ${res.statusText}${detail ? ` — ${detail}` : ''}`)
  }
  return (await res.json()) as T
}

async function postJson<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body),
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
  return (await res.json()) as T
}

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

// 원 단위 천단위 콤마
export const won = (n?: number | null) => (n == null ? '-' : n.toLocaleString('ko-KR'))
