import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { img } from '../lib/data'
import { won } from '../lib/api'
import { useHotdeals } from '../lib/queries'

const pad = (n: number) => String(n).padStart(2, '0')
const SRC_LABEL: Record<string, string> = { kurly: '컬리', oasis: '오아시스' }
const OPEN_HOUR = 17 // 마감특가 = 매일 17시~자정

export default function Hotdeal() {
  const nav = useNavigate()
  // 오픈 전 '미리보기'로 딜을 미리 볼 수 있는 수동 토글 (오픈 시간엔 무시됨)
  const [preview, setPreview] = useState(false)
  // live = 지금이 오픈 시간(17~24시)인가. 매 초 시계로 갱신 → 5시 되면 자동 오픈.
  const [cd, setCd] = useState({ h: 0, m: 0, s: 0, hoursLeft: 0, live: false })
  const { data, error, isLoading: loading } = useHotdeals(24)
  const deals = data?.deals ?? []

  useEffect(() => {
    const tick = () => {
      const now = new Date()
      const live = now.getHours() >= OPEN_HOUR // 17:00~23:59 = 오픈, 자정 지나면 false
      const target = new Date(now)
      if (live) {
        target.setHours(24, 0, 0, 0) // 오픈 중 → 자정(마감)까지 카운트
      } else {
        target.setHours(OPEN_HOUR, 0, 0, 0) // 오픈 전 → 다음 17시까지 카운트
        if (target.getTime() <= now.getTime()) target.setDate(target.getDate() + 1)
      }
      let diff = Math.max(0, Math.floor((target.getTime() - now.getTime()) / 1000))
      const h = Math.floor(diff / 3600)
      diff -= h * 3600
      const m = Math.floor(diff / 60)
      const s = diff - m * 60
      setCd({ h, m, s, hoursLeft: Math.max(1, Math.ceil((h * 3600 + m * 60 + s) / 3600)), live })
    }
    tick()
    const id = window.setInterval(tick, 1000)
    return () => window.clearInterval(id)
  }, [])

  // 오픈 시간이면 자동으로, 아니면 '미리보기' 눌렀을 때만 딜 노출
  const showDeals = cd.live || preview

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 6 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>핫딜</h1>
        {cd.live ? (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '7px 12px', background: '#FCEBDD', color: '#F26419', fontSize: 12.5, fontWeight: 800 }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#F26419' }} />지금 오픈중
          </span>
        ) : (
          <button onClick={() => setPreview((p) => !p)} style={{ padding: '8px 13px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#5E5E5E', fontSize: 12.5, fontWeight: 700, cursor: 'pointer' }}>
            {preview ? '미리보기 닫기' : `마감특가 미리보기${deals.length ? ` (${deals.length})` : ''}`}
          </button>
        )}
      </div>
      <p style={{ fontSize: 13.5, color: '#5E5E5E', margin: '0 0 8px' }}>오후 5시부터 자정까지, 하루 한 번 열리는 마감특가예요.</p>

      {!showDeals ? (
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
            <div style={{ flex: 1, fontSize: 14.5, fontWeight: 700 }}>
              {cd.live ? '지금 마감특가 오픈중 · 자정에 마감돼요' : '오픈 전 미리보기 · 오후 5시에 정식 오픈해요'}
            </div>
            {cd.live && <div className="num" style={{ fontSize: 15, fontWeight: 800, color: '#F7A968' }}>마감까지 {pad(cd.h)}:{pad(cd.m)}:{pad(cd.s)}</div>}
          </div>

          {loading && <div style={{ color: '#9A9A9A', fontSize: 14, padding: '8px 2px' }}>마감특가 불러오는 중…</div>}
          {error && <div style={{ color: '#F04452', fontSize: 14, padding: '8px 2px' }}>핫딜 서버에 연결할 수 없어요 ({error.message})</div>}
          {!loading && !error && deals.length === 0 && <div style={{ color: '#9A9A9A', fontSize: 14, padding: '8px 2px' }}>지금은 열린 마감특가가 없어요.</div>}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(180px,1fr))', gap: 20 }}>
            {deals.map((d, i) => (
              <div key={d.retail_product_id} onClick={() => nav('/cart')} style={{ cursor: 'pointer', opacity: d.is_sold_out ? 0.5 : 1 }}>
                <div className="zoom-wrap" style={{ position: 'relative', aspectRatio: '1', background: '#F0F0F0' }}>
                  <div className="zoom" style={{ position: 'absolute', inset: 0, background: `center/cover no-repeat url("${d.image_url || img(i)}")` }} />
                  {d.is_sold_out && <div style={{ position: 'absolute', inset: 0, background: 'rgba(23,38,74,.55)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: 15 }}>품절</div>}
                </div>
                <div style={{ marginTop: 11 }}>
                  <div style={{ fontSize: 12, color: '#9A9A9A' }}>{SRC_LABEL[d.source] ?? d.source}</div>
                  <div style={{ fontSize: 14, fontWeight: 600, marginTop: 3, lineHeight: 1.4, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{d.name}</div>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 7 }}>
                    {d.discount_rate != null && <span className="num" style={{ fontSize: 16, fontWeight: 800, color: '#F04452' }}>{d.discount_rate}%</span>}
                    <span className="num" style={{ fontSize: 16, fontWeight: 800 }}>{won(d.price)}원</span>
                  </div>
                  {d.original_price != null && d.original_price > d.price && (
                    <div className="num" style={{ fontSize: 12, color: '#B5B5B5', textDecoration: 'line-through' }}>{won(d.original_price)}원</div>
                  )}
                  {d.unit_price != null && d.unit_basis && (
                    <div className="num" style={{ fontSize: 11, color: '#9A9A9A', marginTop: 2 }}>{won(d.unit_price)}원/{d.unit_basis}</div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
