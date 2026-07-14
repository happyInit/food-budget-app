import { useNavigate } from 'react-router-dom'

const items = [
  { name: '돼지고기 목살 300g', price: '5,900원' },
  { name: '대파 3대', price: '1,250원' },
  { name: '고춧가루 100g', price: '3,200원' },
]

export default function Cart() {
  const nav = useNavigate()
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 18 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>장바구니</h1>
        <span style={{ fontSize: 13, color: '#9A9A9A' }}>부족 재료 3개 · 마켓컬리 기준가</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(320px,1fr))', gap: 16 }}>
        {/* 좌: 상품 목록 */}
        <div style={{ background: '#fff', border: '1px solid #E6E6E6', padding: 20 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 6px' }}>김치찌개 · 계란말이 재료</h3>
          {items.map((it) => (
            <div key={it.name} style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '14px 0', borderTop: '1px solid #EFEFEF' }}>
              <div style={{ width: 56, height: 56, background: '#E6F6EC', flexShrink: 0 }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 600 }}>{it.name}</div>
                <div style={{ fontSize: 11.5, color: '#9A9A9A', marginTop: 2 }}>
                  <b style={{ color: '#1FA463', fontWeight: 700 }}>새벽배송</b> · 내일 새벽 도착
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
                  <button style={{ width: 24, height: 24, border: '1px solid #E6E6E6', background: '#fff', cursor: 'pointer' }}>−</button>
                  <span style={{ fontSize: 13, fontWeight: 600, minWidth: 16, textAlign: 'center' }}>1</span>
                  <button style={{ width: 24, height: 24, border: '1px solid #E6E6E6', background: '#fff', cursor: 'pointer' }}>+</button>
                </div>
              </div>
              <div className="num" style={{ fontSize: 15, fontWeight: 700, whiteSpace: 'nowrap' }}>{it.price}</div>
            </div>
          ))}
        </div>
        {/* 우: 예산·결제 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ background: '#1FA463', color: '#fff', padding: 22 }}>
            <div style={{ fontSize: 13, opacity: 0.9 }}>이번 주 예산 잔여</div>
            <div className="num" style={{ fontSize: 27, fontWeight: 800, margin: '6px 0' }}>
              43,200원 <span style={{ fontSize: 14, opacity: 0.75 }}>/ 75,000원</span>
            </div>
            <div style={{ height: 8, background: 'rgba(255,255,255,.25)', overflow: 'hidden' }}>
              <div style={{ height: '100%', width: '42%', background: '#fff' }} />
            </div>
          </div>
          <div style={{ background: '#fff', border: '1px solid #E6E6E6', padding: 20 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14, marginBottom: 8 }}>
              <span style={{ color: '#5E5E5E' }}>상품 합계</span>
              <span className="num">10,350원</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14, marginBottom: 8 }}>
              <span style={{ color: '#5E5E5E' }}>냉장고 재료 절약</span>
              <span className="num" style={{ color: '#15B76E' }}>−6,150원</span>
            </div>
            <div style={{ height: 1, background: '#E6E6E6', margin: '12px 0' }} />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 16, fontWeight: 700 }}>
              <span>예상 결제</span>
              <span className="num" style={{ color: '#1FA463' }}>10,350원</span>
            </div>
          </div>
          <div style={{ background: '#E6F6EC', color: '#1FA463', fontSize: 12.5, padding: '12px 14px' }}>
            이 목록을 구매하면 주간 잔여 → <b>32,850원</b> (예산 내)
          </div>
          <button style={{ width: '100%', padding: 14, border: 'none', background: '#1FA463', color: '#fff', fontSize: 14, fontWeight: 700, cursor: 'pointer' }}>장보기 목록으로 저장</button>
          <button onClick={() => nav('/ocr')} style={{ width: '100%', padding: 12, border: '1.5px solid #E6E6E6', background: '#fff', color: '#5E5E5E', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>구매 완료 → 영수증 등록</button>
        </div>
      </div>
    </div>
  )
}
