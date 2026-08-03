// 확정본 GNB(상단 탭) + 모바일 드로어(4그룹). 아이콘 미사용 — 텍스트로만.

export const TOP_NAV = [
  { to: '/home', label: '홈' },
  { to: '/recipes', label: '레시피' },
  { to: '/mealplan', label: '뭐 해먹지' },
  { to: '/pantry', label: '내 냉장고' },
  { to: '/hotdeal', label: '핫딜' },
  { to: '/expense', label: '식비관리' },
  { to: '/recipebook', label: '레시피북' },
] as const

export const DRAWER_GROUPS = [
  {
    label: '메인',
    items: [
      { to: '/home', label: '홈 대시보드' },
      { to: '/recipes', label: '레시피 탐색' },
      { to: '/pantry', label: '내 냉장고', dot: true },
      { to: '/mealplan', label: '밀플래닝' },
      { to: '/cart', label: '장바구니' },
    ],
  },
  {
    label: '예산 · 식비',
    items: [
      { to: '/expense', label: '식비 캘린더' },
      { to: '/performance', label: '성과지표' },
    ],
  },
  {
    label: '가격 · 딜',
    items: [{ to: '/hotdeal', label: '핫딜 · 시세' }],
  },
  {
    label: '내 콘텐츠',
    items: [
      { to: '/recipebook', label: '내 레시피북' },
      { to: '/my', label: '마이페이지' },
    ],
  },
] as const
