import { useNavigate } from 'react-router-dom'
import { useNotifications, useMarkNotificationRead } from '../lib/queries'
import { NOTIF_COLOR, notifTarget, timeAgo } from '../lib/notify'

export default function Notifications() {
  const nav = useNavigate()
  const { data, isLoading, error } = useNotifications()
  const markRead = useMarkNotificationRead()

  const list = data?.notifications ?? []
  const unread = list.filter((n) => !n.is_read)

  const open = (id: number, to: string) => {
    if (!markRead.isPending) markRead.mutate(id)
    nav(to)
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 18 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>알림</h1>
        {unread.length > 0 && (
          <span
            onClick={() => unread.forEach((n) => markRead.mutate(n.id))}
            style={{ fontSize: 13, color: '#F26419', fontWeight: 600, cursor: 'pointer' }}
          >
            모두 읽음 ({unread.length})
          </span>
        )}
      </div>

      {isLoading && <div style={{ color: '#9A9A9A', padding: '40px 4px' }}>불러오는 중…</div>}
      {error && (
        <div style={{ padding: '30px 4px' }}>
          <div style={{ color: '#F04452', fontWeight: 700, marginBottom: 6 }}>알림을 불러오지 못했어요</div>
          <div style={{ color: '#9A9A9A', fontSize: 13 }}>{error.message}</div>
        </div>
      )}

      {!isLoading && !error && list.length === 0 && (
        <div style={{ maxWidth: 640, textAlign: 'center', padding: '56px 20px', background: '#FAFAFA', border: '1px solid #EFEFEF' }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#17264A', marginBottom: 6 }}>새 알림이 없어요</div>
          <div style={{ fontSize: 13, color: '#9A9A9A' }}>최저가·소비기한·예산 알림이 오면 여기에 표시돼요.</div>
        </div>
      )}

      {list.length > 0 && (
        <div style={{ maxWidth: 640, background: '#fff', border: '1px solid #E6E6E6', padding: '8px 20px' }}>
          {list.map((n, i) => {
            const color = NOTIF_COLOR[n.type]
            return (
              <div key={n.id} onClick={() => open(n.id, notifTarget(n))} style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '14px 0', borderBottom: i < list.length - 1 ? '1px solid #EFEFEF' : 'none', cursor: 'pointer', opacity: n.is_read ? 0.6 : 1 }}>
                <span style={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0, background: n.is_read ? '#D4D4D4' : color }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: n.is_read ? 500 : 600, color: n.is_read ? '#5E5E5E' : color }}>{n.title}</div>
                  {n.body && <div style={{ fontSize: 12, color: '#9A9A9A', marginTop: 2 }}>{n.body}</div>}
                </div>
                <span style={{ fontSize: 11, color: '#9A9A9A', whiteSpace: 'nowrap' }}>{timeAgo(n.created_at)}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
