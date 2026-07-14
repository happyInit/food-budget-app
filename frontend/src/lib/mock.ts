// ── mock 데이터 (백엔드 연동 전 임시. 나중에 hooks/TanStack Query로 교체) ──

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

export const homeData = {
  budget: { remaining: '183,000', total: '460,000', percent: 40, daily: '15,250', save: '38,000' },
  stats: [
    { k: '냉장고 임박', v: '2', unit: '개', m: '2일 내 소진', tone: 'warn' as const },
    { k: '오늘 추천', v: '4', unit: '개', m: '재고·예산 기반', tone: 'sub' as const },
    { k: '이번 달 지출', v: '₩277k', unit: '', m: '외식 ₩84k', tone: 'sub' as const },
    { k: '안 버린 재료', v: '92', unit: '%', m: '지난달 +7%p', tone: 'brand' as const },
  ],
  cheap: [
    { name: '애호박', sub: '300g · 오아시스', dl: '-22%', price: '₩1,290', emoji: '🥬' },
    { name: '돼지고기 300g', sub: '마켓컬리', dl: '-18%', price: '₩4,900', emoji: '🥩' },
    { name: '계란 한판', sub: '타임세일 · 오아시스', dl: '-30%', price: '₩5,900', emoji: '🥚' },
  ],
  expiring: [
    { name: '대파', sub: '냉장 · 오늘 쓰기 좋아요', dday: 'D-1', tone: 'danger' as const, emoji: '🧅' },
    { name: '두부', sub: '냉장 · 1모', dday: 'D-2', tone: 'warn' as const, emoji: '🍚' },
  ],
  recommend: [
    { name: '돼지고기 김치찌개', sub: '보유 3 · 부족 2 · ₩8,200', emoji: '🍲' },
    { name: '대파 계란말이', sub: '보유 4 · 부족 0 · ₩0', emoji: '🍳' },
  ],
}

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

export const recipes = [
  { id: 'kimchi', name: '돼지고기 김치찌개', min: 25, have: 3, total: 5, emoji: '🍲', tag: '부족 ₩8,200', tone: 'danger' },
  { id: 'egg', name: '대파 계란말이', min: 10, have: 4, total: 4, emoji: '🍳', tag: '바로 가능', tone: 'brand' },
  { id: 'jeyuk', name: '제육볶음', min: 20, have: 2, total: 6, emoji: '🥘', tag: '부족 ₩6,400', tone: 'danger' },
  { id: 'bokkeum', name: '김치볶음밥', min: 15, have: 4, total: 5, emoji: '🍚', tag: '부족 ₩1,200', tone: 'warn' },
  { id: 'noodle', name: '잔치국수', min: 15, have: 3, total: 5, emoji: '🍜', tag: '부족 ₩2,100', tone: 'warn' },
  { id: 'salad', name: '두부 샐러드', min: 10, have: 3, total: 4, emoji: '🥗', tag: '바로 가능', tone: 'brand' },
  { id: 'jeon', name: '애호박전', min: 15, have: 3, total: 4, emoji: '🥞', tag: '부족 ₩900', tone: 'warn' },
  { id: 'curry', name: '카레라이스', min: 30, have: 2, total: 6, emoji: '🍛', tag: '부족 ₩5,800', tone: 'danger' },
]
export const recipeFilters = ['전체', '🧊 냉장고 재료로', '💸 ₩5,000 이하', '⏱ 20분 이내', '한식', '1인분']

export const recipeDetail = {
  name: '돼지고기 김치찌개', min: 25, serv: 2, level: '쉬움', emoji: '🍲',
  ingredients: [
    { name: '돼지고기 300g', state: '부족', store: '마켓컬리 최저', price: '₩4,900', emoji: '🥩' },
    { name: '김치 1/4포기', state: '부족', store: '오아시스 최저', price: '₩3,300', emoji: '🥬' },
    { name: '대파 1대', state: '보유', store: '냉장고 · D-1', price: '', emoji: '🧅' },
    { name: '두부 1/2모', state: '보유', store: '냉장고 · D-2', price: '', emoji: '🍚' },
  ],
  total: '₩8,200',
  steps: [
    '돼지고기를 한입 크기로 썰고 김치와 함께 볶아요.',
    '물 400ml를 붓고 두부·대파를 넣어 끓여요.',
    '중불로 10분, 간을 보고 마무리해요.',
  ],
}

export const mealPlan = [
  { name: '돼지고기 김치찌개', sub: '대파 D-1 소진 · 25분', have: 3, short: 2, add: '+₩8,200', emoji: '🍲' },
  { name: '대파 계란말이', sub: '대파·계란 소진 · 10분', have: 4, short: 0, add: '+₩0', emoji: '🍳' },
  { name: '김치볶음밥', sub: '두부 대체 활용 · 15분', have: 4, short: 1, add: '+₩1,200', emoji: '🍚' },
]

export const cart = {
  items: [
    { name: '돼지고기 300g', recipe: '김치찌개', store: '마켓컬리', price: '₩4,900', emoji: '🥩' },
    { name: '김치 1/4포기', recipe: '김치찌개', store: '오아시스', price: '₩3,300', emoji: '🥬' },
    { name: '계란 한판', recipe: '계란말이', store: '마켓컬리', price: '₩5,900', emoji: '🥚' },
  ],
  total: '14,100', remaining: '183,000', percent: 8, after: '168,900',
}

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

export const recipebook = [
  { id: 'kimchi', name: '돼지고기 김치찌개', sub: '만개의레시피 · 저장', emoji: '🍲', tag: '' },
  { id: 'egg', name: '백종원 계란찜', sub: '영상 추출 · 공개', emoji: '🎬', tag: 'YouTube' },
  { id: 'jeyuk', name: '엄마표 제육볶음', sub: '직접 작성 · 비공개', emoji: '🥘', tag: '' },
  { id: 'bokkeum', name: '자취 김치볶음밥', sub: '영상 추출', emoji: '🎬', tag: 'YouTube' },
]

export const hotdeal = {
  time: [
    { name: '부라타치즈 1박스', sub: '100g×6 · 오아시스', dl: '-47%', price: '₩21,600', emoji: '🧀' },
    { name: '유기농 올리브유 500ml', sub: '오아시스', dl: '-46%', price: '₩18,900', emoji: '🫒' },
    { name: '고산지 바나나', sub: '오아시스', dl: '-30%', price: '₩3,590', emoji: '🍌' },
  ],
  close: [
    { name: '전골용 채소와 버섯', sub: '470g · ⏰ 23:59 마감', dl: '-40%', price: '₩4,500', recipe: '🍲 된장찌개', emoji: '🥬' },
  ],
}

export const chat = [
  { me: false, text: '안녕하세요! 냉장고에 대파·두부·계란이 있고, 이번 달 예산은 ₩183,000 남았어요. 뭘 도와드릴까요?' },
  { me: true, text: '이번 주 3만원으로 3일치 저녁 짜줘' },
  { me: false, text: '좋아요. 임박한 대파(D-1)부터 쓰는 3일 플랜이에요 👇\n· 월: 김치찌개 ₩8,200\n· 화: 계란말이 ₩0 (보유)\n· 수: 제육볶음 ₩6,400\n합계 ₩14,600 — 예산 안에서 충분해요. 장바구니에 담을까요?' },
  { me: true, text: '응 담아줘' },
]
