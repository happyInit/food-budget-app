import { useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { TOP_NAV, DRAWER_GROUPS } from '../../lib/nav'
import ChatWidget from '../ChatWidget'

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
  const [drawer, setDrawer] = useState(false)
  const [chat, setChat] = useState(false)
  const loc = useLocation()
  const nav = useNavigate()

  return (
    <div style={{ minHeight: '100vh', background: '#fff' }}>
      {/* GNB 헤더 (64px, sticky) */}
      <header style={{ background: '#fff', borderBottom: '1px solid #E6E6E6', position: 'sticky', top: 0, zIndex: 30 }}>
        <div
          style={{ maxWidth: 1080, margin: '0 auto', padding: '0 24px', height: 64, display: 'flex', alignItems: 'center', gap: 26 }}
        >
          <div
            onClick={() => nav('/home')}
            style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 21, fontWeight: 800, color: '#F26419', letterSpacing: '-.7px', cursor: 'pointer', flexShrink: 0 }}
          >
            <img src="/icons/pug.png" alt="파그" style={{ width: 30, height: 30, borderRadius: '50%', objectFit: 'cover' }} />
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

          {/* 우측: 알림/장바구니/마이/전체 */}
          <div
            style={{ display: 'flex', alignItems: 'center', gap: 20, marginLeft: 'auto', flexShrink: 0, fontSize: 14, fontWeight: 600, color: '#5E5E5E' }}
          >
            <span onClick={() => nav('/notifications')} style={{ position: 'relative', cursor: 'pointer' }} className="hidden min-[900px]:inline">
              알림
              <span style={{ position: 'absolute', top: -3, right: -8, width: 6, height: 6, borderRadius: '50%', background: '#F04452' }} />
            </span>
            <span onClick={() => nav('/cart')} style={{ cursor: 'pointer' }}>
              장바구니
            </span>
            <span onClick={() => nav('/my')} style={{ cursor: 'pointer' }} className="hidden min-[900px]:inline">
              마이
            </span>
            <span onClick={() => setDrawer(true)} style={{ cursor: 'pointer', color: '#9A9A9A' }}>
              전체
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
          <img src="/icons/pug.png" alt="파그" style={{ width: 52, height: 52, objectFit: 'cover', borderRadius: '50%' }} />
        )}
      </button>

      {/* 모바일 드로어 */}
      {drawer && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 60 }}>
          <div onClick={() => setDrawer(false)} style={{ position: 'absolute', inset: 0, background: 'rgba(20,20,20,.5)' }} />
          <aside
            style={{ position: 'absolute', top: 0, left: 0, bottom: 0, width: 280, maxWidth: '82%', background: '#fff', overflowY: 'auto', padding: '20px 0' }}
          >
            <div style={{ padding: '0 20px 16px', display: 'flex', alignItems: 'center', gap: 8, fontSize: 20, fontWeight: 800, color: '#F26419' }}>
              <img src="/icons/pug.png" alt="" style={{ width: 28, height: 28, borderRadius: '50%' }} />
              밀플래닝
            </div>
            {DRAWER_GROUPS.map((g) => (
              <div key={g.label} style={{ marginBottom: 10 }}>
                <div style={{ padding: '8px 20px 4px', fontSize: 11.5, fontWeight: 700, color: '#9A9A9A' }}>{g.label}</div>
                {g.items.map((it) => {
                  const active = loc.pathname === it.to
                  return (
                    <button
                      key={it.to}
                      onClick={() => {
                        nav(it.to)
                        setDrawer(false)
                      }}
                      style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '10px 20px', border: 'none', fontSize: 14, cursor: 'pointer', textAlign: 'left', background: active ? '#FCEBDD' : 'none', color: active ? '#F26419' : '#5E5E5E', fontWeight: active ? 700 : 500 }}
                    >
                      {it.label}
                      {'dot' in it && it.dot && <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#F04452' }} />}
                    </button>
                  )
                })}
              </div>
            ))}
          </aside>
        </div>
      )}
    </div>
  )
}
