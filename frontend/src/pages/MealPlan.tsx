import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { img } from '../lib/data'
import { won } from '../lib/api'
import { useCart, useMealRecommend } from '../lib/queries'

// 접시 스캐터 위치 템플릿 (palmer-dinnerware 오마쥬) — 순수 레이아웃 좌표(데이터 아님).
// left=%(캔버스 기준)·top=px·size=px. 실 추천을 이 슬롯들에 얹는다(추천 수만큼만 렌더).
const POSITIONS = [
  { size: 190, left: '18%', top: 150 },
  { size: 176, left: '60%', top: 96 },
  { size: 150, left: '42%', top: 402 },
  { size: 130, left: '77%', top: 372 },
  { size: 126, left: '11%', top: 486 },
  { size: 118, left: '62%', top: 512 },
  { size: 102, left: '40%', top: 60 },
  { size: 94, left: '86%', top: 128 },
]

type Plate = { name: string; recipe_id: number; coverage: number; size: number; left: string; top: number; image_url?: string | null }

export default function MealPlan() {
  const nav = useNavigate()
  const [active, setActive] = useState(-1)
  const [spinning, setSpinning] = useState(false)
  const [toast, setToast] = useState('')
  const timer = useRef<number | undefined>(undefined)
  const { data: reco, isLoading, error } = useMealRecommend()
  const { data: cart } = useCart()

  useEffect(() => () => window.clearInterval(timer.current), [])

  const recs = reco?.recommendations ?? []
  // 냉장고 재료 기반 실 추천(#32)을 위치 슬롯에 얹기. 추천 없으면 빈 상태(mock 없음).
  const plates: Plate[] = recs.slice(0, POSITIONS.length).map((r, i) => ({
    name: r.name,
    recipe_id: r.recipe_id,
    coverage: r.coverage,
    size: POSITIONS[i].size,
    left: POSITIONS[i].left,
    top: POSITIONS[i].top,
    image_url: r.image_url,
  }))
  const hasPlates = plates.length > 0

  const openPlate = (pl: Plate) => nav('/recipes/' + pl.recipe_id)

  const spin = () => {
    if (spinning || !hasPlates) return
    setSpinning(true)
    setToast('')
    let i = 0
    let step = 60
    const total = 28 + Math.floor(Math.random() * plates.length)
    const tick = () => {
      setActive(i % plates.length)
      i++
      if (i >= total) {
        window.clearInterval(timer.current)
        const win = (i - 1) % plates.length
        setActive(win)
        setToast(`오늘은 「${plates[win].name}」 어때요?`)
        setSpinning(false)
        return
      }
      if (i > total - 8) {
        step += 40
        window.clearInterval(timer.current)
        timer.current = window.setInterval(tick, step)
      }
    }
    timer.current = window.setInterval(tick, step)
  }

  const cartCount = cart?.items.length ?? 0
  const cartSubtotal = cart?.subtotal ?? 0

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <div>
          <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>뭐 해먹지?</h1>
          <p style={{ fontSize: 13.5, color: '#5E5E5E', margin: '6px 0 0' }}>냉장고 재료로 만들 수 있는 추천이에요. 접시를 누르면 레시피가 열려요.</p>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <span style={{ padding: '7px 13px', fontSize: 12.5, fontWeight: 700, background: '#FDECEC', color: '#F04452' }}>임박 재료 우선</span>
          {hasPlates && <span style={{ padding: '7px 13px', fontSize: 12.5, fontWeight: 700, background: '#E7EFF8', color: '#1E5F96' }}>추천 {recs.length}개</span>}
        </div>
      </div>

      {isLoading && <div style={{ color: '#9A9A9A', fontSize: 13.5, padding: '8px 2px', marginBottom: 14 }}>냉장고 재료로 추천을 계산하는 중…</div>}
      {error && <div style={{ color: '#F04452', fontSize: 13.5, padding: '8px 2px', marginBottom: 14 }}>추천 서버에 연결할 수 없어요 ({(error as Error).message})</div>}

      {/* 추천 없음 → 냉장고 채우기 안내 (mock 없음) */}
      {!isLoading && !error && !hasPlates && (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14, background: '#F2ECE3', border: '1px solid #E6E6E6', padding: '56px 24px' }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#17264A' }}>아직 추천할 레시피가 없어요</div>
          <div style={{ fontSize: 13, color: '#5E5E5E', textAlign: 'center', maxWidth: 320, lineHeight: 1.6 }}>
            {reco?.note?.includes('unavailable')
              ? '냉장고 서비스에 연결되면 재료 기반으로 추천해요.'
              : '냉장고에 재료를 채우면 그 재료로 만들 수 있는 레시피를 임박 재료 우선으로 추천해요.'}
          </div>
          <button onClick={() => nav('/pantry')} style={{ padding: '13px 26px', border: 'none', background: '#F26419', color: '#fff', fontSize: 14, fontWeight: 800, cursor: 'pointer' }}>냉장고 채우기 →</button>
        </div>
      )}

      {/* 불규칙 접시 스캐터 */}
      {hasPlates && (
        <>
          <div style={{ position: 'relative', height: 700, background: '#F2ECE3', border: '1px solid #E6E6E6', overflow: 'hidden' }}>
            <span style={{ position: 'absolute', top: 20, left: 24, fontSize: 12.5, fontWeight: 700, color: '#A89B88', letterSpacing: '.5px', zIndex: 2 }}>오늘의 추천 {plates.length}접시 · 마음에 드는 걸 고르거나 룰렛으로 정해보세요</span>
            {plates.map((p, i) => {
              const on = active === i
              return (
                <div
                  key={p.recipe_id}
                  onClick={() => openPlate(p)}
                  style={{ position: 'absolute', left: p.left, top: p.top, width: p.size, textAlign: 'center', cursor: 'pointer', transition: 'transform .22s ease', transform: on ? 'scale(1.06)' : 'none', zIndex: on ? 6 : 1 }}
                >
                  <div
                    style={{
                      width: p.size,
                      height: p.size,
                      borderRadius: '50%',
                      background: `#EDE7DD center/cover no-repeat url("${p.image_url || img(p.recipe_id, 400)}")`,
                      border: '4px solid #fff',
                      transition: 'box-shadow .22s ease',
                      boxShadow: on
                        ? '0 0 0 4px #F26419, 0 26px 40px -10px rgba(60,48,36,.34)'
                        : '0 24px 38px -12px rgba(60,48,36,.30)',
                    }}
                  />
                  <div style={{ marginTop: 11, fontSize: 12.5, fontWeight: 700, color: '#17264A' }}>{p.name}</div>
                  <div className="num" style={{ marginTop: 2, fontSize: 11, fontWeight: 700, color: '#1E5F96' }}>재료 {Math.round(p.coverage * 100)}% 보유</div>
                </div>
              )
            })}
          </div>

          {/* 토스트 + 룰렛 버튼 (캔버스 밖) */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, marginTop: 18 }}>
            <div style={{ opacity: toast ? 1 : 0, transition: 'opacity .3s ease', fontSize: 13, fontWeight: 700, color: '#F26419', background: '#fff', border: '1px solid #F8D3B8', padding: '9px 16px', boxShadow: '0 6px 18px rgba(23,38,74,.10)', textAlign: 'center' }}>{toast || ' '}</div>
            <button onClick={spin} style={{ padding: '15px 32px', border: 'none', background: '#17264A', color: '#fff', fontSize: 15, fontWeight: 800, cursor: 'pointer', boxShadow: '0 10px 24px rgba(23,38,74,.24)' }}>
              룰렛으로 정하기
            </button>
          </div>
        </>
      )}

      {/* 장바구니 요약 (실데이터) */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginTop: 18, background: '#fff', border: '1px solid #E6E6E6', padding: '15px 20px', flexWrap: 'wrap' }}>
        <div style={{ fontSize: 13.5, color: '#5E5E5E' }}>
          장바구니 <b style={{ color: '#F26419' }}>{cartCount}</b>개 · 합계 <b className="num" style={{ color: '#17264A' }}>{won(cartSubtotal)}원</b>
        </div>
        <button onClick={() => nav('/cart')} style={{ padding: '12px 20px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13.5, fontWeight: 700, cursor: 'pointer' }}>장보기 목록 보기</button>
      </div>
    </div>
  )
}
