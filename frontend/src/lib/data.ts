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

// ── 홈 ──
export const homeKpi = [
  { k: '7월 남은 예산', v: '182,400원', sub: '전체 300,000원의 61%', color: '#1FA463' },
  { k: '이번 달 지출', v: '117,600원', sub: '지난달 대비 -8%', subColor: '#15B76E' },
  { k: '재고 활용 절약', v: '27,000원', sub: '안 버린 재료 4종', color: '#15B76E' },
  { k: '냉장고 재고', v: '12종', sub: '유통기한 임박 2종 ›', subColor: '#F04452', to: '/fridge' },
]

export const homeRecipes = [
  { name: '묵은지 김치찌개', tag: '재료 80% 보유', add: '추가 4,200원', p: 1 },
  { name: '폭신 계란말이', tag: '재료 100% 보유', add: '추가 0원', free: true, p: 2 },
  { name: '구수한 된장찌개', tag: '재료 70% 보유', add: '추가 3,500원', p: 3 },
  { name: '알감자 조림', tag: '재료 90% 보유', add: '추가 1,200원', p: 4 },
  { name: '매콤 제육볶음', tag: '재료 60% 보유', add: '추가 6,800원', p: 5 },
]

export const homeDeals = [
  { brand: '한돈', name: '국내산 삼겹살 구이용 600g', pct: '42', price: '10,900', orig: '18,900', review: '1,204', p: 5 },
  { brand: '프레시밀', name: '무항생제 계란 대란 30구', pct: '30', price: '6,930', orig: '9,900', review: '3,118', p: 6 },
  { brand: '컬리', name: '국내산 알배기 배추 1통', pct: '18', price: '2,890', orig: '3,520', review: '662', p: 7 },
  { brand: '산지직송', name: '햇양파 1.5kg (국내산)', pct: '12', price: '3,290', orig: '3,740', review: '421', p: 8 },
  { brand: '풀무원', name: '국산콩 부침용 두부 300g', pct: '15', price: '1,690', orig: '1,990', review: '894', p: 9 },
]
