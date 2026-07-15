import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

const DISPLAY = { fontFamily: 'var(--font-display)' } as const

// 알림 — 페이지 이동 대신 헤더에서 여는 팝오버 패널.
// 데스크톱=우상단 드롭다운, 모바일=폭이 화면에 맞춰 시트처럼 꽉 참.
const list = [
  { to: '/pantry', title: '두부 유통기한 임박', desc: '내일 만료 · 두부 레시피 3개 추천', time: '1시간 전', color: '#F04452' },
  { to: '/hotdeal', title: '삼겹살 최저가 알림', desc: '마켓컬리 100g 1,290원 (평균 대비 30%↓)', time: '3시간 전', color: '#F26419' },
  { to: '/recipebook', title: '박요리님이 레시피북을 공유했어요', desc: '"자취생 일주일 식단" · 7개 레시피', time: '5시간 전' },
  { to: '/expense', title: '오늘 식비 11,200원', desc: '이번 주 예산의 58% 사용', time: '어제' },
  { to: '/hotdeal', title: '오아시스 마감세일 업데이트', desc: '식품 핫딜 12개 · 17시 기준', time: '어제' },
]

export default function NotificationPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const nav = useNavigate()

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  const go = (to: string) => { onClose(); nav(to) }

  return (
    <>
      {/* 바깥 클릭 닫기 (투명) */}
      <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 44 }} />
      <div
        role="dialog"
        aria-label="알림"
        style={{
          // 우측 고정 + 뷰포트 캡 폭 — 데스크톱=400px, 모바일=좌우 8px 여백(min으로 캡)
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
          <span style={{ fontSize: 11.5, color: 'rgba(255,255,255,.6)' }}>{list.length}건</span>
          <button onClick={onClose} aria-label="닫기" style={{ marginLeft: 'auto', width: 26, height: 26, border: 'none', background: 'rgba(255,255,255,.14)', color: '#fff', fontSize: 13, cursor: 'pointer' }}>✕</button>
        </div>
        {/* 리스트 */}
        <div style={{ overflowY: 'auto', padding: '4px 16px 8px' }}>
          {list.map((n, i) => (
            <div key={i} onClick={() => go(n.to)} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '13px 0', borderBottom: i < list.length - 1 ? '1px solid #EFEFEF' : 'none', cursor: 'pointer' }}>
              <span style={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0, background: n.color ?? '#C4C4C4' }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13.5, fontWeight: 600, color: n.color ?? '#17264A' }}>{n.title}</div>
                <div style={{ fontSize: 11.5, color: '#9A9A9A', marginTop: 2 }}>{n.desc}</div>
              </div>
              <span style={{ fontSize: 11, color: '#9A9A9A', whiteSpace: 'nowrap', flexShrink: 0 }}>{n.time}</span>
            </div>
          ))}
        </div>
        {/* 하단 */}
        <div style={{ borderTop: '1px solid #E6E6E6', padding: '10px 16px', flexShrink: 0, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: 12.5, color: '#F26419', fontWeight: 600, cursor: 'pointer' }}>모두 읽음</span>
          <span onClick={() => go('/notifications')} style={{ fontSize: 12.5, color: '#9A9A9A', cursor: 'pointer' }}>전체 보기 ›</span>
        </div>
      </div>
    </>
  )
}
