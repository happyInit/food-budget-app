import { useNavigate } from 'react-router-dom'
import { priceTrends } from '../lib/data'

const card: React.CSSProperties = { background: '#fff', border: '1px solid #E6E6E6' }
const spend: Record<number, string> = { 1: '8.2k', 2: '5.1k', 3: '12k', 5: '6.4k', 6: '9k', 7: '4.1k', 8: '7k', 9: '11k' }
const days = Array.from({ length: 31 }, (_, i) => i + 1)

export default function Expense() {
  const nav = useNavigate()
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 18 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>식비관리</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => nav('/performance')} style={{ padding: '10px 15px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#17264A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>성과 보기</button>
          <button onClick={() => nav('/expense/add')} style={{ padding: '10px 15px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>지출 기록</button>
        </div>
      </div>

      {/* 다크 예산 히어로 */}
      <div style={{ background: '#17264A', color: '#fff', padding: '24px 26px', marginBottom: 18, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 18 }}>
        <div>
          <div style={{ fontSize: 13, color: 'rgba(255,255,255,.6)', marginBottom: 8 }}>7월 남은 예산</div>
          <div className="num" style={{ fontSize: 32, fontWeight: 800, letterSpacing: '-1px' }}>182,400<span style={{ fontSize: 16, fontWeight: 600 }}>원</span></div>
          <div style={{ fontSize: 12.5, color: '#F7A968', marginTop: 6, fontWeight: 600 }}>이 페이스면 월말 +42,000원 절약 예상</div>
        </div>
        <div style={{ flex: 1, minWidth: 190, maxWidth: 300 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11.5, color: 'rgba(255,255,255,.55)', marginBottom: 6 }}>
            <span>지출 117,600원</span>
            <span>예산 300,000원</span>
          </div>
          <div style={{ height: 9, background: 'rgba(255,255,255,.16)', overflow: 'hidden' }}>
            <div style={{ height: '100%', width: '39%', background: '#F26419' }} />
          </div>
        </div>
      </div>

      {/* 캘린더 */}
      <div style={{ ...card, padding: 26 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <span style={{ fontSize: 19, fontWeight: 800 }}>‹ 2026. 7 ›</span>
          <span className="num" style={{ fontSize: 13, color: '#F26419', fontWeight: 700 }}>117,600원</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7,1fr)', gap: 6, textAlign: 'center' }}>
          {['일', '월', '화', '수', '목', '금', '토'].map((w) => (
            <div key={w} style={{ fontSize: 13.5, fontWeight: 700, color: '#9A9A9A', padding: '10px 0' }}>{w}</div>
          ))}
          <div /><div />
          {days.map((d) => {
            const today = d === 13
            const sp = spend[d]
            return (
              <div key={d} style={{ minHeight: 74, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', fontSize: today ? 12.5 : 17, background: today ? '#F26419' : 'transparent', color: today ? '#fff' : sp ? '#17264A' : '#B5B5B5', fontWeight: today ? 700 : 400 }}>
                {d}
                {sp && <span className="num" style={{ fontSize: today ? 9 : 11.5, color: today ? '#fff' : '#F26419', fontWeight: 700 }}>{sp}</span>}
              </div>
            )
          })}
        </div>
      </div>

      {/* 지출 구성 + 오늘 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(280px,1fr))', gap: 16, marginTop: 16 }}>
        <div style={{ ...card, padding: 22 }}>
          <h3 style={{ fontSize: 15, fontWeight: 800, margin: '0 0 16px' }}>이번 달 지출 구성</h3>
          {[['집밥 (재료비)', '68,400원 · 58%', 58, '#F26419'], ['외식', '35,000원 · 30%', 30, '#F26419'], ['카페 · 간식', '14,200원 · 12%', 12, '#B5B5B5']].map(([k, v, w, c]) => (
            <div key={k as string} style={{ marginBottom: 14 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 6 }}>
                <span style={{ fontWeight: 600 }}>{k}</span>
                <span className="num" style={{ color: '#5E5E5E' }}>{v}</span>
              </div>
              <div style={{ height: 8, background: '#EFEFEF', overflow: 'hidden' }}>
                <div style={{ height: '100%', width: (w as number) + '%', background: c as string }} />
              </div>
            </div>
          ))}
        </div>
        <div style={{ ...card, padding: 22 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <h3 style={{ fontSize: 15, fontWeight: 800, margin: 0 }}>7월 13일 · 오늘</h3>
            <span style={{ padding: '4px 10px', fontSize: 12, fontWeight: 700, background: '#FCEBDD', color: '#F26419' }}>11,200원</span>
          </div>
          {[['아침 · 계란말이', '집밥', '#1E5F96', '0원', '#1E5F96'], ['점심 · 김밥천국', '외식', '#F26419', '7,000원', '#17264A'], ['저녁 · 김치찌개', '집밥', '#1E5F96', '4,200원', '#17264A']].map(([t, tag, tagC, p, pC], i) => (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 0', fontSize: 13.5, borderTop: '1px solid #EFEFEF' }}>
              <span>{t} <span style={{ color: tagC as string, fontSize: 11 }}>{tag}</span></span>
              <span className="num" style={{ color: pC as string }}>{p}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 시세 스파크라인 */}
      <h2 style={{ fontSize: 17, fontWeight: 800, margin: '28px 0 14px' }}>재료 시세 · 최근 7일</h2>
      <div style={{ ...card, padding: '6px 20px' }}>
        {priceTrends.map((t) => (
          <div key={t.name} style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '15px 0', borderTop: '1px solid #EFEFEF' }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 14, fontWeight: 700 }}>{t.name}</div>
              <div style={{ fontSize: 12, color: '#9A9A9A', marginTop: 2 }}>{t.avg}</div>
            </div>
            <svg viewBox="0 0 72 24" width="72" height="24" style={{ flexShrink: 0 }}>
              <polyline points={t.pts} fill="none" stroke={t.up ? '#F04452' : '#F26419'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <div style={{ textAlign: 'right', minWidth: 92 }}>
              <div className="num" style={{ fontSize: 15, fontWeight: 800 }}>{t.price}</div>
              <div className="num" style={{ fontSize: 12, fontWeight: 700, color: t.up ? '#F04452' : '#1E5F96' }}>{t.delta}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
