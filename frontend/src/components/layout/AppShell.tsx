import { useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { TOP_NAV } from '../../lib/nav'
import { useNotifications } from '../../lib/queries'
import { useIdleLogout } from '../../lib/useIdleLogout'
import ChatWidget from '../ChatWidget'
import NotificationPanel from '../NotificationPanel'

const tabBase: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  height: 64,
  padding: '0 6px',
  fontSize: 14.5,
  whiteSpace: 'nowrap',
  cursor: 'pointer',
  borderBottom: '2px solid transparent',
  textDecoration: 'none',
}

export default function AppShell() {
  const [chat, setChat] = useState(false)
  const [notif, setNotif] = useState(false)
  const loc = useLocation()
  const nav = useNavigate()
  const { data: notifData } = useNotifications()
  const unreadCount = (notifData?.notifications ?? []).filter((n) => !n.is_read).length
  useIdleLogout() // 30분 유휴 → 자동 로그아웃·랜딩 (+ refresh 하드만료 시 즉시)

  return (
    <div style={{ minHeight: '100vh', background: '#fff', overflowX: 'hidden' }}>
      {/* GNB 헤더 (64px, sticky) */}
      <header style={{ background: '#fff', borderBottom: '1px solid #E6E6E6', position: 'sticky', top: 0, zIndex: 30 }}>
        <div
          style={{ maxWidth: 1080, margin: '0 auto', padding: '0 24px', height: 64, display: 'flex', alignItems: 'center', gap: 26 }}
        >
          <div
            onClick={() => nav('/home')}
            style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 21, fontWeight: 800, color: '#F26419', letterSpacing: '-.7px', cursor: 'pointer', flexShrink: 0 }}
          >
            <img src="/icons/app-icon.png" alt="파그" style={{ width: 30, height: 30, borderRadius: '50%', objectFit: 'cover' }} />
            밀플래닝
          </div>

          {/* 데스크톱 GNB 탭 */}
          <nav className="no-sb hidden min-[900px]:flex" style={{ alignItems: 'stretch', height: 64, gap: 2, overflowX: 'auto', flex: 1 }}>
            {TOP_NAV.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                style={({ isActive }) => ({
                  ...tabBase,
                  color: isActive ? '#F26419' : '#333',
                  fontWeight: isActive ? 700 : 600,
                  borderBottomColor: isActive ? '#F26419' : 'transparent',
                })}
              >
                {t.label}
              </NavLink>
            ))}
          </nav>

          {/* 우측: 알림/장바구니/마이 */}
          <div
            style={{ display: 'flex', alignItems: 'center', gap: 20, marginLeft: 'auto', flexShrink: 0, fontSize: 14, fontWeight: 600, color: '#5E5E5E' }}
          >
            <span onClick={() => setNotif((n) => !n)} style={{ position: 'relative', cursor: 'pointer' }}>
              알림
              {unreadCount > 0 && (
                <span style={{ position: 'absolute', top: -3, right: -8, width: 6, height: 6, borderRadius: '50%', background: '#F04452' }} />
              )}
            </span>
            <span onClick={() => nav('/cart')} style={{ cursor: 'pointer' }}>
              장바구니
            </span>
            <span onClick={() => nav('/my')} style={{ cursor: 'pointer' }} className="hidden min-[900px]:inline">
              마이
            </span>
          </div>
        </div>
      </header>

      {/* 콘텐츠 */}
      <main style={{ maxWidth: 1080, margin: '0 auto', width: '100%', padding: '28px 20px 80px', overflowX: 'hidden' }}>
        <div className="scr-anim" key={loc.pathname}>
          <Outlet />
        </div>
      </main>

      {/* 알림 팝오버 */}
      <NotificationPanel open={notif} onClose={() => setNotif(false)} />

      {/* 우하단 파그 챗버블 — 클릭 시 그 자리 위로 챗 위젯 토글 */}
      <ChatWidget open={chat} onClose={() => setChat(false)} />
      <button
        onClick={() => setChat((c) => !c)}
        aria-label={chat ? '어시스턴트 닫기' : '어시스턴트 열기'}
        style={{ position: 'fixed', right: 26, bottom: 26, zIndex: 46, width: 60, height: 60, borderRadius: '50%', border: 'none', background: '#F26419', cursor: 'pointer', boxShadow: '0 12px 30px rgba(242,100,25,.42)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 0, overflow: 'hidden', transition: 'transform .2s' }}
      >
        {chat ? (
          <span style={{ color: '#fff', fontSize: 24, fontWeight: 700, lineHeight: 1 }}>✕</span>
        ) : (
          <img src="/icons/app-icon.png" alt="파그" style={{ width: 52, height: 52, objectFit: 'cover', borderRadius: '50%' }} />
        )}
      </button>
    </div>
  )
}
