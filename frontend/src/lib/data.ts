// 확정본(FoodBudget.dc.html) mock 데이터. 음식사진은 확정본과 동일 Unsplash 소스.
const PHOTOS = [
  '1584949091598-c31daaaa4aa9', '1498654896293-37aacf113fd9', '1547592166-23ac45744acd',
  '1512058564366-18510be2db19', '1467003909585-2f8a72700288', '1546069901-ba9599a7e63c',
  '1504674900247-0877df9cc836', '1490645935967-10de6ba17061', '1455619452474-d2be8b1e70cd',
  '1466637574441-749b8f19452f', '1540189549336-e6e99c3679fe', '1512621776951-a57141f2eefd',
  '1543339308-43e59d6b73a6', '1473093295043-cdd812d0e601', '1476224203421-9ac39bcb3327',
]
export const img = (i: number, w = 500) =>
  `https://images.unsplash.com/photo-${PHOTOS[((i % PHOTOS.length) + PHOTOS.length) % PHOTOS.length]}?auto=format&fit=crop&q=80&w=${w}`

// 유저가 직접 등록한 레시피(수동)에 썸네일이 없을 때 쓰는 기본 썸네일 — 브랜드 컬러 접시+수저 SVG.
const _defaultRecipeThumb = `<svg xmlns='http://www.w3.org/2000/svg' width='400' height='300'>
<defs><linearGradient id='g' x1='0' y1='0' x2='0' y2='1'><stop offset='0' stop-color='#FCEBDD'/><stop offset='1' stop-color='#F6D6BB'/></linearGradient></defs>
<rect width='400' height='300' fill='url(#g)'/>
<circle cx='200' cy='134' r='58' fill='#ffffff' opacity='0.6'/>
<circle cx='200' cy='134' r='58' fill='none' stroke='#F26419' stroke-width='5'/>
<circle cx='200' cy='134' r='37' fill='none' stroke='#F26419' stroke-width='2.5' opacity='0.55'/>
<path d='M138 102 v64 M131 102 v24 M145 102 v24 M131 126 h14' fill='none' stroke='#F26419' stroke-width='4' stroke-linecap='round'/>
<path d='M262 102 v64 M262 102 c12 4 12 26 0 30' fill='none' stroke='#F26419' stroke-width='4' stroke-linecap='round'/>
<text x='200' y='232' text-anchor='middle' font-family='sans-serif' font-size='15' font-weight='700' fill='#C9762F'>내가 만든 레시피</text>
</svg>`
export const DEFAULT_RECIPE_THUMB = `data:image/svg+xml,${encodeURIComponent(_defaultRecipeThumb)}`

// ── 홈 ──
export const homeKpi = [
  { k: '7월 남은 예산', v: '182,400원', sub: '전체 300,000원의 61%', color: '#F26419' },
  { k: '이번 달 지출', v: '117,600원', sub: '지난달 대비 -8%', subColor: '#1E5F96' },
  { k: '재고 활용 절약', v: '27,000원', sub: '안 버린 재료 4종', color: '#1E5F96' },
  { k: '냉장고 재고', v: '12종', sub: '유통기한 임박 2종 ›', subColor: '#F04452', to: '/pantry' },
]

export const homeRecipes = [
  { name: '묵은지 김치찌개', tag: '재료 80% 보유', add: '추가 4,200원', p: 1 },
  { name: '폭신 계란말이', tag: '재료 100% 보유', add: '추가 0원', free: true, p: 2 },
  { name: '구수한 된장찌개', tag: '재료 70% 보유', add: '추가 3,500원', p: 3 },
  { name: '알감자 조림', tag: '재료 90% 보유', add: '추가 1,200원', p: 4 },
  { name: '매콤 제육볶음', tag: '재료 60% 보유', add: '추가 6,800원', p: 5 },
]

// ── 레시피 탐색 ──
export const recipeList = [
  { name: '김치찌개', meta: '30분 · 4,200원 · 만개의레시피' },
  { name: '제육볶음', meta: '25분 · 6,800원 · 만개의레시피' },
  { name: '된장찌개', meta: '25분 · 3,500원 · 냉부' },
  { name: '계란말이', meta: '15분 · 1,800원 · 만개의레시피' },
  { name: '감자볶음', meta: '20분 · 2,300원 · 만개의레시피' },
  { name: '잔치국수', meta: '20분 · 2,100원 · 냉부' },
  { name: '두부샐러드', meta: '10분 · 3,200원 · 만개의레시피' },
  { name: '카레라이스', meta: '35분 · 4,100원 · 만개의레시피' },
]
export const recipeFilters = ['전체', '집밥', '자취요리', '15분 이내', '다이어트', '냉부 레시피']

// ── 냉장고 (팬트리/냉장/냉동 zone) ──
export type PantryItem = { name: string; qty: string; dday: string; urg: 'danger' | 'warn' | 'ok'; fresh: number; p: number }
export const pantry = {
  room: [
    { name: '양파', qty: '3개 · 실온', dday: 'D-30+', urg: 'ok', fresh: 95, p: 11 },
    { name: '감자', qty: '5개 · 실온', dday: 'D-30+', urg: 'ok', fresh: 88, p: 13 },
    { name: '다진마늘', qty: '약 100g · 실온', dday: 'D-18', urg: 'ok', fresh: 70, p: 12 },
  ] as PantryItem[],
  fridge: [
    { name: '풀무원 두부', qty: '1모 · 냉장', dday: 'D-1', urg: 'danger', fresh: 15, p: 3 },
    { name: '서울우유 1L', qty: '500ml · 냉장', dday: 'D-2', urg: 'danger', fresh: 24, p: 7 },
    { name: '대파', qty: '2대 · 냉장', dday: 'D-6', urg: 'warn', fresh: 46, p: 9 },
    { name: '계란', qty: '6개 · 냉장', dday: 'D-12', urg: 'ok', fresh: 68, p: 8 },
    { name: '묵은지', qty: '약 500g · 냉장', dday: 'D-20', urg: 'ok', fresh: 82, p: 0 },
  ] as PantryItem[],
  freezer: [
    { name: '삼겹살', qty: '300g · 냉동', dday: '냉동', urg: 'ok', fresh: 90, p: 4 },
    { name: '냉동밥', qty: '2개 · 냉동', dday: '냉동', urg: 'ok', fresh: 92, p: 10 },
  ] as PantryItem[],
}

// ── 뭐 해먹지 (palmer-dinnerware 오마쥬: 불규칙 스캐터) ──
// left=%(1040 캔버스 기준), top=px, size=px. 크기·위치 제각각 + 넉넉한 여백.
export const platePlan = [
  { name: '대파 계란볶음밥', p: 6, size: 190, left: '18%', top: 150 },
  { name: '묵은지 김치찌개', p: 0, size: 176, left: '60%', top: 96 },
  { name: '두부김치', p: 3, size: 150, left: '42%', top: 402 },
  { name: '매콤 제육볶음', p: 4, size: 130, left: '77%', top: 372 },
  { name: '알감자 조림', p: 8, size: 126, left: '11%', top: 486 },
  { name: '구수한 된장찌개', p: 2, size: 118, left: '62%', top: 512 },
  { name: '폭신 계란말이', p: 1, size: 102, left: '40%', top: 60 },
  { name: '참치마요덮밥', p: 5, size: 94, left: '86%', top: 128 },
]

export const homeDeals = [
  { brand: '한돈', name: '국내산 삼겹살 구이용 600g', pct: '42', price: '10,900', orig: '18,900', review: '1,204', p: 5 },
  { brand: '프레시밀', name: '무항생제 계란 대란 30구', pct: '30', price: '6,930', orig: '9,900', review: '3,118', p: 6 },
  { brand: '컬리', name: '국내산 알배기 배추 1통', pct: '18', price: '2,890', orig: '3,520', review: '662', p: 7 },
  { brand: '산지직송', name: '햇양파 1.5kg (국내산)', pct: '12', price: '3,290', orig: '3,740', review: '421', p: 8 },
  { brand: '풀무원', name: '국산콩 부침용 두부 300g', pct: '15', price: '1,690', orig: '1,990', review: '894', p: 9 },
]
