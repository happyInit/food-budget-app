import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { TOP_NAV, DRAWER_GROUPS } from '../../lib/nav'
import { useLogout, useNotifications } from '../../lib/queries'
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
  const [drawer, setDrawer] = useState(false) // 모바일 네비 드로어
  const [myMenu, setMyMenu] = useState(false)  // 데스크톱 '마이' 드롭다운
  const loc = useLocation()
  const nav = useNavigate()
  const { data: notifData } = useNotifications()
  const unreadCount = (notifData?.notifications ?? []).filter((n) => !n.is_read).length
  const doLogout = useLogout()
  const onLogout = async () => { setMyMenu(false); setDrawer(false); await doLogout(); nav('/') }
  useIdleLogout() // 30분 유휴 → 자동 로그아웃·랜딩 (+ refresh 하드만료 시 즉시)
  useEffect(() => { setDrawer(false); setMyMenu(false) }, [loc.pathname]) // 라우트 이동 시 드로어·메뉴 닫힘

  return (
    <div style={{ minHeight: '100vh', background: '#fff', overflowX: 'hidden' }}>
      {/* GNB 헤더 (64px, sticky) */}
      <header style={{ background: '#fff', borderBottom: '1px solid #E6E6E6', position: 'sticky', top: 0, zIndex: 30 }}>
        <div
          style={{ maxWidth: 1080, margin: '0 auto', padding: '0 24px', height: 64, display: 'flex', alignItems: 'center', gap: 26 }}
        >
          {/* 모바일 햄버거 — 데스크톱(≥900px)에선 숨김 */}
          <button
            onClick={() => setDrawer(true)}
            aria-label="메뉴 열기"
            className="min-[900px]:hidden"
            style={{ border: 'none', background: 'transparent', cursor: 'pointer', fontSize: 23, lineHeight: 1, padding: 4, marginLeft: -4, color: '#333', flexShrink: 0 }}
          >
            ☰
          </button>

          {/* 브랜드 → 홈 링크(밀플래닝·밥풀이 클릭 시 /home) */}
          <Link
            to="/home"
            style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 21, fontWeight: 800, color: '#F26419', letterSpacing: '-.7px', textDecoration: 'none', flexShrink: 0 }}
          >
            <img src="/icons/app-icon.png" alt="밥풀이" style={{ width: 30, height: 30, borderRadius: '50%', objectFit: 'cover' }} />
            밀플래닝
          </Link>

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
            <div className="hidden min-[900px]:block" style={{ position: 'relative' }}>
              <span onClick={() => setMyMenu((v) => !v)} style={{ cursor: 'pointer' }}>마이 ▾</span>
              {myMenu && (
                <>
                  {/* 바깥 클릭 시 닫힘 */}
                  <div onClick={() => setMyMenu(false)} style={{ position: 'fixed', inset: 0, zIndex: 40 }} />
                  <div style={{ position: 'absolute', top: '100%', right: 0, marginTop: 12, background: '#fff', border: '1px solid #E6E6E6', boxShadow: '0 8px 24px rgba(0,0,0,.12)', minWidth: 150, zIndex: 41 }}>
                    <button onClick={() => { setMyMenu(false); nav('/my') }} style={{ display: 'block', width: '100%', textAlign: 'left', padding: '11px 16px', fontSize: 13.5, fontWeight: 600, color: '#333', background: 'transparent', border: 'none', cursor: 'pointer' }}>내 정보 보기</button>
                    <button onClick={onLogout} style={{ display: 'block', width: '100%', textAlign: 'left', padding: '11px 16px', fontSize: 13.5, fontWeight: 600, color: '#C0392B', background: 'transparent', border: 'none', borderTop: '1px solid #EFEFEF', cursor: 'pointer' }}>로그아웃</button>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* 모바일 네비 드로어 — 데스크톱(≥900px)에선 숨김. 햄버거로 열림 */}
      {drawer && (
        <div className="min-[900px]:hidden">
          <div
            onClick={() => setDrawer(false)}
            style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.42)', zIndex: 48 }}
          />
          <aside
            style={{ position: 'fixed', top: 0, left: 0, bottom: 0, width: 284, maxWidth: '82vw', background: '#fff', zIndex: 49, boxShadow: '2px 0 26px rgba(0,0,0,.16)', overflowY: 'auto', padding: '16px 0 28px' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 20px 12px' }}>
              <span style={{ fontSize: 18, fontWeight: 800, color: '#F26419', letterSpacing: '-.5px' }}>메뉴</span>
              <button
                onClick={() => setDrawer(false)}
                aria-label="메뉴 닫기"
                style={{ border: 'none', background: 'transparent', cursor: 'pointer', fontSize: 20, color: '#5E5E5E', padding: 4, lineHeight: 1 }}
              >
                ✕
              </button>
            </div>
            {DRAWER_GROUPS.map((grp) => (
              <div key={grp.label} style={{ padding: '8px 0' }}>
                <div style={{ padding: '0 20px 4px', fontSize: 11.5, fontWeight: 700, color: '#9A9A9A', letterSpacing: '.2px' }}>{grp.label}</div>
                {grp.items.map((it) => (
                  <NavLink
                    key={it.to}
                    to={it.to}
                    onClick={() => setDrawer(false)}
                    style={({ isActive }) => ({
                      display: 'block',
                      padding: '11px 20px',
                      fontSize: 15,
                      textDecoration: 'none',
                      color: isActive ? '#F26419' : '#333',
                      fontWeight: isActive ? 700 : 500,
                      background: isActive ? '#FCEBDD' : 'transparent',
                    })}
                  >
                    {it.label}
                  </NavLink>
                ))}
              </div>
            ))}
            {/* 최하단 로그아웃 */}
            <div style={{ borderTop: '1px solid #EFEFEF', marginTop: 10, paddingTop: 10 }}>
              <button
                onClick={onLogout}
                style={{ display: 'block', width: '100%', textAlign: 'left', padding: '11px 20px', fontSize: 15, fontWeight: 600, color: '#C0392B', background: 'transparent', border: 'none', cursor: 'pointer' }}
              >
                로그아웃
              </button>
            </div>
          </aside>
        </div>
      )}

      {/* 콘텐츠 */}
      <main style={{ maxWidth: 1080, margin: '0 auto', width: '100%', padding: '28px 20px 80px', overflowX: 'hidden' }}>
        <div className="scr-anim" key={loc.pathname}>
          <Outlet />
        </div>
      </main>

      {/* 알림 팝오버 */}
      <NotificationPanel open={notif} onClose={() => setNotif(false)} />

      {/* 우하단 밥풀이 챗버블 — 클릭 시 그 자리 위로 챗 위젯 토글 */}
      <ChatWidget open={chat} onClose={() => setChat(false)} />
      <button
        onClick={() => setChat((c) => !c)}
        aria-label={chat ? '어시스턴트 닫기' : '어시스턴트 열기'}
        style={{ position: 'fixed', right: 26, bottom: 26, zIndex: 46, width: 60, height: 60, borderRadius: '50%', border: 'none', background: '#F26419', cursor: 'pointer', boxShadow: '0 12px 30px rgba(242,100,25,.42)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 0, overflow: 'hidden', transition: 'transform .2s' }}
      >
        {chat ? (
          <span style={{ color: '#fff', fontSize: 24, fontWeight: 700, lineHeight: 1 }}>✕</span>
        ) : (
          <img src="/icons/app-icon.png" alt="밥풀이" style={{ width: 52, height: 52, objectFit: 'cover', borderRadius: '50%' }} />
        )}
      </button>
    </div>
  )
}
