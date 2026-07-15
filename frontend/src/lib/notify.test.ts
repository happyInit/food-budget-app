// notify.ts 순수 로직 테스트 (vitest) — 알림 타입→라우트 매핑 + 상대시각 포맷.
// pantry.ts/auth.ts 처럼 리터럴로 검증(독립 소스). timeAgo 는 Date.now() 를 읽으므로
// 가짜 타이머로 '지금'을 고정해 6분기를 결정적으로 검증한다(frontend/README §테스트 컨벤션).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import type { AppNotification, NotificationType } from './api'
import { notifTarget, timeAgo } from './notify'

// notifTarget 은 type 만 본다 — 최소 객체로 검증(나머지 필드는 무관).
const notif = (type: string): AppNotification =>
  ({ id: 1, type: type as NotificationType, title: 't', is_read: false, created_at: '' }) as AppNotification

describe('notifTarget', () => {
  it('routes by notification type', () => {
    expect(notifTarget(notif('EXPIRING'))).toBe('/pantry')
    expect(notifTarget(notif('LOW_PRICE'))).toBe('/hotdeal')
    expect(notifTarget(notif('HOTDEAL'))).toBe('/hotdeal')
    expect(notifTarget(notif('BUDGET'))).toBe('/expense')
  })
  it('falls back to /notifications for unknown type', () => {
    expect(notifTarget(notif('WHATEVER'))).toBe('/notifications')
  })
})

describe('timeAgo', () => {
  const NOW = new Date('2026-07-15T12:00:00Z').getTime()
  const SEC = 1000, MIN = 60 * SEC, HR = 60 * MIN, DAY = 24 * HR
  const ago = (ms: number) => new Date(NOW - ms).toISOString() // NOW 기준 ms 전의 ISO

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(NOW) // Date.now() = NOW 로 고정
  })
  afterEach(() => vi.useRealTimers())

  it('empty string for unparseable input', () => expect(timeAgo('nope')).toBe(''))
  it('방금 under a minute (future clamps to 0)', () => {
    expect(timeAgo(ago(30 * SEC))).toBe('방금')
    expect(timeAgo(ago(-5 * MIN))).toBe('방금') // 미래 created_at 도 음수 clamp → 방금
  })
  it('N분 전 under an hour', () => expect(timeAgo(ago(5 * MIN))).toBe('5분 전'))
  it('N시간 전 under a day', () => expect(timeAgo(ago(3 * HR))).toBe('3시간 전'))
  it('어제 at one day', () => expect(timeAgo(ago(25 * HR))).toBe('어제'))
  it('N일 전 within a week', () => expect(timeAgo(ago(3 * DAY))).toBe('3일 전'))
  it('N주 전 beyond a week', () => expect(timeAgo(ago(14 * DAY))).toBe('2주 전'))
})
