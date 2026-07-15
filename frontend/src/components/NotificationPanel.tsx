import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useNotifications, useMarkNotificationRead } from '../lib/queries'
import { notifTarget } from '../lib/notify'
import NotificationRow from './NotificationRow'

const DISPLAY = { fontFamily: 'var(--font-display)' } as const

// 알림 — 헤더에서 여는 팝오버 패널. 실 notify 서비스(#41~42) 연결.
// 데스크톱=우상단 드롭다운, 모바일=폭이 화면에 맞춰 시트처럼 꽉 참.
export default function NotificationPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const nav = useNavigate()
  const { data, isLoading, error } = useNotifications()
  const markRead = useMarkNotificationRead()

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  const list = data?.notifications ?? []
  const unread = list.filter((n) => !n.is_read)

  const go = (to: string, id?: number) => {
    if (id != null) markRead.mutate(id)
    onClose()
    nav(to)
  }

  return (
    <>
      {/* 바깥 클릭 닫기 (투명) */}
      <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 44 }} />
      <div
        role="dialog"
        aria-label="알림"
        style={{
          position: 'fixed', top: 64, right: 8, zIndex: 45,
          width: 'min(400px, calc(100vw - 16px))',
          maxHeight: 'calc(100dvh - 84px)',
          background: '#fff', border: '1px solid #E6E6E6', boxShadow: '0 24px 60px rgba(23,38,74,.28)',
          display: 'flex', flexDirection: 'column', overflow: 'hidden', animation: 'chatPop .22s ease',
        }}
      >
        {/* 헤더 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, background: '#17264A', color: '#fff', padding: '13px 16px', flexShrink: 0 }}>
          <span style={{ ...DISPLAY, fontSize: 16 }}>알림</span>
          <span style={{ fontSize: 11.5, color: 'rgba(255,255,255,.6)' }}>{unread.length ? `안 읽음 ${unread.length}건` : `${list.length}건`}</span>
          <button onClick={onClose} aria-label="닫기" style={{ marginLeft: 'auto', width: 26, height: 26, border: 'none', background: 'rgba(255,255,255,.14)', color: '#fff', fontSize: 13, cursor: 'pointer' }}>✕</button>
        </div>
        {/* 리스트 */}
        <div style={{ overflowY: 'auto', padding: '4px 16px 8px' }}>
          {isLoading && <div style={{ padding: '24px 0', color: '#9A9A9A', fontSize: 13, textAlign: 'center' }}>불러오는 중…</div>}
          {error && <div style={{ padding: '24px 0', color: '#F04452', fontSize: 13, textAlign: 'center' }}>알림을 불러오지 못했어요</div>}
          {!isLoading && !error && list.length === 0 && (
            <div style={{ padding: '32px 0', color: '#9A9A9A', fontSize: 13, textAlign: 'center' }}>새 알림이 없어요</div>
          )}
          {list.map((n, i) => (
            <NotificationRow key={n.id} n={n} last={i === list.length - 1} compact onClick={() => go(notifTarget(n), n.is_read ? undefined : n.id)} />
          ))}
        </div>
        {/* 하단 */}
        <div style={{ borderTop: '1px solid #E6E6E6', padding: '10px 16px', flexShrink: 0, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span
            onClick={() => unread.forEach((n) => markRead.mutate(n.id))}
            style={{ fontSize: 12.5, color: unread.length ? '#F26419' : '#C4C4C4', fontWeight: 600, cursor: unread.length ? 'pointer' : 'default' }}
          >
            모두 읽음
          </span>
          <span onClick={() => go('/notifications')} style={{ fontSize: 12.5, color: '#9A9A9A', cursor: 'pointer' }}>전체 보기 ›</span>
        </div>
      </div>
    </>
  )
}
