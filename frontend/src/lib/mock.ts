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
