// ── DB 데이터 티어 행 타입 (foodbudget 실 컬럼명 그대로) ──
// 소스: docs/prd/schema-public-data.sql + 실 DB introspection (2026-07-14).
// ⚠️ 유저 OLTP(app_user·pantry_item·expense·cart·notification…) 타입은
//    스키마 확정(PR #32) 후 추가. 지금은 mock.ts에서 임시 shape 사용.

export type RetailSource = 'kurly' | 'oasis'
export type DealType = 'general' | 'closeSale' // ⚠️ 실 DB엔 아직 timedeal 없음

// recipe
export interface Recipe {
  id: number
  source: string // '10K' | 'COOKRCP01' | 'EPIS'
  name: string
  category: string | null
  cook_method: string | null
  cooking_time: string | null // '30분 이내' (숫자 아님)
  level_nm: string | null // '아무나' | '초급' …
  kcal: number | null
  serving: string | null // '2인분'
  image_url: string | null // 10K는 대체로 null
}

// recipe_ingredient
export interface RecipeIngredient {
  id: number
  recipe_id: number
  seq: number
  ingredient_name: string | null // '채 썬 표고버섯'
  quantity: string | null // '4개' | '100g'
  ingredient_raw: string | null
  ner_status: string // 'CRAWLER' | 'RAW' | 'NER_PARSED' | 'LABELED'
  item_id: number | null // → item_master (null이면 미매칭)
}

// recipe_step
export interface RecipeStep {
  recipe_id: number
  step_no: number
  description: string | null
  image_url: string | null
}

// retail_product
export interface RetailProduct {
  id: number
  source: RetailSource
  product_id: string
  name: string // '양파 1.5kg'
  name_norm: string | null // '양파'
  item_id: number | null
  weight_g: number | null
  volume_ml: number | null
  category: string | null // 소스 카테고리 '채소'
  url: string | null
  image_url: string | null
  storage: string | null // oasis '냉장' | '신선'
  origin: string | null // '국내산'
  expiry_text: string | null
}

// retail_price (시계열 스냅샷)
export interface RetailPrice {
  retail_product_id: number
  crawled_at: string
  price: number // 판매가(원) — ₩ 포맷 아님
  original_price: number | null
  discount_rate: number | null
  deal_type: DealType
  timedeal_end: string | null
  unit_price: number | null
  unit_basis: string | null // '100g' | '1개' | '100ml' …
  is_sold_out: boolean | null
}

// retail_unit_price (뷰) — 상품별 최신 스냅샷 + 단가
export interface RetailUnitPrice {
  id: number
  source: RetailSource
  item_id: number
  name: string
  weight_g: number | null
  price: number
  deal_type: DealType
  crawled_at: string
  won_per_100g: number | null
  won_per_piece: number | null
  piece_unit: string | null // '알' …
  won_per_100ml: number | null
}

// retail_item_price_compare (뷰) — 품목별 컬리 vs 오아시스 100g 최저
export interface ItemPriceCompare {
  item_id: number
  canonical_name: string
  category: string | null
  kurly_100g: number | null
  oasis_100g: number | null
  kurly_n: number
  oasis_n: number
  kurly_100ml: number | null
  oasis_100ml: number | null
}

// food_nutrition
export interface FoodNutrition {
  food_cd: string
  food_name: string
  serving_g: number | null
  kcal: number | null
  carb_g: number | null
  protein_g: number | null
  fat_g: number | null
  sugar_g: number | null
  sodium_mg: number | null
  item_id: number | null
}

// item_master
export interface ItemMaster {
  item_id: number
  canonical_name: string
  category: string | null // 채소·난류·육류·과일·수산물·버섯·곡류·견과·허브·양념·유제품·발효식품·가공식품·유지
  note: string | null
}

// ── 화면용 조합 뷰모델 (DB행 + 아직 OLTP/파생인 필드) ──
// pantry(보유여부)·최저가 조인은 OLTP/서비스 확정 후 서버가 계산.
// 지금은 mock에서 임시 제공하되 DB 컬럼명은 실명 그대로 유지.

export interface RecipeCardVM extends Recipe {
  emoji: string // image_url null 대체용 UI 값
  have: number // ← pantry 조인(OLTP, 임시)
  total: number
  short_cost: number // 부족재료 합계(retail 조인). 원 단위
}

export interface IngredientVM {
  ingredient_name: string
  quantity: string | null
  item_id: number | null
  emoji: string
  in_stock: boolean // ← pantry 조인(OLTP, 임시)
  lowest: { source: RetailSource; price: number } | null // ← retail 최저가 조인
}

export interface RecipeDetailVM extends Recipe {
  emoji: string
  ingredients: IngredientVM[]
  steps: Pick<RecipeStep, 'step_no' | 'description' | 'image_url'>[]
  short_cost: number
}

export interface DealVM {
  retail_product_id: number
  name: string
  source: RetailSource
  image_url: string | null
  item_id: number | null
  emoji: string
  price: number
  original_price: number | null
  discount_rate: number | null
  deal_type: DealType
  timedeal_end: string | null
  unit_price: number | null
  unit_basis: string | null
  recipe_hint: { id: number; label: string } | null // 연결 레시피(UI)
}

export interface CheapVM {
  item_id: number
  canonical_name: string
  category: string | null
  kurly_100g: number | null
  oasis_100g: number | null
  emoji: string
}

export interface CartItemVM {
  retail_product_id: number
  name: string
  source: RetailSource
  price: number
  item_id: number | null
  from_recipe: string | null
  emoji: string
}
