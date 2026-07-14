import { useNavigate } from 'react-router-dom'

export default function Assistant() {
  const nav = useNavigate()
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18 }}>
        <img src="/icons/pug.png" alt="파그" style={{ width: 40, height: 40, borderRadius: '50%', objectFit: 'cover', border: '1px solid #E6E6E6' }} />
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>파그 · 식비 어시스턴트</h1>
        <span style={{ padding: '3px 9px', fontSize: 11, fontWeight: 700, background: '#FCEBDD', color: '#F26419' }}>P1</span>
      </div>
      <div style={{ maxWidth: 680, background: '#fff', border: '1px solid #E6E6E6', overflow: 'hidden', display: 'flex', flexDirection: 'column', height: 560 }}>
        <div style={{ flex: 1, padding: 20, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ alignSelf: 'flex-end', maxWidth: '75%', background: '#F26419', color: '#fff', padding: '11px 15px', borderRadius: '0 14px 4px 14px', fontSize: 13.5, lineHeight: 1.5 }}>냉장고에 있는 재료로 3천원 안에 뭐 해먹지?</div>
          <div style={{ alignSelf: 'flex-start', maxWidth: '80%', background: '#F7F7F7', padding: '11px 15px', borderRadius: '0 14px 14px 4px', fontSize: 13.5, lineHeight: 1.6 }}>두부(D-1)가 곧 만료돼요! 보유 재료로 만들 수 있는 <b>두부김치</b>를 추천해요. 추가로 필요한 건 대파(1,250원)뿐이라 예산 안에 충분해요.</div>
          <div style={{ alignSelf: 'flex-start', maxWidth: '80%', background: '#fff', border: '1px solid #E6E6E6', padding: 12, display: 'flex', gap: 12, alignItems: 'center' }}>
            <div style={{ width: 48, height: 48, background: '#EFEFEF', flexShrink: 0 }} />
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13.5, fontWeight: 700 }}>두부김치</div>
              <div style={{ fontSize: 11.5, color: '#9A9A9A' }}>재료 90% 보유 · 추가 1,250원</div>
            </div>
            <button onClick={() => nav('/recipes/1')} style={{ padding: '7px 12px', border: 'none', background: '#F26419', color: '#fff', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>보기</button>
          </div>
          <div style={{ alignSelf: 'flex-end', maxWidth: '75%', background: '#F26419', color: '#fff', padding: '11px 15px', borderRadius: '0 14px 4px 14px', fontSize: 13.5, lineHeight: 1.5 }}>좋아, 장바구니에 담아줘</div>
          <div style={{ alignSelf: 'flex-start', maxWidth: '80%', background: '#F7F7F7', padding: '11px 15px', borderRadius: '0 14px 14px 4px', fontSize: 13.5, lineHeight: 1.6 }}>대파 1대를 장바구니에 담았어요. 이번 주 예산 잔여는 41,950원이 됩니다.</div>
        </div>
        <div style={{ borderTop: '1px solid #E6E6E6', padding: '12px 16px', display: 'flex', gap: 10 }}>
          <input placeholder="무엇이든 물어보세요…" style={{ flex: 1, padding: '11px 14px', border: '1.5px solid #E6E6E6', fontSize: 13.5, outline: 'none', minWidth: 0 }} />
          <button style={{ width: 42, height: 42, border: 'none', borderRadius: '50%', background: '#F26419', color: '#fff', fontSize: 16, cursor: 'pointer' }}>↑</button>
        </div>
      </div>
    </div>
  )
}
