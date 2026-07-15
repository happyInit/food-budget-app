import { useNavigate } from 'react-router-dom'

const inp: React.CSSProperties = { width: '100%', margin: '6px 0 16px', padding: '11px 13px', border: '1.5px solid #E6E6E6', fontSize: 14, outline: 'none', boxSizing: 'border-box' }
const lab: React.CSSProperties = { fontSize: 12.5, fontWeight: 600, color: '#5E5E5E' }

export default function FridgeAdd() {
  const nav = useNavigate()
  return (
    <div>
      <div style={{ fontSize: 12.5, color: '#9A9A9A', marginBottom: 10 }}>
        <span style={{ cursor: 'pointer' }} onClick={() => nav('/pantry')}>내 냉장고</span> / 직접 추가
      </div>
      <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: '0 0 20px' }}>재료 직접 등록</h1>
      <div style={{ maxWidth: 520, background: '#fff', border: '1px solid #E6E6E6', padding: 24 }}>
        <label style={lab}>재료명</label>
        <input placeholder="예: 대파 (입력 시 표준 재료 자동완성)" style={inp} />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div>
            <label style={lab}>수량</label>
            <input defaultValue="1" style={inp} />
          </div>
          <div>
            <label style={lab}>단위</label>
            <input defaultValue="단" style={inp} />
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div>
            <label style={lab}>유통기한</label>
            <input defaultValue="2026-07-25" style={inp} />
          </div>
          <div>
            <label style={lab}>보관 위치</label>
            <input defaultValue="냉장" style={inp} />
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, marginTop: 6 }}>
          <button onClick={() => nav('/pantry')} style={{ flex: 1, padding: 12, border: '1.5px solid #E6E6E6', background: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer' }}>취소</button>
          <button onClick={() => nav('/pantry')} style={{ flex: 2, padding: 12, border: 'none', background: '#F26419', color: '#fff', fontSize: 14, fontWeight: 700, cursor: 'pointer' }}>저장</button>
        </div>
      </div>
    </div>
  )
}
