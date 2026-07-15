// 알림(notify 서비스) 표현 헬퍼 — Notifications 페이지 + NotificationPanel 공용.
import type { AppNotification, NotificationType } from './api'

// 타입별 강조색(점·제목). notify.notification.type CHECK 4종.
export const NOTIF_COLOR: Record<NotificationType, string> = {
  EXPIRING: '#F04452', // 소비기한 임박
  LOW_PRICE: '#F26419', // 최저가 알림
  HOTDEAL: '#F26419', // 핫딜
  BUDGET: '#1E5F96', // 예산
}

// 클릭 시 이동 경로 — payload에 명시 라우트가 없으므로 타입으로 추론.
export const notifTarget = (n: AppNotification): string => {
  switch (n.type) {
    case 'EXPIRING':
      return '/pantry'
    case 'LOW_PRICE':
    case 'HOTDEAL':
      return '/hotdeal'
    case 'BUDGET':
      return '/expense'
    default:
      return '/notifications'
  }
}

// created_at(ISO) → '방금 · N분 전 · N시간 전 · 어제 · N일 전'
export function timeAgo(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const sec = Math.max(0, Math.floor((Date.now() - then) / 1000))
  if (sec < 60) return '방금'
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}분 전`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}시간 전`
  const day = Math.floor(hr / 24)
  if (day === 1) return '어제'
  if (day < 7) return `${day}일 전`
  return `${Math.floor(day / 7)}주 전`
}
