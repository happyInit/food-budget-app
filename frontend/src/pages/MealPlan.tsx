import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { platePlan, img } from '../lib/data'

export default function MealPlan() {
  const nav = useNavigate()
  const [active, setActive] = useState(-1)
  const [spinning, setSpinning] = useState(false)
  const [toast, setToast] = useState('')
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearInterval(timer.current), [])

  const spin = () => {
    if (spinning) return
    setSpinning(true)
    setToast('')
    let i = 0
    let step = 60
    const total = 28 + Math.floor(Math.random() * platePlan.length)
    const tick = () => {
      setActive(i % platePlan.length)
      i++
      if (i >= total) {
        window.clearInterval(timer.current)
        const win = (i - 1) % platePlan.length
        setActive(win)
        setToast(`오늘은 「${platePlan[win].name}」 어때요?`)
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

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <div>
          <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>뭐 해먹지?</h1>
          <p style={{ fontSize: 13.5, color: '#5E5E5E', margin: '6px 0 0' }}>냉장고 재료로 만들 수 있는 추천이에요. 접시를 누르면 레시피가 열려요.</p>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <span style={{ padding: '7px 13px', fontSize: 12.5, fontWeight: 700, background: '#FDECEC', color: '#F04452' }}>임박 재료 우선</span>
          <span className="num" style={{ padding: '7px 13px', fontSize: 12.5, fontWeight: 700, background: '#E7EFF8', color: '#1E5F96' }}>잔여 182,400원</span>
        </div>
      </div>

      <div style={{ background: '#F7F7F7', border: '1px solid #E6E6E6', padding: '22px 20px 34px' }}>
        <div style={{ fontSize: 12.5, fontWeight: 700, color: '#9A9A9A', letterSpacing: '.5px', marginBottom: 26 }}>오늘의 추천 8접시 · 마음에 드는 걸 고르거나 룰렛으로 정해보세요</div>

        {/* 겹치지 않는 접시 그리드 */}
        <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: '32px 30px', maxWidth: 720, margin: '0 auto' }}>
          {platePlan.map((p, i) => {
            const on = active === i
            return (
              <div key={p.name} onClick={() => nav('/recipes/1')} style={{ width: 132, textAlign: 'center', cursor: 'pointer', transition: 'transform .18s', transform: on ? 'scale(1.06)' : 'none' }}>
                <div
                  style={{
                    width: 132,
                    height: 132,
                    borderRadius: '50%',
                    background: '#fff',
                    display: 'grid',
                    placeItems: 'center',
                    transition: 'box-shadow .18s',
                    boxShadow: on ? '0 0 0 4px #F26419, 0 16px 34px rgba(23,38,74,.22)' : '0 8px 22px rgba(23,38,74,.13)',
                  }}
                >
                  <div style={{ width: 108, height: 108, borderRadius: '50%', background: `#F0F0F0 center/cover no-repeat url("${img(p.p, 300)}")` }} />
                </div>
                <div style={{ marginTop: 12, fontSize: 12.5, fontWeight: 700, color: '#17264A' }}>{p.name}</div>
              </div>
            )
          })}
        </div>

        {/* 토스트 + 룰렛 버튼 */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, marginTop: 34 }}>
          <div style={{ opacity: toast ? 1 : 0, transition: 'opacity .3s ease', fontSize: 13, fontWeight: 700, color: '#F26419', background: '#fff', padding: '9px 16px', boxShadow: '0 6px 18px rgba(23,38,74,.12)', textAlign: 'center' }}>{toast || ' '}</div>
          <button onClick={spin} style={{ padding: '15px 30px', border: 'none', background: '#17264A', color: '#fff', fontSize: 15, fontWeight: 800, cursor: 'pointer', boxShadow: '0 10px 24px rgba(23,38,74,.24)' }}>
            룰렛으로 정하기
          </button>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginTop: 16, background: '#fff', border: '1px solid #E6E6E6', padding: '15px 20px', flexWrap: 'wrap' }}>
        <div style={{ fontSize: 13.5, color: '#5E5E5E' }}>
          담은 레시피 <b style={{ color: '#F26419' }}>2</b> · 예상 추가비 <b style={{ color: '#17264A' }}>4,200원</b>
        </div>
        <button onClick={() => nav('/cart')} style={{ padding: '12px 20px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13.5, fontWeight: 700, cursor: 'pointer' }}>장보기 목록 만들기</button>
      </div>
    </div>
  )
}
