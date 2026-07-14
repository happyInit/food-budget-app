import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { homeDeals, img } from '../lib/data'

const pad = (n: number) => String(n).padStart(2, '0')

export default function Hotdeal() {
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  const [cd, setCd] = useState({ h: 0, m: 0, s: 0, hoursLeft: 0 })

  useEffect(() => {
    const tick = () => {
      const now = new Date()
      const target = new Date(now)
      target.setHours(17, 0, 0, 0)
      if (target.getTime() <= now.getTime()) target.setDate(target.getDate() + 1)
      let diff = Math.floor((target.getTime() - now.getTime()) / 1000)
      const h = Math.floor(diff / 3600)
      diff -= h * 3600
      const m = Math.floor(diff / 60)
      const s = diff - m * 60
      setCd({ h, m, s, hoursLeft: Math.max(1, Math.ceil((h * 3600 + m * 60 + s) / 3600)) })
    }
    tick()
    const id = window.setInterval(tick, 1000)
    return () => window.clearInterval(id)
  }, [])

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 6 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>핫딜</h1>
        <button onClick={() => setOpen((o) => !o)} style={{ padding: '8px 13px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#5E5E5E', fontSize: 12.5, fontWeight: 700, cursor: 'pointer' }}>
          {open ? '마감특가 닫기' : '마감특가 미리보기'}
        </button>
      </div>
      <p style={{ fontSize: 13.5, color: '#5E5E5E', margin: '0 0 8px' }}>오후 5시부터 자정까지, 하루 한 번 열리는 마감특가예요.</p>

      {!open ? (
        <div style={{ textAlign: 'center', padding: '44px 20px 64px' }}>
          <div style={{ position: 'relative', width: 184, height: 184, margin: '0 auto 30px' }}>
            <div style={{ position: 'absolute', inset: 0, borderRadius: '50%', background: `conic-gradient(#F26419 ${(1 - cd.hoursLeft / 24) * 360}deg,#E6E6E6 0)` }} />
            <div style={{ position: 'absolute', inset: 13, borderRadius: '50%', background: '#FAF8F5', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#9A9A9A', letterSpacing: '1.5px' }}>ONLY</div>
              <div className="num" style={{ fontSize: 54, fontWeight: 800, color: '#17264A', lineHeight: 1 }}>{cd.hoursLeft}</div>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#9A9A9A' }}>hour</div>
            </div>
          </div>
          <div style={{ fontSize: 15, color: '#5E5E5E', marginBottom: 5 }}><b style={{ color: '#F26419' }}>오후 5시</b>부터 <b style={{ color: '#F26419' }}>자정</b>까지 만날 수 있는!</div>
          <div style={{ fontSize: 21, fontWeight: 800, marginBottom: 24 }}>마감특가 오픈까지 남은시간</div>
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 9 }}>
            {[pad(cd.h), pad(cd.m), pad(cd.s)].map((v, i) => (
              <span key={i} style={{ display: 'contents' }}>
                {i > 0 && <span style={{ fontSize: 24, fontWeight: 800 }}>:</span>}
                <div className="num" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minWidth: 46, height: 58, background: '#17264A', color: '#fff', fontSize: 27, fontWeight: 800 }}>{v}</div>
              </span>
            ))}
          </div>
        </div>
      ) : (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, background: '#17264A', color: '#fff', padding: '15px 20px', margin: '12px 0 24px' }}>
            <span style={{ width: 9, height: 9, borderRadius: '50%', background: '#F26419', flexShrink: 0 }} />
            <div style={{ flex: 1, fontSize: 14.5, fontWeight: 700 }}>지금 마감특가 오픈중 · 자정에 마감돼요</div>
            <div className="num" style={{ fontSize: 15, fontWeight: 800, color: '#F7A968' }}>{pad(cd.h)}:{pad(cd.m)}:{pad(cd.s)}</div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(180px,1fr))', gap: 20 }}>
            {homeDeals.map((d) => (
              <div key={d.name} onClick={() => nav('/cart')} style={{ cursor: 'pointer' }}>
                <div style={{ aspectRatio: '1', overflow: 'hidden', background: `#F0F0F0 center/cover no-repeat url("${img(d.p)}")` }} />
                <div style={{ marginTop: 11 }}>
                  <div style={{ fontSize: 12, color: '#9A9A9A' }}>{d.brand}</div>
                  <div style={{ fontSize: 14, fontWeight: 600, marginTop: 3, lineHeight: 1.4 }}>{d.name}</div>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 7 }}>
                    <span className="num" style={{ fontSize: 16, fontWeight: 800, color: '#F04452' }}>{d.pct}%</span>
                    <span className="num" style={{ fontSize: 16, fontWeight: 800 }}>{d.price}원</span>
                  </div>
                  <div className="num" style={{ fontSize: 12, color: '#B5B5B5', textDecoration: 'line-through' }}>{d.orig}원</div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
