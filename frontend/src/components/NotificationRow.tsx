import type { AppNotification } from '../lib/api'
import { NOTIF_COLOR, timeAgo } from '../lib/notify'

// 알림 한 줄 — Notifications 페이지 + NotificationPanel 공용. 점·제목·본문·상대시각.
// 클릭 동작(읽음 처리 + 이동)은 화면마다 달라 부모가 onClick 으로 주입. compact = 패널용 소형.
export default function NotificationRow({ n, last, onClick, compact }: {
  n: AppNotification
  last: boolean
  onClick: () => void
  compact?: boolean
}) {
  const color = NOTIF_COLOR[n.type]
  // 이상탐지 알림(payload.anomaly) → 일반 최저가와 구분되는 배지. 역대최저 > 하락률 > 급락 순.
  const p = (n.payload ?? {}) as Record<string, unknown>
  const badge = p.anomaly
    ? (p.is_record_low ? '역대최저' : typeof p.drop_pct === 'number' ? `${p.drop_pct}%↓` : '급락')
    : null
  return (
    <div
      onClick={onClick}
      style={{ display: 'flex', alignItems: 'center', gap: compact ? 12 : 14, padding: compact ? '13px 0' : '14px 0', borderBottom: last ? 'none' : '1px solid #EFEFEF', cursor: 'pointer', opacity: n.is_read ? 0.6 : 1 }}
    >
      <span style={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0, background: n.is_read ? '#D4D4D4' : color }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          {badge && <span style={{ fontSize: 10, fontWeight: 800, color: '#fff', background: n.is_read ? '#C0C0C0' : '#F04452', padding: '1px 6px', flexShrink: 0 }}>{badge}</span>}
          <span style={{ fontSize: compact ? 13.5 : 14, fontWeight: n.is_read ? 500 : 600, color: n.is_read ? '#5E5E5E' : color }}>{n.title}</span>
        </div>
        {n.body && <div style={{ fontSize: compact ? 11.5 : 12, color: '#9A9A9A', marginTop: 2 }}>{n.body}</div>}
      </div>
      <span style={{ fontSize: 11, color: '#9A9A9A', whiteSpace: 'nowrap', flexShrink: 0 }}>{timeAgo(n.created_at)}</span>
    </div>
  )
}
