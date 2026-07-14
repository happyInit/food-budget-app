// ── mock 데이터 (백엔드 연동 전 임시) ──
// 데이터 티어(recipe·retail·item_master…) 필드 = 실 DB 컬럼명 그대로 (foodbudget, 2026-07-14 확인).
// 유저 OLTP(pantry·expense·budget·cart·notification…) = 스키마 미정 → 임시 shape (PR #32 확정 후 교체).
import type {
  RecipeCardVM,
  RecipeDetailVM,
  CheapVM,
  DealVM,
  CartItemVM,
} from './types'

// ══════════════ 유저 OLTP (임시 mock — 스키마 확정 후 교체) ══════════════

export type Notification = {
  id: number
  emoji: string
  iconBg: string
  title: string
  desc: string
  time: string
  to: string
}

export const notifications: Notification[] = [
  { id: 1, emoji: '💰', iconBg: 'bg-brand-weak', title: '최저가 알림 · 애호박', desc: '평균 대비 22% 하락. 지금이 살 때!', time: '10분 전', to: '/cart' },
  { id: 2, emoji: '⏰', iconBg: 'bg-danger-weak', title: '유통기한 임박 · 대파', desc: 'D-1. 오늘 쓰는 레시피를 추천할까요?', time: '1시간 전', to: '/fridge' },
  { id: 3, emoji: '🔥', iconBg: 'bg-warn-weak', title: '오아시스 마감세일 열림', desc: '전골용 채소와 버섯 -40%. 오늘 마감.', time: '17:00', to: '/hotdeal' },
  { id: 4, emoji: '✅', iconBg: 'bg-black/5', title: '이번 달 예산 60% 사용', desc: '남은 12일, 하루 ₩15,250 페이스면 OK', time: '어제', to: '/expense' },
]

// ══════════════ 데이터 티어 (실 DB 컬럼명) ══════════════

// recipe 행 팩토리 — 10K 소스는 category·cook_method·kcal·image_url이 대체로 null.
// have/total/short_cost는 pantry(OLTP) 조인 자리 — 임시값.
const rc = (
  id: number,
  name: string,
  cooking_time: string,
  level_nm: string,
  serving: string,
  emoji: string,
  have: number,
  total: number,
  short_cost: number,
): RecipeCardVM => ({
  id, source: '10K', name, category: null, cook_method: null,
  cooking_time, level_nm, kcal: null, serving, image_url: null,
  emoji, have, total, short_cost,
})

export const recipes: RecipeCardVM[] = [
  rc(101, '돼지고기 김치찌개', '25분 이내', '보통', '2인분', '🍲', 3, 5, 8200),
  rc(102, '대파 계란말이', '10분 이내', '아무나', '1인분', '🍳', 4, 4, 0),
  rc(103, '제육볶음', '20분 이내', '보통', '2인분', '🥘', 2, 6, 6400),
  rc(104, '김치볶음밥', '15분 이내', '아무나', '1인분', '🍚', 4, 5, 1200),
  rc(105, '잔치국수', '15분 이내', '아무나', '2인분', '🍜', 3, 5, 2100),
  rc(106, '두부 샐러드', '10분 이내', '아무나', '1인분', '🥗', 3, 4, 0),
  rc(107, '애호박전', '15분 이내', '아무나', '2인분', '🥞', 3, 4, 900),
  rc(108, '카레라이스', '30분 이내', '보통', '3인분', '🍛', 2, 6, 5800),
]
export const recipeFilters = ['전체', '🧊 냉장고 재료로', '💸 ₩5,000 이하', '⏱ 20분 이내', '한식', '1인분']

// retail_item_price_compare 뷰 기반 — 품목별 컬리 vs 오아시스 100g 최저(원)
export const cheap: CheapVM[] = [
  { item_id: 31, canonical_name: '애호박', category: '채소', kurly_100g: 430, oasis_100g: 336, emoji: '🥬' },
  { item_id: 26, canonical_name: '돼지고기', category: '육류', kurly_100g: 1980, oasis_100g: 1630, emoji: '🥩' },
  { item_id: 3, canonical_name: '계란', category: '난류', kurly_100g: 1017, oasis_100g: 821, emoji: '🥚' },
]

export const homeData = {
  // 예산·통계·임박 = OLTP(임시)
  budget: { remaining: '183,000', total: '460,000', percent: 40, daily: '15,250', save: '38,000' },
  stats: [
    { k: '냉장고 임박', v: '2', unit: '개', m: '2일 내 소진', tone: 'warn' as const },
    { k: '오늘 추천', v: '4', unit: '개', m: '재고·예산 기반', tone: 'sub' as const },
    { k: '이번 달 지출', v: '₩277k', unit: '', m: '외식 ₩84k', tone: 'sub' as const },
    { k: '안 버린 재료', v: '92', unit: '%', m: '지난달 +7%p', tone: 'brand' as const },
  ],
  cheap, // ← 데이터 티어
  expiring: [
    { name: '대파', sub: '냉장 · 오늘 쓰기 좋아요', dday: 'D-1', tone: 'danger' as const, emoji: '🧅' },
    { name: '두부', sub: '냉장 · 1모', dday: 'D-2', tone: 'warn' as const, emoji: '🍚' },
  ],
  recommend: [recipes[1], recipes[0]] as RecipeCardVM[], // ← 데이터 티어(recipe)
}

// pantry(OLTP, 임시) — storage enum은 shelf_life_ref와 동일 ROOM/FRIDGE/FREEZER 예정
export const fridgeData = {
  summary: [
    { k: '보유 재료', v: '24', unit: '개', m: '냉장 12 · 냉동 7 · 실온 5', tone: 'sub' as const },
    { k: '유통기한 임박', v: '2', unit: '개', m: '2일 내 소진 권장', tone: 'danger' as const },
    { k: '이번 달 등록', v: '31', unit: '건', m: 'OCR 24 · 수동 7', tone: 'sub' as const },
    { k: '예상 폐기 방지', v: '₩12k', unit: '', m: '임박 소진 시', tone: 'brand' as const },
  ],
  expiring: [
    { name: '대파', sub: '냉장 · 1단', dday: 'D-1', tone: 'danger' as const, emoji: '🧅' },
    { name: '두부', sub: '냉장 · 1모', dday: 'D-2', tone: 'warn' as const, emoji: '🍚' },
  ],
  filters: ['전체 24', '냉장 12', '냉동 7', '실온 5'],
  stock: [
    { name: '돼지고기 300g', qty: '1팩', place: '냉동', dday: 'D-24', tone: 'n' as const, emoji: '🥩' },
    { name: '계란', qty: '8구', place: '냉장', dday: 'D-11', tone: 'n' as const, emoji: '🥚' },
    { name: '다진마늘', qty: '100g', place: '냉장', dday: 'D-30', tone: 'n' as const, emoji: '🧄' },
    { name: '우유 1L', qty: '1개', place: '냉장', dday: 'D-5', tone: 'warn' as const, emoji: '🥛' },
    { name: '양파', qty: '3개', place: '실온', dday: 'D-20', tone: 'n' as const, emoji: '🧅' },
    { name: '대파', qty: '1단', place: '냉장', dday: 'D-1', tone: 'danger' as const, emoji: '🧅' },
  ],
}

// recipe + recipe_ingredient + recipe_step (실 컬럼). in_stock/lowest = pantry·retail 조인(임시).
export const recipeDetail: RecipeDetailVM = {
  id: 101, source: '10K', name: '돼지고기 김치찌개', category: null, cook_method: null,
  cooking_time: '25분 이내', level_nm: '보통', kcal: null, serving: '2인분', image_url: null, emoji: '🍲',
  ingredients: [
    { ingredient_name: '돼지고기', quantity: '300g', item_id: 26, emoji: '🥩', in_stock: false, lowest: { source: 'kurly', price: 4900 } },
    { ingredient_name: '김치', quantity: '1/4포기', item_id: 200, emoji: '🥬', in_stock: false, lowest: { source: 'oasis', price: 3300 } },
    { ingredient_name: '대파', quantity: '1대', item_id: 9, emoji: '🧅', in_stock: true, lowest: null },
    { ingredient_name: '두부', quantity: '1/2모', item_id: 55, emoji: '🍚', in_stock: true, lowest: null },
  ],
  steps: [
    { step_no: 1, description: '돼지고기를 한입 크기로 썰고 김치와 함께 볶아요.', image_url: null },
    { step_no: 2, description: '물 400ml를 붓고 두부·대파를 넣어 끓여요.', image_url: null },
    { step_no: 3, description: '중불로 10분, 간을 보고 마무리해요.', image_url: null },
  ],
  short_cost: 8200,
}

// MealPlan(OLTP, 임시) — 추천은 recipe + pantry·예산 파생
export const mealPlan = [
  { name: '돼지고기 김치찌개', sub: '대파 D-1 소진 · 25분', have: 3, short: 2, add: '+₩8,200', emoji: '🍲' },
  { name: '대파 계란말이', sub: '대파·계란 소진 · 10분', have: 4, short: 0, add: '+₩0', emoji: '🍳' },
  { name: '김치볶음밥', sub: '두부 대체 활용 · 15분', have: 4, short: 1, add: '+₩1,200', emoji: '🍚' },
]

// 장바구니: items 제품정보 = retail_product/retail_price(실 컬럼). 합계·예산 = OLTP.
export const cart = {
  items: [
    { retail_product_id: 2001, name: '돼지고기 300g', source: 'kurly', price: 4900, item_id: 26, from_recipe: '김치찌개', emoji: '🥩' },
    { retail_product_id: 2002, name: '김치 1/4포기', source: 'oasis', price: 3300, item_id: 200, from_recipe: '김치찌개', emoji: '🥬' },
    { retail_product_id: 2003, name: '계란 한판', source: 'kurly', price: 5900, item_id: 3, from_recipe: '계란말이', emoji: '🥚' },
  ] as CartItemVM[],
  total: 14100,
  budget_remaining: 183000, // OLTP(예산)
  budget_percent: 8,
  after: 168900,
}

// Expense(OLTP, 임시)
export const expense = {
  budget: '460k', spent: '277k', shop: '193k', eat: '84k', remaining: '183k', percent: 60,
  days: [
    { d: 1 }, { d: 2 }, { d: 3, sp: '28k', hot: true }, { d: 4 }, { d: 5, sp: '12k', hot: true }, { d: 6 }, { d: 7 },
    { d: 8 }, { d: 9, sp: '34k', hot: true }, { d: 10 }, { d: 11 }, { d: 12, sp: '9k', today: true }, { d: 13 }, { d: 14 },
  ],
  today: [
    { icon: '🛒', t: '장보기 · 마켓컬리', s: '돼지고기 외 2건', p: '₩8,200' },
    { icon: '☕', t: '외식 · 카페', s: '수동 입력', p: '₩4,800' },
  ],
}

// Performance(OLTP, 임시)
export const performance = {
  stats: [
    { k: '예산 달성률', v: '순항', m: '60% 사용 · 40% 여유', bar: 60 },
    { k: '안 버린 재료', v: '92%', m: '지난달 85% → +7%p' },
    { k: '아낀 금액(추정)', v: '₩41k', m: '시세추천·임박소진' },
  ],
  months: [
    { m: '2월', h: 82 }, { m: '3월', h: 74 }, { m: '4월', h: 90 },
    { m: '5월', h: 66 }, { m: '6월', h: 70 }, { m: '7월', h: 60, now: true },
  ],
  usage: [
    { k: '다 쓴 재료', v: '22개', tone: 'brand' }, { k: '버린 재료', v: '2개', tone: 'danger' }, { k: '임박 소진 성공', v: '5회', tone: 'n' },
  ],
}

// 레시피북(OLTP recipe_book, 임시) — recipe_id는 recipe 논리참조
export const recipebook = [
  { id: 101, name: '돼지고기 김치찌개', sub: '만개의레시피 · 저장', emoji: '🍲', tag: '' },
  { id: 102, name: '백종원 계란찜', sub: '영상 추출 · 공개', emoji: '🎬', tag: 'YouTube' },
  { id: 103, name: '엄마표 제육볶음', sub: '직접 작성 · 비공개', emoji: '🥘', tag: '' },
  { id: 104, name: '자취 김치볶음밥', sub: '영상 추출', emoji: '🎬', tag: 'YouTube' },
]

// 핫딜: retail_product + retail_price(실 컬럼). ⚠️ 실 DB deal_type은 현재 'closeSale'만(타임세일 미수집).
export const hotdeal: { deals: DealVM[] } = {
  deals: [
    { retail_product_id: 7197, name: '자연키움 고추장 오리주물럭 500g', source: 'oasis', image_url: null, item_id: 26, emoji: '🍖', price: 11950, original_price: null, discount_rate: null, deal_type: 'closeSale', timedeal_end: '2026-07-14T15:00:00+09:00', unit_price: 2390, unit_basis: '100g', recipe_hint: { id: 103, label: '🥘 오리주물럭' } },
    { retail_product_id: 6269, name: '전골용 모둠버섯 300g', source: 'oasis', image_url: null, item_id: 300, emoji: '🍄', price: 5500, original_price: null, discount_rate: null, deal_type: 'closeSale', timedeal_end: '2026-07-14T15:00:00+09:00', unit_price: 1833, unit_basis: '100g', recipe_hint: { id: 101, label: '🍲 된장찌개' } },
    { retail_product_id: 7199, name: '손질 낙지 240g', source: 'oasis', image_url: null, item_id: 400, emoji: '🦑', price: 7900, original_price: null, discount_rate: null, deal_type: 'closeSale', timedeal_end: '2026-07-24T14:59:59+09:00', unit_price: 1787, unit_basis: '100g', recipe_hint: null },
    { retail_product_id: 1, name: '[KF365] 백다다기오이 3입', source: 'kurly', image_url: null, item_id: 31, emoji: '🥒', price: 2790, original_price: 3490, discount_rate: 20, deal_type: 'general', timedeal_end: null, unit_price: null, unit_basis: null, recipe_hint: { id: 106, label: '🥗 오이무침' } },
    { retail_product_id: 2, name: '양파 1.5kg', source: 'kurly', image_url: null, item_id: 29, emoji: '🧅', price: 3990, original_price: 4990, discount_rate: 20, deal_type: 'general', timedeal_end: null, unit_price: null, unit_basis: null, recipe_hint: null },
  ],
}

// Assistant(OLTP/RAG, 임시)
export const chat = [
  { me: false, text: '안녕하세요! 냉장고에 대파·두부·계란이 있고, 이번 달 예산은 ₩183,000 남았어요. 뭘 도와드릴까요?' },
  { me: true, text: '이번 주 3만원으로 3일치 저녁 짜줘' },
  { me: false, text: '좋아요. 임박한 대파(D-1)부터 쓰는 3일 플랜이에요 👇\n· 월: 김치찌개 ₩8,200\n· 화: 계란말이 ₩0 (보유)\n· 수: 제육볶음 ₩6,400\n합계 ₩14,600 — 예산 안에서 충분해요. 장바구니에 담을까요?' },
  { me: true, text: '응 담아줘' },
]
